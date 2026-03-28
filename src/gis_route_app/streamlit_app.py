"""Streamlit dashboard for nearby map and route intersection analysis."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from gis_route_app.config import get_settings
from gis_route_app.models import Coordinate, RouteAnalysisResponse, RouteRequest, TravelMode
from gis_route_app.routing import RoutingError
from gis_route_app.service import RouteIntersectionService

NEAR_ME_URL = (
    "https://www.arcgis.com/apps/instant/nearbybeta/index.html"
    "?appid=3990cecc7b0d42079d60b9aa3ad725e5&locale=en"
)
_GEOD = Geod(ellps="WGS84")
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODER_USER_AGENT = "gis-route-intersection-dashboard/0.1"
_METERS_PER_MILE = 1609.344


class GeocodingError(RuntimeError):
    """Raised when address geocoding fails."""


def _meters_to_miles(distance_m: float) -> float:
    return distance_m / _METERS_PER_MILE


def _autocomplete_addresses(
    query: str,
    timeout_seconds: int,
    limit: int = 5,
) -> list[str]:
    normalized_query = query.strip()
    if len(normalized_query) < 3:
        return []
    try:
        response = requests.get(
            _NOMINATIM_URL,
            params={"q": normalized_query, "format": "jsonv2", "limit": limit},
            headers={"User-Agent": _GEOCODER_USER_AGENT},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return []

    suggestions: list[str] = []
    for item in payload:
        display_name = item.get("display_name")
        if isinstance(display_name, str) and display_name not in suggestions:
            suggestions.append(display_name)
    return suggestions


def _geometry_length_m(geometry: BaseGeometry) -> float:
    if geometry.is_empty:
        return 0.0
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
        if len(coords) < 2:
            return 0.0
        lons = [coord[0] for coord in coords]
        lats = [coord[1] for coord in coords]
        return float(_GEOD.line_length(lons, lats))
    if isinstance(geometry, MultiLineString):
        return float(sum(_geometry_length_m(line) for line in geometry.geoms))
    if isinstance(geometry, GeometryCollection):
        return float(sum(_geometry_length_m(geom) for geom in geometry.geoms))
    if geometry.geom_type in {"Polygon", "MultiPolygon", "Point", "MultiPoint"}:
        return _geometry_length_m(geometry.boundary)
    return float(geometry.length)


def _build_percentage_series(
    result: RouteAnalysisResponse,
    service: RouteIntersectionService,
) -> pd.DataFrame:
    route_geom = shape(result.route.geojson["geometry"])
    route_distance_m = _geometry_length_m(route_geom)
    if route_distance_m <= 0:
        return pd.DataFrame(
            {
                "Category": ["HIN overlap", "CIP overlap", "No overlap"],
                "Percent": [0.0, 0.0, 100.0],
            }
        )

    hin_union = unary_union(
        [feature.geometry for feature in service.analysis_engine.hin_features]
    )
    cip_union = unary_union(
        [feature.geometry for feature in service.analysis_engine.cip_features]
    )

    hin_only = route_geom.intersection(hin_union).difference(cip_union)
    cip_only = route_geom.intersection(cip_union).difference(hin_union)
    none_overlap = route_geom.difference(hin_union.union(cip_union))

    hin_pct = (_geometry_length_m(hin_only) / route_distance_m) * 100.0
    cip_pct = (_geometry_length_m(cip_only) / route_distance_m) * 100.0
    none_pct = (_geometry_length_m(none_overlap) / route_distance_m) * 100.0

    return pd.DataFrame(
        {
            "Category": ["HIN overlap", "CIP overlap", "No overlap"],
            "Percent": [max(hin_pct, 0.0), max(cip_pct, 0.0), max(none_pct, 0.0)],
        }
    )


def _extract_paths_from_geometry(geometry: BaseGeometry) -> list[list[list[float]]]:
    """Extract path arrays from line-based geometries for map rendering."""
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [[[float(lon), float(lat)] for lon, lat in geometry.coords]]
    if isinstance(geometry, MultiLineString):
        return [
            [[float(lon), float(lat)] for lon, lat in line.coords]
            for line in geometry.geoms
        ]
    if isinstance(geometry, GeometryCollection):
        paths: list[list[list[float]]] = []
        for geom in geometry.geoms:
            paths.extend(_extract_paths_from_geometry(geom))
        return paths
    return _extract_paths_from_geometry(geometry.boundary)


def _render_route_map(result: RouteAnalysisResponse, request: RouteRequest) -> None:
    route_geom = shape(result.route.geojson["geometry"])
    paths = _extract_paths_from_geometry(route_geom)
    if not paths:
        st.warning("Route geometry could not be rendered on the map.")
        return

    route_data = [{"name": "Route", "path": path} for path in paths]
    marker_data = [
        {
            "name": "Start",
            "coordinates": [request.start.lon, request.start.lat],
            "color": [34, 139, 34],
        },
        {
            "name": "End",
            "coordinates": [request.end.lon, request.end.lat],
            "color": [220, 20, 60],
        },
    ]

    center_lon = (request.start.lon + request.end.lon) / 2.0
    center_lat = (request.start.lat + request.end.lat) / 2.0

    deck = pdk.Deck(
        initial_view_state=pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=13,
            pitch=0,
        ),
        layers=[
            pdk.Layer(
                "PathLayer",
                route_data,
                get_path="path",
                get_color=[0, 112, 192],
                width_scale=20,
                width_min_pixels=3,
                pickable=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                marker_data,
                get_position="coordinates",
                get_fill_color="color",
                get_radius=35,
                pickable=True,
            ),
        ],
        tooltip={"text": "{name}"},
        map_style="light",
    )
    st.pydeck_chart(deck, use_container_width=True)


def _geocode_address(address: str, timeout_seconds: int) -> Coordinate:
    query = address.strip()
    if not query:
        raise GeocodingError("Address cannot be empty.")
    try:
        response = requests.get(
            _NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": _GEOCODER_USER_AGENT},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding request failed for '{query}': {exc}") from exc

    if not payload:
        raise GeocodingError(f"No location found for address: '{query}'.")

    first = payload[0]
    try:
        return Coordinate(lon=float(first["lon"]), lat=float(first["lat"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError(f"Unexpected geocoding response for '{query}'.") from exc


def _resolve_selected_address(typed_value: str, selected_option: str) -> str:
    if selected_option.startswith("Use typed address"):
        return typed_value
    return selected_option


def _render_route_tab() -> None:
    st.subheader("GIS Route Intersection Analysis")
    st.caption("Set start/end addresses and evaluate route overlap with HIN/CIP datasets.")

    settings = get_settings()
    with st.expander("Data source settings", expanded=False):
        st.write("Current defaults loaded from environment:")
        st.code(
            f"HIN_DATA_SOURCE={settings.hin_data_source}\n"
            f"CIP_DATA_SOURCE={settings.cip_data_source}",
            language="text",
        )

    c1, c2 = st.columns(2)
    with c1:
        start_address = st.text_input(
            "Start address",
            value="1 Market St, San Francisco, CA",
        )
        start_suggestions = _autocomplete_addresses(
            start_address,
            timeout_seconds=settings.request_timeout_seconds,
        )
        start_selection = st.selectbox(
            "Start address suggestions",
            options=[f"Use typed address: {start_address}"] + start_suggestions,
            help="Type at least 3 characters to get autocomplete suggestions.",
        )
        mode = st.selectbox("Travel mode", [m.value for m in TravelMode], index=0)

    with c2:
        end_address = st.text_input(
            "End address",
            value="Ferry Building, San Francisco, CA",
        )
        end_suggestions = _autocomplete_addresses(
            end_address,
            timeout_seconds=settings.request_timeout_seconds,
        )
        end_selection = st.selectbox(
            "End address suggestions",
            options=[f"Use typed address: {end_address}"] + end_suggestions,
            help="Type at least 3 characters to get autocomplete suggestions.",
        )
        provider = st.selectbox(
            "Routing provider",
            options=["mock", "ors"],
            index=0 if settings.routing_provider != "ors" else 1,
        )

    submitted = st.button("Analyze route")

    if not submitted:
        st.info("Enter start/end addresses, choose suggestions if desired, then run analysis.")
        return

    settings = replace(settings, routing_provider=provider)

    try:
        selected_start = _resolve_selected_address(start_address, start_selection)
        selected_end = _resolve_selected_address(end_address, end_selection)
        start_coord = _geocode_address(selected_start, settings.request_timeout_seconds)
        end_coord = _geocode_address(selected_end, settings.request_timeout_seconds)
        service = RouteIntersectionService.from_settings(settings)
        request = RouteRequest(
            start=start_coord,
            end=end_coord,
            mode=TravelMode(mode),
        )
        result = service.analyze(request)
    except (GeocodingError, RoutingError, ValueError, FileNotFoundError) as exc:
        st.error(f"Could not analyze route: {exc}")
        return

    route_miles = _meters_to_miles(result.route.distance_m)
    duration_min = result.route.duration_s / 60.0
    pct_frame = _build_percentage_series(result, service)
    by_category = {row["Category"]: row["Percent"] for _, row in pct_frame.iterrows()}

    m1, m2, m3 = st.columns(3)
    m1.metric("Route distance", f"{route_miles:.2f} mi")
    m2.metric("Travel duration", f"{duration_min:.1f} min")
    m3.metric("Intersections found", str(len(result.intersections)))
    st.caption(
        f"Resolved start: ({request.start.lat:.6f}, {request.start.lon:.6f}) | "
        f"end: ({request.end.lat:.6f}, {request.end.lon:.6f})"
    )
    st.caption(
        "Coverage split: "
        f"HIN {by_category['HIN overlap']:.1f}% | "
        f"CIP {by_category['CIP overlap']:.1f}% | "
        f"No overlap {by_category['No overlap']:.1f}%"
    )

    st.markdown("#### Route map")
    _render_route_map(result, request)

    st.markdown("#### Route overlap percentages")
    st.line_chart(pct_frame.set_index("Category"))

    st.markdown("#### Overlap details")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "dataset": i.dataset,
                    "feature_id": i.feature_id,
                    "overlap_length_mi": round(_meters_to_miles(i.overlap_length_m), 3),
                    "overlap_fraction_of_route": round(i.overlap_fraction_of_route, 6),
                }
                for i in result.intersections
            ]
        ),
        use_container_width=True,
    )


def main() -> None:
    """Run Streamlit dashboard."""
    st.set_page_config(page_title="GIS Route Dashboard", layout="wide")
    st.title("CIP + HIN GIS Dashboard")

    near_me_tab, route_tab = st.tabs(["Near me", "Route intersection"])

    with near_me_tab:
        st.subheader("Near me")
        components.iframe(NEAR_ME_URL, height=900, scrolling=True)

    with route_tab:
        _render_route_tab()


if __name__ == "__main__":
    main()

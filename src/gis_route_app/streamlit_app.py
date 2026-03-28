"""Streamlit dashboard for nearby map and route intersection analysis."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pydeck as pdk
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


def _render_route_tab() -> None:
    st.subheader("GIS Route Intersection Analysis")
    st.caption("Set start/end coordinates and evaluate route overlap with HIN/CIP datasets.")

    settings = get_settings()
    with st.expander("Data source settings", expanded=False):
        st.write("Current defaults loaded from environment:")
        st.code(
            f"HIN_DATA_SOURCE={settings.hin_data_source}\n"
            f"CIP_DATA_SOURCE={settings.cip_data_source}",
            language="text",
        )

    with st.form("route-form"):
        c1, c2 = st.columns(2)
        with c1:
            start_lon = st.number_input("Start longitude", value=-122.431, format="%.6f")
            start_lat = st.number_input("Start latitude", value=37.772, format="%.6f")
            mode = st.selectbox("Travel mode", [m.value for m in TravelMode], index=0)
        with c2:
            end_lon = st.number_input("End longitude", value=-122.421, format="%.6f")
            end_lat = st.number_input("End latitude", value=37.772, format="%.6f")
            provider = st.selectbox(
                "Routing provider",
                options=["mock", "ors"],
                index=0 if settings.routing_provider != "ors" else 1,
            )
        submitted = st.form_submit_button("Analyze route")

    if not submitted:
        st.info("Submit the form to run route analysis.")
        return

    settings = replace(settings, routing_provider=provider)

    try:
        service = RouteIntersectionService.from_settings(settings)
        request = RouteRequest(
            start=Coordinate(lon=float(start_lon), lat=float(start_lat)),
            end=Coordinate(lon=float(end_lon), lat=float(end_lat)),
            mode=TravelMode(mode),
        )
        result = service.analyze(request)
    except (RoutingError, ValueError, FileNotFoundError) as exc:
        st.error(f"Could not analyze route: {exc}")
        return

    route_km = result.route.distance_m / 1000.0
    duration_min = result.route.duration_s / 60.0
    pct_frame = _build_percentage_series(result, service)
    by_category = {row["Category"]: row["Percent"] for _, row in pct_frame.iterrows()}

    m1, m2, m3 = st.columns(3)
    m1.metric("Route distance", f"{route_km:.2f} km")
    m2.metric("Travel duration", f"{duration_min:.1f} min")
    m3.metric("Intersections found", str(len(result.intersections)))
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
                    "overlap_length_m": round(i.overlap_length_m, 3),
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

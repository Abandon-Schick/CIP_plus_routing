"""Streamlit dashboard for nearby map and route intersection analysis."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    mapping,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from gis_route_app.config import get_settings
from gis_route_app.models import (
    Coordinate,
    RouteAnalysisResponse,
    RouteRequest,
    SegmentIntersection,
    TravelMode,
)
from gis_route_app.route_partition import (
    bucket_corridors,
    bucket_route_paths,
    extract_line_geometries,
    geometry_length_m,
    line_metric_overlap_intervals,
    priority_spans_on_line,
)
from gis_route_app.routing import RoutingError
from gis_route_app.service import RouteIntersectionService, get_cached_service, refresh_cached_service
from gis_route_app.summary import (
    BUCKET_COLOR_HEX,
    BUCKET_DISPLAY_ORDER,
    BUCKET_LABEL,
    BUCKET_ORDER,
    cip_detail,
    cip_fields,
    hin_detail,
    hin_fields,
)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODER_USER_AGENT = "gis-route-intersection-dashboard/0.1"
_DEFAULT_START_ADDRESS = "700 East Main Street, Richmond, VA"
_DEFAULT_END_ADDRESS = "1200 Semmes Avenue, Richmond, VA"
# RGBA form of the shared bucket colors, for pydeck layers.
_BUCKET_COLOR_RGBA: dict[str, list[int]] = {
    key: [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)] + [255]
    for key, hex_color in BUCKET_COLOR_HEX.items()
}


class GeocodingError(RuntimeError):
    """Raised when address geocoding fails."""


_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _parse_completion_year(value: object) -> int | None:
    if value is None:
        return None
    match = _YEAR_RE.search(str(value))
    return int(match.group()) if match else None


def _latest_completion_year(result: RouteAnalysisResponse) -> int | None:
    years = [
        year
        for i in result.intersections
        if i.dataset == "cip"
        and (year := _parse_completion_year(i.properties.get("Completion"))) is not None
    ]
    return max(years) if years else None


def _build_bucket_percentage_series(
    result: RouteAnalysisResponse,
    service: RouteIntersectionService,
) -> pd.DataFrame:
    """Mutually-exclusive route-length percentage per citizen-facing bucket.

    When corridors overlap (e.g. a High Injury Network street that's also under
    construction), the higher-priority bucket in ``BUCKET_ORDER`` wins so the
    percentages sum to the total "may change" figure without double-counting.
    """
    route_geom = shape(result.route.geojson["geometry"])
    route_distance_m = geometry_length_m(route_geom)
    if route_distance_m <= 0:
        rows = [{"Bucket": label, "Percent": 0.0} for _, label in BUCKET_ORDER]
        rows.append({"Bucket": "Unaffected", "Percent": 100.0})
        return pd.DataFrame(rows)

    corridors = bucket_corridors(service.analysis_engine, route_geom)
    remaining = route_geom
    rows = []
    for key, label in BUCKET_ORDER:
        this_geom = remaining.intersection(corridors[key])
        pct = (geometry_length_m(this_geom) / route_distance_m) * 100.0
        rows.append({"Bucket": label, "Percent": max(pct, 0.0)})
        remaining = remaining.difference(corridors[key])

    unaffected_pct = (geometry_length_m(remaining) / route_distance_m) * 100.0
    rows.append({"Bucket": "Unaffected", "Percent": max(unaffected_pct, 0.0)})
    return pd.DataFrame(rows)


def _format_age(age: timedelta) -> str:
    total_seconds = max(0, int(age.total_seconds()))
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h"
    return f"{total_seconds // 86400}d"


def _build_cip_overlap_details_frame(result: RouteAnalysisResponse) -> pd.DataFrame:
    columns = [
        "Overlap Percent",
        "Name",
        "Bucket",
        "Category",
        "Description",
        "Cost",
        "Phase",
        "Status",
        "Completion",
    ]
    rows = []
    for intersection in result.intersections:
        if intersection.dataset != "cip":
            continue
        fields = cip_fields(intersection.properties, intersection.feature_id)
        rows.append(
            {
                "Overlap Percent": round(intersection.overlap_fraction_of_route * 100.0, 2),
                "Name": fields["name"],
                "Bucket": BUCKET_LABEL.get(
                    intersection.properties.get("cip_bucket", "planned"), "Planned changes"
                ),
                "Category": fields["category"],
                "Description": fields["description"],
                "Cost": fields["cost"],
                "Phase": fields["phase"],
                "Status": fields["status"],
                "Completion": fields["completion"],
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        by=["Overlap Percent", "Name"],
        ascending=[False, True],
    )


def _build_hin_overlap_details_frame(result: RouteAnalysisResponse) -> pd.DataFrame:
    columns = [
        "Overlap Percent",
        "Name",
        "Street Type",
        "Functional",
        "Posted Speed",
    ]
    rows = []
    for intersection in result.intersections:
        if intersection.dataset != "hin":
            continue
        fields = hin_fields(intersection.properties, intersection.feature_id)
        rows.append(
            {
                "Overlap Percent": round(intersection.overlap_fraction_of_route * 100.0, 2),
                "Name": fields["name"],
                "Street Type": fields["street_type"],
                "Functional": fields["functional"],
                "Posted Speed": fields["posted_speed"],
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        by=["Overlap Percent", "Name"],
        ascending=[False, True],
    )


def _build_line_overlap_intervals(
    route_line: LineString,
    overlap_union: BaseGeometry,
) -> list[tuple[float, float]]:
    return line_metric_overlap_intervals(route_line, overlap_union)


def _build_route_overlap_blocks(
    route_geom: BaseGeometry,
    overlap_union: BaseGeometry,
) -> list[dict[str, float | str]]:
    route_lines = extract_line_geometries(route_geom)
    total_length_m = float(sum(geometry_length_m(line) for line in route_lines))
    if total_length_m <= 0:
        return [{"segment": "no_overlap", "fraction": 1.0}]

    blocks: list[dict[str, float | str]] = []
    for line in route_lines:
        line_length_m = geometry_length_m(line)
        if line_length_m <= 0:
            continue
        overlap_intervals = _build_line_overlap_intervals(line, overlap_union)
        cursor_n = 0.0
        for lo_n, hi_n in overlap_intervals:
            lo_n = max(0.0, min(lo_n, 1.0))
            hi_n = max(0.0, min(hi_n, 1.0))
            if hi_n <= lo_n:
                continue
            if lo_n > cursor_n:
                gap = substring(line, cursor_n, lo_n, normalized=True)
                blocks.append({"segment": "no_overlap", "length_m": geometry_length_m(gap)})
            ov = substring(line, lo_n, hi_n, normalized=True)
            blocks.append({"segment": "overlap", "length_m": geometry_length_m(ov)})
            cursor_n = hi_n
        if cursor_n < 1.0:
            tail = substring(line, cursor_n, 1.0, normalized=True)
            blocks.append({"segment": "no_overlap", "length_m": geometry_length_m(tail)})

    if not blocks:
        return [{"segment": "no_overlap", "fraction": 1.0}]

    merged: list[dict[str, float | str]] = []
    for block in blocks:
        length_m = float(block["length_m"])
        if length_m <= 0:
            continue
        if merged and merged[-1]["segment"] == block["segment"]:
            merged[-1]["length_m"] = float(merged[-1]["length_m"]) + length_m
            continue
        merged.append({"segment": block["segment"], "length_m": length_m})

    output: list[dict[str, float | str]] = []
    for block in merged:
        output.append(
            {
                "segment": str(block["segment"]),
                "fraction": float(block["length_m"]) / total_length_m,
            }
        )
    return output


def _route_path_rows_colored(
    route_geom: BaseGeometry,
    corridors: dict[str, BaseGeometry],
) -> list[dict[str, object]]:
    """PathLayer rows: path (lon/lat) + RGBA color + name (for the map tooltip).

    "name" mirrors the bucket label since a given stretch of route can sit within
    more than one project's buffer at once -- the bucket is the one fact about that
    stretch guaranteed to be unambiguous.
    """
    return [
        {
            "path": path,
            "color": _BUCKET_COLOR_RGBA[tag],
            "name": BUCKET_LABEL.get(tag, "Unaffected"),
        }
        for tag, path in bucket_route_paths(route_geom, corridors)
    ]


def _merge_adjacent_segment_lengths(
    pieces: list[tuple[float, str]],
) -> list[tuple[float, str]]:
    if not pieces:
        return []
    out: list[tuple[float, str]] = [pieces[0]]
    for length_m, seg in pieces[1:]:
        if length_m <= 0:
            continue
        prev_len, prev_seg = out[-1]
        if seg == prev_seg:
            out[-1] = (prev_len + length_m, prev_seg)
        else:
            out.append((length_m, seg))
    return out


def _build_bucket_route_overlap_blocks(
    route_geom: BaseGeometry,
    corridors: dict[str, BaseGeometry],
) -> list[dict[str, float | str]]:
    """Partition the route into ordered bucket segments + "unaffected" gaps (matches map colors)."""
    route_lines = extract_line_geometries(route_geom)
    total_length_m = float(sum(geometry_length_m(line) for line in route_lines))
    if total_length_m <= 0:
        return [{"segment": "unaffected", "fraction": 1.0}]

    tagged_corridors = [(key, corridors[key]) for key, _ in BUCKET_ORDER]
    raw_pieces: list[tuple[float, str]] = []
    tol = 1e-6
    for line in route_lines:
        merged_line: list[tuple[float, str]] = []
        for lo, hi, seg in priority_spans_on_line(line, tagged_corridors):
            span = substring(line, lo, hi, normalized=True)
            length = geometry_length_m(span)
            if length <= tol:
                continue
            if merged_line and merged_line[-1][1] == seg:
                merged_line[-1] = (merged_line[-1][0] + length, seg)
            else:
                merged_line.append((length, seg))
        raw_pieces.extend(merged_line)

    merged_global = _merge_adjacent_segment_lengths(raw_pieces)
    if not merged_global:
        return [{"segment": "unaffected", "fraction": 1.0}]
    return [
        {"segment": seg, "fraction": length_m / total_length_m}
        for length_m, seg in merged_global
        if length_m > tol
    ]


def _build_route_overlap_segments(
    result: RouteAnalysisResponse,
    overlap_geometries: list[dict[str, object]],
) -> pd.DataFrame:
    route_geom = shape(result.route.geojson["geometry"])
    overlap_shapes = [shape(feature["geometry"]) for feature in overlap_geometries]
    overlap_union = unary_union(overlap_shapes) if overlap_shapes else GeometryCollection()
    blocks = _build_route_overlap_blocks(route_geom, overlap_union)
    return pd.DataFrame(
        {
            "segment_type": [
                "Overlap" if str(block["segment"]) == "overlap" else "No overlap"
                for block in blocks
            ],
            "percent": [float(block["fraction"]) * 100.0 for block in blocks],
        }
    )


def _render_route_overlap_bar(
    route_geom: BaseGeometry,
    service: RouteIntersectionService,
) -> None:
    corridors = bucket_corridors(service.analysis_engine, route_geom)
    blocks = _build_bucket_route_overlap_blocks(route_geom, corridors)

    segment_html = "".join(
        (
            f"<div style='height:100%; width:{max(float(block['fraction']) * 100.0, 0.0):.6f}%; "
            f"background:{BUCKET_COLOR_HEX[str(block['segment'])]};'></div>"
        )
        for block in blocks
    )

    legend_items = "".join(
        (
            "<span><span style='display:inline-block; width:12px; height:12px; "
            f"background:{BUCKET_COLOR_HEX[key]}; margin-right:6px; border:1px solid #999;'></span>"
            f"{label}</span>"
        )
        for key, label in BUCKET_ORDER
    )
    legend_items += (
        "<span><span style='display:inline-block; width:12px; height:12px; "
        f"background:{BUCKET_COLOR_HEX['unaffected']}; margin-right:6px; border:1px solid #999;'></span>"
        "Unaffected</span>"
    )

    st.markdown(
        (
            "<div style='width:100%;'>"
            "<div style='width:100%; height:30px; display:flex; border-radius:4px; "
            "overflow:hidden; border:1px solid #a6a6a6;'>"
            f"{segment_html}"
            "</div>"
            "<div style='display:flex; justify-content:space-between; margin-top:4px; "
            "font-size:0.85rem;'>"
            "<span>Route start</span><span>Route end</span>"
            "</div>"
            "<div style='display:flex; flex-wrap:wrap; gap:12px 18px; margin-top:8px; "
            "font-size:0.85rem;'>"
            f"{legend_items}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_bucket_section_header(key: str, label: str, pct: float) -> None:
    """Colored-dot stat card, doubling as the heading for that bucket's project list."""
    st.markdown(
        (
            "<p style='display:flex; align-items:center; gap:6px; font-size:0.85rem; "
            "color:#6b7280; margin:0;'>"
            "<span style='width:8px; height:8px; border-radius:50%; "
            f"background:{BUCKET_COLOR_HEX[key]}; display:inline-block;'></span>"
            f"{label}</p>"
            f"<p style='font-size:1.75rem; font-weight:600; margin:2px 0 0.5rem;'>{pct:.0f}%</p>"
        ),
        unsafe_allow_html=True,
    )


def _aggregate_hin_by_street(hin_frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse individual HIN segments into one row per street name, summing overlap.

    A single named street can be split into dozens of tiny segments in the source
    data (e.g. 24 separate "E Main St" rows for one route) -- listing each
    individually under "High risk" would bury the signal in near-duplicate rows.
    """
    if hin_frame.empty:
        return hin_frame
    agg = hin_frame.groupby("Name", as_index=False).agg(
        {
            "Overlap Percent": "sum",
            "Street Type": "first",
            "Functional": "first",
            "Posted Speed": "first",
        }
    )
    return agg.sort_values(by=["Overlap Percent", "Name"], ascending=[False, True])


def _render_bucket_sections(
    bucket_pct: dict[str, float],
    cip_details_frame: pd.DataFrame,
    hin_street_frame: pd.DataFrame,
) -> None:
    """One section per bucket, in reading order: header card, then its project list."""
    for key, label in BUCKET_DISPLAY_ORDER:
        _render_bucket_section_header(key, label, bucket_pct[label])
        if key == "high_risk":
            rows = hin_street_frame
            if rows.empty:
                st.caption("No high risk streets along this route.")
            for _, row in rows.iterrows():
                detail = hin_detail(row["Street Type"], row["Functional"], row["Posted Speed"])
                st.markdown(f"**{row['Name']}**" + (f"  \n{detail}" if detail else ""))
        else:
            rows = cip_details_frame[cip_details_frame["Bucket"] == label]
            if rows.empty:
                st.caption("No projects in this bucket along this route.")
            for _, row in rows.iterrows():
                detail = cip_detail(row["Category"], row["Cost"], row["Completion"])
                st.markdown(f"**{row['Name']}**" + (f"  \n{detail}" if detail else ""))
        st.markdown("")


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


def _intersecting_bucket_geojson(
    service: RouteIntersectionService,
    intersections: list[SegmentIntersection],
) -> dict[str, dict[str, object]]:
    """Bucket key -> FeatureCollection of intersecting features, for map overlay layers."""
    seen: set[tuple[str, str]] = set()
    by_bucket: dict[str, list[dict[str, object]]] = {key: [] for key, _ in BUCKET_ORDER}
    hin_by_id = {f.feature_id: f for f in service.analysis_engine.hin_features}
    cip_by_id = {f.feature_id: f for f in service.analysis_engine.cip_features}

    for inter in intersections:
        key = (inter.dataset, inter.feature_id)
        if key in seen:
            continue
        seen.add(key)
        if inter.dataset == "hin":
            dataset_feat = hin_by_id.get(inter.feature_id)
            bucket = "high_risk"
            name = hin_fields(inter.properties, inter.feature_id)["name"]
        else:
            dataset_feat = cip_by_id.get(inter.feature_id)
            bucket = inter.properties.get("cip_bucket", "planned")
            name = cip_fields(inter.properties, inter.feature_id)["name"]
        if dataset_feat is None:
            continue
        by_bucket.setdefault(bucket, []).append(
            {
                "type": "Feature",
                "geometry": mapping(dataset_feat.geometry),
                "properties": {**dataset_feat.properties, "name": name},
            }
        )

    return {
        key: {"type": "FeatureCollection", "features": features}
        for key, features in by_bucket.items()
        if features
    }


def _render_route_map(
    result: RouteAnalysisResponse,
    request: RouteRequest,
    service: RouteIntersectionService,
) -> None:
    route_geom = shape(result.route.geojson["geometry"])
    paths = _extract_paths_from_geometry(route_geom)
    if not paths:
        st.warning("Route geometry could not be rendered on the map.")
        return

    corridors = bucket_corridors(service.analysis_engine, route_geom)
    route_path_rows = _route_path_rows_colored(route_geom, corridors)
    if not route_path_rows:
        route_path_rows = [
            {"path": path, "color": _BUCKET_COLOR_RGBA["unaffected"], "name": "Unaffected"}
            for path in paths
        ]
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

    bucket_geojson = _intersecting_bucket_geojson(service, result.intersections)
    layers: list[pdk.Layer] = []
    for key, _ in BUCKET_ORDER:
        fc = bucket_geojson.get(key)
        if fc is None:
            continue
        r, g, b, _a = _BUCKET_COLOR_RGBA[key]
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                fc,
                stroked=True,
                filled=True,
                get_fill_color=[r, g, b, 90],
                get_line_color=[r, g, b, 255],
                line_width_min_pixels=2,
                pickable=True,
            )
        )
    layers.extend(
        [
            pdk.Layer(
                "PathLayer",
                route_path_rows,
                get_path="path",
                get_color="color",
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
        ]
    )

    deck = pdk.Deck(
        initial_view_state=pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=13,
            pitch=0,
        ),
        layers=layers,
        tooltip={"text": "{name}"},
        map_style="light",
    )
    st.pydeck_chart(deck, width="stretch")


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
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding request failed for '{query}': {exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise GeocodingError(f"Geocoding response was not valid JSON for '{query}'.") from exc

    if not isinstance(payload, list):
        raise GeocodingError(f"Unexpected geocoding response for '{query}'.")
    if not payload:
        raise GeocodingError(f"No location found for address: '{query}'.")

    first = payload[0]
    if not isinstance(first, dict):
        raise GeocodingError(f"Unexpected geocoding response for '{query}'.")
    try:
        return Coordinate(lon=float(first["lon"]), lat=float(first["lat"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError(f"Unexpected geocoding response for '{query}'.") from exc


def _render_route_tab() -> None:
    settings = get_settings()
    with st.expander("Set route", expanded=True):
        st.caption("Set start/end addresses and see what's changing along your route.")

        if "start_address_input" not in st.session_state:
            st.session_state["start_address_input"] = _DEFAULT_START_ADDRESS
        if "end_address_input" not in st.session_state:
            st.session_state["end_address_input"] = _DEFAULT_END_ADDRESS

        if st.button("Reset addresses"):
            st.session_state["start_address_input"] = _DEFAULT_START_ADDRESS
            st.session_state["end_address_input"] = _DEFAULT_END_ADDRESS

        c1, c2 = st.columns(2)
        with c1:
            start_address = st.text_input("Start address", key="start_address_input")
            mode = st.selectbox(
                "Travel mode",
                [m.value for m in TravelMode],
                index=list(TravelMode).index(TravelMode.WALKING),
            )
        with c2:
            end_address = st.text_input("End address", key="end_address_input")

        with st.expander("Settings", expanded=False):
            st.write("Current defaults loaded from environment:")
            st.code(
                f"HIN_DATA_SOURCE={settings.hin_data_source}\n"
                f"CIP_DATA_SOURCE={settings.cip_data_source}\n"
                f"PROXIMITY_BUFFER_M={settings.proximity_buffer_m}",
                language="text",
            )
            _, cached_at = get_cached_service(settings)
            age = datetime.now(timezone.utc) - cached_at
            st.caption(
                f"HIN/CIP data last refreshed {_format_age(age)} ago "
                f"(auto-refreshes every {settings.data_refresh_interval_seconds / 3600:.0f}h)."
            )
            if st.button("Refresh live data now"):
                with st.spinner("Re-fetching HIN/CIP datasets..."):
                    refresh_cached_service(settings)
                st.success("Data refreshed.")
                st.rerun()
            st.caption(
                "ORS API key: "
                + (
                    "configured"
                    if settings.openrouteservice_api_key
                    else "not configured (routes fall back to an approximate straight line)"
                )
            )

        submitted = st.button("Analyze route")

        if not submitted:
            return

    try:
        with st.spinner("Analyzing route and overlap details..."):
            start_coord = _geocode_address(start_address, settings.request_timeout_seconds)
            end_coord = _geocode_address(end_address, settings.request_timeout_seconds)
            service, _ = get_cached_service(settings)
            request = RouteRequest(
                start=start_coord,
                end=end_coord,
                mode=TravelMode(mode),
            )
            try:
                result = service.analyze(request, routing_provider="ors")
            except RoutingError:
                result = service.analyze(request, routing_provider="mock")
                st.warning(
                    "Live routing wasn't available, so this route is an "
                    "approximate straight line."
                )
    except (GeocodingError, RoutingError, ValueError, FileNotFoundError) as exc:
        st.error(f"Could not analyze route: {exc}")
        return

    route_km = result.route.distance_m / 1609.3
    duration_min = result.route.duration_s / 60.0
    cip_details_frame = _build_cip_overlap_details_frame(result)
    hin_street_frame = _aggregate_hin_by_street(_build_hin_overlap_details_frame(result))

    bucket_frame = _build_bucket_percentage_series(result, service)
    bucket_pct = {row["Bucket"]: row["Percent"] for _, row in bucket_frame.iterrows()}
    change_pct = max(0.0, 100.0 - bucket_pct["Unaffected"])
    latest_year = _latest_completion_year(result)
    year_suffix = f" by {latest_year}" if latest_year is not None else ""

    st.markdown(f"### {change_pct:.0f}% of your route may change{year_suffix}")
    st.caption(f"{route_km:.2f} mile {mode} route")

    _render_route_overlap_bar(route_geom=shape(result.route.geojson["geometry"]), service=service)

    st.markdown("#### Route map")
    _render_route_map(result, request, service)

    _render_bucket_sections(bucket_pct, cip_details_frame, hin_street_frame)


def main() -> None:
    """Run Streamlit dashboard."""
    st.set_page_config(page_title="Street Vision", layout="wide")
    st.title("Street Vision: Your route's future")

    _render_route_tab()


if __name__ == "__main__":
    main()

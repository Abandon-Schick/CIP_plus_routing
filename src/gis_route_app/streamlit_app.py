"""Streamlit dashboard for nearby map and route intersection analysis."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from pyproj import Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    Point,
    mapping,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from gis_route_app.analysis import union_dataset_corridors_wgs84
from gis_route_app.config import get_settings
from gis_route_app.models import (
    Coordinate,
    RouteAnalysisResponse,
    RouteRequest,
    SegmentIntersection,
    TravelMode,
)
from gis_route_app.routing import RoutingError
from gis_route_app.service import RouteIntersectionService

NEAR_ME_URL = (
    "https://www.arcgis.com/apps/instant/nearbybeta/index.html"
    "?appid=3990cecc7b0d42079d60b9aa3ad725e5&locale=en"
)
_GEOD = Geod(ellps="WGS84")
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODER_USER_AGENT = "gis-route-intersection-dashboard/0.1"
_DEFAULT_START_ADDRESS = "1717 East Cary Street, Shockoe Bottom, Richmond, VA"
_DEFAULT_END_ADDRESS = "407 Cleveland St, Richmond, VA"
_TYPED_ADDRESS_PREFIX = "Searched address: "
# Match Route Map GeoJsonLayer line colors (HIN orange, CIP purple).
_BAR_COLOR_HIN = "#CC5500"
_BAR_COLOR_CIP = "#500050"
_BAR_COLOR_BOTH_GRADIENT = (
    "repeating-linear-gradient(90deg, "
    f"{_BAR_COLOR_HIN} 0px, {_BAR_COLOR_HIN} 4px, "
    f"{_BAR_COLOR_CIP} 4px, {_BAR_COLOR_CIP} 8px)"
)
_BAR_COLOR_NO_OVERLAP = "#BDBDBD"
# PathLayer RGBA (match GeoJsonLayer HIN / CIP line colors; gray = no overlap).
_RGBA_ROUTE_HIN = [204, 85, 0, 255]
_RGBA_ROUTE_CIP = [80, 0, 80, 255]
_RGBA_ROUTE_NONE = [189, 189, 189, 255]
_BOTH_ROUTE_STRIPE_CHUNK_M = 22.0


class GeocodingError(RuntimeError):
    """Raised when address geocoding fails."""


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
    except (requests.RequestException, ValueError):
        return []

    if not isinstance(payload, list):
        return []

    suggestions: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
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

    prox = service.analysis_engine.proximity_buffer_m
    hin_corridor = union_dataset_corridors_wgs84(
        service.analysis_engine.hin_features, prox, route_geom
    )
    cip_corridor = union_dataset_corridors_wgs84(
        service.analysis_engine.cip_features, prox, route_geom
    )

    hin_only = route_geom.intersection(hin_corridor).difference(cip_corridor)
    cip_only = route_geom.intersection(cip_corridor).difference(hin_corridor)
    none_overlap = route_geom.difference(hin_corridor.union(cip_corridor))

    hin_pct = (_geometry_length_m(hin_only) / route_distance_m) * 100.0
    cip_pct = (_geometry_length_m(cip_only) / route_distance_m) * 100.0
    none_pct = (_geometry_length_m(none_overlap) / route_distance_m) * 100.0

    return pd.DataFrame(
        {
            "Category": ["HIN overlap", "CIP overlap", "No overlap"],
            "Percent": [max(hin_pct, 0.0), max(cip_pct, 0.0), max(none_pct, 0.0)],
        }
    )


def _build_overlap_details_frame(result: RouteAnalysisResponse) -> pd.DataFrame:
    columns = [
        "Dataset",
        "Overlap Percent",
        "Name",
        "Category",
        "Description",
        "Cost",
        "Phase",
        "Status",
        "Completion",
    ]

    def _pick(properties: dict[str, object], keys: list[str]) -> str:
        for key in keys:
            value = properties.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    rows = [
        {
            "Dataset": intersection.dataset.upper(),
            "Overlap Percent": round(intersection.overlap_fraction_of_route * 100.0, 2),
            "Name": _pick(
                intersection.properties,
                ["project_name", "name", "Name", "title", "Title", "id", "ID"],
            )
            or intersection.feature_id,
            "Category": _pick(
                intersection.properties,
                ["category", "Category", "kind", "type", "Type"],
            ),
            "Description": _pick(
                intersection.properties,
                ["description", "Description", "desc", "project_description"],
            ),
            "Cost": _pick(
                intersection.properties,
                ["cost", "Cost", "budget", "Budget", "project_cost"],
            ),
            "Phase": _pick(intersection.properties, ["phase", "Phase"]),
            "Status": _pick(intersection.properties, ["status", "Status"]),
            "Completion": _pick(
                intersection.properties,
                ["completion", "Completion", "completion_date", "end_date"],
            ),
        }
        for intersection in result.intersections
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        by=["Dataset", "Overlap Percent"],
        ascending=[True, False],
    )


def _extract_line_geometries(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if len(line.coords) >= 2]
    if isinstance(geometry, GeometryCollection):
        output: list[LineString] = []
        for geom in geometry.geoms:
            output.extend(_extract_line_geometries(geom))
        return output
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return _extract_line_geometries(geometry.boundary)
    return []


def _merge_intervals(
    intervals: list[tuple[float, float]],
    tolerance: float = 1e-6,
) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda i: i[0])
    merged: list[tuple[float, float]] = []
    for start, end in sorted_intervals:
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        if start <= prev_end + tolerance:
            merged[-1] = (prev_start, max(prev_end, end))
            continue
        merged.append((start, end))
    return merged


def _line_metric_overlap_intervals(
    route_line: LineString,
    overlap_union: BaseGeometry,
) -> list[tuple[float, float]]:
    """Sub-intervals of ``route_line`` covered by ``overlap_union``, as normalized [0, 1] along the line.

    Values are for ``shapely.ops.substring(..., normalized=True)`` (Shapely's native distance along
    the line). Do not mix with geodesic meters — use substring + `_geometry_length_m` for lengths.
    """
    if _geometry_length_m(route_line) <= 0 or overlap_union.is_empty:
        return []

    overlap_geom = route_line.intersection(overlap_union)
    overlap_lines = _extract_line_geometries(overlap_geom)
    intervals: list[tuple[float, float]] = []
    for overlap_line in overlap_lines:
        coords = list(overlap_line.coords)
        if len(coords) < 2:
            continue
        start_norm = route_line.project(Point(coords[0]), normalized=True)
        end_norm = route_line.project(Point(coords[-1]), normalized=True)
        lo = max(0.0, min(start_norm, end_norm))
        hi = min(1.0, max(start_norm, end_norm))
        if hi <= lo:
            continue
        intervals.append((lo, hi))
    return _merge_intervals(intervals)


def _build_line_overlap_intervals(
    route_line: LineString,
    overlap_union: BaseGeometry,
) -> list[tuple[float, float]]:
    return _line_metric_overlap_intervals(route_line, overlap_union)


def _build_route_overlap_blocks(
    route_geom: BaseGeometry,
    overlap_union: BaseGeometry,
) -> list[dict[str, float | str]]:
    route_lines = _extract_line_geometries(route_geom)
    total_length_m = float(sum(_geometry_length_m(line) for line in route_lines))
    if total_length_m <= 0:
        return [{"segment": "no_overlap", "fraction": 1.0}]

    blocks: list[dict[str, float | str]] = []
    for line in route_lines:
        line_length_m = _geometry_length_m(line)
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
                blocks.append({"segment": "no_overlap", "length_m": _geometry_length_m(gap)})
            ov = substring(line, lo_n, hi_n, normalized=True)
            blocks.append({"segment": "overlap", "length_m": _geometry_length_m(ov)})
            cursor_n = hi_n
        if cursor_n < 1.0:
            tail = substring(line, cursor_n, 1.0, normalized=True)
            blocks.append({"segment": "no_overlap", "length_m": _geometry_length_m(tail)})

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


def _corridor_hin_cip_both_parts(
    hin_corridor: BaseGeometry,
    cip_corridor: BaseGeometry,
) -> tuple[BaseGeometry, BaseGeometry, BaseGeometry]:
    hin_only = hin_corridor.difference(cip_corridor)
    cip_only = cip_corridor.difference(hin_corridor)
    both = hin_corridor.intersection(cip_corridor)
    return hin_only, cip_only, both


def _merged_metric_spans_on_line(
    line: LineString,
    hin_only: BaseGeometry,
    cip_only: BaseGeometry,
    both: BaseGeometry,
) -> list[tuple[float, float, str]]:
    """Disjoint (start_norm, end_norm, tag) along ``line``; tag is hin|cip|both|no_overlap."""
    if _geometry_length_m(line) <= 0:
        return []
    tol = 1e-9
    tagged: list[tuple[float, float, str]] = []
    for geom, tag in (
        (hin_only, "hin"),
        (cip_only, "cip"),
        (both, "both"),
    ):
        for lo, hi in _line_metric_overlap_intervals(line, geom):
            if hi > lo + tol:
                tagged.append((lo, hi, tag))
    tagged.sort(key=lambda t: t[0])

    segs: list[tuple[float, float, str]] = []
    cursor = 0.0
    for lo, hi, tag in tagged:
        lo = max(0.0, min(lo, 1.0))
        hi = max(0.0, min(hi, 1.0))
        if hi <= lo + tol:
            continue
        if lo > cursor + tol:
            segs.append((cursor, lo, "no_overlap"))
        segs.append((lo, hi, tag))
        cursor = max(cursor, hi)
    if cursor < 1.0 - tol:
        segs.append((cursor, 1.0, "no_overlap"))

    merged: list[tuple[float, float, str]] = []
    for lo, hi, seg in segs:
        if hi <= lo + tol:
            continue
        if merged and merged[-1][2] == seg and abs(merged[-1][1] - lo) < 1e-6:
            merged[-1] = (merged[-1][0], hi, seg)
        else:
            merged.append((lo, hi, seg))
    return merged


def _linestring_subpath_coords(
    line: LineString,
    start_n: float,
    end_n: float,
) -> list[list[float]]:
    if end_n <= start_n + 1e-12:
        return []
    sub = substring(line, start_n, end_n, normalized=True)
    if sub.is_empty:
        return []
    coords = list(sub.coords)
    if len(coords) < 2:
        return []
    return [[float(x), float(y)] for x, y in coords]


def _route_path_rows_colored(
    route_geom: BaseGeometry,
    hin_corridor: BaseGeometry,
    cip_corridor: BaseGeometry,
) -> list[dict[str, object]]:
    """PathLayer rows: path (lon/lat) + RGBA color, aligned with overlap bar classification."""
    hin_only, cip_only, both = _corridor_hin_cip_both_parts(hin_corridor, cip_corridor)
    rows: list[dict[str, object]] = []
    for line in _extract_line_geometries(route_geom):
        line_len_m = max(_geometry_length_m(line), 1e-9)
        chunk_n = min(_BOTH_ROUTE_STRIPE_CHUNK_M / line_len_m, 1.0)
        for lo, hi, tag in _merged_metric_spans_on_line(line, hin_only, cip_only, both):
            if tag == "both":
                cur = lo
                flip = True
                while cur < hi - 1e-12:
                    nxt = min(cur + chunk_n, hi)
                    path = _linestring_subpath_coords(line, cur, nxt)
                    if len(path) >= 2:
                        rows.append(
                            {
                                "path": path,
                                "color": _RGBA_ROUTE_HIN if flip else _RGBA_ROUTE_CIP,
                            }
                        )
                    flip = not flip
                    cur = nxt
                continue
            path = _linestring_subpath_coords(line, lo, hi)
            if len(path) < 2:
                continue
            if tag == "hin":
                color = _RGBA_ROUTE_HIN
            elif tag == "cip":
                color = _RGBA_ROUTE_CIP
            else:
                color = _RGBA_ROUTE_NONE
            rows.append({"path": path, "color": color})
    return rows


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


def _build_typed_route_overlap_blocks(
    route_geom: BaseGeometry,
    hin_corridor: BaseGeometry,
    cip_corridor: BaseGeometry,
) -> list[dict[str, float | str]]:
    """Partition route into hin-only, cip-only, both-corridors, and gap segments (matches map colors)."""
    route_lines = _extract_line_geometries(route_geom)
    total_length_m = float(sum(_geometry_length_m(line) for line in route_lines))
    if total_length_m <= 0:
        return [{"segment": "no_overlap", "fraction": 1.0}]

    hin_only, cip_only, both = _corridor_hin_cip_both_parts(hin_corridor, cip_corridor)
    raw_pieces: list[tuple[float, str]] = []
    tol = 1e-6
    for line in route_lines:
        merged_line: list[tuple[float, str]] = []
        for lo, hi, seg in _merged_metric_spans_on_line(line, hin_only, cip_only, both):
            span = substring(line, lo, hi, normalized=True)
            length = _geometry_length_m(span)
            if length <= tol:
                continue
            if merged_line and merged_line[-1][1] == seg:
                merged_line[-1] = (merged_line[-1][0] + length, seg)
            else:
                merged_line.append((length, seg))
        raw_pieces.extend(merged_line)

    merged_global = _merge_adjacent_segment_lengths(raw_pieces)
    if not merged_global:
        return [{"segment": "no_overlap", "fraction": 1.0}]
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
    prox = service.analysis_engine.proximity_buffer_m
    hin_corridor = union_dataset_corridors_wgs84(
        service.analysis_engine.hin_features, prox, route_geom
    )
    cip_corridor = union_dataset_corridors_wgs84(
        service.analysis_engine.cip_features, prox, route_geom
    )
    blocks = _build_typed_route_overlap_blocks(route_geom, hin_corridor, cip_corridor)

    def _bar_background(seg: str) -> str:
        if seg == "hin":
            return _BAR_COLOR_HIN
        if seg == "cip":
            return _BAR_COLOR_CIP
        if seg == "both":
            return _BAR_COLOR_BOTH_GRADIENT
        return _BAR_COLOR_NO_OVERLAP

    segment_html = "".join(
        (
            f"<div style='height:100%; width:{max(float(block['fraction']) * 100.0, 0.0):.6f}%; "
            f"background:{_bar_background(str(block['segment']))};'></div>"
        )
        for block in blocks
    )
    overlap_pct = (
        sum(
            float(block["fraction"])
            for block in blocks
            if str(block["segment"]) in {"hin", "cip", "both"}
        )
        * 100.0
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
            "<span><span style='display:inline-block; width:12px; height:12px; "
            f"background:{_BAR_COLOR_HIN}; margin-right:6px; border:1px solid #999;'></span>"
            "HIN overlap</span>"
            "<span><span style='display:inline-block; width:12px; height:12px; "
            f"background:{_BAR_COLOR_CIP}; margin-right:6px; border:1px solid #999;'></span>"
            "CIP overlap</span>"
            "<span><span style='display:inline-block; width:12px; height:12px; "
            f"background:{_BAR_COLOR_BOTH_GRADIENT}; margin-right:6px; border:1px solid #999;'></span>"
            "Both</span>"
            "<span><span style='display:inline-block; width:12px; height:12px; "
            f"background:{_BAR_COLOR_NO_OVERLAP}; margin-right:6px; border:1px solid #999;'></span>"
            "No overlap</span>"
            f"<span>Total overlap: {overlap_pct:.1f}%</span>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
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


def _intersecting_hin_cip_geojson(
    service: RouteIntersectionService,
    intersections: list[SegmentIntersection],
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Build FeatureCollections for HIN/CIP features that overlap the route (for map layers)."""
    seen: set[tuple[str, str]] = set()
    hin_features: list[dict[str, object]] = []
    cip_features: list[dict[str, object]] = []
    hin_by_id = {f.feature_id: f for f in service.analysis_engine.hin_features}
    cip_by_id = {f.feature_id: f for f in service.analysis_engine.cip_features}

    for inter in intersections:
        key = (inter.dataset, inter.feature_id)
        if key in seen:
            continue
        seen.add(key)
        if inter.dataset == "hin":
            dataset_feat = hin_by_id.get(inter.feature_id)
            target = hin_features
            label = "HIN"
        else:
            dataset_feat = cip_by_id.get(inter.feature_id)
            target = cip_features
            label = "CIP"
        if dataset_feat is None:
            continue
        props = {
            **dataset_feat.properties,
            "name": f"{label} · {inter.feature_id}",
        }
        target.append(
            {
                "type": "Feature",
                "geometry": mapping(dataset_feat.geometry),
                "properties": props,
            }
        )

    def _fc(features: list[dict[str, object]]) -> dict[str, object] | None:
        if not features:
            return None
        return {"type": "FeatureCollection", "features": features}

    return _fc(hin_features), _fc(cip_features)


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

    prox = service.analysis_engine.proximity_buffer_m
    hin_corridor = union_dataset_corridors_wgs84(
        service.analysis_engine.hin_features, prox, route_geom
    )
    cip_corridor = union_dataset_corridors_wgs84(
        service.analysis_engine.cip_features, prox, route_geom
    )
    route_path_rows = _route_path_rows_colored(route_geom, hin_corridor, cip_corridor)
    if not route_path_rows:
        route_path_rows = [{"path": path, "color": _RGBA_ROUTE_NONE} for path in paths]
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

    hin_fc, cip_fc = _intersecting_hin_cip_geojson(service, result.intersections)
    layers: list[pdk.Layer] = []
    if hin_fc is not None:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                hin_fc,
                stroked=True,
                filled=True,
                get_fill_color=[255, 140, 0, 90],
                get_line_color=[204, 85, 0, 255],
                line_width_min_pixels=2,
                pickable=True,
            )
        )
    if cip_fc is not None:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                cip_fc,
                stroked=True,
                filled=True,
                get_fill_color=[128, 0, 128, 90],
                get_line_color=[80, 0, 80, 255],
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


def _resolve_selected_address(typed_value: str, selected_option: str) -> str:
    if selected_option.startswith(_TYPED_ADDRESS_PREFIX):
        return typed_value
    return selected_option


def _typed_address_option(typed_value: str) -> str:
    return f"{_TYPED_ADDRESS_PREFIX}{typed_value}"


def _swap_addresses(start_address: str, end_address: str) -> tuple[str, str]:
    return end_address, start_address


def _resolve_ors_api_key(
    typed_value: str | None,
    env_value: str | None,
) -> str | None:
    if typed_value is None:
        return (env_value or "").strip() or None

    normalized = typed_value.strip()
    if normalized:
        return normalized
    return None


def _render_route_tab() -> None:
    st.subheader("GIS Route Intersection Analysis")
    st.caption("Set start/end addresses and evaluate route overlap with HIN/CIP datasets.")

    settings = get_settings()
    with st.expander("Data source settings", expanded=False):
        st.write("Current defaults loaded from environment:")
        st.code(
            f"HIN_DATA_SOURCE={settings.hin_data_source}\n"
            f"CIP_DATA_SOURCE={settings.cip_data_source}\n"
            f"PROXIMITY_BUFFER_M={settings.proximity_buffer_m}",
            language="text",
        )

    if "start_address_input" not in st.session_state:
        st.session_state["start_address_input"] = _DEFAULT_START_ADDRESS
    if "end_address_input" not in st.session_state:
        st.session_state["end_address_input"] = _DEFAULT_END_ADDRESS

    a1, a2, _ = st.columns([1, 1, 4])
    with a1:
        if st.button("Swap start/end"):
            swapped_start, swapped_end = _swap_addresses(
                st.session_state["start_address_input"],
                st.session_state["end_address_input"],
            )
            st.session_state["start_address_input"] = swapped_start
            st.session_state["end_address_input"] = swapped_end
    with a2:
        if st.button("Reset addresses"):
            st.session_state["start_address_input"] = _DEFAULT_START_ADDRESS
            st.session_state["end_address_input"] = _DEFAULT_END_ADDRESS

    c1, c2 = st.columns(2)
    with c1:
        start_address = st.text_input(
            "Start address",
            key="start_address_input",
        )
        start_suggestions = _autocomplete_addresses(
            start_address,
            timeout_seconds=settings.request_timeout_seconds,
        )
        start_selection = st.selectbox(
            "Start address suggestions",
            options=[_typed_address_option(start_address)] + start_suggestions,
            help="Type at least 3 characters to get autocomplete suggestions.",
        )
        mode = st.selectbox("Travel mode", [m.value for m in TravelMode], index=0)

    with c2:
        end_address = st.text_input(
            "End address",
            key="end_address_input",
        )
        end_suggestions = _autocomplete_addresses(
            end_address,
            timeout_seconds=settings.request_timeout_seconds,
        )
        end_selection = st.selectbox(
            "End address suggestions",
            options=[_typed_address_option(end_address)] + end_suggestions,
            help="Type at least 3 characters to get autocomplete suggestions.",
        )
        provider = st.selectbox(
            "Routing provider",
            options=["mock", "ors"],
            index=0 if settings.routing_provider != "ors" else 1,
        )
        env_ors_key = settings.openrouteservice_api_key or ""
        if "ors_api_key_input" not in st.session_state:
            st.session_state["ors_api_key_input"] = env_ors_key
        ors_api_key_input = st.text_input(
            "ORS API key",
            key="ors_api_key_input",
            type="password",
            help=(
                "Used only when routing provider is 'ors'. "
                "Overrides OPENROUTESERVICE_API_KEY for this analysis request."
            ),
            placeholder="Paste OpenRouteService API key",
        )

    submitted = st.button("Analyze route")

    if not submitted:
        st.info(
            "Enter start & end addresses. Then run the analysis."
        )
        return

    resolved_ors_api_key = _resolve_ors_api_key(ors_api_key_input, None)
    settings = replace(
        settings,
        routing_provider=provider,
        openrouteservice_api_key=resolved_ors_api_key,
    )

    if provider == "ors" and not settings.openrouteservice_api_key:
        st.error("Routing provider 'ors' requires an ORS API key.")
        return

    try:
        with st.spinner("Analyzing route and overlap details..."):
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

    route_km = result.route.distance_m / 1609.3
    duration_min = result.route.duration_s / 60.0
    pct_frame = _build_percentage_series(result, service)
    details_frame = _build_overlap_details_frame(result)
    by_category = {row["Category"]: row["Percent"] for _, row in pct_frame.iterrows()}
    any_overlap_pct = max(0.0, 100.0 - by_category["No overlap"])

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Route distance", f"{route_km:.2f} miles")
    m2.metric("Roadway Projects", f"{by_category['CIP overlap']:.1f}%")
    m3.metric("High Injury Network", f"{by_category['HIN overlap']:.1f}%")
    m4.metric("Any overlap", f"{any_overlap_pct:.1f}%")
    m5.metric("No overlap", f"{by_category['No overlap']:.1f}%")

    st.markdown("#### Overlaps along route (start to end)")
    _render_route_overlap_bar(route_geom=shape(result.route.geojson["geometry"]), service=service)

    st.markdown("#### Route map")
    st.caption(
        "Route line: orange = HIN corridor, purple = CIP corridor, gray = neither; "
        "striped route segments = both. "
        "Overlays: orange HIN and purple CIP geometries near the route."
    )
    _render_route_map(result, request, service)

    st.markdown("#### Overlap details")
    st.dataframe(details_frame, use_container_width=True, hide_index=True)
    st.download_button(
        "Download overlap details (CSV)",
        data=details_frame.to_csv(index=False).encode("utf-8"),
        file_name="route_overlap_details.csv",
        mime="text/csv",
    )


def main() -> None:
    """Run Streamlit dashboard."""
    st.set_page_config(page_title="Roadway Repairs Along Route", layout="wide")
    st.title("Imagine the future for your favorite routes")

    near_me_tab, route_tab = st.tabs(["Near me", "Along a route"])

    with near_me_tab:
        st.subheader("Find projects happening within a radius")
        components.iframe(NEAR_ME_URL, height=900, scrolling=True)

    with route_tab:
        _render_route_tab()


if __name__ == "__main__":
    main()

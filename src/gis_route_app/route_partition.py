"""Split a route into bucket-tagged stretches (shared by the Streamlit map and navigation)."""

from __future__ import annotations

import math

from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring
from shapely.prepared import prep

from .analysis import SpatialAnalysisEngine, union_dataset_corridors_wgs84
from .summary import BUCKET_ORDER

_GEOD = Geod(ellps="WGS84")


def geometry_length_m(geometry: BaseGeometry) -> float:
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
        return float(sum(geometry_length_m(line) for line in geometry.geoms))
    if isinstance(geometry, GeometryCollection):
        return float(sum(geometry_length_m(geom) for geom in geometry.geoms))
    if geometry.geom_type in {"Polygon", "MultiPolygon", "Point", "MultiPoint"}:
        return geometry_length_m(geometry.boundary)
    return float(geometry.length)


def extract_line_geometries(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if len(line.coords) >= 2]
    if isinstance(geometry, GeometryCollection):
        output: list[LineString] = []
        for geom in geometry.geoms:
            output.extend(extract_line_geometries(geom))
        return output
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return extract_line_geometries(geometry.boundary)
    return []


def merge_intervals(
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


def line_metric_overlap_intervals(
    route_line: LineString,
    overlap_union: BaseGeometry,
) -> list[tuple[float, float]]:
    """Sub-intervals of ``route_line`` covered by ``overlap_union``, as normalized [0, 1] along the line.

    Values are for ``shapely.ops.substring(..., normalized=True)`` (Shapely's native distance along
    the line). Do not mix with geodesic meters — use substring + `geometry_length_m` for lengths.

    Measured one vertex-to-vertex segment at a time, so a route that retraces itself (a GPX
    track out and back along the same road) is placed correctly on *both* passes; projecting
    overlap pieces onto the whole line would put every pass at the first one's position.
    """
    if geometry_length_m(route_line) <= 0 or overlap_union.is_empty:
        return []

    coords = list(route_line.coords)
    cumulative = [0.0]
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        cumulative.append(cumulative[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cumulative[-1]
    if total <= 0:
        return []

    prepared = prep(overlap_union)
    intervals: list[tuple[float, float]] = []
    for i, (start, end) in enumerate(zip(coords, coords[1:])):
        segment = LineString([start, end])
        if segment.length <= 0 or not prepared.intersects(segment):
            continue
        for piece in extract_line_geometries(segment.intersection(overlap_union)):
            piece_coords = list(piece.coords)
            a = segment.project(Point(piece_coords[0]))
            b = segment.project(Point(piece_coords[-1]))
            lo, hi = min(a, b), max(a, b)
            if hi <= lo:
                continue
            intervals.append(((cumulative[i] + lo) / total, (cumulative[i] + hi) / total))
    return merge_intervals(intervals)


def bucket_corridors(
    engine: SpatialAnalysisEngine, route_geom: BaseGeometry
) -> dict[str, BaseGeometry]:
    """Per-bucket corridor geometry (HIN for high risk, CIP split by ``cip_bucket``).

    Shared by the summary cards, the overlap bar, the map, and navigation so all of
    them are computed from -- and agree with -- the same underlying corridors.
    """
    prox = engine.proximity_buffer_m
    cip_by_bucket: dict[str, list] = {}
    for feature in engine.cip_features:
        bucket = feature.properties.get("cip_bucket", "planned")
        cip_by_bucket.setdefault(bucket, []).append(feature)

    corridors = {
        "high_risk": union_dataset_corridors_wgs84(engine.hin_features, prox, route_geom),
    }
    for bucket_key in ("completed", "construction", "planned"):
        corridors[bucket_key] = union_dataset_corridors_wgs84(
            cip_by_bucket.get(bucket_key, []), prox, route_geom
        )
    return corridors


def priority_spans_on_line(
    line: LineString,
    tagged_corridors: list[tuple[str, BaseGeometry]],
) -> list[tuple[float, float, str]]:
    """Disjoint (start_norm, end_norm, tag) along ``line``.

    ``tagged_corridors`` is in priority order (matches ``BUCKET_ORDER``): where two
    corridors' buffers overlap the same stretch of route, the first-listed tag wins.
    Stretches covered by no corridor are tagged "unaffected".
    """
    if geometry_length_m(line) <= 0:
        return []
    tol = 1e-9
    boundaries: set[float] = {0.0, 1.0}
    per_tag_intervals: list[tuple[str, list[tuple[float, float]]]] = []
    for tag, geom in tagged_corridors:
        intervals = line_metric_overlap_intervals(line, geom)
        per_tag_intervals.append((tag, intervals))
        for lo, hi in intervals:
            boundaries.add(max(0.0, min(lo, 1.0)))
            boundaries.add(max(0.0, min(hi, 1.0)))

    segs: list[tuple[float, float, str]] = []
    sorted_bounds = sorted(boundaries)
    for lo, hi in zip(sorted_bounds, sorted_bounds[1:]):
        if hi <= lo + tol:
            continue
        mid = (lo + hi) / 2.0
        winner = "unaffected"
        for tag, intervals in per_tag_intervals:
            if any(ilo - tol <= mid <= ihi + tol for ilo, ihi in intervals):
                winner = tag
                break
        if segs and segs[-1][2] == winner and abs(segs[-1][1] - lo) < 1e-6:
            segs[-1] = (segs[-1][0], hi, winner)
        else:
            segs.append((lo, hi, winner))
    return segs


def linestring_subpath_coords(
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


def bucket_route_paths(
    route_geom: BaseGeometry,
    corridors: dict[str, BaseGeometry],
) -> list[tuple[str, list[list[float]]]]:
    """(bucket key or "unaffected", lon/lat path) pieces covering the route in order."""
    tagged_corridors = [(key, corridors[key]) for key, _ in BUCKET_ORDER]
    pieces: list[tuple[str, list[list[float]]]] = []
    for line in extract_line_geometries(route_geom):
        for lo, hi, tag in priority_spans_on_line(line, tagged_corridors):
            path = linestring_subpath_coords(line, lo, hi)
            if len(path) >= 2:
                pieces.append((tag, path))
    return pieces

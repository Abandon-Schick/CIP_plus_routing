"""Spatial intersection analysis between route and dataset geometries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pyproj import CRS, Geod, Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform, unary_union

from .datasets import DatasetFeature
from .models import SegmentIntersection

_GEOD = Geod(ellps="WGS84")


def _utm_crs_for_wgs84_point(lon: float, lat: float) -> CRS:
    zone = min(max(int((lon + 180.0) // 6) + 1, 1), 60)
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def metric_transformers_for_geometry(route_geom: BaseGeometry) -> tuple[Transformer, Transformer]:
    """WGS84 lon/lat ↔ metric UTM transformers anchored on route geometry."""
    rep = route_geom.representative_point()
    utm = _utm_crs_for_wgs84_point(rep.x, rep.y)
    wgs = CRS.from_epsg(4326)
    return (
        Transformer.from_crs(wgs, utm, always_xy=True),
        Transformer.from_crs(utm, wgs, always_xy=True),
    )


def union_dataset_corridors_wgs84(
    features: list[DatasetFeature],
    proximity_buffer_m: float,
    route_geom: BaseGeometry,
) -> BaseGeometry:
    """Union of features expanded by ``proximity_buffer_m`` (meters), returned in WGS84."""
    if not features:
        return GeometryCollection()
    if proximity_buffer_m <= 0.0:
        return unary_union([f.geometry for f in features])

    forward, inverse = metric_transformers_for_geometry(route_geom)
    parts: list[BaseGeometry] = []
    for f in features:
        geom_m = shapely_transform(forward.transform, f.geometry)
        parts.append(geom_m.buffer(proximity_buffer_m))
    merged_m = unary_union(parts)
    return shapely_transform(inverse.transform, merged_m)


def _route_overlap_length_within_corridor_m(
    route_geom: BaseGeometry,
    feature_geom: BaseGeometry,
    proximity_buffer_m: float,
    forward: Transformer,
    inverse: Transformer,
) -> float:
    """Length of route (geodesic, m) inside a metric buffer around the feature geometry."""
    if proximity_buffer_m <= 0.0:
        return _length_m(route_geom.intersection(feature_geom))
    geom_m = shapely_transform(forward.transform, feature_geom)
    corridor_wgs = shapely_transform(inverse.transform, geom_m.buffer(proximity_buffer_m))
    return _length_m(route_geom.intersection(corridor_wgs))


@dataclass(frozen=True)
class SpatialAnalysisEngine:
    """Compute route intersections for configured datasets."""

    hin_features: list[DatasetFeature]
    cip_features: list[DatasetFeature]
    proximity_buffer_m: float = 50.0
    """Count a dataset feature when the route comes within this many meters (buffer in metric CRS)."""
    overlap_tolerance_m: float = 0.0
    """Drop matches whose overlap length (after proximity) is at or below this many meters."""

    def analyze_route(self, route_geojson: dict[str, Any]) -> list[SegmentIntersection]:
        """Return overlaps for HIN and CIP (includes near-misses within ``proximity_buffer_m``)."""
        route_geom = shape(route_geojson["geometry"])
        route_length_m = _length_m(route_geom)
        if route_length_m <= 0:
            return []

        forward, inverse = metric_transformers_for_geometry(route_geom)
        matches: list[SegmentIntersection] = []
        matches.extend(
            self._collect_dataset_intersections(
                route_geom=route_geom,
                route_length_m=route_length_m,
                features=self.hin_features,
                dataset_name="hin",
                forward=forward,
                inverse=inverse,
            )
        )
        matches.extend(
            self._collect_dataset_intersections(
                route_geom=route_geom,
                route_length_m=route_length_m,
                features=self.cip_features,
                dataset_name="cip",
                forward=forward,
                inverse=inverse,
            )
        )
        return matches

    def _collect_dataset_intersections(
        self,
        route_geom: BaseGeometry,
        route_length_m: float,
        features: list[DatasetFeature],
        dataset_name: Literal["hin", "cip"],
        forward: Transformer,
        inverse: Transformer,
    ) -> list[SegmentIntersection]:
        output: list[SegmentIntersection] = []
        for feature in features:
            overlap_length_m = _route_overlap_length_within_corridor_m(
                route_geom,
                feature.geometry,
                self.proximity_buffer_m,
                forward,
                inverse,
            )
            if overlap_length_m <= self.overlap_tolerance_m:
                continue

            output.append(
                SegmentIntersection(
                    feature_id=feature.feature_id,
                    dataset=dataset_name,
                    overlap_length_m=overlap_length_m,
                    overlap_fraction_of_route=overlap_length_m / route_length_m,
                    properties=feature.properties,
                )
            )
        return output


def _length_m(geometry: BaseGeometry) -> float:
    """Compute geometry length in meters using geodesic length for linework."""
    if geometry.is_empty:
        return 0.0

    if isinstance(geometry, LineString):
        return _line_length_m(geometry)
    if isinstance(geometry, MultiLineString):
        return float(sum(_line_length_m(line) for line in geometry.geoms))
    if isinstance(geometry, GeometryCollection):
        return float(sum(_length_m(geom) for geom in geometry.geoms))

    # Intersections against polygons/points are measured via boundary length.
    if geometry.geom_type in {"Polygon", "MultiPolygon", "Point", "MultiPoint"}:
        return _length_m(geometry.boundary)

    return float(geometry.length)


def _line_length_m(line: LineString) -> float:
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0

    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return float(_GEOD.line_length(lons, lats))

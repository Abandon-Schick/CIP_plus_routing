"""Spatial intersection analysis between route and dataset geometries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry

from .datasets import DatasetFeature
from .models import SegmentIntersection

_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class SpatialAnalysisEngine:
    """Compute route intersections for configured datasets."""

    hin_features: list[DatasetFeature]
    cip_features: list[DatasetFeature]
    overlap_tolerance_m: float = 50.0

    def analyze_route(self, route_geojson: dict[str, Any]) -> list[SegmentIntersection]:
        """Return all non-zero overlaps for HIN and CIP datasets."""
        route_geom = shape(route_geojson["geometry"])
        route_length_m = _length_m(route_geom)
        if route_length_m <= 0:
            return []

        matches: list[SegmentIntersection] = []
        matches.extend(
            self._collect_dataset_intersections(
                route_geom=route_geom,
                route_length_m=route_length_m,
                features=self.hin_features,
                dataset_name="hin",
            )
        )
        matches.extend(
            self._collect_dataset_intersections(
                route_geom=route_geom,
                route_length_m=route_length_m,
                features=self.cip_features,
                dataset_name="cip",
            )
        )
        return matches

    def _collect_dataset_intersections(
        self,
        route_geom: BaseGeometry,
        route_length_m: float,
        features: list[DatasetFeature],
        dataset_name: Literal["hin", "cip"],
    ) -> list[SegmentIntersection]:
        output: list[SegmentIntersection] = []
        for feature in features:
            overlap = route_geom.intersection(feature.geometry)
            overlap_length_m = _length_m(overlap)
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

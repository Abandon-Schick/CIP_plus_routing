"""Navigation-mode payload: everything a live map client needs, computed once up front.

The client downloads this once and then does all position handling locally (which
stretch of route am I on, which cards apply) -- so no location ever leaves the device.
"""

from __future__ import annotations

from typing import Any

import shapely
from pydantic import BaseModel
from shapely.geometry import GeometryCollection, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform, unary_union

from .analysis import (
    SpatialAnalysisEngine,
    metric_transformers_for_geometry,
    union_dataset_corridors_wgs84,
)
from .datasets import DatasetFeature
from .models import RouteAnalysisResponse, TravelMode
from .route_partition import bucket_corridors, bucket_route_paths
from .summary import (
    BUCKET_COLOR_HEX,
    BUCKET_DISPLAY_ORDER,
    cip_detail,
    cip_fields,
    hin_detail,
    hin_fields,
)

# Corridors are only shipped near the route: a walker who drifts off it should still
# see what's around them, but not the whole city's worth of polygons.
_CORRIDOR_CLIP_MARGIN_M = 150.0
# ~1 m of simplification and 0.1 m of coordinate precision keep the payload small
# without visibly changing a 50 m corridor.
_SIMPLIFY_TOLERANCE_DEG = 1e-5
_COORD_GRID_DEG = 1e-6
# Containment tests against a zero-width corridor can never succeed for a moving phone.
_MIN_CORRIDOR_BUFFER_M = 10.0


class NavBucket(BaseModel):
    key: str
    label: str
    color: str


class NavRouteSegment(BaseModel):
    """A stretch of route drawn in one bucket color ("unaffected" when in no corridor)."""

    bucket: str
    path: list[list[float]]


class NavRoute(BaseModel):
    mode: TravelMode
    distance_m: float
    duration_s: float
    geometry: dict[str, Any]
    segments: list[NavRouteSegment]


class NavCard(BaseModel):
    """One thing the info bar can say. Active while the position is inside ``corridor``."""

    id: str
    dataset: str
    bucket: str
    title: str
    detail: str
    overlap_m: float
    corridor: dict[str, Any]


class NavigationPlan(BaseModel):
    route: NavRoute
    buckets: list[NavBucket]
    cards: list[NavCard]
    """Ordered most-important-first: the client stacks simultaneously active cards in this order."""


def _polygonal_part(geometry: BaseGeometry) -> BaseGeometry | None:
    if geometry.is_empty:
        return None
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if isinstance(geometry, GeometryCollection):
        polys = [g for g in geometry.geoms if g.geom_type in {"Polygon", "MultiPolygon"}]
        return unary_union(polys) if polys else None
    return None


def _card_corridor(
    features: list[DatasetFeature],
    buffer_m: float,
    route_geom: BaseGeometry,
    clip_zone: BaseGeometry,
) -> dict[str, Any] | None:
    corridor = union_dataset_corridors_wgs84(features, buffer_m, route_geom)
    clipped = _polygonal_part(corridor.intersection(clip_zone))
    if clipped is None:
        return None
    slim = _polygonal_part(
        shapely.set_precision(
            clipped.simplify(_SIMPLIFY_TOLERANCE_DEG, preserve_topology=True),
            _COORD_GRID_DEG,
        )
    )
    return None if slim is None else dict(mapping(slim))


def build_navigation_plan(
    result: RouteAnalysisResponse,
    engine: SpatialAnalysisEngine,
) -> NavigationPlan:
    route_geom = shape(result.route.geojson["geometry"])
    buffer_m = max(engine.proximity_buffer_m, _MIN_CORRIDOR_BUFFER_M)

    forward, inverse = metric_transformers_for_geometry(route_geom)
    clip_zone = shapely_transform(
        inverse.transform,
        shapely_transform(forward.transform, route_geom).buffer(
            buffer_m + _CORRIDOR_CLIP_MARGIN_M
        ),
    )

    hin_by_id = {f.feature_id: f for f in engine.hin_features}
    cip_by_id = {f.feature_id: f for f in engine.cip_features}

    # HIN is many tiny segments per named street; one card per street, not per segment.
    hin_groups: dict[str, dict[str, Any]] = {}
    cip_cards: list[tuple[str, NavCard]] = []
    seen_cip: set[str] = set()

    for inter in result.intersections:
        if inter.dataset == "hin":
            feature = hin_by_id.get(inter.feature_id)
            if feature is None:
                continue
            fields = hin_fields(inter.properties, inter.feature_id)
            group = hin_groups.setdefault(
                fields["name"], {"fields": fields, "features": [], "overlap_m": 0.0}
            )
            group["features"].append(feature)
            group["overlap_m"] += inter.overlap_length_m
        else:
            feature = cip_by_id.get(inter.feature_id)
            if feature is None or inter.feature_id in seen_cip:
                continue
            seen_cip.add(inter.feature_id)
            corridor = _card_corridor([feature], buffer_m, route_geom, clip_zone)
            if corridor is None:
                continue
            fields = cip_fields(inter.properties, inter.feature_id)
            bucket = inter.properties.get("cip_bucket", "planned")
            cip_cards.append(
                (
                    bucket,
                    NavCard(
                        id=f"cip:{inter.feature_id}",
                        dataset="cip",
                        bucket=bucket,
                        title=fields["name"],
                        detail=cip_detail(
                            fields["category"], fields["cost"], fields["completion"]
                        ),
                        overlap_m=inter.overlap_length_m,
                        corridor=corridor,
                    ),
                )
            )

    cards: list[tuple[str, NavCard]] = list(cip_cards)
    for name, group in hin_groups.items():
        corridor = _card_corridor(group["features"], buffer_m, route_geom, clip_zone)
        if corridor is None:
            continue
        fields = group["fields"]
        cards.append(
            (
                "high_risk",
                NavCard(
                    id=f"hin:{name}",
                    dataset="hin",
                    bucket="high_risk",
                    title=name,
                    detail=hin_detail(
                        fields["street_type"], fields["functional"], fields["posted_speed"]
                    ),
                    overlap_m=group["overlap_m"],
                    corridor=corridor,
                ),
            )
        )

    rank = {key: i for i, (key, _) in enumerate(BUCKET_DISPLAY_ORDER)}
    cards.sort(key=lambda item: (rank.get(item[0], len(rank)), -item[1].overlap_m))

    segments = [
        NavRouteSegment(bucket=tag, path=path)
        for tag, path in bucket_route_paths(route_geom, bucket_corridors(engine, route_geom))
    ]

    return NavigationPlan(
        route=NavRoute(
            mode=result.route.mode,
            distance_m=result.route.distance_m,
            duration_s=result.route.duration_s,
            geometry=result.route.geojson["geometry"],
            segments=segments,
        ),
        buckets=[
            NavBucket(key=key, label=label, color=BUCKET_COLOR_HEX[key])
            for key, label in BUCKET_DISPLAY_ORDER
        ]
        + [NavBucket(key="unaffected", label="Nothing changing here", color=BUCKET_COLOR_HEX["unaffected"])],
        cards=[card for _, card in cards],
    )

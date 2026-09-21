from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, box, shape

from gis_route_app import api
from gis_route_app.analysis import SpatialAnalysisEngine
from gis_route_app.config import Settings
from gis_route_app.datasets import DatasetFeature
from gis_route_app.models import Coordinate, RouteRequest, TravelMode
from gis_route_app.navigation import build_navigation_plan
from gis_route_app.route_partition import bucket_corridors, bucket_route_paths
from gis_route_app.service import RouteIntersectionService

# ~880 m straight east-west route at Richmond's latitude (mock routing draws exactly this).
_START = Coordinate(lon=-77.440, lat=37.540)
_END = Coordinate(lon=-77.430, lat=37.540)
_LAT = 37.540


def _hin(feature_id: str, name: str, lon0: float, lon1: float) -> DatasetFeature:
    return DatasetFeature(
        feature_id=feature_id,
        geometry=LineString([(lon0, _LAT + 0.0002), (lon1, _LAT + 0.0002)]),
        properties={"FullName": name, "StreetType": "Artery", "PostedSpee": 25, "HISN_2023": 1},
    )


def _cip(feature_id: str, name: str, bucket: str, geom) -> DatasetFeature:
    return DatasetFeature(
        feature_id=feature_id,
        geometry=geom,
        properties={"Name": name, "Category": "Pedestrian and Bike", "cip_bucket": bucket},
    )


def _service(proximity_buffer_m: float = 50.0) -> RouteIntersectionService:
    engine = SpatialAnalysisEngine(
        hin_features=[
            _hin("h1", "Main St", -77.4395, -77.4370),
            _hin("h2", "Main St", -77.4370, -77.4350),
        ],
        cip_features=[
            _cip("c1", "Plaza Trail", "planned", box(-77.4334, _LAT - 0.0002, -77.4322, _LAT + 0.0002)),
            # Runs ~2 km north-south: must be clipped to the neighbourhood of the route.
            _cip("c2", "Big Park", "construction", box(-77.4360, _LAT - 0.010, -77.4340, _LAT + 0.010)),
            _cip("c3", "Far Away", "completed", box(-77.40, 37.60, -77.39, 37.61)),
        ],
        proximity_buffer_m=proximity_buffer_m,
    )
    return RouteIntersectionService(settings=Settings(routing_provider="mock"), analysis_engine=engine)


def _plan(service: RouteIntersectionService | None = None):
    service = service or _service()
    result = service.analyze(RouteRequest(start=_START, end=_END, mode=TravelMode.WALKING))
    return build_navigation_plan(result, service.analysis_engine), service


def test_plan_has_one_card_per_street_and_per_project_in_reading_order() -> None:
    plan, _ = _plan()

    assert [c.id for c in plan.cards] == ["hin:Main St", "cip:c1", "cip:c2"]
    assert [c.bucket for c in plan.cards] == ["high_risk", "planned", "construction"]
    main = plan.cards[0]
    assert main.title == "Main St"
    assert main.detail == "Artery · 25 mph posted"
    assert main.dataset == "hin"


def test_hin_segments_of_one_street_merge_into_one_corridor() -> None:
    plan, _ = _plan()
    corridor = shape(plan.cards[0].corridor)

    assert corridor.geom_type in {"Polygon", "MultiPolygon"}
    for lon in (-77.4390, -77.4370, -77.4355):
        assert corridor.contains(Point(lon, _LAT)), lon
    assert not corridor.contains(Point(-77.4300, _LAT))


def test_corridor_is_clipped_near_the_route() -> None:
    plan, _ = _plan()
    big_park = next(c for c in plan.cards if c.id == "cip:c2")
    _, miny, _, maxy = shape(big_park.corridor).bounds

    assert miny > _LAT - 0.003
    assert maxy < _LAT + 0.003
    assert shape(big_park.corridor).contains(Point(-77.4350, _LAT))


def test_route_segments_cover_the_whole_route_in_order() -> None:
    plan, _ = _plan()
    segments = plan.route.segments

    assert segments[0].path[0] == pytest.approx([_START.lon, _START.lat])
    assert segments[-1].path[-1] == pytest.approx([_END.lon, _END.lat])
    for prev, nxt in zip(segments, segments[1:]):
        assert prev.path[-1] == pytest.approx(nxt.path[0])
        assert prev.bucket != nxt.bucket
    assert {s.bucket for s in segments} >= {"high_risk", "planned", "construction", "unaffected"}


def test_segments_agree_with_card_corridors_at_a_sample_point() -> None:
    plan, _ = _plan()
    high_risk = [s for s in plan.route.segments if s.bucket == "high_risk"]
    corridor = shape(plan.cards[0].corridor)

    assert high_risk
    path = high_risk[0].path
    midpoint = Point((path[0][0] + path[-1][0]) / 2, (path[0][1] + path[-1][1]) / 2)
    assert corridor.contains(midpoint)


def test_plan_lists_bucket_metadata_with_shared_colors() -> None:
    plan, _ = _plan()

    assert [b.key for b in plan.buckets] == [
        "high_risk", "planned", "construction", "completed", "unaffected"
    ]
    assert plan.buckets[0].color == "#ef4444"


def test_zero_buffer_still_yields_polygon_corridors_for_line_datasets() -> None:
    plan, _ = _plan(_service(proximity_buffer_m=0.0))
    hin_card = next((c for c in plan.cards if c.dataset == "hin"), None)

    if hin_card is not None:
        assert shape(hin_card.corridor).geom_type in {"Polygon", "MultiPolygon"}


def test_bucket_route_paths_marks_uncovered_route_as_unaffected() -> None:
    route = LineString([(-77.440, _LAT), (-77.430, _LAT)])
    corridors = {
        "high_risk": box(-77.439, _LAT - 0.001, -77.437, _LAT + 0.001),
        "completed": box(0, 0, 0, 0),
        "construction": box(0, 0, 0, 0),
        "planned": box(0, 0, 0, 0),
    }
    pieces = bucket_route_paths(route, corridors)

    assert [tag for tag, _ in pieces] == ["unaffected", "high_risk", "unaffected"]


def test_navigation_plan_endpoint(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(api, "get_cached_service", lambda settings: (service, datetime.now(timezone.utc)))
    client = TestClient(api.app)

    response = client.post(
        "/navigation-plan",
        json={
            "start": {"lon": _START.lon, "lat": _START.lat},
            "end": {"lon": _END.lon, "lat": _END.lat},
            "mode": "walking",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body["cards"]] == ["hin:Main St", "cip:c1", "cip:c2"]
    assert body["route"]["segments"]
    assert body["route"]["geometry"]["type"] == "LineString"

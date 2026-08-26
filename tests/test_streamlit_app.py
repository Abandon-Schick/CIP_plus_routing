from __future__ import annotations

import pytest
from shapely.geometry import LineString

from gis_route_app.analysis import SpatialAnalysisEngine
from gis_route_app.config import Settings
from gis_route_app.datasets import DatasetFeature
from gis_route_app.models import (
    Coordinate,
    RouteAnalysisResponse,
    RouteResponse,
    SegmentIntersection,
    TravelMode,
)
from gis_route_app.service import RouteIntersectionService
from gis_route_app.streamlit_app import (
    GeocodingError,
    _build_bucket_percentage_series,
    _build_cip_overlap_details_frame,
    _build_hin_overlap_details_frame,
    _build_route_overlap_segments,
    _geocode_address,
    _latest_completion_year,
    _parse_completion_year,
)


def test_geocode_address_returns_coordinate(monkeypatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [{"lat": "37.7749", "lon": "-122.4194"}]

    def fake_get(url: str, params: dict, headers: dict, timeout: int):
        assert "nominatim.openstreetmap.org/search" in url
        assert params["q"] == "San Francisco"
        assert params["format"] == "jsonv2"
        assert params["limit"] == 1
        assert "User-Agent" in headers
        assert timeout == 10
        return DummyResponse()

    monkeypatch.setattr("gis_route_app.streamlit_app.requests.get", fake_get)

    output = _geocode_address("San Francisco", timeout_seconds=10)

    assert output == Coordinate(lon=-122.4194, lat=37.7749)


def test_geocode_address_raises_on_empty() -> None:
    with pytest.raises(GeocodingError):
        _geocode_address("   ", timeout_seconds=5)


def test_geocode_address_raises_on_invalid_json(monkeypatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            raise ValueError("invalid json")

    def fake_get(url: str, params: dict, headers: dict, timeout: int):
        return DummyResponse()

    monkeypatch.setattr("gis_route_app.streamlit_app.requests.get", fake_get)

    with pytest.raises(GeocodingError, match="not valid JSON"):
        _geocode_address("San Francisco", timeout_seconds=5)


def test_geocode_address_raises_on_non_list_payload(monkeypatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"lat": "37.7749", "lon": "-122.4194"}

    def fake_get(url: str, params: dict, headers: dict, timeout: int):
        return DummyResponse()

    monkeypatch.setattr("gis_route_app.streamlit_app.requests.get", fake_get)

    with pytest.raises(GeocodingError, match="Unexpected geocoding response"):
        _geocode_address("San Francisco", timeout_seconds=5)


def test_build_cip_overlap_details_frame_empty_intersections() -> None:
    result = RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.DRIVING,
            distance_m=1000.0,
            duration_s=120.0,
            geojson={
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.43, 37.77], [-122.42, 37.77]],
                },
                "properties": {},
            },
        ),
        intersections=[],
    )
    frame = _build_cip_overlap_details_frame(result)
    assert frame.empty
    assert list(frame.columns) == [
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


def test_build_cip_overlap_details_frame_normalizes_and_sorts() -> None:
    result = RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.BIKING,
            distance_m=1800.0,
            duration_s=420.0,
            geojson={
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.43, 37.77], [-122.42, 37.77]],
                },
                "properties": {},
            },
        ),
        intersections=[
            SegmentIntersection(
                feature_id="CIP-1",
                dataset="cip",
                overlap_length_m=150.0,
                overlap_fraction_of_route=0.0833333,
                properties={
                    "project_name": "Protected Bike Lanes",
                    "category": "Mobility",
                    "description": "Protected lanes expansion.",
                    "cost": "$2.1M",
                    "phase": "Design",
                    "status": "Active",
                    "completion": "Q4 2027",
                },
            ),
            SegmentIntersection(
                feature_id="HIN-2",
                dataset="hin",
                overlap_length_m=100.0,
                overlap_fraction_of_route=0.0555555,
                properties={
                    "FullName": "Midlothian Tpke",
                    "StreetType": "Artery",
                    "Functional": "Principal Arterial",
                    "PostedSpee": 35,
                },
            ),
            SegmentIntersection(
                feature_id="HIN-1",
                dataset="hin",
                overlap_length_m=220.0,
                overlap_fraction_of_route=0.1222222,
                properties={
                    "FullName": "Walmsley Blvd",
                    "StreetType": "Artery",
                    "Functional": "Minor Arterial",
                    "PostedSpee": 25,
                },
            ),
        ],
    )
    frame = _build_cip_overlap_details_frame(result)
    assert list(frame.columns) == [
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
    assert frame["Name"].tolist() == ["Protected Bike Lanes"]
    assert frame["Overlap Percent"].tolist() == [8.33]


def test_build_hin_overlap_details_frame_empty_intersections() -> None:
    result = RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.DRIVING,
            distance_m=1000.0,
            duration_s=120.0,
            geojson={
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.43, 37.77], [-122.42, 37.77]],
                },
                "properties": {},
            },
        ),
        intersections=[],
    )
    frame = _build_hin_overlap_details_frame(result)
    assert frame.empty
    assert list(frame.columns) == [
        "Overlap Percent",
        "Name",
        "Street Type",
        "Functional",
        "Posted Speed",
    ]


def test_build_hin_overlap_details_frame_normalizes_and_sorts() -> None:
    result = RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.BIKING,
            distance_m=1800.0,
            duration_s=420.0,
            geojson={
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.43, 37.77], [-122.42, 37.77]],
                },
                "properties": {},
            },
        ),
        intersections=[
            SegmentIntersection(
                feature_id="CIP-1",
                dataset="cip",
                overlap_length_m=150.0,
                overlap_fraction_of_route=0.0833333,
                properties={
                    "project_name": "Protected Bike Lanes",
                },
            ),
            SegmentIntersection(
                feature_id="HIN-2",
                dataset="hin",
                overlap_length_m=100.0,
                overlap_fraction_of_route=0.0555555,
                properties={
                    "FullName": "Midlothian Tpke",
                    "StreetType": "Artery",
                    "Functional": "Principal Arterial",
                    "PostedSpee": 35,
                },
            ),
            SegmentIntersection(
                feature_id="HIN-1",
                dataset="hin",
                overlap_length_m=220.0,
                overlap_fraction_of_route=0.1222222,
                properties={
                    "RouteName": "Walmsley Blvd",
                    "StreetType": "Artery",
                    "Functional": "Minor Arterial",
                    "PostedSpee": 25,
                },
            ),
        ],
    )
    frame = _build_hin_overlap_details_frame(result)
    assert list(frame.columns) == [
        "Overlap Percent",
        "Name",
        "Street Type",
        "Functional",
        "Posted Speed",
    ]
    assert frame["Name"].tolist() == ["Walmsley Blvd", "Midlothian Tpke"]
    assert frame["Overlap Percent"].tolist() == [12.22, 5.56]


def test_build_route_overlap_segments_no_overlap_returns_single_gray_segment() -> None:
    route = RouteResponse(
        mode=TravelMode.DRIVING,
        distance_m=1000.0,
        duration_s=60.0,
        geojson={
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-122.43, 37.77], [-122.42, 37.77]],
            },
            "properties": {},
        },
    )
    result = RouteAnalysisResponse(route=route, intersections=[])
    frame = _build_route_overlap_segments(result, overlap_geometries=[])

    assert frame["segment_type"].tolist() == ["No overlap"]
    assert frame["percent"].tolist() == [100.0]


def test_build_route_overlap_segments_intersection_then_gap_then_intersection() -> None:
    route = RouteResponse(
        mode=TravelMode.BIKING,
        distance_m=1000.0,
        duration_s=120.0,
        geojson={
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[0.0, 0.0], [3.0, 0.0]],
            },
            "properties": {},
        },
    )
    result = RouteAnalysisResponse(route=route, intersections=[])
    # Overlap pieces at [0.5, 1.0] and [2.0, 2.5] along the route.
    overlap_geometries = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0.5, 0.0], [1.0, 0.0]]},
            "properties": {},
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[2.0, 0.0], [2.5, 0.0]]},
            "properties": {},
        },
    ]
    frame = _build_route_overlap_segments(result, overlap_geometries=overlap_geometries)

    assert frame["segment_type"].tolist() == [
        "No overlap",
        "Overlap",
        "No overlap",
        "Overlap",
        "No overlap",
    ]
    rounded = [round(v, 2) for v in frame["percent"].tolist()]
    assert rounded == [16.67, 16.67, 33.33, 16.67, 16.67]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Fall 2031", 2031),
        ("9/30/2026", 2026),
        ("Winter 2025", 2025),
        ("2031", 2031),
        ("December 2027", 2027),
        ("TBD", None),
        ("N/A", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_completion_year(value, expected) -> None:
    assert _parse_completion_year(value) == expected


def test_latest_completion_year_ignores_non_cip_and_unparseable() -> None:
    result = RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.DRIVING, distance_m=1000.0, duration_s=60.0,
            geojson={"type": "Feature", "geometry": {"type": "LineString", "coordinates": []}, "properties": {}},
        ),
        intersections=[
            SegmentIntersection(
                feature_id="CIP-1", dataset="cip", overlap_length_m=10.0,
                overlap_fraction_of_route=0.1, properties={"Completion": "Fall 2027"},
            ),
            SegmentIntersection(
                feature_id="CIP-2", dataset="cip", overlap_length_m=10.0,
                overlap_fraction_of_route=0.1, properties={"Completion": "TBD"},
            ),
            SegmentIntersection(
                feature_id="CIP-3", dataset="cip", overlap_length_m=10.0,
                overlap_fraction_of_route=0.1, properties={"Completion": "12/1/2031"},
            ),
            SegmentIntersection(
                feature_id="HIN-1", dataset="hin", overlap_length_m=10.0,
                overlap_fraction_of_route=0.1, properties={"Completion": "1999"},
            ),
        ],
    )

    assert _latest_completion_year(result) == 2031


def test_latest_completion_year_none_when_no_cip_dates() -> None:
    result = RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.DRIVING, distance_m=1000.0, duration_s=60.0,
            geojson={"type": "Feature", "geometry": {"type": "LineString", "coordinates": []}, "properties": {}},
        ),
        intersections=[],
    )
    assert _latest_completion_year(result) is None


def _make_service(hin_features, cip_features) -> RouteIntersectionService:
    return RouteIntersectionService(
        settings=Settings(),
        analysis_engine=SpatialAnalysisEngine(
            hin_features=hin_features, cip_features=cip_features, proximity_buffer_m=0.0
        ),
    )


def _route_result(coords) -> RouteAnalysisResponse:
    return RouteAnalysisResponse(
        route=RouteResponse(
            mode=TravelMode.DRIVING,
            distance_m=1000.0,
            duration_s=60.0,
            geojson={"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": {}},
        ),
        intersections=[],
    )


def test_build_bucket_percentage_series_splits_by_bucket_and_sums_to_100() -> None:
    # Route split into three equal thirds, one bucket each.
    route_coords = [[-122.430, 37.772], [-122.420, 37.772]]
    hin_features = [
        DatasetFeature(
            feature_id="HIN-1",
            geometry=LineString([(-122.430, 37.772), (-122.427, 37.772)]),
            properties={},
        )
    ]
    cip_features = [
        DatasetFeature(
            feature_id="CIP-CONSTRUCTION",
            geometry=LineString([(-122.427, 37.772), (-122.424, 37.772)]),
            properties={"cip_bucket": "construction"},
        ),
        DatasetFeature(
            feature_id="CIP-PLANNED",
            geometry=LineString([(-122.424, 37.772), (-122.420, 37.772)]),
            properties={"cip_bucket": "planned"},
        ),
    ]
    service = _make_service(hin_features, cip_features)
    result = _route_result(route_coords)

    frame = _build_bucket_percentage_series(result, service)
    pct = {row["Bucket"]: row["Percent"] for _, row in frame.iterrows()}

    assert pct["High risk"] > 0
    assert pct["Construction"] > 0
    assert pct["Planned changes"] > 0
    assert pct["Newly fixed"] == 0
    assert sum(pct.values()) == pytest.approx(100.0, abs=0.01)


def test_build_bucket_percentage_series_high_risk_wins_over_cip_on_overlap() -> None:
    # HIN and a "completed" CIP project cover the exact same stretch of route.
    route_coords = [[-122.430, 37.772], [-122.420, 37.772]]
    overlap_segment = [(-122.430, 37.772), (-122.420, 37.772)]
    hin_features = [
        DatasetFeature(feature_id="HIN-1", geometry=LineString(overlap_segment), properties={})
    ]
    cip_features = [
        DatasetFeature(
            feature_id="CIP-COMPLETED",
            geometry=LineString(overlap_segment),
            properties={"cip_bucket": "completed"},
        )
    ]
    service = _make_service(hin_features, cip_features)
    result = _route_result(route_coords)

    frame = _build_bucket_percentage_series(result, service)
    pct = {row["Bucket"]: row["Percent"] for _, row in frame.iterrows()}

    assert pct["High risk"] == pytest.approx(100.0, abs=0.01)
    assert pct["Newly fixed"] == 0

from __future__ import annotations

import pytest

from gis_route_app.models import (
    Coordinate,
    RouteAnalysisResponse,
    RouteResponse,
    SegmentIntersection,
    TravelMode,
)
from gis_route_app.streamlit_app import (
    GeocodingError,
    _autocomplete_addresses,
    _build_overlap_details_frame,
    _geocode_address,
    _resolve_selected_address,
    _swap_addresses,
    _typed_address_option,
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


def test_autocomplete_addresses_returns_display_names(monkeypatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {"display_name": "San Francisco, California, United States"},
                {"display_name": "San Francisco Bay, California, United States"},
            ]

    def fake_get(url: str, params: dict, headers: dict, timeout: int):
        assert "nominatim.openstreetmap.org/search" in url
        assert params["q"] == "San Fran"
        assert params["format"] == "jsonv2"
        assert params["limit"] == 5
        assert "User-Agent" in headers
        assert timeout == 12
        return DummyResponse()

    monkeypatch.setattr("gis_route_app.streamlit_app.requests.get", fake_get)

    output = _autocomplete_addresses("San Fran", timeout_seconds=12)

    assert output == [
        "San Francisco, California, United States",
        "San Francisco Bay, California, United States",
    ]


def test_autocomplete_addresses_skips_short_queries() -> None:
    assert _autocomplete_addresses("ab", timeout_seconds=5) == []


def test_resolve_selected_address_returns_typed_value_for_typed_option() -> None:
    typed = "1 Market St, San Francisco, CA"
    selected = _typed_address_option(typed)
    assert _resolve_selected_address(typed, selected) == typed


def test_resolve_selected_address_returns_selected_suggestion() -> None:
    typed = "Market"
    selected = "Market Street, San Francisco, California, United States"
    assert _resolve_selected_address(typed, selected) == selected


def test_typed_address_option_prefixes_typed_value() -> None:
    assert _typed_address_option("abc") == "Use typed address: abc"


def test_swap_addresses_swaps_values() -> None:
    swapped_start, swapped_end = _swap_addresses("start", "end")
    assert swapped_start == "end"
    assert swapped_end == "start"


def test_build_overlap_details_frame_empty_intersections() -> None:
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
    frame = _build_overlap_details_frame(result)
    assert frame.empty
    assert list(frame.columns) == [
        "dataset",
        "feature_id",
        "overlap_length_m",
        "overlap_fraction_of_route",
        "overlap_percent",
    ]


def test_build_overlap_details_frame_normalizes_and_sorts() -> None:
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
                properties={},
            ),
            SegmentIntersection(
                feature_id="HIN-2",
                dataset="hin",
                overlap_length_m=100.0,
                overlap_fraction_of_route=0.0555555,
                properties={},
            ),
            SegmentIntersection(
                feature_id="HIN-1",
                dataset="hin",
                overlap_length_m=220.0,
                overlap_fraction_of_route=0.1222222,
                properties={},
            ),
        ],
    )
    frame = _build_overlap_details_frame(result)
    assert frame["dataset"].tolist() == ["CIP", "HIN", "HIN"]
    assert frame["feature_id"].tolist() == ["CIP-1", "HIN-1", "HIN-2"]
    assert frame["overlap_percent"].tolist() == [8.33, 12.22, 5.56]

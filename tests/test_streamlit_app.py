from __future__ import annotations

import pytest

from gis_route_app.models import Coordinate
from gis_route_app.streamlit_app import (
    GeocodingError,
    _autocomplete_addresses,
    _geocode_address,
    _resolve_selected_address,
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
    selected = f"Use typed address: {typed}"
    assert _resolve_selected_address(typed, selected) == typed


def test_resolve_selected_address_returns_selected_suggestion() -> None:
    typed = "Market"
    selected = "Market Street, San Francisco, California, United States"
    assert _resolve_selected_address(typed, selected) == selected

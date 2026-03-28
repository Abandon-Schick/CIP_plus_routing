from __future__ import annotations

import pytest

from gis_route_app.models import Coordinate
from gis_route_app.streamlit_app import GeocodingError, _geocode_address


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

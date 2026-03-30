from __future__ import annotations

import json

import requests
from pyproj import Transformer
from shapely.geometry import LineString, shape

from gis_route_app.datasets import load_geojson_features


def test_load_geojson_features_skips_null_geometry(tmp_path) -> None:
    source = tmp_path / "sample.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": "A"},
                        "geometry": None,
                    },
                    {
                        "type": "Feature",
                        "properties": {"id": "B"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-122.43, 37.77], [-122.42, 37.77]],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    features = load_geojson_features(source, fallback_prefix="test")

    assert len(features) == 1
    assert features[0].feature_id == "B"


def test_load_geojson_features_from_http_url(monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "CIP-REMOTE-1"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.431, 37.772], [-122.421, 37.772]],
                },
            }
        ],
    }

    def fake_get(url: str, timeout: int):
        assert url.startswith("https://services1.arcgis.com/")
        assert timeout == 15
        return DummyResponse(payload)

    monkeypatch.setattr("gis_route_app.datasets.requests.get", fake_get)

    features = load_geojson_features(
        "https://services1.arcgis.com/k3vhq11XkBNeeOfM/arcgis/rest/services/FY23_CIP_Polygon_Layers/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson",
        fallback_prefix="cip",
        timeout_seconds=15,
    )

    assert len(features) == 1
    assert features[0].feature_id == "CIP-REMOTE-1"


def test_load_geojson_features_retries_pending_http_payload(monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    pending_payload = {"status": "Pending", "message": "building"}
    ready_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "HIN-READY-1"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.431, 37.772], [-122.421, 37.772]],
                },
            }
        ],
    }

    calls = {"count": 0}

    def fake_get(url: str, timeout: int):
        calls["count"] += 1
        if calls["count"] < 3:
            return DummyResponse(pending_payload)
        return DummyResponse(ready_payload)

    monkeypatch.setattr("gis_route_app.datasets.requests.get", fake_get)
    monkeypatch.setattr("gis_route_app.datasets.time.sleep", lambda *_args, **_kwargs: None)

    features = load_geojson_features(
        "https://www.virginiaroads.org/api/download/v1/items/x/geojson?layers=1",
        fallback_prefix="hin",
        timeout_seconds=15,
    )

    assert calls["count"] == 3
    assert len(features) == 1
    assert features[0].feature_id == "HIN-READY-1"


def test_load_geojson_features_raises_after_pending_retries(monkeypatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"status": "Pending", "message": "still building"}

    def fake_get(url: str, timeout: int):
        return DummyResponse()

    monkeypatch.setattr("gis_route_app.datasets.requests.get", fake_get)
    monkeypatch.setattr("gis_route_app.datasets.time.sleep", lambda *_args, **_kwargs: None)

    try:
        load_geojson_features(
            "https://www.virginiaroads.org/api/download/v1/items/x/geojson?layers=1",
            fallback_prefix="hin",
            timeout_seconds=15,
        )
        assert False, "Expected ValueError for unresolved pending response"
    except ValueError as exc:
        assert "must be a FeatureCollection" in str(exc)


def test_load_geojson_reprojects_web_mercator_when_crs_declared(tmp_path) -> None:
    to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    lon_lat = [(-77.5229, 37.50195), (-77.5224, 37.50204)]
    coords_3857 = [to_3857.transform(lon, lat) for lon, lat in lon_lat]

    source = tmp_path / "hin_webmerc.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 999},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords_3857,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    features = load_geojson_features(source, fallback_prefix="hin")
    assert len(features) == 1
    loaded_coords = list(shape(features[0].geometry).coords)
    for (lon, lat), (ex_lon, ex_lat) in zip(loaded_coords, lon_lat, strict=True):
        assert abs(lon - ex_lon) < 1e-4
        assert abs(lat - ex_lat) < 1e-4

    hin_line = features[0].geometry
    mid = hin_line.interpolate(0.5, normalized=True)
    route = LineString([(mid.x - 0.02, mid.y), (mid.x + 0.02, mid.y)])
    overlap = route.intersection(hin_line)
    assert not overlap.is_empty


def test_route_intersects_virginia_hin_api_geojson() -> None:
    """Live check: default HIN URL overlaps real routes when reprojected (skipped if unreachable)."""
    import pytest

    url = (
        "https://www.virginiaroads.org/api/download/v1/items/"
        "2052af10bbc04cb88adf4fd87641bb65/geojson?layers=1"
    )
    try:
        features = load_geojson_features(url, fallback_prefix="hin", timeout_seconds=60)
    except (OSError, requests.RequestException, ValueError):
        pytest.skip("HIN API unreachable")
    # Straight line along Midlothian Tpke area (Richmond) where HIN segments exist
    route = LineString([(-77.53, 37.50), (-77.50, 37.51)])
    any_overlap = False
    for f in features:
        if not route.intersection(f.geometry).is_empty:
            any_overlap = True
            break
    assert any_overlap, "expected at least one HIN segment to intersect a corridor in the dataset"


from __future__ import annotations

import json

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


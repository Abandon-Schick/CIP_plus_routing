from gis_route_app.config import Settings
from gis_route_app.models import Coordinate, RouteRequest, TravelMode
from gis_route_app.service import RouteIntersectionService


def test_service_analyze_with_sample_data() -> None:
    settings = Settings(routing_provider="mock")
    service = RouteIntersectionService.from_data_files(
        settings=settings,
        hin_path="data/hin.geojson",
        cip_path="data/cip.geojson",
    )
    req = RouteRequest(
        start=Coordinate(lon=-122.431, lat=37.772),
        end=Coordinate(lon=-122.421, lat=37.772),
        mode=TravelMode.BIKING,
    )

    result = service.analyze(req)

    assert result.route.mode == TravelMode.BIKING
    assert result.route.distance_m > 0
    assert len(result.intersections) >= 1
    datasets = {item.dataset for item in result.intersections}
    assert datasets.issubset({"hin", "cip"})
    for item in result.intersections:
        assert 0.0 <= item.overlap_fraction_of_route <= 1.0


def test_service_from_data_files_falls_back_to_local_hin(
    monkeypatch, tmp_path
) -> None:
    cip_path = tmp_path / "cip.geojson"
    cip_path.write_text(
        """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {"id": "CIP-1"},
      "geometry": {"type": "LineString", "coordinates": [[-122.43, 37.77], [-122.42, 37.77]]}
    }
  ]
}
""",
        encoding="utf-8",
    )
    settings = Settings(routing_provider="mock")
    calls: list[tuple[str, str]] = []

    real_loader = __import__("gis_route_app.datasets", fromlist=["load_geojson_features"])
    original_load = real_loader.load_geojson_features

    def fake_load_geojson_features(source, fallback_prefix, timeout_seconds=30):
        source_str = str(source)
        calls.append((source_str, fallback_prefix))
        if source_str == "https://example.com/hin.geojson":
            raise ValueError("remote hin failed")
        return original_load(source, fallback_prefix, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(
        "gis_route_app.service.load_geojson_features",
        fake_load_geojson_features,
    )

    service = RouteIntersectionService.from_data_files(
        settings=settings,
        hin_path="https://example.com/hin.geojson",
        cip_path=cip_path,
    )

    assert service.analysis_engine.hin_features
    assert any(
        source == "data/hin.geojson" and prefix == "hin" for source, prefix in calls
    )

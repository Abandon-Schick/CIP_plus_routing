import pytest

from gis_route_app.config import Settings
from gis_route_app.models import Coordinate, RouteRequest, TravelMode
from gis_route_app.routing import RoutingError
from gis_route_app.service import CachedServiceProvider, RouteIntersectionService


def _local_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        routing_provider="mock",
        hin_data_source="data/hin.geojson",
        cip_data_source="data/cip.geojson",
        cip_snapshot_path=str(tmp_path / "cip_snapshot.json"),
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_service_analyze_with_sample_data(tmp_path) -> None:
    settings = Settings(
        routing_provider="mock", cip_snapshot_path=str(tmp_path / "cip_snapshot.json")
    )
    service = RouteIntersectionService.from_data_files(
        settings=settings,
        hin_path="data/hin.geojson",
        cip_path="data/cip.geojson",
    )
    # Endpoints of a 2-vertex HIN segment (Broad Rock Blvd area) so mock straight-line routing
    # lies exactly on the network and overlap exceeds the 50 m analysis threshold.
    req = RouteRequest(
        start=Coordinate(lon=-77.487006716845002, lat=37.467975165527903),
        end=Coordinate(lon=-77.486091456900496, lat=37.468371784651197),
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
    settings = Settings(
        routing_provider="mock", cip_snapshot_path=str(tmp_path / "cip_snapshot.json")
    )
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


def test_cached_service_provider_reuses_within_interval(tmp_path) -> None:
    settings = _local_settings(tmp_path, data_refresh_interval_seconds=3600.0)
    provider = CachedServiceProvider()

    service_a, built_at_a = provider.get(settings)
    service_b, built_at_b = provider.get(settings)

    assert service_a is service_b
    assert built_at_a == built_at_b


def test_cached_service_provider_rebuilds_when_interval_elapsed(tmp_path) -> None:
    # A zero-second interval means the cached entry is always considered stale.
    settings = _local_settings(tmp_path, data_refresh_interval_seconds=0.0)
    provider = CachedServiceProvider()

    service_a, _ = provider.get(settings)
    service_b, _ = provider.get(settings)

    assert service_a is not service_b


def test_cached_service_provider_refresh_forces_rebuild(tmp_path) -> None:
    settings = _local_settings(tmp_path, data_refresh_interval_seconds=3600.0)
    provider = CachedServiceProvider()

    service_a, _ = provider.get(settings)
    service_b, _ = provider.refresh(settings)
    service_c, _ = provider.get(settings)

    assert service_a is not service_b
    assert service_b is service_c


def test_cached_service_provider_keys_by_settings(tmp_path) -> None:
    settings_a = _local_settings(tmp_path, cip_snapshot_path=str(tmp_path / "a.json"))
    settings_b = _local_settings(tmp_path, cip_snapshot_path=str(tmp_path / "b.json"))
    provider = CachedServiceProvider()

    service_a, _ = provider.get(settings_a)
    service_b, _ = provider.get(settings_b)

    assert service_a is not service_b


def test_analyze_routing_provider_override_falls_back_from_ors_to_mock(tmp_path) -> None:
    # "ors" with no API key raises RoutingError; the override lets a caller retry
    # with "mock" on the same (already-loaded) service instead of rebuilding it.
    settings = _local_settings(tmp_path, routing_provider="ors", openrouteservice_api_key=None)
    service = RouteIntersectionService.from_settings(settings=settings)
    req = RouteRequest(
        start=Coordinate(lon=-77.487006716845002, lat=37.467975165527903),
        end=Coordinate(lon=-77.486091456900496, lat=37.468371784651197),
        mode=TravelMode.DRIVING,
    )

    with pytest.raises(RoutingError):
        service.analyze(req)

    result = service.analyze(req, routing_provider="mock")

    assert result.route.mode == TravelMode.DRIVING
    assert result.route.distance_m > 0

from gis_route_app.config import Settings
from gis_route_app.models import Coordinate, RouteRequest, TravelMode
from gis_route_app.service import RouteIntersectionService


def test_service_analyze_with_sample_data(monkeypatch) -> None:
    class DummyResponse:
        ok = True
        status_code = 200
        text = ""

        def json(self):
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-122.431, 37.772], [-122.421, 37.772]],
                        },
                        "properties": {"summary": {"distance": 881.0, "duration": 220.0}},
                    }
                ],
            }

    def fake_post(url: str, json: dict, headers: dict, timeout: int):
        assert "openrouteservice.org" in url
        assert json["coordinates"] == [[-122.431, 37.772], [-122.421, 37.772]]
        assert headers["Authorization"] == "test-key"
        assert timeout == 15
        return DummyResponse()

    monkeypatch.setattr("gis_route_app.routing.requests.post", fake_post)

    settings = Settings(routing_provider="ors", openrouteservice_api_key="test-key")
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

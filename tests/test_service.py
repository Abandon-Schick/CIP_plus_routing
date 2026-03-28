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

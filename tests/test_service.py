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

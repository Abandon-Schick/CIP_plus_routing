from shapely.geometry import LineString

from gis_route_app.analysis import SpatialAnalysisEngine
from gis_route_app.datasets import DatasetFeature


def test_route_intersects_hin_and_cip_segments() -> None:
    route = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-122.430, 37.772], [-122.420, 37.772]],
        },
        "properties": {},
    }
    hin_features = [
        DatasetFeature(
            feature_id="HIN-X",
            geometry=LineString([(-122.429, 37.772), (-122.425, 37.772)]),
            properties={"kind": "hin"},
        )
    ]
    cip_features = [
        DatasetFeature(
            feature_id="CIP-X",
            geometry=LineString([(-122.426, 37.772), (-122.421, 37.772)]),
            properties={"kind": "cip"},
        )
    ]

    engine = SpatialAnalysisEngine(hin_features=hin_features, cip_features=cip_features)
    intersections = engine.analyze_route(route)

    assert len(intersections) == 2
    by_id = {item.feature_id: item for item in intersections}
    assert by_id["HIN-X"].dataset == "hin"
    assert by_id["CIP-X"].dataset == "cip"
    assert by_id["HIN-X"].overlap_length_m > 0
    assert by_id["CIP-X"].overlap_length_m > 0


def test_near_miss_parallel_lines_within_proximity_buffer() -> None:
    """Lines ~35 m apart should count with default 50 m proximity; not with buffer disabled."""
    offset_deg = 35.0 / 111_320.0
    route = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-122.430, 37.772], [-122.420, 37.772]],
        },
        "properties": {},
    }
    hin_features = [
        DatasetFeature(
            feature_id="HIN-OFFSET",
            geometry=LineString(
                [(-122.429, 37.772 + offset_deg), (-122.425, 37.772 + offset_deg)]
            ),
            properties={"kind": "hin"},
        )
    ]
    permissive = SpatialAnalysisEngine(
        hin_features=hin_features, cip_features=[], proximity_buffer_m=50.0
    )
    strict = SpatialAnalysisEngine(
        hin_features=hin_features, cip_features=[], proximity_buffer_m=0.0
    )
    assert len(strict.analyze_route(route)) == 0
    hits = permissive.analyze_route(route)
    assert len(hits) == 1
    assert hits[0].feature_id == "HIN-OFFSET"
    assert hits[0].overlap_length_m > 0

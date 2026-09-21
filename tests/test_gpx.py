import pytest

from gis_route_app.gpx import load_static_route, parse_gpx
from gis_route_app.models import TravelMode

_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
 <metadata><name>Metadata name</name></metadata>
 <wpt lat="10" lon="10"><name>A waypoint, not part of the route</name></wpt>
 <trk>
  <name>Sunday loop</name>
  <type>cycling</type>
  <trkseg>
   <trkpt lat="37.54" lon="-77.44"><ele>1</ele></trkpt>
   <trkpt lat="37.54" lon="-77.44"><ele>2</ele></trkpt>
   <trkpt lat="37.55" lon="-77.44"/>
  </trkseg>
  <trkseg>
   <trkpt lat="37.55" lon="-77.43"/>
  </trkseg>
 </trk>
</gpx>
"""


def test_parse_gpx_joins_segments_drops_repeats_and_ignores_waypoints() -> None:
    route = parse_gpx(_GPX, route_id="loop")

    assert route.route_id == "loop"
    assert route.name == "Sunday loop"
    assert route.coordinates == [(-77.44, 37.54), (-77.44, 37.55), (-77.43, 37.55)]


def test_parse_gpx_reads_the_travel_mode_from_the_file_type() -> None:
    assert parse_gpx(_GPX).mode == TravelMode.BIKING
    assert parse_gpx(_GPX.replace("cycling", "kayaking")).mode is None
    assert parse_gpx(_GPX.replace("<type>cycling</type>", "")).mode is None


def test_parse_gpx_falls_back_to_route_points_and_metadata_name() -> None:
    xml = """<gpx xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>Planned</name></metadata>
      <rte><rtept lat="1" lon="2"/><rtept lat="3" lon="4"/></rte></gpx>"""

    route = parse_gpx(xml)

    assert route.coordinates == [(2.0, 1.0), (4.0, 3.0)]
    assert route.name == "Planned"


@pytest.mark.parametrize(
    "xml",
    [
        "not xml at all",
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="1" lon="2"/></trkseg></trk></gpx>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="x" lon="2"/><trkpt lat="1" lon="2"/></trkseg></trk></gpx>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="95" lon="2"/><trkpt lat="1" lon="2"/></trkseg></trk></gpx>',
    ],
)
def test_parse_gpx_rejects_files_without_a_usable_route(xml: str) -> None:
    with pytest.raises(ValueError):
        parse_gpx(xml)


def test_load_static_route_reads_the_bundled_demo_route() -> None:
    route = load_static_route("war-on-cars-bike-tour", "data/routes")

    assert route.name.startswith("War on Cars Bike Tour")
    assert route.mode == TravelMode.BIKING
    assert len(route.coordinates) > 100


@pytest.mark.parametrize("bad_id", ["../secrets", "a/b", "UPPER", "", "-lead", "a.gpx"])
def test_load_static_route_rejects_ids_that_could_escape_the_folder(bad_id: str) -> None:
    with pytest.raises(ValueError):
        load_static_route(bad_id, "data/routes")


def test_load_static_route_reports_unknown_ids() -> None:
    with pytest.raises(FileNotFoundError):
        load_static_route("no-such-route", "data/routes")

"""GPX routes: parse a GPX file into a route line, and find the bundled ones by id.

Uses the standard-library XML parser, which is only safe for trusted files. Swap in
``defusedxml`` before accepting user uploads.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .models import TravelMode

_ROUTE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# GPX <type> values (Strava, Garmin, ...) that tell us how the route is traveled.
_MODE_BY_GPX_TYPE = {
    "cycling": TravelMode.BIKING,
    "biking": TravelMode.BIKING,
    "ride": TravelMode.BIKING,
    "walking": TravelMode.WALKING,
    "hiking": TravelMode.WALKING,
    "running": TravelMode.WALKING,
    "run": TravelMode.WALKING,
    "walk": TravelMode.WALKING,
}


@dataclass(frozen=True)
class GpxRoute:
    route_id: str
    name: str
    coordinates: list[tuple[float, float]]  # (lon, lat), WGS84
    mode: TravelMode | None  # from the file's <type>, when it names one we know


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def parse_gpx(xml_text: str, route_id: str = "gpx") -> GpxRoute:
    """Track points (or, failing that, route points) as one line; waypoints are ignored."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Not a valid GPX file: {exc}") from exc

    points = root.findall(".//{*}trk/{*}trkseg/{*}trkpt") or root.findall(".//{*}rte/{*}rtept")
    coordinates: list[tuple[float, float]] = []
    for point in points:
        try:
            lon, lat = float(point.attrib["lon"]), float(point.attrib["lat"])
        except (KeyError, ValueError) as exc:
            raise ValueError("GPX point without a valid lat/lon") from exc
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("GPX point outside valid coordinates")
        if not coordinates or coordinates[-1] != (lon, lat):
            coordinates.append((lon, lat))
    if len(coordinates) < 2:
        raise ValueError("GPX file has no route (needs at least two track or route points)")

    name = (
        _text(root.find(".//{*}trk/{*}name"))
        or _text(root.find(".//{*}rte/{*}name"))
        or _text(root.find("{*}metadata/{*}name"))
        or route_id
    )
    type_element = root.find(".//{*}trk/{*}type")
    if type_element is None:
        type_element = root.find(".//{*}rte/{*}type")
    gpx_type = _text(type_element).lower()
    return GpxRoute(
        route_id=route_id,
        name=name,
        coordinates=coordinates,
        mode=_MODE_BY_GPX_TYPE.get(gpx_type),
    )


def load_static_route(route_id: str, routes_dir: str | Path) -> GpxRoute:
    """Load ``<routes_dir>/<route_id>.gpx``. Ids are lowercase letters, digits and hyphens."""
    if not _ROUTE_ID_RE.match(route_id):
        raise ValueError(f"Invalid route id: {route_id!r}")
    path = Path(routes_dir) / f"{route_id}.gpx"
    if not path.is_file():
        raise FileNotFoundError(f"No such route: {route_id}")
    return parse_gpx(path.read_text(encoding="utf-8"), route_id=route_id)

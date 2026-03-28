"""Command-line interface for GIS route intersection analysis."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

from .config import get_settings
from .models import Coordinate, RouteRequest, TravelMode
from .service import RouteIntersectionService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gis-route-cli",
        description=(
            "Compute driving/walking/biking routes and intersections with "
            "High Injury Network and Capital Improvement Project datasets."
        ),
    )
    parser.add_argument("--start-lon", type=float, required=True)
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--end-lon", type=float, required=True)
    parser.add_argument("--end-lat", type=float, required=True)
    parser.add_argument(
        "--mode",
        type=str,
        choices=[mode.value for mode in TravelMode],
        default=TravelMode.DRIVING.value,
    )
    parser.add_argument(
        "--hin-path",
        "--hin-source",
        dest="hin_source",
        type=str,
        default=None,
        help="HIN GeoJSON source (file path or HTTP URL). Defaults to HIN_DATA_SOURCE.",
    )
    parser.add_argument(
        "--cip-path",
        "--cip-source",
        dest="cip_source",
        type=str,
        default=None,
        help="CIP GeoJSON source (file path or HTTP URL). Defaults to CIP_DATA_SOURCE.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    if args.hin_source or args.cip_source:
        settings = replace(
            settings,
            hin_data_source=args.hin_source or settings.hin_data_source,
            cip_data_source=args.cip_source or settings.cip_data_source,
        )

    service = RouteIntersectionService.from_settings(settings=settings)

    request = RouteRequest(
        start=Coordinate(lon=args.start_lon, lat=args.start_lat),
        end=Coordinate(lon=args.end_lon, lat=args.end_lat),
        mode=TravelMode(args.mode),
    )
    result = service.analyze(request)

    payload = result.model_dump(mode="json")
    if args.pretty:
        print(json.dumps(payload, indent=2))
        return
    print(json.dumps(payload))

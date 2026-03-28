"""Command-line interface for GIS route intersection analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    parser.add_argument("--hin-path", type=str, default="data/hin.geojson")
    parser.add_argument("--cip-path", type=str, default="data/cip.geojson")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    service = RouteIntersectionService.from_data_files(
        settings=settings,
        hin_path=Path(args.hin_path),
        cip_path=Path(args.cip_path),
    )

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

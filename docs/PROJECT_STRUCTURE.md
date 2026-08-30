# Project Structure

## Directory Layout

- `src/gis_route_app/` -- Python package: routing, spatial analysis, categorization,
  the FastAPI service, the CLI, and the Streamlit dashboard.
- `tests/` -- pytest suite, one `test_*.py` file per module in
  `src/gis_route_app/` (flat, no `unit/`/`integration/` split).
- `data/` -- sample/fallback GeoJSON datasets (`hin.geojson`, `cip.geojson`) and the
  gitignored `cip_snapshot.json` state file the categorization snapshot store writes.
- `docs/` -- this file and other project documentation.

## Directory Descriptions

### `src/gis_route_app/`
- `routing.py` -- route providers (`mock` for local dev, `ors` for OpenRouteService)
- `analysis.py` -- spatial intersection engine (Shapely + geodesic length)
- `categorization.py` -- CIP project bucketing (planned/construction/completed) and the
  `GlobalID`-keyed snapshot store that tracks projects across pulls
- `datasets.py` -- GeoJSON loading (local file or HTTP), CRS reprojection to WGS84
- `service.py` -- orchestrates routing + analysis + categorization; owns the
  process-wide cached-service layer (`get_cached_service`/`refresh_cached_service`)
- `config.py` -- `Settings` dataclass, loaded from environment variables via `.env`
- `api.py` -- FastAPI app (`/health`, `/analyze-route`, `/refresh-data`)
- `cli.py` -- `gis-route-cli` entry point
- `streamlit_app.py` -- the dashboard

### `tests/`
Mirrors the package layout: `test_analysis_engine.py`, `test_categorization.py`,
`test_datasets.py`, `test_service.py`, `test_streamlit_app.py`, etc.

## Naming Conventions

Standard Python: `snake_case` for files, functions, and variables; `PascalCase` for
classes (e.g. `RouteIntersectionService`, `CipSnapshotStore`).

## Development Workflow

See the Quickstart in [README.md](../README.md) for install/run/test commands.

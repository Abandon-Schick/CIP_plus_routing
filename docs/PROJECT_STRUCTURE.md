# Project Structure

## Directory Layout

- `src/gis_route_app/` -- Python package: routing, spatial analysis, categorization,
  the FastAPI service, the CLI, and the Streamlit dashboard.
- `tests/` -- pytest suite, one `test_*.py` file per module in
  `src/gis_route_app/` (flat, no `unit/`/`integration/` split).
- `web/navigate/` -- static browser client for navigation mode (MapLibre GL JS, plain ES
  modules, no build step); FastAPI serves it at `/navigate/`.
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
- `summary.py` -- citizen-facing bucket vocabulary (order, labels, colors) and the
  per-feature text (`hin_fields`/`cip_fields`, `*_detail`) shared by every UI
- `route_partition.py` -- splits a route into bucket-tagged stretches (overlap
  priority, per-bucket corridors); shared by the Streamlit map and navigation mode
- `navigation.py` -- builds the navigation-mode payload (route colored by bucket, plus
  one card + clipped corridor polygon per HIN street / CIP project)
- `config.py` -- `Settings` dataclass, loaded from environment variables via `.env`
- `api.py` -- FastAPI app (`/health`, `/analyze-route`, `/navigation-plan`,
  `/refresh-data`) and the static mount for `web/navigate/`
- `cli.py` -- `gis-route-cli` entry point
- `streamlit_app.py` -- the dashboard

### `web/navigate/`
- `index.html`, `nav.css` -- page shell: full-screen map, info bar, simulator panel
- `main.js` -- loads `/navigation-plan`, draws the route, follows the position (map turns
  to the travel direction) and renders the cards for the corridors the position is in
- `geo.js` -- pure geometry (distance, bearing, point-in-polygon), no DOM or map
- `simulator.js` -- fake GPS that walks the route; a real-location source must emit the
  same fix shape (`{lon, lat, heading, distanceAlongM}`)

All position handling happens in the browser; no location is sent to the server.

### `tests/`
Mirrors the package layout: `test_analysis_engine.py`, `test_categorization.py`,
`test_datasets.py`, `test_service.py`, `test_streamlit_app.py`, etc.

## Naming Conventions

Standard Python: `snake_case` for files, functions, and variables; `PascalCase` for
classes (e.g. `RouteIntersectionService`, `CipSnapshotStore`).

## Development Workflow

See the Quickstart in [README.md](../README.md) for install/run/test commands.

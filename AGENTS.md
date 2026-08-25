# AGENTS.md

## Cursor Cloud specific instructions

This is a Python GIS application that computes driving/walking/biking routes and detects
their intersection with the High Injury Network (HIN) and Capital Improvement Projects
(CIP) datasets. It exposes a FastAPI service, a CLI, and a Streamlit dashboard.

### Key commands

| Action | Command |
|--------|---------|
| Install (editable, with dev deps) | `pip install -e ".[dev]"` |
| Run tests | `pytest -q` |
| Run API (hot-reload) | `uvicorn gis_route_app.main:app --reload --host 0.0.0.0 --port 8000` |
| Run CLI | `gis-route-cli --start-lon ... --start-lat ... --end-lon ... --end-lat ... --mode driving` |
| Run Streamlit dashboard | `streamlit run src/gis_route_app/streamlit_app.py` |

### Non-obvious notes

- The `.env` file must exist before running; copy from `.env.example` if missing.
  `ROUTING_PROVIDER=mock` needs no API key; `ROUTING_PROVIDER=ors` requires
  `OPENROUTESERVICE_API_KEY`.
- `HIN_DATA_SOURCE` and `CIP_DATA_SOURCE` accept a local file path or an HTTP GeoJSON URL.
  HIN is filtered to the `HISN_2023`-flagged segments in `service.py` -- the raw local
  export includes evaluated-but-not-flagged segments too.
- CIP projects are bucketed into planned/construction/completed from the live source's
  `Phase` field (`categorization.py`); a `GlobalID`-keyed snapshot store
  (`data/cip_snapshot.json`, gitignored) detects projects the feed has dropped and
  archives them as completed, since the source rarely leaves a project tagged
  "Completed" for long.
- `RouteIntersectionService` is cached process-wide and only rebuilt at most every
  `DATA_REFRESH_INTERVAL_SECONDS` (default 24h) -- see `get_cached_service` /
  `refresh_cached_service` in `service.py`. Don't reintroduce a fresh build per request;
  that reintroduces a live-network dependency on every single call.
- `pyproject.toml` sets `pythonpath = ["src"]` for pytest, so tests import
  `gis_route_app` directly without an editable install.

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
- The FastAPI app (`api.py`) also runs `run_background_refresh` in a daemon thread from
  its `lifespan`, so the CIP snapshot diffs on a schedule even with no traffic --
  otherwise a project that disappears and reappears between two widely-spaced requests
  would never get detected. The CLI doesn't run this (short-lived); Streamlit gets it
  indirectly, see the next note.
- Streamlit's Analyze / Simulate / Go buttons: Simulate and Go are link buttons to the
  navigation page (`NAVIGATION_BASE_URL`, default `http://localhost:8000/navigate/`) carrying
  the analyzed start/end/mode in the URL, enabled only while the inputs still match the last
  analysis (kept in `st.session_state`). `_ensure_navigation_server` starts the FastAPI app
  in a daemon thread inside the Streamlit process if nothing answers on that port, so
  `streamlit run` alone is enough for the demo (and shares its warmed HIN/CIP cache).
- GPX routes: `data/routes/<id>.gpx` are bundled routes (ids: lowercase letters, digits,
  hyphens). Streamlit's **Upload a .GPX route** button is a demo stand-in that loads
  `war-on-cars-bike-tour` rather than accepting a file -- real uploads need somewhere to
  keep the file for the navigation page (currently only bundled routes, by id, so no
  storage) and `defusedxml` for untrusted XML (see `gpx.py`). The API's
  `/navigation-plan` takes `route_id` instead of start/end; the page takes `?route=<id>`.
- Routes that retrace themselves (GPX out-and-backs): overlap intervals are measured per
  vertex-to-vertex segment in `route_partition.line_metric_overlap_intervals`, and the
  Streamlit percentages come from the same partition as the bar and map. Don't go back to
  projecting overlap pieces onto the whole line -- it puts every pass at the first one's spot.
- Navigation mode (`web/navigate/`, opened at `http://localhost:8000/navigate/`) is a
  plain-JS MapLibre page, not Streamlit -- Streamlit reruns the whole script per update,
  which can't drive a live follow-the-user map. It takes `?start=lon,lat&end=lon,lat&mode=`
  (defaults to the Richmond demo route), `?source=sim` (autoplays the simulated walker),
  `?source=gps` (opens on a route overview with a
  Start button, for phone links) and `?debug` (exposes `window.__nav`). It defaults to the
  simulated walker, which is what demos on a laptop should use. Text shown in its info
  bar comes from `summary.py`, the same source as the Streamlit sections.
- Real GPS needs HTTPS (localhost is exempt), so testing on a phone needs a tunnel or
  hosting. Pure JS logic is tested by opening `/navigate/tests.html` (no Node here); the
  map itself only renders in a *visible* browser tab, so headless/hidden panes stall on load.
- `pyproject.toml` sets `pythonpath = ["src"]` for pytest, so tests import
  `gis_route_app` directly without an editable install.

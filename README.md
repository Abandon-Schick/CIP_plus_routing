# GIS Route Intersection Application

Python-based GIS application to:

- calculate **driving / walking / biking routes**
- determine route intersections with:
  - **High Injury Network (HIN)** dataset
  - **Capital Improvement Projects (CIP)** dataset

The project includes:

- a **FastAPI service** (`/analyze-route`)
- a **CLI tool** (`gis-route-cli`)
- a **Streamlit dashboard** with:
  - **Near me** tab (embedded ArcGIS Nearby app iframe)
  - **Route intersection** tab (start/end controls + overlap chart)

## Architecture

- `src/gis_route_app/routing.py`  
  Routing providers:
  - `mock` provider for local development/tests
  - `ors` provider (OpenRouteService)
- `src/gis_route_app/analysis.py`  
  Spatial intersection engine using Shapely + geodesic length calculations
- `src/gis_route_app/service.py`  
  Application service that composes routing + intersection logic
- `src/gis_route_app/api.py`  
  FastAPI endpoints
- `src/gis_route_app/cli.py`  
  Command-line entrypoint
- `data/hin.geojson`, `data/cip.geojson`  
  Sample local datasets (the app can also load datasets from HTTP GeoJSON URLs)

## Quickstart

### 1) Create environment and install

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### 2) Configure environment

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

Key variables:

- `ROUTING_PROVIDER=mock` for local deterministic routes
- `ROUTING_PROVIDER=ors` to use OpenRouteService API
- `OPENROUTESERVICE_API_KEY=<your_key>` required when using `ors`
- `HIN_DATA_SOURCE` accepts a local file path or HTTP GeoJSON URL
- `CIP_DATA_SOURCE` accepts a local file path or HTTP GeoJSON URL (default is your ArcGIS endpoint)

Default CIP source:

```text
https://services1.arcgis.com/k3vhq11XkBNeeOfM/arcgis/rest/services/FY23_CIP_Polygon_Layers/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson
```

### 3) Run API

```bash
uvicorn gis_route_app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Analyze route:

```bash
curl -X POST http://localhost:8000/analyze-route \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"lon": -122.431, "lat": 37.772},
    "end": {"lon": -122.421, "lat": 37.772},
    "mode": "biking"
  }'
```

### 4) Run CLI

```bash
gis-route-cli \
  --start-lon -122.431 --start-lat 37.772 \
  --end-lon -122.421 --end-lat 37.772 \
  --mode biking \
  --pretty
```

### 5) Run Streamlit dashboard

```bash
streamlit run src/gis_route_app/streamlit_app.py
```

Or run with module mode:

```bash
python3 -m streamlit run src/gis_route_app/streamlit_app.py
```

Dashboard tabs:

- **Near me**: embeds  
  `https://www.arcgis.com/apps/instant/nearbybeta/index.html?appid=3990cecc7b0d42079d60b9aa3ad725e5&locale=en`
- **Route intersection**: address-based route input controls with autocomplete suggestions, summary metrics, and a line chart showing:
  - percent of route intersecting **HIN**
  - percent of route intersecting **CIP**
  - percent of route intersecting **neither**
  - a compact route map panel with start/end markers and route geometry

Override dataset sources at runtime (file path or URL):

```bash
gis-route-cli \
  --start-lon -122.431 --start-lat 37.772 \
  --end-lon -122.421 --end-lat 37.772 \
  --mode biking \
  --cip-source "https://services1.arcgis.com/k3vhq11XkBNeeOfM/arcgis/rest/services/FY23_CIP_Polygon_Layers/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson" \
  --pretty
```

## Intersection Output

Each intersection includes:

- `feature_id`
- `dataset` (`hin` or `cip`)
- `overlap_length_m`
- `overlap_fraction_of_route`
- source feature `properties`

## Running Tests

```bash
pytest -q
```

## Extending Datasets

You can use either:

- local files (`data/hin.geojson`, `data/cip.geojson`), or
- remote HTTP GeoJSON APIs (for example ArcGIS REST query endpoints returning `f=geojson`).

Expected format is GeoJSON `FeatureCollection`. Null-geometry features are skipped automatically.
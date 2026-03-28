# GIS Route Intersection Application

Python-based GIS application to:

- calculate **driving / walking / biking routes**
- determine route intersections with:
  - **High Injury Network (HIN)** dataset
  - **Capital Improvement Projects (CIP)** dataset

The project includes both:

- a **FastAPI service** (`/analyze-route`)
- a **CLI tool** (`gis-route-cli`)

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
  Sample datasets

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

Replace sample files:

- `data/hin.geojson`
- `data/cip.geojson`

Expected format is GeoJSON `FeatureCollection` with line-based geometries (recommended for corridor/project overlap analysis).
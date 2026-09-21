"""FastAPI application for route and intersection analysis."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .gpx import load_static_route
from .models import NavigationPlanRequest, RouteAnalysisResponse, RouteRequest
from .navigation import NavigationPlan, build_navigation_plan
from .routing import RoutingError
from .service import get_cached_service, refresh_cached_service, run_background_refresh

_background_refresh_stop = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    thread = threading.Thread(
        target=run_background_refresh,
        args=(get_settings(), _background_refresh_stop),
        daemon=True,
        name="cip-data-refresh",
    )
    thread.start()
    try:
        yield
    finally:
        _background_refresh_stop.set()
        thread.join(timeout=5)


app = FastAPI(
    title="GIS Route Intersection API",
    description=(
        "Compute routes for driving/walking/biking and detect intersections "
        "with High Injury Network and Capital Improvement Projects datasets."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness endpoint."""
    return {"status": "ok"}


@app.post("/analyze-route", response_model=RouteAnalysisResponse)
def analyze_route(payload: RouteRequest) -> RouteAnalysisResponse:
    """Generate route and return intersection analysis for HIN and CIP."""
    try:
        service, _ = get_cached_service(get_settings())
        return service.analyze(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Dataset file missing: {exc}") from exc
    except RoutingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/refresh-data")
def refresh_data() -> dict[str, str]:
    """Force an immediate re-fetch of the HIN/CIP datasets, bypassing the cache."""
    _, refreshed_at = refresh_cached_service(get_settings())
    return {"status": "ok", "refreshed_at": refreshed_at.isoformat()}


@app.post("/navigation-plan", response_model=NavigationPlan)
def navigation_plan(payload: NavigationPlanRequest) -> NavigationPlan:
    """Route plus per-stretch colors and per-feature corridors/text for the live map."""
    settings = get_settings()
    try:
        service, _ = get_cached_service(settings)
        if payload.route_id is not None:
            try:
                gpx_route = load_static_route(payload.route_id, settings.static_routes_dir)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=404, detail=f"Unknown route: {payload.route_id}") from exc
            result = service.analyze_line(gpx_route.coordinates, payload.mode)
        else:
            result = service.analyze(RouteRequest(start=payload.start, end=payload.end, mode=payload.mode))
        return build_navigation_plan(result, service.analysis_engine)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Dataset file missing: {exc}") from exc
    except RoutingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_NAVIGATE_DIR = Path(__file__).resolve().parents[2] / "web" / "navigate"
if _NAVIGATE_DIR.is_dir():
    app.mount("/navigate", StaticFiles(directory=_NAVIGATE_DIR, html=True), name="navigate")

"""FastAPI application for route and intersection analysis."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .config import get_settings
from .models import RouteAnalysisResponse, RouteRequest
from .routing import RoutingError
from .service import RouteIntersectionService

app = FastAPI(
    title="GIS Route Intersection API",
    description=(
        "Compute routes for driving/walking/biking and detect intersections "
        "with High Injury Network and Capital Improvement Projects datasets."
    ),
    version="0.1.0",
)


def _build_service() -> RouteIntersectionService:
    settings = get_settings()
    return RouteIntersectionService.from_settings(settings=settings)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness endpoint."""
    return {"status": "ok"}


@app.post("/analyze-route", response_model=RouteAnalysisResponse)
def analyze_route(payload: RouteRequest) -> RouteAnalysisResponse:
    """Generate route and return intersection analysis for HIN and CIP."""
    try:
        service = _build_service()
        return service.analyze(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Dataset file missing: {exc}") from exc
    except RoutingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

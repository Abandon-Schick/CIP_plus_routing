"""Shared models for routing and spatial analysis."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TravelMode(str, Enum):
    """Supported transportation modes."""

    DRIVING = "driving"
    WALKING = "walking"
    BIKING = "biking"


class Coordinate(BaseModel):
    """Longitude/latitude coordinate in WGS84."""

    lon: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)


class RouteRequest(BaseModel):
    """Input request for route generation and analysis."""

    start: Coordinate
    end: Coordinate
    mode: TravelMode
    include_geometry: bool = True


class SegmentIntersection(BaseModel):
    """Information about a route overlap with a dataset feature."""

    feature_id: str
    dataset: Literal["hin", "cip"]
    overlap_length_m: float
    overlap_fraction_of_route: float
    properties: dict[str, Any]


class RouteResponse(BaseModel):
    """Route response with optional intersection analysis."""

    mode: TravelMode
    distance_m: float
    duration_s: float
    geojson: dict[str, Any]


class RouteAnalysisResponse(BaseModel):
    """Combined route and spatial intersection output."""

    route: RouteResponse
    intersections: list[SegmentIntersection]

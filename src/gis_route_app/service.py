"""Application service that combines routing and spatial analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analysis import SpatialAnalysisEngine
from .config import Settings
from .datasets import load_geojson_features
from .models import RouteAnalysisResponse, RouteRequest
from .routing import RoutingContext, build_routing_provider


@dataclass(frozen=True)
class RouteIntersectionService:
    """Main orchestration service for route analysis requests."""

    settings: Settings
    analysis_engine: SpatialAnalysisEngine

    @classmethod
    def from_data_files(
        cls,
        settings: Settings,
        hin_path: str | Path,
        cip_path: str | Path,
    ) -> "RouteIntersectionService":
        hin_features = load_geojson_features(hin_path, fallback_prefix="hin")
        cip_features = load_geojson_features(cip_path, fallback_prefix="cip")
        engine = SpatialAnalysisEngine(hin_features=hin_features, cip_features=cip_features)
        return cls(settings=settings, analysis_engine=engine)

    def analyze(self, request: RouteRequest) -> RouteAnalysisResponse:
        provider = build_routing_provider(
            self.settings.routing_provider,
            RoutingContext(
                request_timeout_seconds=self.settings.request_timeout_seconds,
                openrouteservice_api_key=self.settings.openrouteservice_api_key,
                openrouteservice_base_url=self.settings.openrouteservice_base_url,
            ),
        )
        route = provider.get_route(start=request.start, end=request.end, mode=request.mode)
        intersections = self.analysis_engine.analyze_route(route.geojson)
        return RouteAnalysisResponse(route=route, intersections=intersections)

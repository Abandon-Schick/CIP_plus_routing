"""Application service that combines routing and spatial analysis."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
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

    @staticmethod
    def _is_http_source(source: str | Path) -> bool:
        parsed = urlparse(str(source))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @classmethod
    def from_data_files(
        cls,
        settings: Settings,
        hin_path: str | Path,
        cip_path: str | Path,
    ) -> "RouteIntersectionService":
        try:
            hin_features = load_geojson_features(
                hin_path,
                fallback_prefix="hin",
                timeout_seconds=settings.request_timeout_seconds,
            )
        except Exception:
            if (
                cls._is_http_source(hin_path)
                and str(hin_path) != "data/hin.geojson"
            ):
                hin_features = load_geojson_features(
                    "data/hin.geojson",
                    fallback_prefix="hin",
                    timeout_seconds=settings.request_timeout_seconds,
                )
            else:
                raise
        cip_features = load_geojson_features(
            cip_path,
            fallback_prefix="cip",
            timeout_seconds=settings.request_timeout_seconds,
        )
        engine = SpatialAnalysisEngine(hin_features=hin_features, cip_features=cip_features)
        return cls(settings=settings, analysis_engine=engine)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RouteIntersectionService":
        """Build service using data sources from runtime settings."""
        return cls.from_data_files(
            settings=settings,
            hin_path=settings.hin_data_source,
            cip_path=settings.cip_data_source,
        )

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

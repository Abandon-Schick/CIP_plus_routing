"""Application service that combines routing and spatial analysis."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from pathlib import Path

from .analysis import SpatialAnalysisEngine
from .categorization import CipSnapshotStore
from .config import Settings
from .datasets import DatasetFeature, load_geojson_features
from .models import RouteAnalysisResponse, RouteRequest
from .routing import RoutingContext, build_routing_provider

_HIN_FLAG_FIELD = "HISN_2023"


def _is_flagged_high_injury(feature: DatasetFeature) -> bool:
    """Whether a HIN source feature is flagged high-injury under the current vintage.

    The static HIN export includes segments evaluated but not flagged in every
    vintage (e.g. Grove Ave, Walmsley Blvd under HISN_2023) alongside the ones
    that are; without this check every evaluated segment counts as HIN.
    """
    value = feature.properties.get(_HIN_FLAG_FIELD)
    return value in (1, "1", True)


def _bucket_cip_features(
    features: list[DatasetFeature], snapshot_path: str | Path
) -> list[DatasetFeature]:
    """Attach each CIP feature's citizen-facing bucket via the snapshot store.

    The bucket travels as an added ``cip_bucket`` property so downstream
    consumers (analysis, API, UI) don't need a separate lookup -- it's just
    part of the feature's properties like anything else in the source data.
    """
    result = CipSnapshotStore(snapshot_path).refresh(features)
    return [
        DatasetFeature(
            feature_id=bf.feature.feature_id,
            geometry=bf.feature.geometry,
            properties={**bf.feature.properties, "cip_bucket": bf.bucket},
        )
        for bf in result.features
    ]


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
        hin_features = [f for f in hin_features if _is_flagged_high_injury(f)]
        cip_features = load_geojson_features(
            cip_path,
            fallback_prefix="cip",
            timeout_seconds=settings.request_timeout_seconds,
        )
        cip_features = _bucket_cip_features(cip_features, settings.cip_snapshot_path)
        engine = SpatialAnalysisEngine(
            hin_features=hin_features,
            cip_features=cip_features,
            proximity_buffer_m=settings.proximity_buffer_m,
        )
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

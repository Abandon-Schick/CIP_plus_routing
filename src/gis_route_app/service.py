"""Application service that combines routing and spatial analysis."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from pathlib import Path

from .analysis import SpatialAnalysisEngine
from .categorization import CipSnapshotStore
from .config import Settings
from .datasets import DatasetFeature, load_geojson_features
from .models import RouteAnalysisResponse, RouteRequest
from .models import TravelMode
from .routing import RoutingContext, build_routing_provider, route_from_coordinates

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

    def analyze(
        self, request: RouteRequest, routing_provider: str | None = None
    ) -> RouteAnalysisResponse:
        """Compute the route and its intersections.

        ``routing_provider`` overrides ``self.settings.routing_provider`` for this
        call only -- lets a caller retry with a different provider (e.g. falling
        back from "ors" to "mock") without rebuilding the cached HIN/CIP data.
        """
        provider = build_routing_provider(
            routing_provider or self.settings.routing_provider,
            RoutingContext(
                request_timeout_seconds=self.settings.request_timeout_seconds,
                openrouteservice_api_key=self.settings.openrouteservice_api_key,
                openrouteservice_base_url=self.settings.openrouteservice_base_url,
            ),
        )
        route = provider.get_route(start=request.start, end=request.end, mode=request.mode)
        intersections = self.analysis_engine.analyze_route(route.geojson)
        return RouteAnalysisResponse(route=route, intersections=intersections)

    def analyze_line(
        self, coordinates: list[tuple[float, float]], mode: TravelMode
    ) -> RouteAnalysisResponse:
        """Analyze a route we were handed as a line (e.g. a GPX track), with no routing step."""
        route = route_from_coordinates(coordinates, mode)
        intersections = self.analysis_engine.analyze_route(route.geojson)
        return RouteAnalysisResponse(route=route, intersections=intersections)


def _cache_key(settings: Settings) -> tuple:
    return (
        settings.hin_data_source,
        settings.cip_data_source,
        settings.proximity_buffer_m,
        settings.cip_snapshot_path,
    )


class CachedServiceProvider:
    """Serves a process-wide ``RouteIntersectionService``, rebuilt at most periodically.

    The live CIP feed and the HIN export don't change second-to-second, so
    reloading and re-fetching them on every request just adds latency and a
    new external-network failure point per request -- see ``analyze_route``'s
    callers, which used to build a fresh service on every call. ``refresh``
    supports an explicit manual refresh (e.g. a UI button) regardless of age.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[RouteIntersectionService, datetime]] = {}

    def get(self, settings: Settings) -> tuple[RouteIntersectionService, datetime]:
        key = _cache_key(settings)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                age = datetime.now(timezone.utc) - cached[1]
                if age < timedelta(seconds=settings.data_refresh_interval_seconds):
                    return cached
            return self._build_and_cache(settings, key)

    def refresh(self, settings: Settings) -> tuple[RouteIntersectionService, datetime]:
        """Force a rebuild regardless of cache age."""
        with self._lock:
            return self._build_and_cache(settings, _cache_key(settings))

    def _build_and_cache(
        self, settings: Settings, key: tuple
    ) -> tuple[RouteIntersectionService, datetime]:
        service = RouteIntersectionService.from_settings(settings=settings)
        entry = (service, datetime.now(timezone.utc))
        self._cache[key] = entry
        return entry


_cached_service_provider = CachedServiceProvider()


def get_cached_service(settings: Settings) -> tuple[RouteIntersectionService, datetime]:
    """Return the process-wide cached service and when it was last built."""
    return _cached_service_provider.get(settings)


def refresh_cached_service(settings: Settings) -> tuple[RouteIntersectionService, datetime]:
    """Force an immediate rebuild of the process-wide cached service."""
    return _cached_service_provider.refresh(settings)


def run_background_refresh(
    settings: Settings,
    stop_event: threading.Event,
    provider: CachedServiceProvider | None = None,
) -> None:
    """Refresh the cached service on a timer until ``stop_event`` is set.

    Without this, the CIP snapshot only diffs when a request happens to
    arrive after the cache goes stale -- so a project that disappears and
    reappears between two widely-spaced requests (or during a quiet stretch
    with no traffic at all) would never be detected. Meant to run in a
    daemon thread started from the API's lifespan; the first refresh fires
    after one interval, not immediately, so process startup doesn't block
    on a live network fetch.
    """
    target = provider if provider is not None else _cached_service_provider
    logger = logging.getLogger(__name__)
    while not stop_event.wait(settings.data_refresh_interval_seconds):
        try:
            target.refresh(settings)
        except Exception:
            logger.exception("Background data refresh failed")

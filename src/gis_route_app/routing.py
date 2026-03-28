"""Routing providers for driving/walking/biking routes."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from .models import Coordinate, RouteResponse, TravelMode


@dataclass(frozen=True)
class RoutingContext:
    """Runtime parameters for routing providers."""

    request_timeout_seconds: int = 15
    openrouteservice_api_key: str | None = None
    openrouteservice_base_url: str = "https://api.openrouteservice.org"


class RoutingError(RuntimeError):
    """Raised when a route cannot be produced by the routing provider."""


class BaseRoutingProvider:
    """Base class for route generation providers."""

    def get_route(self, start: Coordinate, end: Coordinate, mode: TravelMode) -> RouteResponse:
        raise NotImplementedError


class OpenRouteServiceProvider(BaseRoutingProvider):
    """Route provider backed by OpenRouteService directions API."""

    _ors_profile = {
        TravelMode.DRIVING: "driving-car",
        TravelMode.WALKING: "foot-walking",
        TravelMode.BIKING: "cycling-regular",
    }

    def __init__(self, context: RoutingContext) -> None:
        if not context.openrouteservice_api_key:
            raise RoutingError("OPENROUTESERVICE_API_KEY is required for ors provider")
        self._api_key = context.openrouteservice_api_key
        self._base_url = context.openrouteservice_base_url
        self._timeout = context.request_timeout_seconds

    def get_route(self, start: Coordinate, end: Coordinate, mode: TravelMode) -> RouteResponse:
        profile = self._ors_profile[mode]
        url = f"{self._base_url}/v2/directions/{profile}/geojson"
        headers = {"Authorization": self._api_key, "Content-Type": "application/json"}
        payload = {
            "coordinates": [[start.lon, start.lat], [end.lon, end.lat]],
            "instructions": False,
            "elevation": False,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=self._timeout)
        if not response.ok:
            raise RoutingError(
                f"OpenRouteService error ({response.status_code}): {response.text[:200]}"
            )

        body = response.json()
        features = body.get("features", [])
        if not features:
            raise RoutingError("OpenRouteService returned no route features")

        feat = features[0]
        summary = (
            feat.get("properties", {})
            .get("summary", {})
        )
        distance_m = float(summary.get("distance", 0.0))
        duration_s = float(summary.get("duration", 0.0))

        return RouteResponse(mode=mode, distance_m=distance_m, duration_s=duration_s, geojson=feat)


def build_routing_provider(provider_name: str, context: RoutingContext) -> BaseRoutingProvider:
    """Factory for supported routing providers (ORS only)."""
    if provider_name == "ors":
        return OpenRouteServiceProvider(context)
    raise RoutingError(
        f"Unsupported routing provider: {provider_name}. "
        "Only 'ors' is supported."
    )

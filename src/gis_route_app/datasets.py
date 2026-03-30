"""Loading and representing spatial datasets for intersection analysis."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

_PENDING_HTTP_STATUSES = {"pending", "queued", "in progress", "processing"}
_HTTP_GEOJSON_MAX_ATTEMPTS = 6
_HTTP_GEOJSON_POLL_SECONDS = 2.0


@dataclass(frozen=True)
class DatasetFeature:
    """Single geometry feature and metadata from a dataset."""

    feature_id: str
    geometry: BaseGeometry
    properties: dict[str, Any]


def _feature_id_from_properties(
    properties: dict[str, Any], fallback_prefix: str, idx: int
) -> str:
    raw = (
        properties.get("id")
        or properties.get("ID")
        or properties.get("objectid")
        or properties.get("OBJECTID")
        or f"{fallback_prefix}_{idx}"
    )
    return str(raw)


def _is_http_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _read_geojson_payload(source: str | Path, timeout_seconds: int = 30) -> dict[str, Any]:
    source_str = str(source)
    if _is_http_url(source_str):
        payload: dict[str, Any] = {}
        for attempt in range(1, _HTTP_GEOJSON_MAX_ATTEMPTS + 1):
            response = requests.get(source_str, timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            if payload.get("type") == "FeatureCollection":
                return payload

            status = str(payload.get("status", "")).strip().lower()
            if (
                attempt < _HTTP_GEOJSON_MAX_ATTEMPTS
                and status in _PENDING_HTTP_STATUSES
            ):
                time.sleep(_HTTP_GEOJSON_POLL_SECONDS)
                continue
            return payload
        return payload
    file_path = Path(source_str)
    return json.loads(file_path.read_text(encoding="utf-8"))


def load_geojson_features(
    source: str | Path, fallback_prefix: str, timeout_seconds: int = 30
) -> list[DatasetFeature]:
    """Load features from a GeoJSON FeatureCollection from file path or URL."""
    payload = _read_geojson_payload(source, timeout_seconds=timeout_seconds)
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"{source} must be a FeatureCollection")

    features: list[DatasetFeature] = []
    for idx, feat in enumerate(payload.get("features", []), start=1):
        geometry_payload = feat.get("geometry")
        if not geometry_payload:
            # ArcGIS and other APIs may include sparse features with null geometry.
            continue
        geometry = shape(geometry_payload)
        properties = dict(feat.get("properties", {}))
        feature_id = _feature_id_from_properties(properties, fallback_prefix, idx)
        features.append(
            DatasetFeature(feature_id=feature_id, geometry=geometry, properties=properties)
        )

    return features

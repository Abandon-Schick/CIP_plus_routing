"""Loading and representing spatial datasets for intersection analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


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


def load_geojson_features(path: str | Path, fallback_prefix: str) -> list[DatasetFeature]:
    """Load features from a GeoJSON FeatureCollection."""
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"{file_path} must be a FeatureCollection")

    features: list[DatasetFeature] = []
    for idx, feat in enumerate(payload.get("features", []), start=1):
        geometry = shape(feat["geometry"])
        properties = dict(feat.get("properties", {}))
        feature_id = _feature_id_from_properties(properties, fallback_prefix, idx)
        features.append(
            DatasetFeature(feature_id=feature_id, geometry=geometry, properties=properties)
        )

    return features

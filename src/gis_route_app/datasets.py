"""Loading and representing spatial datasets for intersection analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform


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


def _feature_collection_source_crs(payload: dict[str, Any]) -> str | None:
    """Return CRS name from legacy GeoJSON `crs` member, if present."""
    crs_block = payload.get("crs")
    if not isinstance(crs_block, dict) or crs_block.get("type") != "name":
        return None
    props = crs_block.get("properties")
    if not isinstance(props, dict):
        return None
    name = props.get("name")
    return str(name) if isinstance(name, str) else None


def _to_wgs84_lonlat(geometry: BaseGeometry, source_crs: str | None) -> BaseGeometry:
    """Reproject to WGS84 (lon/lat) when the collection CRS is projected (e.g. ArcGIS Web Mercator).

    Routes and downstream analysis assume EPSG:4326-style coordinates. Geographic CRS values
    in the `crs` member (CRS84, EPSG:4326) are left unchanged.
    """
    if not source_crs:
        return geometry
    try:
        crs_obj = CRS.from_user_input(source_crs)
    except CRSError:
        return geometry
    if crs_obj.is_geographic:
        return geometry
    transformer = Transformer.from_crs(crs_obj, CRS.from_epsg(4326), always_xy=True)
    return shapely_transform(transformer.transform, geometry)


def _read_geojson_payload(source: str | Path, timeout_seconds: int = 30) -> dict[str, Any]:
    source_str = str(source)
    if _is_http_url(source_str):
        response = requests.get(source_str, timeout=timeout_seconds)
        response.raise_for_status()
        return response.json()
    file_path = Path(source_str)
    return json.loads(file_path.read_text(encoding="utf-8"))


def load_geojson_features(
    source: str | Path, fallback_prefix: str, timeout_seconds: int = 30
) -> list[DatasetFeature]:
    """Load features from a GeoJSON FeatureCollection from file path or URL."""
    payload = _read_geojson_payload(source, timeout_seconds=timeout_seconds)
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"{source} must be a FeatureCollection")

    source_crs = _feature_collection_source_crs(payload)
    features: list[DatasetFeature] = []
    for idx, feat in enumerate(payload.get("features", []), start=1):
        geometry_payload = feat.get("geometry")
        if not geometry_payload:
            # ArcGIS and other APIs may include sparse features with null geometry.
            continue
        geometry = _to_wgs84_lonlat(shape(geometry_payload), source_crs)
        properties = dict(feat.get("properties", {}))
        feature_id = _feature_id_from_properties(properties, fallback_prefix, idx)
        features.append(
            DatasetFeature(feature_id=feature_id, geometry=geometry, properties=properties)
        )

    return features

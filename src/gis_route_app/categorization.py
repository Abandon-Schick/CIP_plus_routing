"""Bucketing CIP projects into citizen-facing phase categories.

The city's own ``Phase`` field is the best available signal for whether a
project is planned, under construction, or completed -- but it reflects the
city's internal project-management categorization, not necessarily whether a
citizen would see visible change on their route (a project can sit in
"Construction" for years before completion). This module buckets by
``Phase`` as-is rather than trying to second-guess it; callers are expected
to display the project's raw completion estimate alongside the bucket so a
citizen can judge timing themselves.

The live CIP source only ever carries two "Completed" records across the
city's entire project history, which means it drops projects from the feed
rather than leaving them tagged -- so ``CipSnapshotStore`` treats a
project's disappearance between pulls as the primary completed signal, and
an explicit "Completed" phase as a secondary, faster-arriving one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from shapely.geometry import mapping, shape

from .datasets import DatasetFeature

CipBucket = Literal["completed", "construction", "planned"]

_PHASE_BUCKET_OVERRIDES: dict[str, CipBucket] = {
    "completed": "completed",
    "construction": "construction",
}


def bucket_from_phase(phase: str | None) -> CipBucket:
    """Map a project's raw ``Phase`` value to a citizen-facing bucket.

    Anything not explicitly "Completed" or "Construction" -- including
    missing or unrecognized values -- defaults to "planned".
    """
    key = (phase or "").strip().lower()
    return _PHASE_BUCKET_OVERRIDES.get(key, "planned")


def _global_id(feature: DatasetFeature) -> str | None:
    raw = feature.properties.get("GlobalID")
    return str(raw) if raw else None


@dataclass(frozen=True)
class BucketedCipFeature:
    """A CIP feature paired with its citizen-facing bucket."""

    feature: DatasetFeature
    bucket: CipBucket


@dataclass(frozen=True)
class CipSnapshotResult:
    """Output of a snapshot refresh: every feature to analyze, bucketed."""

    features: list[BucketedCipFeature]
    newly_completed_global_ids: list[str]


def _feature_to_record(feature: DatasetFeature, **extra: Any) -> dict[str, Any]:
    return {"geometry": mapping(feature.geometry), "properties": feature.properties, **extra}


def _record_to_feature(global_id: str, record: dict[str, Any]) -> DatasetFeature:
    return DatasetFeature(
        feature_id=global_id, geometry=shape(record["geometry"]), properties=record["properties"]
    )


class CipSnapshotStore:
    """Persists CIP pulls across runs to detect projects the feed has dropped.

    On each refresh, any project present in the previous snapshot but
    missing from the current pull is archived as completed, keeping its
    last-known geometry so route intersections against it keep working
    after the source stops listing it. Features without a ``GlobalID``
    can't be tracked across pulls and are bucketed by phase only.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"known": {}, "completed_archive": {}}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        data.setdefault("known", {})
        data.setdefault("completed_archive", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def refresh(self, current_features: list[DatasetFeature]) -> CipSnapshotResult:
        """Diff ``current_features`` against the stored snapshot and update it."""
        data = self._load()
        known: dict[str, Any] = data["known"]
        archive: dict[str, Any] = data["completed_archive"]

        trackable = {gid: f for f in current_features if (gid := _global_id(f))}
        untrackable = [f for f in current_features if not _global_id(f)]

        newly_completed = [
            global_id
            for global_id in known
            if global_id not in trackable and global_id not in archive
        ]
        now = datetime.now(timezone.utc).isoformat()
        for global_id in newly_completed:
            archive[global_id] = {**known[global_id], "completed_detected_at": now}

        data["known"] = {
            global_id: _feature_to_record(feature, last_seen_at=now)
            for global_id, feature in trackable.items()
        }
        self._save(data)

        bucketed = [
            BucketedCipFeature(
                feature=feature, bucket=bucket_from_phase(feature.properties.get("Phase"))
            )
            for feature in trackable.values()
        ]
        bucketed.extend(
            BucketedCipFeature(
                feature=feature, bucket=bucket_from_phase(feature.properties.get("Phase"))
            )
            for feature in untrackable
        )
        bucketed.extend(
            BucketedCipFeature(feature=_record_to_feature(global_id, record), bucket="completed")
            for global_id, record in archive.items()
        )
        return CipSnapshotResult(features=bucketed, newly_completed_global_ids=newly_completed)

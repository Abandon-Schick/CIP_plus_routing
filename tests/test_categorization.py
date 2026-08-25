from shapely.geometry import LineString

from gis_route_app.categorization import CipSnapshotStore, bucket_from_phase
from gis_route_app.datasets import DatasetFeature


def _feature(global_id: str, phase: str | None, **extra_props) -> DatasetFeature:
    return DatasetFeature(
        feature_id=global_id,
        geometry=LineString([(-77.45, 37.54), (-77.44, 37.53)]),
        properties={"GlobalID": global_id, "Phase": phase, **extra_props},
    )


def test_bucket_from_phase_maps_known_values() -> None:
    assert bucket_from_phase("Completed") == "completed"
    assert bucket_from_phase("Construction") == "construction"
    assert bucket_from_phase("construction") == "construction"  # case-insensitive


def test_bucket_from_phase_defaults_to_planned() -> None:
    assert bucket_from_phase("Planning/Design") == "planned"
    assert bucket_from_phase("Pre-Construction") == "planned"
    assert bucket_from_phase("Some Unrecognized Phase") == "planned"
    assert bucket_from_phase(None) == "planned"
    assert bucket_from_phase("") == "planned"


def test_first_refresh_buckets_by_phase_with_no_completions(tmp_path) -> None:
    store = CipSnapshotStore(tmp_path / "snapshot.json")
    features = [
        _feature("A", "Construction"),
        _feature("B", "Planning/Design"),
        _feature("C", "Completed"),
    ]

    result = store.refresh(features)

    assert result.newly_completed_global_ids == []
    buckets = {bf.feature.feature_id: bf.bucket for bf in result.features}
    assert buckets == {"A": "construction", "B": "planned", "C": "completed"}


def test_disappearing_project_is_archived_as_completed(tmp_path) -> None:
    store = CipSnapshotStore(tmp_path / "snapshot.json")
    store.refresh([_feature("A", "Construction"), _feature("B", "Planning/Design")])

    # "A" drops out of the next pull -- the source stopped listing it.
    result = store.refresh([_feature("B", "Planning/Design")])

    assert result.newly_completed_global_ids == ["A"]
    buckets = {bf.feature.feature_id: bf.bucket for bf in result.features}
    assert buckets == {"A": "completed", "B": "planned"}
    # Archived geometry is preserved so route intersections keep working.
    archived = next(bf.feature for bf in result.features if bf.feature.feature_id == "A")
    assert archived.geometry.geom_type == "LineString"


def test_archived_project_is_not_reflagged_on_later_refreshes(tmp_path) -> None:
    store = CipSnapshotStore(tmp_path / "snapshot.json")
    store.refresh([_feature("A", "Construction")])
    first_drop = store.refresh([])
    assert first_drop.newly_completed_global_ids == ["A"]

    second_refresh = store.refresh([])

    assert second_refresh.newly_completed_global_ids == []
    assert [bf.feature.feature_id for bf in second_refresh.features] == ["A"]
    assert second_refresh.features[0].bucket == "completed"


def test_snapshot_persists_across_store_instances(tmp_path) -> None:
    path = tmp_path / "snapshot.json"
    CipSnapshotStore(path).refresh([_feature("A", "Construction")])

    result = CipSnapshotStore(path).refresh([])

    assert result.newly_completed_global_ids == ["A"]


def test_features_without_global_id_are_bucketed_but_not_tracked(tmp_path) -> None:
    store = CipSnapshotStore(tmp_path / "snapshot.json")
    untrackable = DatasetFeature(
        feature_id="fallback_1",
        geometry=LineString([(-77.45, 37.54), (-77.44, 37.53)]),
        properties={"Phase": "Construction"},
    )

    first = store.refresh([untrackable])
    assert first.features[0].bucket == "construction"

    # Dropping it on the next pull shouldn't mark anything completed --
    # there was never a stable id to track it by.
    second = store.refresh([])
    assert second.newly_completed_global_ids == []
    assert second.features == []

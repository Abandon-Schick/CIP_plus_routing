from gis_route_app.summary import (
    BUCKET_COLOR_HEX,
    BUCKET_DISPLAY_ORDER,
    BUCKET_ORDER,
    cip_detail,
    cip_fields,
    hin_detail,
    hin_fields,
    pick_property,
)


def test_pick_property_skips_blank_and_missing_values() -> None:
    props = {"a": None, "b": "   ", "c": " x ", "d": 5}
    assert pick_property(props, ["a", "b", "c", "d"]) == "x"
    assert pick_property(props, ["missing"]) == ""


def test_hin_fields_and_detail() -> None:
    fields = hin_fields(
        {"FullName": "E Main St", "StreetType": "Artery", "Functional": "Minor Arterial", "PostedSpee": 25},
        "hin_3",
    )
    assert fields["name"] == "E Main St"
    assert hin_detail(fields["street_type"], fields["functional"], fields["posted_speed"]) == (
        "Artery · Minor Arterial · 25 mph posted"
    )


def test_hin_name_falls_back_to_feature_id() -> None:
    assert hin_fields({}, "hin_9")["name"] == "hin_9"
    assert hin_detail("", "", "") == ""


def test_cip_fields_and_detail() -> None:
    fields = cip_fields(
        {"Name": "Trail", "Category": "Bike", "Cost": "$1", "Completion": "2027"}, "cip_1"
    )
    assert fields["name"] == "Trail"
    assert cip_detail(fields["category"], fields["cost"], fields["completion"]) == (
        "Bike · $1 · est. completion 2027"
    )
    assert cip_detail("Bike", "", "") == "Bike"


def test_bucket_lists_cover_the_same_buckets_and_all_have_colors() -> None:
    keys = {key for key, _ in BUCKET_ORDER}
    assert keys == {key for key, _ in BUCKET_DISPLAY_ORDER}
    assert keys | {"unaffected"} == set(BUCKET_COLOR_HEX)

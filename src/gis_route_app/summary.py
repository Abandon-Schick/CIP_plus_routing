"""Citizen-facing bucket vocabulary and per-feature text, shared by every UI."""

from __future__ import annotations

from typing import Any

# Priority order for resolving overlapping corridors (route line / bar segment
# colors). Deliberately NOT the same list as BUCKET_DISPLAY_ORDER: changing reading
# order must not silently change how overlaps are resolved. Whether "high risk"
# hiding an overlapping "planned" stretch undersells a project is still an open
# product question.
BUCKET_ORDER: list[tuple[str, str]] = [
    ("high_risk", "High risk"),
    ("completed", "Newly fixed"),
    ("construction", "Construction"),
    ("planned", "Planned changes"),
]
BUCKET_LABEL: dict[str, str] = dict(BUCKET_ORDER)

# Reading order: risk identified -> planned -> underway -> done.
BUCKET_DISPLAY_ORDER: list[tuple[str, str]] = [
    ("high_risk", "High risk"),
    ("planned", "Planned changes"),
    ("construction", "Construction"),
    ("completed", "Newly fixed"),
]

BUCKET_COLOR_HEX: dict[str, str] = {
    "high_risk": "#ef4444",
    "completed": "#22c55e",
    "construction": "#f97316",
    "planned": "#6366f1",
    "unaffected": "#BDBDBD",
}


def pick_property(properties: dict[str, Any], keys: list[str]) -> str:
    """First non-blank property among ``keys``, as stripped text ('' when none)."""
    for key in keys:
        value = properties.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def hin_fields(properties: dict[str, Any], feature_id: str) -> dict[str, str]:
    return {
        "name": pick_property(
            properties, ["FullName", "RouteName", "name", "Name", "title", "Title"]
        )
        or feature_id,
        "street_type": pick_property(
            properties, ["StreetType", "street_type", "streetType", "Type", "type"]
        ),
        "functional": pick_property(properties, ["Functional", "functional"]),
        "posted_speed": pick_property(
            properties, ["PostedSpee", "PostedSpeed", "posted_speed", "speed_limit"]
        ),
    }


def cip_fields(properties: dict[str, Any], feature_id: str) -> dict[str, str]:
    return {
        "name": pick_property(
            properties,
            ["project_name", "ProjectName", "name", "Name", "title", "Title"],
        )
        or feature_id,
        "category": pick_property(
            properties,
            ["category", "Category", "project_category", "kind", "type", "Type"],
        ),
        "description": pick_property(
            properties, ["description", "Description", "desc", "project_description"]
        ),
        "cost": pick_property(
            properties, ["cost", "Cost", "budget", "Budget", "project_cost"]
        ),
        "phase": pick_property(properties, ["phase", "Phase"]),
        "status": pick_property(properties, ["status", "Status"]),
        "completion": pick_property(
            properties, ["completion", "Completion", "completion_date", "end_date"]
        ),
    }


def hin_detail(street_type: str, functional: str, posted_speed: str) -> str:
    parts = [street_type, functional]
    if posted_speed:
        parts.append(f"{posted_speed} mph posted")
    return " · ".join(p for p in parts if p)


def cip_detail(category: str, cost: str, completion: str) -> str:
    parts = [category, cost]
    if completion:
        parts.append(f"est. completion {completion}")
    return " · ".join(p for p in parts if p)

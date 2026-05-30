"""Live planner selection helpers.

The driver owns execution and evidence. This module owns strategy choices that
turn context rows into candidate plan actions.
"""

from __future__ import annotations

from typing import Any

from codex_hl.live.policy_profiles import (
    CIVIC_PRIORITY,
    DEDICATION_PRIORITY,
    POLICY_PRIORITY,
    PRODUCTION_PRIORITY_EXPAND,
    PRODUCTION_PRIORITY_STABILIZE,
    TECH_PRIORITY,
)


def current_value_empty(value: Any) -> bool:
    if value is None:
        return True
    normalized = str(value).strip().lower()
    return normalized in {"", "none", "null", "nothing", "none."}


def city_count(context: dict[str, Any]) -> int:
    cities = [row for row in context.get("cities", []) if isinstance(row, dict)]
    overview = context.get("overview") if isinstance(context.get("overview"), dict) else {}
    try:
        return max(len(cities), int(overview.get("num_cities") or 0))
    except (TypeError, ValueError):
        return len(cities)


def city_has_empty_queue(city: dict[str, Any]) -> bool:
    return current_value_empty(city.get("currently_building")) or int(city.get("production_turns_left") or 0) <= 0


def option_identity(option: dict[str, Any]) -> str:
    return str(
        option.get("item_name")
        or option.get("name")
        or option.get("type")
        or option.get("item_type")
        or ""
    ).upper()


def option_category(option: dict[str, Any], item_name: str) -> str:
    raw = str(option.get("item_type") or option.get("category") or "").upper()
    if raw in {"UNIT", "BUILDING", "DISTRICT", "PROJECT", "WONDER"}:
        return raw
    if item_name.startswith("UNIT_"):
        return "UNIT"
    if item_name.startswith("BUILDING_"):
        return "BUILDING"
    if item_name.startswith("DISTRICT_"):
        return "DISTRICT"
    if item_name.startswith("PROJECT_"):
        return "PROJECT"
    return "BUILDING"


def threat_pressure(context: dict[str, Any]) -> int:
    threats = context.get("threats")
    if isinstance(threats, list):
        return len([item for item in threats if item is not None])
    return 0


def choose_production_option(options: list[dict[str, Any]], context: dict[str, Any]) -> tuple[str, str] | None:
    if not options:
        return None
    count = city_count(context)
    priority = PRODUCTION_PRIORITY_EXPAND if count < 2 else PRODUCTION_PRIORITY_STABILIZE
    if count >= 2 and threat_pressure(context) > 0:
        priority = ["UNIT_SLINGER", "UNIT_WARRIOR", *priority]
    by_name = {option_identity(option): option for option in options}
    for wanted in priority:
        option = by_name.get(wanted)
        if option is not None:
            return option_category(option, wanted), wanted
    for option in options:
        item = option_identity(option)
        if not item or item.startswith("DISTRICT_"):
            continue
        return option_category(option, item), item
    item = option_identity(options[0])
    if item:
        return option_category(options[0], item), item
    return None


def select_by_priority(options: list[dict[str, Any]], key: str, priority: list[str]) -> dict[str, Any] | None:
    if not options:
        return None
    by_type = {str(item.get(key) or "").upper(): item for item in options}
    for item_type in priority:
        if item_type in by_type:
            return by_type[item_type]
    return options[0]


def choose_research_option(rc: dict[str, Any]) -> str | None:
    option = select_by_priority(
        [row for row in rc.get("available_techs", []) if isinstance(row, dict)],
        "tech_type",
        TECH_PRIORITY,
    )
    return str(option["tech_type"]) if option else None


def choose_civic_option(rc: dict[str, Any]) -> str | None:
    option = select_by_priority(
        [row for row in rc.get("available_civics", []) if isinstance(row, dict)],
        "civic_type",
        CIVIC_PRIORITY,
    )
    return str(option["civic_type"]) if option else None


def choose_pantheon_belief(status: dict[str, Any]) -> str | None:
    beliefs = [row for row in status.get("available_beliefs", []) if isinstance(row, dict)]
    if not beliefs:
        return None
    by_type = {str(row.get("belief_type") or "").upper(): row for row in beliefs}
    for wanted in ("BELIEF_FERTILITY_RITES", "BELIEF_RELIGIOUS_SETTLEMENTS"):
        if wanted in by_type:
            return wanted
    return str(beliefs[0].get("belief_type") or "") or None


def _policy_choice(slot_type: str, available: list[dict[str, Any]], used: set[str]) -> str | None:
    compatible = []
    for policy in available:
        policy_type = str(policy.get("policy_type") or "")
        if not policy_type or policy_type in used:
            continue
        policy_slot = str(policy.get("slot_type") or policy.get("policy_slot") or "").upper()
        if policy_slot and slot_type and policy_slot != slot_type:
            continue
        compatible.append(policy_type)
    for wanted in POLICY_PRIORITY:
        if wanted in compatible:
            return wanted
    return compatible[0] if compatible else None


def choose_policy_assignments(status: dict[str, Any]) -> dict[int, str]:
    slots = [row for row in status.get("slots", []) if isinstance(row, dict)]
    available = [row for row in status.get("available_policies", []) if isinstance(row, dict)]
    assignments: dict[int, str] = {}
    used: set[str] = set()
    for slot in slots:
        slot_index = slot.get("slot_index")
        if slot_index is None:
            continue
        current = slot.get("current_policy") or slot.get("policy_type")
        if not current_value_empty(current):
            continue
        choice = _policy_choice(str(slot.get("slot_type") or "").upper(), available, used)
        if choice is None:
            continue
        assignments[int(slot_index)] = choice
        used.add(choice)
    return assignments


def choose_dedication(status: dict[str, Any]) -> int | None:
    choices = [row for row in status.get("choices", []) if isinstance(row, dict)]
    active = status.get("active") if isinstance(status.get("active"), list) else []
    allowed = int(status.get("selections_allowed") or 0)
    if not choices or allowed <= len(active):
        return None
    by_name = {str(row.get("name") or "").upper(): row for row in choices}
    choice = None
    for wanted in DEDICATION_PRIORITY:
        if wanted in by_name:
            choice = by_name[wanted]
            break
    choice = choice or choices[0]
    dedication_index = choice.get("index")
    return int(dedication_index) if dedication_index is not None else None

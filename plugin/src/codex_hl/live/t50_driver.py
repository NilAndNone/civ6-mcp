"""Live strict T50 driver for the standard Civ6 ``test 1`` save.

The driver is intentionally small-strategy and evidence-heavy: every real game
mutation is submitted as a JSON plan, armed, and executed through
``ActionGateway``. Runtime evidence remains in local ``episodes/`` and
``outputs/`` artifacts; this module is the tracked public entrypoint.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

from civ6_connector.connection import GameConnection
from civ6_connector.game_state import GameState
from codex_hl.diagnostics import load_test1
from codex_hl.evidence.store import EpisodeStore
from codex_hl.live.actions import classify_action
from codex_hl.live.gateway import ActionGateway, ActionRequest, GatewayMode
from codex_hl.live.ledger import EpisodeLedger, now_iso
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import normalize_turn_plan
from codex_hl.live.state_machine import LiveStateError
from codex_hl.live.verifier import PostconditionVerifier


BRANCH_ID = "b000"
WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
OUTPUT_ROOT = WORKSPACE_ROOT / "outputs"

TECH_PRIORITY = [
    "TECH_POTTERY",
    "TECH_ANIMAL_HUSBANDRY",
    "TECH_MINING",
    "TECH_WRITING",
    "TECH_ARCHERY",
    "TECH_IRRIGATION",
    "TECH_BRONZE_WORKING",
    "TECH_MASONRY",
    "TECH_THE_WHEEL",
    "TECH_CURRENCY",
    "TECH_HORSEBACK_RIDING",
    "TECH_CONSTRUCTION",
    "TECH_ENGINEERING",
    "TECH_APPRENTICESHIP",
]

CIVIC_PRIORITY = [
    "CIVIC_CODE_OF_LAWS",
    "CIVIC_CRAFTSMANSHIP",
    "CIVIC_FOREIGN_TRADE",
    "CIVIC_EARLY_EMPIRE",
    "CIVIC_STATE_WORKFORCE",
    "CIVIC_POLITICAL_PHILOSOPHY",
    "CIVIC_MILITARY_TRADITION",
    "CIVIC_GAMES_RECREATION",
    "CIVIC_DRAMA_POETRY",
]

POLICY_PRIORITY = [
    "POLICY_URBAN_PLANNING",
    "POLICY_DISCIPLINE",
    "POLICY_GOD_KING",
    "POLICY_AGOGE",
    "POLICY_CARAVANSARIES",
    "POLICY_COLONIZATION",
]

DEDICATION_PRIORITY = [
    "COMMEMORATION_SCIENTIFIC",
    "COMMEMORATION_FREE_INQUIRY",
    "COMMEMORATION_MONUMENTALITY",
    "COMMEMORATION_EXODUS",
]

PRODUCTION_PRIORITY_EXPAND = [
    "UNIT_SETTLER",
    "UNIT_BUILDER",
    "UNIT_SLINGER",
    "BUILDING_MONUMENT",
    "UNIT_WARRIOR",
    "BUILDING_GRANARY",
]

PRODUCTION_PRIORITY_STABILIZE = [
    "UNIT_BUILDER",
    "UNIT_SLINGER",
    "BUILDING_MONUMENT",
    "BUILDING_GRANARY",
    "UNIT_SETTLER",
    "UNIT_WARRIOR",
]


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(jsonable(item) for item in value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def response(data: dict[str, Any]) -> str:
    return json.dumps(jsonable(data), ensure_ascii=False, indent=2)


def context_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


async def safe_field(name: str, fn: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
    try:
        return {"ok": True, "field": name, "value": await fn()}
    except Exception as exc:  # noqa: BLE001 - context should preserve read gaps.
        return {
            "ok": False,
            "field": name,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _missing_field(name: str) -> Any:
    raise AttributeError(f"GameState has no {name}")


def _reader(gs: GameState, name: str) -> Callable[[], Awaitable[Any]]:
    return getattr(gs, name, lambda: _missing_field(name))


def _value(field: dict[str, Any], fallback: Any) -> Any:
    return field.get("value") if field.get("ok") else fallback


def _gap(field: dict[str, Any]) -> dict[str, Any] | None:
    if field.get("ok"):
        return None
    return {
        "field": field.get("field"),
        "taxonomy": "state_representation_gap",
        "error": field.get("error"),
    }


def turn_from_overview(overview: Any) -> int:
    if isinstance(overview, dict):
        value = overview.get("turn")
    else:
        value = getattr(overview, "turn", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def cities_from_payload(cities: Any) -> list[dict[str, Any]]:
    value = jsonable(cities)
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], list):
        return [row for row in value[0] if isinstance(row, dict)]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _safe_rows(value: Any) -> list[dict[str, Any]]:
    value = jsonable(value)
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in value:
        if isinstance(row, dict):
            rows.append(row)
        elif isinstance(row, list):
            rows.extend(item for item in row if isinstance(item, dict))
    return rows


def _resource_summary(resources: Any) -> dict[str, Any]:
    value = jsonable(resources)
    if isinstance(value, list) and len(value) == 4:
        stockpile, owned, nearby, totals = value
        return {
            "stockpile": stockpile if isinstance(stockpile, list) else [],
            "owned": owned if isinstance(owned, list) else [],
            "nearby": nearby if isinstance(nearby, list) else [],
            "totals": totals if isinstance(totals, dict) else {},
        }
    return {"stockpile": [], "owned": [], "nearby": [], "totals": {}}


def _append_structural_gaps(payload: dict[str, Any], known_gaps: list[dict[str, Any]]) -> None:
    overview = payload.get("overview") if isinstance(payload.get("overview"), dict) else {}
    for key in ("gold", "gold_per_turn", "science_yield", "culture_yield", "num_cities"):
        if key not in overview:
            known_gaps.append(
                {
                    "field": f"overview.{key}",
                    "taxonomy": "state_representation_gap",
                    "error": "field missing from overview",
                }
            )
    for city in payload.get("cities", []):
        if not isinstance(city, dict):
            continue
        city_id = city.get("city_id", "unknown")
        for key in ("currently_building", "production_turns_left", "loyalty", "loyalty_per_turn"):
            if key not in city:
                known_gaps.append(
                    {
                        "field": f"cities[{city_id}].{key}",
                        "taxonomy": "state_representation_gap",
                        "error": "field missing from city row",
                    }
                )


async def capture_context(
    gs: GameState,
    *,
    episode_id: str,
    plan_store: LivePlanStore | None = None,
) -> dict[str, Any]:
    overview_field = await safe_field("overview", _reader(gs, "get_game_overview"))
    cities_field = await safe_field("cities", _reader(gs, "get_cities"))
    units_field = await safe_field("units", _reader(gs, "get_units"))
    notifications_field = await safe_field("notifications", _reader(gs, "get_notifications"))
    research_civic_field = await safe_field("research_civic", _reader(gs, "get_tech_civics"))
    threats_field = await safe_field("threats", _reader(gs, "get_threat_scan"))
    resources_field = await safe_field("resources", _reader(gs, "get_empire_resources"))

    overview = jsonable(_value(overview_field, {}))
    cities_raw = jsonable(_value(cities_field, []))
    units = jsonable(_value(units_field, []))
    notifications = jsonable(_value(notifications_field, []))
    research_civic = jsonable(_value(research_civic_field, {}))
    threats = jsonable(_value(threats_field, []))
    resources = _resource_summary(_value(resources_field, []))
    known_gaps = [
        gap
        for gap in (
            _gap(overview_field),
            _gap(cities_field),
            _gap(units_field),
            _gap(notifications_field),
            _gap(research_civic_field),
            _gap(threats_field),
            _gap(resources_field),
        )
        if gap is not None
    ]
    cities = cities_from_payload(cities_raw)
    turn = turn_from_overview(overview)
    payload = {
        "episode_id": episode_id,
        "turn": turn,
        "branch_id": BRANCH_ID,
        "overview": overview if isinstance(overview, dict) else {},
        "cities": cities,
        "units": units if isinstance(units, list) else [],
        "notifications": notifications if isinstance(notifications, list) else [],
        "research_civic": research_civic if isinstance(research_civic, dict) else {},
        "threats": threats if isinstance(threats, list) else [],
        "resources": resources,
        "production": {
            "cities": [
                {
                    "city_id": city.get("city_id"),
                    "currently_building": city.get("currently_building"),
                    "production_turns_left": city.get("production_turns_left"),
                    "production": city.get("production"),
                }
                for city in cities
            ]
        },
        "available_action_summary": {
            "city_count": len(cities),
            "unit_count": len(units) if isinstance(units, list) else 0,
            "threat_count": len(threats) if isinstance(threats, list) else 0,
        },
        "known_gaps": known_gaps,
        "evidence_issues": known_gaps,
    }
    _append_structural_gaps(payload, known_gaps)
    payload["context_hash"] = context_hash(payload)
    if plan_store is not None:
        plan_store.record_turn_context(
            turn=turn,
            branch_id=BRANCH_ID,
            context_hash=payload["context_hash"],
            payload=payload,
        )
    return payload


async def verifier_state(gs: GameState, episode_id: str) -> dict[str, Any]:
    return await capture_context(gs, episode_id=episode_id, plan_store=None)


def default_episode_id() -> str:
    return f"phase5_live_t50_driver_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def ensure_episode(
    *,
    workspace: Path,
    episode_id: str,
    start_turn: int,
    target_turn: int,
) -> tuple[Path, LivePlanStore, EpisodeStore]:
    episode_root = workspace / "episodes" / episode_id
    store = EpisodeStore(episode_root, episode_id)
    if not store.has_artifact("header.json"):
        store.put_episode_header(
            {
                "episode_id": episode_id,
                "workflow": "live-json-plan",
                "save_name": "test 1",
                "requested_turns": target_turn,
                "target_turn": target_turn,
                "runner": "codex-hl-civ6-live-t50-driver",
                "runner_kind": "live",
                "mode": "live_strict",
                "start_turn": start_turn,
                "created_at": now_iso(),
                "note": (
                    "Live strict T50 driver; all L2+ mutations are JSON-plan "
                    "armed steps through ActionGateway."
                ),
            },
            workflow="live-json-plan",
            save_name="test 1",
            requested_turns=target_turn,
            start_turn=start_turn,
        )
    plan_store = LivePlanStore.for_episode_root(episode_root, episode_id)
    try:
        plan_store.start_episode(
            save_name="test 1",
            target_turns=target_turn,
            mode="live_strict",
            runner="codex-hl-civ6-live-t50-driver",
            branch_id=BRANCH_ID,
        )
    except LiveStateError as exc:
        if "already active" not in str(exc):
            raise
    return episode_root, plan_store, store


def read_last_seq(plan_store: LivePlanStore) -> int:
    state = plan_store.replay()
    max_plan = 0
    for plan_id in state.plans:
        match = re.search(r"p(\d+)_", plan_id)
        if match:
            max_plan = max(max_plan, int(match.group(1)))
    return max_plan


def plan_payload(
    *,
    episode_id: str,
    seq: int,
    tool: str,
    args: dict[str, Any],
    turn: int,
    context_hash_value: str,
    postconditions: list[dict[str, Any]] | None,
    metadata: dict[str, Any] | None = None,
    rationale: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    plan_id = f"p{seq:04d}_{tool}"
    step_id = f"s{seq:04d}"
    spec = classify_action(tool, args)
    payload = {
        "episode_id": episode_id,
        "plan_id": plan_id,
        "turn": turn,
        "branch_id": BRANCH_ID,
        "context_hash": context_hash_value,
        "metadata": {
            "driver": "codex_hl.live.t50_driver",
            **(metadata or {}),
        },
        "steps": [
            {
                "step_id": step_id,
                "tool": tool,
                "args": args,
                "allowed_mutation_level": spec.mutation_level.value,
                "postconditions": postconditions or [],
                "rationale": rationale or "live T50 driver JSON-plan step",
            }
        ],
    }
    return plan_id, step_id, payload


async def execute_step(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    tool: str,
    args: dict[str, Any],
    fn: Callable[[], Awaitable[Any]],
    postconditions: list[dict[str, Any]] | None = None,
    source: str = "live_plan",
    metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
    rationale: str | None = None,
    verify_with_state: bool = True,
) -> dict[str, Any]:
    context = await capture_context(gs, episode_id=episode_id, plan_store=plan_store)
    plan_id, step_id, raw_plan = plan_payload(
        episode_id=episode_id,
        seq=seq,
        tool=tool,
        args=args,
        turn=int(context["turn"]),
        context_hash_value=str(context["context_hash"]),
        postconditions=postconditions,
        metadata=metadata,
        rationale=rationale,
    )
    plan_store.submit_plan(normalize_turn_plan(raw_plan))
    plan_store.arm_step(plan_id, step_id)
    spec = classify_action(tool, args)

    async def timed_fn() -> Any:
        value = fn()
        if timeout_seconds is None:
            return await value
        return await asyncio.wait_for(value, timeout=timeout_seconds)

    request = ActionRequest(
        source=source,  # type: ignore[arg-type]
        tool_name=tool,
        args=args,
        mutation_level=spec.mutation_level,
        episode_id=episode_id,
        turn=int(context["turn"]),
        plan_id=plan_id,
        step_id=step_id,
        context_hash=str(context["context_hash"]),
        branch_id=BRANCH_ID,
    )
    try:
        result = await gateway.execute(
            request,
            timed_fn,
            state_reader=(lambda: verifier_state(gs, episode_id)) if verify_with_state else None,
        )
        return {
            "seq": seq,
            "turn": context["turn"],
            "plan_id": plan_id,
            "step_id": step_id,
            "tool": tool,
            "args": args,
            "allowed": result.allowed,
            "status": result.status,
            "verifier_status": result.verifier_status,
            "error": result.error,
            "error_code": result.error_code,
            "result": result.result,
            "ledger_event_ids": result.ledger_event_ids,
            "metadata": metadata or {},
        }
    except Exception as exc:  # noqa: BLE001 - caller needs evidence, not an orphaned EXECUTING step.
        return {
            "seq": seq,
            "turn": context["turn"],
            "plan_id": plan_id,
            "step_id": step_id,
            "tool": tool,
            "args": args,
            "allowed": True,
            "status": "failed",
            "verifier_status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": "ACTION_TIMEOUT" if isinstance(exc, TimeoutError) else "ACTION_FAILED",
            "result": None,
            "ledger_event_ids": [],
            "metadata": metadata or {},
            "recovery_needed": True,
        }


def current_value_empty(value: Any) -> bool:
    if value is None:
        return True
    normalized = str(value).strip().lower()
    return normalized in {"", "none", "null", "nothing", "none."}


def select_by_priority(options: list[dict[str, Any]], key: str, priority: list[str]) -> dict[str, Any] | None:
    if not options:
        return None
    by_type = {str(item.get(key) or "").upper(): item for item in options}
    for item_type in priority:
        if item_type in by_type:
            return by_type[item_type]
    return options[0]


def _city_count(context: dict[str, Any]) -> int:
    cities = [row for row in context.get("cities", []) if isinstance(row, dict)]
    overview = context.get("overview") if isinstance(context.get("overview"), dict) else {}
    try:
        return max(len(cities), int(overview.get("num_cities") or 0))
    except (TypeError, ValueError):
        return len(cities)


def _settler_units(context: dict[str, Any]) -> list[dict[str, Any]]:
    settlers = []
    for unit in _safe_rows(context.get("units")):
        unit_type = str(unit.get("unit_type") or unit.get("type") or "").upper()
        name = str(unit.get("name") or "").upper()
        if unit_type == "UNIT_SETTLER" or "SETTLER" in name:
            settlers.append(unit)
    return settlers


def _unit_id(unit: dict[str, Any]) -> int:
    return int(unit.get("unit_id") if unit.get("unit_id") is not None else unit.get("unit_index"))


def _unit_index(unit: dict[str, Any]) -> int:
    return int(unit.get("unit_index") if unit.get("unit_index") is not None else _unit_id(unit) % 65536)


def _xy(row: dict[str, Any]) -> tuple[int, int] | None:
    try:
        return int(row["x"]), int(row["y"])
    except (KeyError, TypeError, ValueError):
        location = row.get("location")
        if isinstance(location, dict):
            try:
                return int(location["x"]), int(location["y"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _rough_city_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _far_enough_to_found(unit: dict[str, Any], cities: list[dict[str, Any]]) -> bool:
    if float(unit.get("moves_remaining") or 0) <= 0:
        return False
    unit_xy = _xy(unit)
    if unit_xy is None:
        return False
    city_positions = [_xy(city) for city in cities]
    city_positions = [pos for pos in city_positions if pos is not None]
    return bool(city_positions) and all(_rough_city_distance(unit_xy, pos) >= 3 for pos in city_positions)


def _candidate_score(candidate: dict[str, Any]) -> tuple[float, int, int]:
    loyalty = float(candidate.get("loyalty_pressure") or 0)
    resources = candidate.get("resources") if isinstance(candidate.get("resources"), list) else []
    return (
        float(candidate.get("score") or 0) + max(0.0, loyalty) + len(resources),
        int(candidate.get("total_prod") or 0),
        int(candidate.get("total_food") or 0),
    )


def _threat_positions(context: dict[str, Any]) -> list[tuple[int, int]]:
    positions = []
    for row in _safe_rows(context.get("threats")):
        pos = _xy(row)
        if pos is not None:
            positions.append(pos)
    return positions


async def _settle_candidates(gs: GameState, cities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    field = await safe_field("global_settle_scan", _reader(gs, "get_global_settle_scan"))
    rows = _safe_rows(_value(field, []))
    city_positions = [_xy(city) for city in cities]
    city_positions = [pos for pos in city_positions if pos is not None]
    candidates: list[dict[str, Any]] = []
    for row in rows:
        pos = _xy(row)
        if pos is None:
            continue
        if city_positions and any(_rough_city_distance(pos, city_pos) < 3 for city_pos in city_positions):
            continue
        if float(row.get("loyalty_pressure") or 0) < -5:
            continue
        candidates.append(row)
    return sorted(candidates, key=_candidate_score, reverse=True)


async def _fallback_settle_target(
    *,
    gs: GameState,
    settler: dict[str, Any],
    cities: list[dict[str, Any]],
    context: dict[str, Any],
) -> tuple[int, int] | None:
    settler_xy = _xy(settler)
    if settler_xy is None:
        return None
    city_positions = [_xy(city) for city in cities]
    city_positions = [pos for pos in city_positions if pos is not None]
    threats = _threat_positions(context)
    offsets = [
        (-4, 2),
        (-4, 0),
        (-3, 3),
        (0, 4),
        (-5, 1),
        (4, -2),
        (4, 0),
        (0, -4),
        (3, -3),
        (-2, -4),
        (2, 4),
    ]
    candidates = []
    for dx, dy in offsets:
        target = (settler_xy[0] + dx, settler_xy[1] + dy)
        if city_positions and any(_rough_city_distance(target, city_pos) < 3 for city_pos in city_positions):
            continue
        threat_distance = min((_rough_city_distance(target, threat) for threat in threats), default=6)
        city_distance = min((_rough_city_distance(target, city_pos) for city_pos in city_positions), default=4)
        score = threat_distance + city_distance * 0.25
        candidates.append((score, target))
    candidates.sort(reverse=True)
    unit_index = _unit_index(settler)
    for _score, target in candidates:
        path_field = await safe_field(
            f"pathing_{unit_index}_{target[0]}_{target[1]}",
            lambda target=target, unit_index=unit_index: gs.get_pathing_estimate(
                unit_index,
                target[0],
                target[1],
            ),
        )
        if not path_field.get("ok"):
            continue
        estimate = jsonable(path_field.get("value"))
        if not isinstance(estimate, dict):
            continue
        if int(estimate.get("total_tiles") or 0) > 0 or int(estimate.get("turns") or 0) >= 0:
            return target
    return candidates[0][1] if candidates else None


async def found_settler(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    settler: dict[str, Any],
    actions: list[dict[str, Any]],
    rationale: str,
) -> tuple[int, bool]:
    unit_index = _unit_index(settler)
    args = {
        "unit_id": _unit_id(settler),
        "unit_index": unit_index,
        "action": "found_city",
    }
    result = await execute_step(
        gs=gs,
        gateway=gateway,
        plan_store=plan_store,
        episode_id=episode_id,
        seq=seq,
        tool="unit_action",
        args=args,
        fn=lambda unit_index=unit_index: gs.found_city(unit_index),
        postconditions=[{"type": "city_count_increased"}],
        rationale=rationale,
    )
    actions.append(result)
    return seq + 1, result.get("verifier_status") == "PASS"


async def maybe_found_initial_city(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    context: dict[str, Any],
    actions: list[dict[str, Any]],
) -> tuple[int, bool]:
    if _city_count(context) > 0:
        return seq, False
    settlers = _settler_units(context)
    if not settlers:
        actions.append(
            {
                "seq": seq,
                "tool": "unit_action",
                "status": "skipped",
                "error_code": "NO_SETTLER_FOR_INITIAL_FOUND_CITY",
                "recovery_needed": True,
            }
        )
        return seq, False
    settler = sorted(
        settlers,
        key=lambda unit: (
            -float(unit.get("moves_remaining") or 0),
            _unit_index(unit),
        ),
    )[0]
    return await found_settler(
        gs=gs,
        gateway=gateway,
        plan_store=plan_store,
        episode_id=episode_id,
        seq=seq,
        settler=settler,
        actions=actions,
        rationale="settler must found the capital before any unit skipping",
    )


async def maybe_expand_with_settler(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    context: dict[str, Any],
    actions: list[dict[str, Any]],
    min_cities: int,
) -> tuple[int, bool]:
    cities = [row for row in context.get("cities", []) if isinstance(row, dict)]
    if _city_count(context) >= min_cities:
        return seq, False
    settlers = _settler_units(context)
    if not settlers:
        return seq, False
    settler = sorted(
        settlers,
        key=lambda unit: (
            -float(unit.get("moves_remaining") or 0),
            _unit_index(unit),
        ),
    )[0]
    if _far_enough_to_found(settler, cities):
        return await found_settler(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            settler=settler,
            actions=actions,
            rationale="found second city once settler reaches a legal expansion tile",
        )
    if float(settler.get("moves_remaining") or 0) <= 0:
        return seq, False
    candidates = await _settle_candidates(gs, cities)
    target_xy = _xy(candidates[0]) if candidates else None
    if target_xy is None:
        target_xy = await _fallback_settle_target(
            gs=gs,
            settler=settler,
            cities=cities,
            context=context,
        )
    if target_xy is None:
        actions.append(
            {
                "seq": seq,
                "tool": "unit_action",
                "status": "skipped",
                "taxonomy": "state_representation_gap",
                "error": "no settle scan candidate available for expansion settler",
            }
        )
        return seq, False
    unit_index = _unit_index(settler)
    args = {
        "unit_id": _unit_id(settler),
        "unit_index": unit_index,
        "action": "move",
        "target_x": target_xy[0],
        "target_y": target_xy[1],
    }
    actions.append(
        await execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            tool="unit_action",
            args=args,
            fn=lambda unit_index=unit_index, target_xy=target_xy: gs.move_unit(
                unit_index,
                target_xy[0],
                target_xy[1],
            ),
            postconditions=[
                {
                    "type": "unit_position_changed_or_blocked",
                    "unit_id": _unit_id(settler),
                    "target": {"x": target_xy[0], "y": target_xy[1]},
                }
            ],
            rationale="move expansion settler toward best known settle scan candidate",
        )
    )
    return seq + 1, False


async def handle_diplomacy_and_deals(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
) -> int:
    deals_field = await safe_field("pending_deals", _reader(gs, "get_pending_deals"))
    deals = jsonable(_value(deals_field, []))
    if isinstance(deals, list):
        for deal in deals:
            if not isinstance(deal, dict):
                continue
            player = deal.get("other_player_id") or deal.get("player_id")
            if player is None:
                continue
            args = {"other_player_id": int(player), "accept": False}
            actions.append(
                await execute_step(
                    gs=gs,
                    gateway=gateway,
                    plan_store=plan_store,
                    episode_id=episode_id,
                    seq=seq,
                    tool="respond_to_trade",
                    args=args,
                    fn=lambda player=int(player): gs.respond_to_deal(player, False),
                    postconditions=[{"type": "tool_result_ok"}],
                )
            )
            seq += 1
    sessions_field = await safe_field("diplomacy_sessions", _reader(gs, "get_diplomacy_sessions"))
    sessions = jsonable(_value(sessions_field, []))
    if isinstance(sessions, list):
        for session in sessions:
            if not isinstance(session, dict):
                continue
            player = session.get("other_player_id") or session.get("player_id")
            if player is None:
                continue
            args = {"other_player_id": int(player), "response": "POSITIVE"}
            actions.append(
                await execute_step(
                    gs=gs,
                    gateway=gateway,
                    plan_store=plan_store,
                    episode_id=episode_id,
                    seq=seq,
                    tool="respond_to_diplomacy",
                    args=args,
                    fn=lambda player=int(player): gs.diplomacy_respond(player, "POSITIVE"),
                    postconditions=[{"type": "tool_result_ok"}],
                )
            )
            seq += 1
    return seq


async def maybe_choose_research_or_civic(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    context: dict[str, Any],
    actions: list[dict[str, Any]],
) -> int:
    rc = context.get("research_civic") if isinstance(context.get("research_civic"), dict) else {}
    current_research = rc.get("current_research") or context.get("overview", {}).get("current_research")
    if current_value_empty(current_research):
        option = select_by_priority(
            [row for row in rc.get("available_techs", []) if isinstance(row, dict)],
            "tech_type",
            TECH_PRIORITY,
        )
        if option:
            tech = str(option["tech_type"])
            args = {"category": "tech", "tech_or_civic": tech}
            actions.append(
                await execute_step(
                    gs=gs,
                    gateway=gateway,
                    plan_store=plan_store,
                    episode_id=episode_id,
                    seq=seq,
                    tool="set_research",
                    args=args,
                    fn=lambda tech=tech: gs.set_research(tech),
                    postconditions=[
                        {"type": "research_or_civic_selected", "category": "tech", "value": tech}
                    ],
                )
            )
            seq += 1
    current_civic = rc.get("current_civic") or context.get("overview", {}).get("current_civic")
    if current_value_empty(current_civic):
        option = select_by_priority(
            [row for row in rc.get("available_civics", []) if isinstance(row, dict)],
            "civic_type",
            CIVIC_PRIORITY,
        )
        if option:
            civic = str(option["civic_type"])
            args = {"category": "civic", "tech_or_civic": civic}
            actions.append(
                await execute_step(
                    gs=gs,
                    gateway=gateway,
                    plan_store=plan_store,
                    episode_id=episode_id,
                    seq=seq,
                    tool="set_research",
                    args=args,
                    fn=lambda civic=civic: gs.set_civic(civic),
                    postconditions=[
                        {"type": "research_or_civic_selected", "category": "civic", "value": civic}
                    ],
                )
            )
            seq += 1
    return seq


async def maybe_choose_pantheon(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
) -> int:
    status_field = await safe_field("pantheon_status", _reader(gs, "get_pantheon_status"))
    status = jsonable(_value(status_field, {}))
    if not isinstance(status, dict) or status.get("has_pantheon") is True:
        return seq
    beliefs = [row for row in status.get("available_beliefs", []) if isinstance(row, dict)]
    if not beliefs:
        return seq
    by_type = {str(row.get("belief_type") or "").upper(): row for row in beliefs}
    belief = None
    for wanted in ("BELIEF_FERTILITY_RITES", "BELIEF_RELIGIOUS_SETTLEMENTS"):
        if wanted in by_type:
            belief = wanted
            break
    belief = belief or str(beliefs[0].get("belief_type") or "")
    if not belief:
        return seq
    actions.append(
        await execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            tool="choose_pantheon",
            args={"belief_type": belief},
            fn=lambda belief=belief: gs.choose_pantheon(belief),
            postconditions=[{"type": "tool_result_ok"}],
        )
    )
    return seq + 1


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


async def maybe_set_policies(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
) -> int:
    status_field = await safe_field("policies", _reader(gs, "get_policies"))
    status = jsonable(_value(status_field, {}))
    if not isinstance(status, dict):
        return seq
    slots = [row for row in status.get("slots", []) if isinstance(row, dict)]
    available = [row for row in status.get("available_policies", []) if isinstance(row, dict)]
    if not slots or not available:
        return seq
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
    if not assignments:
        return seq
    actions.append(
        await execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            tool="set_policies",
            args={"assignments": assignments},
            fn=lambda assignments=assignments: gs.set_policies(assignments),
            postconditions=[{"type": "tool_result_ok"}],
        )
    )
    return seq + 1


async def maybe_choose_dedication(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
) -> int:
    status_field = await safe_field("dedications", _reader(gs, "get_dedications"))
    status = jsonable(_value(status_field, {}))
    if not isinstance(status, dict):
        return seq
    choices = [row for row in status.get("choices", []) if isinstance(row, dict)]
    active = status.get("active") if isinstance(status.get("active"), list) else []
    allowed = int(status.get("selections_allowed") or 0)
    if not choices or allowed <= len(active):
        return seq
    by_name = {str(row.get("name") or "").upper(): row for row in choices}
    choice = None
    for wanted in DEDICATION_PRIORITY:
        if wanted in by_name:
            choice = by_name[wanted]
            break
    choice = choice or choices[0]
    dedication_index = choice.get("index")
    if dedication_index is None:
        return seq
    actions.append(
        await execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            tool="choose_dedication",
            args={"dedication_index": int(dedication_index)},
            fn=lambda dedication_index=int(dedication_index): gs.choose_dedication(dedication_index),
            postconditions=[{"type": "tool_result_ok"}],
        )
    )
    return seq + 1


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


def _threat_pressure(context: dict[str, Any]) -> int:
    threats = context.get("threats")
    if isinstance(threats, list):
        return len([item for item in threats if item is not None])
    return 0


def choose_production_option(options: list[dict[str, Any]], context: dict[str, Any]) -> tuple[str, str] | None:
    if not options:
        return None
    city_count = _city_count(context)
    priority = PRODUCTION_PRIORITY_EXPAND if city_count < 2 else PRODUCTION_PRIORITY_STABILIZE
    if city_count >= 2 and _threat_pressure(context) > 0:
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


async def maybe_set_city_production(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    context: dict[str, Any],
    actions: list[dict[str, Any]],
) -> int:
    cities = [row for row in context.get("cities", []) if isinstance(row, dict)]
    for city in cities:
        if not city_has_empty_queue(city):
            continue
        city_id = int(city["city_id"])
        production_field = await safe_field(
            f"production_{city_id}",
            lambda city_id=city_id: gs.list_city_production(city_id),
        )
        options = [row for row in jsonable(_value(production_field, [])) if isinstance(row, dict)]
        chosen = choose_production_option(options, context)
        if chosen is None:
            gap = _gap(production_field) or {
                "field": f"production_{city_id}",
                "taxonomy": "state_representation_gap",
                "error": "no production options available",
            }
            actions.append({"seq": seq, "tool": "set_city_production", "status": "skipped", **gap})
            continue
        item_type, item_name = chosen
        args = {"city_id": city_id, "item_type": item_type, "item_name": item_name}
        actions.append(
            await execute_step(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                tool="set_city_production",
                args=args,
                fn=lambda city_id=city_id, item_type=item_type, item_name=item_name: gs.set_city_production(
                    city_id,
                    item_type,
                    item_name,
                ),
                postconditions=[{"type": "city_production_set", "city_id": city_id, "item_name": item_name}],
            )
        )
        seq += 1
    return seq


async def skip_units(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
) -> int:
    actions.append(
        await execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            tool="skip_remaining_units",
            args={},
            fn=gs.skip_remaining_units,
            postconditions=[{"type": "tool_result_ok"}],
        )
    )
    return seq + 1


async def end_turn(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
    timeout_seconds: float,
) -> tuple[int, bool, dict[str, Any]]:
    before = await capture_context(gs, episode_id=episode_id, plan_store=None)
    before_turn = int(before.get("turn") or 0)
    result = await execute_step(
        gs=gs,
        gateway=gateway,
        plan_store=plan_store,
        episode_id=episode_id,
        seq=seq,
        tool="end_turn",
        args={"phase5_live_t50_driver": True},
        fn=gs.end_turn,
        postconditions=[{"type": "turn_advanced_exactly_one"}],
        metadata={"plan_kind": "normal_turn_boundary", "timeout_seconds": timeout_seconds},
        timeout_seconds=timeout_seconds,
        rationale="normal live strict turn boundary",
    )
    actions.append(result)
    if result.get("status") == "failed":
        return seq + 1, False, result
    after = await capture_context(gs, episode_id=episode_id, plan_store=None)
    after_turn = int(after.get("turn") or 0)
    return seq + 1, after_turn > before_turn, result


async def execute_recovery_restart_and_load(
    *,
    gs: GameState,
    gateway: ActionGateway,
    plan_store: LivePlanStore,
    episode_id: str,
    seq: int,
    actions: list[dict[str, Any]],
    save_name: str,
    failed_action: dict[str, Any],
    force_restart: bool,
    port: int,
    timeout_seconds: float = 480.0,
) -> int:
    metadata = {
        "plan_kind": "recovery",
        "recovery_lineage": {
            "failed_plan_id": failed_action.get("plan_id"),
            "failed_step_id": failed_action.get("step_id"),
            "failed_tool": failed_action.get("tool"),
            "error_code": failed_action.get("error_code"),
        },
    }

    async def load_save() -> str:
        payload = await load_test1.load_and_verify(
            save_name=save_name,
            port=port,
            initial_wait_seconds=5.0,
            verify_timeout=180.0,
            poll_seconds=5.0,
            launch_if_needed=True,
            connect_retries=3,
            load_retries=1,
            load_timeout=90.0,
            force_restart=force_restart,
            continue_screen=True,
        )
        if not payload.get("ok"):
            return "Error: recovery load failed: " + json.dumps(payload, ensure_ascii=False)
        return "RECOVERY_LOAD_OK|" + save_name

    actions.append(
        await execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=plan_store,
            episode_id=episode_id,
            seq=seq,
            tool="restart_and_load",
            args={"save_name": save_name, "force_restart": force_restart},
            fn=load_save,
            postconditions=[{"type": "tool_result_ok"}],
            source="recovery",
            metadata=metadata,
            timeout_seconds=timeout_seconds,
            rationale="explicit recovery plan after failed live turn boundary",
            verify_with_state=False,
        )
    )
    return seq + 1


async def run(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    episode_id = args.episode_id or default_episode_id()
    conn = GameConnection(port=args.port)
    if args.load_test1:
        try:
            await conn.ensure_connected()
        except Exception:
            pass
    else:
        await conn.ensure_connected()
    store: EpisodeStore | None = None
    try:
        gs = GameState(conn)
        initial = await capture_context(gs, episode_id=episode_id, plan_store=None)
        start_turn = int(initial.get("turn") or 0)
        episode_root, plan_store, store = ensure_episode(
            workspace=workspace,
            episode_id=episode_id,
            start_turn=start_turn,
            target_turn=args.target_turn,
        )
        ledger = EpisodeLedger.for_episode_root(episode_root, episode_id, store=store, branch_id=BRANCH_ID)
        gateway = ActionGateway(
            mode=GatewayMode.LIVE_STRICT,
            ledger=ledger,
            verifier=PostconditionVerifier(),
            plan_store=plan_store,
        )
        seq = read_last_seq(plan_store) + 1
        actions: list[dict[str, Any]] = []
        if args.load_test1:
            seq = await execute_recovery_restart_and_load(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
                save_name=args.save_name,
                failed_action={
                    "plan_id": None,
                    "step_id": None,
                    "tool": "initial_load",
                    "error_code": "INITIAL_TEST1_LOAD",
                },
                force_restart=args.force_restart,
                port=args.port,
                timeout_seconds=480.0,
            )
            if not actions or actions[-1].get("verifier_status") != "PASS":
                final_context = await capture_context(gs, episode_id=episode_id, plan_store=plan_store)
                final_turn = int(final_context.get("turn") or 0)
                final_cities = _city_count(final_context)
                store.update_episode_run(final_turn=final_turn)
                summary = {
                    "ok": False,
                    "episode_id": episode_id,
                    "episode_root": str(episode_root),
                    "start_turn": start_turn,
                    "final_turn": final_turn,
                    "target_turn": args.target_turn,
                    "num_cities": final_cities,
                    "min_cities": args.min_cities,
                    "turn_advances": 0,
                    "actions": len(actions),
                    "finish_error": None,
                    "failure_taxonomy": "civ6_firetuner_instability",
                    "recovery_needed": True,
                    "last_actions": actions[-10:],
                }
                summary_path = OUTPUT_ROOT / "phase5" / f"{episode_id}_driver_summary.json"
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(response(summary) + "\n", encoding="utf-8")
                summary["summary_path"] = str(summary_path)
                return summary
            await conn.reconnect()
            gs = GameState(conn)

        turn_advances = 0
        consecutive_no_advance = 0
        current = await capture_context(gs, episode_id=episode_id, plan_store=plan_store)
        while int(current.get("turn") or 0) < args.target_turn:
            if len(actions) >= args.max_actions:
                break
            seq = await handle_diplomacy_and_deals(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
            )
            current = await capture_context(gs, episode_id=episode_id, plan_store=None)
            seq, founded = await maybe_found_initial_city(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                context=current,
                actions=actions,
            )
            if _city_count(current) == 0 and not founded:
                break
            current = await capture_context(gs, episode_id=episode_id, plan_store=None)
            seq = await maybe_choose_research_or_civic(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                context=current,
                actions=actions,
            )
            seq = await maybe_choose_pantheon(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
            )
            seq = await maybe_set_policies(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
            )
            seq = await maybe_choose_dedication(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
            )
            current = await capture_context(gs, episode_id=episode_id, plan_store=None)
            seq = await maybe_set_city_production(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                context=current,
                actions=actions,
            )
            current = await capture_context(gs, episode_id=episode_id, plan_store=None)
            seq, _expanded = await maybe_expand_with_settler(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                context=current,
                actions=actions,
                min_cities=args.min_cities,
            )
            seq = await skip_units(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
            )
            seq, advanced, end_turn_action = await end_turn(
                gs=gs,
                gateway=gateway,
                plan_store=plan_store,
                episode_id=episode_id,
                seq=seq,
                actions=actions,
                timeout_seconds=args.end_turn_timeout,
            )
            if end_turn_action.get("status") == "failed":
                if args.recovery_save_name:
                    seq = await execute_recovery_restart_and_load(
                        gs=gs,
                        gateway=gateway,
                        plan_store=plan_store,
                        episode_id=episode_id,
                        seq=seq,
                        actions=actions,
                        save_name=args.recovery_save_name,
                        failed_action=end_turn_action,
                        force_restart=args.recovery_force_restart,
                        port=args.port,
                    )
                break
            if advanced:
                turn_advances += 1
                consecutive_no_advance = 0
            else:
                consecutive_no_advance += 1
            current = await capture_context(gs, episode_id=episode_id, plan_store=plan_store)
            print(
                json.dumps(
                    {
                        "episode_id": episode_id,
                        "turn": current.get("turn"),
                        "cities": _city_count(current),
                        "advanced": advanced,
                        "turn_advances": turn_advances,
                        "actions": len(actions),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if consecutive_no_advance >= args.max_no_advance:
                actions.append(
                    {
                        "tool": "driver_no_advance_guard",
                        "status": "failed",
                        "error_code": "NO_ADVANCE_LIMIT",
                        "recovery_needed": True,
                        "consecutive_no_advance": consecutive_no_advance,
                    }
                )
                break

        final_context = await capture_context(gs, episode_id=episode_id, plan_store=plan_store)
        final_turn = int(final_context.get("turn") or 0)
        final_cities = _city_count(final_context)
        store.update_episode_run(final_turn=final_turn)
        finish_error = None
        if final_turn >= args.target_turn:
            try:
                plan_store.finish_episode()
            except LiveStateError as exc:
                finish_error = str(exc)
                actions.append({"tool": "finish_episode", "error": finish_error})
        summary = {
            "ok": final_turn >= args.target_turn and final_cities >= args.min_cities and finish_error is None,
            "episode_id": episode_id,
            "episode_root": str(episode_root),
            "start_turn": start_turn,
            "final_turn": final_turn,
            "target_turn": args.target_turn,
            "num_cities": final_cities,
            "min_cities": args.min_cities,
            "turn_advances": turn_advances,
            "actions": len(actions),
            "finish_error": finish_error,
            "last_actions": actions[-10:],
        }
        summary_path = OUTPUT_ROOT / "phase5" / f"{episode_id}_driver_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(response(summary) + "\n", encoding="utf-8")
        summary["summary_path"] = str(summary_path)
        return summary
    finally:
        if store is not None:
            store.close()
        await conn.disconnect()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--episode-id")
    parser.add_argument("--save-name", default="test 1")
    parser.add_argument("--target-turn", type=int, default=51)
    parser.add_argument("--min-cities", type=int, default=2)
    parser.add_argument("--max-actions", type=int, default=500)
    parser.add_argument("--max-no-advance", type=int, default=8)
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--end-turn-timeout", type=float, default=120.0)
    parser.add_argument("--load-test1", action="store_true")
    parser.add_argument("--force-restart", action="store_true")
    parser.add_argument("--recovery-save-name")
    parser.add_argument("--recovery-force-restart", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001 - script output should be machine-readable.
        print(response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise
    print(response(result))


if __name__ == "__main__":
    main()

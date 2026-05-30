"""Support helpers for human-demo capture.

These helpers are intentionally limited to read-only capture, connection
logging, JSON normalization, and fact summaries. They do not provide a rules
runner, action policy, or legacy T50 heuristic.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

from civ6_connector.connection import GameConnection
from civ6_connector.game_state import GameState


ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
WORKFLOW_LABEL = "Human Demo"
DEFAULT_SAVE_NAME = "test 1"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, set):
        return sorted(to_jsonable(v) for v in value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return value


def short_text(value: Any, limit: int = 360) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def run_git(args: list[str]) -> str:
    git = Path(r"C:\Program Files\Git\cmd\git.exe")
    cmd = [str(git) if git.exists() else "git", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return (result.stdout or result.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001 - demo reports should preserve environment gaps.
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


class RecordingConnection(GameConnection):
    def __init__(self, recorder: Any):
        super().__init__()
        self.recorder = recorder

    async def execute_read(self, lua_code: str, timeout: float = 5.0) -> list[str]:
        return await self.recorder.log_lua(
            "gamecore",
            lua_code,
            timeout,
            lambda: super(RecordingConnection, self).execute_read(lua_code, timeout),
        )

    async def execute_write(self, lua_code: str, timeout: float = 5.0) -> list[str]:
        return await self.recorder.log_lua(
            "ingame",
            lua_code,
            timeout,
            lambda: super(RecordingConnection, self).execute_write(lua_code, timeout),
        )

    async def execute_in_state(self, state_index: int, lua_code: str, timeout: float = 5.0) -> list[str]:
        return await self.recorder.log_lua(
            f"state:{state_index}",
            lua_code,
            timeout,
            lambda: super(RecordingConnection, self).execute_in_state(state_index, lua_code, timeout),
        )


def is_transient_tool_error(exc: Exception) -> bool:
    message = str(exc)
    return any(
        marker in message
        for marker in [
            "Empty overview response",
            "Cannot connect to Civ 6",
            "Connection changed",
        ]
    )


async def required_tool_with_retries(
    recorder: Any,
    name: str,
    params: dict[str, Any],
    fn: Callable[[], Awaitable[Any]],
    *,
    turn: int | None = None,
    attempts: int = 3,
    delay_seconds: float = 2.0,
) -> tuple[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        call_params = dict(params)
        if attempt > 1:
            call_params["retry_attempt"] = attempt
        try:
            return await recorder.tool_call(name, call_params, fn, turn=turn)
        except Exception as exc:  # noqa: BLE001 - retry preserves raw failed call.
            last_exc = exc
            if attempt >= attempts or not is_transient_tool_error(exc):
                raise
            recorder.timeline(
                f"- Retrying required tool `{name}` after transient {type(exc).__name__}: {short_text(exc, 240)}."
            )
            await asyncio.sleep(delay_seconds * attempt)
    assert last_exc is not None
    raise last_exc


async def safe_tool(
    recorder: Any,
    name: str,
    params: dict[str, Any],
    fn: Callable[[], Awaitable[Any]],
    *,
    turn: int | None,
    gaps: list[dict[str, str]],
    field: str,
) -> tuple[str | None, Any | None]:
    try:
        return await recorder.tool_call(name, params, fn, turn=turn)
    except Exception as exc:  # noqa: BLE001 - snapshot should continue with a gap.
        gap = {
            "field": field,
            "reason": f"{type(exc).__name__}: {exc}",
            "next_step": f"Investigate or add a minimal Civ6 MCP query for {field}.",
        }
        gaps.append(gap)
        recorder.add_gap(gap["field"], gap["reason"], gap["next_step"])
        return None, None


def _rows(value: Any) -> list[Any]:
    value = to_jsonable(value)
    if isinstance(value, list):
        return value
    return []


def _overview_value(overview: Any, key: str, default: Any = None) -> Any:
    overview = to_jsonable(overview)
    if isinstance(overview, dict):
        return overview.get(key, default)
    return getattr(overview, key, default)


def demo_episode_fact_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return factual snapshot counts without strategy recommendations."""

    overview = snapshot.get("overview")
    cities = _rows(snapshot.get("cities"))
    units = _rows(snapshot.get("units"))
    threats = _rows(snapshot.get("threats"))
    resources = to_jsonable(snapshot.get("resources"))
    return {
        "turn": snapshot.get("turn"),
        "city_count": len(cities),
        "unit_count": len(units),
        "threat_count": len(threats),
        "science": _overview_value(overview, "science_yield", 0),
        "culture": _overview_value(overview, "culture_yield", 0),
        "gold": _overview_value(overview, "gold", 0),
        "gold_per_turn": _overview_value(overview, "gold_per_turn", 0),
        "known_gap_count": len(_rows(snapshot.get("known_gaps"))),
        "resource_shape": type(resources).__name__,
    }


async def capture_state(
    recorder: Any,
    gs: GameState,
    label: str,
) -> tuple[int, str, dict[str, Any]]:
    gaps: list[dict[str, str]] = []
    related: list[str] = []
    captured: dict[str, Any] = {}

    call_id, overview = await required_tool_with_retries(
        recorder, "get_game_overview", {}, gs.get_game_overview
    )
    related.append(call_id)
    turn = int(_overview_value(overview, "turn", 0))
    if recorder.start_turn is None:
        recorder.start_turn = turn

    identity_call_id, identity = await safe_tool(
        recorder,
        "get_game_identity",
        {},
        gs.get_game_identity,
        turn=turn,
        gaps=gaps,
        field="empire.identity",
    )
    if identity_call_id:
        related.append(identity_call_id)

    for name, field, fn in [
        ("get_diary_snapshot", "empire.diary_snapshot", gs.get_diary_snapshot),
        ("get_cities", "cities", gs.get_cities),
        ("get_units", "units", gs.get_units),
        ("get_notifications", "notifications", gs.get_notifications),
        ("get_threat_scan", "threats", gs.get_threat_scan),
        ("get_tech_civics", "research_civic", gs.get_tech_civics),
        ("get_policies", "civic.policies", gs.get_policies),
        ("get_governors", "governors", gs.get_governors),
        ("get_empire_resources", "empire.resources", gs.get_empire_resources),
        ("get_diplomacy", "diplomacy", gs.get_diplomacy),
        ("get_victory_progress", "victory", gs.get_victory_progress),
        ("get_trade_routes", "trade_routes", gs.get_trade_routes),
        ("get_strategic_map", "exploration.strategic_map", gs.get_strategic_map),
        ("get_pantheon_beliefs", "religion.pantheon", gs.get_pantheon_status),
        ("get_religion_beliefs", "religion.founding", gs.get_religion_founding_status),
        ("get_great_people", "great_people", gs.get_great_people),
    ]:
        cid, value = await safe_tool(recorder, name, {}, fn, turn=turn, gaps=gaps, field=field)
        if cid:
            related.append(cid)
        captured[field] = value

    cities_value = captured.get("cities")
    cities = []
    city_distances = []
    if isinstance(cities_value, tuple):
        cities, city_distances = cities_value
    elif cities_value:
        cities = cities_value

    production_by_city: dict[str, Any] = {}
    for city in cities or []:
        city_json = to_jsonable(city)
        city_id = city_json.get("city_id") if isinstance(city_json, dict) else getattr(city, "city_id", None)
        if city_id is None:
            continue
        cid, options = await safe_tool(
            recorder,
            "get_city_production",
            {"city_id": city_id},
            lambda city_id=city_id: gs.list_city_production(city_id),
            turn=turn,
            gaps=gaps,
            field=f"production.city_{city_id}",
        )
        if cid:
            related.append(cid)
        production_by_city[str(city_id)] = options

    snapshot = {
        "workflow": WORKFLOW_LABEL,
        "turn": turn,
        "overview": overview,
        "identity": identity,
        "empire": captured.get("empire.diary_snapshot"),
        "cities": cities,
        "city_distances": city_distances,
        "units": captured.get("units"),
        "notifications": captured.get("notifications"),
        "threats": captured.get("threats"),
        "research_civic": captured.get("research_civic"),
        "policies": captured.get("civic.policies"),
        "governors": captured.get("governors"),
        "production": production_by_city,
        "resources": captured.get("empire.resources"),
        "diplomacy": captured.get("diplomacy"),
        "victory": captured.get("victory"),
        "trade_routes": captured.get("trade_routes"),
        "strategic_map": captured.get("exploration.strategic_map"),
        "pantheon_status": captured.get("religion.pantheon"),
        "religion_founding_status": captured.get("religion.founding"),
        "great_people": captured.get("great_people"),
        "known_gaps": gaps,
    }
    snapshot["demo_episode_fact_summary"] = demo_episode_fact_summary(snapshot)

    for key in ["empire", "cities", "units", "notifications", "threats", "research_civic", "production"]:
        if snapshot.get(key) is None:
            gap = {
                "field": key,
                "reason": "Current tool returned no data for this snapshot field.",
                "next_step": "Repair the corresponding Civ6 MCP query before using this demo as evidence.",
            }
            snapshot["known_gaps"].append(gap)
            recorder.add_gap(gap["field"], gap["reason"], gap["next_step"])

    snapshot_id = recorder.record_state(turn, label, snapshot, related)
    return turn, snapshot_id, snapshot

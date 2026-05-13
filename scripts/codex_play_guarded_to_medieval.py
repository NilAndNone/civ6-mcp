"""Guarded Civ VI run from the `test 1` save to the Medieval era.

This MCP-backed runner is intentionally conservative in the first 50 turns:
combat units guard the core, settlers wait for escorts, builders avoid visible
threats, ranged units avoid accidental melee attacks, and trade capacity is
filled quickly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from civ_mcp import game_launcher
from civ_mcp.connection import GameConnection
from civ_mcp.game_lifecycle import load_game_save, save_game
from civ_mcp.game_state import GameState


ROOT = Path(r"O:\civ6")
STATE_PATH = ROOT / "play_to_medieval_guarded_state.json"
LOG_DIR = ROOT / "logs"
FINAL_SAVE_PREFIX = "test_1_guarded_medieval"

TECH_PRIORITY = [
    "TECH_MINING",
    "TECH_ANIMAL_HUSBANDRY",
    "TECH_POTTERY",
    "TECH_WRITING",
    "TECH_ARCHERY",
    "TECH_THE_WHEEL",
    "TECH_CURRENCY",
    "TECH_BRONZE_WORKING",
    "TECH_IRON_WORKING",
    "TECH_HORSEBACK_RIDING",
    "TECH_APPRENTICESHIP",
    "TECH_MASONRY",
    "TECH_ENGINEERING",
    "TECH_MATHEMATICS",
    "TECH_CONSTRUCTION",
    "TECH_EDUCATION",
]

CIVIC_PRIORITY = [
    "CIVIC_CODE_OF_LAWS",
    "CIVIC_FOREIGN_TRADE",
    "CIVIC_CRAFTSMANSHIP",
    "CIVIC_EARLY_EMPIRE",
    "CIVIC_STATE_WORKFORCE",
    "CIVIC_POLITICAL_PHILOSOPHY",
    "CIVIC_MILITARY_TRADITION",
    "CIVIC_GAMES_RECREATION",
    "CIVIC_DRAMA_POETRY",
    "CIVIC_DEFENSIVE_TACTICS",
    "CIVIC_RECORDED_HISTORY",
    "CIVIC_FEUDALISM",
]

PANTHEON_PRIORITY = [
    "BELIEF_RELIGIOUS_SETTLEMENTS",
    "BELIEF_GOD_OF_THE_SEA",
    "BELIEF_FERTILITY_RITES",
    "BELIEF_GODDESS_OF_THE_HUNT",
    "BELIEF_CITY_PATRON_GODDESS",
    "BELIEF_DIVINE_SPARK",
]

GOVERNMENT_PRIORITY = [
    "GOVERNMENT_CLASSICAL_REPUBLIC",
    "GOVERNMENT_OLIGARCHY",
    "GOVERNMENT_AUTOCRACY",
    "GOVERNMENT_MERCHANT_REPUBLIC",
]

GOVERNOR_PRIORITY = [
    "GOVERNOR_THE_EDUCATOR",
    "GOVERNOR_THE_BUILDER",
    "GOVERNOR_THE_DEFENDER",
    "GOVERNOR_THE_RESOURCE_MANAGER",
]

GOVERNOR_PROMOTION_PRIORITY = [
    "GOVERNOR_PROMOTION_EDUCATOR_RESEARCHER",
    "GOVERNOR_PROMOTION_EDUCATOR_CONNOISSEUR",
    "GOVERNOR_PROMOTION_ZONING_COMMISSIONER",
    "GOVERNOR_PROMOTION_GARRISON_COMMANDER",
    "GOVERNOR_PROMOTION_RESOURCE_MANAGER_SURPLUS_LOGISTICS",
]

MILITARY_POLICY_PRIORITY = [
    "POLICY_DISCIPLINE",
    "POLICY_AGOGE",
    "POLICY_CONSCRIPTION",
    "POLICY_MARITIME_INDUSTRIES",
]

ECONOMIC_POLICY_PRIORITY = [
    "POLICY_URBAN_PLANNING",
    "POLICY_COLONIZATION",
    "POLICY_ILKUM",
    "POLICY_GOD_KING",
]

DIPLO_POLICY_PRIORITY = [
    "POLICY_CHARISMATIC_LEADER",
    "POLICY_DIPLOMATIC_LEAGUE",
]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_text(value: Any) -> str:
    text = str(value)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, set):
        return sorted(value)
    return value


class RunLog:
    def __init__(self, new_run: bool = False):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if STATE_PATH.exists() and not new_run:
            self.state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self.path = Path(self.state["log_path"])
            self.jsonl_path = Path(self.state["jsonl_path"])
            self.screenshot_dir = Path(self.state["screenshot_dir"])
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.screenshot_dir = LOG_DIR / f"play_to_medieval_guarded_{stamp}_screens"
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.path = LOG_DIR / f"play_to_medieval_guarded_{stamp}.md"
            self.jsonl_path = LOG_DIR / f"play_to_medieval_guarded_{stamp}.jsonl"
            self.state = {
                "created_at": now(),
                "log_path": str(self.path),
                "jsonl_path": str(self.jsonl_path),
                "screenshot_dir": str(self.screenshot_dir),
                "done": False,
            }
            self.path.write_text(
                "# Civ VI 本局逐步记录：test 1 至中世纪（修正版）\n\n"
                f"- 创建时间：{self.state['created_at']}\n"
                "- 目标：加载 `test 1` 存档并推进到中世纪。\n"
                "- 方法：通过 civ6 MCP GameState 执行实际操作，并周期性保存游戏窗口截图。\n"
                "- 本局原则：战士前 20 回合守核心；开拓者必须护送；建造者只在安全区工作；远程单位避免贴脸近战；商路容量出现后优先补商人和开线；平伽拉保持在科研核心城。\n\n",
                encoding="utf-8",
            )
            self.jsonl_path.write_text("", encoding="utf-8")
            self.save_state()

    def save_state(self) -> None:
        STATE_PATH.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def event(self, kind: str, turn: int | None, message: str, data: Any = None) -> None:
        prefix = f"- `{now()}`"
        if turn is not None:
            prefix += f" T{turn}"
        line = f"{prefix} **{kind}**: {message}\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
            if data is not None:
                text = safe_text(data)
                if "\n" in text:
                    f.write("\n```text\n")
                    f.write(text[:6000])
                    if len(text) > 6000:
                        f.write("\n... [truncated]\n")
                    f.write("\n```\n")
        row = {
            "ts": now(),
            "kind": kind,
            "turn": turn,
            "message": message,
            "data": to_jsonable(data),
        }
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def turn_header(self, turn: int) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"\n## Turn {turn}\n\n")

    def mark_done(self, overview: Any) -> None:
        self.state["done"] = True
        self.state["completed_at"] = now()
        self.state["final_turn"] = getattr(overview, "turn", None)
        self.state["final_era"] = getattr(overview, "era_name", "")
        self.save_state()


async def logged(log: RunLog, turn: int | None, kind: str, message: str, func):
    log.event(kind, turn, f"START {message}")
    try:
        result = await func()
        log.event(kind, turn, f"OK {message}", result)
        return result
    except Exception as exc:  # noqa: BLE001 - operational script logs and continues.
        log.event(kind, turn, f"ERROR {message}: {type(exc).__name__}: {exc}")
        raise


def is_medieval(era_name: str) -> bool:
    text = (era_name or "").upper()
    return "中世纪" in era_name or "MEDIEVAL" in text


def is_classical_or_later(era_name: str) -> bool:
    text = (era_name or "").upper()
    return (
        "古典" in era_name
        or "中世纪" in era_name
        or "CLASSICAL" in text
        or "MEDIEVAL" in text
    )


def needs_research(name: str) -> bool:
    return not name or name.lower() in {"none", "null", "no research", "无", "未选择"}


def idle_city(city: Any) -> bool:
    building = (city.currently_building or "").upper()
    return (
        building in {"", "NONE", "NOTHING", "CORRUPTED_QUEUE"}
        or city.production_turns_left <= 0
    )


def count_units(units: list[Any], unit_type: str) -> int:
    return sum(1 for u in units if u.unit_type == unit_type)


def is_combat_unit(unit: Any) -> bool:
    return unit.unit_type not in {
        "UNIT_SETTLER",
        "UNIT_BUILDER",
        "UNIT_TRADER",
        "UNIT_SCOUT",
    }


def is_civilian(unit: Any) -> bool:
    return unit.unit_type in {"UNIT_SETTLER", "UNIT_BUILDER", "UNIT_TRADER"}


def unit_by_id(units: list[Any], unit_id: int) -> Any | None:
    return next((u for u in units if u.unit_id == unit_id), None)


def nearest_city(cities: list[Any], x: int, y: int) -> Any | None:
    if not cities:
        return None
    return sorted(cities, key=lambda c: rough_distance(x, y, c.x, c.y))[0]


def nearest_core_tile(cities: list[Any], x: int, y: int) -> tuple[int, int] | None:
    city = nearest_city(cities, x, y)
    if city is None:
        return None
    return city.x, city.y


def threats_within(threats: list[Any], x: int, y: int, radius: int) -> list[Any]:
    return [t for t in threats if rough_distance(x, y, t.x, t.y) <= radius]


def serious_settler_threats(threats: list[Any], x: int, y: int, radius: int, escorted: bool) -> list[Any]:
    nearby = threats_within(threats, x, y, radius)
    if not escorted:
        return nearby
    return [
        t
        for t in nearby
        if not (
            getattr(t, "unit_type", "") == "UNIT_SCOUT"
        )
    ]


def target_xy(target: str) -> tuple[int, int] | None:
    match = re.search(r"@(-?\d+),(-?\d+)", target or "")
    if not match:
        match = re.search(r"\((-?\d+),(-?\d+)\)", target or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def target_hp(target: str) -> int:
    hp_match = re.search(r"\((\d+)hp\)", target or "", re.IGNORECASE)
    return int(hp_match.group(1)) if hp_match else 100


def is_barbarian_or_enemy(target: str) -> bool:
    upper = (target or "").upper()
    return "BARBARIAN" in upper or "UNIT_" in upper


def rough_distance(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by), abs((ax - bx) + (ay - by)))


def production_option(options: list[Any], category: str, item_name: str) -> Any | None:
    for opt in options:
        if opt.category == category and opt.item_name == item_name and not opt.is_repair:
            return opt
    return None


def choose_available(options: list[Any], priorities: list[tuple[str, str]]) -> Any | None:
    for category, item in priorities:
        opt = production_option(options, category, item)
        if opt is not None:
            return opt
    return None


async def capture_screen(log: RunLog, turn: int, tag: str) -> None:
    def _capture() -> Path | None:
        win = game_launcher._find_game_window()
        if not win:
            return None
        try:
            img = game_launcher._capture_window_win32(win.window_id)
            path = log.screenshot_dir / f"turn_{turn:03d}_{tag}.png"
            img.save(str(path))
            return path
        except Exception as exc:  # noqa: BLE001
            log.event("SCREENSHOT", turn, f"capture failed: {type(exc).__name__}: {exc}")
            return None

    path = await asyncio.to_thread(_capture)
    if path:
        log.event("SCREENSHOT", turn, f"saved {path}")
    else:
        log.event("SCREENSHOT", turn, "failed: game window not found")


async def ensure_research(gs: GameState, log: RunLog, turn: int) -> None:
    tc = await logged(log, turn, "MCP_QUERY", "get_tech_civics", gs.get_tech_civics)
    if needs_research(tc.current_research):
        available = {t.tech_type: t for t in tc.available_techs}
        chosen = next((tech for tech in TECH_PRIORITY if tech in available), None)
        if chosen is None and tc.available_techs:
            chosen = sorted(tc.available_techs, key=lambda t: (t.era, t.turns, t.cost))[0].tech_type
        if chosen:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"set_research tech {chosen}",
                lambda: gs.set_research(chosen),
            )
    if needs_research(tc.current_civic):
        available = {c.civic_type: c for c in tc.available_civics}
        chosen = next((civic for civic in CIVIC_PRIORITY if civic in available), None)
        if chosen is None and tc.available_civics:
            chosen = sorted(tc.available_civics, key=lambda c: (c.era, c.turns, c.cost))[0].civic_type
        if chosen:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"set_research civic {chosen}",
                lambda: gs.set_civic(chosen),
            )


async def choose_policies(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_policies", gs.get_policies)
    except Exception:
        return
    if not status.slots or not status.available_policies:
        return
    available = {p.policy_type: p for p in status.available_policies}
    assignments: dict[int, str] = {}
    used: set[str] = set()

    def pick(slot_type: str) -> str | None:
        if slot_type == "SLOT_MILITARY":
            prefs = MILITARY_POLICY_PRIORITY
        elif slot_type == "SLOT_ECONOMIC":
            prefs = ECONOMIC_POLICY_PRIORITY
        elif slot_type == "SLOT_DIPLOMATIC":
            prefs = DIPLO_POLICY_PRIORITY
        else:
            prefs = ECONOMIC_POLICY_PRIORITY + MILITARY_POLICY_PRIORITY + DIPLO_POLICY_PRIORITY
        for pol in prefs:
            info = available.get(pol)
            if info and pol not in used and (
                info.slot_type == slot_type or info.slot_type == "SLOT_WILDCARD" or slot_type == "SLOT_WILDCARD"
            ):
                used.add(pol)
                return pol
        return None

    for slot in status.slots:
        if slot.current_policy:
            used.add(slot.current_policy)
            continue
        selected = pick(slot.slot_type)
        if selected and selected != slot.current_policy:
            assignments[slot.slot_index] = selected

    if assignments:
        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"set_policies {assignments}",
            lambda: gs.set_policies(assignments),
        )


async def choose_pantheon(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_pantheon_status", gs.get_pantheon_status)
    except Exception:
        return
    if status.has_pantheon or not status.available_beliefs:
        return
    if status.faith_balance < 25:
        log.event(
            "DECISION",
            turn,
            f"pantheon available but skipped until enough faith ({status.faith_balance}/25)",
        )
        return
    available = {b.belief_type: b for b in status.available_beliefs}
    chosen = next((b for b in PANTHEON_PRIORITY if b in available), None)
    if chosen is None:
        chosen = status.available_beliefs[0].belief_type
    await logged(
        log,
        turn,
        "MCP_ACTION",
        f"choose_pantheon {chosen}",
        lambda: gs.choose_pantheon(chosen),
    )


async def choose_government(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_policies for government", gs.get_policies)
    except Exception:
        return
    if status.government_type and status.government_type not in {"GOVERNMENT_CHIEFDOM", "NONE"}:
        return
    for gov in GOVERNMENT_PRIORITY:
        result = await logged(
            log,
            turn,
            "MCP_ACTION",
            f"try change_government {gov}",
            lambda gov=gov: gs.change_government(gov),
        )
        if not str(result).startswith("Error"):
            return


async def choose_dedication(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_dedications", gs.get_dedications)
    except Exception:
        return
    if status.selections_allowed <= 0 or not status.choices:
        return
    preferred = ["COMMEMORATION_SCIENTIFIC", "COMMEMORATION_INFRASTRUCTURE", "COMMEMORATION_EXPLORATION"]
    by_name = {c.name: c for c in status.choices}
    choice = next((by_name[n] for n in preferred if n in by_name), status.choices[0])
    await logged(
        log,
        turn,
        "MCP_ACTION",
        f"choose_dedication {choice.index}:{choice.name}",
        lambda: gs.choose_dedication(choice.index),
    )


async def handle_envoys(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_city_states", gs.get_city_states)
    except Exception:
        return
    tokens = status.tokens_available
    while tokens > 0:
        candidates = [cs for cs in status.city_states if cs.can_send_envoy]
        if not candidates:
            return
        preferred = sorted(
            candidates,
            key=lambda cs: (
                0 if cs.city_state_type in {"Scientific", "Trade", "Industrial"} else 1,
                cs.envoys_sent,
                cs.name,
            ),
        )[0]
        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"send_envoy {preferred.player_id}:{preferred.name}",
            lambda preferred=preferred: gs.send_envoy(preferred.player_id),
        )
        tokens -= 1
        status = await gs.get_city_states()


async def handle_governors(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_governors", gs.get_governors)
    except Exception:
        return

    pingala = next((g for g in status.appointed if g.governor_type == "GOVERNOR_THE_EDUCATOR"), None)

    # First governor point should establish Pingala in the science core.  Later
    # points should not displace him with Liang/Victor as happened last run.
    if status.points_available > 0 and status.can_appoint and status.available_to_appoint:
        available = {g.governor_type: g for g in status.available_to_appoint}
        choice = "GOVERNOR_THE_EDUCATOR" if "GOVERNOR_THE_EDUCATOR" in available else next(
            (g for g in GOVERNOR_PRIORITY if g in available),
            status.available_to_appoint[0].governor_type,
        )
        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"appoint_governor {choice}",
            lambda choice=choice: gs.appoint_governor(choice),
        )
        try:
            status = await gs.get_governors()
        except Exception:
            return

    try:
        cities, _ = await gs.get_cities()
    except Exception:
        cities = []
    if cities:
        best_city = sorted(cities, key=lambda c: (-(c.science + c.culture + c.production), c.city_id))[0]
        pingala = next((g for g in status.appointed if g.governor_type == "GOVERNOR_THE_EDUCATOR"), None)
        if pingala and pingala.assigned_city_id < 0:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"assign_governor Pingala -> {best_city.name} (科研核心)",
                lambda best_city=best_city: gs.assign_governor("GOVERNOR_THE_EDUCATOR", best_city.city_id),
            )
            try:
                status = await gs.get_governors()
            except Exception:
                return
        pingala_city_id = next(
            (g.assigned_city_id for g in status.appointed if g.governor_type == "GOVERNOR_THE_EDUCATOR"),
            -1,
        )
        for gov in status.appointed:
            if gov.assigned_city_id < 0:
                candidate_cities = [c for c in cities if c.city_id != pingala_city_id]
                if not candidate_cities:
                    log.event(
                        "DECISION",
                        turn,
                        f"skip assigning {gov.governor_type}: only science-core city is available, preserving Pingala.",
                    )
                    continue
                target_city = sorted(
                    candidate_cities,
                    key=lambda c: (c.population, c.production, c.city_id),
                    reverse=True,
                )[0]
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"assign_governor {gov.governor_type} -> {target_city.name} (不替换平伽拉)",
                    lambda gov=gov, target_city=target_city: gs.assign_governor(gov.governor_type, target_city.city_id),
                )
                try:
                    status = await gs.get_governors()
                except Exception:
                    return
                break

    if status.points_available <= 0:
        return
    ordered_governors = sorted(
        status.appointed,
        key=lambda g: 0 if g.governor_type == "GOVERNOR_THE_EDUCATOR" else 1,
    )
    for gov in ordered_governors:
        options = {p.promotion_type: p for p in gov.available_promotions}
        choice = next((p for p in GOVERNOR_PROMOTION_PRIORITY if p in options), None)
        if choice:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"promote_governor {gov.governor_type} {choice}",
                lambda gov=gov, choice=choice: gs.promote_governor(gov.governor_type, choice),
            )
            return


async def handle_diplomacy(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        sessions = await logged(log, turn, "MCP_QUERY", "get_diplomacy_sessions", gs.get_diplomacy_sessions)
    except Exception:
        sessions = []
    for session in sessions:
        if session.deal_summary:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"reject_trade from {session.other_player_id}",
                lambda session=session: gs.respond_to_deal(session.other_player_id, False),
            )
        else:
            response = "POSITIVE" if not session.is_at_war else "NEGATIVE"
            for _ in range(3):
                result = await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"respond_to_diplomacy {session.other_player_id} {response}",
                    lambda session=session, response=response: gs.diplomacy_respond(session.other_player_id, response),
                )
                if "SESSION_CONTINUES" not in str(result):
                    break


async def handle_promotions(gs: GameState, log: RunLog, turn: int, units: list[Any]) -> None:
    for unit in units:
        if not unit.needs_promotion:
            continue
        try:
            status = await logged(
                log,
                turn,
                "MCP_QUERY",
                f"get_unit_promotions {unit.unit_id}",
                lambda unit=unit: gs.get_unit_promotions(unit.unit_id),
            )
            if status.promotions:
                choice = status.promotions[0].promotion_type
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"promote_unit {unit.unit_id} {choice}",
                    lambda unit=unit, choice=choice: gs.promote_unit(unit.unit_id, choice),
                )
        except Exception:
            continue


async def handle_unit_upgrades(gs: GameState, log: RunLog, turn: int, units: list[Any]) -> list[Any]:
    upgradeable = [
        unit
        for unit in units
        if is_combat_unit(unit) and unit.can_upgrade and unit.upgrade_cost > 0
    ]
    if not upgradeable:
        return units
    try:
        ov = await gs.get_game_overview()
    except Exception:
        return units
    gold = int(ov.gold)
    for unit in sorted(upgradeable, key=lambda u: (u.unit_type != "UNIT_WARRIOR", u.upgrade_cost)):
        if unit.upgrade_cost > gold:
            continue
        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"upgrade_unit {unit.unit_id} {unit.unit_type}->{unit.upgrade_target} ({unit.upgrade_cost}g)",
            lambda unit=unit: gs.upgrade_unit(unit.unit_id),
        )
        gold -= unit.upgrade_cost
    return await gs.get_units()


async def set_city_outputs(gs: GameState, log: RunLog, turn: int, units: list[Any]) -> None:
    cities, distances = await logged(log, turn, "MCP_QUERY", "get_cities", gs.get_cities)
    if distances:
        log.event("MCP_QUERY", turn, "city distance notes", distances)
    if not cities:
        return
    builder_count = count_units(units, "UNIT_BUILDER")
    settler_count = count_units(units, "UNIT_SETTLER")
    scout_count = count_units(units, "UNIT_SCOUT")
    slinger_count = count_units(units, "UNIT_SLINGER")
    trader_count = count_units(units, "UNIT_TRADER")
    city_count = len(cities)
    trade_capacity = 0
    active_routes = 0
    try:
        route_status = await gs.get_trade_routes()
        trade_capacity = route_status.capacity
        active_routes = route_status.active_count
        trader_count += sum(1 for t in route_status.traders if not t.on_route)
    except Exception:
        route_status = None
    try:
        threats = await gs.get_threat_scan()
    except Exception:
        threats = []
    threat_pressure = bool(threats)

    for city in cities:
        if not idle_city(city):
            continue
        options = await logged(
            log,
            turn,
            "MCP_QUERY",
            f"list_city_production {city.city_id}:{city.name}",
            lambda city=city: gs.list_city_production(city.city_id),
        )
        log.event(
            "DECISION",
            turn,
            f"{city.name} production options",
            ", ".join(f"{o.category}:{o.item_name}:{o.turns}t" for o in options[:20]),
        )

        priorities: list[tuple[str, str]] = []
        combat_count = sum(1 for u in units if is_combat_unit(u))
        if combat_count < max(2, len(cities) + 1) or (threat_pressure and combat_count < city_count + 3):
            priorities.extend([("UNIT", "UNIT_ARCHER"), ("UNIT", "UNIT_SLINGER"), ("UNIT", "UNIT_WARRIOR")])
        if trade_capacity > active_routes and trader_count < max(1, trade_capacity - active_routes):
            priorities.append(("UNIT", "UNIT_TRADER"))
        if scout_count < 1 and not (trade_capacity > active_routes and trader_count < max(1, trade_capacity - active_routes)):
            priorities.append(("UNIT", "UNIT_SCOUT"))
        if city_count < 4 and settler_count < 1 and city.population >= 2 and combat_count >= max(2, city_count):
            priorities.append(("UNIT", "UNIT_SETTLER"))
        if "MONUMENT" not in ",".join(city.buildings).upper() and city_count >= 2:
            priorities.append(("BUILDING", "BUILDING_MONUMENT"))
        if builder_count < max(1, city_count):
            priorities.append(("UNIT", "UNIT_BUILDER"))
        if city_count < 5 and settler_count < 2 and city.population >= 3 and combat_count >= city_count + 1:
            priorities.append(("UNIT", "UNIT_SETTLER"))
        if slinger_count < 1:
            priorities.append(("UNIT", "UNIT_SLINGER"))
        if "DISTRICT_CAMPUS" not in city.districts:
            priorities.append(("DISTRICT", "DISTRICT_CAMPUS"))
        priorities.extend(
            [
                ("BUILDING", "BUILDING_GRANARY"),
                ("UNIT", "UNIT_TRADER"),
                ("UNIT", "UNIT_BUILDER"),
                ("UNIT", "UNIT_SETTLER"),
                ("BUILDING", "BUILDING_LIBRARY"),
                ("UNIT", "UNIT_ARCHER"),
                ("UNIT", "UNIT_WARRIOR"),
                ("PROJECT", "PROJECT_CAMPUS_RESEARCH_GRANTS"),
            ]
        )
        choice = choose_available(options, priorities)
        if choice is None and options:
            non_repair = [o for o in options if not o.is_repair and o.category != "PROJECT"]
            choice = sorted(non_repair or options, key=lambda o: (o.turns <= 0, o.turns, o.cost))[0]
        if choice is None:
            log.event("DECISION", turn, f"No production choice available for {city.name}")
            continue

        target_x = target_y = None
        if choice.category == "DISTRICT":
            placements = await logged(
                log,
                turn,
                "MCP_QUERY",
                f"get_district_advisor {city.city_id} {choice.item_name}",
                lambda city=city, choice=choice: gs.get_district_advisor(city.city_id, choice.item_name),
            )
            if isinstance(placements, str) or not placements:
                log.event("DECISION", turn, f"district skipped for {city.name}: {placements}")
                fallback = choose_available(options, [("UNIT", "UNIT_BUILDER"), ("UNIT", "UNIT_SLINGER"), ("BUILDING", "BUILDING_GRANARY")])
                if fallback is None:
                    continue
                choice = fallback
            else:
                best = sorted(placements, key=lambda p: (-p.total_adjacency, p.x, p.y))[0]
                target_x, target_y = best.x, best.y
                log.event(
                    "DECISION",
                    turn,
                    f"district placement {choice.item_name} at {target_x},{target_y}",
                    best,
                )

        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"set_city_production {city.name} {choice.category}:{choice.item_name}",
            lambda city=city, choice=choice, target_x=target_x, target_y=target_y: gs.set_city_production(
                city.city_id, choice.category, choice.item_name, target_x, target_y
            ),
        )


async def handle_builders(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        tasks, builders = await logged(log, turn, "MCP_QUERY", "get_builder_tasks", gs.get_builder_tasks)
    except Exception:
        return
    if not builders:
        return
    try:
        threats = await gs.get_threat_scan()
    except Exception:
        threats = []
    builder_tiles = {(b.x, b.y) for b in builders}
    priority_rank = {"urgent": 0, "high": 1, "normal": 2}
    used_targets: set[tuple[int, int]] = set()
    for builder in builders:
        if builder.moves <= 0:
            continue
        if threats_within(threats, builder.x, builder.y, 6):
            log.event(
                "DECISION",
                turn,
                f"建造者 {builder.unit_id} 原地等待：3 格内有可见威胁，避免上一局建造者进入危险区。",
            )
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"skip threatened builder {builder.unit_id}",
                lambda builder=builder: gs.skip_unit(builder.unit_index),
            )
            continue
        candidates = [
            t
            for t in tasks
            if (t.x, t.y) not in used_targets
            and ((t.x, t.y) == (builder.x, builder.y) or (t.x, t.y) not in builder_tiles)
            and not threats_within(threats, t.x, t.y, 6)
            and (t.nearest_builder_id in {-1, builder.unit_id} or t.distance <= 3)
        ]
        if not candidates:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"skip idle builder {builder.unit_id}",
                lambda builder=builder: gs.skip_unit(builder.unit_index),
            )
            continue
        target = sorted(candidates, key=lambda t: (priority_rank.get(t.priority, 9), t.distance))[0]
        used_targets.add((target.x, target.y))
        try:
            area = await logged(
                log,
                turn,
                "MCP_QUERY",
                f"builder safety map around {target.x},{target.y}",
                lambda target=target: gs.get_map_area(target.x, target.y, 2),
            )
            if any(tile.units for tile in area):
                log.event(
                    "DECISION",
                    turn,
                    f"建造者 {builder.unit_id} 暂停前往 {target.x},{target.y}：目标附近地图显示敌方单位。",
                )
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"skip builder unsafe target {builder.unit_id}",
                    lambda builder=builder: gs.skip_unit(builder.unit_index),
                )
                continue
        except Exception:
            pass
        if builder.x == target.x and builder.y == target.y:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"builder improve {target.improvement} at {target.x},{target.y}",
                lambda builder=builder, target=target: gs.improve_tile(builder.unit_index, target.improvement),
            )
        else:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"builder move {builder.unit_id} to task {target.improvement}@{target.x},{target.y}",
                lambda builder=builder, target=target: gs.move_unit(builder.unit_index, target.x, target.y),
            )


async def handle_trade_routes(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        status = await logged(log, turn, "MCP_QUERY", "get_trade_routes", gs.get_trade_routes)
    except Exception:
        return
    if status.capacity > status.active_count and not any(not t.on_route for t in status.traders):
        try:
            ov = await gs.get_game_overview()
            cities, _ = await gs.get_cities()
        except Exception:
            cities = []
            ov = None
        if ov and cities:
            for city in sorted(cities, key=lambda c: (c.population, c.production), reverse=True):
                options = await logged(
                    log,
                    turn,
                    "MCP_QUERY",
                    f"trade-capacity production options {city.city_id}:{city.name}",
                    lambda city=city: gs.list_city_production(city.city_id),
                )
                trader = production_option(options, "UNIT", "UNIT_TRADER")
                if trader and 0 <= trader.gold_cost <= ov.gold:
                    result = await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"purchase trader in {city.name} because route capacity is idle",
                        lambda city=city: gs.purchase_item(city.city_id, "UNIT", "UNIT_TRADER", "YIELD_GOLD"),
                    )
                    if "STACKING_CONFLICT" in str(result):
                        log.event(
                            "DECISION",
                            turn,
                            f"trader purchase blocked in {city.name} by stacked unit; switching production to trader so route capacity is not ignored.",
                        )
                        await logged(
                            log,
                            turn,
                            "MCP_ACTION",
                            f"set_city_production {city.name} UNIT:UNIT_TRADER after blocked purchase",
                            lambda city=city: gs.set_city_production(city.city_id, "UNIT", "UNIT_TRADER"),
                        )
                    status = await logged(log, turn, "MCP_QUERY", "get_trade_routes after trader purchase", gs.get_trade_routes)
                    break
    for trader in status.traders:
        if trader.on_route or not trader.has_moves:
            continue
        try:
            threats = await gs.get_threat_scan()
        except Exception:
            threats = []
        nearby_barbs = [
            t
            for t in threats
            if getattr(t, "owner_id", None) == 63 and rough_distance(trader.x, trader.y, t.x, t.y) <= 6
        ]
        if nearby_barbs:
            log.event(
                "DECISION",
                turn,
                f"trader {trader.unit_id} stays home: barbarian threat within route origin radius; avoiding repeat trader loss.",
            )
            continue
        dests = await logged(
            log,
            turn,
            "MCP_QUERY",
            f"get_trade_destinations {trader.unit_id}",
            lambda trader=trader: gs.get_trade_destinations(trader.unit_id % 65536),
        )
        if not dests:
            continue
        cities, _ = await gs.get_cities()
        newest_city = sorted(cities, key=lambda c: (c.population, c.production, c.city_id))[0] if cities else None
        choice = sorted(
            dests,
            key=lambda d: (
                0 if newest_city and d.city_name == newest_city.name else 1,
                0 if d.is_domestic else 1,
                0 if d.has_quest else 1,
                -yield_score(d.dest_yields + " " + d.origin_yields),
            ),
        )[0]
        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"make_trade_route {trader.unit_id} to {choice.city_name}@{choice.x},{choice.y}",
            lambda trader=trader, choice=choice: gs.make_trade_route(trader.unit_id % 65536, choice.x, choice.y),
        )


def yield_score(text: str) -> int:
    nums = [int(n) for n in re.findall(r"-?\d+", text or "")]
    return sum(nums)


async def emergency_defense(gs: GameState, log: RunLog, turn: int, units: list[Any]) -> None:
    combat_count = sum(1 for u in units if is_combat_unit(u))
    if combat_count >= 2:
        return
    try:
        threats = await logged(log, turn, "MCP_QUERY", "get_threat_scan", gs.get_threat_scan)
    except Exception:
        threats = []
    if not threats:
        return
    try:
        ov = await gs.get_game_overview()
        cities, _ = await gs.get_cities()
    except Exception:
        return
    if ov.gold < 80 or not cities:
        return
    for city in cities:
        options = await logged(
            log,
            turn,
            "MCP_QUERY",
            f"emergency production options {city.city_id}:{city.name}",
            lambda city=city: gs.list_city_production(city.city_id),
        )
        for item in ["UNIT_ARCHER", "UNIT_SLINGER", "UNIT_WARRIOR"]:
            opt = production_option(options, "UNIT", item)
            if opt and 0 <= opt.gold_cost <= ov.gold:
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"emergency purchase {item} in {city.name}",
                    lambda city=city, item=item: gs.purchase_item(city.city_id, "UNIT", item, "YIELD_GOLD"),
                )
                return


async def handle_settlers_and_units(gs: GameState, log: RunLog, turn: int) -> list[Any]:
    units = await logged(log, turn, "MCP_QUERY", "get_units", gs.get_units)
    cities, _ = await gs.get_cities()
    try:
        threats = await gs.get_threat_scan()
    except Exception:
        threats = []
    for unit in list(units):
        if unit.moves_remaining <= 0:
            continue
        if unit.unit_type == "UNIT_SETTLER":
            nearby_threats = [
                t for t in threats if rough_distance(unit.x, unit.y, t.x, t.y) <= 3
            ]
            if cities and nearby_threats:
                nearest_city = sorted(
                    cities,
                    key=lambda c: rough_distance(unit.x, unit.y, c.x, c.y),
                )[0]
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"retreat settler {unit.unit_id} to {nearest_city.name} due nearby threat",
                    lambda unit=unit, nearest_city=nearest_city: gs.move_unit(
                        unit.unit_index, nearest_city.x, nearest_city.y
                    ),
                )
                continue
            if not cities:
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"found initial city with settler {unit.unit_id}",
                    lambda unit=unit: gs.found_city(unit.unit_index),
                )
                cities, _ = await gs.get_cities()
                continue
            advisor = await logged(
                log,
                turn,
                "MCP_QUERY",
                f"get_global_settle_scan for settler {unit.unit_id}",
                gs.get_global_settle_scan,
            )
            candidates = [c for c in advisor if c.loyalty_pressure >= -5]
            if not candidates:
                candidates = advisor
            if candidates:
                best = sorted(candidates, key=lambda c: (-c.score, -c.total_food - c.total_prod))[0]
                if unit.x == best.x and unit.y == best.y:
                    await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"found city at settle advisor site {best.x},{best.y}",
                        lambda unit=unit: gs.found_city(unit.unit_index),
                    )
                    cities, _ = await gs.get_cities()
                else:
                    await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"move settler {unit.unit_id} toward {best.x},{best.y}",
                        lambda unit=unit, best=best: gs.move_unit(unit.unit_index, best.x, best.y),
                    )
            else:
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"found fallback city with settler {unit.unit_id}",
                    lambda unit=unit: gs.found_city(unit.unit_index),
                )
        elif unit.unit_type == "UNIT_BUILDER":
            continue
        elif unit.unit_type == "UNIT_TRADER":
            continue
        elif unit.needs_promotion:
            continue
        else:
            if unit.unit_type == "UNIT_SCOUT":
                result = await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"automate exploration for {unit.name} {unit.unit_id}",
                    lambda unit=unit: gs.automate_explore(unit.unit_index),
                )
                if str(result).startswith("Error"):
                    await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"skip unit {unit.unit_id}",
                        lambda unit=unit: gs.skip_unit(unit.unit_index),
                    )
                continue
            if unit.targets:
                barb_target = next((t for t in unit.targets if "BARBARIAN" in t.upper()), None) or unit.targets[0]
                match = re.search(r"@(-?\d+),(-?\d+)", barb_target or "")
                hp_match = re.search(r"\((\d+)hp\)", barb_target or "", re.IGNORECASE)
                target_hp = int(hp_match.group(1)) if hp_match else 100
                should_attack = unit.health >= 65 or (target_hp <= 55 and unit.health >= 30)
                if barb_target and match and should_attack:
                    x, y = int(match.group(1)), int(match.group(2))
                    await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"attack barbarian with {unit.name} {unit.unit_id} -> {x},{y}",
                        lambda unit=unit, x=x, y=y: gs.attack_unit(unit.unit_index, x, y),
                    )
                else:
                    await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"alert unit near threat {unit.unit_id}",
                        lambda unit=unit: gs.alert_unit(unit.unit_index),
                    )
            elif unit.health < max(50, unit.max_health // 2):
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"heal damaged unit {unit.unit_id}",
                    lambda unit=unit: gs.heal_unit(unit.unit_index),
                )
            else:
                if unit.unit_type == "UNIT_SCOUT":
                    result = await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"automate exploration for {unit.name} {unit.unit_id}",
                        lambda unit=unit: gs.automate_explore(unit.unit_index),
                    )
                    if str(result).startswith("Error"):
                        await logged(
                            log,
                            turn,
                            "MCP_ACTION",
                            f"skip unit {unit.unit_id}",
                            lambda unit=unit: gs.skip_unit(unit.unit_index),
                        )
                elif is_combat_unit(unit):
                    await logged(
                        log,
                        turn,
                        "MCP_ACTION",
                        f"alert defensive unit {unit.name} {unit.unit_id}",
                        lambda unit=unit: gs.alert_unit(unit.unit_index),
                    )
    return await gs.get_units()


async def handle_settlers_and_units_guarded(gs: GameState, log: RunLog, turn: int) -> list[Any]:
    units = await logged(log, turn, "MCP_QUERY", "get_units", gs.get_units)
    cities, _ = await gs.get_cities()
    try:
        threats = await gs.get_threat_scan()
    except Exception:
        threats = []
    acted_units: set[int] = set()
    reserved_settle_sites: set[tuple[int, int]] = set()

    for settler in [u for u in units if u.unit_type == "UNIT_SETTLER" and u.moves_remaining > 0]:
        if not cities:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"found initial city with settler {settler.unit_id}",
                lambda settler=settler: gs.found_city(settler.unit_index),
            )
            acted_units.add(settler.unit_id)
            cities, _ = await gs.get_cities()
            continue

        nearby_escort_for_threat = any(
            is_combat_unit(u)
            and u.health >= 50
            and rough_distance(u.x, u.y, settler.x, settler.y) <= 2
            for u in units
        )
        if nearby_escort_for_threat and not serious_settler_threats(threats, settler.x, settler.y, 1, True):
            current_scan = await logged(
                log,
                turn,
                "MCP_QUERY",
                f"check current settle tile for settler {settler.unit_id}",
                gs.get_global_settle_scan,
            )
            current_site = next((c for c in current_scan if c.x == settler.x and c.y == settler.y), None)
            if current_site is not None:
                log.event(
                    "DECISION",
                    turn,
                    f"settler {settler.unit_id} is already on legal escorted city site {settler.x},{settler.y}; founding now avoids another retreat loop.",
                )
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"found escorted city at current tile {settler.x},{settler.y}",
                    lambda settler=settler: gs.found_city(settler.unit_index),
                )
                acted_units.add(settler.unit_id)
                cities, _ = await gs.get_cities()
                continue
        threat_radius = 2 if nearby_escort_for_threat else 4
        settler_threats = serious_settler_threats(threats, settler.x, settler.y, threat_radius, nearby_escort_for_threat)
        if settler_threats:
            safe_city = nearest_city(cities, settler.x, settler.y)
            log.event(
                "DECISION",
                turn,
                f"开拓者 {settler.unit_id} 附近有威胁，放弃推进并回撤，下一步等护卫到位后恢复扩张。",
            )
            if safe_city:
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"retreat settler {settler.unit_id} to {safe_city.name}",
                    lambda settler=settler, safe_city=safe_city: gs.move_unit(settler.unit_index, safe_city.x, safe_city.y),
                )
            else:
                await logged(log, turn, "MCP_ACTION", f"skip threatened settler {settler.unit_id}", lambda settler=settler: gs.skip_unit(settler.unit_index))
            acted_units.add(settler.unit_id)
            continue

        escort = sorted(
            [
                u
                for u in units
                if is_combat_unit(u)
                and u.health >= 50
                and u.unit_id not in acted_units
                and rough_distance(u.x, u.y, settler.x, settler.y) <= 2
            ],
            key=lambda u: (rough_distance(u.x, u.y, settler.x, settler.y), -u.health),
        )
        if not escort:
            rally = sorted(
                [
                    u
                    for u in units
                    if is_combat_unit(u)
                    and u.health >= 50
                    and u.moves_remaining > 0
                    and u.unit_id not in acted_units
                ],
                key=lambda u: rough_distance(u.x, u.y, settler.x, settler.y),
            )
            if rally:
                guard = rally[0]
                log.event(
                    "DECISION",
                    turn,
                    f"开拓者 {settler.unit_id} 不裸奔：护卫 {guard.unit_id} 先向开拓者靠近。",
                )
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"move escort {guard.unit_id} toward settler {settler.unit_id}",
                    lambda guard=guard, settler=settler: gs.move_unit(guard.unit_index, settler.x, settler.y),
                )
                acted_units.add(guard.unit_id)
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"skip settler {settler.unit_id} until escort arrives",
                lambda settler=settler: gs.skip_unit(settler.unit_index),
            )
            acted_units.add(settler.unit_id)
            continue

        advisor = await logged(
            log,
            turn,
            "MCP_QUERY",
            f"get_global_settle_scan for settler {settler.unit_id}",
            gs.get_global_settle_scan,
        )
        occupied_by_non_settler = {
            (u.x, u.y)
            for u in units
            if u.unit_type != "UNIT_SETTLER"
            and u.unit_id != settler.unit_id
            and (u.x, u.y) != (settler.x, settler.y)
        }
        candidates = [
            c
            for c in advisor
            if c.loyalty_pressure >= -5
            and c.total_food >= 24
            and c.total_prod >= 14
            and (c.x, c.y) not in reserved_settle_sites
            and (c.x, c.y) not in occupied_by_non_settler
            and not serious_settler_threats(threats, c.x, c.y, 2 if escort else 4, bool(escort))
        ] or [
            c
            for c in advisor
            if c.loyalty_pressure >= -5
            and (c.x, c.y) not in reserved_settle_sites
            and (c.x, c.y) not in occupied_by_non_settler
            and not serious_settler_threats(threats, c.x, c.y, 2 if escort else 4, bool(escort))
        ]
        if not candidates:
            log.event("DECISION", turn, f"开拓者 {settler.unit_id} 暂停：没有安全且有发展空间的可见城址。")
            await logged(log, turn, "MCP_ACTION", f"skip settler {settler.unit_id} no safe site", lambda settler=settler: gs.skip_unit(settler.unit_index))
            acted_units.add(settler.unit_id)
            continue

        best = sorted(
            candidates,
            key=lambda c: (
                0 if c.water_type in {"fresh", "coast"} else 1,
                -c.score,
                -(c.total_food + c.total_prod),
                -c.defense_score,
            ),
        )[0]
        reserved_settle_sites.add((best.x, best.y))
        log.event(
            "DECISION",
            turn,
            f"城址 {best.x},{best.y}: food={best.total_food}, prod={best.total_prod}, water={best.water_type}, defense={best.defense_score}; 选择理由是粮产安全综合最好。",
        )
        if settler.x == best.x and settler.y == best.y:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"found escorted city at {best.x},{best.y}",
                lambda settler=settler: gs.found_city(settler.unit_index),
            )
            acted_units.add(settler.unit_id)
            cities, _ = await gs.get_cities()
            continue

        guard = escort[0]
        if guard.moves_remaining > 0 and rough_distance(guard.x, guard.y, settler.x, settler.y) > 1:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"move escort {guard.unit_id} toward settler {settler.unit_id}",
                lambda guard=guard, settler=settler: gs.move_unit(guard.unit_index, settler.x, settler.y),
            )
            acted_units.add(guard.unit_id)
            units = await gs.get_units()
            settler = unit_by_id(units, settler.unit_id) or settler
            guard = unit_by_id(units, guard.unit_id) or guard
        if rough_distance(guard.x, guard.y, settler.x, settler.y) <= 3:
            await logged(
                log,
                turn,
                "MCP_ACTION",
                f"move escorted settler {settler.unit_id} toward {best.x},{best.y}",
                lambda settler=settler, best=best: gs.move_unit(settler.unit_index, best.x, best.y),
            )
            acted_units.add(settler.unit_id)
        else:
            log.event("DECISION", turn, f"开拓者 {settler.unit_id} 等待：护卫移动后仍离得太远。")
            await logged(log, turn, "MCP_ACTION", f"skip settler {settler.unit_id} after escort reposition", lambda settler=settler: gs.skip_unit(settler.unit_index))
            acted_units.add(settler.unit_id)

    units = await gs.get_units()

    for scout in [u for u in units if u.unit_type == "UNIT_SCOUT" and u.unit_id not in acted_units]:
        if scout.moves_remaining <= 0 or scout.needs_promotion:
            continue
        nearby_scout_threats = threats_within(threats, scout.x, scout.y, 2)
        if scout.health < 55 or nearby_scout_threats:
            safe_city = nearest_city(cities, scout.x, scout.y)
            log.event(
                "DECISION",
                turn,
                f"scout {scout.unit_id} pauses exploration: hp={scout.health}, nearby threats={len(nearby_scout_threats)}; preserving scout instead of repeating prior unit losses.",
            )
            if nearby_scout_threats and safe_city:
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"retreat scout {scout.unit_id} toward {safe_city.name}",
                    lambda scout=scout, safe_city=safe_city: gs.move_unit(scout.unit_index, safe_city.x, safe_city.y),
                )
            else:
                await logged(log, turn, "MCP_ACTION", f"heal scout {scout.unit_id}", lambda scout=scout: gs.heal_unit(scout.unit_index))
            acted_units.add(scout.unit_id)
            continue
        result = await logged(
            log,
            turn,
            "MCP_ACTION",
            f"automate exploration for scout {scout.unit_id}",
            lambda scout=scout: gs.automate_explore(scout.unit_index),
        )
        acted_units.add(scout.unit_id)
        if str(result).startswith("Error"):
            await logged(log, turn, "MCP_ACTION", f"skip scout {scout.unit_id}", lambda scout=scout: gs.skip_unit(scout.unit_index))

    for original in [u for u in await gs.get_units() if is_combat_unit(u)]:
        current_units = await gs.get_units()
        unit = unit_by_id(current_units, original.unit_id)
        if unit is None or unit.unit_id in acted_units or unit.moves_remaining <= 0 or unit.needs_promotion:
            continue
        if unit.health < max(45, unit.max_health // 2):
            await logged(log, turn, "MCP_ACTION", f"heal damaged combat unit {unit.unit_id}", lambda unit=unit: gs.heal_unit(unit.unit_index))
            acted_units.add(unit.unit_id)
            continue

        target_candidates = sorted(
            unit.targets,
            key=lambda t: (
                0 if any(k in (t or "").upper() for k in ("HORSE", "SPEARMAN", "WARRIOR", "SLINGER", "ARCHER")) else 1,
                target_hp(t),
            ),
        )
        chosen_target = None
        for candidate in target_candidates:
            xy = target_xy(candidate)
            if xy is None:
                continue
            dist = rough_distance(unit.x, unit.y, xy[0], xy[1])
            hp = target_hp(candidate)
            if unit.ranged_strength > 0 and dist <= 1 and hp > 35 and "BUILDER" not in candidate.upper():
                log.event(
                    "DECISION",
                    turn,
                    f"远程单位 {unit.unit_id} 不贴脸攻击 {candidate}，避免远程单位被当近战消耗。",
                )
            chosen_target = candidate
            break
        if unit.unit_id in acted_units:
            continue

        if chosen_target:
            xy = target_xy(chosen_target)
            if xy is None:
                continue
            fresh = await gs.get_units()
            fresh_unit = unit_by_id(fresh, unit.unit_id)
            if fresh_unit is None or not any(target_xy(t) == xy for t in fresh_unit.targets):
                log.event("DECISION", turn, f"攻击前刷新目标：{xy[0]},{xy[1]} 已不存在，跳过。")
                continue
            hp = target_hp(chosen_target)
            should_attack = fresh_unit.ranged_strength > 0 or fresh_unit.health >= 65 or (hp <= 55 and fresh_unit.health >= 35)
            if should_attack:
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"attack after refresh with {fresh_unit.name} {fresh_unit.unit_id} -> {xy[0]},{xy[1]}",
                    lambda fresh_unit=fresh_unit, xy=xy: gs.attack_unit(fresh_unit.unit_index, xy[0], xy[1]),
                )
                acted_units.add(unit.unit_id)
                await logged(log, turn, "MCP_QUERY", "refresh units after attack", gs.get_units)
            else:
                await logged(log, turn, "MCP_ACTION", f"fortify low-confidence attacker {fresh_unit.unit_id}", lambda fresh_unit=fresh_unit: gs.fortify_unit(fresh_unit.unit_index))
                acted_units.add(unit.unit_id)
            continue

        core_threats = [
            t
            for t in threats
            if getattr(t, "owner_id", None) == 63
            and cities
            and min(rough_distance(t.x, t.y, c.x, c.y) for c in cities) <= 4
        ]
        if core_threats:
            threat = sorted(
                core_threats,
                key=lambda t: (rough_distance(unit.x, unit.y, t.x, t.y), t.hp, t.combat_strength),
            )[0]
            dist_to_threat = rough_distance(unit.x, unit.y, threat.x, threat.y)
            if unit.ranged_strength > 0:
                log.event(
                    "DECISION",
                    turn,
                    f"ranged unit {unit.unit_id} sees core threat at {threat.x},{threat.y} but has no confirmed ranged target; holding instead of risking melee fallback.",
                )
                result = await logged(log, turn, "MCP_ACTION", f"alert ranged unit near core threat {unit.unit_id}", lambda unit=unit: gs.alert_unit(unit.unit_index))
                if str(result).startswith("Error"):
                    await logged(log, turn, "MCP_ACTION", f"fortify ranged unit near core threat {unit.unit_id}", lambda unit=unit: gs.fortify_unit(unit.unit_index))
                acted_units.add(unit.unit_id)
                continue
            if unit.health >= 65 and dist_to_threat <= 2:
                log.event(
                    "DECISION",
                    turn,
                    f"melee unit {unit.unit_id} intercepts core threat {threat.unit_type} at {threat.x},{threat.y}; this clears settler/trader blockage before expanding.",
                )
                await logged(
                    log,
                    turn,
                    "MCP_ACTION",
                    f"intercept core threat with {unit.name} {unit.unit_id} -> {threat.x},{threat.y}",
                    lambda unit=unit, threat=threat: gs.attack_unit(unit.unit_index, threat.x, threat.y),
                )
                acted_units.add(unit.unit_id)
                await logged(log, turn, "MCP_QUERY", "refresh units after core-threat intercept", gs.get_units)
                continue

        if turn <= 20:
            if cities and min(rough_distance(unit.x, unit.y, c.x, c.y) for c in cities) > 3:
                core = nearest_core_tile(cities, unit.x, unit.y)
                if core:
                    await logged(log, turn, "MCP_ACTION", f"move combat unit {unit.unit_id} back toward core defense", lambda unit=unit, core=core: gs.move_unit(unit.unit_index, core[0], core[1]))
                    acted_units.add(unit.unit_id)
                    continue
            log.event("DECISION", turn, f"军事单位 {unit.unit_id} 前 20 回合不自动探索，留在核心区守城/护送。")
            result = await logged(log, turn, "MCP_ACTION", f"fortify early defensive unit {unit.unit_id}", lambda unit=unit: gs.fortify_unit(unit.unit_index))
            if str(result).startswith("Error"):
                await logged(log, turn, "MCP_ACTION", f"skip early defensive unit {unit.unit_id}", lambda unit=unit: gs.skip_unit(unit.unit_index))
            acted_units.add(unit.unit_id)
        else:
            result = await logged(log, turn, "MCP_ACTION", f"alert defensive unit {unit.name} {unit.unit_id}", lambda unit=unit: gs.alert_unit(unit.unit_index))
            if str(result).startswith("Error"):
                await logged(log, turn, "MCP_ACTION", f"fortify defensive unit {unit.unit_id}", lambda unit=unit: gs.fortify_unit(unit.unit_index))
            acted_units.add(unit.unit_id)

    return await gs.get_units()


async def handle_city_attacks(gs: GameState, log: RunLog, turn: int) -> None:
    attacked: set[int] = set()
    while True:
        try:
            cities, _ = await gs.get_cities()
        except Exception:
            return
        city = next((c for c in cities if c.attack_targets and c.city_id not in attacked), None)
        if city is None:
            return
        target = city.attack_targets[0]
        match = re.search(r"(-?\d+),(-?\d+)", target)
        if not match:
            attacked.add(city.city_id)
            continue
        x, y = int(match.group(1)), int(match.group(2))
        fresh_cities, _ = await gs.get_cities()
        fresh_city = next((c for c in fresh_cities if c.city_id == city.city_id), city)
        if not any(re.search(fr"{x},{y}", t or "") for t in fresh_city.attack_targets):
            log.event("DECISION", turn, f"{city.name} 城防攻击前刷新后目标 {x},{y} 不存在，跳过。")
            attacked.add(city.city_id)
            continue
        await logged(
            log,
            turn,
            "MCP_ACTION",
            f"city_attack {city.name} -> {x},{y}",
            lambda city=city, x=x, y=y: gs.city_attack(city.city_id, x, y),
        )
        attacked.add(city.city_id)


async def end_current_turn(gs: GameState, log: RunLog, turn: int) -> str:
    await logged(log, turn, "MCP_ACTION", "dismiss_popup before end turn", gs.dismiss_popup)
    await logged(log, turn, "MCP_ACTION", "skip_remaining_units", gs.skip_remaining_units)
    log.event("MCP_ACTION", turn, "START end_turn")
    try:
        result = await asyncio.wait_for(gs.end_turn(), timeout=75)
    except asyncio.TimeoutError:
        result = "HANG: end_turn timeout after 75s; will re-check overview and continue if turn advanced"
        log.event("MCP_ACTION", turn, result)
        return result
    log.event("MCP_ACTION", turn, "OK end_turn", result)
    return result


async def record_checkpoint(gs: GameState, log: RunLog, turn: int) -> None:
    try:
        ov = await gs.get_game_overview()
        cities, _ = await gs.get_cities()
        units = await gs.get_units()
        trade = await gs.get_trade_routes()
        threats = await gs.get_threat_scan()
        governors = await gs.get_governors()
    except Exception as exc:  # noqa: BLE001
        log.event("CHECKPOINT", turn, f"10 回合复盘失败：{type(exc).__name__}: {exc}")
        return

    idle_routes = max(0, trade.capacity - trade.active_count)
    idle_settlers = [u for u in units if u.unit_type == "UNIT_SETTLER" and u.moves_remaining > 0]
    civilians_in_danger = [
        u for u in units if is_civilian(u) and threats_within(threats, u.x, u.y, 4)
    ]
    pingala = next((g for g in governors.appointed if g.governor_type == "GOVERNOR_THE_EDUCATOR"), None)
    science_core = max(cities, key=lambda c: c.science, default=None)
    pingala_ok = bool(
        pingala
        and pingala.assigned_city_id >= 0
        and (science_core is None or pingala.assigned_city_id == science_core.city_id)
    )
    if threats:
        risk = f"可见威胁 {len(threats)} 个，最近 {min(t.distance for t in threats)} 格"
    elif idle_routes:
        risk = f"商路容量闲置 {idle_routes}"
    elif idle_settlers:
        risk = f"开拓者待护送/落城 {len(idle_settlers)} 个"
    else:
        risk = "暂无立即战术风险，主要风险是扩张速度"
    if ov.num_cities < 3 and turn <= 30:
        next_goal = "T30 前完成第三城，并准备第四城护送路线"
    elif ov.num_cities < 5:
        next_goal = "继续护送开拓者到安全粮产点，补到 4-5 城"
    elif idle_routes:
        next_goal = "立刻开商路支援新城"
    else:
        next_goal = "补学院/粮仓/工人，把城市转为科研与产能"
    log.event(
        "CHECKPOINT",
        turn,
        "10 回合复盘："
        f"城市 {ov.num_cities} 座，总人口 {ov.total_population}；"
        f"闲置商路 {idle_routes}；"
        f"闲置开拓者 {len(idle_settlers)}；"
        f"危险区平民 {len(civilians_in_danger)}；"
        f"未处理蛮族/敌方威胁 {len(threats)}；"
        f"平伽拉科研核心状态 {'是' if pingala_ok else '否/未就位'}；"
        f"最大风险：{risk}；"
        f"下一阶段目标：{next_goal}。",
    )


async def _wait_for_loaded_overview(log: RunLog, label: str, timeout: int = 45) -> bool:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        conn = GameConnection()
        try:
            await conn.connect()
            gs = GameState(conn)
            ov = await gs.get_game_overview()
            log.event("MCP_QUERY", ov.turn, f"{label}: verified loaded overview", ov)
            await conn.disconnect()
            return True
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            try:
                await conn.disconnect()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(2)
    log.event("MCP_QUERY", None, f"{label}: overview not ready", last_error)
    return False


async def _click_continue_if_present(log: RunLog, timeout: int = 35) -> None:
    clicked = await asyncio.to_thread(
        lambda: game_launcher._click_text("CONTINUE", timeout=timeout, exact=False, post_delay=1)
    )
    if not clicked:
        log.event("MCP_ACTION", None, "CONTINUE not found by OCR; using positional click fallback")
        await asyncio.to_thread(game_launcher._click_continue_positional)
    await asyncio.sleep(5)


async def _click_load_from_visible_menu(log: RunLog, save_name: str, timeout: int = 5) -> bool:
    clicked_save = await asyncio.to_thread(
        lambda: game_launcher._click_text(save_name, timeout=timeout, exact=False, post_delay=0.5)
    )
    if not clicked_save:
        return False

    def click_bottom_load() -> str:
        win = game_launcher._find_game_window()
        if not win:
            return "NO_WINDOW"
        game_launcher._bring_to_front()
        time.sleep(0.2)
        # Chinese load menu: blue load button near the bottom center-left.
        x = win.x + int(win.w * 0.405)
        y = win.y + int(win.h * 0.965)
        game_launcher._click(x, y)
        return f"CLICKED|{x},{y}"

    result = await asyncio.to_thread(click_bottom_load)
    log.event("MCP_ACTION", None, f"load-menu fallback selected save {save_name}", result)
    return result != "NO_WINDOW"


async def load_requested_save(log: RunLog, save_name: str) -> None:
    log.event("MCP_ACTION", None, f"START load save {save_name}")
    used_visible_menu = await _click_load_from_visible_menu(log, save_name, timeout=5)
    if not used_visible_menu:
        try:
            conn = GameConnection()
            await conn.connect()
        except Exception:
            log.event("MCP_ACTION", None, "game not reachable; launching Civ VI before save load")
            await game_launcher.launch_game()
            await asyncio.sleep(12)
            conn = GameConnection()
            await conn.connect()
        try:
            result = await load_game_save(conn, save_name)
            log.event("MCP_ACTION", None, f"OK load save {save_name}", result)
        finally:
            await conn.disconnect()

    await asyncio.sleep(18)
    await _click_continue_if_present(log, timeout=45)
    if await _wait_for_loaded_overview(log, "after load request", timeout=30):
        return

    if not used_visible_menu and await _click_load_from_visible_menu(log, save_name, timeout=8):
        await asyncio.sleep(18)
        await _click_continue_if_present(log, timeout=45)
        if await _wait_for_loaded_overview(log, "after visible load fallback", timeout=30):
            return
    raise RuntimeError(f"Could not verify loaded save: {save_name}")


async def play_chunk(max_advances: int, new_run: bool = False, save_name: str | None = None) -> int:
    log = RunLog(new_run=new_run)
    if save_name:
        await load_requested_save(log, save_name)
    conn = GameConnection()
    await conn.connect()
    gs = GameState(conn)
    advances = 0
    checkpointed_turns: set[int] = set()
    try:
        start = await logged(log, None, "MCP_QUERY", "get_game_overview initial", gs.get_game_overview)
        log.event(
            "STATUS",
            start.turn,
            f"start chunk: era={start.era_name}, score={start.score}, cities={start.num_cities}, units={start.num_units}",
        )
        if is_medieval(start.era_name):
            final_name = f"{FINAL_SAVE_PREFIX}_T{start.turn:03d}_{datetime.now().strftime('%Y%m%d_%H%M')}"
            await logged(log, start.turn, "MCP_ACTION", f"save_game {final_name}", lambda: save_game(conn, final_name))
            log.mark_done(start)
            print(f"DONE|turn={start.turn}|era={start.era_name}|log={log.path}")
            return advances
        await capture_screen(log, start.turn, "chunk_start")

        while advances < max_advances:
            ov = await logged(log, None, "MCP_QUERY", "get_game_overview", gs.get_game_overview)
            if is_medieval(ov.era_name):
                log.mark_done(ov)
                await capture_screen(log, ov.turn, "medieval_reached")
                final_name = f"{FINAL_SAVE_PREFIX}_T{ov.turn:03d}_{datetime.now().strftime('%Y%m%d_%H%M')}"
                await logged(log, ov.turn, "MCP_ACTION", f"save_game {final_name}", lambda: save_game(conn, final_name))
                print(f"DONE|turn={ov.turn}|era={ov.era_name}|log={log.path}")
                return advances
            log.turn_header(ov.turn)
            log.event(
                "STATUS",
                ov.turn,
                f"overview: era={ov.era_name}, score={ov.score}, cities={ov.num_cities}, pop={ov.total_population}, gold={ov.gold}({ov.gold_per_turn:+}/t), science={ov.science_yield}, culture={ov.culture_yield}",
            )

            await handle_diplomacy(gs, log, ov.turn)
            await ensure_research(gs, log, ov.turn)
            units = await logged(log, ov.turn, "MCP_QUERY", "get_units before upgrades", gs.get_units)
            units = await handle_unit_upgrades(gs, log, ov.turn, units)
            units = await handle_settlers_and_units_guarded(gs, log, ov.turn)
            await emergency_defense(gs, log, ov.turn, units)
            await set_city_outputs(gs, log, ov.turn, units)
            units = await gs.get_units()
            await handle_promotions(gs, log, ov.turn, units)
            await handle_builders(gs, log, ov.turn)
            await handle_trade_routes(gs, log, ov.turn)
            await handle_city_attacks(gs, log, ov.turn)
            await choose_policies(gs, log, ov.turn)
            await choose_pantheon(gs, log, ov.turn)
            if is_classical_or_later(ov.era_name) or ov.current_civic in {"政治哲学", "Political Philosophy"}:
                await choose_government(gs, log, ov.turn)
            await choose_dedication(gs, log, ov.turn)
            await handle_governors(gs, log, ov.turn)
            await handle_envoys(gs, log, ov.turn)
            if ov.turn % 10 == 0 and ov.turn not in checkpointed_turns:
                await record_checkpoint(gs, log, ov.turn)
                checkpointed_turns.add(ov.turn)

            result = await end_current_turn(gs, log, ov.turn)
            post_turn = ov.turn
            try:
                post_ov = await gs.get_game_overview()
                post_turn = post_ov.turn
            except Exception:
                post_ov = None
            if post_turn > ov.turn:
                advances += post_turn - ov.turn
            else:
                log.event("STATUS", ov.turn, "end_turn did not advance; continuing same turn after resolving blockers")
            if "HANG:" in result and post_turn > ov.turn:
                log.event("STATUS", post_turn, "end_turn timed out in client, but game advanced; continuing")
            elif "HANG:" in result or "GAME OVER" in result.upper():
                log.event("STOP", ov.turn, "end_turn returned terminal or hang condition", result)
                print(f"STOP|turn={ov.turn}|reason=end_turn|log={log.path}")
                return advances
            if advances == 1 or advances % 5 == 0:
                post = post_ov or await gs.get_game_overview()
                await capture_screen(log, post.turn, f"after_{advances}_advances")
            time.sleep(0.5)

        ov = await gs.get_game_overview()
        print(f"CHUNK|turn={ov.turn}|era={ov.era_name}|advances={advances}|log={log.path}")
        return advances
    finally:
        await conn.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-advances", type=int, default=5)
    parser.add_argument("--new-run", action="store_true")
    parser.add_argument("--load-save", default=None)
    args = parser.parse_args()
    try:
        asyncio.run(play_chunk(args.max_advances, args.new_run, args.load_save))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR|{type(exc).__name__}|{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

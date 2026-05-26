"""Codex HL Observation observation-only runner for the real ``test 1`` save.

The goal of this script is evidence capture, not strategy improvement.  It
plays only a short validation run by default, records every high-level tool call
and low-level FireTuner Lua exchange, writes per-turn state snapshots, indexes
save files, and produces a human-readable HTML acceptance report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_SRC = PLUGIN_ROOT / "src"
ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from codex_hl.evidence.store import (  # noqa: E402
    EpisodeReader,
    EpisodeStore,
    EpisodeStoreError,
    has_episode_db,
    logical_path_for,
    reader_for_path,
    rebuild_episode_db,
)
from codex_hl.strategy.registry import write_active_asset_snapshot  # noqa: E402
from civ6_connector import game_launcher  # noqa: E402
from civ6_connector.connection import GameConnection  # noqa: E402
from civ6_connector.game_lifecycle import load_game_save, save_game  # noqa: E402
from civ6_connector.game_state import GameState  # noqa: E402


WORKFLOW_LABEL = "Observation Only"
SAVE_DIR = Path(game_launcher.SINGLE_SAVE_DIR)
DEFAULT_SAVE_NAME = "test 1"
MIN_SHORT_RUN_TURNS = 3
MAX_SHORT_RUN_TURNS = 10
T20_EXPLORATION_TURNS = 20
T50_OBSERVATION_TURNS = 50
FIRETUNER_CONNECT_TIMEOUT_SECONDS = 420
FIRETUNER_LOAD_TIMEOUT_SECONDS = 420
BASELINE_STRATEGY_PROFILE = "baseline_static"
EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE = "explore_scout_first"
SCIENCE_CULTURE_T50_STRATEGY_PROFILE = "science_culture_t50"
GOLDEN_AGE_PUSH_STRATEGY_PROFILE = "golden_age_push"
STRATEGY_PROFILES = {
    BASELINE_STRATEGY_PROFILE,
    EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE,
    SCIENCE_CULTURE_T50_STRATEGY_PROFILE,
    GOLDEN_AGE_PUSH_STRATEGY_PROFILE,
}
ACCEPTED_HUMAN_REPORT_EPISODE = "observation_test1_short_20260512_130155"
HUMAN_REPORT_CONTRACT_PATH = (
    PLUGIN_ROOT / "fixtures" / "observation_report_contract" / "contract.json"
)
CANDIDATE_RUNTIME_KIND = "strategy_candidate_playbook"

DEFAULT_HUMAN_REPORT_CONTRACT = {
    "reference_episode": ACCEPTED_HUMAN_REPORT_EPISODE,
    "required_fragments": [
        '<html lang="zh-CN">',
        "Codex HL Observation 人类验收报告",
        "验收结论",
        "我实际观测到的局面变化",
        "起点 T",
        "终点 T",
        "回合叙事",
        "重点：决策流程",
        "当时看到的问题：",
        "候选动作：",
        "我选择了：",
        "为什么这样选：",
        "为什么没选其他动作：",
        "执行后结果：",
        "对 review 的意义：",
        "证据边界和你需要判断的点",
        "存档和决策关联",
        "缺口清单",
        "面向 Agent 的报告",
        "agent_report.md",
        "agent_audit_report.html",
        "先读这份报告的顺序",
        "快速定位",
        "关键数字变化",
        "证据线索",
        "快速接手",
        "完整审计",
    ],
    "required_css_fragments": [
        ".summary",
        ".read-path",
        ".report-nav",
        ".verdict",
        ".tile",
        ".metric-grid",
        ".metric-chip",
        ".turn-timeline",
        ".turn-card",
        ".turn-flow",
        ".decision-card",
        ".decision-header",
        ".decision-grid",
        ".review-note",
        ".evidence",
        ".two-col",
        ".agent-links",
    ],
    "forbidden_fragments": ["<details", "<pre", "{&quot;turn&quot;"],
}


def observation_mode(turns: int) -> str:
    if turns == T20_EXPLORATION_TURNS:
        return "t20_exploration"
    if turns == T50_OBSERVATION_TURNS:
        return "t50_observation"
    if MIN_SHORT_RUN_TURNS <= turns <= MAX_SHORT_RUN_TURNS:
        return "short_validation"
    return "unsupported"


def observation_mode_zh(turns: int) -> str:
    mode = observation_mode(turns)
    if mode == "t50_observation":
        return "T50 完整观测"
    if mode == "t20_exploration":
        return "T20 策略探索"
    return "短跑验收"


def observation_episode_prefix(turns: int) -> str:
    mode = observation_mode(turns)
    if mode == "t50_observation":
        return "observation_test1_t50"
    if mode == "t20_exploration":
        return "observation_test1_t20"
    return "observation_test1_short"


def observation_stop_boundary(turns: int) -> str:
    mode = observation_mode(turns)
    if mode == "t50_observation":
        return "Stop after the 50-turn T50 observation. Do not continue to T51+ or Review without explicit user approval."
    if mode == "t20_exploration":
        return "Stop after the 20-turn T20 exploration. Treat results as local candidate evidence, not a long-horizon strategy proof."
    return "Stop after the 3-10 turn short-run. Do not continue to T50 until human acceptance."


def valid_observation_turns(turns: int) -> bool:
    return observation_mode(turns) != "unsupported"

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
]

SCIENCE_CULTURE_T50_TECH_PRIORITY = [
    "TECH_POTTERY",
    "TECH_WRITING",
    "TECH_ARCHERY",
    "TECH_ANIMAL_HUSBANDRY",
    "TECH_HORSEBACK_RIDING",
    "TECH_MINING",
    "TECH_BRONZE_WORKING",
    "TECH_THE_WHEEL",
    "TECH_CURRENCY",
    "TECH_IRON_WORKING",
]

GOLDEN_AGE_PUSH_TECH_PRIORITY = [
    "TECH_ANIMAL_HUSBANDRY",
    "TECH_ARCHERY",
    "TECH_HORSEBACK_RIDING",
    "TECH_ASTROLOGY",
    "TECH_MINING",
    "TECH_BRONZE_WORKING",
    "TECH_POTTERY",
    "TECH_WRITING",
    "TECH_THE_WHEEL",
    "TECH_CURRENCY",
    "TECH_IRON_WORKING",
]

CIVIC_PRIORITY = [
    "CIVIC_CODE_OF_LAWS",
    "CIVIC_FOREIGN_TRADE",
    "CIVIC_CRAFTSMANSHIP",
    "CIVIC_EARLY_EMPIRE",
    "CIVIC_STATE_WORKFORCE",
    "CIVIC_POLITICAL_PHILOSOPHY",
]

GOLDEN_AGE_PUSH_CIVIC_PRIORITY = [
    "CIVIC_CODE_OF_LAWS",
    "CIVIC_FOREIGN_TRADE",
    "CIVIC_CRAFTSMANSHIP",
    "CIVIC_MYSTICISM",
    "CIVIC_EARLY_EMPIRE",
    "CIVIC_STATE_WORKFORCE",
    "CIVIC_POLITICAL_PHILOSOPHY",
    "CIVIC_THEOLOGY",
]

PRODUCTION_PRIORITY = [
    "UNIT_SETTLER",
    "UNIT_BUILDER",
    "UNIT_TRADER",
    "BUILDING_MONUMENT",
    "BUILDING_GRANARY",
    "BUILDING_WATER_MILL",
    "DISTRICT_CAMPUS",
    "UNIT_SCOUT",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
]

EXPLORE_SCOUT_FIRST_PRODUCTION_PRIORITY = [
    "UNIT_SCOUT",
    "UNIT_SETTLER",
    "BUILDING_MONUMENT",
    "UNIT_TRADER",
    "UNIT_BUILDER",
    "DISTRICT_CAMPUS",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "BUILDING_GRANARY",
    "BUILDING_WATER_MILL",
]
EXPLORE_SCOUT_FIRST_SCOUT_CAP = 2
EXPLORE_SCOUT_FIRST_BUILDER_CAP_AFTER_THREE_CITIES = 2
EXPLORE_SCOUT_FIRST_MIN_COMBAT_AFTER_THREE_CITIES = 3
EXPLORE_SCOUT_FIRST_TARGET_T50_CITIES = 4
EXPLORE_SCOUT_FIRST_POST_THREE_CITY_PRIORITY = [
    "UNIT_BUILDER",
    "BUILDING_MONUMENT",
    "UNIT_TRADER",
    "DISTRICT_CAMPUS",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "BUILDING_GRANARY",
    "BUILDING_WATER_MILL",
    "UNIT_SETTLER",
    "UNIT_SCOUT",
]
EXPLORE_SCOUT_FIRST_POST_THREE_CITY_DEFENSE_PRIORITY = [
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "BUILDING_MONUMENT",
    "UNIT_BUILDER",
    "UNIT_TRADER",
    "DISTRICT_CAMPUS",
    "BUILDING_GRANARY",
    "BUILDING_WATER_MILL",
    "UNIT_SETTLER",
    "UNIT_SCOUT",
]
EXPLORE_SCOUT_FIRST_POST_THREE_CITY_EXPANSION_PRIORITY = [
    "UNIT_SETTLER",
    "BUILDING_MONUMENT",
    "UNIT_BUILDER",
    "UNIT_TRADER",
    "DISTRICT_CAMPUS",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "BUILDING_GRANARY",
    "BUILDING_WATER_MILL",
    "UNIT_SCOUT",
]
SCIENCE_CULTURE_T50_YIELD_TARGET = 10.0
SCIENCE_CULTURE_T50_TARGET_CITIES = 4
SCIENCE_CULTURE_T50_RANGED_CLEARING_CAP = 4
SCIENCE_CULTURE_T50_MIN_COMBAT_AFTER_TWO_CITIES = 2
SCIENCE_CULTURE_T50_MIN_COMBAT_AFTER_THREE_CITIES = 3
SCIENCE_CULTURE_T50_DEFENSE_PRIORITY = [
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_HORSEMAN",
    "UNIT_WARRIOR",
    "BUILDING_MONUMENT",
    "DISTRICT_CAMPUS",
    "UNIT_BUILDER",
    "UNIT_TRADER",
    "UNIT_SETTLER",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
    "UNIT_SCOUT",
]
SCIENCE_CULTURE_T50_EARLY_EXPANSION_PRIORITY = [
    "UNIT_SETTLER",
    "UNIT_SLINGER",
    "BUILDING_MONUMENT",
    "UNIT_BUILDER",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_ARCHER",
    "UNIT_HORSEMAN",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
    "UNIT_WARRIOR",
    "UNIT_SCOUT",
]
SCIENCE_CULTURE_T50_LOW_YIELD_PRIORITY = [
    "BUILDING_MONUMENT",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_BUILDER",
    "BUILDING_WATER_MILL",
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_HORSEMAN",
    "UNIT_SETTLER",
    "BUILDING_GRANARY",
    "UNIT_WARRIOR",
    "UNIT_SCOUT",
]
GOLDEN_AGE_PUSH_PRODUCTION_PRIORITY = [
    "PROJECT_HOLY_SITE_PRAYERS",
    "UNIT_HORSEMAN",
    "UNIT_ARCHER",
    "DISTRICT_HOLY_SITE",
    "BUILDING_SHRINE",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "UNIT_SCOUT",
    "UNIT_SETTLER",
    "UNIT_BUILDER",
    "BUILDING_MONUMENT",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_SCOUTING_PRIORITY = [
    "UNIT_SCOUT",
    "UNIT_SETTLER",
    "BUILDING_MONUMENT",
    "UNIT_BUILDER",
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_WARRIOR",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_HORSEMAN",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_EXPANSION_PRIORITY = [
    "UNIT_SETTLER",
    "PROJECT_HOLY_SITE_PRAYERS",
    "DISTRICT_HOLY_SITE",
    "BUILDING_SHRINE",
    "UNIT_SCOUT",
    "BUILDING_MONUMENT",
    "UNIT_BUILDER",
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_WARRIOR",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_HORSEMAN",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_DEVELOPMENT_PRIORITY = [
    "PROJECT_HOLY_SITE_PRAYERS",
    "DISTRICT_HOLY_SITE",
    "BUILDING_SHRINE",
    "UNIT_BUILDER",
    "BUILDING_MONUMENT",
    "UNIT_SETTLER",
    "UNIT_SCOUT",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_WARRIOR",
    "UNIT_HORSEMAN",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_STRATEGIC_RESOURCE_PRIORITY = [
    "UNIT_HORSEMAN",
    "UNIT_BUILDER",
    "UNIT_ARCHER",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "PROJECT_HOLY_SITE_PRAYERS",
    "DISTRICT_HOLY_SITE",
    "BUILDING_SHRINE",
    "UNIT_SETTLER",
    "UNIT_SCOUT",
    "BUILDING_MONUMENT",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_BUILDER_PURCHASE_RESERVE_PRIORITY = [
    "UNIT_ARCHER",
    "UNIT_SLINGER",
    "BUILDING_MONUMENT",
    "PROJECT_HOLY_SITE_PRAYERS",
    "DISTRICT_HOLY_SITE",
    "BUILDING_SHRINE",
    "UNIT_SETTLER",
    "UNIT_WARRIOR",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_HORSEMAN",
    "UNIT_SCOUT",
    "UNIT_BUILDER",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_DEFENSE_PRIORITY = [
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_WARRIOR",
    "PROJECT_HOLY_SITE_PRAYERS",
    "DISTRICT_HOLY_SITE",
    "BUILDING_SHRINE",
    "UNIT_SCOUT",
    "BUILDING_MONUMENT",
    "UNIT_SETTLER",
    "UNIT_BUILDER",
    "DISTRICT_CAMPUS",
    "UNIT_TRADER",
    "UNIT_HORSEMAN",
    "BUILDING_WATER_MILL",
    "BUILDING_GRANARY",
]
GOLDEN_AGE_PUSH_ANCIENT_SCOUT_CAP = 2
GOLDEN_AGE_PUSH_ANCIENT_SCOUT_REPLACEMENT_LATEST_TURN = 18
GOLDEN_AGE_PUSH_ANCIENT_STRATEGIC_RESOURCE_START_TURN = 12
GOLDEN_AGE_PUSH_ANCIENT_TARGET_CITIES = 3
GOLDEN_AGE_PUSH_ANCIENT_MIN_COMBAT_UNITS = 2
GOLDEN_AGE_PUSH_ANCIENT_RANGED_CAP = 3
GOLDEN_AGE_PUSH_EARLY_MILITARY_BUY_PRIORITY = {"UNIT_HORSEMAN", "UNIT_ARCHER"}
GOLDEN_AGE_PUSH_ACTIVE_PRODUCTION_OVERRIDE_ITEMS = {"UNIT_HORSEMAN"}
GOLDEN_AGE_PUSH_MILITARY_PURCHASE_PRIORITY = [
    "UNIT_HORSEMAN",
    "UNIT_ARCHER",
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "UNIT_SCOUT",
]
GOLDEN_AGE_PUSH_MILITARY_UPGRADE_SOURCE_PRIORITY = [
    "UNIT_SLINGER",
    "UNIT_WARRIOR",
    "UNIT_SCOUT",
    "UNIT_ARCHER",
    "UNIT_HORSEMAN",
]
GOLDEN_AGE_PUSH_MILITARY_UPGRADE_TARGET_PRIORITY = [
    "UNIT_HORSEMAN",
    "UNIT_ARCHER",
    "UNIT_SWORDSMAN",
    "UNIT_SKIRMISHER",
    "UNIT_CROSSBOWMAN",
    "UNIT_COURSER",
]
GOLDEN_AGE_PUSH_BUILDER_PURCHASE_PRIORITY = ["UNIT_BUILDER"]
GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY = ["HORSES", "IRON"]
GOLDEN_AGE_PUSH_MIN_GOLD_TO_SPEND = 120
GOLDEN_AGE_PUSH_ANCIENT_MIN_GOLD_TO_SPEND = 65
GOLDEN_AGE_PUSH_RESOURCE_TRADE_RESERVE = {"HORSES": 20, "IRON": 10}
GOLDEN_AGE_PUSH_RESOURCE_TRADE_MIN_SURPLUS = 5
GOLDEN_AGE_PUSH_WAR_START_TURN = 30
GOLDEN_AGE_PUSH_WAR_MIN_COMBAT_UNITS = 3
GOLDEN_AGE_PUSH_MAP_TARGET_SCAN_RADIUS = 12
GOLDEN_AGE_PUSH_BLOCKED_MAP_TARGET_COOLDOWN_TURNS = 6
GOLDEN_AGE_PUSH_URGENT_SETTLER_MOVE_TURN = 24
GOLDEN_AGE_PUSH_SETTLER_ADJACENT_BARBARIAN_DISTANCE = 1
GOLDEN_AGE_PUSH_STRATEGIC_SETTLE_RADIUS = 3
GOLDEN_AGE_PUSH_PANTHEON_PRIORITY = [
    "BELIEF_DIVINE_SPARK",
    "BELIEF_RELIGIOUS_SETTLEMENTS",
    "BELIEF_GOD_OF_THE_FORGE",
]
GOLDEN_AGE_PUSH_FOLLOWER_BELIEF = "BELIEF_CHORAL_MUSIC"
GOLDEN_AGE_PUSH_FOUNDER_BELIEF_PRIORITY = [
    "BELIEF_STEWARDSHIP",
    "BELIEF_TITHE",
    "BELIEF_CHURCH_PROPERTY",
    "BELIEF_WORLD_CHURCH",
]
GOLDEN_AGE_PUSH_RELIGION_PRIORITY = [
    "RELIGION_CONFUCIANISM",
    "RELIGION_TAOISM",
    "RELIGION_BUDDHISM",
    "RELIGION_HINDUISM",
    "RELIGION_ISLAM",
    "RELIGION_CATHOLICISM",
]
BARBARIAN_CLEARING_UNIT_TYPES = {
    "UNIT_WARRIOR",
    "UNIT_SLINGER",
    "UNIT_ARCHER",
    "UNIT_HORSEMAN",
}
HORSEMAN_PRESSURE_START_TURN = 30
SETTLER_MAX_UNESCORTED_DISTANCE_WITH_BARBARIANS = 6


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def candidate_text_blob(candidate: dict[str, Any]) -> str:
    source_failure = candidate.get("source_failure") or {}
    proposed_change = candidate.get("proposed_change") or {}
    target_asset = candidate.get("target_asset") or {}
    parts = [
        candidate.get("candidate_id"),
        candidate.get("status"),
        source_failure.get("title") if isinstance(source_failure, dict) else "",
        source_failure.get("failure_type") if isinstance(source_failure, dict) else "",
        source_failure.get("capability_category") if isinstance(source_failure, dict) else "",
        proposed_change.get("content_appendix") if isinstance(proposed_change, dict) else "",
        proposed_change.get("rationale") if isinstance(proposed_change, dict) else "",
        target_asset.get("asset_id") if isinstance(target_asset, dict) else "",
        target_asset.get("asset_type") if isinstance(target_asset, dict) else "",
    ]
    return "\n".join(str(part or "") for part in parts)


def candidate_runtime_effects(candidate: dict[str, Any]) -> list[str]:
    text = candidate_text_blob(candidate).lower()
    effects: list[str] = []
    if any(term in text for term in ["scout", "侦察", "explor"]):
        effects.append("scouting_pressure")
    if any(term in text for term in ["settler", "city", "城市", "扩张", "落第三城"]):
        effects.append("expansion_pressure")
    if any(term in text for term in ["defense", "escort", "防守", "驻军", "维持城市"]):
        effects.append("defense_before_extra_expansion")
    if any(term in text for term in ["river", "fresh water", "沿河", "淡水"]):
        effects.append("river_settlement")
    if any(term in text for term in ["barbarian", "barb", "蛮族", "清理蛮"]):
        effects.append("barbarian_clearance")
    if any(term in text for term in ["writing", "campus", "学院", "science", "科学", "culture", "文化"]):
        effects.append("science_culture_push")
    if any(term in text for term in ["horseman", "horsemen", "骑手", "邻国", "neighbor"]):
        effects.append("horseman_pressure")
    if any(term in text for term in ["era score", "golden age", "时代得分", "黄金时代"]):
        effects.append("era_score_push")
    if any(term in text for term in ["golden_age_push", "golden age push"]):
        effects.append("golden_age_push")
    if any(
        term in text
        for term in ["resource trade", "strategic resource", "horses", "iron", "sell resource"]
    ):
        effects.append("strategic_resource_trading")
    if any(term in text for term in ["opportunistic war", "declare war", "neighbor war", "war opportunity"]):
        effects.append("opportunistic_war")
    if any(term in text for term in ["gold spender", "military purchase", "buy unit", "purchase unit"]):
        effects.append("military_gold_spending")
    if not effects and "playbook" in text:
        effects.append("playbook_loaded")
    return effects


def load_candidate_runtime(candidate_package: Path | None) -> dict[str, Any]:
    if candidate_package is None:
        return {"status": "not_supplied", "runtime_effects": []}
    path = candidate_package.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Candidate package not found: {path}")
    candidate = read_json_object(path)
    source_failure_ids = candidate.get("source_failure_ids") or []
    if not source_failure_ids:
        raise ValueError(f"Candidate package has no source_failure_ids: {path}")
    target_asset = candidate.get("target_asset") or {}
    if not isinstance(target_asset, dict) or target_asset.get("asset_type") != "playbook":
        raise ValueError(f"Candidate package does not target a playbook asset: {path}")
    effects = candidate_runtime_effects(candidate)
    return {
        "status": "applied" if effects else "loaded_without_effects",
        "kind": CANDIDATE_RUNTIME_KIND,
        "package_path": str(path),
        "package_sha256": sha256_file(path),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_status": candidate.get("status"),
        "source_episode_ids": candidate.get("source_episode_ids") or [],
        "source_failure_ids": source_failure_ids,
        "target_asset": {
            "asset_id": target_asset.get("asset_id"),
            "asset_type": target_asset.get("asset_type"),
            "current_version": target_asset.get("current_version"),
            "proposed_version": target_asset.get("proposed_version"),
            "content_path": target_asset.get("content_path"),
            "current_sha256": target_asset.get("current_sha256"),
            "proposed_sha256": target_asset.get("proposed_sha256"),
        },
        "runtime_effects": effects,
        "runtime_note": (
            "Candidate package is read-only input for this episode. It may alter "
            "runtime priorities, but it does not mutate strategy assets or mark the "
            "candidate accepted."
        ),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_snapshot_manifest(active_assets_path: Path) -> dict[str, Any]:
    rel_path = active_assets_path.as_posix()
    if active_assets_path.exists():
        try:
            snapshot = json.loads(active_assets_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "status": "invalid",
                "path": rel_path,
                "gap": f"Could not read active asset snapshot: {type(exc).__name__}: {exc}",
                "next_step": "Regenerate the episode only if historical asset provenance is intentionally being refreshed.",
            }
        return {
            "status": "present",
            "path": rel_path,
            "asset_count": snapshot.get("asset_count"),
            "source_catalog": snapshot.get("source_catalog"),
            "active_assets": [
                {
                    "asset_id": asset.get("asset_id"),
                    "version": asset.get("version"),
                    "content_sha256": asset.get("content_sha256"),
                }
                for asset in snapshot.get("active_assets", [])
                if isinstance(asset, dict)
            ],
        }
    return {
        "status": "missing",
        "path": rel_path,
        "gap": "This episode predates strategy asset snapshots or was recorded without the strategy asset registry.",
        "next_step": "Do not fabricate historical asset versions; use current catalog only as a low-trust reference.",
    }


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
        text = (result.stdout or result.stderr or "").strip()
        return text
    except Exception as exc:  # noqa: BLE001 - report environment gaps.
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def is_tuner_port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 4318), timeout=2):
            return True
    except OSError:
        return False


def press_continue_keys_win32() -> str:
    if sys.platform != "win32":
        return "Keyboard continue fallback is only implemented on Windows."
    import ctypes

    game_launcher._bring_to_front()
    time.sleep(0.5)
    user32 = ctypes.windll.user32
    vk_tab = 0x09
    vk_return = 0x0D
    keyeventf_keyup = 0x0002
    for key in [vk_tab, vk_tab, vk_tab, vk_return]:
        user32.keybd_event(key, 0, 0, 0)
        time.sleep(0.08)
        user32.keybd_event(key, 0, keyeventf_keyup, 0)
        time.sleep(0.18)
    return "Sent TAB, TAB, TAB, ENTER to the Civ6 window."


def stop_repo_mcp_servers() -> str:
    """Stop stale repo-local civ6-connector server processes before direct observation."""
    if sys.platform != "win32":
        return "Repo-local civ6-connector cleanup is only implemented on Windows."

    ps = r"""
$ErrorActionPreference = 'Stop'
$rootInput = $env:CODEX_HL_CIV6_WORKSPACE
if ([string]::IsNullOrWhiteSpace($rootInput)) {
    throw 'CODEX_HL_CIV6_WORKSPACE is empty.'
}
$root = [System.IO.Path]::GetFullPath($rootInput).ToLowerInvariant()
$selfPid = [int]$env:CODEX_HL_CIV6_SELF_PID
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $selfPid -and
    $_.CommandLine -and
    ($_.Name -in @('uv.exe', 'python.exe', 'civ6-connector.exe')) -and
    $_.CommandLine.ToLowerInvariant().Contains($root) -and
    ($_.CommandLine -match 'civ6-connector(\.exe)?' -or $_.CommandLine -match 'src[\\/]civ6_connector[\\/]server\.py')
}
$rows = @()
foreach ($p in $targets) {
    $stopped = $true
    $stop_note = ''
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    } catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
        $stopped = $false
        $stop_note = 'already exited before Stop-Process'
    }
    $rows += [pscustomobject]@{
        pid = $p.ProcessId
        name = $p.Name
        command_line = $p.CommandLine
        stop_attempted = $true
        stopped = $stopped
        note = $stop_note
    }
}
if ($rows.Count -eq 0) {
    'No repo-local civ6-connector server processes found.'
} else {
    $rows | ConvertTo-Json -Compress
}
"""
    env = os.environ.copy()
    env["CODEX_HL_CIV6_WORKSPACE"] = str(ROOT)
    env["CODEX_HL_CIV6_SELF_PID"] = str(os.getpid())
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps,
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=25,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Failed to stop repo-local civ6-connector servers: {details}")
    return (result.stdout or "No output from repo-local civ6-connector cleanup.").strip()


class EpisodeRecorder:
    def __init__(self, episode_id: str, save_name: str) -> None:
        self.episode_id = episode_id
        self.save_name = save_name
        self.root = ROOT / "episodes" / episode_id
        self.raw = self.root / "raw"
        self.states_dir = self.raw / "civ6_states"
        self.saves_dir = self.raw / "saves"
        self.derived = self.root / "derived"
        self.outcome = self.root / "outcome"
        self.assets = self.root / "assets_snapshot"
        for path in [
            self.raw,
            self.states_dir,
            self.saves_dir,
            self.derived,
            self.outcome,
            self.assets,
        ]:
            path.mkdir(parents=True, exist_ok=True)

        self.header_path = self.root / "header.json"
        self.mcp_path = self.raw / "mcp.jsonl"
        self.tool_calls_path = self.raw / "tool_calls.jsonl"
        self.codex_outputs_path = self.raw / "codex_outputs.jsonl"
        self.decision_path = self.derived / "decision_atoms.jsonl"
        self.report_pack_path = self.derived / "report_pack.json"
        self.timeline_path = self.derived / "timeline.md"
        self.human_notes_path = self.outcome / "human_notes.md"
        self.human_draft_path = self.outcome / "observation_report.draft.html"
        self.report_path = self.outcome / "observation_report.html"
        self.agent_handoff_path = self.outcome / "agent_report.md"
        self.agent_report_path = self.outcome / "agent_audit_report.html"
        self.save_index_path = self.saves_dir / "save_index.jsonl"
        self.manifest_path = self.assets / "manifest.json"
        self.active_assets_path = self.assets / "active_assets.json"
        self.store = EpisodeStore(self.root, episode_id, create=True, reset=True)

        for path in [
            self.mcp_path,
            self.tool_calls_path,
            self.codex_outputs_path,
            self.decision_path,
            self.save_index_path,
        ]:
            path.write_text("", encoding="utf-8")
            self.store.put_text_artifact(
                self.rel(path),
                "",
                kind={
                    self.mcp_path: "mcp_events",
                    self.tool_calls_path: "tool_calls",
                    self.codex_outputs_path: "codex_outputs",
                    self.decision_path: "decision_atoms",
                    self.save_index_path: "saves",
                }[path],
                media_type="application/x-ndjson",
            )
        self.timeline_path.write_text(
            f"# {episode_id}\n\nWorkflow: {WORKFLOW_LABEL}\n\n", encoding="utf-8"
        )
        self.store.put_text_artifact(
            self.rel(self.timeline_path),
            self.timeline_path.read_text(encoding="utf-8"),
            kind="timeline",
            media_type="text/markdown",
        )
        self.human_notes_path.write_text(
            "# Human notes\n\nShort-run acceptance is pending.\n", encoding="utf-8"
        )
        self.store.put_text_artifact(
            self.rel(self.human_notes_path),
            self.human_notes_path.read_text(encoding="utf-8"),
            kind="human_notes",
            media_type="text/markdown",
        )
        active_assets = write_active_asset_snapshot(self.active_assets_path)
        self.store.put_json_artifact(
            self.rel(self.active_assets_path),
            active_assets,
            kind="asset_snapshot",
        )

        self.tool_seq = 0
        self.lua_seq = 0
        self.state_seq = 0
        self.decision_seq = 0
        self.save_seq = 0
        self.state_ids: list[str] = []
        self.save_ids: list[str] = []
        self.turn_summaries: list[dict[str, Any]] = []
        self.missing_fields: list[dict[str, str]] = []
        self.tool_error_count = 0
        self.lua_error_count = 0
        self.start_time = now_iso()
        self.final_turn: int | None = None
        self.start_turn: int | None = None
        self.blocked_map_targets: dict[tuple[str, int, int], int] = {}

    def rel(self, path: Path) -> str:
        return logical_path_for(self.root, path)

    def store_text_artifact(
        self,
        path: Path,
        text: str,
        *,
        kind: str | None = None,
        media_type: str | None = None,
    ) -> None:
        self.store.put_text_artifact(
            self.rel(path),
            text,
            kind=kind,
            media_type=media_type,
        )

    def store_json_artifact(
        self,
        path: Path,
        data: Any,
        *,
        kind: str | None = None,
    ) -> None:
        self.store.put_json_artifact(self.rel(path), to_jsonable(data), kind=kind)

    def append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        serializable = to_jsonable(row)
        self.store.append_jsonl(self.rel(path), serializable)
        self.store.export_artifact(self.rel(path))

    def timeline(self, line: str) -> None:
        with self.timeline_path.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
        self.store_text_artifact(
            self.timeline_path,
            self.timeline_path.read_text(encoding="utf-8"),
            kind="timeline",
            media_type="text/markdown",
        )

    def codex_output(self, kind: str, turn: int | None, content: Any) -> None:
        self.append_jsonl(
            self.codex_outputs_path,
            {
                "ts": now_iso(),
                "episode_id": self.episode_id,
                "kind": kind,
                "turn": turn,
                "content": to_jsonable(content),
            },
        )

    async def log_lua(
        self,
        context: str,
        lua_code: str,
        timeout: float,
        fn: Callable[[], Awaitable[list[str]]],
    ) -> list[str]:
        self.lua_seq += 1
        call_id = f"lua-{self.lua_seq:05d}"
        start = time.perf_counter()
        row: dict[str, Any] = {
            "call_id": call_id,
            "ts_start": now_iso(),
            "episode_id": self.episode_id,
            "kind": "lua_exchange",
            "context": context,
            "timeout": timeout,
            "request": lua_code,
        }
        try:
            result = await fn()
            row["ts_end"] = now_iso()
            row["duration_ms"] = int((time.perf_counter() - start) * 1000)
            row["success"] = True
            row["response"] = result
            return result
        except Exception as exc:  # noqa: BLE001 - raw evidence capture.
            self.lua_error_count += 1
            row["ts_end"] = now_iso()
            row["duration_ms"] = int((time.perf_counter() - start) * 1000)
            row["success"] = False
            row["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            raise
        finally:
            self.append_jsonl(self.mcp_path, row)

    async def tool_call(
        self,
        name: str,
        params: dict[str, Any],
        fn: Callable[[], Awaitable[Any]],
        *,
        turn: int | None = None,
    ) -> tuple[str, Any]:
        self.tool_seq += 1
        call_id = f"tool-{self.tool_seq:05d}"
        start = time.perf_counter()
        row: dict[str, Any] = {
            "tool_call_id": call_id,
            "ts_start": now_iso(),
            "episode_id": self.episode_id,
            "turn": turn,
            "tool": name,
            "params": to_jsonable(params),
        }
        try:
            result = await fn()
            row["ts_end"] = now_iso()
            row["duration_ms"] = int((time.perf_counter() - start) * 1000)
            row["success"] = True
            row["result_raw"] = to_jsonable(result)
            row["result_text"] = short_text(result, 6000)
            return call_id, result
        except Exception as exc:  # noqa: BLE001 - raw evidence capture.
            self.tool_error_count += 1
            row["ts_end"] = now_iso()
            row["duration_ms"] = int((time.perf_counter() - start) * 1000)
            row["success"] = False
            row["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            raise
        finally:
            self.append_jsonl(self.tool_calls_path, row)

    def add_gap(self, field: str, reason: str, next_step: str) -> None:
        self.missing_fields.append(
            {"field": field, "reason": reason, "next_step": next_step}
        )

    def write_header(self, data: dict[str, Any]) -> None:
        serializable = to_jsonable(data)
        self.store.put_episode_header(
            serializable,
            workflow=WORKFLOW_LABEL,
            save_name=self.save_name,
            requested_turns=getattr(self, "requested_turns", None),
            strategy_profile=getattr(self, "strategy_profile", None),
        )
        self.store.export_artifact(self.rel(self.header_path))

    def record_state(
        self,
        turn: int,
        label: str,
        snapshot: dict[str, Any],
        related_tool_call_ids: list[str],
    ) -> str:
        self.state_seq += 1
        snapshot_id = f"state-{self.state_seq:04d}-T{turn:04d}-{label}"
        row = {
            "snapshot_id": snapshot_id,
            "episode_id": self.episode_id,
            "turn": turn,
            "label": label,
            "ts": now_iso(),
            "related_tool_call_ids": related_tool_call_ids,
            **snapshot,
        }
        path = self.states_dir / f"{snapshot_id}.json"
        self.store_json_artifact(path, row, kind="state_snapshot")
        self.store.export_artifact(self.rel(path))
        self.state_ids.append(snapshot_id)
        self.timeline(f"- T{turn} state snapshot `{snapshot_id}` captured.")
        return snapshot_id

    def record_decision(self, atom: dict[str, Any]) -> str:
        self.decision_seq += 1
        decision_id = f"decision-{self.decision_seq:04d}"
        row = {
            "decision_id": decision_id,
            "episode_id": self.episode_id,
            **atom,
        }
        required = [
            "turn",
            "trigger",
            "importance",
            "background",
            "current_goal",
            "available_actions",
            "selected_action",
            "rationale",
            "why_not_alternatives",
            "execution",
            "outcome",
            "related_tool_call_ids",
            "related_state_snapshot_ids",
            "related_save_ids",
        ]
        for key in required:
            if key not in row:
                row[key] = [] if key.startswith("related_") or key == "available_actions" else ""
        row.setdefault("alternatives", row.get("available_actions", []))
        row.setdefault(
            "evidence_ids",
            {
                "tool_call_ids": row.get("related_tool_call_ids", []),
                "state_snapshot_ids": row.get("related_state_snapshot_ids", []),
                "save_ids": row.get("related_save_ids", []),
            },
        )
        self.append_jsonl(self.decision_path, row)
        self.codex_output("decision_atom", row.get("turn"), row)
        self.timeline(
            f"- T{row.get('turn')} decision `{decision_id}`: {row.get('selected_action')}"
        )
        return decision_id

    def record_save(
        self,
        *,
        source_path: Path,
        turn: int | None,
        label: str,
        decision_id: str | None = None,
        event: str = "",
    ) -> str:
        self.save_seq += 1
        save_id = f"save-{self.save_seq:04d}"
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
        destination = self.saves_dir / f"{save_id}_{safe_label}{source_path.suffix}"
        shutil.copy2(source_path, destination)
        save_artifact_id = self.store.put_file_artifact(
            self.rel(destination),
            destination,
            kind="save_file",
            metadata={"save_id": save_id, "turn": turn, "label": label},
        )
        row = {
            "save_id": save_id,
            "episode_id": self.episode_id,
            "turn": turn,
            "label": label,
            "event": event,
            "decision_id": decision_id,
            "source_path": str(source_path),
            "episode_path": str(destination),
            "size_bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "save_artifact_id": save_artifact_id,
            "ts": now_iso(),
        }
        self.append_jsonl(self.save_index_path, row)
        self.save_ids.append(save_id)
        self.timeline(f"- T{turn} save `{save_id}` indexed: `{destination.name}`.")
        return save_id

    def write_manifest(self) -> None:
        self.store.update_episode_run(
            save_name=self.save_name,
            requested_turns=getattr(self, "requested_turns", None),
            start_turn=self.start_turn,
            final_turn=self.final_turn,
            strategy_profile=getattr(self, "strategy_profile", None),
        )
        files = self.store.manifest_file_rows(exclude={self.rel(self.manifest_path)})
        if self.store is not None and self.store.has_artifact("assets_snapshot/active_assets.json"):
            asset_snapshot = {
                "status": "present",
                "path": "assets_snapshot/active_assets.json",
                "sha256": self.store.artifact_ref("assets_snapshot/active_assets.json")["sha256"],
                "active_assets": self.store.read_json("assets_snapshot/active_assets.json").get("active_assets", []),
            }
        else:
            asset_snapshot = asset_snapshot_manifest(self.active_assets_path)
        manifest = {
            "episode_id": self.episode_id,
            "workflow": WORKFLOW_LABEL,
            "generated_at": now_iso(),
            "storage": {
                "backend": "sqlite",
                "db_path": str(self.root / "episode.db"),
                "schema_version": 1,
                "legacy_tree_role": "cache/export",
            },
            "repo": {
                "root": str(ROOT),
                "commit": run_git(["rev-parse", "HEAD"]),
                "branch": run_git(["branch", "--show-current"]),
                "status_short": run_git(["status", "--short"]),
            },
            "counts": {
                "tool_calls": self.tool_seq,
                "lua_exchanges": self.lua_seq,
                "state_snapshots": len(self.state_ids),
                "decision_atoms": self.decision_seq,
                "indexed_saves": len(self.save_ids),
                "tool_errors": self.tool_error_count,
                "lua_errors": self.lua_error_count,
            },
            "asset_snapshot": asset_snapshot,
            "files": files,
        }
        self.store_json_artifact(self.manifest_path, manifest, kind="manifest")
        self.store.export_artifact(self.rel(self.manifest_path))


class RecordingConnection(GameConnection):
    def __init__(self, recorder: EpisodeRecorder):
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

    async def execute_in_state(
        self, state_index: int, lua_code: str, timeout: float = 5.0
    ) -> list[str]:
        return await self.recorder.log_lua(
            f"state:{state_index}",
            lua_code,
            timeout,
            lambda: super(RecordingConnection, self).execute_in_state(
                state_index, lua_code, timeout
            ),
        )


def needs_choice(value: str) -> bool:
    text = (value or "").strip().lower()
    return text in {"", "none", "null", "no research", "not selected"}


def is_idle_city(city: Any) -> bool:
    building = (getattr(city, "currently_building", "") or "").upper()
    turns_left = getattr(city, "production_turns_left", 0)
    return building in {"", "NONE", "NOTHING", "CORRUPTED_QUEUE"} or turns_left <= 0


def choose_by_priority(options: list[Any], attr: str, priority: list[str]) -> Any | None:
    if not options:
        return None
    by_name = {getattr(opt, attr, ""): opt for opt in options}
    for item in priority:
        if item in by_name:
            return by_name[item]
    return sorted(options, key=lambda opt: getattr(opt, "turns", 9999))[0]


def recorder_strategy_profile(recorder: Any) -> str:
    return str(getattr(recorder, "strategy_profile", BASELINE_STRATEGY_PROFILE))


def recorder_candidate_runtime(recorder: Any) -> dict[str, Any]:
    runtime = getattr(recorder, "candidate_runtime", None)
    return runtime if isinstance(runtime, dict) else {"status": "not_supplied", "runtime_effects": []}


def candidate_runtime_has(recorder: Any, effect: str) -> bool:
    runtime = recorder_candidate_runtime(recorder)
    return effect in (runtime.get("runtime_effects") or [])


def uses_science_culture_t50_runtime(recorder: Any) -> bool:
    return (
        recorder_strategy_profile(recorder) == SCIENCE_CULTURE_T50_STRATEGY_PROFILE
        or recorder_strategy_profile(recorder) == GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        or candidate_runtime_has(recorder, "science_culture_push")
        or candidate_runtime_has(recorder, "era_score_push")
        or candidate_runtime_has(recorder, "golden_age_push")
    )


def uses_golden_age_push_runtime(recorder: Any) -> bool:
    return (
        recorder_strategy_profile(recorder) == GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        or candidate_runtime_has(recorder, "golden_age_push")
        or candidate_runtime_has(recorder, "era_score_push")
    )


def uses_barbarian_clearance_runtime(recorder: Any) -> bool:
    return (
        recorder_strategy_profile(recorder) == SCIENCE_CULTURE_T50_STRATEGY_PROFILE
        or recorder_strategy_profile(recorder) == GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        or candidate_runtime_has(recorder, "barbarian_clearance")
        or candidate_runtime_has(recorder, "golden_age_push")
    )


def uses_river_settlement_runtime(recorder: Any) -> bool:
    return (
        recorder_strategy_profile(recorder) == SCIENCE_CULTURE_T50_STRATEGY_PROFILE
        or recorder_strategy_profile(recorder) == GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        or candidate_runtime_has(recorder, "river_settlement")
    )


def uses_horseman_pressure_runtime(recorder: Any) -> bool:
    return (
        recorder_strategy_profile(recorder) == SCIENCE_CULTURE_T50_STRATEGY_PROFILE
        or recorder_strategy_profile(recorder) == GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        or candidate_runtime_has(recorder, "horseman_pressure")
        or candidate_runtime_has(recorder, "opportunistic_war")
    )


def uses_expansion_runtime(recorder: Any) -> bool:
    return (
        recorder_strategy_profile(recorder) == EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE
        or recorder_strategy_profile(recorder) == SCIENCE_CULTURE_T50_STRATEGY_PROFILE
        or recorder_strategy_profile(recorder) == GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        or candidate_runtime_has(recorder, "expansion_pressure")
        or candidate_runtime_has(recorder, "scouting_pressure")
        or candidate_runtime_has(recorder, "river_settlement")
    )


def strategy_context(recorder: Any) -> dict[str, Any]:
    runtime = recorder_candidate_runtime(recorder)
    return {
        "strategy_profile": recorder_strategy_profile(recorder),
        "candidate_runtime_status": runtime.get("status"),
        "candidate_id": runtime.get("candidate_id"),
        "source_failure_ids": runtime.get("source_failure_ids", []),
        "runtime_effects": runtime.get("runtime_effects", []),
    }


def strategy_priority_label(recorder: Any) -> str:
    runtime = recorder_candidate_runtime(recorder)
    if runtime.get("status") == "applied":
        return f"candidate playbook {runtime.get('candidate_id')}"
    return f"{recorder_strategy_profile(recorder)} profile"


def snapshot_unit_count(
    snapshot: dict[str, Any] | None,
    unit_type: str,
    extra_units: dict[str, int] | None = None,
) -> int:
    if not snapshot:
        count = 0
    else:
        count = sum(
            1
            for unit in snapshot.get("units") or []
            if getattr(unit, "unit_type", None) == unit_type
            or (isinstance(unit, dict) and unit.get("unit_type") == unit_type)
        )
        count += sum(
            1
            for city in snapshot.get("cities") or []
            if getattr(city, "currently_building", None) == unit_type
            or (isinstance(city, dict) and city.get("currently_building") == unit_type)
        )
    if extra_units:
        count += extra_units.get(unit_type, 0)
    return count


def snapshot_city_count(snapshot: dict[str, Any] | None) -> int:
    if not snapshot:
        return 0
    return len(snapshot.get("cities") or [])


def snapshot_turn(snapshot: dict[str, Any] | None) -> int:
    if not snapshot:
        return 0
    overview = snapshot.get("overview") or {}
    return int(number_from(overview, "turn", number_from(snapshot, "turn", 0)) or 0)


def snapshot_combat_unit_count(
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> int:
    combat_types = {"UNIT_WARRIOR", "UNIT_SLINGER", "UNIT_ARCHER", "UNIT_HORSEMAN"}
    if not snapshot:
        count = 0
    else:
        count = sum(
            1
            for unit in snapshot.get("units") or []
            if getattr(unit, "unit_type", None) in combat_types
            or (isinstance(unit, dict) and unit.get("unit_type") in combat_types)
        )
        count += sum(
            1
            for city in snapshot.get("cities") or []
            if getattr(city, "currently_building", None) in combat_types
            or (
                isinstance(city, dict)
                and city.get("currently_building") in combat_types
            )
        )
    if extra_units:
        count += sum(extra_units.get(unit_type, 0) for unit_type in combat_types)
    return count


def snapshot_ranged_clearing_unit_count(
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> int:
    ranged_types = {"UNIT_SLINGER", "UNIT_ARCHER"}
    if not snapshot:
        count = 0
    else:
        count = sum(
            1
            for unit in snapshot.get("units") or []
            if value_from(unit, "unit_type") in ranged_types
        )
        count += sum(
            1
            for city in snapshot.get("cities") or []
            if value_from(city, "currently_building") in ranged_types
        )
    if extra_units:
        count += sum(extra_units.get(unit_type, 0) for unit_type in ranged_types)
    return count


def value_from(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def number_from(value: Any, key: str, default: float = 0.0) -> float:
    raw = value_from(value, key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def snapshot_overview_number(snapshot: dict[str, Any] | None, key: str) -> float | None:
    if not snapshot:
        return None
    raw = value_from(snapshot.get("overview") or {}, key)
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def snapshot_agent_empire_row(snapshot: dict[str, Any] | None) -> Any | None:
    if not snapshot:
        return None
    empire = snapshot.get("empire") or {}
    players = value_from(empire, "players", []) or []
    for player in players:
        if int(number_from(player, "pid", -1)) == 0 or bool(value_from(player, "is_agent", False)):
            return player
    return players[0] if players else None


def snapshot_current_age(snapshot: dict[str, Any] | None) -> str:
    agent = snapshot_agent_empire_row(snapshot)
    if agent is None:
        return ""
    return str(value_from(agent, "age", "") or "").upper()


def snapshot_current_era(snapshot: dict[str, Any] | None) -> str:
    agent = snapshot_agent_empire_row(snapshot)
    if agent is not None:
        era = str(value_from(agent, "era", "") or "")
        if era:
            return era.upper()
    if not snapshot:
        return ""
    overview = snapshot.get("overview") or {}
    era_name = str(value_from(overview, "era_name", "") or "")
    if "ancient" in era_name.lower() or "远古" in era_name:
        return "ERA_ANCIENT"
    if "classical" in era_name.lower() or "古典" in era_name:
        return "ERA_CLASSICAL"
    return era_name.upper()


def snapshot_is_ancient_era(snapshot: dict[str, Any] | None) -> bool:
    return snapshot_current_era(snapshot) == "ERA_ANCIENT"


def era_score_gap(snapshot: dict[str, Any] | None) -> int | None:
    if not snapshot:
        return None
    overview = snapshot.get("overview") or {}
    threshold = int(number_from(overview, "era_golden_threshold", 0))
    if threshold <= 0:
        return None
    score = int(number_from(overview, "era_score", 0))
    return max(0, threshold - score)


def golden_age_achieved(snapshot: dict[str, Any] | None) -> bool:
    if snapshot_current_age(snapshot) in {"GOLDEN", "HEROIC"}:
        return True
    gap = era_score_gap(snapshot)
    return gap == 0 if gap is not None else False


def golden_age_gold_spend_threshold(snapshot: dict[str, Any] | None) -> int:
    if (
        snapshot_is_ancient_era(snapshot)
        and not golden_age_achieved(snapshot)
        and (era_score_gap(snapshot) or 0) > 0
    ):
        return GOLDEN_AGE_PUSH_ANCIENT_MIN_GOLD_TO_SPEND
    return GOLDEN_AGE_PUSH_MIN_GOLD_TO_SPEND


def threat_is_barbarian(threat: Any) -> bool:
    owner_name = str(value_from(threat, "owner_name", "") or "").lower()
    owner_id = value_from(threat, "owner_id", None)
    return owner_id == 63 or "barbarian" in owner_name or "蛮" in owner_name


def visible_barbarian_threat_count(snapshot: dict[str, Any] | None) -> int:
    if not snapshot:
        return 0
    return sum(1 for threat in snapshot.get("threats") or [] if threat_is_barbarian(threat))


def cap_post_three_city_builders(
    priority: list[str],
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> list[str]:
    if (
        snapshot_unit_count(snapshot, "UNIT_BUILDER", extra_units)
        < EXPLORE_SCOUT_FIRST_BUILDER_CAP_AFTER_THREE_CITIES
    ):
        return priority
    return [item for item in priority if item != "UNIT_BUILDER"] + ["UNIT_BUILDER"]


def science_culture_t50_priority_for(
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> list[str]:
    city_count = snapshot_city_count(snapshot)
    combat_count = snapshot_combat_unit_count(snapshot, extra_units)
    ranged_count = snapshot_ranged_clearing_unit_count(snapshot, extra_units)
    settler_count = snapshot_unit_count(snapshot, "UNIT_SETTLER", extra_units)
    science = snapshot_overview_number(snapshot, "science_yield") or 0.0
    culture = snapshot_overview_number(snapshot, "culture_yield") or 0.0
    if (
        visible_barbarian_threat_count(snapshot) > 0
        and ranged_count < SCIENCE_CULTURE_T50_RANGED_CLEARING_CAP
    ):
        return SCIENCE_CULTURE_T50_DEFENSE_PRIORITY
    if (
        city_count >= 3
        and combat_count < SCIENCE_CULTURE_T50_MIN_COMBAT_AFTER_THREE_CITIES
    ):
        return SCIENCE_CULTURE_T50_DEFENSE_PRIORITY
    if city_count >= 2 and combat_count < SCIENCE_CULTURE_T50_MIN_COMBAT_AFTER_TWO_CITIES:
        return SCIENCE_CULTURE_T50_DEFENSE_PRIORITY
    if city_count < 3 and settler_count == 0:
        return SCIENCE_CULTURE_T50_EARLY_EXPANSION_PRIORITY
    if science < SCIENCE_CULTURE_T50_YIELD_TARGET or culture < SCIENCE_CULTURE_T50_YIELD_TARGET:
        return SCIENCE_CULTURE_T50_LOW_YIELD_PRIORITY
    if city_count < SCIENCE_CULTURE_T50_TARGET_CITIES and settler_count == 0:
        return SCIENCE_CULTURE_T50_EARLY_EXPANSION_PRIORITY
    return SCIENCE_CULTURE_T50_LOW_YIELD_PRIORITY


def golden_age_push_priority_for(
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> list[str]:
    gap = era_score_gap(snapshot)
    if gap and gap > 0:
        if snapshot_is_ancient_era(snapshot):
            turn = snapshot_turn(snapshot)
            city_count = snapshot_city_count(snapshot)
            scout_count = snapshot_unit_count(snapshot, "UNIT_SCOUT", extra_units)
            settler_count = snapshot_unit_count(snapshot, "UNIT_SETTLER", extra_units)
            builder_count = snapshot_unit_count(snapshot, "UNIT_BUILDER", extra_units)
            combat_count = snapshot_combat_unit_count(snapshot, extra_units)
            ranged_count = snapshot_ranged_clearing_unit_count(snapshot, extra_units)
            if (
                scout_count < GOLDEN_AGE_PUSH_ANCIENT_SCOUT_CAP
                and turn <= GOLDEN_AGE_PUSH_ANCIENT_SCOUT_REPLACEMENT_LATEST_TURN
            ):
                return GOLDEN_AGE_PUSH_ANCIENT_SCOUTING_PRIORITY
            if ancient_post_settle_builder_reserve_active(
                snapshot
            ) and builder_purchase_affordable(snapshot):
                return GOLDEN_AGE_PUSH_ANCIENT_BUILDER_PURCHASE_RESERVE_PRIORITY
            if ancient_strategic_resource_push_active(snapshot, extra_units):
                return GOLDEN_AGE_PUSH_ANCIENT_STRATEGIC_RESOURCE_PRIORITY
            if combat_count < GOLDEN_AGE_PUSH_ANCIENT_MIN_COMBAT_UNITS:
                return GOLDEN_AGE_PUSH_ANCIENT_DEFENSE_PRIORITY
            if (
                city_count < GOLDEN_AGE_PUSH_ANCIENT_TARGET_CITIES
                and settler_count == 0
                and combat_count >= GOLDEN_AGE_PUSH_ANCIENT_MIN_COMBAT_UNITS
            ):
                return GOLDEN_AGE_PUSH_ANCIENT_EXPANSION_PRIORITY
            if builder_count == 0 or ranged_count >= GOLDEN_AGE_PUSH_ANCIENT_RANGED_CAP:
                return GOLDEN_AGE_PUSH_ANCIENT_DEVELOPMENT_PRIORITY
        return GOLDEN_AGE_PUSH_PRODUCTION_PRIORITY
    return science_culture_t50_priority_for(snapshot, extra_units)


def production_priority_for(
    recorder: Any,
    snapshot: dict[str, Any] | None = None,
    extra_units: dict[str, int] | None = None,
) -> list[str]:
    if uses_golden_age_push_runtime(recorder):
        return golden_age_push_priority_for(snapshot, extra_units)
    if uses_science_culture_t50_runtime(recorder):
        return science_culture_t50_priority_for(snapshot, extra_units)
    if uses_expansion_runtime(recorder):
        if (
            snapshot_unit_count(snapshot, "UNIT_SCOUT", extra_units)
            >= EXPLORE_SCOUT_FIRST_SCOUT_CAP
        ):
            if snapshot_city_count(snapshot) >= 3:
                if (
                    snapshot_combat_unit_count(snapshot, extra_units)
                    < EXPLORE_SCOUT_FIRST_MIN_COMBAT_AFTER_THREE_CITIES
                ):
                    return cap_post_three_city_builders(
                        EXPLORE_SCOUT_FIRST_POST_THREE_CITY_DEFENSE_PRIORITY,
                        snapshot,
                        extra_units,
                    )
                if (
                    snapshot_city_count(snapshot)
                    < EXPLORE_SCOUT_FIRST_TARGET_T50_CITIES
                    and snapshot_unit_count(snapshot, "UNIT_SETTLER", extra_units) == 0
                ):
                    return cap_post_three_city_builders(
                        EXPLORE_SCOUT_FIRST_POST_THREE_CITY_EXPANSION_PRIORITY,
                        snapshot,
                        extra_units,
                    )
                return cap_post_three_city_builders(
                    EXPLORE_SCOUT_FIRST_POST_THREE_CITY_PRIORITY,
                    snapshot,
                    extra_units,
                )
            if (
                snapshot_city_count(snapshot) >= 2
                and snapshot_combat_unit_count(snapshot, extra_units) < 2
            ):
                return [
                    "UNIT_SLINGER",
                    "UNIT_WARRIOR",
                    "BUILDING_MONUMENT",
                    "UNIT_BUILDER",
                    "UNIT_SETTLER",
                    "UNIT_TRADER",
                    "DISTRICT_CAMPUS",
                    "BUILDING_GRANARY",
                    "BUILDING_WATER_MILL",
                    "UNIT_SCOUT",
                ]
            return [
                item
                for item in EXPLORE_SCOUT_FIRST_PRODUCTION_PRIORITY
                if item != "UNIT_SCOUT"
            ] + ["UNIT_SCOUT"]
        return EXPLORE_SCOUT_FIRST_PRODUCTION_PRIORITY
    return PRODUCTION_PRIORITY


def tech_priority_for(recorder: Any) -> list[str]:
    if uses_golden_age_push_runtime(recorder):
        return GOLDEN_AGE_PUSH_TECH_PRIORITY
    if uses_science_culture_t50_runtime(recorder):
        return SCIENCE_CULTURE_T50_TECH_PRIORITY
    return TECH_PRIORITY


def civic_priority_for(recorder: Any) -> list[str]:
    if uses_golden_age_push_runtime(recorder):
        return GOLDEN_AGE_PUSH_CIVIC_PRIORITY
    return CIVIC_PRIORITY


def should_auto_explore_unit(
    recorder: Any, unit_type: str, snapshot: dict[str, Any] | None = None
) -> bool:
    if not uses_expansion_runtime(recorder):
        return False
    if unit_type == "UNIT_SCOUT":
        return True
    if unit_type == "UNIT_WARRIOR":
        if (
            uses_golden_age_push_runtime(recorder)
            and snapshot_is_ancient_era(snapshot)
            and not golden_age_achieved(snapshot)
            and snapshot_turn(snapshot) <= 12
            and snapshot_unit_count(snapshot, "UNIT_SETTLER") == 0
        ):
            return True
        return snapshot_unit_count(snapshot, "UNIT_SCOUT") == 0 and snapshot_unit_count(
            snapshot, "UNIT_SETTLER"
        ) == 0
    return False


def best_settle_candidate(candidates: list[Any], *, prefer_fresh: bool = False) -> Any | None:
    if not candidates:
        return None
    return ranked_settle_candidates(candidates, prefer_fresh=prefer_fresh)[0]


def settle_fresh_water_bonus(candidate: Any) -> float:
    water_type = str(value_from(candidate, "water_type", "") or "").lower()
    if water_type == "fresh":
        return 6.0
    if water_type == "coast":
        return 1.0
    return 0.0


def candidate_matches_unit_tile(candidate: Any, unit: Any) -> bool:
    try:
        return int(value_from(candidate, "x")) == int(value_from(unit, "x")) and int(
            value_from(candidate, "y")
        ) == int(value_from(unit, "y"))
    except (TypeError, ValueError):
        return False


def candidate_has_fresh_water(candidate: Any) -> bool:
    return settle_fresh_water_bonus(candidate) >= 6.0


def candidate_distance_from_unit(candidate: Any, unit: Any) -> int:
    try:
        return max(
            abs(int(value_from(candidate, "x")) - int(value_from(unit, "x"))),
            abs(int(value_from(candidate, "y")) - int(value_from(unit, "y"))),
        )
    except (TypeError, ValueError):
        return 999


def ranked_settle_candidates(candidates: list[Any], *, prefer_fresh: bool = False) -> list[Any]:
    if prefer_fresh:
        return sorted(
            candidates,
            key=lambda item: (
                1 if candidate_has_fresh_water(item) else 0,
                float(value_from(item, "score", 0) or 0)
                + (1.0 if str(value_from(item, "water_type", "") or "").lower() == "coast" else 0.0),
                float(value_from(item, "score", 0) or 0),
            ),
            reverse=True,
        )
    return sorted(
        candidates,
        key=lambda item: (
            float(value_from(item, "score", 0) or 0),
        ),
        reverse=True,
    )


def strategic_resource_distance_for_xy(
    x: Any,
    y: Any,
    snapshot: dict[str, Any] | None,
) -> int:
    if not snapshot:
        return 999
    try:
        cx = int(x)
        cy = int(y)
    except (TypeError, ValueError):
        return 999
    resources = snapshot.get("resources")
    targets = [
        *unimproved_strategic_resources(resources),
        *nearby_strategic_resources(resources),
    ]
    distances: list[int] = []
    for resource in targets:
        rx = value_from(resource, "x", None)
        ry = value_from(resource, "y", None)
        if rx is None or ry is None:
            continue
        try:
            distances.append(max(abs(cx - int(rx)), abs(cy - int(ry))))
        except (TypeError, ValueError):
            continue
    return min(distances) if distances else 999


def strategic_resource_distance_for_candidate(
    candidate: Any,
    snapshot: dict[str, Any] | None,
) -> int:
    return strategic_resource_distance_for_xy(
        value_from(candidate, "x", None),
        value_from(candidate, "y", None),
        snapshot,
    )


def golden_age_strategic_settle_active(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    if not snapshot_is_ancient_era(snapshot) or golden_age_achieved(snapshot):
        return False
    if (era_score_gap(snapshot) or 0) <= 0:
        return False
    resources = snapshot.get("resources")
    if not nearby_strategic_resources(resources) and not unimproved_strategic_resources(resources):
        return False
    income = strategic_resource_income_by_key(resources)
    return not any(income.get(resource, 0) > 0 for resource in GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY)


def ranked_golden_age_strategic_settle_candidates(
    candidates: list[Any],
    snapshot: dict[str, Any] | None,
    *,
    prefer_fresh: bool = False,
) -> list[Any]:
    return sorted(
        candidates,
        key=lambda item: (
            0
            if strategic_resource_distance_for_candidate(item, snapshot)
            <= GOLDEN_AGE_PUSH_STRATEGIC_SETTLE_RADIUS
            else 1,
            strategic_resource_distance_for_candidate(item, snapshot),
            -min(settle_fresh_water_bonus(item), 2.0) if prefer_fresh else 0.0,
            -float(value_from(item, "score", 0) or 0),
        ),
    )


def ranked_settle_candidates_for_strategy(
    recorder: Any,
    snapshot: dict[str, Any] | None,
    candidates: list[Any],
    *,
    prefer_fresh: bool = False,
) -> list[Any]:
    if uses_golden_age_push_runtime(recorder) and golden_age_strategic_settle_active(snapshot):
        return ranked_golden_age_strategic_settle_candidates(
            candidates,
            snapshot,
            prefer_fresh=prefer_fresh,
        )
    return ranked_settle_candidates(candidates, prefer_fresh=prefer_fresh)


def ranked_near_settle_candidates_for_unit(
    candidates: list[Any],
    unit: Any,
    *,
    max_distance: int,
    prefer_fresh: bool = False,
) -> list[Any]:
    near = [
        candidate
        for candidate in candidates
        if candidate_distance_from_unit(candidate, unit) <= max_distance
    ]
    return sorted(
        near,
        key=lambda item: (
            float(value_from(item, "score", 0) or 0),
            min(settle_fresh_water_bonus(item), 2.0) if prefer_fresh else 0.0,
            -candidate_distance_from_unit(item, unit),
        ),
        reverse=True,
    )


def ranked_near_settle_candidates_for_strategy(
    recorder: Any,
    snapshot: dict[str, Any] | None,
    candidates: list[Any],
    unit: Any,
    *,
    max_distance: int,
    prefer_fresh: bool = False,
) -> list[Any]:
    near = [
        candidate
        for candidate in candidates
        if candidate_distance_from_unit(candidate, unit) <= max_distance
    ]
    if uses_golden_age_push_runtime(recorder) and golden_age_strategic_settle_active(snapshot):
        return ranked_golden_age_strategic_settle_candidates(
            near,
            snapshot,
            prefer_fresh=prefer_fresh,
        )
    return ranked_near_settle_candidates_for_unit(
        near,
        unit,
        max_distance=max_distance,
        prefer_fresh=prefer_fresh,
    )


TARGET_RE = re.compile(r"@(?P<x>-?\d+),(?P<y>-?\d+)\((?P<hp>\d+)hp\)")


def parse_attack_target(raw: str) -> dict[str, Any] | None:
    match = TARGET_RE.search(raw or "")
    if not match:
        return None
    return {
        "raw": raw,
        "x": int(match.group("x")),
        "y": int(match.group("y")),
        "hp": int(match.group("hp")),
    }


def threat_at(threats: list[Any], x: int, y: int) -> Any | None:
    for threat in threats:
        if value_from(threat, "x") == x and value_from(threat, "y") == y:
            return threat
    return None


def unit_is_ranged_clearer(unit: Any) -> bool:
    return str(value_from(unit, "unit_type", "") or "") in {"UNIT_SLINGER", "UNIT_ARCHER"} or (
        float(value_from(unit, "ranged_strength", 0) or 0) > 0
        and float(value_from(unit, "combat_strength", 0) or 0) <= 15
    )


def target_is_adjacent_to_unit(unit: Any, target: dict[str, Any]) -> bool:
    unit_x = int(value_from(unit, "x", target["x"]) or target["x"])
    unit_y = int(value_from(unit, "y", target["y"]) or target["y"])
    return max(abs(int(target["x"]) - unit_x), abs(int(target["y"]) - unit_y)) <= 1


def golden_age_map_target_event(tile: Any) -> tuple[str, int] | None:
    improvement = str(value_from(tile, "improvement", "") or "").upper()
    feature = str(value_from(tile, "feature", "") or "").upper()
    if "BARBARIAN_CAMP" in improvement or "BARBARIAN_OUTPOST" in improvement:
        return "clear_barbarian_camp", 0
    if "NATURAL_WONDER" in feature:
        return "natural_wonder", 1
    if "GOODY" in improvement or "TRIBAL" in improvement or "VILLAGE" in improvement:
        return "tribal_village", 3
    return None


def unit_can_route_to_golden_age_map_target(unit: Any, target: dict[str, Any]) -> bool:
    unit_type = str(value_from(unit, "unit_type", "") or "")
    event_key = str(target.get("event_key") or "")
    if event_key == "clear_barbarian_camp":
        return unit_type in BARBARIAN_CLEARING_UNIT_TYPES
    if event_key in {"tribal_village", "natural_wonder"}:
        return unit_type in {
            "UNIT_SCOUT",
            "UNIT_WARRIOR",
            "UNIT_SLINGER",
            "UNIT_ARCHER",
            "UNIT_HORSEMAN",
        }
    return False


def ranked_golden_age_map_targets_for_unit(unit: Any, tiles: list[Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for tile in tiles:
        event = golden_age_map_target_event(tile)
        if event is None:
            continue
        event_key, priority = event
        target = {
            "event_key": event_key,
            "priority": priority,
            "x": int(number_from(tile, "x", 0)),
            "y": int(number_from(tile, "y", 0)),
            "distance": candidate_distance_from_unit(tile, unit),
            "improvement": value_from(tile, "improvement", ""),
            "feature": value_from(tile, "feature", ""),
            "resource": value_from(tile, "resource", ""),
        }
        if unit_can_route_to_golden_age_map_target(unit, target):
            targets.append(target)
    return sorted(
        targets,
        key=lambda row: (
            int(row["priority"]),
            int(row["distance"]),
            str(row["event_key"]),
            int(row["x"]),
            int(row["y"]),
        ),
    )


def golden_age_map_target_key(unit: Any, target: dict[str, Any]) -> tuple[str, int, int]:
    unit_id = value_from(unit, "unit_id", value_from(unit, "id", "?"))
    return (
        str(unit_id),
        int(target.get("x", -999999)),
        int(target.get("y", -999999)),
    )


def remember_blocked_golden_age_map_target(
    recorder: Any,
    unit: Any,
    target: dict[str, Any] | None,
    turn: int,
) -> None:
    if not target or not hasattr(recorder, "blocked_map_targets"):
        return
    recorder.blocked_map_targets[golden_age_map_target_key(unit, target)] = int(turn)


def golden_age_map_target_is_blocked(
    recorder: Any,
    unit: Any,
    target: dict[str, Any],
    turn: int,
) -> bool:
    if not hasattr(recorder, "blocked_map_targets"):
        return False
    last_blocked_turn = recorder.blocked_map_targets.get(
        golden_age_map_target_key(unit, target)
    )
    if last_blocked_turn is None:
        return False
    return (
        int(turn) - int(last_blocked_turn)
        <= GOLDEN_AGE_PUSH_BLOCKED_MAP_TARGET_COOLDOWN_TURNS
    )


def filter_blocked_golden_age_map_targets(
    recorder: Any,
    unit: Any,
    targets: list[dict[str, Any]],
    turn: int,
) -> list[dict[str, Any]]:
    return [
        target
        for target in targets
        if not golden_age_map_target_is_blocked(recorder, unit, target, turn)
    ]


def movement_result_is_blocked(result: Any) -> bool:
    text = str(result or "").upper()
    return "BLOCKED" in text or "STACKING_CONFLICT" in text


async def golden_age_map_target_for_unit(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    unit: Any,
    snapshot: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    if not uses_golden_age_push_runtime(recorder):
        return None, None
    if not snapshot_is_ancient_era(snapshot):
        return None, None
    gap = era_score_gap(snapshot)
    if gap is None or gap <= 0:
        return None, None
    if not hasattr(gs, "get_map_area"):
        return None, None
    unit_type = str(value_from(unit, "unit_type", "") or "")
    if unit_type not in {
        "UNIT_SCOUT",
        "UNIT_WARRIOR",
        "UNIT_SLINGER",
        "UNIT_ARCHER",
        "UNIT_HORSEMAN",
    }:
        return None, None
    try:
        center_x = int(value_from(unit, "x", 0))
        center_y = int(value_from(unit, "y", 0))
        call_id, tiles = await recorder.tool_call(
            "get_map_area",
            {
                "center_x": center_x,
                "center_y": center_y,
                "radius": GOLDEN_AGE_PUSH_MAP_TARGET_SCAN_RADIUS,
                "reason": "golden_age_map_target_scan",
            },
            lambda center_x=center_x, center_y=center_y: gs.get_map_area(
                center_x,
                center_y,
                GOLDEN_AGE_PUSH_MAP_TARGET_SCAN_RADIUS,
            ),
            turn=turn,
        )
    except Exception as exc:  # noqa: BLE001
        recorder.add_gap(
            f"units.golden_age_map_target.{value_from(unit, 'unit_id', '?')}",
            f"{type(exc).__name__}: {exc}",
            "Repair get_map_area target scans before relying on camp/village routing for golden-age pushes.",
        )
        return None, None
    targets = filter_blocked_golden_age_map_targets(
        recorder,
        unit,
        ranked_golden_age_map_targets_for_unit(unit, list(tiles or [])),
        turn,
    )
    return (call_id, targets[0]) if targets else (None, None)


def threat_distance_from_unit(unit: Any, threat: Any) -> int:
    try:
        return max(
            abs(int(value_from(threat, "x")) - int(value_from(unit, "x"))),
            abs(int(value_from(threat, "y")) - int(value_from(unit, "y"))),
        )
    except (TypeError, ValueError):
        return 999


def nearest_barbarian_threat_for_unit(unit: Any, threats: list[Any]) -> dict[str, Any] | None:
    barbarian_threats = [threat for threat in threats if threat_is_barbarian(threat)]
    if not barbarian_threats:
        return None
    threat = sorted(
        barbarian_threats,
        key=lambda item: (
            threat_distance_from_unit(unit, item),
            int(value_from(item, "hp", 999) or 999),
        ),
    )[0]
    return {
        "x": int(value_from(threat, "x")),
        "y": int(value_from(threat, "y")),
        "threat": threat,
        "distance": threat_distance_from_unit(unit, threat),
        "is_barbarian": True,
    }


def nearest_barbarian_threat_distance_for_unit(unit: Any, threats: list[Any]) -> int:
    target = nearest_barbarian_threat_for_unit(unit, threats)
    if target is None:
        return 999
    return int(target.get("distance", 999))


def should_risk_golden_age_settler_move(
    recorder: Any,
    snapshot: dict[str, Any],
    unit: Any,
    turn: int,
) -> bool:
    if not uses_golden_age_push_runtime(recorder):
        return False
    if not snapshot_is_ancient_era(snapshot):
        return False
    if golden_age_achieved(snapshot):
        return False
    if turn < GOLDEN_AGE_PUSH_URGENT_SETTLER_MOVE_TURN:
        return False
    nearest_distance = nearest_barbarian_threat_distance_for_unit(
        unit, list(snapshot.get("threats") or [])
    )
    return nearest_distance > GOLDEN_AGE_PUSH_SETTLER_ADJACENT_BARBARIAN_DISTANCE


def ranged_reposition_target(unit: Any, target: dict[str, Any]) -> tuple[int, int]:
    unit_x = int(value_from(unit, "x", target["x"]) or target["x"])
    unit_y = int(value_from(unit, "y", target["y"]) or target["y"])
    dx = unit_x - int(target["x"])
    dy = unit_y - int(target["y"])
    step_x = 1 if dx > 0 else -1 if dx < 0 else 0
    step_y = 1 if dy > 0 else -1 if dy < 0 else 0
    if step_x == 0 and step_y == 0:
        step_y = 1
    return unit_x + step_x, unit_y + step_y


def target_matches_map_event(
    target: dict[str, Any] | None,
    map_target: dict[str, Any] | None,
    event_key: str | None = None,
) -> bool:
    if not target or not map_target:
        return False
    if event_key and str(map_target.get("event_key") or "") != event_key:
        return False
    return int(target.get("x", 999999)) == int(map_target.get("x", -999999)) and int(
        target.get("y", 999999)
    ) == int(map_target.get("y", -999999))


def prioritize_golden_age_attack_targets(
    attack_targets: list[dict[str, Any]],
    map_target: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not map_target:
        return attack_targets
    return sorted(
        attack_targets,
        key=lambda target: (
            0 if target_matches_map_event(target, map_target, "clear_barbarian_camp") else 1,
            attack_targets.index(target),
        ),
    )


def should_attack_adjacent_ranged_target(
    recorder: Any,
    target: dict[str, Any],
    map_target: dict[str, Any] | None,
) -> bool:
    if not uses_golden_age_push_runtime(recorder):
        return False
    if not target.get("is_barbarian"):
        return False
    if target_matches_map_event(target, map_target, "clear_barbarian_camp"):
        return True
    return int(target.get("hp", 999) or 999) <= 45


def should_attack_critical_target_while_wounded(
    recorder: Any,
    target: dict[str, Any],
    map_target: dict[str, Any] | None,
) -> bool:
    return should_attack_adjacent_ranged_target(recorder, target, map_target)


def should_move_to_critical_map_target_while_wounded(
    recorder: Any,
    unit: Any,
    map_target: dict[str, Any] | None,
) -> bool:
    if not uses_golden_age_push_runtime(recorder) or not map_target:
        return False
    if str(map_target.get("event_key") or "") not in {"tribal_village", "natural_wonder"}:
        return False
    if str(value_from(unit, "unit_type", "") or "") != "UNIT_SCOUT":
        return False
    return int(map_target.get("distance", 999) or 999) <= 1


def at_war_player_ids(diplomacy: list[Any] | None) -> set[int]:
    ids: set[int] = set()
    for civ in diplomacy or []:
        if not value_from(civ, "is_at_war", False):
            continue
        player_id = value_from(civ, "player_id", None)
        if player_id is None:
            continue
        ids.add(int(player_id))
    return ids


def high_confidence_attack_window(unit: Any, threat: Any) -> bool:
    attacker_strength = combat_strength_for_tactical_estimate(unit)
    defender_strength = combat_strength_for_tactical_estimate(threat)
    defender_hp = int(number_from(threat, "hp", 100))
    if attacker_strength <= 0 or defender_strength <= 0:
        return False
    margin = attacker_strength - defender_strength
    attacker_hp = int(number_from(unit, "health", 100))
    if unit_is_ranged_clearer(unit):
        return margin >= 0 or defender_hp <= 45
    if attacker_hp < 60:
        return margin >= 0 and defender_hp <= 30
    return margin >= 0 or (margin >= -5 and defender_hp <= 45)


def high_confidence_attack_target(unit: Any, threat: Any, target: dict[str, Any]) -> bool:
    attacker_strength = combat_strength_for_tactical_estimate(unit)
    defender_strength = combat_strength_for_tactical_estimate(threat)
    defender_hp = int(number_from(threat, "hp", target.get("hp", 100)))
    target_hp = int(target.get("hp", defender_hp) or defender_hp)
    defender_hp = min(defender_hp, target_hp)
    if attacker_strength <= 0 or defender_strength <= 0:
        return False
    margin = attacker_strength - defender_strength
    attacker_hp = int(number_from(unit, "health", 100))
    if unit_is_ranged_clearer(unit):
        return margin >= 0 or defender_hp <= 45
    if attacker_hp < 60:
        return margin >= 0 and defender_hp <= 30
    return margin >= 0 or (margin >= -5 and defender_hp <= 45)


def is_high_confidence_war_target(
    recorder: Any,
    unit: Any,
    threat: Any,
    diplomacy: list[Any] | None,
) -> bool:
    if threat is None or threat_is_barbarian(threat):
        return False
    if value_from(threat, "is_city_state", False):
        return False
    owner_id = int(number_from(threat, "owner_id", -1))
    if owner_id not in at_war_player_ids(diplomacy):
        return False
    if not uses_golden_age_push_runtime(recorder):
        return False
    return high_confidence_attack_window(unit, threat)


def nearest_war_threat_for_unit(
    recorder: Any,
    unit: Any,
    threats: list[Any],
    diplomacy: list[Any] | None,
) -> dict[str, Any] | None:
    if str(value_from(unit, "unit_type", "") or "") not in BARBARIAN_CLEARING_UNIT_TYPES:
        return None
    if not uses_golden_age_push_runtime(recorder):
        return None
    war_ids = at_war_player_ids(diplomacy)
    if not war_ids:
        return None
    candidates = [
        threat
        for threat in threats
        if int(number_from(threat, "owner_id", -1)) in war_ids
        and not threat_is_barbarian(threat)
        and not value_from(threat, "is_city_state", False)
    ]
    if not candidates:
        return None
    threat = sorted(
        candidates,
        key=lambda item: (
            threat_distance_from_unit(unit, item),
            int(number_from(item, "hp", 999)),
        ),
    )[0]
    distance = threat_distance_from_unit(unit, threat)
    if distance > 4:
        return None
    return {
        "x": int(value_from(threat, "x")),
        "y": int(value_from(threat, "y")),
        "threat": threat,
        "distance": distance,
        "is_opportunistic_war": True,
    }


def ranked_attack_targets_for_unit(
    recorder: Any,
    unit: Any,
    threats: list[Any],
    turn: int,
    diplomacy: list[Any] | None = None,
) -> list[dict[str, Any]]:
    unit_type = str(value_from(unit, "unit_type", "") or "")
    if unit_type not in BARBARIAN_CLEARING_UNIT_TYPES:
        return []
    parsed_targets = [
        target
        for raw in (value_from(unit, "targets", []) or [])
        if (target := parse_attack_target(str(raw))) is not None
    ]
    ranked: list[dict[str, Any]] = []
    for target in parsed_targets:
        threat = threat_at(threats, target["x"], target["y"])
        is_barb = bool(threat and threat_is_barbarian(threat))
        is_barb_attack_target = is_barb and uses_barbarian_clearance_runtime(recorder)
        if is_barb_attack_target and uses_golden_age_push_runtime(recorder):
            is_barb_attack_target = high_confidence_attack_target(unit, threat, target)
        is_war_target = is_high_confidence_war_target(recorder, unit, threat, diplomacy)
        is_horseman_pressure = (
            unit_type == "UNIT_HORSEMAN"
            and turn >= HORSEMAN_PRESSURE_START_TURN
            and uses_horseman_pressure_runtime(recorder)
            and not (threat and value_from(threat, "is_city_state", False))
            and high_confidence_attack_window(unit, threat)
        )
        if not (
            is_barb_attack_target
            or is_horseman_pressure
            or is_war_target
        ):
            continue
        target["threat"] = threat
        target["is_barbarian"] = is_barb
        target["is_opportunistic_war"] = is_war_target or is_horseman_pressure and not is_barb
        target["estimated_margin"] = (
            combat_strength_for_tactical_estimate(unit)
            - combat_strength_for_tactical_estimate(threat)
            if threat is not None
            else None
        )
        target["adjacent_to_ranged_unit"] = unit_is_ranged_clearer(unit) and target_is_adjacent_to_unit(
            unit, target
        )
        target["distance"] = (
            value_from(threat, "distance", None)
            if threat is not None
            else abs(target["x"] - int(value_from(unit, "x", target["x"]) or target["x"]))
            + abs(target["y"] - int(value_from(unit, "y", target["y"]) or target["y"]))
        )
        ranked.append(target)
    return sorted(
        ranked,
        key=lambda target: (
            0 if target.get("is_barbarian") else 1,
            0 if target.get("is_opportunistic_war") else 1,
            -(target.get("estimated_margin") or 0),
            target.get("hp", 999),
            target.get("distance", 999),
        ),
    )


BUILDER_TASK_PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2}
EARLY_UNRELIABLE_BUILDER_IMPROVEMENTS = {"IMPROVEMENT_LUMBER_MILL"}


def builder_task_resource_rank(task: Any) -> int:
    resource = strategic_resource_key(value_from(task, "resource", ""))
    resource_class = str(value_from(task, "resource_class", "") or "").lower()
    if resource in {"HORSES", "IRON"}:
        return 0
    if resource_class == "strategic":
        return 1
    if resource_class in {"luxury", "bonus", "pillaged"}:
        return 2
    return 3


def builder_task_is_usable_now(task: Any, unit: Any) -> bool:
    improvement = str(value_from(task, "improvement", "") or "")
    if not unit_can_build_improvement(unit, improvement):
        return False
    resource = strategic_resource_key(value_from(task, "resource", ""))
    resource_class = str(value_from(task, "resource_class", "") or "").lower()
    if improvement in EARLY_UNRELIABLE_BUILDER_IMPROVEMENTS and not (
        resource or resource_class == "strategic"
    ):
        return False
    return True


def ranked_builder_tasks_for_unit(
    tasks: list[Any],
    unit: Any,
    prefer_strategic: bool = False,
) -> list[Any]:
    unit_id = value_from(unit, "unit_id", None)

    def task_rank(task: Any) -> tuple[int, int, int, float]:
        nearest = value_from(task, "nearest_builder_id", None)
        priority = str(value_from(task, "priority", "") or "")
        distance = value_from(task, "distance", 999) or 999
        priority_rank = BUILDER_TASK_PRIORITY_RANK.get(priority, 3)
        resource_rank = builder_task_resource_rank(task)
        secondary_rank, tertiary_rank = (
            (resource_rank, priority_rank)
            if prefer_strategic
            else (priority_rank, resource_rank)
        )
        return (
            0 if nearest == unit_id else 1,
            secondary_rank,
            tertiary_rank,
            float(distance),
        )

    return sorted(tasks, key=task_rank)


TRADE_YIELD_WEIGHTS = {
    "Food": 4.0,
    "Prod": 5.0,
    "Gold": 2.0,
    "Sci": 6.0,
    "Cul": 4.0,
    "Faith": 1.0,
}


def trade_yield_score(text: str) -> float:
    score = 0.0
    for name, raw_value in re.findall(
        r"(Food|Prod|Gold|Sci|Cul|Faith):([0-9]+(?:\.[0-9]+)?)", text or ""
    ):
        score += TRADE_YIELD_WEIGHTS.get(name, 1.0) * float(raw_value)
    return score


def trade_destination_score(destination: Any) -> tuple[float, str, int, int]:
    origin_score = trade_yield_score(str(getattr(destination, "origin_yields", "") or ""))
    destination_score = trade_yield_score(str(getattr(destination, "dest_yields", "") or ""))
    score = origin_score + destination_score
    if getattr(destination, "has_quest", False):
        score += 1000.0
    if getattr(destination, "is_domestic", False):
        score += 100.0
    if getattr(destination, "has_trading_post", False):
        score += 10.0
    return (
        -score,
        str(getattr(destination, "city_name", "")),
        int(getattr(destination, "x", 0)),
        int(getattr(destination, "y", 0)),
    )


def ranked_trade_destinations(destinations: list[Any]) -> list[Any]:
    return sorted(destinations, key=trade_destination_score)


def trader_is_already_on_route(trade_routes: Any, unit: Any) -> bool:
    for trader in getattr(trade_routes, "traders", []) or []:
        if not getattr(trader, "on_route", False):
            continue
        trader_id = getattr(trader, "unit_id", None)
        if trader_id in {
            getattr(unit, "unit_id", None),
            getattr(unit, "unit_index", None),
        }:
            return True
    return False


def religion_slots_open(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    overview = snapshot.get("overview") or {}
    if value_from(overview, "our_religion", None):
        return False
    founded = int(number_from(overview, "religions_founded", 0))
    max_slots = int(number_from(overview, "religions_max", 0))
    return max_slots <= 0 or founded < max_slots


def choose_belief_by_priority(beliefs: list[Any], priority: list[str]) -> Any | None:
    return choose_by_priority(beliefs, "belief_type", priority) or (beliefs[0] if beliefs else None)


def preferred_religion_type(status: Any) -> str | None:
    religions = list(value_from(status, "available_religions", []) or [])
    for preferred in GOLDEN_AGE_PUSH_RELIGION_PRIORITY:
        for religion_type, _religion_name in religions:
            if religion_type == preferred:
                return religion_type
    return religions[0][0] if religions else None


def preferred_founder_belief(status: Any) -> str | None:
    founder_beliefs = list(
        value_from(status, "beliefs_by_class", {}).get("BELIEF_CLASS_FOUNDER", [])
        if value_from(status, "beliefs_by_class", None)
        else []
    )
    selected = choose_belief_by_priority(
        founder_beliefs, GOLDEN_AGE_PUSH_FOUNDER_BELIEF_PRIORITY
    )
    return value_from(selected, "belief_type", None) if selected else None


def choral_music_available(status: Any) -> bool:
    follower_beliefs = list(
        value_from(status, "beliefs_by_class", {}).get("BELIEF_CLASS_FOLLOWER", [])
        if value_from(status, "beliefs_by_class", None)
        else []
    )
    return any(
        value_from(belief, "belief_type", None) == GOLDEN_AGE_PUSH_FOLLOWER_BELIEF
        for belief in follower_beliefs
    )


def unit_is_great_prophet(unit: Any) -> bool:
    unit_type = str(value_from(unit, "unit_type", "") or "").upper()
    return unit_type in {"UNIT_GREAT_PROPHET", "UNIT_PROPHET"} or "PROPHET" in unit_type


def snapshot_has_great_prophet_unit(snapshot: dict[str, Any] | None) -> bool:
    return any(unit_is_great_prophet(unit) for unit in (snapshot or {}).get("units") or [])


def great_person_is_prophet(great_person: Any) -> bool:
    name = str(value_from(great_person, "class_name", "") or "").lower()
    return "prophet" in name or "预言" in name or "先知" in name


POLICY_PRIORITY_BY_SLOT = {
    "SLOT_MILITARY": [
        "POLICY_AGOGE",
        "POLICY_DISCIPLINE",
        "POLICY_MANEUVER",
        "POLICY_SURVEY",
        "POLICY_CONSCRIPTION",
    ],
    "SLOT_ECONOMIC": [
        "POLICY_URBAN_PLANNING",
        "POLICY_COLONIZATION",
        "POLICY_ILKUM",
        "POLICY_CARAVANSERIES",
        "POLICY_GOD_KING",
    ],
    "SLOT_DIPLOMATIC": [
        "POLICY_CHARISMATIC_LEADER",
        "POLICY_DIPLOMATIC_LEAGUE",
        "POLICY_LIMITANEI",
    ],
    "SLOT_WILDCARD": [
        "POLICY_URBAN_PLANNING",
        "POLICY_AGOGE",
        "POLICY_COLONIZATION",
        "POLICY_ILKUM",
        "POLICY_CHARISMATIC_LEADER",
    ],
    "SLOT_GREAT_PERSON": [
        "POLICY_URBAN_PLANNING",
        "POLICY_AGOGE",
        "POLICY_CHARISMATIC_LEADER",
    ],
}

GOVERNOR_PRIORITY = [
    "GOVERNOR_THE_EDUCATOR",
    "GOVERNOR_THE_BUILDER",
    "GOVERNOR_THE_RESOURCE_MANAGER",
    "GOVERNOR_THE_MERCHANT",
    "GOVERNOR_THE_AMBASSADOR",
]

ENVOY_CITY_STATE_TYPE_PRIORITY = [
    "SCIENTIFIC",
    "CULTURAL",
    "TRADE",
    "INDUSTRIAL",
    "MILITARISTIC",
    "RELIGIOUS",
]

DEDICATION_PRIORITY = [
    "COMMEMORATION_SCIENTIFIC",
    "COMMEMORATION_INFRASTRUCTURE",
    "COMMEMORATION_CULTURAL",
    "COMMEMORATION_RELIGIOUS",
    "COMMEMORATION_MILITARY",
]

PROMOTION_PRIORITY = [
    "PROMOTION_RANGER",
    "PROMOTION_ALPINE",
    "PROMOTION_GARRISON",
    "PROMOTION_VOLLEY",
    "PROMOTION_BATTLECRY",
    "PROMOTION_TORTOISE",
]


def policy_fits_slot(slot: Any, policy: Any) -> bool:
    slot_type = str(getattr(slot, "slot_type", "") or "")
    policy_slot_type = str(getattr(policy, "slot_type", "") or "")
    if slot_type in {"SLOT_WILDCARD", "SLOT_GREAT_PERSON"}:
        return True
    return policy_slot_type in {slot_type, "SLOT_WILDCARD"}


def priority_index(value: str, priority: list[str]) -> int:
    try:
        return priority.index(value)
    except ValueError:
        return len(priority)


def policy_assignments_for_empty_slots(status: Any) -> dict[int, str]:
    slots = list(getattr(status, "slots", []) or [])
    policies = list(getattr(status, "available_policies", []) or [])
    used = {
        str(getattr(slot, "current_policy", "") or "")
        for slot in slots
        if getattr(slot, "current_policy", None)
    }
    assignments: dict[int, str] = {}
    for slot in sorted(slots, key=lambda item: int(getattr(item, "slot_index", 0))):
        if getattr(slot, "current_policy", None):
            continue
        slot_type = str(getattr(slot, "slot_type", "") or "SLOT_WILDCARD")
        priority = POLICY_PRIORITY_BY_SLOT.get(slot_type, POLICY_PRIORITY_BY_SLOT["SLOT_WILDCARD"])
        candidates = [
            policy
            for policy in policies
            if str(getattr(policy, "policy_type", "") or "") not in used
            and policy_fits_slot(slot, policy)
        ]
        if not candidates:
            continue
        selected = sorted(
            candidates,
            key=lambda policy: (
                priority_index(str(getattr(policy, "policy_type", "") or ""), priority),
                str(getattr(policy, "policy_type", "") or ""),
            ),
        )[0]
        policy_type = str(getattr(selected, "policy_type", "") or "")
        if policy_type:
            assignments[int(getattr(slot, "slot_index", 0))] = policy_type
            used.add(policy_type)
    return assignments


def first_by_priority(items: list[Any], attr: str, priority: list[str]) -> Any | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            priority_index(str(getattr(item, attr, "") or ""), priority),
            str(getattr(item, attr, "") or ""),
        ),
    )[0]


def governor_is_assigned(governor: Any) -> bool:
    city_id = int(number_from(governor, "assigned_city_id", -1))
    city_name = str(value_from(governor, "assigned_city_name", "") or "")
    return city_id >= 0 and city_name.upper() not in {"", "NONE", "UNASSIGNED"}


def governor_assignment_target(cities: list[Any], governor_type: str) -> Any | None:
    if not cities:
        return None
    if governor_type == "GOVERNOR_THE_EDUCATOR":
        return sorted(
            cities,
            key=lambda city: (
                number_from(city, "science", 0) + number_from(city, "culture", 0),
                number_from(city, "population", 0),
                number_from(city, "production", 0),
            ),
            reverse=True,
        )[0]
    if governor_type in {"GOVERNOR_THE_BUILDER", "GOVERNOR_THE_RESOURCE_MANAGER"}:
        return sorted(
            cities,
            key=lambda city: (
                number_from(city, "production", 0),
                len(value_from(city, "unimproved_resources", []) or []),
                number_from(city, "population", 0),
            ),
            reverse=True,
        )[0]
    return sorted(
        cities,
        key=lambda city: (
            number_from(city, "population", 0),
            number_from(city, "science", 0) + number_from(city, "culture", 0),
        ),
        reverse=True,
    )[0]


async def assign_governor_with_record(
    recorder: EpisodeRecorder,
    gs: GameState,
    *,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
    governor_type: str,
    trigger: str,
    existing_tool_call_ids: list[str] | None = None,
    appointment_result: Any | None = None,
) -> bool:
    cities = list(snapshot.get("cities") or [])
    target_city = governor_assignment_target(cities, governor_type)
    if target_city is None:
        recorder.add_gap(
            f"governance.governor_assignment.{governor_type}",
            "Governor is available but no city snapshot is available for assignment.",
            "Repair city snapshot coverage before governor assignment becomes a T50 blocker.",
        )
        return False
    city_id = int(value_from(target_city, "city_id", -1))
    city_name = str(value_from(target_city, "name", city_id))
    if city_id < 0:
        recorder.add_gap(
            f"governance.governor_assignment.{governor_type}",
            f"Selected city {city_name} has no valid city_id.",
            "Repair get_cities city_id coverage before assigning governors.",
        )
        return False
    assign_id, result = await recorder.tool_call(
        "assign_governor",
        {"governor_type": governor_type, "city_id": city_id, "city_name": city_name},
        lambda governor_type=governor_type, city_id=city_id: gs.assign_governor(
            governor_type, city_id
        ),
        turn=turn,
    )
    related = [*(existing_tool_call_ids or []), assign_id]
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": trigger,
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Place newly appointed or unassigned governors immediately so T50 snapshots can verify city != NONE.",
            "available_actions": [
                f"assign {governor_type} to {value_from(city, 'name', value_from(city, 'city_id', '?'))}"
                for city in cities
            ],
            "selected_action": f"assign {governor_type} to {city_name}",
            "rationale": (
                "Pingala goes to the highest science/culture city; Liang or Magnus goes to the city with the strongest production/resource pressure."
            ),
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "leave governor unassigned": "The current T50 plan treats city == NONE as a strategy failure to verify in snapshots.",
                "assign to lower-ranked city": "Lower current science/culture or production/resource pressure.",
            },
            "execution": {
                "tool": "assign_governor",
                "governor_type": governor_type,
                "city_id": city_id,
                "city_name": city_name,
                "appointment_result": appointment_result,
                "result": result,
            },
            "outcome": short_text(result),
            "related_tool_call_ids": related,
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )
    return not str(result).startswith(("Error", "ERR", "FAILED"))


def notification_text_rows(snapshot: dict[str, Any]) -> list[str]:
    raw_notifications = snapshot.get("notifications")
    if isinstance(raw_notifications, str):
        return [raw_notifications]
    rows: list[str] = []
    for notification in raw_notifications or []:
        type_name = str(value_from(notification, "type_name", "") or "")
        message = str(value_from(notification, "message", "") or "")
        rows.append(" ".join(part for part in [type_name, message] if part))
    if not rows and raw_notifications:
        rows.append(str(raw_notifications or ""))
    return rows


def snapshot_notification_text(snapshot: dict[str, Any]) -> str:
    return " ".join(notification_text_rows(snapshot))


def snapshot_mentions_any(snapshot: dict[str, Any], terms: list[str]) -> bool:
    text = snapshot_notification_text(snapshot).lower()
    return any(term.lower() in text for term in terms)


def snapshot_envoy_tokens_available(snapshot: dict[str, Any] | None) -> int:
    if not snapshot:
        return 0
    agent = snapshot_agent_empire_row(snapshot)
    values = [
        number_from(agent, "envoys_available", 0) if agent is not None else 0,
        number_from(snapshot.get("overview") or {}, "envoys_available", 0),
    ]
    return max(int(value) for value in values)


def should_handle_envoy_opportunity(snapshot: dict[str, Any]) -> bool:
    return snapshot_envoy_tokens_available(snapshot) > 0 or snapshot_mentions_any(
        snapshot,
        [
            "envoy",
            "influence",
            "GIVE_INFLUENCE_TOKEN",
            "INFLUENCE_TOKEN",
            "city-state",
            "城邦",
            "使者",
            "影响力",
        ],
    )


def ranked_envoy_targets(status: Any) -> list[Any]:
    targets = [
        city_state
        for city_state in list(value_from(status, "city_states", []) or [])
        if bool(value_from(city_state, "can_send_envoy", False))
    ]

    def rank(city_state: Any) -> tuple[int, int, str]:
        city_state_type = str(value_from(city_state, "city_state_type", "") or "").upper()
        priority = len(ENVOY_CITY_STATE_TYPE_PRIORITY)
        for index, token in enumerate(ENVOY_CITY_STATE_TYPE_PRIORITY):
            if token in city_state_type:
                priority = index
                break
        return (
            priority,
            int(number_from(city_state, "envoys_sent", 0)),
            str(value_from(city_state, "name", "") or ""),
        )

    return sorted(targets, key=rank)


def split_resource_snapshot(resources: Any) -> tuple[list[Any], list[Any], list[Any], dict[str, int]]:
    if isinstance(resources, tuple) and len(resources) >= 4:
        stockpiles, owned, nearby, luxuries = resources[:4]
        return list(stockpiles or []), list(owned or []), list(nearby or []), dict(luxuries or {})
    return [], [], [], {}


def resource_type_for_trade(name: str) -> str:
    cleaned = str(name or "").strip().upper().replace(" ", "_")
    if not cleaned:
        return ""
    return cleaned if cleaned.startswith("RESOURCE_") else f"RESOURCE_{cleaned}"


def strategic_stockpile_rows(resources: Any) -> list[dict[str, Any]]:
    stockpiles, _owned, _nearby, _luxuries = split_resource_snapshot(resources)
    rows: list[dict[str, Any]] = []
    for stock in stockpiles:
        amount = int(number_from(stock, "amount", 0))
        per_turn = int(number_from(stock, "per_turn", 0))
        demand = int(number_from(stock, "demand", 0))
        rows.append(
            {
                "name": value_from(stock, "name", ""),
                "amount": amount,
                "cap": int(number_from(stock, "cap", 0)),
                "per_turn": per_turn,
                "demand": demand,
                "imported": int(number_from(stock, "imported", 0)),
                "net_per_turn": per_turn - demand,
                "surplus_after_reserve": amount
                - GOLDEN_AGE_PUSH_RESOURCE_TRADE_RESERVE.get(
                    str(value_from(stock, "name", "") or "").upper(),
                    0,
                ),
            }
        )
    return rows


def strategic_resource_income_by_key(resources: Any) -> dict[str, int]:
    income: dict[str, int] = {}
    for row in strategic_stockpile_rows(resources):
        key = strategic_resource_key(row.get("name"))
        income[key] = income.get(key, 0) + int(row.get("net_per_turn") or 0)
    return income


def unimproved_strategic_resources(resources: Any) -> list[dict[str, Any]]:
    _stockpiles, owned, _nearby, _luxuries = split_resource_snapshot(resources)
    rows: list[dict[str, Any]] = []
    for resource in owned:
        if value_from(resource, "resource_class") != "strategic" or value_from(
            resource, "improved", False
        ):
            continue
        rows.append(
            {
                "name": value_from(resource, "name", ""),
                "x": value_from(resource, "x"),
                "y": value_from(resource, "y"),
            }
        )
    return rows


def nearby_strategic_resources(resources: Any) -> list[dict[str, Any]]:
    _stockpiles, _owned, nearby, _luxuries = split_resource_snapshot(resources)
    rows: list[dict[str, Any]] = []
    for resource in nearby:
        name = value_from(resource, "name", value_from(resource, "resource", ""))
        resource_key = strategic_resource_key(name)
        resource_class = str(value_from(resource, "resource_class", "") or "").lower()
        if resource_class != "strategic" and resource_key not in GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY:
            continue
        rows.append(
            {
                "name": name,
                "resource_key": resource_key,
                "x": value_from(resource, "x"),
                "y": value_from(resource, "y"),
                "distance": value_from(resource, "distance", None),
            }
        )
    return rows


def strategic_resource_development_path_available(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    resources = snapshot.get("resources")
    if unimproved_strategic_resources(resources) or nearby_strategic_resources(resources):
        return True
    income = strategic_resource_income_by_key(resources)
    return any(income.get(resource, 0) > 0 for resource in GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY)


def ancient_strategic_resource_push_active(
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> bool:
    if not snapshot:
        return False
    if not snapshot_is_ancient_era(snapshot) or golden_age_achieved(snapshot):
        return False
    if (era_score_gap(snapshot) or 0) <= 0:
        return False
    if snapshot_turn(snapshot) < GOLDEN_AGE_PUSH_ANCIENT_STRATEGIC_RESOURCE_START_TURN:
        return False
    if snapshot_unit_count(snapshot, "UNIT_HORSEMAN", extra_units) > 0:
        return False
    city_count = snapshot_city_count(snapshot)
    settler_count = snapshot_unit_count(snapshot, "UNIT_SETTLER", extra_units)
    resources = snapshot.get("resources")
    if city_count < 2 and settler_count == 0 and not unimproved_strategic_resources(resources):
        return False
    return strategic_resource_development_path_available(snapshot)


def ancient_strategic_builder_needed(
    snapshot: dict[str, Any] | None,
    extra_units: dict[str, int] | None = None,
) -> bool:
    if not ancient_strategic_resource_push_active(snapshot, extra_units):
        return False
    resources = snapshot.get("resources") if snapshot else None
    if not (unimproved_strategic_resources(resources) or nearby_strategic_resources(resources)):
        return False
    return snapshot_unit_count(snapshot, "UNIT_BUILDER", extra_units) == 0


def ancient_post_settle_builder_reserve_active(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    if not snapshot_is_ancient_era(snapshot) or golden_age_achieved(snapshot):
        return False
    if (era_score_gap(snapshot) or 0) <= 0:
        return False
    turn = snapshot_turn(snapshot)
    if (
        turn < GOLDEN_AGE_PUSH_ANCIENT_STRATEGIC_RESOURCE_START_TURN
        or turn > GOLDEN_AGE_PUSH_URGENT_SETTLER_MOVE_TURN
    ):
        return False
    if snapshot_unit_count(snapshot, "UNIT_SETTLER") <= 0:
        return False
    if snapshot_unit_count(snapshot, "UNIT_BUILDER") > 0:
        return False
    if snapshot_unit_count(snapshot, "UNIT_HORSEMAN") > 0:
        return False
    resources = snapshot.get("resources")
    income = strategic_resource_income_by_key(resources)
    if any(income.get(resource, 0) > 0 for resource in GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY):
        return False
    stockpiles = strategic_stockpile_rows(resources)
    return any(
        strategic_resource_key(value_from(row, "name", ""))
        in GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY
        for row in stockpiles
    )


def builder_purchase_affordable(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    gold = number_from(snapshot.get("overview") or {}, "gold", 0)
    for options in (snapshot.get("production") or {}).values():
        for option in options or []:
            if str(value_from(option, "category", "") or "") != "UNIT":
                continue
            if str(value_from(option, "item_name", "") or "") != "UNIT_BUILDER":
                continue
            cost = int(number_from(option, "gold_cost", -1))
            if 0 <= cost <= gold:
                return True
    return False


def strategic_builder_purchase_shortfall(snapshot: dict[str, Any]) -> int | None:
    if not (
        ancient_strategic_builder_needed(snapshot)
        or ancient_post_settle_builder_reserve_active(snapshot)
    ):
        return None
    gold = number_from(snapshot.get("overview") or {}, "gold", 0)
    costs: list[int] = []
    for options in (snapshot.get("production") or {}).values():
        for option in options or []:
            if str(value_from(option, "category", "") or "") != "UNIT":
                continue
            if str(value_from(option, "item_name", "") or "") != "UNIT_BUILDER":
                continue
            cost = int(number_from(option, "gold_cost", -1))
            if cost > gold:
                costs.append(cost)
    return min(costs) if costs else None


def builder_task_is_strategic_resource(task: Any) -> bool:
    return builder_task_resource_rank(task) <= 1


def governor_audit_rows(governors: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for governor in list(value_from(governors, "appointed", []) or []):
        city_id = int(number_from(governor, "assigned_city_id", -1))
        city_name = str(value_from(governor, "assigned_city_name", "") or "")
        rows.append(
            {
                "governor_type": value_from(governor, "governor_type", ""),
                "name": value_from(governor, "name", ""),
                "city_id": city_id,
                "city": city_name if city_id >= 0 else "NONE",
                "assigned": city_id >= 0 and city_name.upper() not in {"", "NONE", "UNASSIGNED"},
                "is_established": bool(value_from(governor, "is_established", False)),
                "turns_to_establish": int(number_from(governor, "turns_to_establish", 0)),
            }
        )
    return rows


def civ_available_actions(civ: Any) -> list[str]:
    return [str(action or "") for action in (value_from(civ, "available_actions", []) or [])]


def can_declare_war_on(civ: Any) -> bool:
    return any("DECLARE" in action.upper() and "WAR" in action.upper() for action in civ_available_actions(civ))


GOLDEN_AGE_TARGET_EVENT_DEFINITIONS = [
    {
        "event_key": "clear_barbarian_camp",
        "priority": 1,
        "label": "Clear barbarian camp or nearby barbarian pressure",
        "action_hint": "Move combat units toward clearable barbarian targets; camp clear is the preferred era-score path.",
    },
    {
        "event_key": "meet_civilization",
        "priority": 2,
        "label": "Meet another civilization",
        "action_hint": "Keep scouts and safe combat units exploring until first-contact era score opportunities are exhausted.",
    },
    {
        "event_key": "tribal_village",
        "priority": 3,
        "label": "Claim tribal village",
        "action_hint": "Route the closest safe unit to any revealed tribal village notification or map marker.",
    },
    {
        "event_key": "natural_wonder",
        "priority": 4,
        "label": "Discover natural wonder",
        "action_hint": "Prefer exploration routes that reveal high-yield terrain and natural-wonder notifications.",
    },
    {
        "event_key": "first_new_era_tech_or_civic",
        "priority": 5,
        "label": "Finish first new-era technology or civic",
        "action_hint": "Keep science/culture progress moving while the golden-age gap remains open.",
    },
    {
        "event_key": "first_strategic_resource_unit",
        "priority": 6,
        "label": "Field first strategic-resource military unit",
        "action_hint": "Develop Horses/Iron, then buy, build, or upgrade into the first strategic military unit.",
    },
    {
        "event_key": "aggressive_neighbor_settlement",
        "priority": 7,
        "label": "Settle aggressively near a neighbor",
        "action_hint": "Use safe settler opportunities near contacted neighbors when expansion and loyalty are viable.",
    },
    {
        "event_key": "first_government_or_governor",
        "priority": 8,
        "label": "Complete first government or governor-related historic moment",
        "action_hint": "Resolve government, policy, appointment, and governor-assignment blockers immediately.",
    },
]


def text_mentions_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def golden_age_target_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    text = snapshot_notification_text(snapshot)
    resources = snapshot.get("resources")
    diplomacy = list(snapshot.get("diplomacy") or [])
    units = list(snapshot.get("units") or [])
    cities = list(snapshot.get("cities") or [])
    production = snapshot.get("production") or {}
    events: list[dict[str, Any]] = []

    def add(event_key: str, *, active: bool, evidence: list[str]) -> None:
        definition = next(
            item
            for item in GOLDEN_AGE_TARGET_EVENT_DEFINITIONS
            if item["event_key"] == event_key
        )
        events.append(
            {
                **definition,
                "active": active,
                "evidence": [item for item in evidence if item],
            }
        )

    barb_count = visible_barbarian_threat_count(snapshot)
    add(
        "clear_barbarian_camp",
        active=barb_count > 0 or text_mentions_any(text, ["barbarian", "camp", "outpost"]),
        evidence=[f"visible_barbarian_threats={barb_count}"],
    )
    met_civs = [civ for civ in diplomacy if value_from(civ, "has_met", False)]
    add(
        "meet_civilization",
        active=bool(met_civs) or text_mentions_any(text, ["met", "encountered", "civilization"]),
        evidence=[f"met_civilizations={len(met_civs)}"],
    )
    add(
        "tribal_village",
        active=text_mentions_any(text, ["tribal", "village", "goody hut"]),
        evidence=notification_text_rows(snapshot),
    )
    add(
        "natural_wonder",
        active=text_mentions_any(text, ["natural wonder", "wonder discovered"]),
        evidence=notification_text_rows(snapshot),
    )
    research_civic = snapshot.get("research_civic")
    completed_techs = int(number_from(research_civic, "completed_tech_count", 0))
    completed_civics = int(number_from(research_civic, "completed_civic_count", 0))
    add(
        "first_new_era_tech_or_civic",
        active=text_mentions_any(text, ["historic moment", "technology", "civic", "new era"])
        or completed_techs > 0
        or completed_civics > 0,
        evidence=[f"completed_techs={completed_techs}", f"completed_civics={completed_civics}"],
    )
    strategic_units = [
        unit
        for unit in units
        if str(value_from(unit, "unit_type", "") or "") in {"UNIT_HORSEMAN", "UNIT_SWORDSMAN"}
    ]
    purchasable_strategic_units = [
        value_from(option, "item_name", "")
        for options in production.values()
        for option in (options or [])
        if str(value_from(option, "item_name", "") or "") in {"UNIT_HORSEMAN", "UNIT_SWORDSMAN"}
    ]
    add(
        "first_strategic_resource_unit",
        active=bool(strategic_units)
        or bool(purchasable_strategic_units)
        or bool(unimproved_strategic_resources(resources))
        or bool(strategic_stockpile_rows(resources)),
        evidence=[
            f"strategic_units={len(strategic_units)}",
            f"purchasable_strategic_units={','.join(map(str, purchasable_strategic_units))}",
            f"unimproved_strategics={len(unimproved_strategic_resources(resources))}",
        ],
    )
    visible_neighbor_cities = sum(len(value_from(civ, "visible_cities", []) or []) for civ in met_civs)
    settler_count = sum(1 for unit in units if value_from(unit, "unit_type") == "UNIT_SETTLER")
    add(
        "aggressive_neighbor_settlement",
        active=visible_neighbor_cities > 0 and (settler_count > 0 or len(cities) < 4),
        evidence=[f"visible_neighbor_cities={visible_neighbor_cities}", f"settlers={settler_count}"],
    )
    add(
        "first_government_or_governor",
        active=text_mentions_any(text, ["government", "governor", "policy", "civic"])
        or any(not row["assigned"] for row in governor_audit_rows(snapshot.get("governors"))),
        evidence=[
            f"unassigned_governors={len([row for row in governor_audit_rows(snapshot.get('governors')) if not row['assigned']])}"
        ],
    )
    return sorted(events, key=lambda row: (int(row["priority"]), not bool(row["active"])))


def combat_strength_for_tactical_estimate(unit: Any) -> int:
    return max(
        int(number_from(unit, "combat_strength", 0)),
        int(number_from(unit, "ranged_strength", 0)),
    )


def favorable_attack_windows_for_civ(
    snapshot: dict[str, Any],
    civ: Any,
) -> list[dict[str, Any]]:
    player_id = int(number_from(civ, "player_id", -1))
    if player_id < 0:
        return []
    threats = list(snapshot.get("threats") or [])
    windows: list[dict[str, Any]] = []
    for unit in snapshot.get("units") or []:
        unit_type = str(value_from(unit, "unit_type", "") or "")
        if unit_type not in BARBARIAN_CLEARING_UNIT_TYPES:
            continue
        attacker_strength = combat_strength_for_tactical_estimate(unit)
        if attacker_strength <= 0:
            continue
        for raw in value_from(unit, "targets", []) or []:
            target = parse_attack_target(str(raw))
            if target is None:
                continue
            threat = threat_at(threats, int(target["x"]), int(target["y"]))
            if threat is None or int(number_from(threat, "owner_id", -1)) != player_id:
                continue
            defender_strength = combat_strength_for_tactical_estimate(threat)
            defender_hp = int(number_from(threat, "hp", target["hp"]))
            estimated_margin = attacker_strength - defender_strength
            if estimated_margin < -5 and defender_hp > 45:
                continue
            windows.append(
                {
                    "unit_id": value_from(unit, "unit_id"),
                    "unit_type": unit_type,
                    "target_unit_type": value_from(threat, "unit_type", ""),
                    "target_x": target["x"],
                    "target_y": target["y"],
                    "target_hp": defender_hp,
                    "attacker_strength": attacker_strength,
                    "defender_strength": defender_strength,
                    "estimated_margin": estimated_margin,
                }
            )
    return sorted(
        windows,
        key=lambda row: (
            -int(row["estimated_margin"]),
            int(row["target_hp"]),
            str(row["unit_type"]),
        ),
    )


def border_pressure_windows_for_civ(
    snapshot: dict[str, Any],
    civ: Any,
) -> list[dict[str, Any]]:
    units = [
        unit
        for unit in snapshot.get("units") or []
        if str(value_from(unit, "unit_type", "") or "") in BARBARIAN_CLEARING_UNIT_TYPES
    ]
    if not units:
        return []
    windows: list[dict[str, Any]] = []
    for city in value_from(civ, "visible_cities", []) or []:
        x = value_from(city, "x", None)
        y = value_from(city, "y", None)
        if x is None or y is None:
            continue
        city_defense = int(number_from(city, "defense_strength", 0))
        has_walls = bool(value_from(city, "has_walls", False))
        nearest = sorted(
            units,
            key=lambda unit: max(
                abs(int(number_from(unit, "x", 999)) - int(x)),
                abs(int(number_from(unit, "y", 999)) - int(y)),
            ),
        )[0]
        distance = max(
            abs(int(number_from(nearest, "x", 999)) - int(x)),
            abs(int(number_from(nearest, "y", 999)) - int(y)),
        )
        if distance > 4:
            continue
        if has_walls or city_defense > combat_strength_for_tactical_estimate(nearest) + 12:
            continue
        windows.append(
            {
                "city_name": value_from(city, "name", ""),
                "x": int(x),
                "y": int(y),
                "distance": distance,
                "defense_strength": city_defense,
                "has_walls": has_walls,
                "nearest_unit_id": value_from(nearest, "unit_id"),
                "nearest_unit_type": value_from(nearest, "unit_type", ""),
            }
        )
    return sorted(
        windows,
        key=lambda row: (
            int(row["distance"]),
            int(row["defense_strength"]),
            str(row["city_name"]),
        ),
    )


def t50_strategy_audit(snapshot: dict[str, Any]) -> dict[str, Any]:
    overview = snapshot.get("overview") or {}
    diplomacy = list(snapshot.get("diplomacy") or [])
    gap = era_score_gap(snapshot)
    governors = governor_audit_rows(snapshot.get("governors"))
    strategic_resources = strategic_stockpile_rows(snapshot.get("resources"))
    war_targets = [
        {
            "player_id": value_from(civ, "player_id"),
            "civ_name": value_from(civ, "civ_name", ""),
            "leader_name": value_from(civ, "leader_name", ""),
            "military_strength": value_from(civ, "military_strength", 0),
            "available_actions": civ_available_actions(civ),
            "favorable_attack_count": len(favorable_attack_windows_for_civ(snapshot, civ)),
            "border_pressure_count": len(border_pressure_windows_for_civ(snapshot, civ)),
        }
        for civ in diplomacy
        if value_from(civ, "has_met", False)
        and not value_from(civ, "is_at_war", False)
        and can_declare_war_on(civ)
    ]
    trade_targets = [
        {
            "player_id": value_from(civ, "player_id"),
            "civ_name": value_from(civ, "civ_name", ""),
            "leader_name": value_from(civ, "leader_name", ""),
            "diplomatic_state": value_from(civ, "diplomatic_state", ""),
        }
        for civ in diplomacy
        if value_from(civ, "has_met", False) and not value_from(civ, "is_at_war", False)
    ]
    opportunities = []
    target_events = golden_age_target_events(snapshot)
    if visible_barbarian_threat_count(snapshot) > 0:
        opportunities.append("clear_visible_barbarian")
    if war_targets:
        opportunities.append("opportunistic_neighbor_war")
    if unimproved_strategic_resources(snapshot.get("resources")):
        opportunities.append("improve_strategic_resource")
    if nearby_strategic_resources(snapshot.get("resources")):
        opportunities.append("claim_nearby_strategic_resource")
    if snapshot_mentions_any(snapshot, ["governor", "GOVERNOR"]):
        opportunities.append("governor_event")
    if should_handle_envoy_opportunity(snapshot):
        opportunities.append("send_envoy")
    if religion_slots_open(snapshot):
        religion_status = snapshot.get("religion_founding_status")
        if choral_music_available(religion_status):
            opportunities.append("found_choral_music_religion")
        if any(great_person_is_prophet(gp) for gp in snapshot.get("great_people") or []):
            opportunities.append("great_prophet_path")
        if any(
            str(value_from(opt, "item_name", "") or "") in {"PROJECT_HOLY_SITE_PRAYERS", "DISTRICT_HOLY_SITE"}
            for options in (snapshot.get("production") or {}).values()
            for opt in (options or [])
        ):
            opportunities.append("holy_site_prayers")
    if snapshot_mentions_any(snapshot, ["tribal", "village", "wonder", "natural"]):
        opportunities.append("historic_moment_notification")
    opportunities.extend(
        event["event_key"] for event in target_events if event.get("active")
    )
    opportunities = sorted(set(opportunities), key=opportunities.index)
    return {
        "turn": snapshot.get("turn"),
        "era_name": value_from(overview, "era_name", ""),
        "current_era": snapshot_current_era(snapshot),
        "current_age": snapshot_current_age(snapshot),
        "era_score": int(number_from(overview, "era_score", 0)),
        "golden_threshold": int(number_from(overview, "era_golden_threshold", 0)),
        "era_score_gap": gap,
        "golden_age_achieved": golden_age_achieved(snapshot),
        "gold": number_from(overview, "gold", 0),
        "gold_per_turn": number_from(overview, "gold_per_turn", 0),
        "faith": number_from(overview, "faith", 0),
        "religions_founded": int(number_from(overview, "religions_founded", 0)),
        "religions_max": int(number_from(overview, "religions_max", 0)),
        "our_religion": value_from(overview, "our_religion", None),
        "religion_slots_open": religion_slots_open(snapshot),
        "choral_music_available": choral_music_available(
            snapshot.get("religion_founding_status")
        ),
        "envoy_tokens_available": snapshot_envoy_tokens_available(snapshot),
        "governors": governors,
        "unassigned_governors": [row for row in governors if not row["assigned"]],
        "strategic_resources": strategic_resources,
        "unimproved_strategic_resources": unimproved_strategic_resources(snapshot.get("resources")),
        "nearby_strategic_resources": nearby_strategic_resources(snapshot.get("resources")),
        "tradable_players": trade_targets,
        "war_targets": war_targets,
        "gold_conversion_pressure": number_from(overview, "gold", 0)
        >= golden_age_gold_spend_threshold(snapshot),
        "opportunities": opportunities,
        "golden_age_target_events": target_events,
        "active_golden_age_target_events": [
            event for event in target_events if event.get("active")
        ],
    }


def unit_can_build_improvement(unit: Any, improvement: str) -> bool:
    valid = set(getattr(unit, "valid_improvements", []) or [])
    return not valid or improvement in valid


def summarize_overview(overview: Any) -> str:
    if overview is None:
        return "overview unavailable"
    return (
        f"{getattr(overview, 'civ_name', '?')} T{getattr(overview, 'turn', '?')}: "
        f"{getattr(overview, 'num_cities', '?')} cities, "
        f"{getattr(overview, 'num_units', '?')} units, "
        f"science {getattr(overview, 'science_yield', '?')}, "
        f"culture {getattr(overview, 'culture_yield', '?')}, "
        f"gold {getattr(overview, 'gold', '?')} ({getattr(overview, 'gold_per_turn', '?')}/t)"
    )


async def safe_tool(
    recorder: EpisodeRecorder,
    name: str,
    params: dict[str, Any],
    fn: Callable[[], Awaitable[Any]],
    *,
    turn: int | None = None,
    gaps: list[dict[str, str]],
    field: str,
) -> tuple[str | None, Any | None]:
    try:
        return await recorder.tool_call(name, params, fn, turn=turn)
    except Exception as exc:  # noqa: BLE001 - snapshot should continue.
        gap = {
            "field": field,
            "reason": f"{type(exc).__name__}: {exc}",
            "next_step": f"Investigate or add a minimal Civ6 MCP query for {field}.",
        }
        gaps.append(gap)
        recorder.add_gap(gap["field"], gap["reason"], gap["next_step"])
        return None, None


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
    recorder: EpisodeRecorder,
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


async def capture_state(
    recorder: EpisodeRecorder,
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
    turn = int(getattr(overview, "turn", 0))
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
        cid, value = await safe_tool(
            recorder, name, {}, fn, turn=turn, gaps=gaps, field=field
        )
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
        city_id = getattr(city, "city_id", None)
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
    snapshot["t50_strategy_audit"] = t50_strategy_audit(snapshot)

    required_fields = [
        "empire",
        "cities",
        "units",
        "notifications",
        "threats",
        "research_civic",
        "production",
    ]
    for key in required_fields:
        if snapshot.get(key) is None:
            gap = {
                "field": key,
                "reason": "Current tool returned no data for this snapshot field.",
                "next_step": "Add or repair the corresponding Civ6 MCP query before the T50 run.",
            }
            snapshot["known_gaps"].append(gap)
            recorder.add_gap(gap["field"], gap["reason"], gap["next_step"])

    snapshot_id = recorder.record_state(turn, label, snapshot, related)
    return turn, snapshot_id, snapshot


async def front_end_load_game_save(conn: GameConnection, save_name: str) -> str:
    """Load a save from the main menu using FrontEnd/LoadGameMenu Lua state."""
    states = [
        idx
        for idx, name in conn.lua_states.items()
        if name in {"LoadGameMenu", "FrontEnd"}
    ]
    if not states:
        return "Error: no LoadGameMenu/FrontEnd Lua state is available."
    state = states[0]
    target = json.dumps(save_name)
    target_ext = json.dumps(f"{save_name}.Civ6Save")
    marker = "CodexPhase1Load"
    lua = f"""
if not ExposedMembers then ExposedMembers = {{}} end;
ExposedMembers.{marker}Result = nil;
ExposedMembers.{marker}Done = false;
pcall(function() Automation.SetAutoStartEnabled(true) end);
local target = {target};
local targetExt = {target_ext};
local function OnResults(fileList, qid)
  UI.CloseFileListQuery(qid);
  LuaEvents.FileListQueryResults.Remove(OnResults);
  for i, s in ipairs(fileList) do
    if s.Name == target or s.Name == targetExt then
      ExposedMembers.{marker}Result = "FOUND|" .. tostring(s.Name);
      ExposedMembers.{marker}Done = true;
      Network.LoadGame(s, ServerType.SERVER_TYPE_NONE);
      return;
    end
  end;
  ExposedMembers.{marker}Result = "NOT_FOUND|" .. tostring(fileList and #fileList or 0);
  ExposedMembers.{marker}Done = true;
end;
LuaEvents.FileListQueryResults.Add(OnResults);
local opts = SaveLocationOptions.NORMAL + SaveLocationOptions.AUTOSAVE
  + SaveLocationOptions.QUICKSAVE + SaveLocationOptions.LOAD_METADATA;
UI.QuerySaveGameList(SaveLocations.LOCAL_STORAGE, SaveTypes.SINGLE_PLAYER, opts);
print("QUERY_SENT|" .. tostring({state}));
print("---END---");
"""
    await conn.execute_in_state(state, lua, timeout=5)
    check_lua = f"""
if ExposedMembers and ExposedMembers.{marker}Done then
  print("RESULT|" .. tostring(ExposedMembers.{marker}Result));
else
  print("PENDING");
end;
print("---END---");
"""
    for _ in range(40):
        await asyncio.sleep(0.25)
        try:
            lines = await conn.execute_in_state(state, check_lua, timeout=5)
        except Exception:
            return f"Loading save: {save_name}. Connection changed during front-end load."
        for line in lines:
            if line.startswith("RESULT|FOUND|"):
                return f"Loading save: {line.split('|', 2)[2]} via front-end Lua state {state}."
            if line.startswith("RESULT|NOT_FOUND|"):
                return f"Error: save '{save_name}' not found in front-end save list ({line})."
    return f"Error: timed out waiting for front-end save query for '{save_name}'."


async def connect_with_retry(
    conn: GameConnection,
    timeout_seconds: int = FIRETUNER_CONNECT_TIMEOUT_SECONDS,
) -> str:
    deadline = time.time() + timeout_seconds
    attempts = 0
    last_error = ""
    frontend_states = {"LoadGameMenu", "FrontEnd"}
    while time.time() < deadline:
        attempts += 1
        try:
            await conn.connect()
            ready = conn.gamecore_index is not None or any(
                name in frontend_states for name in conn.lua_states.values()
            )
            if not ready:
                last_error = f"Lua states not ready yet: {conn.lua_states}"
                await conn.disconnect()
                await asyncio.sleep(3)
                continue
            return (
                f"Connected after {attempts} attempt(s); "
                f"GameCore={conn.gamecore_index}, InGame={conn.ingame_index}."
            )
        except Exception as exc:  # noqa: BLE001 - startup race retry.
            last_error = f"{type(exc).__name__}: {exc}"
            try:
                await conn.disconnect()
            except Exception:
                pass
            await asyncio.sleep(3)
    raise ConnectionError(
        f"Could not connect to FireTuner after {attempts} attempts: {last_error}"
    )


async def ensure_game_loaded(
    recorder: EpisodeRecorder, gs: GameState, save_name: str, save_path: Path
) -> Any:
    if not game_launcher.is_game_running() or not is_tuner_port_open():
        await recorder.tool_call(
            "launch_game",
            {"reason": "game_not_running_or_tuner_port_closed"},
            lambda: game_launcher.launch_game(),
        )

    await recorder.tool_call(
        "connect",
        {"timeout_seconds": FIRETUNER_CONNECT_TIMEOUT_SECONDS},
        lambda: connect_with_retry(gs.conn, FIRETUNER_CONNECT_TIMEOUT_SECONDS),
    )
    used_front_end_load = False
    if gs.conn.gamecore_index is None:
        used_front_end_load = True
        load_id, load_result = await recorder.tool_call(
            "front_end_load_game_save",
            {"save_name": save_name},
            lambda: front_end_load_game_save(gs.conn, save_name),
        )
    else:
        load_id, load_result = await recorder.tool_call(
            "load_game_save",
            {"save_name": save_name},
            lambda: load_game_save(gs.conn, save_name),
        )
    recorder.codex_output("load_save", None, {"tool_call_id": load_id, "result": load_result})
    if str(load_result).startswith("Error:"):
        raise RuntimeError(str(load_result))

    if used_front_end_load:
        await recorder.tool_call(
            "disconnect_after_front_end_load",
            {},
            gs.conn.disconnect,
        )

    await asyncio.sleep(18)

    connected = False
    load_deadline = time.time() + FIRETUNER_LOAD_TIMEOUT_SECONDS
    keyboard_continue_sent = False
    while time.time() < load_deadline:
        try:
            await recorder.tool_call("reconnect_after_load", {}, gs.conn.reconnect)
            connected = True
            break
        except Exception:
            if not keyboard_continue_sent:
                try:
                    await recorder.tool_call(
                        "click_continue_if_needed",
                        {"method": "positional_grid"},
                        lambda: asyncio.to_thread(game_launcher._click_continue_positional),
                    )
                except Exception as exc:  # noqa: BLE001
                    recorder.add_gap(
                        "load.continue_screen.positional_click",
                        f"{type(exc).__name__}: {exc}",
                        "Use keyboard continue fallback or manual continue if the leader screen blocks loading.",
                    )
                try:
                    await recorder.tool_call(
                        "keyboard_continue_if_needed",
                        {"method": "tab_tab_tab_enter"},
                        lambda: asyncio.to_thread(press_continue_keys_win32),
                    )
                except Exception as exc:  # noqa: BLE001
                    recorder.add_gap(
                        "load.continue_screen.keyboard",
                        f"{type(exc).__name__}: {exc}",
                        "Use manual continue if keyboard fallback cannot operate.",
                    )
                keyboard_continue_sent = True
            await asyncio.sleep(5)
    if not connected:
        raise ConnectionError("Timed out waiting for FireTuner after loading save.")

    try:
        _, overview = await recorder.tool_call(
            "verify_loaded_get_game_overview", {}, gs.get_game_overview
        )
    except Exception:
        # The save may show the leader intro screen after loading.  Only click
        # the known continue position after an overview query fails.
        try:
            await recorder.tool_call(
                "click_continue_if_needed",
                {},
                lambda: asyncio.to_thread(game_launcher._click_continue_positional),
            )
            await asyncio.sleep(3)
            await recorder.tool_call("reconnect_after_continue", {}, gs.conn.reconnect)
        except Exception as exc:  # noqa: BLE001 - record as a gap, overview verifies.
            recorder.add_gap(
                "load.continue_screen",
                f"{type(exc).__name__}: {exc}",
                "If overview fails, load the save from the menu and rerun short validation.",
            )
        _, overview = await recorder.tool_call(
            "verify_loaded_get_game_overview", {}, gs.get_game_overview
        )
    recorder.record_save(
        source_path=save_path,
        turn=getattr(overview, "turn", None),
        label="observation_start_original_test_1",
        event="original starting save copied before decisions",
    )
    return overview


async def save_checkpoint(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    label: str,
    decision_id: str | None = None,
) -> str | None:
    save_name = f"{recorder.episode_id}_{label}_T{turn:04d}"
    call_id, result = await recorder.tool_call(
        "save_game", {"save_name": save_name}, lambda: save_game(gs.conn, save_name), turn=turn
    )
    recorder.codex_output("save_game", turn, {"tool_call_id": call_id, "result": result})
    await asyncio.sleep(2)
    source = SAVE_DIR / f"{save_name}.Civ6Save"
    for _ in range(10):
        if source.exists():
            return recorder.record_save(
                source_path=source,
                turn=turn,
                label=label,
                decision_id=decision_id,
                event="checkpoint created by Observation recorder",
            )
        await asyncio.sleep(1)
    recorder.add_gap(
        f"saves.{label}",
        f"save_game returned {result!r} but {source} was not found",
        "Before T50, verify Network.SaveGame writes the expected Single save file on this Windows install.",
    )
    return None


def background_from_snapshot(snapshot: dict[str, Any]) -> str:
    overview = snapshot.get("overview")
    threats = snapshot.get("threats") or []
    cities = snapshot.get("cities") or []
    units = snapshot.get("units") or []
    return (
        f"{summarize_overview(overview)}; "
        f"visible threats={len(threats)}, cities={len(cities)}, units={len(units)}."
    )


async def maybe_choose_research(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    tech_status = snapshot.get("research_civic")
    if tech_status is None:
        return
    if not needs_choice(getattr(tech_status, "current_research", "")):
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": "research review",
                "importance": "medium",
                "background": background_from_snapshot(snapshot),
                "current_goal": "Keep recording complete while avoiding unnecessary changes.",
                "available_actions": [
                    f"continue current research: {getattr(tech_status, 'current_research', '')}",
                    "change research manually",
                    "defer",
                ],
                "selected_action": "continue current research",
                "rationale": "A research target is already active; Observation should observe rather than rewrite the plan.",
                "why_not_alternatives": {
                    "change research manually": "Would alter live strategy without a blocker.",
                    "defer": "No action is required.",
                },
                "execution": {"tool": "none", "result": "no tool call needed"},
                "outcome": "Research left unchanged.",
                "related_tool_call_ids": [],
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )
        return

    options = list(getattr(tech_status, "available_techs", []) or [])
    selected = choose_by_priority(options, "tech_type", tech_priority_for(recorder))
    if selected is None:
        return
    actions = [f"set tech {getattr(opt, 'tech_type', '')}" for opt in options]
    call_id, result = await recorder.tool_call(
        "set_research",
        {"tech_or_civic": selected.tech_type, "category": "tech"},
        lambda: gs.set_research(selected.tech_type),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "missing research target",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Resolve mandatory research blocker so the observed game can advance.",
            "available_actions": actions,
            "selected_action": f"set tech {selected.tech_type}",
            "rationale": f"Pick the first available item from the active {strategy_priority_label(recorder)} technology priority.",
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "other available techs": "Lower priority or slower according to the static list used only for this run.",
                "leave unset": "End turn would be blocked by missing research.",
            },
            "execution": {"tool": "set_research", "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )


async def maybe_choose_civic(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    tech_status = snapshot.get("research_civic")
    if tech_status is None:
        return
    if not needs_choice(getattr(tech_status, "current_civic", "")):
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": "civic review",
                "importance": "medium",
                "background": background_from_snapshot(snapshot),
                "current_goal": "Keep current civic plan unless a blocker appears.",
                "available_actions": [
                    f"continue current civic: {getattr(tech_status, 'current_civic', '')}",
                    "change civic manually",
                    "defer",
                ],
                "selected_action": "continue current civic",
                "rationale": "A civic target is already active; Observation records the state instead of changing policy.",
                "why_not_alternatives": {
                    "change civic manually": "Would modify strategy outside observation scope.",
                    "defer": "No action is required.",
                },
                "execution": {"tool": "none", "result": "no tool call needed"},
                "outcome": "Civic left unchanged.",
                "related_tool_call_ids": [],
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )
        return

    options = list(getattr(tech_status, "available_civics", []) or [])
    selected = choose_by_priority(options, "civic_type", civic_priority_for(recorder))
    if selected is None:
        return
    actions = [f"set civic {getattr(opt, 'civic_type', '')}" for opt in options]
    call_id, result = await recorder.tool_call(
        "set_research",
        {"tech_or_civic": selected.civic_type, "category": "civic"},
        lambda: gs.set_civic(selected.civic_type),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "missing civic target",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Resolve mandatory civic blocker so the observed game can advance.",
            "available_actions": actions,
            "selected_action": f"set civic {selected.civic_type}",
            "rationale": f"Pick the first available item from the active {strategy_priority_label(recorder)} civic priority.",
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "other available civics": "Lower priority or slower according to the static list used only for this run.",
                "leave unset": "End turn would be blocked by missing civic.",
            },
            "execution": {"tool": "set_research", "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )


async def maybe_choose_pantheon(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    if not uses_golden_age_push_runtime(recorder):
        return
    status = snapshot.get("pantheon_status")
    if status is None or value_from(status, "has_pantheon", False):
        return
    beliefs = list(value_from(status, "available_beliefs", []) or [])
    selected = choose_belief_by_priority(beliefs, GOLDEN_AGE_PUSH_PANTHEON_PRIORITY)
    if selected is None:
        return
    belief_type = str(value_from(selected, "belief_type", "") or "")
    call_id, result = await recorder.tool_call(
        "choose_pantheon",
        {"belief_type": belief_type, "reason": "golden_age_push_religion_path"},
        lambda belief_type=belief_type: gs.choose_pantheon(belief_type),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "pantheon selection",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Open the religion path for Holy Site prayers and Choral Music if the game offers a pantheon choice.",
            "available_actions": [
                f"choose {value_from(belief, 'belief_type', '')}" for belief in beliefs
            ],
            "selected_action": f"choose {belief_type}",
            "rationale": "The golden_age_push religion branch prefers Divine Spark for prophet pressure, with military/economy pantheons as fallbacks.",
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "skip pantheon": "Would delay the religion branch and risk losing religion slots.",
                "other beliefs": "Lower in the configured religion-path priority.",
            },
            "execution": {"tool": "choose_pantheon", "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )


async def maybe_recruit_great_prophet(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    if not uses_golden_age_push_runtime(recorder) or not religion_slots_open(snapshot):
        return
    candidates = [
        gp
        for gp in snapshot.get("great_people") or []
        if great_person_is_prophet(gp) and value_from(gp, "can_recruit", False)
    ]
    if not candidates:
        return
    selected = sorted(
        candidates,
        key=lambda gp: (
            int(number_from(gp, "cost", 9999)),
            str(value_from(gp, "individual_name", "")),
        ),
    )[0]
    individual_id = int(number_from(selected, "individual_id", -1))
    if individual_id < 0:
        return
    call_id, result = await recorder.tool_call(
        "recruit_great_person",
        {
            "individual_id": individual_id,
            "class_name": value_from(selected, "class_name", ""),
            "individual_name": value_from(selected, "individual_name", ""),
            "reason": "golden_age_push_religion_path",
        },
        lambda individual_id=individual_id: gs.recruit_great_person(individual_id),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "great prophet recruitment",
            "importance": "critical",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Convert Holy Site project points into a Great Prophet before religion slots close.",
            "available_actions": [
                f"recruit {value_from(gp, 'individual_name', '')}"
                for gp in candidates
            ],
            "selected_action": f"recruit {value_from(selected, 'individual_name', '')}",
            "rationale": "A Great Prophet is recruitable, so the religion branch claims it immediately instead of waiting.",
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "wait": "Religion slots can be lost to AI founders.",
                "patronize": "Accumulated points are already enough to recruit.",
            },
            "execution": {"tool": "recruit_great_person", "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )


async def maybe_found_religion_with_choral(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
    *,
    trigger: str = "religion founding",
) -> None:
    if not uses_golden_age_push_runtime(recorder) or not religion_slots_open(snapshot):
        return
    status_id, status = await recorder.tool_call(
        "get_religion_beliefs",
        {"reason": "golden_age_push_choral_music_check"},
        gs.get_religion_founding_status,
        turn=turn,
    )
    if value_from(status, "has_religion", False):
        return
    religion_type = preferred_religion_type(status)
    founder_belief = preferred_founder_belief(status)
    if not religion_type or not founder_belief or not choral_music_available(status):
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": trigger,
                "importance": "high",
                "background": background_from_snapshot(snapshot),
                "current_goal": "Found a religion with Choral Music when all required choices are available.",
                "available_actions": ["found religion with Choral Music", "wait"],
                "selected_action": "wait for required religion choices",
                "rationale": "The religion founding status did not expose an open religion type, Choral Music, and a founder belief at the same time.",
                "strategy_context": strategy_context(recorder),
                "why_not_alternatives": {
                    "found without Choral Music": "User explicitly requested the Choral Music follower belief.",
                    "ignore religion": "Would abandon the requested religion branch without evidence.",
                },
                "execution": {
                    "tool": "get_religion_beliefs",
                    "religion_type": religion_type,
                    "choral_music_available": choral_music_available(status),
                    "founder_belief": founder_belief,
                },
                "outcome": "Religion not founded this turn.",
                "related_tool_call_ids": [status_id],
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )
        return
    call_id, result = await recorder.tool_call(
        "found_religion",
        {
            "religion_type": religion_type,
            "follower_belief": GOLDEN_AGE_PUSH_FOLLOWER_BELIEF,
            "founder_belief": founder_belief,
            "reason": "golden_age_push_choral_music",
        },
        lambda religion_type=religion_type, founder_belief=founder_belief: gs.found_religion(
            religion_type,
            GOLDEN_AGE_PUSH_FOLLOWER_BELIEF,
            founder_belief,
        ),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": trigger,
            "importance": "critical",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Found the run's religion using Choral Music as requested.",
            "available_actions": ["found religion with Choral Music", "wait"],
            "selected_action": f"found {religion_type} with {GOLDEN_AGE_PUSH_FOLLOWER_BELIEF}",
            "rationale": "The religion choices include Choral Music, so the runner locks the culture-scaling belief immediately.",
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "wait": "Religion slots and desired beliefs can be taken by other players.",
                "different follower belief": "User explicitly requested Choral Music.",
            },
            "execution": {
                "tool": "found_religion",
                "religion_type": religion_type,
                "follower_belief": GOLDEN_AGE_PUSH_FOLLOWER_BELIEF,
                "founder_belief": founder_belief,
                "result": result,
            },
            "outcome": short_text(result),
            "related_tool_call_ids": [status_id, call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )


def active_production_override_for_golden_age(
    recorder: Any,
    snapshot: dict[str, Any],
    city: Any,
    options: list[Any],
    planned_units: dict[str, int] | None = None,
) -> Any | None:
    if not uses_golden_age_push_runtime(recorder):
        return None
    if not snapshot_is_ancient_era(snapshot) or golden_age_achieved(snapshot):
        return None
    if (era_score_gap(snapshot) or 0) <= 0:
        return None
    current = str(value_from(city, "currently_building", "") or "")
    if current.upper() in {"", "NONE", "NOTHING", "CORRUPTED_QUEUE"}:
        return None
    if current in GOLDEN_AGE_PUSH_ACTIVE_PRODUCTION_OVERRIDE_ITEMS:
        return None
    priority = production_priority_for(recorder, snapshot, planned_units)
    selected = choose_by_priority(options, "item_name", priority)
    if selected is None:
        return None
    selected_name = str(value_from(selected, "item_name", "") or "")
    if selected_name not in GOLDEN_AGE_PUSH_ACTIVE_PRODUCTION_OVERRIDE_ITEMS:
        return None
    if priority_index(selected_name, priority) >= priority_index(current, priority):
        return None
    return selected


async def maybe_set_city_production(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    cities = snapshot.get("cities") or []
    production = snapshot.get("production") or {}
    planned_units: dict[str, int] = {}
    for city in cities:
        city_id = getattr(city, "city_id", None)
        if city_id is None:
            continue
        options = production.get(str(city_id)) or []
        selected = None
        production_override = False
        if not is_idle_city(city):
            selected = active_production_override_for_golden_age(
                recorder,
                snapshot,
                city,
                list(options or []),
                planned_units,
            )
            if selected is not None:
                production_override = True
            else:
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": f"production review for {getattr(city, 'name', city_id)}",
                        "importance": "medium",
                        "background": f"{getattr(city, 'name', city_id)} is producing {getattr(city, 'currently_building', '')} with {getattr(city, 'production_turns_left', '?')} turns left.",
                        "current_goal": "Avoid changing active production during Observation observation.",
                        "available_actions": [
                            f"continue {getattr(city, 'currently_building', '')}",
                            "change production",
                            "defer",
                        ],
                        "selected_action": "continue active production",
                        "rationale": "The city has an active queue; changing it would be a strategy intervention.",
                        "why_not_alternatives": {
                            "change production": "Not needed to advance the turn.",
                            "defer": "Equivalent to continuing the active queue.",
                        },
                        "execution": {"tool": "none", "result": "no tool call needed"},
                        "outcome": "Production left unchanged.",
                        "related_tool_call_ids": [],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                continue

        if production_override:
            repairs = []
        else:
            repairs = [opt for opt in options if getattr(opt, "is_repair", False)]
        if selected is None and repairs:
            selected = sorted(repairs, key=lambda opt: getattr(opt, "turns", 9999))[0]
        elif selected is None:
            selected = choose_by_priority(
                options,
                "item_name",
                production_priority_for(recorder, snapshot, planned_units),
            )
        if selected is None:
            recorder.add_gap(
                f"production.city_{city_id}.selection",
                "City appears idle but no production options were returned.",
                "Repair list_city_production coverage before T50.",
            )
            continue
        if not is_idle_city(city) and production_override:
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": f"golden age production override for {getattr(city, 'name', city_id)}",
                    "importance": "high",
                    "background": f"{getattr(city, 'name', city_id)} is producing {getattr(city, 'currently_building', '')} with {getattr(city, 'production_turns_left', '?')} turns left.",
                    "current_goal": "Convert the completed Horseback Riding and stocked Horses into the first Horseman before the ancient-era golden-age gate closes.",
                    "available_actions": [
                        f"continue {getattr(city, 'currently_building', '')}",
                        f"switch to {value_from(selected, 'item_name', '')}",
                        "defer",
                    ],
                    "selected_action": f"switch production to {value_from(selected, 'item_name', '')}",
                    "rationale": "The golden_age_push layer only overrides active production when UNIT_HORSEMAN is already a legal city option and first-age era score is still short.",
                    "strategy_context": strategy_context(recorder),
                    "why_not_alternatives": {
                        "continue current queue": "Run13 showed active builder queues can consume the remaining ancient-era window after Horses and Horseback are ready.",
                        "defer": "Equivalent to missing the first strategic-resource-unit timing window.",
                    },
                    "execution": {"tool": "pending", "result": "set_city_production below"},
                    "outcome": "Production override selected; command follows in the production tool call.",
                    "related_tool_call_ids": [],
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
        actions = [
            f"{getattr(opt, 'category', '?')} {getattr(opt, 'item_name', '?')} ({getattr(opt, 'turns', '?')}t)"
            for opt in options
        ]
        related_calls: list[str] = []
        target_x = getattr(selected, "repair_x", None)
        target_y = getattr(selected, "repair_y", None)
        if selected.category == "DISTRICT" and (target_x is None or target_y is None):
            advisor_id, placements = await recorder.tool_call(
                "get_district_advisor",
                {"city_id": city_id, "district_type": selected.item_name},
                lambda city_id=city_id, item_name=selected.item_name: gs.get_district_advisor(
                    city_id, item_name
                ),
                turn=turn,
            )
            related_calls.append(advisor_id)
            if isinstance(placements, str) or not placements:
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": f"district placement for {getattr(city, 'name', city_id)}",
                        "importance": "high",
                        "background": f"{selected.item_name} was the selected idle-city option, but no valid placement was returned.",
                        "current_goal": "Avoid an invalid production command while preserving the blocker evidence.",
                        "available_actions": actions,
                        "selected_action": "defer district production",
                        "rationale": "District production requires a concrete tile; the advisor did not provide a usable placement.",
                        "why_not_alternatives": {
                            "set district without tile": "Would fail and obscure the real blocker.",
                            "pick unrelated production": "Would change strategy after the static selector chose the district.",
                        },
                        "execution": {"tool": "get_district_advisor", "result": placements},
                        "outcome": "Production not changed; blocker recorded for human review.",
                        "related_tool_call_ids": related_calls,
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                continue
            placement = sorted(
                placements,
                key=lambda p: getattr(p, "total_adjacency", 0),
                reverse=True,
            )[0]
            target_x = getattr(placement, "x", None)
            target_y = getattr(placement, "y", None)

        params = {
            "city_id": city_id,
            "item_type": selected.category,
            "item_name": selected.item_name,
            "target_x": target_x,
            "target_y": target_y,
        }
        call_id, result = await recorder.tool_call(
            "set_city_production",
            params,
            lambda selected=selected, city_id=city_id: gs.set_city_production(
                city_id,
                selected.category,
                selected.item_name,
                target_x,
                target_y,
            ),
            turn=turn,
        )
        related_calls.append(call_id)
        if (
            selected.category == "UNIT"
            and isinstance(result, str)
            and not result.startswith(("Error", "ERR", "FAILED"))
        ):
            planned_units[selected.item_name] = planned_units.get(selected.item_name, 0) + 1
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": (
                    f"golden age production override for {getattr(city, 'name', city_id)}"
                    if production_override
                    else f"idle city production for {getattr(city, 'name', city_id)}"
                ),
                "importance": "high",
                "background": (
                    f"{getattr(city, 'name', city_id)} is producing {getattr(city, 'currently_building', '')} with {getattr(city, 'production_turns_left', '?')} turns left."
                    if production_override
                    else f"{getattr(city, 'name', city_id)} has no active production."
                ),
                "current_goal": (
                    "Switch to the first legal Horseman while the ancient-era golden-age gate is still open."
                    if production_override
                    else "Resolve mandatory production blocker while recording all candidate actions."
                ),
                "available_actions": actions,
                "selected_action": f"{selected.category} {selected.item_name}",
                "rationale": (
                    "Override the active queue because UNIT_HORSEMAN is legal and highest priority for first-age era score."
                    if production_override
                    else (
                        "Use repair first if needed, otherwise select from the active "
                        f"{strategy_priority_label(recorder)} production priority."
                    )
                ),
                "strategy_context": strategy_context(recorder),
                "why_not_alternatives": {
                    "other production options": "Recorded as available actions but lower in the active production priority.",
                    "continue current queue" if production_override else "leave idle": (
                        "Would miss the first strategic-resource-unit timing window."
                        if production_override
                        else "End turn may be blocked and the city would waste production."
                    ),
                },
                "execution": {"tool": "set_city_production", "params": params, "result": result},
                "outcome": short_text(result),
                "related_tool_call_ids": related_calls,
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )


def gold_purchase_candidates(
    snapshot: dict[str, Any],
    *,
    allowed_reasons: set[str] | None = None,
) -> list[dict[str, Any]]:
    overview = snapshot.get("overview") or {}
    gold = number_from(overview, "gold", 0)
    if gold < golden_age_gold_spend_threshold(snapshot):
        return []
    city_by_id = {str(value_from(city, "city_id", "")): city for city in snapshot.get("cities") or []}
    production = snapshot.get("production") or {}
    candidates: list[dict[str, Any]] = []
    has_strategic_development_path = (
        strategic_resource_development_path_available(snapshot)
        or ancient_post_settle_builder_reserve_active(snapshot)
    )
    scout_count = snapshot_unit_count(snapshot, "UNIT_SCOUT")
    for city_id, options in production.items():
        city = city_by_id.get(str(city_id))
        for option in options or []:
            item_name = str(value_from(option, "item_name", "") or "")
            category = str(value_from(option, "category", "") or "")
            cost = int(number_from(option, "gold_cost", -1))
            if cost < 0 or cost > gold or category != "UNIT":
                continue
            if (
                item_name == "UNIT_SCOUT"
                and snapshot_is_ancient_era(snapshot)
                and (
                    scout_count >= GOLDEN_AGE_PUSH_ANCIENT_SCOUT_CAP
                    or snapshot_turn(snapshot) > GOLDEN_AGE_PUSH_ANCIENT_SCOUT_REPLACEMENT_LATEST_TURN
                )
            ):
                continue
            if item_name in GOLDEN_AGE_PUSH_MILITARY_PURCHASE_PRIORITY:
                priority = GOLDEN_AGE_PUSH_MILITARY_PURCHASE_PRIORITY
                reason = "military_unit"
            elif (
                has_strategic_development_path
                and item_name in GOLDEN_AGE_PUSH_BUILDER_PURCHASE_PRIORITY
            ):
                priority = GOLDEN_AGE_PUSH_BUILDER_PURCHASE_PRIORITY
                reason = "strategic_resource_builder"
            else:
                continue
            if allowed_reasons is not None and reason not in allowed_reasons:
                continue
            candidates.append(
                {
                    "city_id": int(city_id),
                    "city_name": value_from(city, "name", city_id) if city else str(city_id),
                    "category": category,
                    "item_name": item_name,
                    "gold_cost": cost,
                    "reason": reason,
                    "rank": priority_index(item_name, priority),
                }
            )
    return sorted(
        candidates,
        key=lambda item: (
            0 if item["reason"] == "military_unit" else 1,
            int(item["rank"]),
            int(item["gold_cost"]),
            str(item["city_name"]),
        ),
    )


def select_gold_purchase(
    snapshot: dict[str, Any],
    *,
    allowed_reasons: set[str] | None = None,
) -> dict[str, Any] | None:
    candidates = gold_purchase_candidates(snapshot, allowed_reasons=allowed_reasons)
    return candidates[0] if candidates else None


def parse_unit_upgrade_check_result(result: Any) -> dict[str, Any] | None:
    for line in str(result or "").splitlines():
        if not line.startswith("UPGRADE|"):
            continue
        parts = line.split("|")
        if len(parts) < 6:
            return None
        return {
            "current_type": parts[1],
            "upgrade_type": parts[2],
            "upgrade_name": parts[3],
            "gold_cost": int(number_from({"value": parts[4]}, "value", 0)),
            "available_gold": int(number_from({"value": parts[5]}, "value", 0)),
        }
    return None


def military_upgrade_units(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for unit in snapshot.get("units") or []:
        unit_type = str(value_from(unit, "unit_type", "") or "")
        if unit_type not in GOLDEN_AGE_PUSH_MILITARY_UPGRADE_SOURCE_PRIORITY:
            continue
        unit_id = value_from(unit, "unit_id", None)
        if unit_id is None:
            continue
        candidates.append(
            {
                "unit_id": int(unit_id),
                "unit_type": unit_type,
                "rank": priority_index(
                    unit_type,
                    GOLDEN_AGE_PUSH_MILITARY_UPGRADE_SOURCE_PRIORITY,
                ),
            }
        )
    return sorted(candidates, key=lambda row: (int(row["rank"]), int(row["unit_id"])))


def unit_upgrade_candidate(
    unit: dict[str, Any],
    check_result: Any,
    *,
    snapshot_gold: float,
) -> dict[str, Any] | None:
    parsed = parse_unit_upgrade_check_result(check_result)
    if parsed is None:
        return None
    available_gold = min(float(parsed["available_gold"]), snapshot_gold)
    if parsed["gold_cost"] < 0 or parsed["gold_cost"] > available_gold:
        return None
    return {
        "unit_id": int(unit["unit_id"]),
        "unit_type": str(parsed["current_type"] or unit["unit_type"]),
        "upgrade_type": str(parsed["upgrade_type"]),
        "upgrade_name": str(parsed["upgrade_name"]),
        "gold_cost": int(parsed["gold_cost"]),
        "available_gold": available_gold,
        "check_result": check_result,
        "rank": (
            priority_index(
                str(parsed["upgrade_type"]),
                GOLDEN_AGE_PUSH_MILITARY_UPGRADE_TARGET_PRIORITY,
            ),
            priority_index(
                str(parsed["current_type"] or unit["unit_type"]),
                GOLDEN_AGE_PUSH_MILITARY_UPGRADE_SOURCE_PRIORITY,
            ),
            int(parsed["gold_cost"]),
        ),
    }


def select_unit_upgrade_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row["rank"])[0]


def strategic_resource_key(resource: Any) -> str:
    text = str(resource or "").strip().upper().replace("RESOURCE_", "")
    if "HORSE" in text:
        return "HORSES"
    if "IRON" in text:
        return "IRON"
    return text


def strategic_tile_purchase_candidates(
    snapshot: dict[str, Any],
    purchasable_by_city: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    overview = snapshot.get("overview") or {}
    gold = number_from(overview, "gold", 0)
    if gold < golden_age_gold_spend_threshold(snapshot):
        return []
    resource_income = strategic_resource_income_by_key(snapshot.get("resources"))
    city_by_id = {str(value_from(city, "city_id", "")): city for city in snapshot.get("cities") or []}
    candidates: list[dict[str, Any]] = []
    for city_id, tiles in purchasable_by_city.items():
        city = city_by_id.get(str(city_id))
        for tile in tiles or []:
            cost = int(number_from(tile, "cost", -1))
            resource = value_from(tile, "resource", "")
            resource_key = strategic_resource_key(resource)
            resource_class = str(value_from(tile, "resource_class", "") or "").lower()
            if cost < 0 or cost > gold:
                continue
            if resource_class != "strategic" and resource_key not in GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY:
                continue
            if resource_income.get(resource_key, 0) > 0:
                continue
            candidates.append(
                {
                    "city_id": int(city_id),
                    "city_name": value_from(city, "name", city_id) if city else str(city_id),
                    "x": int(number_from(tile, "x", 0)),
                    "y": int(number_from(tile, "y", 0)),
                    "gold_cost": cost,
                    "resource": resource,
                    "resource_key": resource_key,
                    "resource_class": resource_class,
                    "terrain": value_from(tile, "terrain", ""),
                    "rank": priority_index(
                        resource_key,
                        GOLDEN_AGE_PUSH_STRATEGIC_TILE_PRIORITY,
                    ),
                }
            )
    return sorted(
        candidates,
        key=lambda item: (
            int(item["rank"]),
            int(item["gold_cost"]),
            str(item["city_name"]),
            int(item["x"]),
            int(item["y"]),
        ),
    )


def select_strategic_tile_purchase(
    snapshot: dict[str, Any],
    purchasable_by_city: dict[str, list[Any]],
) -> dict[str, Any] | None:
    candidates = strategic_tile_purchase_candidates(snapshot, purchasable_by_city)
    return candidates[0] if candidates else None


async def maybe_upgrade_military_unit_for_t50(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> bool:
    overview = snapshot.get("overview") or {}
    gold = number_from(overview, "gold", 0)
    upgrade_units = military_upgrade_units(snapshot)
    if not upgrade_units:
        return False
    related_calls: list[str] = []
    upgrade_candidates: list[dict[str, Any]] = []
    for unit in upgrade_units[:6]:
        call_id, result = await recorder.tool_call(
            "check_unit_upgrade",
            {"unit_id": unit["unit_id"], "unit_type": unit["unit_type"]},
            lambda unit_id=unit["unit_id"]: gs.check_unit_upgrade(unit_id),
            turn=turn,
        )
        related_calls.append(call_id)
        candidate = unit_upgrade_candidate(unit, result, snapshot_gold=gold)
        if candidate is not None:
            upgrade_candidates.append(candidate)
    selected = select_unit_upgrade_candidate(upgrade_candidates)
    if selected is None:
        return False
    call_id, result = await recorder.tool_call(
        "upgrade_unit",
        {
            "unit_id": selected["unit_id"],
            "unit_type": selected["unit_type"],
            "upgrade_type": selected["upgrade_type"],
            "gold_cost": selected["gold_cost"],
            "reason": "golden_age_push_military_upgrade",
        },
        lambda selected=selected: gs.upgrade_unit(selected["unit_id"]),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "golden age gold spender",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Convert idle gold into military upgrades before the T50 checkpoint.",
            "available_actions": [
                (
                    f"upgrade {candidate['unit_type']} to {candidate['upgrade_type']} "
                    f"for {candidate['gold_cost']} gold"
                )
                for candidate in upgrade_candidates
            ],
            "selected_action": (
                f"upgrade {selected['unit_type']} to {selected['upgrade_type']} with gold"
            ),
            "rationale": (
                "The golden_age_push layer treats immediate military upgrades as a direct way to turn idle gold into combat options."
            ),
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "hold gold": "The current plan explicitly avoids leaving large T50 gold unconverted.",
                "buy a new unit first": "A legal upgrade creates immediate combat value without waiting for city placement or movement.",
            },
            "execution": {"tool": "upgrade_unit", "params": selected, "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [*related_calls, call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )
    return not str(result).startswith(("Error", "ERR", "FAILED"))


async def execute_gold_purchase_for_t50(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
    selected: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> bool:
    call_id, result = await recorder.tool_call(
        "purchase_item",
        {
            "city_id": selected["city_id"],
            "item_type": selected["category"],
            "item_name": selected["item_name"],
            "yield_type": "YIELD_GOLD",
            "reason": selected["reason"],
        },
        lambda selected=selected: gs.purchase_item(
            selected["city_id"],
            selected["category"],
            selected["item_name"],
            "YIELD_GOLD",
        ),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "golden age gold spender",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Convert idle gold into military or strategic-resource tempo before the T50 checkpoint.",
            "available_actions": [
                f"buy {candidate['item_name']} in {candidate['city_name']} for {candidate['gold_cost']} gold"
                for candidate in candidates
            ],
            "selected_action": f"purchase {selected['item_name']} with gold",
            "rationale": (
                "The golden_age_push layer treats era-score and military opportunities as higher priority than ending T50 with a large gold reserve."
            ),
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "hold gold": "The current plan explicitly avoids leaving large T50 gold unconverted.",
                "civilian purchase first": "Military tempo and strategic-resource conversion are the active gold priorities.",
            },
            "execution": {"tool": "purchase_item", "params": selected, "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )
    return not str(result).startswith(("Error", "ERR", "FAILED"))


async def maybe_purchase_strategic_tile_for_t50(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> bool:
    purchasable_by_city: dict[str, list[Any]] = {}
    related_calls: list[str] = []
    for city in snapshot.get("cities") or []:
        city_id = value_from(city, "city_id", None)
        if city_id is None:
            continue
        call_id, tiles = await recorder.tool_call(
            "get_purchasable_tiles",
            {"city_id": int(city_id), "city_name": value_from(city, "name", city_id)},
            lambda city_id=int(city_id): gs.get_purchasable_tiles(city_id),
            turn=turn,
        )
        related_calls.append(call_id)
        purchasable_by_city[str(city_id)] = list(tiles or [])
    candidates = strategic_tile_purchase_candidates(snapshot, purchasable_by_city)
    selected = candidates[0] if candidates else None
    if selected is None:
        return False
    call_id, result = await recorder.tool_call(
        "purchase_tile",
        {
            "city_id": selected["city_id"],
            "city_name": selected["city_name"],
            "x": selected["x"],
            "y": selected["y"],
            "gold_cost": selected["gold_cost"],
            "resource": selected["resource"],
            "reason": "golden_age_push_strategic_tile",
        },
        lambda selected=selected: gs.purchase_tile(
            selected["city_id"],
            selected["x"],
            selected["y"],
        ),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "golden age strategic tile purchase",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Convert idle gold into ownership of a strategic Horses or Iron tile for the T50 plan.",
            "available_actions": [
                (
                    f"buy {candidate['resource_key']} tile "
                    f"({candidate['x']},{candidate['y']}) for {candidate['gold_cost']} gold"
                )
                for candidate in candidates
            ],
            "selected_action": (
                f"purchase {selected['resource_key']} tile "
                f"({selected['x']},{selected['y']}) with gold"
            ),
            "rationale": (
                "When no higher-priority military buy is available, owning a nearby strategic tile creates a concrete resource-development path."
            ),
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "hold gold": "The current plan explicitly avoids ending T50 with large idle gold.",
                "buy non-strategic tile": "The T50 golden-age plan values Horses/Iron ownership above generic yield tiles.",
            },
            "execution": {"tool": "purchase_tile", "params": selected, "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [*related_calls, call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )
    return not str(result).startswith(("Error", "ERR", "FAILED"))


async def maybe_spend_gold_for_t50(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    if not uses_golden_age_push_runtime(recorder):
        return
    overview = snapshot.get("overview") or {}
    if number_from(overview, "gold", 0) < golden_age_gold_spend_threshold(snapshot):
        return
    try:
        if await maybe_upgrade_military_unit_for_t50(recorder, gs, turn, state_id, snapshot):
            return
    except Exception as exc:  # noqa: BLE001
        recorder.add_gap(
            "economy.gold_upgrade",
            f"{type(exc).__name__}: {exc}",
            "Repair military upgrade spending if T50 runs still end with idle gold.",
        )

    military_candidates = gold_purchase_candidates(
        snapshot,
        allowed_reasons={"military_unit"},
    )
    early_military_candidates = [
        candidate
        for candidate in military_candidates
        if candidate["item_name"] in GOLDEN_AGE_PUSH_EARLY_MILITARY_BUY_PRIORITY
    ]
    if early_military_candidates:
        if await execute_gold_purchase_for_t50(
            recorder,
            gs,
            turn,
            state_id,
            snapshot,
            early_military_candidates[0],
            early_military_candidates,
        ):
            return

    if ancient_strategic_builder_needed(snapshot):
        builder_candidates = gold_purchase_candidates(
            snapshot,
            allowed_reasons={"strategic_resource_builder"},
        )
        if builder_candidates:
            if await execute_gold_purchase_for_t50(
                recorder,
                gs,
                turn,
                state_id,
                snapshot,
                builder_candidates[0],
                builder_candidates,
            ):
                return
            return
        builder_cost = strategic_builder_purchase_shortfall(snapshot)
        if builder_cost is not None:
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": "golden age gold spender",
                    "importance": "high",
                    "background": background_from_snapshot(snapshot),
                    "current_goal": "Save early gold for a builder that can unlock Horses or Iron before the ancient-era golden-age gate closes.",
                    "available_actions": [
                        f"save toward UNIT_BUILDER for {builder_cost} gold",
                        *[
                            f"buy {candidate['item_name']} in {candidate['city_name']} for {candidate['gold_cost']} gold"
                            for candidate in military_candidates
                        ],
                    ],
                    "selected_action": "save gold for strategic-resource builder",
                    "rationale": (
                        "Run evidence showed that spending the first 65 gold on another basic unit left Horses unimproved until after the first-era gate."
                    ),
                    "strategy_context": strategy_context(recorder),
                    "why_not_alternatives": {
                        "buy basic military now": "A basic unit that cannot immediately clear a camp or become a Horseman is lower value than the strategic-resource builder path.",
                        "buy tile first": "Without a builder, tile ownership alone does not create Horseman stockpile before the ancient-era rollover.",
                    },
                    "execution": {"tool": "none", "result": "gold held for builder purchase"},
                    "outcome": f"Held gold until UNIT_BUILDER reaches {builder_cost} gold.",
                    "related_tool_call_ids": [],
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            return
        return

    tried_strategic_tile_purchase = False
    if ancient_strategic_resource_push_active(snapshot):
        tried_strategic_tile_purchase = True
        try:
            if await maybe_purchase_strategic_tile_for_t50(recorder, gs, turn, state_id, snapshot):
                return
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                "economy.strategic_tile_purchase",
                f"{type(exc).__name__}: {exc}",
                "Repair strategic tile buying if Horses/Iron remain outside borders during T50 runs.",
            )

    if ancient_post_settle_builder_reserve_active(snapshot):
        builder_candidates = gold_purchase_candidates(
            snapshot,
            allowed_reasons={"strategic_resource_builder"},
        )
        if builder_candidates:
            if await execute_gold_purchase_for_t50(
                recorder,
                gs,
                turn,
                state_id,
                snapshot,
                builder_candidates[0],
                builder_candidates,
            ):
                return
            return
        builder_cost = strategic_builder_purchase_shortfall(snapshot)
        if builder_cost is not None:
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": "golden age gold spender",
                    "importance": "high",
                    "background": background_from_snapshot(snapshot),
                    "current_goal": "Reserve early gold for a builder timed with the strategic second-city settle instead of buying a basic unit before Horses are inside borders.",
                    "available_actions": [
                        f"save toward UNIT_BUILDER for {builder_cost} gold",
                        *[
                            f"buy {candidate['item_name']} in {candidate['city_name']} for {candidate['gold_cost']} gold"
                            for candidate in military_candidates
                        ],
                    ],
                    "selected_action": "save gold for post-settlement strategic builder",
                    "rationale": (
                        "Run evidence showed that the T18 warrior purchase delayed the horse pasture enough for the first Horseman to miss the ancient-era golden-age gate."
                    ),
                    "strategy_context": strategy_context(recorder),
                    "why_not_alternatives": {
                        "buy basic military now": "The unit does not directly accelerate the first Horseman or create a reliable era-score event before rollover.",
                        "buy scout now": "Late scout replacement already missed the opening discovery window and competes with the Horseman path.",
                    },
                    "execution": {"tool": "none", "result": "gold held for post-settlement builder purchase"},
                    "outcome": f"Held gold until UNIT_BUILDER reaches {builder_cost} gold.",
                    "related_tool_call_ids": [],
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            return
        return

    if military_candidates:
        if await execute_gold_purchase_for_t50(
            recorder,
            gs,
            turn,
            state_id,
            snapshot,
            military_candidates[0],
            military_candidates,
        ):
            return

    if not tried_strategic_tile_purchase:
        try:
            if await maybe_purchase_strategic_tile_for_t50(recorder, gs, turn, state_id, snapshot):
                return
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                "economy.strategic_tile_purchase",
                f"{type(exc).__name__}: {exc}",
                "Repair strategic tile buying if Horses/Iron remain outside borders during T50 runs.",
            )

    builder_candidates = gold_purchase_candidates(
        snapshot,
        allowed_reasons={"strategic_resource_builder"},
    )
    if builder_candidates:
        await execute_gold_purchase_for_t50(
            recorder,
            gs,
            turn,
            state_id,
            snapshot,
            builder_candidates[0],
            builder_candidates,
        )


def resource_trade_candidate(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    stockpiles = strategic_stockpile_rows(snapshot.get("resources"))
    diplomacy = list(snapshot.get("diplomacy") or [])
    trade_targets = [
        civ
        for civ in diplomacy
        if value_from(civ, "has_met", False) and not value_from(civ, "is_at_war", False)
    ]
    if not trade_targets:
        return None
    for stock in sorted(stockpiles, key=lambda row: int(row["surplus_after_reserve"]), reverse=True):
        name = str(stock.get("name") or "").upper()
        reserve = GOLDEN_AGE_PUSH_RESOURCE_TRADE_RESERVE.get(name)
        if reserve is None:
            continue
        if int(stock["surplus_after_reserve"]) < GOLDEN_AGE_PUSH_RESOURCE_TRADE_MIN_SURPLUS:
            continue
        if int(stock["net_per_turn"]) < 0:
            continue
        civ = sorted(
            trade_targets,
            key=lambda item: (
                -int(number_from(item, "relationship_score", 0)),
                str(value_from(item, "civ_name", "")),
            ),
        )[0]
        return {
            "resource_name": name,
            "resource_type": resource_type_for_trade(name),
            "stockpile": stock,
            "other_player_id": int(value_from(civ, "player_id")),
            "other_civ_name": value_from(civ, "civ_name", ""),
        }
    return None


def counter_request_items_from_trade_test(test_result: Any) -> list[dict[str, Any]]:
    text = str(test_result or "")
    gpt_match = re.search(r"They give:\s*(?P<amount>\d+)\s*gold\s+per\s+turn", text, re.I)
    if gpt_match:
        return [
            {
                "type": "GOLD",
                "amount": int(gpt_match.group("amount")),
                "duration": 30,
            }
        ]
    gold_match = re.search(r"They give:\s*(?P<amount>\d+)\s*gold", text, re.I)
    if gold_match:
        return [
            {
                "type": "GOLD",
                "amount": int(gold_match.group("amount")),
                "duration": 0,
            }
        ]
    return []


async def maybe_trade_surplus_strategic_resources(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    if not uses_golden_age_push_runtime(recorder):
        return
    candidate = resource_trade_candidate(snapshot)
    if candidate is None:
        return
    related_calls: list[str] = []
    try:
        options_id, options = await recorder.tool_call(
            "get_trade_options",
            {"other_player_id": candidate["other_player_id"]},
            lambda candidate=candidate: gs.get_deal_options(candidate["other_player_id"]),
            turn=turn,
        )
        related_calls.append(options_id)
        their_gold = int(number_from(options, "their_gold", 0))
        their_gpt = int(number_from(options, "their_gpt", 0))
        request_items: list[dict[str, Any]]
        if their_gold > 0:
            request_items = [{"type": "GOLD", "amount": min(90, their_gold), "duration": 0}]
        elif their_gpt > 0:
            request_items = [{"type": "GOLD", "amount": min(3, their_gpt), "duration": 30}]
        else:
            return
        offer_items = [
            {
                "type": "RESOURCE",
                "name": candidate["resource_type"],
                "amount": 1,
                "duration": 30,
            }
        ]
        test_id, test_result = await recorder.tool_call(
            "test_trade",
            {
                "other_player_id": candidate["other_player_id"],
                "offer_items": offer_items,
                "request_items": request_items,
            },
            lambda candidate=candidate, offer_items=offer_items, request_items=request_items: gs.test_trade(
                candidate["other_player_id"], offer_items, request_items
            ),
            turn=turn,
        )
        related_calls.append(test_id)
        selected_action = "test strategic resource sale"
        execution: dict[str, Any] = {
            "tool": "test_trade",
            "candidate": candidate,
            "offer_items": offer_items,
            "request_items": request_items,
            "test_result": test_result,
        }
        outcome = short_text(test_result)
        counter_request_items = []
        if "ACCEPTABLE" not in str(test_result).upper():
            counter_request_items = counter_request_items_from_trade_test(test_result)
            if counter_request_items:
                request_items = counter_request_items
                execution["counter_request_items"] = counter_request_items
        if "ACCEPTABLE" in str(test_result).upper() or counter_request_items:
            propose_id, propose_result = await recorder.tool_call(
                "propose_trade",
                {
                    "other_player_id": candidate["other_player_id"],
                    "offer_items": offer_items,
                    "request_items": request_items,
                },
                lambda candidate=candidate, offer_items=offer_items, request_items=request_items: gs.propose_trade(
                    candidate["other_player_id"], offer_items, request_items
                ),
                turn=turn,
            )
            related_calls.append(propose_id)
            selected_action = "sell surplus strategic resource"
            execution["tool"] = "test_trade + propose_trade"
            execution["request_items"] = request_items
            execution["propose_result"] = propose_result
            outcome = short_text(propose_result)
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": "strategic resource monetization",
                "importance": "medium",
                "background": background_from_snapshot(snapshot),
                "current_goal": "Convert surplus Horses or Iron into gold without consuming resources reserved for the immediate military plan.",
                "available_actions": [
                    f"offer {candidate['resource_type']} to player {candidate['other_player_id']}",
                    "hold strategic resource reserve",
                    "skip trade this turn",
                ],
                "selected_action": selected_action,
                "rationale": "Only stockpile above the configured military reserve is offered, and the deal is tested before commit.",
                "strategy_context": strategy_context(recorder),
                "why_not_alternatives": {
                    "hold all resources": "The current plan explicitly tests aggressive conversion of surplus strategics.",
                    "trade without test": "Testing avoids committing an obviously poor or rejected deal.",
                },
                "execution": execution,
                "outcome": outcome,
                "related_tool_call_ids": related_calls,
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )
    except Exception as exc:  # noqa: BLE001
        recorder.add_gap(
            "economy.resource_trade",
            f"{type(exc).__name__}: {exc}",
            "Repair strategic resource trading if surplus Horses/Iron remain idle in T50 runs.",
        )


def preferred_war_action(civ: Any) -> str | None:
    actions = civ_available_actions(civ)
    for preferred in [
        "DECLARE_SURPRISE_WAR",
        "DECLARE_FORMAL_WAR",
        "DECLARE_TERRITORIAL_WAR",
        "DECLARE_HOLY_WAR",
    ]:
        for action in actions:
            if preferred in action.upper():
                return action
    return None


def opportunistic_war_candidate(snapshot: dict[str, Any], turn: int) -> dict[str, Any] | None:
    if turn < GOLDEN_AGE_PUSH_WAR_START_TURN:
        return None
    diplomacy = list(snapshot.get("diplomacy") or [])
    if any(value_from(civ, "is_at_war", False) for civ in diplomacy):
        return None
    combat_count = snapshot_combat_unit_count(snapshot)
    if combat_count < GOLDEN_AGE_PUSH_WAR_MIN_COMBAT_UNITS:
        return None
    candidates: list[dict[str, Any]] = []
    for civ in diplomacy:
        if not value_from(civ, "has_met", False) or value_from(civ, "is_at_war", False):
            continue
        action = preferred_war_action(civ)
        if not action:
            continue
        their_military = int(number_from(civ, "military_strength", 0))
        if their_military and their_military > combat_count * 45:
            continue
        attack_windows = favorable_attack_windows_for_civ(snapshot, civ)
        border_windows = border_pressure_windows_for_civ(snapshot, civ)
        if not attack_windows and not border_windows:
            continue
        candidates.append(
            {
                "other_player_id": int(value_from(civ, "player_id")),
                "other_civ_name": value_from(civ, "civ_name", ""),
                "leader_name": value_from(civ, "leader_name", ""),
                "action": action,
                "combat_unit_count": combat_count,
                "their_military_strength": their_military,
                "visible_city_count": len(value_from(civ, "visible_cities", []) or []),
                "favorable_attack_count": len(attack_windows),
                "border_pressure_count": len(border_windows),
                "best_attack_window": attack_windows[0] if attack_windows else None,
                "best_border_window": border_windows[0] if border_windows else None,
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            -int(row["favorable_attack_count"]),
            -int(row["border_pressure_count"]),
            int(row["their_military_strength"] or 0),
            -int(row["visible_city_count"]),
            str(row["other_civ_name"]),
        ),
    )[0]


async def maybe_declare_opportunistic_war(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    if not uses_golden_age_push_runtime(recorder):
        return
    candidate = opportunistic_war_candidate(snapshot, turn)
    if candidate is None:
        return
    call_id, result = await recorder.tool_call(
        "send_diplomatic_action",
        {
            "other_player_id": candidate["other_player_id"],
            "action": candidate["action"],
            "reason": "golden_age_push_opportunistic_war",
        },
        lambda candidate=candidate: gs.send_diplomatic_action(
            candidate["other_player_id"], candidate["action"]
        ),
        turn=turn,
    )
    recorder.record_decision(
        {
            "turn": turn,
            "trigger": "opportunistic war gate",
            "importance": "high",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Use a favorable neighbor-war window only when contact, declaration action, and military gate all pass.",
            "available_actions": [
                (
                    f"{candidate['action']} on {candidate['other_civ_name']} "
                    f"(attacks={candidate['favorable_attack_count']}, border={candidate['border_pressure_count']})"
                ),
                "hold peace",
                "wait for stronger force or better positioning",
            ],
            "selected_action": f"{candidate['action']} on {candidate['other_civ_name']}",
            "rationale": (
                "The target is met, a declaration action is currently available, local force is sufficient, "
                "and the snapshot contains a favorable attack or border-pressure window."
            ),
            "strategy_context": strategy_context(recorder),
            "why_not_alternatives": {
                "hold peace": "The current golden-age plan allows opportunistic aggression when gates pass.",
                "force city assault": "War declaration only opens tactical options; unit logic still avoids suicidal attacks.",
            },
            "execution": {"tool": "send_diplomatic_action", "candidate": candidate, "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )


async def maybe_handle_governance_blockers(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> None:
    policy_status = snapshot.get("policies")
    if policy_status is not None:
        assignments = policy_assignments_for_empty_slots(policy_status)
        if assignments:
            actions = [
                f"slot {slot_index} -> {policy_type}"
                for slot_index, policy_type in assignments.items()
            ]
            call_id, result = await recorder.tool_call(
                "set_policies",
                {"assignments": assignments},
                lambda assignments=assignments: gs.set_policies(assignments),
                turn=turn,
            )
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": "empty policy slot blocker",
                    "importance": "high",
                    "background": background_from_snapshot(snapshot),
                    "current_goal": "Fill mandatory policy slots so T50 automation can keep advancing.",
                    "available_actions": actions,
                    "selected_action": "set policy assignments",
                    "rationale": "Use conservative early-game policy priorities for empty slots instead of leaving end_turn blocked.",
                    "why_not_alternatives": {
                        "leave slots empty": "Would leave a required civic blocker unresolved.",
                        "manual policy planning": "This run needs deterministic blocker resolution without human intervention.",
                    },
                    "execution": {
                        "tool": "set_policies",
                        "assignments": assignments,
                        "result": result,
                    },
                    "outcome": short_text(result),
                    "related_tool_call_ids": [call_id],
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )

    if snapshot_mentions_any(
        snapshot,
        [
            "dedication",
            "commemoration",
            "着力点",
            "纪念",
            "COMMEMORATION",
        ],
    ):
        try:
            call_id, status = await recorder.tool_call(
                "get_dedications", {}, gs.get_dedications, turn=turn
            )
            choices = list(getattr(status, "choices", []) or [])
            selected = first_by_priority(choices, "name", DEDICATION_PRIORITY)
            if selected is not None:
                choose_id, result = await recorder.tool_call(
                    "choose_dedication",
                    {"dedication_index": int(getattr(selected, "index", 0))},
                    lambda selected=selected: gs.choose_dedication(
                        int(getattr(selected, "index", 0))
                    ),
                    turn=turn,
                )
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": "dedication blocker",
                        "importance": "high",
                        "background": background_from_snapshot(snapshot),
                        "current_goal": "Resolve era dedication selection before ending the turn.",
                        "available_actions": [
                            f"{getattr(choice, 'index', '?')}: {getattr(choice, 'name', '')}"
                            for choice in choices
                        ],
                        "selected_action": f"choose {getattr(selected, 'name', '')}",
                        "rationale": "Pick a deterministic economy/science-friendly dedication to avoid a midgame blocker.",
                        "why_not_alternatives": {
                            "other dedications": "Lower current priority for the automated T50 strategy profile.",
                            "leave unset": "End turn can remain blocked until a dedication is chosen.",
                        },
                        "execution": {
                            "tool": "choose_dedication",
                            "dedication_index": int(getattr(selected, "index", 0)),
                            "result": result,
                        },
                        "outcome": short_text(result),
                        "related_tool_call_ids": [call_id, choose_id],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                "governance.dedication",
                f"{type(exc).__name__}: {exc}",
                "Repair dedication auto-selection if era blockers recur in T50 runs.",
            )

    if should_handle_envoy_opportunity(snapshot):
        try:
            call_id, status = await recorder.tool_call(
                "get_city_states", {}, gs.get_city_states, turn=turn
            )
            tokens_available = int(number_from(status, "tokens_available", 0))
            targets = ranked_envoy_targets(status)
            if tokens_available > 0 and targets:
                selected = targets[0]
                player_id = int(number_from(selected, "player_id", -1))
                send_id, result = await recorder.tool_call(
                    "send_envoy",
                    {
                        "player_id": player_id,
                        "city_state": value_from(selected, "name", ""),
                        "city_state_type": value_from(selected, "city_state_type", ""),
                    },
                    lambda player_id=player_id: gs.send_envoy(player_id),
                    turn=turn,
                )
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": "envoy token blocker",
                        "importance": "high",
                        "background": background_from_snapshot(snapshot),
                        "current_goal": "Convert available envoy tokens instead of leaving city-state influence idle during the first-age push.",
                        "available_actions": [
                            f"{value_from(target, 'name', '?')} ({value_from(target, 'city_state_type', '?')})"
                            for target in targets
                        ],
                        "selected_action": f"send envoy to {value_from(selected, 'name', '')}",
                        "rationale": "Prefer scientific/cultural city-states first, then other yield types with fewer existing envoys.",
                        "why_not_alternatives": {
                            "save envoy token": "The T50 plan treats idle conversion opportunities as a failure mode.",
                            "other city-states": "Lower priority by city-state yield type or already-sent envoy count.",
                        },
                        "execution": {
                            "tool": "send_envoy",
                            "player_id": player_id,
                            "result": result,
                        },
                        "outcome": short_text(result),
                        "related_tool_call_ids": [call_id, send_id],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
            elif tokens_available > 0:
                recorder.add_gap(
                    "governance.envoy",
                    "Envoy tokens are available but get_city_states returned no sendable city-state.",
                    "Repair city-state envoy visibility before treating envoy blockers as resolved.",
                )
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                "governance.envoy",
                f"{type(exc).__name__}: {exc}",
                "Repair envoy auto-selection if influence-token blockers recur in T50 runs.",
            )

    governor_status = snapshot.get("governors")
    if governor_status is not None or snapshot_mentions_any(
        snapshot,
        ["governor", "总督", "GOVERNOR_APPOINTMENT", "GOVERNOR_PROMOTION"],
    ):
        try:
            related_status_calls: list[str] = []
            status = governor_status
            if status is None:
                call_id, status = await recorder.tool_call(
                    "get_governors", {}, gs.get_governors, turn=turn
                )
                related_status_calls.append(call_id)
            available = list(getattr(status, "available_to_appoint", []) or [])
            selected = first_by_priority(available, "governor_type", GOVERNOR_PRIORITY)
            if getattr(status, "can_appoint", False) and selected is not None:
                gov_type = str(getattr(selected, "governor_type", "") or "")
                appoint_id, result = await recorder.tool_call(
                    "appoint_governor",
                    {"governor_type": gov_type},
                    lambda gov_type=gov_type: gs.appoint_governor(gov_type),
                    turn=turn,
                )
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": "governor appointment blocker",
                        "importance": "high",
                        "background": background_from_snapshot(snapshot),
                        "current_goal": "Spend available governor appointment so end_turn does not stall.",
                        "available_actions": [
                            getattr(gov, "governor_type", "") for gov in available
                        ],
                        "selected_action": f"appoint {gov_type}",
                        "rationale": "Prefer early science/economy governors, with deterministic fallback to the first available governor.",
                        "why_not_alternatives": {
                            "other governors": "Lower priority for the current automated opening profile.",
                            "leave point unused": "Governor appointment notifications can block or delay turn advancement.",
                        },
                        "execution": {
                            "tool": "appoint_governor",
                            "governor_type": gov_type,
                            "result": result,
                        },
                        "outcome": short_text(result),
                        "related_tool_call_ids": [*related_status_calls, appoint_id],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                if not str(result).startswith(("Error", "ERR", "FAILED")):
                    await assign_governor_with_record(
                        recorder,
                        gs,
                        turn=turn,
                        state_id=state_id,
                        snapshot=snapshot,
                        governor_type=gov_type,
                        trigger="governor assignment after appointment",
                        existing_tool_call_ids=[*related_status_calls, appoint_id],
                        appointment_result=result,
                    )
            for appointed in list(getattr(status, "appointed", []) or []):
                gov_type = str(getattr(appointed, "governor_type", "") or "")
                if not gov_type or governor_is_assigned(appointed):
                    continue
                await assign_governor_with_record(
                    recorder,
                    gs,
                    turn=turn,
                    state_id=state_id,
                    snapshot=snapshot,
                    governor_type=gov_type,
                    trigger="unassigned governor placement",
                    existing_tool_call_ids=related_status_calls,
                )
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                "governance.governor",
                f"{type(exc).__name__}: {exc}",
                "Repair governor auto-appointment if governor blockers recur in T50 runs.",
            )

    units = list(snapshot.get("units") or [])
    for unit in units:
        if not getattr(unit, "needs_promotion", False):
            continue
        unit_id = getattr(unit, "unit_id", 0)
        try:
            call_id, status = await recorder.tool_call(
                "get_unit_promotions",
                {"unit_id": unit_id},
                lambda unit_id=unit_id: gs.get_unit_promotions(unit_id),
                turn=turn,
            )
            promotions = list(getattr(status, "promotions", []) or [])
            selected = first_by_priority(promotions, "promotion_type", PROMOTION_PRIORITY)
            if selected is None:
                continue
            promotion_type = str(getattr(selected, "promotion_type", "") or "")
            promote_id, result = await recorder.tool_call(
                "promote_unit",
                {"unit_id": unit_id, "promotion_type": promotion_type},
                lambda unit_id=unit_id, promotion_type=promotion_type: gs.promote_unit(
                    unit_id, promotion_type
                ),
                turn=turn,
            )
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": f"unit promotion blocker {unit_id}",
                    "importance": "high",
                    "background": f"{getattr(unit, 'unit_type', '')} has a pending promotion.",
                    "current_goal": "Resolve promotion blockers before unit movement and end_turn.",
                    "available_actions": [
                        getattr(promo, "promotion_type", "") for promo in promotions
                    ],
                    "selected_action": f"promote {promotion_type}",
                    "rationale": "Pick a deterministic combat/scout-safe promotion to clear the pending promotion prompt.",
                    "why_not_alternatives": {
                        "other promotions": "Lower generic priority for automated blocker resolution.",
                        "leave unpromoted": "A pending promotion can block turn completion.",
                    },
                    "execution": {
                        "tool": "promote_unit",
                        "unit_id": unit_id,
                        "promotion_type": promotion_type,
                        "result": result,
                    },
                    "outcome": short_text(result),
                    "related_tool_call_ids": [call_id, promote_id],
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                f"units.promotion.{unit_id}",
                f"{type(exc).__name__}: {exc}",
                "Repair unit promotion auto-selection if promotion blockers recur in T50 runs.",
            )


async def handle_units(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> bool:
    units = list(snapshot.get("units") or [])
    cities = list(snapshot.get("cities") or [])
    city_count = len(cities)
    founded_city = False
    builder_tasks_call_ids: list[str] = []
    builder_tasks: list[Any] = []
    if any(getattr(u, "unit_type", "") == "UNIT_BUILDER" for u in units):
        try:
            call_id, task_tuple = await recorder.tool_call(
                "get_builder_tasks", {}, gs.get_builder_tasks, turn=turn
            )
            builder_tasks_call_ids.append(call_id)
            builder_tasks = list(task_tuple[0])
        except Exception as exc:  # noqa: BLE001
            recorder.add_gap(
                "units.builder_tasks",
                f"{type(exc).__name__}: {exc}",
                "Repair get_builder_tasks if builder automation must be observed in T50.",
            )

    for unit in units:
        moves = float(getattr(unit, "moves_remaining", 0) or 0)
        unit_type = getattr(unit, "unit_type", "")
        unit_id = getattr(unit, "unit_id", 0)
        unit_index = getattr(unit, "unit_index", unit_id % 65536)
        if moves <= 0:
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": f"unit review {unit_type} {unit_id}",
                    "importance": "low",
                    "background": f"{unit_type} at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}) has no moves remaining.",
                    "current_goal": "Record why no unit command was issued.",
                    "available_actions": ["no legal move this turn"],
                    "selected_action": "no action",
                    "rationale": "The unit has no movement points.",
                    "why_not_alternatives": {"other actions": "Not executable this turn."},
                    "execution": {"tool": "none", "result": "no tool call needed"},
                    "outcome": "No change.",
                    "related_tool_call_ids": [],
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            continue

        if unit_is_great_prophet(unit):
            actions = [
                "activate Great Prophet on Holy Site",
                "move toward Holy Site",
                "skip Great Prophet",
            ]
            related_calls: list[str] = []
            advisor = None
            try:
                advisor_id, advisor = await recorder.tool_call(
                    "get_gp_advisor",
                    {"unit_id": unit_id},
                    lambda unit_index=unit_index: gs.get_gp_advisor(unit_index),
                    turn=turn,
                )
                related_calls.append(advisor_id)
            except Exception as exc:  # noqa: BLE001
                recorder.add_gap(
                    f"units.great_prophet_advisor.{unit_id}",
                    f"{type(exc).__name__}: {exc}",
                    "Repair get_gp_advisor if Great Prophet routing must be automatic.",
                )
            advisor_cities = list(value_from(advisor, "cities", []) or [])
            activation_city = next(
                (
                    city
                    for city in advisor_cities
                    if value_from(city, "can_activate", False)
                    and int(number_from(city, "distance", 999)) == 0
                ),
                None,
            )
            if activation_city is not None or not advisor_cities:
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {"unit_id": unit_id, "action": "activate"},
                    lambda unit_index=unit_index: gs.activate_great_person(unit_index),
                    turn=turn,
                )
                related_calls.append(call_id)
                selected = "activate Great Prophet"
                execution = {"tool": "unit_action", "action": "activate", "result": result}
                rationale = (
                    "The Great Prophet is on an activation tile, so the runner starts the religion founding operation."
                    if activation_city is not None
                    else "No activation advisor data was available, so the runner tries direct activation and records the result."
                )
                outcome = short_text(result)
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": f"great prophet action {unit_id}",
                        "importance": "critical",
                        "background": f"{unit_type} at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}).",
                        "current_goal": "Use the Great Prophet to found a religion with Choral Music.",
                        "available_actions": actions,
                        "selected_action": selected,
                        "rationale": rationale,
                        "strategy_context": strategy_context(recorder),
                        "why_not_alternatives": {
                            "move": "Activation is available or advisor data was unavailable.",
                            "skip": "Would risk losing the Choral Music branch after earning a prophet.",
                        },
                        "execution": execution,
                        "outcome": outcome,
                        "related_tool_call_ids": related_calls,
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                if str(result).startswith("OK:"):
                    await maybe_found_religion_with_choral(
                        recorder,
                        gs,
                        turn,
                        state_id,
                        snapshot,
                        trigger=f"religion founding after Great Prophet activation {unit_id}",
                    )
                continue
            target_city = sorted(
                advisor_cities,
                key=lambda city: (
                    0 if value_from(city, "can_activate", False) else 1,
                    int(number_from(city, "distance", 999)),
                    str(value_from(city, "city_name", "")),
                ),
            )[0]
            target_x = int(number_from(target_city, "district_x", value_from(unit, "x", 0)))
            target_y = int(number_from(target_city, "district_y", value_from(unit, "y", 0)))
            call_id, result = await recorder.tool_call(
                "unit_action",
                {
                    "unit_id": unit_id,
                    "action": "move",
                    "target_x": target_x,
                    "target_y": target_y,
                    "target_district": value_from(advisor, "target_district", ""),
                },
                lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.move_unit(
                    unit_index, target_x, target_y
                ),
                turn=turn,
            )
            related_calls.append(call_id)
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": f"great prophet action {unit_id}",
                    "importance": "critical",
                    "background": f"{unit_type} at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}).",
                    "current_goal": "Move the Great Prophet to a Holy Site so it can found the requested Choral Music religion.",
                    "available_actions": actions,
                    "selected_action": "move toward Holy Site",
                    "rationale": "The prophet is not on an activation tile yet, so it routes to the best Holy Site advisor target.",
                    "strategy_context": strategy_context(recorder),
                    "why_not_alternatives": {
                        "activate": "The advisor did not report activation available on the current tile.",
                        "skip": "Would leave the earned prophet idle.",
                    },
                    "execution": {
                        "tool": "unit_action",
                        "action": "move",
                        "target": {
                            "x": target_x,
                            "y": target_y,
                            "city_name": value_from(target_city, "city_name", ""),
                            "target_district": value_from(advisor, "target_district", ""),
                        },
                        "result": result,
                    },
                    "outcome": short_text(result),
                    "related_tool_call_ids": related_calls,
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            continue

        if unit_type == "UNIT_SETTLER" and city_count == 0:
            actions = [
                "found_city on current tile",
                "move settler toward fresh water",
                "wait for more map information",
            ]
            related_calls: list[str] = []
            if uses_river_settlement_runtime(recorder):
                try:
                    scan_id, candidates = await recorder.tool_call(
                        "get_global_settle_scan", {}, gs.get_global_settle_scan, turn=turn
                    )
                    related_calls.append(scan_id)
                    candidate_list = ranked_settle_candidates(
                        list(candidates or []),
                        prefer_fresh=True,
                    )
                    current_candidate = next(
                        (
                            candidate
                            for candidate in candidate_list
                            if candidate_matches_unit_tile(candidate, unit)
                        ),
                        None,
                    )
                    best_candidate = candidate_list[0] if candidate_list else None
                    if (
                        best_candidate is not None
                        and candidate_has_fresh_water(best_candidate)
                        and not candidate_matches_unit_tile(best_candidate, unit)
                        and not (
                            current_candidate is not None
                            and candidate_has_fresh_water(current_candidate)
                        )
                    ):
                        target_x = int(value_from(best_candidate, "x"))
                        target_y = int(value_from(best_candidate, "y"))
                        move_id, move_result = await recorder.tool_call(
                            "unit_action",
                            {
                                "unit_id": unit_id,
                                "action": "move",
                                "target_x": target_x,
                                "target_y": target_y,
                                "water_type": value_from(best_candidate, "water_type"),
                            },
                            lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.move_unit(
                                unit_index, target_x, target_y
                            ),
                            turn=turn,
                        )
                        related_calls.append(move_id)
                        recorder.record_decision(
                            {
                                "turn": turn,
                                "trigger": "opening settler action",
                                "importance": "critical",
                                "background": background_from_snapshot(snapshot),
                                "current_goal": "Establish the capital on fresh water when a visible river/fresh-water opening tile is available.",
                                "available_actions": actions,
                                "selected_action": "move settler toward fresh water",
                                "rationale": "The active strategy explicitly prefers river/fresh-water settlement; the current tile was not the best fresh-water candidate.",
                                "strategy_context": strategy_context(recorder),
                                "why_not_alternatives": {
                                    "found_city on current tile": "Would ignore the river/fresh-water opening preference when a better visible tile is available.",
                                    "wait": "Moving toward the chosen tile preserves opening momentum.",
                                },
                                "execution": {
                                    "tool": "unit_action",
                                    "action": "move",
                                    "target": {
                                        "x": target_x,
                                        "y": target_y,
                                        "score": value_from(best_candidate, "score"),
                                        "water_type": value_from(best_candidate, "water_type"),
                                    },
                                    "result": move_result,
                                },
                                "outcome": short_text(move_result),
                                "related_tool_call_ids": related_calls,
                                "related_state_snapshot_ids": [state_id],
                                "related_save_ids": [],
                            }
                        )
                        continue
                except Exception as exc:  # noqa: BLE001
                    recorder.add_gap(
                        "units.opening_settle_scan",
                        f"{type(exc).__name__}: {exc}",
                        "Fall back to immediate founding if the fresh-water settle scan cannot be queried.",
                    )
            call_id, result = await recorder.tool_call(
                "unit_action",
                {"unit_id": unit_id, "action": "found_city"},
                lambda unit_index=unit_index: gs.found_city(unit_index),
                turn=turn,
            )
            related_calls.append(call_id)
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": "opening settler action",
                    "importance": "critical",
                    "background": background_from_snapshot(snapshot),
                    "current_goal": "Establish the first city so the real game can progress.",
                    "available_actions": actions,
                    "selected_action": "found_city on current tile",
                    "rationale": "With zero cities, founding immediately is the least speculative action once no better fresh-water move was selected.",
                    "strategy_context": strategy_context(recorder),
                    "why_not_alternatives": {
                        "move settler toward fresh water": "No better fresh-water candidate was selected from the opening settle scan.",
                        "wait": "Delays all production and research.",
                    },
                    "execution": {"tool": "unit_action", "action": "found_city", "result": result},
                    "outcome": short_text(result),
                    "related_tool_call_ids": related_calls,
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            if str(result).startswith("FOUNDED|"):
                city_count += 1
                founded_city = True
            continue

        if unit_type == "UNIT_SETTLER":
            actions = [
                "found_city on current tile",
                "move toward best settle candidate",
                "skip settler",
            ]
            related_calls: list[str] = []
            if uses_golden_age_push_runtime(recorder) and golden_age_strategic_settle_active(
                snapshot
            ):
                try:
                    scan_id, candidates = await recorder.tool_call(
                        "get_global_settle_scan", {}, gs.get_global_settle_scan, turn=turn
                    )
                    related_calls.append(scan_id)
                    candidate_list = ranked_settle_candidates_for_strategy(
                        recorder,
                        snapshot,
                        list(candidates or []),
                        prefer_fresh=uses_river_settlement_runtime(recorder),
                    )
                    best_candidate = candidate_list[0] if candidate_list else None
                    current_resource_distance = strategic_resource_distance_for_xy(
                        value_from(unit, "x", None),
                        value_from(unit, "y", None),
                        snapshot,
                    )
                    if (
                        best_candidate is not None
                        and not candidate_matches_unit_tile(best_candidate, unit)
                        and strategic_resource_distance_for_candidate(best_candidate, snapshot)
                        < current_resource_distance
                    ):
                        move_attempts: list[dict[str, Any]] = []
                        move_result = ""
                        moved = False
                        target_x = int(value_from(best_candidate, "x"))
                        target_y = int(value_from(best_candidate, "y"))
                        for candidate in candidate_list[:3]:
                            target_x = int(value_from(candidate, "x"))
                            target_y = int(value_from(candidate, "y"))
                            move_id, move_result = await recorder.tool_call(
                                "unit_action",
                                {
                                    "unit_id": unit_id,
                                    "action": "move",
                                    "target_x": target_x,
                                    "target_y": target_y,
                                    "reason": "strategic_resource_settle",
                                },
                                lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.move_unit(
                                    unit_index, target_x, target_y
                                ),
                                turn=turn,
                            )
                            related_calls.append(move_id)
                            move_attempts.append(
                                {
                                    "target": {
                                        "x": target_x,
                                        "y": target_y,
                                        "score": value_from(candidate, "score", None),
                                        "water_type": value_from(candidate, "water_type", None),
                                        "resource_distance": strategic_resource_distance_for_candidate(
                                            candidate, snapshot
                                        ),
                                        "distance": candidate_distance_from_unit(candidate, unit),
                                    },
                                    "result": move_result,
                                    "tool_call_id": move_id,
                                }
                            )
                            if "BLOCKED" not in str(move_result):
                                moved = True
                                break
                        if moved:
                            recorder.record_decision(
                                {
                                    "turn": turn,
                                    "trigger": f"expansion settler action {unit_id}",
                                    "importance": "critical",
                                    "background": (
                                        f"UNIT_SETTLER at ({value_from(unit, 'x', '?')},{value_from(unit, 'y', '?')}); "
                                        f"nearest strategic resource distance={current_resource_distance}."
                                    ),
                                    "current_goal": "Place the next city close enough to Horses or Iron to unlock the first strategic-resource unit before the ancient-era golden gate closes.",
                                    "available_actions": actions,
                                    "selected_action": "move toward strategic resource settle candidate",
                                    "rationale": (
                                        "The current tile is farther from the revealed strategic resource cluster, so the golden_age_push layer routes before founding."
                                    ),
                                    "strategy_context": strategy_context(recorder),
                                    "why_not_alternatives": {
                                        "found_city on current tile": "Would repeat the observed run12 failure where Horses stayed nearby but outside owned/improvable tiles.",
                                        "ordinary settle score": "Raw settle score is secondary while the first-age golden gate depends on strategic-resource conversion.",
                                    },
                                    "execution": {
                                        "tool": "unit_action",
                                        "action": "move",
                                        "target": {
                                            "x": target_x,
                                            "y": target_y,
                                            "resource_distance": strategic_resource_distance_for_xy(
                                                target_x, target_y, snapshot
                                            ),
                                        },
                                        "move_result": move_result,
                                        "move_attempts": move_attempts,
                                    },
                                    "outcome": short_text(move_result),
                                    "related_tool_call_ids": related_calls,
                                    "related_state_snapshot_ids": [state_id],
                                    "related_save_ids": [],
                                }
                            )
                            continue
                except Exception as exc:  # noqa: BLE001
                    recorder.add_gap(
                        "units.strategic_settle_scan",
                        f"{type(exc).__name__}: {exc}",
                        "Repair strategic-resource settlement routing if nearby Horses/Iron remain outside owned tiles.",
                    )
            found_id, found_result = await recorder.tool_call(
                "unit_action",
                {"unit_id": unit_id, "action": "found_city"},
                lambda unit_index=unit_index: gs.found_city(unit_index),
                turn=turn,
            )
            related_calls.append(found_id)
            selected = "found_city on current tile"
            execution: dict[str, Any] = {
                "tool": "unit_action",
                "action": "found_city",
                "result": found_result,
            }
            outcome = short_text(found_result)
            rationale = (
                "A produced settler should convert exploration into expansion as soon as the current tile is legal."
            )
            if not str(found_result).startswith("FOUNDED|"):
                scan_id, candidates = await recorder.tool_call(
                    "get_global_settle_scan", {}, gs.get_global_settle_scan, turn=turn
                )
                related_calls.append(scan_id)
                candidate_list = ranked_settle_candidates_for_strategy(
                    recorder,
                    snapshot,
                    list(candidates or []),
                    prefer_fresh=uses_river_settlement_runtime(recorder),
                )
                if candidate_list:
                    move_attempts: list[dict[str, Any]] = []
                    move_result = ""
                    candidate = candidate_list[0]
                    target_x = int(getattr(candidate, "x"))
                    target_y = int(getattr(candidate, "y"))
                    target_distance = candidate_distance_from_unit(candidate, unit)
                    if (
                        visible_barbarian_threat_count(snapshot) > 0
                        and target_distance
                        > SETTLER_MAX_UNESCORTED_DISTANCE_WITH_BARBARIANS
                    ):
                        nearby_candidates = ranked_near_settle_candidates_for_strategy(
                            recorder,
                            snapshot,
                            list(candidates or []),
                            unit,
                            max_distance=SETTLER_MAX_UNESCORTED_DISTANCE_WITH_BARBARIANS,
                            prefer_fresh=uses_river_settlement_runtime(recorder),
                        )
                        if nearby_candidates:
                            candidate_list = nearby_candidates
                            candidate = candidate_list[0]
                            target_x = int(getattr(candidate, "x"))
                            target_y = int(getattr(candidate, "y"))
                            target_distance = candidate_distance_from_unit(candidate, unit)
                            selected = "move toward nearby safe settle candidate"
                            rationale = (
                                "Visible barbarian pressure made the top long-path settle target unsafe, so the runner chose the best revealed candidate inside the safety radius."
                            )
                        elif should_risk_golden_age_settler_move(recorder, snapshot, unit, turn):
                            selected = "move toward best settle candidate despite barbarian pressure"
                            rationale = (
                                "The first-age golden gate is still open and the settler has no adjacent barbarian, so the runner accepts path risk instead of holding expansion indefinitely."
                            )
                        else:
                            skip_id, skip_result = await recorder.tool_call(
                                "unit_action",
                                {"unit_id": unit_id, "action": "skip"},
                                lambda unit_index=unit_index: gs.skip_unit(unit_index),
                                turn=turn,
                            )
                            related_calls.append(skip_id)
                            selected = "hold settler for barbarian safety"
                            execution = {
                                "tool": "unit_action",
                                "action": "skip",
                                "found_result": found_result,
                                "target": {
                                    "x": target_x,
                                    "y": target_y,
                                    "score": getattr(candidate, "score", None),
                                    "water_type": getattr(candidate, "water_type", None),
                                    "distance": target_distance,
                                },
                                "skip_result": skip_result,
                            }
                            outcome = short_text(skip_result)
                            rationale = (
                                "A visible barbarian threat and a long settle path make this unescorted settler vulnerable, so it waits instead of walking into capture risk."
                            )
                    else:
                        selected = "move toward best settle candidate"
                        rationale = (
                            "The settler could not found on its current tile, so the runner moved it toward the highest-scored revealed settle candidate."
                        )
                    if selected.startswith("move toward"):
                        for candidate in candidate_list[:3]:
                            target_x = int(getattr(candidate, "x"))
                            target_y = int(getattr(candidate, "y"))
                            move_id, move_result = await recorder.tool_call(
                                "unit_action",
                                {
                                    "unit_id": unit_id,
                                    "action": "move",
                                    "target_x": target_x,
                                    "target_y": target_y,
                                },
                                lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.move_unit(
                                    unit_index, target_x, target_y
                                ),
                                turn=turn,
                            )
                            related_calls.append(move_id)
                            move_attempts.append(
                                {
                                    "target": {
                                        "x": target_x,
                                        "y": target_y,
                                        "score": getattr(candidate, "score", None),
                                        "water_type": getattr(candidate, "water_type", None),
                                        "distance": candidate_distance_from_unit(candidate, unit),
                                    },
                                    "result": move_result,
                                    "tool_call_id": move_id,
                                }
                            )
                            if "BLOCKED" not in str(move_result):
                                break
                        execution = {
                            "tool": "unit_action",
                            "action": "move",
                            "target": {
                                "x": target_x,
                                "y": target_y,
                                "score": getattr(candidate, "score", None),
                                "water_type": getattr(candidate, "water_type", None),
                                "distance": candidate_distance_from_unit(candidate, unit),
                            },
                            "found_result": found_result,
                            "move_result": move_result,
                            "move_attempts": move_attempts,
                        }
                        outcome = short_text(move_result)
                else:
                    skip_id, skip_result = await recorder.tool_call(
                        "unit_action",
                        {"unit_id": unit_id, "action": "skip"},
                        lambda unit_index=unit_index: gs.skip_unit(unit_index),
                        turn=turn,
                    )
                    related_calls.append(skip_id)
                    selected = "skip settler"
                    execution = {
                        "tool": "unit_action",
                        "action": "skip",
                        "found_result": found_result,
                        "settle_candidates": [],
                        "skip_result": skip_result,
                    }
                    outcome = short_text(skip_result)
                    rationale = (
                        "The current tile was illegal and the settle scan returned no target, so the settler was skipped to avoid blocking end_turn."
                    )
            else:
                city_count += 1
                founded_city = True
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": f"expansion settler action {unit_id}",
                    "importance": "critical",
                    "background": f"UNIT_SETTLER at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}); current cities={city_count}.",
                    "current_goal": "Convert produced settlers into real city expansion during the T50 run.",
                    "available_actions": actions,
                    "selected_action": selected,
                    "rationale": rationale,
                    "strategy_context": strategy_context(recorder),
                    "why_not_alternatives": {
                        "wait for more map information": "The T50 strategy needs expansion pressure, not indefinite settler idling.",
                        "ignore settler": "Leaving a settler with moves can block end_turn and wastes production.",
                    },
                    "execution": execution,
                    "outcome": outcome,
                    "related_tool_call_ids": related_calls,
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            continue

        if unit_type == "UNIT_BUILDER":
            prefer_strategic_builder = uses_golden_age_push_runtime(
                recorder
            ) and ancient_strategic_resource_push_active(snapshot)
            same_tile_tasks = ranked_builder_tasks_for_unit(
                [
                    t
                    for t in builder_tasks
                    if getattr(t, "x", None) == getattr(unit, "x", None)
                    and getattr(t, "y", None) == getattr(unit, "y", None)
                    and builder_task_is_usable_now(t, unit)
                ],
                unit,
                prefer_strategic=uses_golden_age_push_runtime(recorder),
            )
            if (
                prefer_strategic_builder
                and same_tile_tasks
                and not builder_task_is_strategic_resource(same_tile_tasks[0])
            ):
                strategic_off_tile_tasks = [
                    t
                    for t in builder_tasks
                    if (
                        getattr(t, "x", None) != getattr(unit, "x", None)
                        or getattr(t, "y", None) != getattr(unit, "y", None)
                    )
                    and builder_task_is_usable_now(t, unit)
                    and builder_task_is_strategic_resource(t)
                ]
                if strategic_off_tile_tasks:
                    same_tile_tasks = []
            if same_tile_tasks:
                task = same_tile_tasks[0]
                improvement = getattr(task, "improvement", "")
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {"unit_id": unit_id, "action": "improve", "improvement": improvement},
                    lambda unit_index=unit_index, improvement=improvement: gs.improve_tile(
                        unit_index, improvement
                    ),
                    turn=turn,
                )
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": f"builder task at current tile for {unit_id}",
                        "importance": "high",
                        "background": f"Builder is already on a recommended task tile ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}).",
                        "current_goal": "Execute a directly available improvement while preserving evidence.",
                        "available_actions": [
                            f"build {improvement}",
                            "skip builder",
                            "move builder to a different task",
                        ],
                        "selected_action": f"build {improvement}",
                        "rationale": "The builder is already on the target tile, so no exploratory movement is needed.",
                        "why_not_alternatives": {
                            "skip builder": "Would waste an available safe improvement.",
                            "move builder": "No better adjacent action was established by the snapshot.",
                        },
                        "execution": {"tool": "unit_action", "action": "improve", "result": result},
                        "outcome": short_text(result),
                        "related_tool_call_ids": [*builder_tasks_call_ids, call_id],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                continue
            target_tasks = [
                task
                for task in ranked_builder_tasks_for_unit(
                    builder_tasks,
                    unit,
                    prefer_strategic=uses_golden_age_push_runtime(recorder),
                )
                if (
                    getattr(task, "x", None) != getattr(unit, "x", None)
                    or getattr(task, "y", None) != getattr(unit, "y", None)
                )
                and builder_task_is_usable_now(task, unit)
            ]
            if target_tasks:
                task = target_tasks[0]
                target_x = int(getattr(task, "x"))
                target_y = int(getattr(task, "y"))
                improvement = getattr(task, "improvement", "")
                priority = getattr(task, "priority", "")
                city_name = getattr(task, "city_name", "")
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {
                        "unit_id": unit_id,
                        "action": "move",
                        "target_x": target_x,
                        "target_y": target_y,
                        "improvement": improvement,
                    },
                    lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.move_unit(
                        unit_index, target_x, target_y
                    ),
                    turn=turn,
                )
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": f"builder move toward task for {unit_id}",
                        "importance": "high",
                        "background": (
                            f"Builder at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}); "
                            f"target {improvement} at ({target_x},{target_y}) near {city_name}."
                        ),
                        "current_goal": "Convert builder production into tile improvements during the T50 run.",
                        "available_actions": [
                            f"move to {improvement} target",
                            "skip builder",
                            "wait for better task",
                        ],
                        "selected_action": f"move to {improvement} target",
                        "rationale": (
                            f"The builder is not on an improvement tile yet, so it moves toward the best "
                            f"{priority or 'known'} builder task instead of idling."
                        ),
                        "why_not_alternatives": {
                            "skip builder": "Would repeat the observed failure where builders accumulated without improving tiles.",
                            "wait": "The task list already provides a concrete target from current game state.",
                        },
                        "execution": {
                            "tool": "unit_action",
                            "action": "move",
                            "target": {
                                "x": target_x,
                                "y": target_y,
                                "improvement": improvement,
                                "priority": priority,
                            },
                            "result": result,
                        },
                        "outcome": short_text(result),
                        "related_tool_call_ids": [*builder_tasks_call_ids, call_id],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                continue

        if unit_type == "UNIT_TRADER":
            trade_routes = snapshot.get("trade_routes")
            actions = [
                "start best trade route",
                "skip trader",
                "wait for more route information",
            ]
            if trader_is_already_on_route(trade_routes, unit):
                recorder.record_decision(
                    {
                        "turn": turn,
                        "trigger": f"trader route review {unit_id}",
                        "importance": "medium",
                        "background": f"UNIT_TRADER at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}) is already on an active route.",
                        "current_goal": "Avoid issuing redundant commands to an active trade route.",
                        "available_actions": actions,
                        "selected_action": "already on active trade route",
                        "rationale": "The trade route snapshot already records this trader as assigned.",
                        "why_not_alternatives": {
                            "start route": "A trader already on a route cannot start another one.",
                            "skip": "No unit command is needed when the route is active.",
                        },
                        "execution": {"tool": "none", "result": "active trade route"},
                        "outcome": "No change.",
                        "related_tool_call_ids": [],
                        "related_state_snapshot_ids": [state_id],
                        "related_save_ids": [],
                    }
                )
                continue
            related_calls: list[str] = []
            destinations: list[Any] = []
            route_gap = ""
            try:
                dest_id, destinations = await recorder.tool_call(
                    "get_trade_destinations",
                    {"unit_id": unit_id},
                    lambda unit_index=unit_index: gs.get_trade_destinations(unit_index),
                    turn=turn,
                )
                related_calls.append(dest_id)
            except Exception as exc:  # noqa: BLE001
                route_gap = f"{type(exc).__name__}: {exc}"
                recorder.add_gap(
                    "units.trade_destinations",
                    route_gap,
                    "Repair get_trade_destinations if trader automation must be observed in T50.",
                )
            ranked_destinations = ranked_trade_destinations(list(destinations or []))
            if ranked_destinations:
                destination = ranked_destinations[0]
                target_x = int(getattr(destination, "x"))
                target_y = int(getattr(destination, "y"))
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {
                        "unit_id": unit_id,
                        "action": "trade_route",
                        "target_x": target_x,
                        "target_y": target_y,
                    },
                    lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.make_trade_route(
                        unit_index, target_x, target_y
                    ),
                    turn=turn,
                )
                related_calls.append(call_id)
                selected = "start best trade route"
                execution = {
                    "tool": "unit_action",
                    "action": "trade_route",
                    "target": {
                        "x": target_x,
                        "y": target_y,
                        "city_name": getattr(destination, "city_name", ""),
                        "owner_name": getattr(destination, "owner_name", ""),
                        "is_domestic": getattr(destination, "is_domestic", False),
                        "has_quest": getattr(destination, "has_quest", False),
                        "origin_yields": getattr(destination, "origin_yields", ""),
                        "dest_yields": getattr(destination, "dest_yields", ""),
                    },
                    "result": result,
                }
                outcome = short_text(result)
                rationale = (
                    "An idle trader should convert the route slot into food/production/gold "
                    "instead of being repeatedly skipped during the T50 run."
                )
            else:
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {"unit_id": unit_id, "action": "skip"},
                    lambda unit_index=unit_index: gs.skip_unit(unit_index),
                    turn=turn,
                )
                related_calls.append(call_id)
                selected = "skip trader"
                execution = {
                    "tool": "unit_action",
                    "action": "skip",
                    "route_destinations": [],
                    "route_gap": route_gap,
                    "result": result,
                }
                outcome = short_text(result)
                rationale = (
                    "No legal trade destination was available from the current city, so the runner skipped the trader rather than blocking end_turn."
                )
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": f"trader route review {unit_id}",
                    "importance": "high",
                    "background": f"UNIT_TRADER at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}); route capacity snapshot={trade_routes}.",
                    "current_goal": "Turn idle trader production into an active route during the T50 run.",
                    "available_actions": actions,
                    "selected_action": selected,
                    "rationale": rationale,
                    "why_not_alternatives": {
                        "skip trader": "Would repeat the observed T41/T42 idle trader failure when destinations exist.",
                        "wait": "The destination query provides concrete current-game route candidates.",
                    },
                    "execution": execution,
                    "outcome": outcome,
                    "related_tool_call_ids": related_calls,
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            continue

        attack_targets = ranked_attack_targets_for_unit(
            recorder,
            unit,
            list(snapshot.get("threats") or []),
            turn,
            list(snapshot.get("diplomacy") or []),
        )
        barbarian_move_target = (
            nearest_barbarian_threat_for_unit(unit, list(snapshot.get("threats") or []))
            if unit_type in BARBARIAN_CLEARING_UNIT_TYPES
            and uses_barbarian_clearance_runtime(recorder)
            else None
        )
        war_move_target = nearest_war_threat_for_unit(
            recorder,
            unit,
            list(snapshot.get("threats") or []),
            list(snapshot.get("diplomacy") or []),
        )
        unit_health = float(value_from(unit, "health", 100) or 100)
        unit_max_health = max(1.0, float(value_from(unit, "max_health", 100) or 100))
        golden_age_map_call_id: str | None = None
        golden_age_map_target: dict[str, Any] | None = None
        if unit_health >= unit_max_health * 0.6 or (
            uses_golden_age_push_runtime(recorder)
            and unit_type == "UNIT_SCOUT"
            and snapshot_is_ancient_era(snapshot)
            and not golden_age_achieved(snapshot)
        ):
            golden_age_map_call_id, golden_age_map_target = await golden_age_map_target_for_unit(
                recorder,
                gs,
                turn,
                unit,
                snapshot,
            )
        if attack_targets:
            attack_targets = prioritize_golden_age_attack_targets(
                attack_targets, golden_age_map_target
            )
        wounded_critical_attack = bool(
            attack_targets
            and unit_health < unit_max_health * 0.6
            and should_attack_critical_target_while_wounded(
                recorder,
                attack_targets[0],
                golden_age_map_target,
            )
        )
        wounded_critical_map_move = bool(
            unit_health < unit_max_health * 0.6
            and should_move_to_critical_map_target_while_wounded(
                recorder,
                unit,
                golden_age_map_target,
            )
        )
        if (
            unit_health < unit_max_health * 0.6
            and not wounded_critical_attack
            and not wounded_critical_map_move
        ):
            call_id, result = await recorder.tool_call(
                "unit_action",
                {"unit_id": unit_id, "action": "heal"},
                lambda unit_index=unit_index: gs.heal_unit(unit_index),
                turn=turn,
            )
            selected = "heal"
            rationale = "The unit is badly damaged; preserving it is safer than moving during an observation run."
        elif attack_targets:
            target = attack_targets[0]
            target_x = int(target["x"])
            target_y = int(target["y"])
            if target.get("adjacent_to_ranged_unit") and not should_attack_adjacent_ranged_target(
                recorder, target, golden_age_map_target
            ):
                move_x, move_y = ranged_reposition_target(unit, target)
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {
                        "unit_id": unit_id,
                        "action": "move",
                        "target_x": move_x,
                        "target_y": move_y,
                        "deferred_attack_target_x": target_x,
                        "deferred_attack_target_y": target_y,
                        "target": target.get("raw"),
                    },
                    lambda unit_index=unit_index, move_x=move_x, move_y=move_y: gs.move_unit(
                        unit_index, move_x, move_y
                    ),
                    turn=turn,
                )
                selected = "reposition ranged unit"
                rationale = (
                    "The ranged unit is adjacent to its target; moving away first avoids the observed close-range ranged attack rejection and can free stacking pressure."
                )
            else:
                call_id, result = await recorder.tool_call(
                    "unit_action",
                    {
                        "unit_id": unit_id,
                        "action": "attack",
                        "target_x": target_x,
                        "target_y": target_y,
                        "target": target.get("raw"),
                    },
                    lambda unit_index=unit_index, target_x=target_x, target_y=target_y: gs.attack_unit(
                        unit_index, target_x, target_y
                    ),
                    turn=turn,
                )
                selected = "attack target"
                rationale = (
                    "The active T50 strategy gives clearable barbarian threats priority over fortifying."
                    if target.get("is_barbarian")
                    else "The active T50 strategy only attacks declared-war targets when the snapshot shows a high-confidence combat window."
                )
        elif golden_age_map_target:
            move_x = int(golden_age_map_target["x"])
            move_y = int(golden_age_map_target["y"])
            call_id, result = await recorder.tool_call(
                "unit_action",
                {
                    "unit_id": unit_id,
                    "action": "move",
                    "target_x": move_x,
                    "target_y": move_y,
                    "target": golden_age_map_target,
                },
                lambda unit_index=unit_index, move_x=move_x, move_y=move_y: gs.move_unit(
                    unit_index, move_x, move_y
                ),
                turn=turn,
            )
            if movement_result_is_blocked(result):
                remember_blocked_golden_age_map_target(
                    recorder,
                    unit,
                    golden_age_map_target,
                    turn,
                )
            selected = "move toward era-score map target"
            rationale = (
                "The ancient golden-age gap is still open and the map scan found a revealed camp, village, or natural-wonder target, so the unit routes to that era-score objective before chasing generic threats."
            )
        elif barbarian_move_target:
            if unit_is_ranged_clearer(unit) and target_is_adjacent_to_unit(
                unit, barbarian_move_target
            ):
                move_x, move_y = ranged_reposition_target(unit, barbarian_move_target)
                selected = "reposition ranged unit"
                rationale = (
                    "A visible barbarian is adjacent but not currently attackable; the ranged unit moves away to avoid close-range ranged rejection and free stacking."
                )
            else:
                move_x = int(barbarian_move_target["x"])
                move_y = int(barbarian_move_target["y"])
                selected = "move toward barbarian threat"
                rationale = (
                    "The active T50 strategy treats clearing visible barbarians as high priority, so this unit moves toward the nearest known barbarian instead of fortifying."
                )
            call_id, result = await recorder.tool_call(
                "unit_action",
                {
                    "unit_id": unit_id,
                    "action": "move",
                    "target_x": move_x,
                    "target_y": move_y,
                    "target": {
                        "x": barbarian_move_target["x"],
                        "y": barbarian_move_target["y"],
                        "distance": barbarian_move_target["distance"],
                    },
                },
                lambda unit_index=unit_index, move_x=move_x, move_y=move_y: gs.move_unit(
                    unit_index, move_x, move_y
                ),
                turn=turn,
            )
        elif war_move_target:
            move_x = int(war_move_target["x"])
            move_y = int(war_move_target["y"])
            selected = "move toward war target"
            rationale = (
                "The active T50 strategy is already at war and has a nearby visible target, so this combat unit moves tactically instead of fortifying."
            )
            call_id, result = await recorder.tool_call(
                "unit_action",
                {
                    "unit_id": unit_id,
                    "action": "move",
                    "target_x": move_x,
                    "target_y": move_y,
                    "target": {
                        "x": war_move_target["x"],
                        "y": war_move_target["y"],
                        "distance": war_move_target["distance"],
                        "owner_id": value_from(war_move_target.get("threat"), "owner_id"),
                    },
                },
                lambda unit_index=unit_index, move_x=move_x, move_y=move_y: gs.move_unit(
                    unit_index, move_x, move_y
                ),
                turn=turn,
            )
        elif should_auto_explore_unit(recorder, unit_type, snapshot):
            call_id, result = await recorder.tool_call(
                "unit_action",
                {
                    "unit_id": unit_id,
                    "action": "automate_explore",
                    "strategy_profile": recorder_strategy_profile(recorder),
                    "strategy_context": strategy_context(recorder),
                },
                lambda unit_index=unit_index: gs.automate_explore(unit_index),
                turn=turn,
            )
            selected = "automate_explore"
            runtime = recorder_candidate_runtime(recorder)
            rationale = (
                "The candidate playbook runtime treats early map knowledge as higher value than repeated fortify/hold."
                if runtime.get("status") == "applied"
                else "The explore_scout_first profile treats early map knowledge as higher value than repeated fortify/hold during T20 exploration."
            )
        elif "COMBAT" in unit_type or unit_type in {
            "UNIT_WARRIOR",
            "UNIT_SLINGER",
            "UNIT_ARCHER",
            "UNIT_SCOUT",
        }:
            call_id, result = await recorder.tool_call(
                "unit_action",
                {"unit_id": unit_id, "action": "fortify"},
                lambda unit_index=unit_index: gs.fortify_unit(unit_index),
                turn=turn,
            )
            selected = "fortify"
            rationale = "No specific recorded tactical target justified movement; fortify/hold avoids speculative exploration in the short validation run."
        else:
            call_id, result = await recorder.tool_call(
                "unit_action",
                {"unit_id": unit_id, "action": "skip"},
                lambda unit_index=unit_index: gs.skip_unit(unit_index),
                turn=turn,
            )
            selected = "skip"
            rationale = "No high-confidence, state-supported action was identified for this unit in the short validation run."

        recorder.record_decision(
            {
                "turn": turn,
                "trigger": f"unit action review {unit_type} {unit_id}",
                "importance": "medium",
                "background": f"{unit_type} at ({getattr(unit, 'x', '?')},{getattr(unit, 'y', '?')}); HP {getattr(unit, 'health', '?')}/{getattr(unit, 'max_health', '?')}; moves {moves}.",
                "current_goal": "Advance the turn while recording why the unit was not used for speculative strategy changes.",
                "available_actions": [
                    "move to explored/revealed tile",
                    "attack visible target if valid",
                    "fortify/hold",
                    "heal if damaged",
                    "skip",
                ],
                "selected_action": selected,
                "rationale": rationale,
                "strategy_context": strategy_context(recorder),
                "why_not_alternatives": {
                    "move": "No explicit safe target was selected from the snapshot.",
                    "attack": "No higher-priority attackable target matched the active strategy.",
                    "other": "Deferred to keep Observation observation focused on evidence capture.",
                },
                "execution": {
                    "tool": "unit_action",
                    "action": selected,
                    "target": (
                        attack_targets[0]
                        if selected == "attack target"
                        else attack_targets[0]
                        if selected == "reposition ranged unit" and attack_targets
                        else barbarian_move_target
                        if selected
                        in {"move toward barbarian threat", "reposition ranged unit"}
                        else war_move_target
                        if selected == "move toward war target"
                        else golden_age_map_target
                        if selected == "move toward era-score map target"
                        else None
                    ),
                    "result": result,
                },
                "outcome": short_text(result),
                "related_tool_call_ids": [
                    item
                    for item in [
                        golden_age_map_call_id
                        if selected == "move toward era-score map target"
                        else None,
                        call_id,
                    ]
                    if item
                ],
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )

    return founded_city


async def end_turn_with_record(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
) -> str:
    actions = [
        "end turn now",
        "query more state before ending",
        "make additional unit/city/research changes",
        "pause run",
    ]
    call_id, result = await recorder.tool_call("end_turn", {}, gs.end_turn, turn=turn)
    decision_id = recorder.record_decision(
        {
            "turn": turn,
            "trigger": "turn completion",
            "importance": "critical",
            "background": background_from_snapshot(snapshot),
            "current_goal": "Advance exactly one real Civ6 turn after mandatory blockers have been handled.",
            "available_actions": actions,
            "selected_action": "end turn now",
            "rationale": "The Observation observation needs the requested real turns; all prior choices and tool calls have been logged.",
            "why_not_alternatives": {
                "query more state": "The required per-turn state snapshot was already captured.",
                "make additional changes": "Would move beyond observation and blocker handling.",
                "pause run": "No validation-report boundary has been reached yet.",
            },
            "execution": {"tool": "end_turn", "result": result},
            "outcome": short_text(result),
            "related_tool_call_ids": [call_id],
            "related_state_snapshot_ids": [state_id],
            "related_save_ids": [],
        }
    )
    if "call end_turn again" in str(result):
        retry_id, retry_result = await recorder.tool_call(
            "end_turn_retry", {}, gs.end_turn, turn=turn
        )
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": "end_turn requested retry",
                "importance": "high",
                "background": short_text(result),
                "current_goal": "Complete the same turn after an automatic blocker was handled.",
                "available_actions": ["retry end_turn", "pause for human", "query blockers"],
                "selected_action": "retry end_turn",
                "rationale": "The engine reported that the original turn did not advance and explicitly requested another end_turn.",
                "why_not_alternatives": {
                    "pause": "The blocker was already auto-handled.",
                    "query blockers": "The end_turn result was specific enough to retry once.",
                },
                "execution": {"tool": "end_turn_retry", "result": retry_result},
                "outcome": short_text(retry_result),
                "related_tool_call_ids": [retry_id],
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )
        result = retry_result
    if end_turn_result_requests_diplomacy_response(result):
        result = await resolve_end_turn_diplomacy_blocker(
            recorder, gs, turn, state_id, snapshot, result
        )
    save_id = await save_checkpoint(
        recorder, gs, turn, f"after_turn_{turn:04d}", decision_id=decision_id
    )
    if save_id:
        recorder.timeline(f"- T{turn} end-turn decision linked to save `{save_id}`.")
    return str(result)


def end_turn_result_requests_diplomacy_response(result: Any) -> bool:
    text = str(result).lower()
    return any(
        fragment in text
        for fragment in (
            "respond_to_diplomacy",
            "respond_to_trade",
            "diplomacy encounter pending",
            "diplomatic proposal",
        )
    )


def describe_diplomacy_session(session: Any) -> str:
    civ = getattr(session, "other_civ_name", "?")
    leader = getattr(session, "other_leader_name", "?")
    player_id = getattr(session, "other_player_id", "?")
    if getattr(session, "deal_summary", ""):
        state = "deal"
    elif getattr(session, "is_at_war", False):
        state = "war"
    elif str(getattr(session, "buttons", "")).upper() == "GOODBYE":
        state = "goodbye"
    else:
        state = "active"
    return f"{civ} ({leader}, player {player_id}) [{state}]"


async def respond_to_diplomacy_session(
    recorder: EpisodeRecorder,
    gs: GameState,
    session: Any,
    turn: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    related_tool_call_ids: list[str] = []
    responses: list[dict[str, Any]] = []
    other_player_id = int(getattr(session, "other_player_id"))
    description = describe_diplomacy_session(session)
    deal_summary = str(getattr(session, "deal_summary", "") or "")
    buttons = str(getattr(session, "buttons", "") or "").upper()
    is_war = bool(getattr(session, "is_at_war", False))

    if deal_summary:
        call_id, result = await recorder.tool_call(
            "respond_to_trade_decline_for_end_turn",
            {"other_player_id": other_player_id, "accept": False},
            lambda: gs.respond_to_deal(other_player_id, False),
            turn=turn,
        )
        related_tool_call_ids.append(call_id)
        responses.append(
            {
                "session": description,
                "selected_response": "decline incoming trade deal",
                "result": result,
                "rationale": "Observation-mode automation keeps AI-initiated deals deterministic unless a strategy asset explicitly authorizes acceptance.",
            }
        )
        return related_tool_call_ids, responses

    response = "EXIT" if is_war or buttons == "GOODBYE" else "POSITIVE"
    call_id, result = await recorder.tool_call(
        "respond_to_diplomacy_for_end_turn",
        {"other_player_id": other_player_id, "response": response},
        lambda: gs.diplomacy_respond(other_player_id, response),
        turn=turn,
    )
    related_tool_call_ids.append(call_id)
    responses.append(
        {
            "session": description,
            "selected_response": response,
            "result": result,
            "rationale": (
                "Friendly first-contact acknowledgement preserves scouting momentum."
                if response == "POSITIVE"
                else "The session is already informational or in goodbye state, so it can be closed."
            ),
        }
    )
    if response != "EXIT" and "SESSION_CONTINUES" in str(result):
        exit_id, exit_result = await recorder.tool_call(
            "respond_to_diplomacy_exit_for_end_turn",
            {"other_player_id": other_player_id, "response": "EXIT"},
            lambda: gs.diplomacy_respond(other_player_id, "EXIT"),
            turn=turn,
        )
        related_tool_call_ids.append(exit_id)
        responses.append(
            {
                "session": description,
                "selected_response": "EXIT",
                "result": exit_result,
                "rationale": "The positive response was accepted but the leader screen stayed open, so the runner closed the goodbye state before retrying end_turn.",
            }
        )
    return related_tool_call_ids, responses


async def resolve_end_turn_diplomacy_blocker(
    recorder: EpisodeRecorder,
    gs: GameState,
    turn: int,
    state_id: str,
    snapshot: dict[str, Any],
    blocker_result: Any,
) -> str:
    current_result = blocker_result
    for attempt in range(1, 5):
        sessions_id, sessions = await recorder.tool_call(
            "get_diplomacy_sessions_for_end_turn",
            {"attempt": attempt},
            gs.get_diplomacy_sessions,
            turn=turn,
        )
        related_tool_call_ids = [sessions_id]
        response_rows: list[dict[str, Any]] = []
        for session in sessions or []:
            ids, rows = await respond_to_diplomacy_session(recorder, gs, session, turn)
            related_tool_call_ids.extend(ids)
            response_rows.extend(rows)

        if not response_rows:
            recorder.record_decision(
                {
                    "turn": turn,
                    "trigger": "diplomacy blocker detected",
                    "importance": "critical",
                    "background": short_text(current_result),
                    "current_goal": "Advance the turn after resolving the diplomacy UI blocker.",
                    "available_actions": [
                        "pause for human",
                        "retry end_turn",
                        "query diplomacy sessions again",
                    ],
                    "selected_action": "pause for human",
                    "rationale": "end_turn reported a diplomacy blocker, but no open diplomacy session was returned.",
                    "why_not_alternatives": {
                        "retry end_turn": "No blocker was actually resolved.",
                        "query diplomacy sessions again": "A fresh query was already captured for this decision.",
                    },
                    "execution": {
                        "tool": "get_diplomacy_sessions_for_end_turn",
                        "attempt": attempt,
                        "result": sessions,
                    },
                    "outcome": "No open session available to auto-handle.",
                    "related_tool_call_ids": related_tool_call_ids,
                    "related_state_snapshot_ids": [state_id],
                    "related_save_ids": [],
                }
            )
            return str(current_result)

        retry_id, retry_result = await recorder.tool_call(
            "end_turn_after_diplomacy", {"attempt": attempt}, gs.end_turn, turn=turn
        )
        related_tool_call_ids.append(retry_id)
        recorder.record_decision(
            {
                "turn": turn,
                "trigger": "diplomacy blocker detected",
                "importance": "critical",
                "background": short_text(current_result),
                "current_goal": "Advance the same Civ6 turn after automatically handling the diplomacy screen.",
                "available_actions": [
                    "respond positively and continue",
                    "decline trade deal and continue",
                    "close goodbye/war screen and continue",
                    "pause for human",
                ],
                "selected_action": "auto-resolve diplomacy blocker and retry end_turn",
                "rationale": "The run is an automated observation/evolution pass; unresolved leader screens otherwise prevent the real turn counter from advancing.",
                "why_not_alternatives": {
                    "pause": "The blocker type is deterministic and covered by existing connector APIs.",
                    "ignore": "Repeated end_turn calls would keep capturing the same game turn.",
                },
                "execution": {
                    "tool": "diplomacy + end_turn_after_diplomacy",
                    "attempt": attempt,
                    "responses": response_rows,
                    "retry_result": retry_result,
                },
                "outcome": short_text(retry_result),
                "related_tool_call_ids": related_tool_call_ids,
                "related_state_snapshot_ids": [state_id],
                "related_save_ids": [],
            }
        )
        if not end_turn_result_requests_diplomacy_response(retry_result):
            return str(retry_result)
        current_result = retry_result

    return str(current_result)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    db_ref = reader_for_path(path)
    if db_ref is not None:
        reader, logical_path = db_ref
        if reader.has_artifact(logical_path):
            return reader.read_jsonl(logical_path)
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json_artifact(path: Path) -> dict[str, Any]:
    db_ref = reader_for_path(path)
    if db_ref is not None:
        reader, logical_path = db_ref
        if reader.has_artifact(logical_path):
            return reader.read_json(logical_path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_state_rows_for_recorder(recorder: Any) -> list[dict[str, Any]]:
    reader = getattr(recorder, "reader", None)
    if reader is None and getattr(recorder, "root", None):
        try:
            reader = EpisodeReader(recorder.root)
        except Exception:
            reader = None
    if reader is not None and reader.backend == "sqlite":
        return [state for _, state in reader.state_rows()]
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(recorder.states_dir.glob("*.json"))
    ]


def store_report_artifact(recorder: Any, path: Path, content: str, *, kind: str) -> None:
    store = getattr(recorder, "store", None)
    if store is None:
        return
    try:
        logical_path = logical_path_for(recorder.root, path)
    except EpisodeStoreError:
        return
    media_type = "text/html" if path.suffix.lower() == ".html" else "text/markdown"
    store.put_text_artifact(logical_path, content, kind=kind, media_type=media_type)
    store.export_artifact(logical_path)


def store_json_report_artifact(recorder: Any, path: Path, data: Any, *, kind: str) -> None:
    store = getattr(recorder, "store", None)
    if store is None:
        return
    try:
        logical_path = logical_path_for(recorder.root, path)
    except EpisodeStoreError:
        return
    store.put_json_artifact(logical_path, to_jsonable(data), kind=kind)
    store.export_artifact(logical_path)


def decision_field_missing_reason(row: dict[str, Any], key: str) -> str | None:
    if key not in row:
        return "missing"
    value = row[key]
    if value is None:
        return "null"
    if key == "available_actions":
        if not isinstance(value, list):
            return "must be a list"
        if not value:
            return "empty list"
        return None
    if key.startswith("related_"):
        if not isinstance(value, list):
            return "must be a list"
        return None
    if isinstance(value, str) and not value.strip():
        return "empty string"
    if isinstance(value, (list, dict)) and not value:
        return "empty"
    return None


class ExistingEpisodeReportView:
    """Read-only view used to regenerate the HTML report for an existing episode."""

    def __init__(self, episode_id: str) -> None:
        self.episode_id = episode_id
        self.root = ROOT / "episodes" / episode_id
        if not self.root.exists():
            raise FileNotFoundError(f"Episode not found: {self.root}")
        self.raw = self.root / "raw"
        self.states_dir = self.raw / "civ6_states"
        self.saves_dir = self.raw / "saves"
        self.derived = self.root / "derived"
        self.outcome = self.root / "outcome"
        self.assets = self.root / "assets_snapshot"
        self.assets.mkdir(parents=True, exist_ok=True)
        self.header_path = self.root / "header.json"
        self.mcp_path = self.raw / "mcp.jsonl"
        self.tool_calls_path = self.raw / "tool_calls.jsonl"
        self.codex_outputs_path = self.raw / "codex_outputs.jsonl"
        self.decision_path = self.derived / "decision_atoms.jsonl"
        self.report_pack_path = self.derived / "report_pack.json"
        self.timeline_path = self.derived / "timeline.md"
        self.human_draft_path = self.outcome / "observation_report.draft.html"
        self.report_path = self.outcome / "observation_report.html"
        self.agent_handoff_path = self.outcome / "agent_report.md"
        self.agent_report_path = self.outcome / "agent_audit_report.html"
        self.save_index_path = self.saves_dir / "save_index.jsonl"
        self.manifest_path = self.assets / "manifest.json"
        self.active_assets_path = self.assets / "active_assets.json"
        self.reader = EpisodeReader(self.root)
        self.store = self.reader.store

        self.header = self._load_header()
        self.save_name = self.header.get("save_name", DEFAULT_SAVE_NAME)
        self.states = self._load_states()
        self.start_turn, self.final_turn = self._turn_bounds()

        tool_rows = load_jsonl(self.tool_calls_path)
        lua_rows = load_jsonl(self.mcp_path)
        decisions = load_jsonl(self.decision_path)
        saves = load_jsonl(self.save_index_path)
        self.tool_seq = len(tool_rows)
        self.lua_seq = len(lua_rows)
        self.decision_seq = len(decisions)
        self.save_ids = [s.get("save_id") for s in saves if s.get("save_id")]
        self.state_ids = [s.get("snapshot_id") for s in self.states if s.get("snapshot_id")]
        self.tool_error_count = sum(
            1 for row in tool_rows if row.get("success") is False or "error" in row
        )
        self.lua_error_count = sum(
            1 for row in lua_rows if row.get("success") is False or "error" in row
        )
        self.missing_fields = self._collect_gaps()
        self.turn_summaries = self._build_turn_summaries(decisions, saves)

    def _load_header(self) -> dict[str, Any]:
        if self.reader.has_artifact("header.json"):
            return self.reader.read_json("header.json")
        return {}

    def _load_states(self) -> list[dict[str, Any]]:
        return [state for _, state in self.reader.state_rows()]

    def _turn_bounds(self) -> tuple[int | None, int | None]:
        turns = [s.get("turn") for s in self.states if isinstance(s.get("turn"), int)]
        if not turns:
            return None, None
        return min(turns), max(turns)

    def _collect_gaps(self) -> list[dict[str, str]]:
        gaps: list[dict[str, str]] = []
        version_info = self.header.get("civ6_version_info")
        if isinstance(version_info, dict) and not version_info.get("value"):
            gaps.append(
                {
                    "field": "header.civ6_version_info",
                    "reason": str(version_info.get("gap") or "Civ6 version unavailable."),
                    "next_step": str(
                        version_info.get("next_step")
                        or "Add a minimal version metadata query before long runs depend on it."
                    ),
                }
            )
        model_info = self.header.get("codex_model_info")
        if isinstance(model_info, dict) and not model_info.get("value"):
            gaps.append(
                {
                    "field": "header.codex_model_info",
                    "reason": str(
                        model_info.get("gap")
                        or "Codex runtime model metadata unavailable to this runner."
                    ),
                    "next_step": "Set CODEX_HL_CIV6_AGENT_MODEL or add a runtime metadata bridge if exact model provenance is required.",
                }
            )
        for state in self.states:
            for gap in state.get("known_gaps") or []:
                if isinstance(gap, dict):
                    gaps.append(
                        {
                            "field": str(gap.get("field", "state.unknown")),
                            "reason": str(gap.get("reason", "")),
                            "next_step": str(gap.get("next_step", "")),
                        }
                    )
        if not self.reader.has_artifact("assets_snapshot/active_assets.json"):
            gaps.append(
                {
                    "field": "assets_snapshot.active_assets",
                    "reason": "This episode has no strategy asset snapshot.",
                    "next_step": "Do not fabricate historical asset versions; use current catalog only as a low-trust reference.",
                }
            )
        return gaps

    def _build_turn_summaries(
        self, decisions: list[dict[str, Any]], saves: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_turn: dict[int, list[str]] = {}
        for decision in decisions:
            turn = decision.get("turn")
            if not isinstance(turn, int):
                continue
            by_turn.setdefault(turn, []).append(str(decision.get("selected_action", "")))

        saves_by_turn: dict[int, list[str]] = {}
        for save in saves:
            turn = save.get("turn")
            if not isinstance(turn, int):
                continue
            label = save.get("label") or save.get("save_id") or ""
            saves_by_turn.setdefault(turn, []).append(str(label))

        turns = sorted(
            set(by_turn)
            | set(saves_by_turn)
            | {s.get("turn") for s in self.states if isinstance(s.get("turn"), int)}
        )
        summaries: list[dict[str, Any]] = []
        for turn in turns:
            actions = [short_text(action, 140) for action in by_turn.get(turn, []) if action]
            save_labels = saves_by_turn.get(turn, [])
            parts = ["state snapshot captured"]
            if actions:
                parts.append("decisions: " + "; ".join(actions[:6]))
            if save_labels:
                parts.append("saves: " + ", ".join(save_labels))
            summaries.append({"turn": turn, "summary": ". ".join(parts) + "."})
        return summaries

    def write_manifest(self) -> None:
        if self.store is not None:
            self.store.update_episode_run(
                save_name=self.save_name,
                start_turn=self.start_turn,
                final_turn=self.final_turn,
            )
            files = self.store.manifest_file_rows(exclude={"assets_snapshot/manifest.json"})
            storage = {
                "backend": "sqlite",
                "db_path": str(self.root / "episode.db"),
                "schema_version": 1,
                "legacy_tree_role": "cache/export",
            }
        else:
            files = []
            for path in self.root.rglob("*"):
                if path.is_file() and path.name != "episode.db":
                    rel = path.relative_to(self.root).as_posix()
                    files.append(
                        {
                            "path": rel,
                            "size_bytes": path.stat().st_size,
                            "sha256": sha256_file(path),
                        }
                    )
            storage = {"backend": "files", "legacy_tree_role": "source"}
        manifest = {
            "episode_id": self.episode_id,
            "workflow": WORKFLOW_LABEL,
            "generated_at": now_iso(),
            "storage": storage,
            "repo": {
                "root": str(ROOT),
                "commit": run_git(["rev-parse", "HEAD"]),
                "branch": run_git(["branch", "--show-current"]),
                "status_short": run_git(["status", "--short"]),
            },
            "counts": {
                "tool_calls": self.tool_seq,
                "lua_exchanges": self.lua_seq,
                "state_snapshots": len(self.state_ids),
                "decision_atoms": self.decision_seq,
                "indexed_saves": len(self.save_ids),
                "tool_errors": self.tool_error_count,
                "lua_errors": self.lua_error_count,
            },
            "asset_snapshot": asset_snapshot_manifest(self.active_assets_path),
            "files": files,
        }
        if self.store is not None:
            self.store.put_json_artifact("assets_snapshot/manifest.json", manifest, kind="manifest")
            self.store.export_artifact("assets_snapshot/manifest.json")
        else:
            self.manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def generate_report_legacy(recorder: Any) -> None:
    tool_rows = load_jsonl(recorder.tool_calls_path)
    lua_rows = load_jsonl(recorder.mcp_path)
    decisions = load_jsonl(recorder.decision_path)
    saves = load_jsonl(recorder.save_index_path)
    states = sorted(recorder.states_dir.glob("*.json"))

    missing_decision_fields = []
    required_decision_fields = [
        "decision_id",
        "episode_id",
        "turn",
        "trigger",
        "importance",
        "background",
        "current_goal",
        "available_actions",
        "selected_action",
        "rationale",
        "why_not_alternatives",
        "execution",
        "outcome",
        "related_tool_call_ids",
        "related_state_snapshot_ids",
        "related_save_ids",
    ]
    for d in decisions:
        for key in required_decision_fields:
            reason = decision_field_missing_reason(d, key)
            if reason:
                missing_decision_fields.append(
                    {
                        "decision_id": d.get("decision_id", "?"),
                        "field": key,
                        "reason": reason,
                    }
                )

    actual_turns = 0
    if recorder.start_turn is not None and recorder.final_turn is not None:
        actual_turns = max(0, recorder.final_turn - recorder.start_turn)

    state_turns = []
    for path in states:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            state_turns.append(row.get("turn"))
        except Exception:
            pass

    gaps = recorder.missing_fields + [
        {
            "field": f"decision.{m['decision_id']}.{m['field']}",
            "reason": m["reason"],
            "next_step": "Fill this field before accepting the T50 run.",
        }
        for m in missing_decision_fields
    ]
    if not gaps:
        gaps = [
            {
                "field": "none",
                "reason": "No required short-run fields were missing in generated artifacts.",
                "next_step": "Human should inspect raw files before approving T50.",
            }
        ]

    def yes_no(value: bool) -> str:
        return "PASS" if value else "FAIL"

    tool_complete = bool(tool_rows) and all("result_raw" in r or "error" in r for r in tool_rows)
    mcp_complete = bool(lua_rows) and all("request" in r and ("response" in r or "error" in r) for r in lua_rows)
    states_complete = bool(states) and len(states) >= max(1, actual_turns)
    decisions_complete = bool(decisions) and not missing_decision_fields
    save_complete = len(saves) >= 2 and all(
        s.get("episode_id")
        and s.get("turn") is not None
        and (s.get("decision_id") or s.get("event") or s.get("label"))
        and s.get("episode_path")
        and s.get("sha256")
        for s in saves
    )

    turn_blocks = []
    for summary in recorder.turn_summaries:
        turn_blocks.append(
            "<li>"
            f"<strong>T{html.escape(str(summary.get('turn')))}</strong>: "
            f"{html.escape(summary.get('summary', ''))}"
            "</li>"
        )

    gap_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(g.get('field', ''))}</td>"
        f"<td>{html.escape(g.get('reason', ''))}</td>"
        f"<td>{html.escape(g.get('next_step', ''))}</td>"
        "</tr>"
        for g in gaps
    )
    save_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(s.get('save_id', ''))}</td>"
        f"<td>{html.escape(str(s.get('turn', '')))}</td>"
        f"<td>{html.escape(str(s.get('decision_id') or ''))}</td>"
        f"<td>{html.escape(s.get('label', ''))}</td>"
        f"<td>{html.escape(s.get('event', ''))}</td>"
        f"<td>{html.escape(s.get('episode_path', ''))}</td>"
        f"<td>{html.escape(s.get('sha256', '')[:16])}</td>"
        "</tr>"
        for s in saves
    )

    report = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Codex HL Observation Short Run Report - {html.escape(recorder.episode_id)}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #1f2937; line-height: 1.45; }}
    h1, h2 {{ color: #111827; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; max-width: 1100px; }}
    .box {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 12px; background: #f9fafb; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0 24px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    code {{ background: #eef2ff; padding: 1px 4px; border-radius: 4px; }}
    .pass {{ color: #047857; font-weight: 700; }}
    .fail {{ color: #b91c1c; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Codex HL Observation 短跑验收报告</h1>
  <p><strong>Workflow:</strong> {WORKFLOW_LABEL}. 本报告只用于 3-10 回合短跑验收；人类确认前不继续 T50。</p>

  <h2>Episode 基本信息</h2>
  <div class="grid">
    <div class="box"><strong>episode_id</strong><br><code>{html.escape(recorder.episode_id)}</code></div>
    <div class="box"><strong>save</strong><br>{html.escape(recorder.save_name)}</div>
    <div class="box"><strong>start_turn</strong><br>{html.escape(str(recorder.start_turn))}</div>
    <div class="box"><strong>final_turn</strong><br>{html.escape(str(recorder.final_turn))}</div>
    <div class="box"><strong>实际推进回合数</strong><br>{actual_turns}</div>
    <div class="box"><strong>repo</strong><br>{html.escape(str(ROOT))}</div>
  </div>

  <h2>每回合发生了什么</h2>
  <ul>
    {''.join(turn_blocks) if turn_blocks else '<li>No turn summaries recorded.</li>'}
  </ul>

  <h2>四类记录验收</h2>
  <table>
    <tr><th>类别</th><th>状态</th><th>证据</th></tr>
    <tr><td>全部工具调用和返回结果</td><td class="{ 'pass' if tool_complete and mcp_complete else 'fail' }">{yes_no(tool_complete and mcp_complete)}</td><td><code>raw/tool_calls.jsonl</code>: {len(tool_rows)} calls; <code>raw/mcp.jsonl</code>: {len(lua_rows)} Lua exchanges; errors: tool={recorder.tool_error_count}, lua={recorder.lua_error_count}</td></tr>
    <tr><td>每回合状态快照</td><td class="{ 'pass' if states_complete else 'fail' }">{yes_no(states_complete)}</td><td><code>raw/civ6_states/</code>: {len(states)} snapshots; turns={html.escape(str(sorted(set(state_turns))))}</td></tr>
    <tr><td>关键决策记录</td><td class="{ 'pass' if decisions_complete else 'fail' }">{yes_no(decisions_complete)}</td><td><code>derived/decision_atoms.jsonl</code>: {len(decisions)} records; missing required fields={len(missing_decision_fields)}</td></tr>
    <tr><td>存档与回合/决策关联</td><td class="{ 'pass' if save_complete else 'fail' }">{yes_no(save_complete)}</td><td><code>raw/saves/save_index.jsonl</code>: {len(saves)} indexed saves</td></tr>
  </table>

  <h2>存档索引</h2>
  <table>
    <tr><th>save_id</th><th>turn</th><th>decision_id</th><th>label</th><th>event</th><th>episode path</th><th>sha256 prefix</th></tr>
    {save_rows}
  </table>

  <h2>缺失字段清单</h2>
  <table>
    <tr><th>field</th><th>why unavailable / missing</th><th>next step</th></tr>
    {gap_rows}
  </table>

  <h2>原始证据入口</h2>
  <ul>
    <li><code>header.json</code></li>
    <li><code>raw/mcp.jsonl</code></li>
    <li><code>raw/tool_calls.jsonl</code></li>
    <li><code>raw/codex_outputs.jsonl</code></li>
    <li><code>raw/civ6_states/*.json</code></li>
    <li><code>derived/decision_atoms.jsonl</code></li>
    <li><code>derived/timeline.md</code></li>
    <li><code>assets_snapshot/manifest.json</code></li>
  </ul>
</body>
</html>
"""
    recorder.report_path.write_text(report, encoding="utf-8")


def json_pretty(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, indent=2, default=str)


def html_pre(value: Any) -> str:
    return html.escape(json_pretty(value))


def text_preview(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(to_jsonable(value), ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def details_block(summary: str, value: Any, css_class: str = "") -> str:
    klass = f' class="{css_class}"' if css_class else ""
    return (
        f"<details{klass}>"
        f"<summary>{html.escape(summary)}</summary>"
        f"<pre>{html_pre(value)}</pre>"
        "</details>"
    )


def yes_no(value: bool) -> str:
    return "PASS" if value else "FAIL"


def joined_ids(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def state_metric_summary(state: dict[str, Any]) -> str:
    overview = state.get("overview") or {}
    research = state.get("research_civic") or {}
    cities = state.get("cities") or []
    units = state.get("units") or []
    notifications = state.get("notifications") or []
    threats = state.get("threats") or []
    production = state.get("production") or {}

    city_names = []
    if isinstance(cities, list):
        for city in cities:
            if isinstance(city, dict):
                city_names.append(str(city.get("name") or city.get("city_name") or city.get("id")))
    unit_names = []
    if isinstance(units, list):
        for unit in units:
            if isinstance(unit, dict):
                unit_names.append(str(unit.get("name") or unit.get("unit_type") or unit.get("unit_id")))

    return (
        f"文明={overview.get('civ_name')}; 城市={len(cities) if isinstance(cities, list) else 'unknown'}"
        f"({', '.join(city_names[:5])}); 单位={len(units) if isinstance(units, list) else 'unknown'}"
        f"({', '.join(unit_names[:6])}); 通知={len(notifications) if isinstance(notifications, list) else 'unknown'};"
        f" 威胁={len(threats) if isinstance(threats, list) else 'unknown'};"
        f" 科技={research.get('current_research')}; 市政={research.get('current_civic')};"
        f" 生产记录={'有' if production else '空/无城市或无可取生产'}"
    )


def state_field_status(state: dict[str, Any], key: str) -> str:
    if key not in state:
        return "缺失"
    value = state.get(key)
    if value is None:
        return "不可用"
    if isinstance(value, (list, dict)) and not value:
        return "已记录为空"
    return "已记录"


def render_tool_rows(tool_rows: list[dict[str, Any]]) -> str:
    rows = []
    for row in tool_rows:
        status = "成功" if row.get("success") is not False and "error" not in row else "错误"
        result = row.get("result_raw") if "result_raw" in row else row.get("error")
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('tool_call_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('turn', '')))}</td>"
            f"<td>{html.escape(str(row.get('tool', '')))}</td>"
            f"<td>{html.escape(str(row.get('ts_start', '')))}</td>"
            f"<td>{html.escape(str(row.get('duration_ms', '')))}</td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{html.escape(text_preview(row.get('params'), 180))}</td>"
            f"<td>{html.escape(text_preview(result, 260))}</td>"
            f"<td>{details_block('查看这一条完整原始记录', row)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_lua_rows(lua_rows: list[dict[str, Any]]) -> str:
    rows = []
    for row in lua_rows:
        status = "成功" if row.get("success") is not False and "error" not in row else "错误"
        response = row.get("response") if "response" in row else row.get("error")
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('call_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('context', '')))}</td>"
            f"<td>{html.escape(str(row.get('ts_start', '')))}</td>"
            f"<td>{html.escape(str(row.get('duration_ms', '')))}</td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{html.escape(text_preview(row.get('request'), 260))}</td>"
            f"<td>{html.escape(text_preview(response, 260))}</td>"
            f"<td>{details_block('查看这一条完整 Lua/MCP 原始记录', row)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_state_sections(state_rows: list[dict[str, Any]]) -> str:
    required = [
        ("empire", "帝国/全局"),
        ("cities", "城市"),
        ("units", "单位"),
        ("notifications", "通知"),
        ("threats", "威胁"),
        ("research_civic", "科技/市政"),
        ("production", "生产"),
    ]
    sections = []
    for state in state_rows:
        coverage = "".join(
            "<tr>"
            f"<td>{label}</td>"
            f"<td><code>{key}</code></td>"
            f"<td>{html.escape(state_field_status(state, key))}</td>"
            f"<td>{html.escape(text_preview(state.get(key), 220))}</td>"
            "</tr>"
            for key, label in required
        )
        gaps = state.get("known_gaps") or []
        gap_text = "无状态字段缺口" if not gaps else text_preview(gaps, 800)
        sections.append(
            "<section class=\"record-card\">"
            f"<h3>T{html.escape(str(state.get('turn')))} 状态快照："
            f"<code>{html.escape(str(state.get('snapshot_id', '')))}</code></h3>"
            f"<p>{html.escape(state_metric_summary(state))}</p>"
            "<table>"
            "<tr><th>覆盖项</th><th>字段</th><th>状态</th><th>页面摘要</th></tr>"
            f"{coverage}"
            "</table>"
            f"<p><strong>拿不到/不完整的状态：</strong>{html.escape(gap_text)}</p>"
            f"{details_block('展开这一回合完整状态快照原始 JSON', state)}"
            "</section>"
        )
    return "\n".join(sections)


def render_decision_sections(decisions: list[dict[str, Any]]) -> str:
    sections = []
    for decision in decisions:
        alternatives = decision.get("why_not_alternatives")
        execution = decision.get("execution")
        sections.append(
            "<section class=\"record-card\">"
            f"<h3>T{html.escape(str(decision.get('turn')))} "
            f"{html.escape(str(decision.get('decision_id', '')))}："
            f"{html.escape(str(decision.get('selected_action', '')))}</h3>"
            "<table>"
            f"<tr><th>触发</th><td>{html.escape(text_preview(decision.get('trigger'), 800))}</td></tr>"
            f"<tr><th>重要性</th><td>{html.escape(text_preview(decision.get('importance'), 800))}</td></tr>"
            f"<tr><th>当前背景</th><td>{html.escape(text_preview(decision.get('background'), 1200))}</td></tr>"
            f"<tr><th>当前目标</th><td>{html.escape(text_preview(decision.get('current_goal'), 1200))}</td></tr>"
            f"<tr><th>候选动作 available_actions</th><td><pre>{html_pre(decision.get('available_actions'))}</pre></td></tr>"
            f"<tr><th>选择动作</th><td>{html.escape(text_preview(decision.get('selected_action'), 1200))}</td></tr>"
            f"<tr><th>选择理由</th><td>{html.escape(text_preview(decision.get('rationale'), 1600))}</td></tr>"
            f"<tr><th>为什么没选其他动作</th><td><pre>{html_pre(alternatives)}</pre></td></tr>"
            f"<tr><th>执行记录</th><td><pre>{html_pre(execution)}</pre></td></tr>"
            f"<tr><th>执行后结果/阻塞/回看点</th><td>{html.escape(text_preview(decision.get('outcome'), 1600))}</td></tr>"
            f"<tr><th>关联 tool_call_ids</th><td>{html.escape(joined_ids(decision.get('related_tool_call_ids')))}</td></tr>"
            f"<tr><th>关联 state_snapshot_ids</th><td>{html.escape(joined_ids(decision.get('related_state_snapshot_ids')))}</td></tr>"
            f"<tr><th>关联 save_ids</th><td>{html.escape(joined_ids(decision.get('related_save_ids')))}</td></tr>"
            "</table>"
            f"{details_block('展开这一条 decision_atom 原始 JSON', decision)}"
            "</section>"
        )
    return "\n".join(sections)


def render_save_rows(saves: list[dict[str, Any]]) -> str:
    rows = []
    for save in saves:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(save.get('save_id', '')))}</td>"
            f"<td>{html.escape(str(save.get('episode_id', '')))}</td>"
            f"<td>{html.escape(str(save.get('turn', '')))}</td>"
            f"<td>{html.escape(str(save.get('decision_id') or ''))}</td>"
            f"<td>{html.escape(str(save.get('label', '')))}</td>"
            f"<td>{html.escape(str(save.get('event', '')))}</td>"
            f"<td>{html.escape(str(save.get('episode_path', '')))}</td>"
            f"<td>{html.escape(str(save.get('sha256', '')))}</td>"
            f"<td>{details_block('展开这一条存档索引原始 JSON', save)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def decision_category(decision: dict[str, Any]) -> str:
    text = " ".join(
        str(decision.get(key, ""))
        for key in ("trigger", "selected_action", "current_goal")
    ).lower()
    if "settler" in text or "found_city" in text:
        return "定居/城市建立"
    if "production" in text or "builder" in text or "unit " in text:
        return "城市生产"
    if "research" in text or "tech" in text:
        return "科技"
    if "civic" in text:
        return "市政"
    if "unit action" in text or "fortify" in text or "move" in text:
        return "单位行动/探索"
    if "end turn" in text or "turn completion" in text:
        return "回合推进"
    return "其他"


def render_error_rows(tool_rows: list[dict[str, Any]], lua_rows: list[dict[str, Any]]) -> str:
    rows = []
    for row in tool_rows:
        if row.get("success") is False or "error" in row:
            rows.append(
                "<tr>"
                f"<td>tool</td><td>{html.escape(str(row.get('tool_call_id', '')))}</td>"
                f"<td>{html.escape(str(row.get('turn', '')))}</td>"
                f"<td>{html.escape(str(row.get('tool', '')))}</td>"
                f"<td>{html.escape(text_preview(row.get('error') or row.get('result_raw'), 500))}</td>"
                f"<td>{details_block('展开错误原始记录', row)}</td>"
                "</tr>"
            )
    for row in lua_rows:
        if row.get("success") is False or "error" in row:
            rows.append(
                "<tr>"
                f"<td>MCP/Lua</td><td>{html.escape(str(row.get('call_id', '')))}</td>"
                f"<td>{html.escape(str(row.get('context', '')))}</td>"
                f"<td>{html.escape(str(row.get('context', '')))}</td>"
                f"<td>{html.escape(text_preview(row.get('error') or row.get('response'), 500))}</td>"
                f"<td>{details_block('展开错误原始记录', row)}</td>"
                "</tr>"
            )
    if not rows:
        return '<tr><td colspan="6">没有记录到 tool 或 MCP/Lua 错误。</td></tr>'
    return "\n".join(rows)


def render_codex_review_layer(
    *,
    actual_turns: int,
    state_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    saves: list[dict[str, Any]],
    tool_rows: list[dict[str, Any]],
    lua_rows: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    missing_state_cells: list[tuple[Any, str]],
    missing_decision_fields: list[dict[str, Any]],
) -> str:
    first_state = state_rows[0] if state_rows else {}
    final_state = state_rows[-1] if state_rows else {}
    first_overview = first_state.get("overview") or {}
    final_overview = final_state.get("overview") or {}

    categories: dict[str, list[str]] = {}
    for decision in decisions:
        categories.setdefault(decision_category(decision), []).append(
            f"{decision.get('decision_id')} T{decision.get('turn')}: {decision.get('selected_action')}"
        )
    category_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(category)}</td>"
        f"<td>{len(items)}</td>"
        f"<td>{html.escape('; '.join(items))}</td>"
        "</tr>"
        for category, items in categories.items()
    )

    turn_story = []
    decisions_by_turn: dict[int, list[dict[str, Any]]] = {}
    saves_by_turn: dict[int, list[dict[str, Any]]] = {}
    for decision in decisions:
        if isinstance(decision.get("turn"), int):
            decisions_by_turn.setdefault(decision["turn"], []).append(decision)
    for save in saves:
        if isinstance(save.get("turn"), int):
            saves_by_turn.setdefault(save["turn"], []).append(save)
    for state in state_rows:
        turn = state.get("turn")
        decision_text = "；".join(
            f"{d.get('decision_id')}={d.get('selected_action')}"
            for d in decisions_by_turn.get(turn, [])
        )
        save_text = "；".join(
            f"{s.get('save_id')}={s.get('label')}"
            for s in saves_by_turn.get(turn, [])
        )
        turn_story.append(
            "<tr>"
            f"<td>T{html.escape(str(turn))}</td>"
            f"<td>{html.escape(state_metric_summary(state))}</td>"
            f"<td>{html.escape(decision_text or '无决策记录')}</td>"
            f"<td>{html.escape(save_text or '无存档')}</td>"
            "</tr>"
        )

    mode_zh = observation_mode_zh(actual_turns)
    next_boundary = (
        "本报告停在 T50，不继续 T51+，也不进入 Review。"
        if observation_mode(actual_turns) == "t50_observation"
        else "人工接受前不继续 T50。"
    )
    review_notes = [
        f"这份{mode_zh}报告已经把原始证据和人工 review 视图放在同一个 HTML 里：先看本导读确认观测范围，再按需展开底层 JSON。",
        "当前记录机制证明了链路能覆盖起点加载、回合开始状态、关键决策、工具执行结果、回合后 checkpoint 和最终 checkpoint。",
        "决策后结果目前主要来自 tool 返回值、decision outcome 和回合后存档；不是每一个非 end-turn 决策后都额外抓取 after-state 快照。",
        f"本报告只陈述观测到什么和证据在哪里，不把{mode_zh}决策转化为策略改进，也不做失败归因或 promote/reject。{next_boundary}",
    ]
    if observation_mode(actual_turns) == "t50_observation":
        review_questions = [
            "这个 T50 episode 是否完整覆盖了你要看的 50 回合证据链？",
            "四类证据里是否有任何缺口足以阻止进入 Review 或后续评估？",
            "T50 报告是否足够支持后续只读复盘，而不需要重新打开游戏补证据？",
        ]
    else:
        review_questions = [
            "你是否接受 T50 继续沿用同一套 evidence schema：tool/MCP 原始日志、turn-start state、decision_atoms、save_index？",
            "你是否要求每个关键决策执行后都额外补一份 after-decision state snapshot，而不是只依赖 tool result/outcome 和 after-turn checkpoint？",
            "你希望 T50 报告按什么维度优先 review：早期战略、城市发展、探索路径、生产/科技/市政选择、单位行动，还是工具覆盖缺口？",
            "当前 Civ6 版本和 Codex 运行模型信息仍是环境元数据缺口；是否需要在 T50 前补采这些 provenance 字段？",
        ]

    gap_summary = "没有必填字段缺失。" if not missing_decision_fields and not missing_state_cells else (
        f"状态字段缺失 {len(missing_state_cells)} 个，决策字段缺失 {len(missing_decision_fields)} 个。"
    )
    env_gap_count = len([g for g in gaps if str(g.get("field", "")).startswith("header.")])

    return f"""
  <h2 id="review">Codex review 版导读</h2>
  <section class="review-panel">
    <h3>一句话结论</h3>
    <p>这次{html.escape(mode_zh)}从 T{html.escape(str(first_state.get('turn', '?')))} 到 T{html.escape(str(final_state.get('turn', '?')))}，实际推进 {actual_turns} 回合。记录链路已覆盖四类 Observation 证据；页面下方可以逐条展开原始 tool、MCP/Lua、state、decision、save 记录。</p>
  </section>

  <section class="review-panel">
    <h3>我实际观测到的局面变化</h3>
    <p>起点：{html.escape(text_preview(first_overview, 900))}</p>
    <p>终点：{html.escape(text_preview(final_overview, 900))}</p>
    <table>
      <tr><th>回合</th><th>状态摘要</th><th>该回合记录到的决策</th><th>关联存档</th></tr>
      {''.join(turn_story)}
    </table>
  </section>

  <section class="review-panel">
    <h3>关键决策覆盖地图</h3>
    <p>这里按 review 语义把 decision_atoms 重新归类，方便你快速判断“我到底记录了哪些类型的决策”。</p>
    <table>
      <tr><th>类别</th><th>数量</th><th>决策</th></tr>
      {category_rows}
    </table>
  </section>

  <section class="review-panel">
    <h3>证据质量和边界</h3>
    <ul>
      {''.join(f'<li>{html.escape(note)}</li>' for note in review_notes)}
    </ul>
    <p><strong>缺口摘要：</strong>{html.escape(gap_summary)} 环境/provenance 类缺口 {env_gap_count} 个；完整清单见“缺失字段清单”。</p>
  </section>

  <section class="review-panel">
    <h3>建议你重点 review 的问题</h3>
    <ol>
      {''.join(f'<li>{html.escape(question)}</li>' for question in review_questions)}
    </ol>
  </section>

  <section class="review-panel">
    <h3>错误和异常入口</h3>
    <p>错误不被隐藏；它们是原始证据的一部分。这里集中列出，方便你判断是否影响验收。</p>
    <table>
      <tr><th>来源</th><th>ID</th><th>turn/context</th><th>tool/context</th><th>错误/返回摘要</th><th>完整原始记录</th></tr>
      {render_error_rows(tool_rows, lua_rows)}
    </table>
  </section>
"""


DISPLAY_NAMES = {
    "TECH_MINING": "采矿业",
    "TECH_POTTERY": "制陶术",
    "TECH_ANIMAL_HUSBANDRY": "畜牧业",
    "TECH_SAILING": "航海术",
    "TECH_ASTROLOGY": "占星术",
    "UNIT_BUILDER": "建造者",
    "UNIT_SCOUT": "侦察兵",
    "UNIT_WARRIOR": "勇士",
    "UNIT_SLINGER": "投石兵",
    "BUILDING_MONUMENT": "纪念碑",
    "BUILDING_GRANARY": "粮仓",
    "CIVIC_CODE_OF_LAWS": "法典",
}


def humanize(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "set tech ": "选择科技：",
        "continue current research": "继续当前科技",
        "continue current civic": "继续当前市政",
        "found_city on current tile": "原地建立首都",
        "fortify/hold": "驻守/防御",
        "fortify": "驻守",
        "end turn now": "结束本回合",
        "continue active production": "继续当前生产",
        "UNIT UNIT_BUILDER": "生产建造者",
        "UNIT UNIT_SCOUT": "生产侦察兵",
        "UNIT UNIT_WARRIOR": "生产勇士",
        "UNIT UNIT_SLINGER": "生产投石兵",
        "BUILDING BUILDING_MONUMENT": "建造纪念碑",
        "change research manually": "手动改科技",
        "change civic manually": "手动改市政",
        "defer": "暂不处理",
        "skip": "跳过",
    }
    for raw, label in {**DISPLAY_NAMES, **replacements}.items():
        text = text.replace(raw, label)
    return text


REASON_TRANSLATIONS = {
    "Pick the first available item from the conservative early-game priority list; this is a blocker-resolution choice, not a learned strategy update.": "从固定的早期保守优先级里选择第一个当前可用项；这只是解除阻塞，不是从短跑中学习出的策略更新。",
    "A civic target is already active; Observation records the state instead of changing policy.": "当前已经有市政目标。Observation 的职责是记录状态，不主动改写市政路线。",
    "With zero cities, founding immediately is the least speculative action and resolves the main opening blocker.": "当前没有城市；原地建城是最少引入猜测的动作，也能解除开局无法生产、成长和稳定产出的主要阻塞。",
    "No specific recorded tactical target justified movement; fortify/hold avoids speculative exploration in the short validation run.": "快照里没有足够明确的战术目标、敌人或指定探索路线；选择驻守可以避免把推测性探索混进短跑验收。",
    "The short run needs 3-10 real turns; all prior choices and tool calls have been logged.": "短跑需要推进 3-10 个真实回合；本回合前面的选择、工具调用和状态记录已经落盘。",
    "The Observation observation needs the requested real turns; all prior choices and tool calls have been logged.": "本次 Observation 观测需要推进请求的真实回合数；本回合前面的选择、工具调用和状态记录已经落盘。",
    "A research target is already active; Observation should observe rather than rewrite the plan.": "当前已经有科技目标。Observation 应该观察并记录，而不是无阻塞地重写路线。",
    "Use repair first if needed, otherwise a static conservative priority list. This does not update the main strategy.": "如果有修理项先修理，否则按固定保守优先级选择。这个选择只用于解除生产阻塞，不更新主策略。",
    "The city has an active queue; changing it would be a strategy intervention.": "城市已经有生产队列。主动切换生产会变成策略干预，不符合本次只观测的边界。",
    "Lower priority or slower according to the static list used only for this run.": "在本次短跑使用的固定优先级里排序更低，或不如当前选择适合解除阻塞。",
    "End turn would be blocked by missing research.": "如果科技保持为空，结束回合会被阻塞。",
    "Would modify strategy outside observation scope.": "这会在没有必要阻塞的情况下改写策略，超出 Observation 观测范围。",
    "No action is required.": "当前不需要额外操作。",
    "Would intentionally alter opening strategy without a stronger recorded reason.": "在没有更强证据的情况下移动开拓者，会主动改变开局策略。",
    "Delays all production and research.": "等待会推迟城市、生产和稳定科研文化产出。",
    "No explicit safe target was selected from the snapshot.": "当前快照没有记录到明确、安全、值得移动的目标格。",
    "No attack was chosen without a recorded target and combat estimate.": "没有记录到攻击目标和战斗评估，因此不选择攻击。",
    "Deferred to keep Observation observation focused on evidence capture.": "为保持 Observation 聚焦证据采集，暂不做额外策略动作。",
    "The required per-turn state snapshot was already captured.": "本回合要求的开始状态快照已经记录。",
    "Would move beyond observation and blocker handling.": "这会超出观测和必要阻塞处理的范围。",
    "No validation-report boundary has been reached yet.": "尚未到短跑验收报告的暂停边界。",
    "Would alter live strategy without a blocker.": "没有阻塞时改科技会改变真实对局策略。",
    "Recorded as available actions but lower in the static blocker-resolution priority.": "这些选项已经作为候选项记录，但在固定的阻塞处理优先级里低于当前选择。",
    "End turn may be blocked and the city would waste production.": "城市空转可能阻塞结束回合，也会浪费生产。",
    "Not needed to advance the turn.": "推进回合不需要改生产。",
    "Equivalent to continuing the active queue.": "实际效果等同于继续当前生产队列。",
}


KEY_TRANSLATIONS = {
    "other available techs": "其他可选科技",
    "leave unset": "保持未选择",
    "change civic manually": "手动改市政",
    "defer": "暂不处理",
    "move settler before founding": "先移动开拓者再建城",
    "wait": "等待",
    "move": "移动单位",
    "attack": "攻击",
    "other": "其他动作",
    "query more state": "继续查询状态",
    "make additional changes": "做额外改动",
    "pause run": "暂停运行",
    "change research manually": "手动改科技",
    "other production options": "其他生产选项",
    "leave idle": "让城市空转",
    "change production": "改生产",
}


def human_reason(value: Any) -> str:
    text = str(value or "")
    if text in REASON_TRANSLATIONS:
        return REASON_TRANSLATIONS[text]
    return humanize(text)


def human_key(value: Any) -> str:
    text = str(value or "")
    return KEY_TRANSLATIONS.get(text, humanize(text))


def human_outcome(value: Any) -> str:
    text = humanize(value)
    if text.startswith("RESEARCHING|"):
        return "已开始研究：" + text.split("|", 1)[1]
    if text.startswith("FOUNDED|"):
        return "已建立城市，坐标：" + text.split("|", 1)[1]
    if text == "FORTIFIED":
        return "单位已驻守。"
    if text.startswith("ALREADY_FORTIFIED|"):
        return "单位已经处于驻守状态；" + text.split("|", 1)[1].replace("Fortify turns", "驻守回合")
    if text.startswith("PRODUCING|"):
        parts = text.split("|")
        if len(parts) >= 3:
            return f"城市已开始生产：{humanize(parts[1])}，预计 {parts[2].replace('turns', '回合')}。"
    text = text.replace("Turn ", "回合 ")
    text = text.replace("Score", "分数")
    text = text.replace("== Action Required ==", "需要处理")
    text = text.replace("Use: set_city_production(city_id=..., item_type=..., item_name=...)", "需要调用城市生产选择工具。")
    return text


def human_list(values: Any) -> str:
    if not values:
        return "无"
    if isinstance(values, list):
        return "；".join(humanize(v) for v in values)
    return humanize(values)


def fmt_num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def delta_line(label: str, start: Any, end: Any, suffix: str = "") -> str:
    try:
        delta = end - start
        sign = "+" if delta > 0 else ""
        return f"{label}: {fmt_num(start)} -> {fmt_num(end)} ({sign}{fmt_num(delta)}{suffix})"
    except Exception:
        return f"{label}: {fmt_num(start)} -> {fmt_num(end)}"


def city_sentence(state: dict[str, Any]) -> str:
    cities = state.get("cities") or []
    if not cities:
        return "没有城市。"
    city = cities[0]
    if not isinstance(city, dict):
        return f"城市数量 {len(cities)}。"
    return (
        f"{city.get('name', '城市')}位于 ({city.get('x')}, {city.get('y')})，"
        f"人口 {city.get('population')}，住房 {fmt_num(city.get('housing'))}，宜居度 {city.get('amenities')}，"
        f"食物 {fmt_num(city.get('food_stored'))}/{fmt_num(city.get('growth_threshold'))}，"
        f"预计 {city.get('turns_to_grow')} 回合后增长。"
    )


def production_sentence(state: dict[str, Any]) -> str:
    cities = state.get("cities") or []
    if not cities or not isinstance(cities[0], dict):
        return "没有城市生产队列。"
    city = cities[0]
    building = city.get("currently_building")
    if not building or str(building).lower() == "nothing":
        return f"{city.get('name', '城市')}尚未选择生产项目。"
    return (
        f"{city.get('name', '城市')}正在生产 {humanize(building)}，"
        f"预计还需 {city.get('production_turns_left')} 回合。"
    )


def unit_sentence(state: dict[str, Any]) -> str:
    units = state.get("units") or []
    if not units:
        return "没有可记录单位。"
    parts = []
    for unit in units:
        if isinstance(unit, dict):
            parts.append(
                f"{unit.get('name', unit.get('unit_type'))}在 ({unit.get('x')}, {unit.get('y')})，"
                f"生命 {unit.get('health')}/{unit.get('max_health')}，移动力 {fmt_num(unit.get('moves_remaining'))}/{fmt_num(unit.get('max_moves'))}"
            )
    return "；".join(parts) + "。"


def emptyish(value: Any) -> bool:
    return value is None or str(value).strip().lower() in {"", "none", "null", "nothing"}


def overview_sentence(state: dict[str, Any]) -> str:
    overview = state.get("overview") or {}
    threats = state.get("threats") or []
    notifications = state.get("notifications") or []
    research = "科技为空" if emptyish(overview.get("current_research")) else f"科技为{humanize(overview.get('current_research'))}"
    civic = "市政为空" if emptyish(overview.get("current_civic")) else f"市政为《{humanize(overview.get('current_civic'))}》"
    return (
        f"城市 {overview.get('num_cities', 0)}，单位 {overview.get('num_units', 0)}；"
        f"金币 {fmt_num(overview.get('gold', 0))}（每回合 {fmt_num(overview.get('gold_per_turn', 0))}），"
        f"科研 {fmt_num(overview.get('science_yield', 0))}，文化 {fmt_num(overview.get('culture_yield', 0))}；"
        f"{research}，{civic}；通知 {len(notifications)} 条，威胁 {len(threats)} 条。"
    )


def metric_chip(label: str, start: Any, end: Any, suffix: str = "") -> str:
    delta_class = "neutral"
    try:
        delta = end - start
        delta_text = f"{'+' if delta > 0 else ''}{fmt_num(delta)}{suffix}"
        if delta > 0:
            delta_class = "positive"
        elif delta < 0:
            delta_class = "negative"
    except Exception:
        delta_text = "n/a"
    return (
        "<div class=\"metric-chip\">"
        f"<span>{html.escape(label)}</span>"
        f"<strong>{html.escape(fmt_num(start))} → {html.escape(fmt_num(end))}</strong>"
        f"<em class=\"{delta_class}\">{html.escape(delta_text)}</em>"
        "</div>"
    )


def code_badges(values: Any) -> str:
    if not values:
        return "<span>无</span>"
    if not isinstance(values, list):
        values = [values]
    return "".join(f"<code>{html.escape(str(value))}</code>" for value in values)


def basename_text(value: Any) -> str:
    text = str(value or "")
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def decision_flow_narrative(decision: dict[str, Any]) -> dict[str, str]:
    trigger = str(decision.get("trigger", ""))
    selected = humanize(decision.get("selected_action"))
    actions = human_list(decision.get("available_actions"))
    rationale = human_reason(decision.get("rationale"))
    outcome = human_outcome(decision.get("outcome"))
    why_not = decision.get("why_not_alternatives") or {}
    if isinstance(why_not, dict):
        why_not_text = "；".join(
            f"{human_key(k)}：{human_reason(v)}" for k, v in why_not.items()
        )
    else:
        why_not_text = human_reason(why_not)

    if "missing research" in trigger:
        observed = "科技槽为空，如果不选择科技，后续结束回合会被阻塞。"
        meaning = "这是解除规则阻塞的选择，不代表从短跑中学到的新策略。"
    elif "civic review" in trigger:
        observed = "市政已经在研究《法典》，没有出现必须改动的阻塞。"
        meaning = "这里的重点是确认没有无故改写市政路线。"
    elif "opening settler" in trigger:
        observed = "开局没有城市，只有开拓者和勇士；没有城市就没有生产、人口和稳定科研文化产出。"
        meaning = "这一步把存档从开局单位状态推进到可持续记录城市状态的局面。"
    elif "production" in trigger:
        observed = "城市生产为空或已有生产队列，需要确认是否处理生产阻塞。"
        meaning = "这是城市运营链路的关键样本：报告记录了可选项目、选择理由和执行结果。"
    elif "unit action" in trigger:
        observed = "勇士有行动能力，但当前快照没有记录到明确目标、敌人或指定探索路线。"
        meaning = "短跑阶段选择驻守，避免把探索策略改进混进 Observation 观测。"
    elif "turn completion" in trigger:
        observed = "本回合必须处理的科技、城市、单位等阻塞已经记录并处理。"
        meaning = "结束回合用于验证记录链路能跨回合延续，并产生 checkpoint 存档。"
    elif "research review" in trigger:
        observed = "当前科技已经是采矿业，不存在空科技阻塞。"
        meaning = "这里验证了 runner 能记录“继续当前选择”，而不是只记录主动改动。"
    else:
        observed = humanize(decision.get("background"))
        meaning = "作为 Observation 观测记录保留，供后续复盘判断。"

    return {
        "observed": observed,
        "actions": actions,
        "selected": selected,
        "rationale": rationale,
        "why_not": why_not_text or "无",
        "outcome": outcome,
        "meaning": meaning,
    }


def build_human_decision_flow(decisions: list[dict[str, Any]]) -> str:
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for decision in decisions:
        turn = decision.get("turn")
        if isinstance(turn, int):
            by_turn.setdefault(turn, []).append(decision)

    blocks = []
    for turn in sorted(by_turn):
        rows = []
        for decision in by_turn[turn]:
            flow = decision_flow_narrative(decision)
            rows.append(
                "<article class=\"decision-card\">"
                "<header class=\"decision-header\">"
                f"<span class=\"decision-id\">{html.escape(str(decision.get('decision_id')))}</span>"
                f"<h4>{html.escape(flow['selected'])}</h4>"
                f"<span class=\"turn-badge\">T{html.escape(str(turn))}</span>"
                "</header>"
                "<div class=\"decision-grid\">"
                f"<p><strong>当时看到的问题：</strong><span>{html.escape(flow['observed'])}</span></p>"
                f"<p><strong>候选动作：</strong><span>{html.escape(flow['actions'])}</span></p>"
                f"<p><strong>我选择了：</strong><span>{html.escape(flow['selected'])}</span></p>"
                f"<p><strong>为什么这样选：</strong><span>{html.escape(flow['rationale'])}</span></p>"
                f"<p><strong>为什么没选其他动作：</strong><span>{html.escape(flow['why_not'])}</span></p>"
                f"<p><strong>执行后结果：</strong><span>{html.escape(flow['outcome'])}</span></p>"
                "</div>"
                f"<p class=\"review-note\"><strong>对 review 的意义：</strong>{html.escape(flow['meaning'])}</p>"
                "<p class=\"evidence\">证据线索："
                f"state {code_badges(decision.get('related_state_snapshot_ids'))}"
                f" tool {code_badges(decision.get('related_tool_call_ids'))}"
                f" save {code_badges(decision.get('related_save_ids'))}"
                "</p>"
                "</article>"
            )
        blocks.append(
            "<section class=\"turn-flow\">"
            f"<h3>T{turn} 决策流程</h3>"
            + "".join(rows)
            + "</section>"
        )
    return "\n".join(blocks)


def _episode_rel(recorder: Any, path: Path) -> str:
    try:
        return path.relative_to(recorder.root).as_posix()
    except ValueError:
        return str(path)


def build_evidence_status(
    *,
    tool_complete: bool,
    mcp_complete: bool,
    states_complete: bool,
    decisions_complete: bool,
    save_complete: bool,
    tool_rows: list[dict[str, Any]],
    lua_rows: list[dict[str, Any]],
    state_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    saves: list[dict[str, Any]],
    missing_state_cells: list[tuple[Any, str]],
    missing_decision_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "tool_mcp_raw_records": {
            "status": yes_no(tool_complete and mcp_complete),
            "tool_calls": len(tool_rows),
            "lua_exchanges": len(lua_rows),
            "tool_errors": sum(
                1 for row in tool_rows if row.get("success") is False or "error" in row
            ),
            "lua_errors": sum(
                1 for row in lua_rows if row.get("success") is False or "error" in row
            ),
            "expectation": "Every tool/MCP call keeps timing, params/request, raw result/response, and raw error data.",
        },
        "turn_state_snapshots": {
            "status": yes_no(states_complete),
            "snapshots": len(state_rows),
            "turns": sorted(
                {row.get("turn") for row in state_rows if isinstance(row.get("turn"), int)}
            ),
            "missing_cells": [
                {"snapshot_id": snapshot_id, "field": field}
                for snapshot_id, field in missing_state_cells
            ],
            "expectation": "Every turn start has empire, cities, units, notifications, threats, research/civic, and production coverage or explicit gaps.",
        },
        "decision_records": {
            "status": yes_no(decisions_complete),
            "decision_atoms": len(decisions),
            "missing_fields": missing_decision_fields,
            "expectation": "Each important decision records context, available actions, choice, rationale, rejected alternatives, execution, outcome, and evidence ids.",
        },
        "save_links": {
            "status": yes_no(save_complete),
            "indexed_saves": len(saves),
            "expectation": "Every checkpoint save is linked to episode, turn, decision or event, path, size, and SHA256.",
        },
    }


def build_report_pack(
    recorder: Any,
    *,
    header: dict[str, Any],
    state_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    saves: list[dict[str, Any]],
    tool_rows: list[dict[str, Any]],
    lua_rows: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    actual_turns: int,
    evidence_status: dict[str, Any],
) -> dict[str, Any]:
    first_state = state_rows[0] if state_rows else {}
    final_state = state_rows[-1] if state_rows else {}
    decision_flows = []
    for decision in decisions:
        flow = decision_flow_narrative(decision)
        decision_flows.append(
            {
                "decision_id": decision.get("decision_id"),
                "turn": decision.get("turn"),
                "selected_action": flow["selected"],
                "observed_problem": flow["observed"],
                "candidate_actions": flow["actions"],
                "rationale": flow["rationale"],
                "why_not_alternatives": flow["why_not"],
                "execution_outcome": flow["outcome"],
                "review_meaning": flow["meaning"],
                "evidence": {
                    "state_snapshot_ids": decision.get("related_state_snapshot_ids", []),
                    "tool_call_ids": decision.get("related_tool_call_ids", []),
                    "save_ids": decision.get("related_save_ids", []),
                },
            }
        )

    turn_story = []
    saves_by_turn: dict[int, list[dict[str, Any]]] = {}
    decisions_by_turn: dict[int, list[dict[str, Any]]] = {}
    for save in saves:
        if isinstance(save.get("turn"), int):
            saves_by_turn.setdefault(save["turn"], []).append(save)
    for decision in decisions:
        if isinstance(decision.get("turn"), int):
            decisions_by_turn.setdefault(decision["turn"], []).append(decision)
    for state in state_rows:
        turn = state.get("turn")
        turn_story.append(
            {
                "turn": turn,
                "human_state": [
                    city_sentence(state),
                    production_sentence(state),
                    unit_sentence(state),
                ],
                "decisions": [
                    {
                        "decision_id": decision.get("decision_id"),
                        "selected_action": humanize(decision.get("selected_action")),
                    }
                    for decision in decisions_by_turn.get(turn, [])
                ],
                "saves": [
                    {
                        "save_id": save.get("save_id"),
                        "label": save.get("label"),
                        "decision_id": save.get("decision_id"),
                    }
                    for save in saves_by_turn.get(turn, [])
                ],
            }
        )

    paths = {
        "human_html": _episode_rel(recorder, recorder.report_path),
        "human_draft_html": _episode_rel(recorder, recorder.human_draft_path),
        "agent_handoff": _episode_rel(recorder, recorder.agent_handoff_path),
        "agent_audit_html": _episode_rel(recorder, recorder.agent_report_path),
        "report_pack": _episode_rel(recorder, recorder.report_pack_path),
        "tool_calls": _episode_rel(recorder, recorder.tool_calls_path),
        "mcp_lua": _episode_rel(recorder, recorder.mcp_path),
        "state_snapshots_dir": _episode_rel(recorder, recorder.states_dir),
        "decision_atoms": _episode_rel(recorder, recorder.decision_path),
        "save_index": _episode_rel(recorder, recorder.save_index_path),
    }

    run_mode = observation_mode(actual_turns)
    mode_zh = observation_mode_zh(actual_turns)
    observe_command = (
        "$env:PYTHONIOENCODING='utf-8'; & 'O:\\civ6\\.tools\\uv\\uv.exe' run "
        f"codex-hl-civ6-observe --save-name \"test 1\" --turns {actual_turns}"
    )
    candidate_runtime = header.get("candidate_runtime") or {
        "status": "not_supplied",
        "runtime_effects": [],
    }
    if isinstance(candidate_runtime, dict) and candidate_runtime.get("package_path"):
        observe_command += (
            " --candidate-package "
            + json.dumps(str(candidate_runtime.get("package_path")), ensure_ascii=False)
        )

    return {
        "episode_id": recorder.episode_id,
        "workflow": WORKFLOW_LABEL,
        "generated_at": now_iso(),
        "accepted_reference_episode": ACCEPTED_HUMAN_REPORT_EPISODE,
        "repo": {
            "root": str(ROOT),
            "branch": run_git(["branch", "--show-current"]),
            "commit": run_git(["rev-parse", "HEAD"]),
            "status_short": run_git(["status", "--short"]),
        },
        "run": {
            "save_name": recorder.save_name,
            "start_turn": recorder.start_turn,
            "final_turn": recorder.final_turn,
            "actual_turns": actual_turns,
            "mode": run_mode,
            "mode_zh": mode_zh,
            "route_map": header.get("route_map", WORKFLOW_LABEL),
            "stop_boundary": observation_stop_boundary(actual_turns),
        },
        "candidate_runtime": candidate_runtime,
        "paths": paths,
        "counts": {
            "tool_calls": len(tool_rows),
            "lua_exchanges": len(lua_rows),
            "state_snapshots": len(state_rows),
            "decision_atoms": len(decisions),
            "indexed_saves": len(saves),
        },
        "evidence_status": evidence_status,
        "human_html_contract": load_human_report_contract(),
        "human_report_guidance": {
            "role": "Polished Chinese review HTML for a human. It should be agent-refined prose, not a raw evidence dump.",
            "readability_floor": [
                "top read path for reviewer order",
                "quick nav anchors",
                "metric chips for key numeric changes",
                "card-based turn narrative",
                "structured decision cards with review notes",
                "compact save filenames before full paths",
                "separate quick handoff and full audit tiles",
            ],
            "allowed_to_change": [
                "episode id",
                "counts",
                "paths",
                "observed game-state text",
                "decision prose derived from decision_atoms",
            ],
            "must_preserve": [
                "accepted section order",
                "CSS skeleton and improved card layout",
                "decision-flow labels",
                "links to both agent handoff and audit report",
                "no raw JSON/details/pre blocks",
            ],
        },
        "turn_story": turn_story,
        "decision_flows": decision_flows,
        "gaps": gaps,
        "recovery": {
            "firetuner_reconnect": "Confirm EnableTuner=1, close stale Civ6/civ6-connector processes, rerun the normal short-run, and inspect raw/tool_calls.jsonl for reconnect attempts.",
            "stale_repo_mcp": "Rerun without --keep-existing-mcp-server; default preflight stops repo-local civ6-connector server processes and logs affected pids.",
            "stale_civ6_frontend": "Rerun without --reuse-running-game; default preflight resets Civ6 before loading test 1.",
            "html_contract_failed": "Fix the human renderer or Codex refinement, then rerun --report-only <episode_id>; raw evidence must remain unchanged.",
        },
        "commands": {
            "observe": observe_command,
            "short_run": observe_command,
            "report_only": "$env:PYTHONIOENCODING='utf-8'; & 'O:\\civ6\\.tools\\uv\\uv.exe' run codex-hl-civ6-observe --report-only "
            + str(recorder.episode_id),
        },
    }


def build_agent_handoff(report_pack: dict[str, Any]) -> str:
    evidence = report_pack["evidence_status"]
    paths = report_pack["paths"]
    run = report_pack["run"]
    if run.get("mode") == "t50_observation":
        boundary_line = "- T50 observation complete. Stop before T51+ or Review unless the user explicitly asks to continue."
    elif run.get("mode") == "t20_exploration":
        boundary_line = "- T20 exploration complete. Treat this as local candidate evidence before longer validation."
    else:
        boundary_line = "- Stop before T50 until a human accepts the human HTML."
    status_rows = "\n".join(
        f"- {name}: {data['status']} ({data['expectation']})"
        for name, data in evidence.items()
    )
    gap_rows = "\n".join(
        f"- {gap.get('field')}: {gap.get('reason')} Next: {gap.get('next_step')}"
        for gap in report_pack.get("gaps", [])
    )
    if not gap_rows:
        gap_rows = "- none"
    return f"""# Observation Agent Handoff - {report_pack['episode_id']}

## Read First
- Human review HTML: `{paths['human_html']}`
- Draft human HTML: `{paths['human_draft_html']}`
- Report pack: `{paths['report_pack']}`
- Full audit HTML: `{paths['agent_audit_html']}`

## Boundary
- Workflow: {report_pack.get('workflow', WORKFLOW_LABEL)}
- Mode: {run.get('mode_zh', run.get('mode', 'unknown'))}
- Save: `{run['save_name']}`
- Turns: T{run['start_turn']} -> T{run['final_turn']} ({run['actual_turns']} turns advanced)
{boundary_line}
- Do not do failure attribution, Replay Arena, strategy learning, or promote/reject.

## Evidence Status
{status_rows}

## Human HTML Contract
- Preserve the accepted `observation_test1_short_20260512_130155` structure, sections, and decision-flow labels while keeping the newer scan-friendly layout.
- The final human HTML must be Chinese, readable, decision-focused, and easier to skim than the accepted baseline.
- It must include the read path, quick nav, metric chips, turn cards, structured decision cards, compact save rows, and the quick handoff/full audit tiles.
- Raw JSON, `<details>`, and `<pre>` belong only in the audit HTML, never in the human HTML.
- Human HTML must link both `agent_report.md` and `agent_audit_report.html`.

## Commands
```powershell
{report_pack['commands'].get('observe', report_pack['commands']['short_run'])}
{report_pack['commands']['report_only']}
```

## Recovery
- FireTuner reconnect: {report_pack['recovery']['firetuner_reconnect']}
- Stale repo-local MCP: {report_pack['recovery']['stale_repo_mcp']}
- Stale Civ6/frontend state: {report_pack['recovery']['stale_civ6_frontend']}
- HTML contract failure: {report_pack['recovery']['html_contract_failed']}

## Gaps
{gap_rows}
"""


def build_human_report(
    recorder: Any,
    *,
    header: dict[str, Any],
    state_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    saves: list[dict[str, Any]],
    tool_rows: list[dict[str, Any]],
    lua_rows: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    actual_turns: int,
    tool_complete: bool,
    mcp_complete: bool,
    states_complete: bool,
    decisions_complete: bool,
    save_complete: bool,
    missing_state_cells: list[tuple[Any, str]],
    missing_decision_fields: list[dict[str, Any]],
    agent_handoff_name: str,
    agent_report_name: str,
) -> str:
    first_state = state_rows[0] if state_rows else {}
    final_state = state_rows[-1] if state_rows else {}
    start = first_state.get("overview") or {}
    end = final_state.get("overview") or {}
    start_turn = first_state.get("turn", "?")
    final_turn = final_state.get("turn", "?")

    change_chips = [
        metric_chip("城市数", start.get("num_cities", 0), end.get("num_cities", 0)),
        metric_chip("单位数", start.get("num_units", 0), end.get("num_units", 0)),
        metric_chip("金币", start.get("gold", 0), end.get("gold", 0)),
        metric_chip("每回合金币", start.get("gold_per_turn", 0), end.get("gold_per_turn", 0)),
        metric_chip("科技产出", start.get("science_yield", 0), end.get("science_yield", 0)),
        metric_chip("文化产出", start.get("culture_yield", 0), end.get("culture_yield", 0)),
        metric_chip("分数", start.get("score", 0), end.get("score", 0)),
        metric_chip("已探索陆地", start.get("explored_land", 0), end.get("explored_land", 0)),
    ]

    saves_by_turn: dict[int, list[dict[str, Any]]] = {}
    for save in saves:
        if isinstance(save.get("turn"), int):
            saves_by_turn.setdefault(save["turn"], []).append(save)
    turn_story = []
    for state in state_rows:
        turn = state.get("turn")
        saves_text = "；".join(
            f"{save.get('save_id')} {save.get('label')}"
            for save in saves_by_turn.get(turn, [])
        ) or "无"
        turn_story.append(
            "<article class=\"turn-card\">"
            "<header>"
            f"<strong>T{html.escape(str(turn))}</strong>"
            f"<span>关联存档：{html.escape(saves_text)}</span>"
            "</header>"
            "<ul>"
            f"<li>{html.escape(overview_sentence(state))}</li>"
            f"<li>{html.escape(city_sentence(state))}</li>"
            f"<li>{html.escape(production_sentence(state))}</li>"
            f"<li>{html.escape(unit_sentence(state))}</li>"
            "</ul>"
            "</article>"
        )

    gap_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(g.get('field', '')))}</td>"
        f"<td>{html.escape(str(g.get('reason', '')))}</td>"
        f"<td>{html.escape(str(g.get('next_step', '')))}</td>"
        "</tr>"
        for g in gaps
    )

    save_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(save.get('save_id', '')))}</td>"
        f"<td>T{html.escape(str(save.get('turn', '')))}</td>"
        f"<td>{html.escape(str(save.get('decision_id') or '关键事件'))}</td>"
        f"<td>{html.escape(str(save.get('label', '')))}</td>"
        f"<td>{html.escape(str(save.get('event', '')))}</td>"
        f"<td><strong>{html.escape(basename_text(save.get('episode_path', '')))}</strong><br><code class=\"path-mini\">{html.escape(str(save.get('episode_path', '')))}</code></td>"
        "</tr>"
        for save in saves
    )

    tool_error_count = sum(1 for row in tool_rows if row.get("success") is False or "error" in row)
    lua_error_count = sum(1 for row in lua_rows if row.get("success") is False or "error" in row)
    mode_zh = observation_mode_zh(actual_turns)
    mode = observation_mode(actual_turns)
    is_t50 = mode == "t50_observation"
    is_t20 = mode == "t20_exploration"
    if is_t50:
        summary_text = f"本次 T50 完整观测从 T{html.escape(str(start_turn))} 推进到 T{html.escape(str(final_turn))}，实际推进 {actual_turns} 回合。我的操作只用于解除必要阻塞并完整记录 Observation 证据，已停在 T50，没有继续 T51+、Review、策略学习、失败归因、Replay Arena 或资产 promote/reject。"
        first_read_item = "先看四个 PASS 卡片，确认这次 T50 完整观测有没有达到 Observation 的 50 回合证据门槛。"
        final_read_item = "最后看证据边界、存档关联和缺口清单，决定是否允许进入后续阶段。"
    elif is_t20:
        summary_text = f"本次 T20 策略探索从 T{html.escape(str(start_turn))} 推进到 T{html.escape(str(final_turn))}，实际推进 {actual_turns} 回合。它用于比较局部开局表现和暴露策略候选问题，不是长期战略证明，也不直接触发资产 promote/reject。"
        first_read_item = "先看四个 PASS 卡片，确认这次 T20 探索有没有达到 Observation 的局部证据门槛。"
        final_read_item = "最后看证据边界、存档关联和缺口清单，决定是否进入多局 T20/T50 对比或 Review 标注。"
    else:
        summary_text = f"本次短跑从 T{html.escape(str(start_turn))} 推进到 T{html.escape(str(final_turn))}，实际推进 {actual_turns} 回合。我的操作只用于解除短跑中的必要阻塞并验证记录链路，没有继续 T50，没有做策略学习、失败归因、Replay Arena 或资产 promote/reject。"
        first_read_item = "先看四个 PASS 卡片，确认这次短跑有没有达到 Observation 的最低证据门槛。"
        final_read_item = "最后看证据边界、存档关联和缺口清单，决定是否允许同一套机制继续 T50。"
    evidence_boundary_rows = [
        (
            "这次 T50 完整观测证明记录链路能覆盖 50 回合，但仍不宣称这些开局选择是最优策略。"
            if is_t50
            else "这次 T20 探索提供了局部策略比较材料，但不能单独证明策略变强。"
            if is_t20
            else "这次短跑证明记录链路可用，但并不证明这些开局选择是最优策略。"
        ),
        "每回合开始都有状态快照；非 end-turn 决策后主要依赖 tool 返回、decision outcome 和后续回合快照来确认结果。",
        (
            "T50 已停止在完整观测边界；任何 T51+、Review、失败归因或策略改进都需要用户另行明确要求。"
            if is_t50
            else "勇士在短跑中选择驻守，是为了避免把探索策略改进混入 Observation。若你希望 T50 覆盖探索决策，需要给出探索原则或允许 runner 在观测阶段做最小探索。"
        ),
        f"工具错误和 Lua 错误没有隐藏：tool error={tool_error_count}，lua error={lua_error_count}。详见 Agent 审计报告。",
    ]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Codex HL Observation 人类验收报告 - {html.escape(recorder.episode_id)}</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; color: #1f2937; margin: 0; line-height: 1.68; background: #f8fafc; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 34px 28px 52px; background: #ffffff; }}
    h1, h2, h3, h4 {{ color: #111827; line-height: 1.25; }}
    h1 {{ margin: 0 0 6px; font-size: 30px; }}
    h2 {{ border-top: 2px solid #e5e7eb; padding-top: 24px; margin-top: 34px; }}
    h3 {{ margin-bottom: 10px; }}
    .subtitle, .muted {{ color: #64748b; }}
    .summary {{ background: #f8fafc; border: 1px solid #cbd5e1; border-left: 5px solid #2563eb; border-radius: 6px; padding: 16px 18px; margin-top: 18px; }}
    .summary h2 {{ border: 0; margin-top: 0; padding-top: 0; }}
    .read-path {{ margin: 12px 0 0; padding-left: 24px; }}
    .report-nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }}
    .report-nav a {{ color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 999px; padding: 5px 10px; text-decoration: none; }}
    .verdict {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }}
    .tile {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 12px; background: #fff; }}
    .pass {{ color: #047857; font-weight: 700; }}
    .fail {{ color: #b91c1c; font-weight: 700; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 14px 0 4px; }}
    .metric-chip {{ border: 1px solid #dbe3ef; border-radius: 6px; padding: 10px 12px; background: #ffffff; }}
    .metric-chip span {{ display: block; color: #64748b; font-size: 13px; }}
    .metric-chip strong {{ display: block; margin-top: 3px; font-size: 16px; }}
    .metric-chip em {{ font-style: normal; font-weight: 700; }}
    .metric-chip em.positive {{ color: #047857; }}
    .metric-chip em.negative {{ color: #b45309; }}
    .metric-chip em.neutral {{ color: #64748b; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 22px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 9px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    code {{ background: #eef2ff; padding: 1px 4px; border-radius: 4px; word-break: break-word; }}
    .path-mini {{ color: #64748b; font-size: 12px; }}
    .turn-timeline {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .turn-card {{ border: 1px solid #d1d5db; border-left: 4px solid #64748b; border-radius: 6px; background: #ffffff; padding: 12px; }}
    .turn-card header {{ display: flex; justify-content: space-between; gap: 12px; color: #475569; }}
    .turn-card ul {{ margin: 8px 0 0; padding-left: 18px; }}
    .turn-flow {{ margin: 20px 0 30px; }}
    .decision-card {{ border: 1px solid #bfdbfe; border-left: 4px solid #2563eb; background: #f8fbff; border-radius: 6px; padding: 14px; margin: 12px 0; }}
    .decision-header {{ display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; margin-bottom: 10px; }}
    .decision-header h4 {{ margin: 0; }}
    .decision-id, .turn-badge {{ color: #1d4ed8; background: #dbeafe; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; }}
    .decision-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .decision-grid p {{ background: #ffffff; border: 1px solid #dbe3ef; border-radius: 6px; padding: 10px; margin: 0; }}
    .decision-grid strong {{ display: block; margin-bottom: 4px; color: #334155; }}
    .review-note {{ background: #ecfdf5; border: 1px solid #bbf7d0; border-radius: 6px; padding: 10px; margin: 10px 0 8px; }}
    .evidence {{ color: #475569; font-size: 13px; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .agent-links {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .agent-links a {{ color: #1d4ed8; font-weight: 700; }}
    ul {{ padding-left: 22px; }}
    @media (max-width: 860px) {{ .verdict, .metric-grid, .two-col, .turn-timeline, .decision-grid, .agent-links {{ grid-template-columns: 1fr; }} main {{ padding: 24px 16px; }} }}
  </style>
</head>
<body>
<main>
  <h1>Codex HL Observation 人类验收报告</h1>
  <p class="subtitle">episode: <code>{html.escape(recorder.episode_id)}</code>；存档：<code>{html.escape(str(recorder.save_name))}</code>；路线：{html.escape(str(header.get('route_map', WORKFLOW_LABEL)))}。</p>

  <section class="summary">
    <h2 id="verdict">验收结论</h2>
    <p>{summary_text}</p>
    <p>人类版重点解释“为什么这样决策”。给下一轮 agent 快速接手的摘要在 <a href="{html.escape(agent_handoff_name)}">Agent handoff</a>；完整机器证据另存为 <a href="{html.escape(agent_report_name)}">Agent 审计报告</a>，原始 JSONL 和存档仍保留在 episode 目录下。</p>
    <h3>先读这份报告的顺序</h3>
    <ol class="read-path">
      <li>{html.escape(first_read_item)}</li>
      <li>再看局面变化和回合叙事，建立 T1 到 T{html.escape(str(final_turn))} 的整体画面。</li>
      <li>重点 review 决策流程，判断我看到的信息、候选项、选择理由和未选理由是否足够清楚。</li>
      <li>{html.escape(final_read_item)}</li>
    </ol>
  </section>

  <nav class="report-nav" aria-label="快速定位">
    <a href="#changes">局面变化</a>
    <a href="#turn-story">回合叙事</a>
    <a href="#decision-flow">决策流程</a>
    <a href="#evidence-boundary">证据边界</a>
    <a href="#saves">存档关联</a>
    <a href="#agent-reports">Agent 报告</a>
  </nav>

  <div class="verdict">
    <div class="tile"><strong>工具/MCP 原始记录</strong><br><span class="{ 'pass' if tool_complete and mcp_complete else 'fail' }">{yes_no(tool_complete and mcp_complete)}</span><br>{len(tool_rows)} tool calls，{len(lua_rows)} Lua/MCP exchanges</div>
    <div class="tile"><strong>每回合状态快照</strong><br><span class="{ 'pass' if states_complete else 'fail' }">{yes_no(states_complete)}</span><br>{len(state_rows)} 份快照，缺失单元 {len(missing_state_cells)}</div>
    <div class="tile"><strong>关键决策记录</strong><br><span class="{ 'pass' if decisions_complete else 'fail' }">{yes_no(decisions_complete)}</span><br>{len(decisions)} 条决策，缺失字段 {len(missing_decision_fields)}</div>
    <div class="tile"><strong>存档关联</strong><br><span class="{ 'pass' if save_complete else 'fail' }">{yes_no(save_complete)}</span><br>{len(saves)} 个索引存档</div>
  </div>

  <h2 id="changes">我实际观测到的局面变化</h2>
  <div class="two-col">
    <div class="tile">
      <h3>起点 T{html.escape(str(start_turn))}</h3>
      <p>{html.escape(overview_sentence(first_state))}</p>
      <p>{html.escape(unit_sentence(first_state))}</p>
    </div>
    <div class="tile">
      <h3>终点 T{html.escape(str(final_turn))}</h3>
      <p>{html.escape(overview_sentence(final_state))}</p>
      <p>{html.escape(city_sentence(final_state))}</p>
      <p>{html.escape(production_sentence(final_state))}</p>
    </div>
  </div>
  <h3>关键数字变化</h3>
  <div class="metric-grid">
    {''.join(change_chips)}
  </div>

  <h2 id="turn-story">回合叙事</h2>
  <div class="turn-timeline">
    {''.join(turn_story)}
  </div>

  <h2 id="decision-flow">重点：决策流程</h2>
  <p>下面是我对每条关键决策的人工化复述。每条都按“看到什么 -> 候选动作 -> 选择 -> 为什么没选其他 -> 执行结果 -> review 意义”展开，避免把 JSON 直接丢给人看。</p>
  {build_human_decision_flow(decisions)}

  <h2 id="evidence-boundary">证据边界和你需要判断的点</h2>
  <ul>
    {''.join(f'<li>{html.escape(row)}</li>' for row in evidence_boundary_rows)}
  </ul>

  <h2 id="saves">存档和决策关联</h2>
  <table>
    <tr><th>存档</th><th>回合</th><th>关联决策/事件</th><th>label</th><th>event</th><th>路径</th></tr>
    {save_rows}
  </table>

  <h2 id="gaps">缺口清单</h2>
  <table>
    <tr><th>字段</th><th>为什么拿不到/缺失</th><th>下一步建议</th></tr>
    {gap_rows}
  </table>

  <h2 id="agent-reports">面向 Agent 的报告</h2>
  <div class="agent-links">
    <div class="tile">
      <h3>快速接手</h3>
      <p>下一轮 agent 先读这份 handoff，避免从大体积审计 HTML 里重新摸索流程。</p>
      <p><a href="{html.escape(agent_handoff_name)}">{html.escape(agent_handoff_name)}</a></p>
    </div>
    <div class="tile">
      <h3>完整审计</h3>
      <p>机器可审计版保留完整 tool/MCP/state/decision/save 表格和可展开 JSON。</p>
      <p><a href="{html.escape(agent_report_name)}">{html.escape(agent_report_name)}</a></p>
    </div>
  </div>
</main>
</body>
</html>
"""


def load_human_report_contract() -> dict[str, Any]:
    if HUMAN_REPORT_CONTRACT_PATH.exists():
        return json.loads(HUMAN_REPORT_CONTRACT_PATH.read_text(encoding="utf-8"))
    return DEFAULT_HUMAN_REPORT_CONTRACT


def validate_human_report_text(text: str, *, path_hint: str = "<memory>") -> None:
    """Keep the human-facing report compatible with the accepted Observation review HTML."""
    contract = load_human_report_contract()
    lower_text = text.lower()
    required_fragments = contract.get("required_fragments", [])
    required_css = contract.get("required_css_fragments", [])
    forbidden_fragments = contract.get("forbidden_fragments", [])
    missing = [
        str(fragment)
        for fragment in [*required_fragments, *required_css]
        if str(fragment) not in text
    ]
    forbidden = [
        str(fragment)
        for fragment in forbidden_fragments
        if str(fragment).lower() in lower_text
    ]
    problems = []
    if missing:
        problems.append("missing required human-report fragments: " + ", ".join(missing))
    if forbidden:
        problems.append("human report contains raw-audit fragments: " + ", ".join(forbidden))
    if problems:
        raise RuntimeError(
            f"Human report contract failed for {path_hint}: " + "; ".join(problems)
        )


def validate_human_report_contract(path: Path) -> None:
    validate_human_report_text(path.read_text(encoding="utf-8"), path_hint=str(path))


def generate_report(recorder: Any) -> None:
    tool_rows = load_jsonl(recorder.tool_calls_path)
    lua_rows = load_jsonl(recorder.mcp_path)
    decisions = load_jsonl(recorder.decision_path)
    saves = load_jsonl(recorder.save_index_path)
    state_rows = load_state_rows_for_recorder(recorder)
    state_turns = [row.get("turn") for row in state_rows]

    required_decision_fields = [
        "decision_id",
        "episode_id",
        "turn",
        "trigger",
        "importance",
        "background",
        "current_goal",
        "available_actions",
        "selected_action",
        "rationale",
        "why_not_alternatives",
        "execution",
        "outcome",
        "related_tool_call_ids",
        "related_state_snapshot_ids",
        "related_save_ids",
    ]
    missing_decision_fields = []
    for decision in decisions:
        for key in required_decision_fields:
            reason = decision_field_missing_reason(decision, key)
            if reason:
                missing_decision_fields.append(
                    {
                        "decision_id": decision.get("decision_id", "?"),
                        "field": key,
                        "reason": reason,
                    }
                )

    actual_turns = 0
    if recorder.start_turn is not None and recorder.final_turn is not None:
        actual_turns = max(0, recorder.final_turn - recorder.start_turn)

    gaps = recorder.missing_fields + [
        {
            "field": f"decision.{m['decision_id']}.{m['field']}",
            "reason": m["reason"],
            "next_step": "T50 前补齐该字段。",
        }
        for m in missing_decision_fields
    ]
    if not gaps:
        mode_zh = observation_mode_zh(actual_turns)
        mode = observation_mode(actual_turns)
        if mode == "t50_observation":
            next_step = "停在 T50，等待用户决定是否进入后续阶段。"
        elif mode == "t20_exploration":
            next_step = "进入 Review 候选标注或继续多局 T20/T50 对比。"
        else:
            next_step = "人工验收后再继续 T50。"
        gaps = [
            {
                "field": "none",
                "reason": f"本次{mode_zh}生成产物没有缺失必填字段。",
                "next_step": next_step,
            }
        ]

    required_state_fields = ["empire", "cities", "units", "notifications", "threats", "research_civic", "production"]
    missing_state_cells = [
        (state.get("snapshot_id"), key)
        for state in state_rows
        for key in required_state_fields
        if key not in state or state.get(key) is None
    ]

    tool_complete = bool(tool_rows) and all("result_raw" in r or "error" in r for r in tool_rows)
    mcp_complete = bool(lua_rows) and all("request" in r and ("response" in r or "error" in r) for r in lua_rows)
    states_complete = (
        bool(state_rows)
        and not missing_state_cells
        and len(state_rows) >= max(1, actual_turns)
    )
    decisions_complete = bool(decisions) and not missing_decision_fields
    save_complete = len(saves) >= 2 and all(
        save.get("episode_id")
        and save.get("turn") is not None
        and (save.get("decision_id") or save.get("event") or save.get("label"))
        and save.get("episode_path")
        and save.get("sha256")
        for save in saves
    )

    tool_error_count = sum(1 for row in tool_rows if row.get("success") is False or "error" in row)
    lua_error_count = sum(1 for row in lua_rows if row.get("success") is False or "error" in row)

    turn_blocks = []
    decisions_by_turn: dict[int, list[dict[str, Any]]] = {}
    saves_by_turn: dict[int, list[dict[str, Any]]] = {}
    for decision in decisions:
        if isinstance(decision.get("turn"), int):
            decisions_by_turn.setdefault(decision["turn"], []).append(decision)
    for save in saves:
        if isinstance(save.get("turn"), int):
            saves_by_turn.setdefault(save["turn"], []).append(save)
    for state in state_rows:
        turn = state.get("turn")
        d_list = decisions_by_turn.get(turn, [])
        s_list = saves_by_turn.get(turn, [])
        turn_blocks.append(
            "<section class=\"record-card\">"
            f"<h3>T{html.escape(str(turn))}</h3>"
            f"<p>{html.escape(state_metric_summary(state))}</p>"
            f"<p><strong>决策：</strong>{html.escape('; '.join(str(d.get('selected_action')) for d in d_list) or '无')}</p>"
            f"<p><strong>存档：</strong>{html.escape('; '.join(str(s.get('save_id')) + ' ' + str(s.get('label')) for s in s_list) or '无')}</p>"
            "</section>"
        )

    gap_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(g.get('field', '')))}</td>"
        f"<td>{html.escape(str(g.get('reason', '')))}</td>"
        f"<td>{html.escape(str(g.get('next_step', '')))}</td>"
        "</tr>"
        for g in gaps
    )

    codex_output_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('ts', '')))}</td>"
        f"<td>{html.escape(str(row.get('turn', '')))}</td>"
        f"<td>{html.escape(str(row.get('kind', '')))}</td>"
        f"<td>{html.escape(text_preview(row.get('content') or row.get('payload'), 260))}</td>"
        f"<td>{details_block('展开 Codex 输出原始记录', row)}</td>"
        "</tr>"
        for row in load_jsonl(recorder.codex_outputs_path)
    )

    header = getattr(recorder, "header", None)
    if header is None and getattr(recorder, "header_path", None) and recorder.header_path.exists():
        header = load_json_artifact(recorder.header_path)
    header = header or {}
    mode_zh = observation_mode_zh(actual_turns)
    workflow_boundary_text = (
        "本次是 T50 完整观测；到 T50 后停止，不继续 T51+ 或 Review。"
        if observation_mode(actual_turns) == "t50_observation"
        else "本次只做 3-10 回合短跑验收；人工确认前不继续 T50。"
    )
    review_html = render_codex_review_layer(
        actual_turns=actual_turns,
        state_rows=state_rows,
        decisions=decisions,
        saves=saves,
        tool_rows=tool_rows,
        lua_rows=lua_rows,
        gaps=gaps,
        missing_state_cells=missing_state_cells,
        missing_decision_fields=missing_decision_fields,
    )

    report = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Codex HL Observation {html.escape(mode_zh)}报告 - {html.escape(recorder.episode_id)}</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; margin: 28px; color: #1f2937; line-height: 1.5; }}
    h1, h2, h3 {{ color: #111827; }}
    h1 {{ margin-bottom: 4px; }}
    .muted {{ color: #6b7280; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; max-width: 1280px; }}
    .box, .record-card {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 12px; background: #f9fafb; margin: 12px 0; }}
    .record-card {{ background: #ffffff; }}
    .review-panel {{ border: 1px solid #93c5fd; border-left: 4px solid #2563eb; border-radius: 6px; padding: 14px; background: #eff6ff; margin: 14px 0; }}
    .review-panel table th {{ background: #dbeafe; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0 24px; font-size: 13px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 7px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    code {{ background: #eef2ff; padding: 1px 4px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #111827; color: #f9fafb; padding: 10px; border-radius: 6px; max-height: 520px; overflow: auto; }}
    details {{ margin: 4px 0; }}
    summary {{ cursor: pointer; color: #1d4ed8; }}
    .pass {{ color: #047857; font-weight: 700; }}
    .fail {{ color: #b91c1c; font-weight: 700; }}
    .toc a {{ margin-right: 14px; }}
  </style>
</head>
<body>
  <h1>Codex HL Observation {html.escape(mode_zh)}报告</h1>
  <p class="muted">本报告是中文审计入口。页面内直接列出工具调用、MCP/Lua 原始交互、每回合状态、关键决策、存档索引；原始 JSON 仍以 <code>details</code> 折叠块完整保留。</p>
  <p><strong>Workflow:</strong> {html.escape(WORKFLOW_LABEL)}。{html.escape(workflow_boundary_text)}</p>

  <nav class="toc">
    <a href="#review">Codex review 导读</a>
    <a href="#basic">基本信息</a>
    <a href="#acceptance">四类验收</a>
    <a href="#turns">每回合发生了什么</a>
    <a href="#tools">全部工具调用和返回结果</a>
    <a href="#states">每回合状态快照</a>
    <a href="#decisions">关键决策记录</a>
    <a href="#saves">存档关联</a>
    <a href="#gaps">缺失字段清单</a>
  </nav>

  {review_html}

  <h2 id="basic">Episode 基本信息</h2>
  <div class="grid">
    <div class="box"><strong>episode_id</strong><br><code>{html.escape(recorder.episode_id)}</code></div>
    <div class="box"><strong>存档</strong><br>{html.escape(str(recorder.save_name))}</div>
    <div class="box"><strong>起始回合</strong><br>{html.escape(str(recorder.start_turn))}</div>
    <div class="box"><strong>最终快照回合</strong><br>{html.escape(str(recorder.final_turn))}</div>
    <div class="box"><strong>实际推进回合数</strong><br>{actual_turns}</div>
    <div class="box"><strong>仓库</strong><br>{html.escape(str(ROOT))}</div>
    <div class="box"><strong>仓库提交</strong><br><code>{html.escape(str(header.get('civ6_mcp_repo_commit', '')))}</code></div>
    <div class="box"><strong>路线标记</strong><br>{html.escape(str(header.get('route_map', WORKFLOW_LABEL)))}</div>
  </div>

  <h2 id="acceptance">四类记录验收</h2>
  <table>
    <tr><th>类别</th><th>状态</th><th>页面内证据</th></tr>
    <tr><td>1. 全部工具调用和返回结果</td><td class="{ 'pass' if tool_complete and mcp_complete else 'fail' }">{yes_no(tool_complete and mcp_complete)}</td><td><a href="#tool-calls">高层 tool 调用 {len(tool_rows)} 条</a>；<a href="#lua-calls">MCP/Lua 交互 {len(lua_rows)} 条</a>；错误记录 tool={tool_error_count}, lua={lua_error_count}，错误原文也保留。</td></tr>
    <tr><td>2. 每回合状态快照</td><td class="{ 'pass' if states_complete else 'fail' }">{yes_no(states_complete)}</td><td><a href="#states">状态快照 {len(state_rows)} 份</a>；覆盖回合 {html.escape(str(sorted(set(state_turns))))}；必查字段缺失单元 {len(missing_state_cells)} 个。</td></tr>
    <tr><td>3. 关键决策前后记录</td><td class="{ 'pass' if decisions_complete else 'fail' }">{yes_no(decisions_complete)}</td><td><a href="#decisions">decision_atoms {len(decisions)} 条</a>；每条展示背景、目标、候选动作、选择理由、未选理由、执行和结果；必填字段缺失 {len(missing_decision_fields)} 个。</td></tr>
    <tr><td>4. 存档文件与回合/决策关联</td><td class="{ 'pass' if save_complete else 'fail' }">{yes_no(save_complete)}</td><td><a href="#saves">索引存档 {len(saves)} 个</a>；表内展示 episode、turn、decision_id、event、路径和 sha256。</td></tr>
  </table>

  <h2 id="turns">每回合发生了什么</h2>
  {''.join(turn_blocks) if turn_blocks else '<p>没有记录到回合摘要。</p>'}

  <h2 id="tools">1. 全部工具调用和返回结果</h2>
  <p>本节直接列出每一次高层工具调用和每一次底层 MCP/Lua 交互。参数、返回值、错误信息都在每行的“完整原始记录”里，不只保留摘要。</p>

  <h3 id="tool-calls">1.1 高层 tool 调用：<code>raw/tool_calls.jsonl</code></h3>
  <table>
    <tr><th>call_id</th><th>turn</th><th>tool</th><th>开始时间</th><th>耗时 ms</th><th>状态</th><th>参数摘要</th><th>返回/错误摘要</th><th>完整原始记录</th></tr>
    {render_tool_rows(tool_rows)}
  </table>

  <h3 id="lua-calls">1.2 MCP/Lua 原始交互：<code>raw/mcp.jsonl</code></h3>
  <table>
    <tr><th>lua_id</th><th>context</th><th>开始时间</th><th>耗时 ms</th><th>状态</th><th>Lua 请求摘要</th><th>返回/错误摘要</th><th>完整原始记录</th></tr>
    {render_lua_rows(lua_rows)}
  </table>

  <h3>1.3 Codex 输出记录：<code>raw/codex_outputs.jsonl</code></h3>
  <table>
    <tr><th>时间</th><th>turn</th><th>kind</th><th>摘要</th><th>完整原始记录</th></tr>
    {codex_output_rows}
  </table>

  <h2 id="states">2. 每回合状态快照</h2>
  <p>每个回合开始至少记录一次状态。下方逐回合展示 empire、cities、units、notifications、threats、research/civic、production 的覆盖情况；空列表/空对象表示该回合工具返回为空或实体不存在，不等同于未记录。</p>
  {render_state_sections(state_rows)}

  <h2 id="decisions">3. 关键决策前后的决策记录</h2>
  <p>每条决策都展示 <code>available_actions</code>，用于区分“没有想到该选项”和“想到了但判断错了”。本次{html.escape(mode_zh)}只做观测和必要 blocker 处理，不把这些决策 promoted 成策略改进。</p>
  {render_decision_sections(decisions)}

  <h2 id="saves">4. 存档文件和回合/决策的关联</h2>
  <table>
    <tr><th>save_id</th><th>episode_id</th><th>turn</th><th>decision_id</th><th>label</th><th>关键事件</th><th>episode 内路径</th><th>sha256</th><th>完整原始记录</th></tr>
    {render_save_rows(saves)}
  </table>

  <h2 id="gaps">缺失字段清单</h2>
  <p>这里列出“拿不到什么、为什么拿不到、下一步怎么补”。如果是版本/运行时来源信息不可得，会和状态字段缺口分开列出。</p>
  <table>
    <tr><th>字段</th><th>原因</th><th>下一步</th></tr>
    {gap_rows}
  </table>

  <h2>原始证据文件入口</h2>
  <ul>
    <li><code>header.json</code></li>
    <li><code>raw/mcp.jsonl</code></li>
    <li><code>raw/tool_calls.jsonl</code></li>
    <li><code>raw/codex_outputs.jsonl</code></li>
    <li><code>raw/civ6_states/*.json</code></li>
    <li><code>raw/saves/save_index.jsonl</code> 和 <code>raw/saves/*.Civ6Save</code></li>
    <li><code>derived/decision_atoms.jsonl</code></li>
    <li><code>derived/timeline.md</code></li>
    <li><code>assets_snapshot/manifest.json</code></li>
  </ul>
</body>
</html>
"""
    recorder.report_path.write_text(report, encoding="utf-8")
    store_report_artifact(recorder, recorder.report_path, report, kind="html_report")


def generate_reports(recorder: Any) -> None:
    """Write both reports: a detailed agent audit and a polished human review."""
    generate_report(recorder)

    agent_report_path = getattr(
        recorder,
        "agent_report_path",
        recorder.outcome / "agent_audit_report.html",
    )
    if recorder.report_path != agent_report_path:
        shutil.copy2(recorder.report_path, agent_report_path)
        store_report_artifact(
            recorder,
            agent_report_path,
            agent_report_path.read_text(encoding="utf-8"),
            kind="agent_audit_report",
        )

    tool_rows = load_jsonl(recorder.tool_calls_path)
    lua_rows = load_jsonl(recorder.mcp_path)
    decisions = load_jsonl(recorder.decision_path)
    saves = load_jsonl(recorder.save_index_path)
    state_rows = load_state_rows_for_recorder(recorder)
    state_turns = [state.get("turn") for state in state_rows]

    required_decision_fields = [
        "decision_id",
        "episode_id",
        "turn",
        "trigger",
        "importance",
        "background",
        "current_goal",
        "available_actions",
        "selected_action",
        "rationale",
        "why_not_alternatives",
        "execution",
        "outcome",
        "related_tool_call_ids",
        "related_state_snapshot_ids",
        "related_save_ids",
    ]
    missing_decision_fields = []
    for decision in decisions:
        for key in required_decision_fields:
            reason = decision_field_missing_reason(decision, key)
            if reason:
                missing_decision_fields.append(
                    {
                        "decision_id": decision.get("decision_id", "?"),
                        "field": key,
                        "reason": reason,
                    }
                )

    actual_turns = 0
    if recorder.start_turn is not None and recorder.final_turn is not None:
        actual_turns = max(0, recorder.final_turn - recorder.start_turn)

    gaps = list(getattr(recorder, "missing_fields", [])) + [
        {
            "field": f"decision.{m['decision_id']}.{m['field']}",
            "reason": m["reason"],
            "next_step": "T50 前补齐该字段。",
        }
        for m in missing_decision_fields
    ]
    if not gaps:
        mode_zh = observation_mode_zh(actual_turns)
        mode = observation_mode(actual_turns)
        if mode == "t50_observation":
            next_step = "停在 T50，等待用户决定是否进入后续阶段。"
        elif mode == "t20_exploration":
            next_step = "进入 Review 候选标注或继续多局 T20/T50 对比。"
        else:
            next_step = "人工验收后再继续 T50。"
        gaps = [
            {
                "field": "none",
                "reason": f"本次{mode_zh}生成产物没有缺失必填字段。",
                "next_step": next_step,
            }
        ]

    required_state_fields = [
        "empire",
        "cities",
        "units",
        "notifications",
        "threats",
        "research_civic",
        "production",
    ]
    missing_state_cells = [
        (state.get("snapshot_id"), key)
        for state in state_rows
        for key in required_state_fields
        if key not in state or state.get(key) is None
    ]

    tool_complete = bool(tool_rows) and all(
        "result_raw" in row or "error" in row for row in tool_rows
    )
    mcp_complete = bool(lua_rows) and all(
        "request" in row and ("response" in row or "error" in row) for row in lua_rows
    )
    states_complete = (
        bool(state_rows)
        and not missing_state_cells
        and len(state_rows) >= max(1, actual_turns)
    )
    decisions_complete = bool(decisions) and not missing_decision_fields
    save_complete = len(saves) >= 2 and all(
        save.get("episode_id")
        and save.get("turn") is not None
        and (save.get("decision_id") or save.get("event") or save.get("label"))
        and save.get("episode_path")
        and save.get("sha256")
        for save in saves
    )

    header = getattr(recorder, "header", None)
    if header is None and getattr(recorder, "header_path", None) and recorder.header_path.exists():
        header = json.loads(recorder.header_path.read_text(encoding="utf-8"))
    header = header or {}
    agent_handoff_path = getattr(
        recorder,
        "agent_handoff_path",
        recorder.outcome / "agent_report.md",
    )
    human_draft_path = getattr(
        recorder,
        "human_draft_path",
        recorder.outcome / "observation_report.draft.html",
    )
    report_pack_path = getattr(
        recorder,
        "report_pack_path",
        recorder.derived / "report_pack.json",
    )

    evidence_status = build_evidence_status(
        tool_complete=tool_complete,
        mcp_complete=mcp_complete,
        states_complete=states_complete,
        decisions_complete=decisions_complete,
        save_complete=save_complete,
        tool_rows=tool_rows,
        lua_rows=lua_rows,
        state_rows=state_rows,
        decisions=decisions,
        saves=saves,
        missing_state_cells=missing_state_cells,
        missing_decision_fields=missing_decision_fields,
    )
    report_pack = build_report_pack(
        recorder,
        header=header,
        state_rows=state_rows,
        decisions=decisions,
        saves=saves,
        tool_rows=tool_rows,
        lua_rows=lua_rows,
        gaps=gaps,
        actual_turns=actual_turns,
        evidence_status=evidence_status,
    )
    report_pack_path.write_text(
        json.dumps(to_jsonable(report_pack), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store_json_report_artifact(recorder, report_pack_path, report_pack, kind="report_pack")
    agent_handoff = build_agent_handoff(report_pack)
    agent_handoff_path.write_text(agent_handoff, encoding="utf-8")
    store_report_artifact(recorder, agent_handoff_path, agent_handoff, kind="agent_handoff")

    human_report = build_human_report(
        recorder,
        header=header,
        state_rows=state_rows,
        decisions=decisions,
        saves=saves,
        tool_rows=tool_rows,
        lua_rows=lua_rows,
        gaps=gaps,
        actual_turns=actual_turns,
        tool_complete=tool_complete,
        mcp_complete=mcp_complete,
        states_complete=states_complete,
        decisions_complete=decisions_complete,
        save_complete=save_complete,
        missing_state_cells=missing_state_cells,
        missing_decision_fields=missing_decision_fields,
        agent_handoff_name=agent_handoff_path.name,
        agent_report_name=agent_report_path.name,
    )
    human_draft_path.write_text(human_report, encoding="utf-8")
    store_report_artifact(recorder, human_draft_path, human_report, kind="human_draft_report")
    recorder.report_path.write_text(human_report, encoding="utf-8")
    store_report_artifact(recorder, recorder.report_path, human_report, kind="human_report")
    validate_human_report_contract(recorder.report_path)


async def run_short(args: argparse.Namespace) -> int:
    save_name = args.save_name
    save_path = SAVE_DIR / f"{save_name}.Civ6Save"
    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_path}")

    mode = observation_mode(args.turns)
    mode_zh = observation_mode_zh(args.turns)
    episode_id = args.episode_id or f"{observation_episode_prefix(args.turns)}_{now_stamp()}"
    recorder = EpisodeRecorder(episode_id, save_name)
    recorder.requested_turns = args.turns
    recorder.observation_mode = mode
    recorder.strategy_profile = args.strategy_profile
    recorder.candidate_runtime = load_candidate_runtime(args.candidate_package)
    hostname = os.environ.get("COMPUTERNAME")
    if not hostname and hasattr(os, "uname"):
        hostname = os.uname().nodename

    header = {
        "episode_id": episode_id,
        "start_time": recorder.start_time,
        "machine": {
            "platform": sys.platform,
            "hostname": hostname,
            "cwd": str(ROOT),
            "python": sys.version,
        },
        "environment": {
            "os": os.name,
            "timezone": datetime.now().astimezone().tzname(),
            "save_dir": str(SAVE_DIR),
        },
        "codex_hl_civ6_workspace_commit": run_git(["rev-parse", "HEAD"]),
        "codex_hl_civ6_workspace_branch": run_git(["branch", "--show-current"]),
        "codex_hl_civ6_workspace_status": run_git(["status", "--short"]),
        "civ6_version_info": {
            "value": None,
            "gap": "No stable Civ6 version query is exposed by current civ6_connector tools.",
            "next_step": "Add a minimal Lua/version or executable metadata query before long-run provenance depends on exact build number.",
        },
        "codex_model_info": {
            "value": os.environ.get("CODEX_HL_CIV6_AGENT_MODEL") or None,
            "gap": "Codex runtime model is not exposed to this external runner unless CODEX_HL_CIV6_AGENT_MODEL is set.",
        },
        "save_name": save_name,
        "save_path": str(save_path),
        "save_sha256": sha256_file(save_path),
        "requested_turns": args.turns,
        "observation_mode": mode,
        "observation_mode_zh": mode_zh,
        "strategy_profile": args.strategy_profile,
        "candidate_runtime": recorder.candidate_runtime,
        "route_map": f"{WORKFLOW_LABEL} - {mode_zh}",
        "workflow_rules": [
            (
                "short run only before human acceptance"
                if mode == "short_validation"
                else "T20 local strategy exploration by explicit user request"
                if mode == "t20_exploration"
                else "T50 observation only after human short-run acceptance"
            ),
            "no failure attribution",
            "no Replay Arena",
            "no candidate strategy improvement",
            "no learning loop",
            "no asset promote/reject",
            "candidate package is read-only runtime input when supplied; it does not mutate strategy assets",
            "single-player test 1 save only",
            observation_stop_boundary(args.turns),
        ],
    }
    recorder.write_header(header)
    recorder.add_gap(
        "header.civ6_version_info",
        header["civ6_version_info"]["gap"],
        header["civ6_version_info"]["next_step"],
    )
    if not header["codex_model_info"]["value"]:
        recorder.add_gap(
            "header.codex_model_info",
            header["codex_model_info"]["gap"],
            "Set CODEX_HL_CIV6_AGENT_MODEL or add a Codex runtime metadata bridge if this must be exact.",
        )

    conn = RecordingConnection(recorder)
    gs = GameState(conn)
    try:
        if not args.keep_existing_mcp_server:
            await recorder.tool_call(
                "stop_repo_mcp_servers",
                {
                    "reason": "Observation runner talks directly to FireTuner and needs exclusive game lifecycle control.",
                    "scope": str(ROOT),
                },
                lambda: asyncio.to_thread(stop_repo_mcp_servers),
            )
        if not args.reuse_running_game:
            await recorder.tool_call(
                "reset_game_before_front_end_load",
                {
                    "reason": "Fresh Observation observation runs must not depend on whatever screen a previous session left open.",
                    "expected_next_step": "launch Civ6 to the front end, then load test 1 through FrontEnd/LoadGameMenu Lua state",
                },
                lambda: game_launcher.kill_game(),
            )
        overview = await ensure_game_loaded(recorder, gs, save_name, save_path)
        recorder.timeline(f"- Loaded `{save_name}` and verified {summarize_overview(overview)}.")

        for i in range(args.turns):
            turn, state_id, snapshot = await capture_state(recorder, gs, f"turn_start_{i + 1}")
            recorder.codex_output(
                "turn_start",
                turn,
                {
                    "state_snapshot_id": state_id,
                    "summary": background_from_snapshot(snapshot),
                },
            )
            await maybe_choose_research(recorder, gs, turn, state_id, snapshot)
            await maybe_choose_civic(recorder, gs, turn, state_id, snapshot)
            await maybe_choose_pantheon(recorder, gs, turn, state_id, snapshot)
            await maybe_set_city_production(recorder, gs, turn, state_id, snapshot)
            await maybe_handle_governance_blockers(recorder, gs, turn, state_id, snapshot)
            await maybe_trade_surplus_strategic_resources(recorder, gs, turn, state_id, snapshot)
            await maybe_spend_gold_for_t50(recorder, gs, turn, state_id, snapshot)
            await maybe_recruit_great_prophet(recorder, gs, turn, state_id, snapshot)
            await maybe_declare_opportunistic_war(recorder, gs, turn, state_id, snapshot)
            founded_city = await handle_units(recorder, gs, turn, state_id, snapshot)
            end_state_id = state_id
            end_snapshot = snapshot
            end_turn = turn
            if founded_city:
                end_turn, end_state_id, end_snapshot = await capture_state(
                    recorder, gs, f"post_found_city_{i + 1}"
                )
                recorder.codex_output(
                    "post_found_city",
                    end_turn,
                    {
                        "state_snapshot_id": end_state_id,
                        "summary": background_from_snapshot(end_snapshot),
                        "reason": "A settler founded a city after the normal production pass; resolve new-city production before end_turn.",
                    },
                )
                await maybe_set_city_production(
                    recorder, gs, end_turn, end_state_id, end_snapshot
                )
            if snapshot_has_great_prophet_unit(snapshot):
                await maybe_found_religion_with_choral(
                    recorder,
                    gs,
                    turn,
                    state_id,
                    snapshot,
                    trigger="religion founding after unit handling",
                )
            end_result = await end_turn_with_record(
                recorder, gs, end_turn, end_state_id, end_snapshot
            )
            recorder.turn_summaries.append(
                {
                    "turn": turn,
                    "state_snapshot_id": state_id,
                    "summary": short_text(end_result, 1000),
                }
            )

        if mode == "t50_observation":
            final_label = "t50_final"
        elif mode == "t20_exploration":
            final_label = "t20_final"
        else:
            final_label = "short_run_final"
        final_turn, final_state_id, _final_snapshot = await capture_state(recorder, gs, final_label)
        recorder.final_turn = final_turn
        await save_checkpoint(recorder, gs, final_turn, final_label)
        recorder.codex_output(
            "t50_pause" if mode == "t50_observation" else "t20_pause" if mode == "t20_exploration" else "short_run_pause",
            final_turn,
            {
                "message": (
                    "T50 observation complete. Stop before T51+ or Review."
                    if mode == "t50_observation"
                    else "T20 exploration complete. Use results as local candidate evidence before longer validation."
                    if mode == "t20_exploration"
                    else "Short run complete. Pausing for human acceptance before any T50 run."
                ),
                "final_state_snapshot_id": final_state_id,
                "report_path": str(recorder.report_path),
            },
        )
    finally:
        try:
            await conn.disconnect()
        except Exception:
            pass

    generate_reports(recorder)
    recorder.write_manifest()
    print(json.dumps({"episode_id": episode_id, "report_path": str(recorder.report_path)}, ensure_ascii=False))
    return 0


def run_report_only(args: argparse.Namespace) -> int:
    view = ExistingEpisodeReportView(args.report_only)
    generate_reports(view)
    view.write_manifest()
    print(
        json.dumps(
            {"episode_id": view.episode_id, "report_path": str(view.report_path)},
            ensure_ascii=False,
        )
    )
    return 0


def run_rebuild_db(args: argparse.Namespace) -> int:
    episode_root = ROOT / "episodes" / args.rebuild_db
    if not episode_root.exists():
        raise FileNotFoundError(f"Episode not found: {episode_root}")
    store = rebuild_episode_db(episode_root)
    exported = store.export_legacy_tree()
    print(
        json.dumps(
            {
                "episode_id": args.rebuild_db,
                "db_path": str(store.db_path),
                "artifact_count": len(store.artifacts()),
                "exported_files": len(exported),
            },
            ensure_ascii=False,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-name", default=DEFAULT_SAVE_NAME)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--episode-id")
    parser.add_argument(
        "--strategy-profile",
        default=BASELINE_STRATEGY_PROFILE,
        choices=sorted(STRATEGY_PROFILES),
        help="Runtime strategy profile. Non-baseline profiles are explicit T20 exploration experiments.",
    )
    parser.add_argument(
        "--candidate-package",
        type=Path,
        help="Read a strategy candidate playbook package as read-only runtime guidance for this episode.",
    )
    parser.add_argument(
        "--report-only",
        help="Regenerate the HTML report and manifest for an existing episode without running Civ6.",
    )
    parser.add_argument(
        "--rebuild-db",
        help="Build or replace episode.db for an existing episode from its legacy file tree without running Civ6.",
    )
    parser.add_argument(
        "--keep-existing-mcp-server",
        action="store_true",
        help="Do not stop repo-local civ6-connector server processes before the direct observation run.",
    )
    parser.add_argument(
        "--reuse-running-game",
        action="store_true",
        help="Reuse the current Civ6 process instead of resetting to the front end before loading the save.",
    )
    args = parser.parse_args()
    if not args.report_only and not args.rebuild_db and not valid_observation_turns(args.turns):
        parser.error(
            f"--turns must be {MIN_SHORT_RUN_TURNS}-{MAX_SHORT_RUN_TURNS} for Observation short-run validation, {T20_EXPLORATION_TURNS} for T20 exploration, or {T50_OBSERVATION_TURNS} for T50 observation"
        )
    return args


def main() -> None:
    args = parse_args()
    if args.rebuild_db:
        raise SystemExit(run_rebuild_db(args))
    if args.report_only:
        raise SystemExit(run_report_only(args))
    raise SystemExit(asyncio.run(run_short(args)))


if __name__ == "__main__":
    main()

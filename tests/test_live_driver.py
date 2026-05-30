from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

from codex_hl.live.gateway import ActionGateway, GatewayMode
from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import StepStatus
from codex_hl.live.driver import (
    capture_context,
    end_turn,
    execute_step,
    maybe_found_initial_city,
    maybe_expand_with_settler,
    maybe_set_city_production,
)
from codex_hl.live.verifier import PostconditionVerifier


class FakeGameState:
    def __init__(self) -> None:
        self.turn = 1
        self.cities: list[dict] = []
        self.units = [
            {
                "unit_id": 65536,
                "unit_index": 0,
                "unit_type": "UNIT_SETTLER",
                "name": "Settler",
                "x": 62,
                "y": 41,
                "moves_remaining": 2,
            },
            {
                "unit_id": 131073,
                "unit_index": 1,
                "unit_type": "UNIT_WARRIOR",
                "name": "Warrior",
                "x": 62,
                "y": 42,
                "moves_remaining": 2,
            },
        ]
        self.production_options = [
            {"category": "UNIT", "item_name": "UNIT_BUILDER", "cost": 50, "turns": 8},
            {"category": "UNIT", "item_name": "UNIT_SLINGER", "cost": 35, "turns": 6},
            {"category": "BUILDING", "item_name": "BUILDING_MONUMENT", "cost": 60, "turns": 10},
        ]

    async def get_game_overview(self) -> dict:
        return {
            "turn": self.turn,
            "num_cities": len(self.cities),
            "gold": 25,
            "gold_per_turn": 2,
            "science_yield": 3,
            "culture_yield": 2,
        }

    async def get_cities(self) -> list[dict]:
        return self.cities

    async def get_units(self) -> list[dict]:
        return self.units

    async def get_notifications(self) -> list[dict]:
        return []

    async def get_tech_civics(self) -> dict:
        return {
            "current_research": "TECH_POTTERY",
            "current_civic": "CIVIC_CODE_OF_LAWS",
            "completed_tech_count": 0,
            "completed_civic_count": 0,
            "available_techs": [],
            "available_civics": [],
        }

    async def get_threat_scan(self) -> list[dict]:
        return []

    async def get_empire_resources(self) -> tuple[list, list, list, dict]:
        return [], [], [], {}

    async def found_city(self, unit_index: int) -> str:
        assert unit_index == 0
        self.cities = [
            {
                "city_id": 1,
                "name": "Capital",
                "x": 62,
                "y": 41,
                "currently_building": "NONE",
                "production_turns_left": 0,
                "loyalty": 100,
                "loyalty_per_turn": 0,
            }
        ]
        self.units = [unit for unit in self.units if unit["unit_type"] != "UNIT_SETTLER"]
        return "FOUNDED|62,41"

    async def list_city_production(self, city_id: int) -> list[dict]:
        assert city_id == 1
        return self.production_options

    async def set_city_production(self, city_id: int, item_type: str, item_name: str) -> str:
        assert city_id == 1
        self.cities[0]["currently_building"] = item_name
        self.cities[0]["production_turns_left"] = 8
        return f"PRODUCING|{item_name}|8"

    async def skip_remaining_units(self) -> str:
        return "SKIPPED|1 units"

    async def move_unit(self, unit_index: int, target_x: int, target_y: int) -> str:
        unit = next(unit for unit in self.units if unit["unit_index"] == unit_index)
        unit["x"] = target_x
        unit["y"] = target_y
        unit["moves_remaining"] = 0
        return f"MOVED|{target_x},{target_y}"

    async def get_global_settle_scan(self) -> list[dict]:
        return []

    async def get_pathing_estimate(self, unit_index: int, target_x: int, target_y: int) -> dict:
        return {"turns": 2, "total_tiles": 4, "reachable_this_turn": 1, "waypoints": []}

    async def end_turn(self) -> str:
        before = self.turn
        self.turn += 1
        return f"Turn {before} -> {self.turn}"


class SlowEndTurnGameState(FakeGameState):
    async def end_turn(self) -> str:
        await asyncio.sleep(10)
        return "never"


class ScoredSettleScanGameState(FakeGameState):
    async def get_global_settle_scan(self) -> list[dict]:
        return [
            {"x": 57, "y": 42, "score": 200, "total_food": 30, "total_prod": 30},
            {"x": 62, "y": 37, "score": 100, "total_food": 25, "total_prod": 25},
        ]

    async def get_pathing_estimate(self, unit_index: int, target_x: int, target_y: int) -> dict:
        if (target_x, target_y) == (57, 42):
            return {"turns": -1, "total_tiles": 0, "reachable_this_turn": 0, "waypoints": []}
        return {"turns": 2, "total_tiles": 4, "reachable_this_turn": 1, "waypoints": []}


def _gateway(tmp_path: Path, episode_id: str) -> tuple[Path, LivePlanStore, ActionGateway]:
    root = tmp_path / episode_id
    store = LivePlanStore.for_episode_root(root, episode_id)
    store.start_episode(
        save_name="test 1",
        target_turns=51,
        mode="live_strict",
        runner="codex-hl-civ6-live-driver",
    )
    ledger = EpisodeLedger.for_episode_root(root, episode_id)
    gateway = ActionGateway(
        mode=GatewayMode.LIVE_STRICT,
        ledger=ledger,
        verifier=PostconditionVerifier(),
        plan_store=store,
    )
    return root, store, gateway


def _events(root: Path) -> list[dict]:
    path = root / "raw" / "live_events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_live_driver_founds_city_before_skipping_units(tmp_path: Path) -> None:
    episode_id = "ep_found_first"
    _root, store, gateway = _gateway(tmp_path, episode_id)
    gs = FakeGameState()
    actions: list[dict] = []
    context = asyncio.run(capture_context(gs, episode_id=episode_id, plan_store=None))

    seq, founded = asyncio.run(
        maybe_found_initial_city(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            context=context,
            actions=actions,
        )
    )

    assert seq == 2
    assert founded is True
    assert actions[0]["tool"] == "unit_action"
    assert actions[0]["args"]["action"] == "found_city"
    assert actions[0]["verifier_status"] == "PASS"
    assert len(gs.cities) == 1


def test_live_driver_found_city_step_reaches_verified_city_count_state(tmp_path: Path) -> None:
    episode_id = "ep_found_verified"
    root, store, gateway = _gateway(tmp_path, episode_id)
    gs = FakeGameState()
    actions: list[dict] = []
    context = asyncio.run(capture_context(gs, episode_id=episode_id, plan_store=None))

    asyncio.run(
        maybe_found_initial_city(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            context=context,
            actions=actions,
        )
    )

    state = store.replay()
    step = state.steps[("p0001_unit_action", "s0001")]
    plan = state.plans["p0001_unit_action"]
    assert step.status is StepStatus.VERIFIED
    assert step.verifier_status == "PASS"
    assert plan.payload["steps"][0]["postconditions"] == [{"type": "city_count_increased"}]
    finished = [event for event in _events(root) if event["event_type"] == "ACTION_FINISHED"][-1]
    assert finished["payload"]["verifier"]["objective_delta"]["city_count_after"] == 1


def test_live_driver_sets_safe_initial_city_production(tmp_path: Path) -> None:
    episode_id = "ep_production"
    _root, store, gateway = _gateway(tmp_path, episode_id)
    gs = FakeGameState()
    asyncio.run(gs.found_city(0))
    actions: list[dict] = []
    context = asyncio.run(capture_context(gs, episode_id=episode_id, plan_store=None))

    seq = asyncio.run(
        maybe_set_city_production(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            context=context,
            actions=actions,
        )
    )

    assert seq == 2
    assert actions[0]["tool"] == "set_city_production"
    assert actions[0]["args"]["item_name"] == "UNIT_BUILDER"
    assert actions[0]["verifier_status"] == "PASS"


def test_live_driver_moves_expansion_settler_when_settle_scan_is_empty(tmp_path: Path) -> None:
    episode_id = "ep_expand_move"
    _root, store, gateway = _gateway(tmp_path, episode_id)
    gs = FakeGameState()
    asyncio.run(gs.found_city(0))
    gs.units.append(
        {
            "unit_id": 262146,
            "unit_index": 2,
            "unit_type": "UNIT_SETTLER",
            "name": "Settler",
            "x": 62,
            "y": 41,
            "moves_remaining": 2,
        }
    )
    actions: list[dict] = []
    context = asyncio.run(capture_context(gs, episode_id=episode_id, plan_store=None))

    seq, founded = asyncio.run(
        maybe_expand_with_settler(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            context=context,
            actions=actions,
            min_cities=2,
        )
    )

    assert seq == 2
    assert founded is False
    assert actions[0]["tool"] == "unit_action"
    assert actions[0]["args"]["action"] == "move"
    assert actions[0]["verifier_status"] == "PASS"


def test_live_driver_moves_expansion_settler_when_exactly_three_tiles_from_city(tmp_path: Path) -> None:
    episode_id = "ep_expand_distance_three"
    _root, store, gateway = _gateway(tmp_path, episode_id)
    gs = FakeGameState()
    asyncio.run(gs.found_city(0))
    gs.units.append(
        {
            "unit_id": 327683,
            "unit_index": 3,
            "unit_type": "UNIT_SETTLER",
            "name": "Settler",
            "x": 62,
            "y": 38,
            "moves_remaining": 2,
        }
    )
    actions: list[dict] = []
    context = asyncio.run(capture_context(gs, episode_id=episode_id, plan_store=None))

    seq, founded = asyncio.run(
        maybe_expand_with_settler(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            context=context,
            actions=actions,
            min_cities=2,
        )
    )

    assert seq == 2
    assert founded is False
    assert actions[0]["tool"] == "unit_action"
    assert actions[0]["args"]["action"] == "move"
    assert actions[0]["verifier_status"] == "PASS"


def test_live_driver_skips_unreachable_settle_scan_candidate(tmp_path: Path) -> None:
    episode_id = "ep_expand_skip_unreachable"
    _root, store, gateway = _gateway(tmp_path, episode_id)
    gs = ScoredSettleScanGameState()
    asyncio.run(gs.found_city(0))
    gs.units.append(
        {
            "unit_id": 327683,
            "unit_index": 3,
            "unit_type": "UNIT_SETTLER",
            "name": "Settler",
            "x": 62,
            "y": 41,
            "moves_remaining": 2,
        }
    )
    actions: list[dict] = []
    context = asyncio.run(capture_context(gs, episode_id=episode_id, plan_store=None))

    seq, founded = asyncio.run(
        maybe_expand_with_settler(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            context=context,
            actions=actions,
            min_cities=2,
        )
    )

    assert seq == 2
    assert founded is False
    assert actions[0]["args"]["action"] == "move"
    assert actions[0]["args"]["target_x"] == 62
    assert actions[0]["args"]["target_y"] == 37
    assert actions[0]["verifier_status"] == "PASS"


def test_live_driver_end_turn_timeout_marks_failed_not_executing(tmp_path: Path) -> None:
    episode_id = "ep_timeout"
    _root, store, gateway = _gateway(tmp_path, episode_id)
    gs = SlowEndTurnGameState()
    asyncio.run(gs.found_city(0))
    actions: list[dict] = []

    _seq, advanced, result = asyncio.run(
        end_turn(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            actions=actions,
            timeout_seconds=0.01,
        )
    )

    counts = Counter(step.status.value for step in store.replay().steps.values())
    assert advanced is False
    assert result["status"] == "failed"
    assert result["error_code"] == "ACTION_TIMEOUT"
    assert counts["FAILED"] == 1
    assert counts["EXECUTING"] == 0


def test_live_driver_recovery_plan_records_metadata_and_lineage(tmp_path: Path) -> None:
    episode_id = "ep_recovery"
    root, store, gateway = _gateway(tmp_path, episode_id)
    gs = FakeGameState()
    asyncio.run(gs.found_city(0))
    lineage = {
        "failed_plan_id": "p0007_end_turn",
        "failed_step_id": "s0007",
        "failed_tool": "end_turn",
        "error_code": "ACTION_TIMEOUT",
    }

    result = asyncio.run(
        execute_step(
            gs=gs,
            gateway=gateway,
            plan_store=store,
            episode_id=episode_id,
            seq=1,
            tool="restart_and_load",
            args={"save_name": "test 1", "force_restart": False},
            fn=lambda: _ok_recovery(),
            postconditions=[{"type": "tool_result_ok"}],
            source="recovery",
            metadata={"plan_kind": "recovery", "recovery_lineage": lineage},
            verify_with_state=False,
        )
    )

    assert result["verifier_status"] == "PASS"
    finished = [event for event in _events(root) if event["event_type"] == "ACTION_FINISHED"][-1]
    assert finished["source"] == "recovery"
    assert finished["payload"]["l4_semantics"] == "recovery_plan"
    assert finished["payload"]["plan_metadata"]["plan_kind"] == "recovery"
    assert finished["payload"]["recovery_lineage"]["failed_step_id"] == "s0007"


async def _ok_recovery() -> str:
    return "RECOVERY_LOAD_OK|test 1"

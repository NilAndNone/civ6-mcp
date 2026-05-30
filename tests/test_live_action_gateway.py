from __future__ import annotations

import asyncio
import json

import pytest

from codex_hl.evidence.store import EpisodeReader, EpisodeStore
from codex_hl.live.gateway import ActionGateway, ActionRequest, GatewayMode
from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import normalize_turn_plan


def _read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _planned_gateway(
    tmp_path,
    *,
    episode_id: str,
    tool: str,
    args: dict,
    allowed_mutation_level: str,
    metadata: dict | None = None,
) -> tuple[LivePlanStore, ActionGateway]:
    episode_root = tmp_path / episode_id
    store = LivePlanStore.for_episode_root(episode_root, episode_id)
    store.start_episode(
        save_name="test 1",
        target_turns=3,
        mode="live_strict",
        runner="live-json-plan",
    )
    store.record_turn_context(
        turn=1,
        branch_id="b000",
        context_hash="ctx-123",
        payload={"overview": {"turn": 1}},
    )
    store.submit_plan(
        normalize_turn_plan(
            {
                "episode_id": episode_id,
                "plan_id": "plan-001",
                "turn": 1,
                "branch_id": "b000",
                "context_hash": "ctx-123",
                "metadata": metadata or {},
                "steps": [
                    {
                        "step_id": "s001",
                        "tool": tool,
                        "args": args,
                        "allowed_mutation_level": allowed_mutation_level,
                        "postconditions": [],
                    }
                ],
            }
        )
    )
    store.arm_step("plan-001", "s001")
    ledger = EpisodeLedger.for_episode_root(episode_root, episode_id)
    return store, ActionGateway(
        mode=GatewayMode.LIVE_STRICT,
        ledger=ledger,
        plan_store=store,
    )


def test_live_strict_rejects_l2_without_plan_and_does_not_execute(tmp_path) -> None:
    ledger = EpisodeLedger.for_episode_root(tmp_path / "episode", "ep_strict")
    gateway = ActionGateway(mode=GatewayMode.LIVE_STRICT, ledger=ledger)
    calls: list[str] = []

    async def run_action() -> str:
        calls.append("ran")
        return "OK"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="set_city_production",
                args={
                    "city_id": 1,
                    "item_type": "UNIT",
                    "item_name": "UNIT_SCOUT",
                },
                mutation_level=MutationLevel.L3_HIGH_GAME_MUTATION,
                episode_id="ep_strict",
                turn=1,
            ),
            run_action,
        )
    )

    assert calls == []
    assert result.allowed is False
    assert result.status == "rejected"
    assert "plan_id" in (result.error or "")

    events = _read_events(tmp_path / "episode" / "raw" / "live_events.jsonl")
    assert len(events) == 1
    assert events[0]["event_type"] == "ACTION_REJECTED"
    assert events[0]["source"] == "mcp"
    assert events[0]["tool"] == "set_city_production"
    assert events[0]["unplanned_mutation"] is True


def test_live_strict_allows_l1_without_plan(tmp_path) -> None:
    ledger = EpisodeLedger.for_episode_root(tmp_path / "episode", "ep_l1")
    gateway = ActionGateway(mode=GatewayMode.LIVE_STRICT, ledger=ledger)

    async def run_action() -> str:
        return "TRACE_OK"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="get_gp_advisor",
                args={"focus": "activation"},
                mutation_level=MutationLevel.L1_RUNTIME_SIDE_EFFECT,
                episode_id="ep_l1",
            ),
            run_action,
        )
    )

    assert result.allowed is True
    assert result.result == "TRACE_OK"
    events = _read_events(tmp_path / "episode" / "raw" / "live_events.jsonl")
    assert events[-1]["level"] == "L1"
    assert events[-1]["unplanned_mutation"] is False


def test_live_strict_allows_l0_without_plan(tmp_path) -> None:
    ledger = EpisodeLedger.for_episode_root(tmp_path / "episode", "ep_l0")
    gateway = ActionGateway(mode=GatewayMode.LIVE_STRICT, ledger=ledger)

    async def run_action() -> dict[str, str]:
        return {"status": "READ_OK"}

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="get_units",
                args={},
                mutation_level=MutationLevel.L0_READ,
                episode_id="ep_l0",
            ),
            run_action,
        )
    )

    assert result.allowed is True
    assert result.result == {"status": "READ_OK"}
    events = _read_events(tmp_path / "episode" / "raw" / "live_events.jsonl")
    assert events[-1]["level"] == "L0"
    assert events[-1]["plan_id"] is None
    assert events[-1]["step_id"] is None
    assert events[-1]["unplanned_mutation"] is False


def test_live_strict_allows_l2_with_plan_step(tmp_path) -> None:
    episode_root = tmp_path / "episode"
    store = LivePlanStore.for_episode_root(episode_root, "ep_planned")
    store.start_episode(
        save_name="test 1",
        target_turns=3,
        mode="live_strict",
        runner="live-json-plan",
    )
    store.record_turn_context(
        turn=2,
        branch_id="b000",
        context_hash="ctx-123",
        payload={"overview": {"turn": 2}},
    )
    store.submit_plan(
        normalize_turn_plan(
            {
                "episode_id": "ep_planned",
                "plan_id": "plan-001",
                "turn": 2,
                "branch_id": "b000",
                "context_hash": "ctx-123",
                "steps": [
                    {
                        "step_id": "s001",
                        "tool": "unit_action",
                        "args": {"unit_id": 65536, "action": "skip"},
                        "allowed_mutation_level": "L2",
                        "postconditions": [],
                    }
                ],
            }
        )
    )
    store.arm_step("plan-001", "s001")
    ledger = EpisodeLedger.for_episode_root(episode_root, "ep_planned")
    gateway = ActionGateway(
        mode=GatewayMode.LIVE_STRICT,
        ledger=ledger,
        plan_store=store,
    )

    async def run_action() -> str:
        return "OK"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="unit_action",
                args={"unit_id": 65536, "action": "skip"},
                mutation_level=MutationLevel.L2_LOW_GAME_MUTATION,
                episode_id="ep_planned",
                turn=2,
                plan_id="plan-001",
                step_id="s001",
                context_hash="ctx-123",
            ),
            run_action,
        )
    )

    assert result.allowed is True
    events = _read_events(tmp_path / "episode" / "raw" / "live_events.jsonl")
    assert events[-1]["plan_id"] == "plan-001"
    assert events[-1]["step_id"] == "s001"
    assert events[-1]["context_hash"] == "ctx-123"
    assert events[-1]["unplanned_mutation"] is False
    assert events[-1]["verifier_status"] == "INCONCLUSIVE"


def test_live_strict_marks_normal_l4_end_turn_boundary(tmp_path) -> None:
    _store, gateway = _planned_gateway(
        tmp_path,
        episode_id="ep_l4_end_turn",
        tool="end_turn",
        args={},
        allowed_mutation_level="L4",
    )
    states = [{"overview": {"turn": 1}}, {"overview": {"turn": 2}}]

    async def run_action() -> str:
        return "Turn 1 -> 2"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="end_turn",
                args={},
                mutation_level=MutationLevel.L4_BOUNDARY_RECOVERY,
                episode_id="ep_l4_end_turn",
                turn=1,
                plan_id="plan-001",
                step_id="s001",
                context_hash="ctx-123",
            ),
            run_action,
            state_reader=lambda: states.pop(0),
        )
    )

    assert result.allowed is True
    events = _read_events(tmp_path / "ep_l4_end_turn" / "raw" / "live_events.jsonl")
    assert events[-1]["payload"]["l4_semantics"] == "normal_turn_boundary"
    assert events[-1]["verifier_status"] == "PASS"


def test_live_strict_rejects_save_load_without_recovery_plan_metadata(tmp_path) -> None:
    _store, gateway = _planned_gateway(
        tmp_path,
        episode_id="ep_l4_load_reject",
        tool="load_game_save",
        args={"save_name": "AutoSave_0020"},
        allowed_mutation_level="L4",
    )
    calls: list[str] = []

    async def run_action() -> str:
        calls.append("ran")
        return "Loaded"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="load_game_save",
                args={"save_name": "AutoSave_0020"},
                mutation_level=MutationLevel.L4_BOUNDARY_RECOVERY,
                episode_id="ep_l4_load_reject",
                turn=20,
                plan_id="plan-001",
                step_id="s001",
                context_hash="ctx-123",
            ),
            run_action,
        )
    )

    assert calls == []
    assert result.allowed is False
    assert result.error_code == "LIVE_RECOVERY_PLAN_REQUIRED"
    events = _read_events(tmp_path / "ep_l4_load_reject" / "raw" / "live_events.jsonl")
    assert events[-1]["event_type"] == "ACTION_REJECTED"
    assert events[-1]["payload"]["l4_semantics"] == "l4_boundary"


def test_live_strict_records_explicit_recovery_l4_lineage(tmp_path) -> None:
    _store, gateway = _planned_gateway(
        tmp_path,
        episode_id="ep_l4_recovery",
        tool="load_game_save",
        args={"save_name": "AutoSave_0020"},
        allowed_mutation_level="L4",
        metadata={
            "plan_kind": "recovery",
            "recovery_lineage": {"failed_plan_id": "plan-prev", "failed_step_id": "s009"},
        },
    )

    async def run_action() -> str:
        return "Loaded AutoSave_0020"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="load_game_save",
                args={"save_name": "AutoSave_0020"},
                mutation_level=MutationLevel.L4_BOUNDARY_RECOVERY,
                episode_id="ep_l4_recovery",
                turn=20,
                plan_id="plan-001",
                step_id="s001",
                context_hash="ctx-123",
            ),
            run_action,
        )
    )

    assert result.allowed is True
    events = _read_events(tmp_path / "ep_l4_recovery" / "raw" / "live_events.jsonl")
    assert events[-1]["payload"]["l4_semantics"] == "recovery_plan"
    assert events[-1]["payload"]["plan_metadata"]["plan_kind"] == "recovery"
    assert events[-1]["payload"]["recovery_lineage"]["failed_step_id"] == "s009"


def test_episode_ledger_mirrors_live_events_to_episode_db(tmp_path) -> None:
    episode_root = tmp_path / "episode"
    store = EpisodeStore(episode_root, "ep_db_live", create=True, reset=True)
    store.put_episode_header(
        {"episode_id": "ep_db_live", "workflow": "live-json-plan"},
        workflow="live-json-plan",
        save_name="test 1",
        requested_turns=3,
    )
    store.close()

    ledger = EpisodeLedger.for_episode_root(episode_root, "ep_db_live")
    request = ActionRequest(
        source="mcp",
        tool_name="unit_action",
        args={"unit_id": 65536, "action": "skip"},
        mutation_level=MutationLevel.L2_LOW_GAME_MUTATION,
        episode_id="ep_db_live",
        turn=1,
    )
    event_id = ledger.append_event(
        event_type="ACTION_FINISHED",
        request=request,
        mode=GatewayMode.LIVE_STRICT.value,
        allowed=True,
        status="executed",
        unplanned_mutation=True,
        result="OK",
    )

    rows = EpisodeReader(episode_root).read_jsonl("raw/live_events.jsonl")
    assert rows[0]["event_id"] == event_id
    assert rows[0]["event_type"] == "ACTION_FINISHED"
    assert rows[0]["tool"] == "unit_action"


def test_episode_ledger_keeps_process_local_seq_across_instances(
    monkeypatch, tmp_path
) -> None:
    read_calls: list[str] = []
    original_read_last_seq = EpisodeLedger._read_last_seq

    def spy_read_last_seq(self):
        read_calls.append(str(self.event_path))
        return original_read_last_seq(self)

    monkeypatch.setattr(EpisodeLedger, "_read_last_seq", spy_read_last_seq)

    ledger_root = tmp_path / "episode"
    ledger_a = EpisodeLedger.for_episode_root(ledger_root, "ep_seq")
    ledger_b = EpisodeLedger.for_episode_root(ledger_root, "ep_seq")
    request = ActionRequest(
        source="mcp",
        tool_name="set_research",
        args={"tech_or_civic": "TECH_POTTERY", "category": "tech"},
        mutation_level=MutationLevel.L2_LOW_GAME_MUTATION,
        episode_id="ep_seq",
    )

    ledger_a.append_event(
        event_type="ACTION_STARTED",
        request=request,
        mode=GatewayMode.LIVE_STRICT.value,
        allowed=True,
        status="executing",
        unplanned_mutation=True,
    )
    ledger_b.append_event(
        event_type="ACTION_FINISHED",
        request=request,
        mode=GatewayMode.LIVE_STRICT.value,
        allowed=True,
        status="executed",
        unplanned_mutation=True,
        result="OK",
    )

    events = _read_events(ledger_root / "raw" / "live_events.jsonl")
    assert [event["seq"] for event in events] == [1, 2]
    assert len(read_calls) == 1

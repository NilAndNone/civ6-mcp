from __future__ import annotations

import asyncio
import json

import pytest

from codex_hl.live.gateway import ActionGateway, ActionRequest, GatewayMode
from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import normalize_turn_plan


def _read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("mode", [GatewayMode.LEGACY_COMPAT, GatewayMode.SHADOW])
def test_compat_and_shadow_allow_unplanned_l2_mutation_and_record_ledger(
    tmp_path, mode
) -> None:
    ledger = EpisodeLedger.for_episode_root(tmp_path / "episode", "ep_shadow")
    gateway = ActionGateway(mode=mode, ledger=ledger)
    calls: list[str] = []

    async def run_action() -> str:
        calls.append("ran")
        return "OK"

    result = asyncio.run(
        gateway.execute(
            ActionRequest(
                source="mcp",
                tool_name="set_research",
                args={"tech_or_civic": "TECH_POTTERY", "category": "tech"},
                mutation_level=MutationLevel.L2_LOW_GAME_MUTATION,
                episode_id="ep_shadow",
                turn=1,
            ),
            run_action,
        )
    )

    assert calls == ["ran"]
    assert result.allowed is True
    assert result.status == "executed"
    assert result.result == "OK"

    events = _read_events(tmp_path / "episode" / "raw" / "live_events.jsonl")
    finished = events[-1]
    assert finished["event_type"] == "ACTION_FINISHED"
    assert finished["source"] == "mcp"
    assert finished["tool"] == "set_research"
    assert finished["level"] == "L2"
    assert finished["args"] == {"tech_or_civic": "TECH_POTTERY", "category": "tech"}
    assert finished["plan_id"] is None
    assert finished["step_id"] is None
    assert finished["unplanned_mutation"] is True
    assert result.ledger_event_ids == [event["event_id"] for event in events]


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
        mode=GatewayMode.SHADOW.value,
        allowed=True,
        status="executing",
        unplanned_mutation=True,
    )
    ledger_b.append_event(
        event_type="ACTION_FINISHED",
        request=request,
        mode=GatewayMode.SHADOW.value,
        allowed=True,
        status="executed",
        unplanned_mutation=True,
        result="OK",
    )

    events = _read_events(ledger_root / "raw" / "live_events.jsonl")
    assert [event["seq"] for event in events] == [1, 2]
    assert len(read_calls) == 1

from __future__ import annotations

import asyncio
import json

from codex_hl.live.gateway import ActionGateway, ActionRequest, GatewayMode
from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import normalize_turn_plan


def plan_payload(**step_overrides) -> dict:
    step = {
        "step_id": "s001",
        "tool": "unit_action",
        "args": {"unit_id": 65536, "action": "skip"},
        "allowed_mutation_level": "L2",
        "postconditions": [],
    }
    step.update(step_overrides)
    return {
        "episode_id": "ep_guard",
        "plan_id": "plan_t0001_v01",
        "turn": 1,
        "branch_id": "b000",
        "context_hash": "sha256:ctx",
        "steps": [step],
    }


def make_gateway(tmp_path, *, arm: bool = True, plan: dict | None = None) -> ActionGateway:
    root = tmp_path / "ep_guard"
    store = LivePlanStore.for_episode_root(root, "ep_guard")
    store.start_episode(
        save_name="test 1",
        target_turns=3,
        mode="live_strict",
        runner="live-json-plan",
    )
    store.record_turn_context(
        turn=1,
        branch_id="b000",
        context_hash="sha256:ctx",
        payload={"overview": {"turn": 1}},
    )
    store.submit_plan(normalize_turn_plan(plan or plan_payload()))
    if arm:
        store.arm_step("plan_t0001_v01", "s001")
    ledger = EpisodeLedger.for_episode_root(root, "ep_guard")
    return ActionGateway(
        mode=GatewayMode.LIVE_STRICT,
        ledger=ledger,
        plan_store=store,
    )


def request(**overrides) -> ActionRequest:
    data = {
        "source": "mcp",
        "tool_name": "unit_action",
        "args": {"unit_id": 65536, "action": "skip"},
        "mutation_level": MutationLevel.L2_LOW_GAME_MUTATION,
        "episode_id": "ep_guard",
        "turn": 1,
        "plan_id": "plan_t0001_v01",
        "step_id": "s001",
        "context_hash": "sha256:ctx",
        "branch_id": "b000",
    }
    data.update(overrides)
    return ActionRequest(**data)


def test_live_strict_rejects_step_that_is_not_armed(tmp_path) -> None:
    gateway = make_gateway(tmp_path, arm=False)
    calls: list[str] = []

    result = asyncio.run(gateway.execute(request(), lambda: calls.append("ran")))

    assert calls == []
    assert result.allowed is False
    assert result.error_code == "LIVE_STEP_NOT_ARMED"


def test_live_strict_rejects_stale_context_hash(tmp_path) -> None:
    gateway = make_gateway(tmp_path)

    result = asyncio.run(
        gateway.execute(request(context_hash="sha256:stale"), lambda: "OK")
    )

    assert result.allowed is False
    assert result.error_code == "LIVE_CONTEXT_STALE"


def test_live_strict_rejects_args_mismatch(tmp_path) -> None:
    gateway = make_gateway(tmp_path)

    result = asyncio.run(
        gateway.execute(
            request(args={"unit_id": 65536, "action": "fortify"}),
            lambda: "OK",
        )
    )

    assert result.allowed is False
    assert result.error_code == "LIVE_ARGS_MISMATCH"


def test_live_strict_rejects_mutation_above_step_allowance(tmp_path) -> None:
    gateway = make_gateway(tmp_path)

    result = asyncio.run(
        gateway.execute(
            request(mutation_level=MutationLevel.L3_HIGH_GAME_MUTATION),
            lambda: "OK",
        )
    )

    assert result.allowed is False
    assert result.error_code == "LIVE_MUTATION_LEVEL_DENIED"


def test_live_strict_executes_once_then_rejects_duplicate_step(tmp_path) -> None:
    gateway = make_gateway(tmp_path)
    calls: list[str] = []

    first = asyncio.run(
        gateway.execute(request(), lambda: calls.append("ran") or "OK")
    )
    second = asyncio.run(
        gateway.execute(request(request_id="act-duplicate"), lambda: "OK_AGAIN")
    )

    assert calls == ["ran"]
    assert first.allowed is True
    assert second.allowed is False
    assert second.error_code == "LIVE_STEP_NOT_ARMED"

    rows = [
        json.loads(line)
        for line in (tmp_path / "ep_guard" / "raw" / "live_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows[-1]["event_type"] == "ACTION_REJECTED"
    assert rows[-1]["payload"]["error_code"] == "LIVE_STEP_NOT_ARMED"

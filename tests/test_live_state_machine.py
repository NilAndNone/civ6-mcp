from __future__ import annotations

import pytest

from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import EpisodeStatus, StepStatus, normalize_turn_plan
from codex_hl.live.state_machine import LiveStateError


def plan_payload() -> dict:
    return {
        "episode_id": "ep_state",
        "plan_id": "plan_t0001_v01",
        "turn": 1,
        "branch_id": "b000",
        "context_hash": "sha256:ctx",
        "steps": [
            {
                "step_id": "s001",
                "tool": "set_research",
                "args": {"tech_or_civic": "TECH_POTTERY", "category": "tech"},
                "allowed_mutation_level": "L2",
                "postconditions": [
                    {
                        "type": "research_or_civic_selected",
                        "category": "tech",
                        "value": "TECH_POTTERY",
                    }
                ],
            }
        ],
    }


def test_live_plan_store_replays_submit_arm_verify_finish(tmp_path) -> None:
    store = LivePlanStore.for_episode_root(tmp_path / "ep_state", "ep_state")

    started = store.start_episode(
        save_name="test 1",
        target_turns=3,
        mode="live_strict",
        runner="live-json-plan",
    )
    assert started.status == EpisodeStatus.EPISODE_STARTED

    context = store.record_turn_context(
        turn=1,
        branch_id="b000",
        context_hash="sha256:ctx",
        payload={"overview": {"turn": 1}},
    )
    assert context["status"] == "TURN_CONTEXT_RECORDED"

    submitted = store.submit_plan(normalize_turn_plan(plan_payload()))
    assert submitted["status"] == "PLAN_SUBMITTED"
    assert submitted["step_count"] == 1

    armed = store.arm_step("plan_t0001_v01", "s001")
    assert armed["status"] == "STEP_ARMED"
    assert store.get_step("plan_t0001_v01", "s001").status == StepStatus.ARMED

    store.mark_step_executing("plan_t0001_v01", "s001", request_id="act-001")
    store.mark_step_result(
        "plan_t0001_v01",
        "s001",
        request_id="act-001",
        verifier_status="PASS",
        ledger_event_ids=["live-000001-test"],
    )
    assert store.get_step("plan_t0001_v01", "s001").status == StepStatus.VERIFIED

    finished = store.finish_episode()
    assert finished["status"] == EpisodeStatus.EPISODE_FINISHED.value


def test_arm_step_requires_submitted_step(tmp_path) -> None:
    store = LivePlanStore.for_episode_root(tmp_path / "ep_state", "ep_state")
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
    store.submit_plan(normalize_turn_plan(plan_payload()))

    with pytest.raises(LiveStateError, match="step not found"):
        store.arm_step("plan_t0001_v01", "missing")


def test_postcondition_failure_enters_recovery_state(tmp_path) -> None:
    store = LivePlanStore.for_episode_root(tmp_path / "ep_recovery", "ep_state")
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
    store.submit_plan(normalize_turn_plan(plan_payload()))
    store.arm_step("plan_t0001_v01", "s001")
    store.mark_step_executing("plan_t0001_v01", "s001", request_id="act-001")

    store.mark_step_result(
        "plan_t0001_v01",
        "s001",
        request_id="act-001",
        verifier_status="FAIL",
        ledger_event_ids=[],
    )

    assert store.get_episode().status == EpisodeStatus.NEED_RECOVERY_PLAN
    with pytest.raises(LiveStateError, match="NEED_RECOVERY_PLAN"):
        store.finish_episode()


def test_finish_rejects_unverified_executed_steps(tmp_path) -> None:
    store = LivePlanStore.for_episode_root(tmp_path / "ep_unverified", "ep_state")
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
    store.submit_plan(normalize_turn_plan(plan_payload()))
    store.arm_step("plan_t0001_v01", "s001")
    store.mark_step_executing("plan_t0001_v01", "s001", request_id="act-001")
    store.mark_step_result(
        "plan_t0001_v01",
        "s001",
        request_id="act-001",
        verifier_status="INCONCLUSIVE",
        ledger_event_ids=[],
    )

    with pytest.raises(LiveStateError, match="unverified executed step"):
        store.finish_episode()

from __future__ import annotations

import pytest

from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.schemas import LivePlanValidationError, normalize_turn_plan


def valid_plan() -> dict:
    return {
        "episode_id": "live_ep",
        "plan_id": "plan_t0012_v01",
        "turn": 12,
        "branch_id": "b000",
        "context_hash": "sha256:abc123",
        "steps": [
            {
                "step_id": "s001",
                "tool": "unit_action",
                "args": {
                    "unit_id": 65536,
                    "action": "move",
                    "target_x": 4,
                    "target_y": 7,
                },
                "allowed_mutation_level": "L3",
                "postconditions": [
                    {
                        "type": "unit_position_changed_or_blocked",
                        "unit_id": 65536,
                        "target": {"x": 4, "y": 7},
                    }
                ],
            }
        ],
    }


def test_normalize_turn_plan_accepts_documented_shape() -> None:
    plan = normalize_turn_plan(valid_plan())

    assert plan.episode_id == "live_ep"
    assert plan.plan_id == "plan_t0012_v01"
    assert plan.context_hash == "sha256:abc123"
    assert plan.steps[0].step_id == "s001"
    assert plan.steps[0].tool == "unit_action"
    assert plan.steps[0].allowed_mutation_level == MutationLevel.L3_HIGH_GAME_MUTATION
    assert plan.steps[0].args["target_x"] == 4


@pytest.mark.parametrize(
    "field",
    ["episode_id", "plan_id", "turn", "branch_id", "context_hash", "steps"],
)
def test_normalize_turn_plan_rejects_missing_required_fields(field: str) -> None:
    payload = valid_plan()
    payload.pop(field)

    with pytest.raises(LivePlanValidationError, match=field):
        normalize_turn_plan(payload)


def test_normalize_turn_plan_rejects_duplicate_step_ids() -> None:
    payload = valid_plan()
    payload["steps"].append(dict(payload["steps"][0]))

    with pytest.raises(LivePlanValidationError, match="duplicate step_id"):
        normalize_turn_plan(payload)


def test_normalize_turn_plan_rejects_non_object_args() -> None:
    payload = valid_plan()
    payload["steps"][0]["args"] = ["unit_action", "move"]

    with pytest.raises(LivePlanValidationError, match="args"):
        normalize_turn_plan(payload)


def test_normalize_turn_plan_rejects_unknown_mutation_level() -> None:
    payload = valid_plan()
    payload["steps"][0]["allowed_mutation_level"] = "L9"

    with pytest.raises(LivePlanValidationError, match="allowed_mutation_level"):
        normalize_turn_plan(payload)

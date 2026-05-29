from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from codex_hl.live.mutation_levels import MutationLevel


class LivePlanValidationError(ValueError):
    """Raised when a submitted live turn plan is not safe to store."""


class EpisodeStatus(str, Enum):
    EPISODE_STARTED = "EPISODE_STARTED"
    TURN_CONTEXT_READY = "TURN_CONTEXT_READY"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    STEP_ARMED = "STEP_ARMED"
    STEP_EXECUTING = "STEP_EXECUTING"
    STEP_EXECUTED = "STEP_EXECUTED"
    STEP_VERIFIED = "STEP_VERIFIED"
    NEED_RECOVERY_PLAN = "NEED_RECOVERY_PLAN"
    EPISODE_ABORTED = "EPISODE_ABORTED"
    EPISODE_FINISHED = "EPISODE_FINISHED"
    EPISODE_FAILED = "EPISODE_FAILED"

    def is_terminal(self) -> bool:
        return self in {
            EpisodeStatus.EPISODE_ABORTED,
            EpisodeStatus.EPISODE_FINISHED,
            EpisodeStatus.EPISODE_FAILED,
        }


class StepStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ARMED = "ARMED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class LivePlanStep:
    step_id: str
    tool: str
    args: dict[str, Any]
    allowed_mutation_level: MutationLevel
    postconditions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    rationale: str = ""
    fragment_allowed: bool = False

    def args_fingerprint(self) -> str:
        return canonical_json(self.args)


@dataclass(frozen=True)
class LiveTurnPlan:
    episode_id: str
    plan_id: str
    turn: int
    branch_id: str
    context_hash: str
    steps: tuple[LivePlanStep, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_object(payload: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LivePlanValidationError(f"{label} must be a JSON object")
    return payload


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LivePlanValidationError(f"{key} must be a non-empty string")
    return value.strip()


def _coerce_turn(payload: dict[str, Any]) -> int:
    value = payload.get("turn")
    if not isinstance(value, int) or value < 0:
        raise LivePlanValidationError("turn must be a non-negative integer")
    return value


def mutation_level_from_value(value: Any, *, field_name: str = "allowed_mutation_level") -> MutationLevel:
    if isinstance(value, MutationLevel):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        for level in MutationLevel:
            if stripped == level.value or stripped == level.name:
                return level
    raise LivePlanValidationError(f"{field_name} must be one of L0, L1, L2, L3, L4, L5")


def normalize_turn_plan(payload: Any) -> LiveTurnPlan:
    payload = _require_object(payload, label="live turn plan")
    episode_id = _require_text(payload, "episode_id")
    plan_id = _require_text(payload, "plan_id")
    turn = _coerce_turn(payload)
    branch_id = _require_text(payload, "branch_id")
    context_hash = _require_text(payload, "context_hash")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise LivePlanValidationError("steps must be a non-empty list")

    steps: list[LivePlanStep] = []
    seen_step_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps, start=1):
        step = _require_object(raw_step, label=f"steps[{index}]")
        step_id = _require_text(step, "step_id")
        if step_id in seen_step_ids:
            raise LivePlanValidationError(f"duplicate step_id: {step_id}")
        seen_step_ids.add(step_id)
        tool = _require_text(step, "tool")
        args = step.get("args")
        if not isinstance(args, dict):
            raise LivePlanValidationError(f"steps[{index}].args must be a JSON object")
        level_value = step.get("allowed_mutation_level", step.get("mutation_level"))
        allowed_level = mutation_level_from_value(level_value)
        postconditions = step.get("postconditions", [])
        if not isinstance(postconditions, list):
            raise LivePlanValidationError(
                f"steps[{index}].postconditions must be a list"
            )
        normalized_postconditions: list[dict[str, Any]] = []
        for post_index, postcondition in enumerate(postconditions, start=1):
            if not isinstance(postcondition, dict):
                raise LivePlanValidationError(
                    f"steps[{index}].postconditions[{post_index}] must be a JSON object"
                )
            normalized_postconditions.append(dict(postcondition))
        rationale = step.get("rationale", "")
        if rationale is not None and not isinstance(rationale, str):
            raise LivePlanValidationError(f"steps[{index}].rationale must be a string")
        fragment_allowed = step.get("fragment_allowed", False)
        if not isinstance(fragment_allowed, bool):
            raise LivePlanValidationError(
                f"steps[{index}].fragment_allowed must be a boolean"
            )
        steps.append(
            LivePlanStep(
                step_id=step_id,
                tool=tool,
                args=dict(args),
                allowed_mutation_level=allowed_level,
                postconditions=tuple(normalized_postconditions),
                rationale=str(rationale or ""),
                fragment_allowed=fragment_allowed,
            )
        )

    metadata = payload.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise LivePlanValidationError("metadata must be a JSON object")
    return LiveTurnPlan(
        episode_id=episode_id,
        plan_id=plan_id,
        turn=turn,
        branch_id=branch_id,
        context_hash=context_hash,
        steps=tuple(steps),
        metadata=dict(metadata),
    )


def plan_to_payload(plan: LiveTurnPlan) -> dict[str, Any]:
    return {
        "episode_id": plan.episode_id,
        "plan_id": plan.plan_id,
        "turn": plan.turn,
        "branch_id": plan.branch_id,
        "context_hash": plan.context_hash,
        "metadata": plan.metadata,
        "steps": [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "args": step.args,
                "allowed_mutation_level": step.allowed_mutation_level.value,
                "postconditions": list(step.postconditions),
                "rationale": step.rationale,
                "fragment_allowed": step.fragment_allowed,
            }
            for step in plan.steps
        ],
    }

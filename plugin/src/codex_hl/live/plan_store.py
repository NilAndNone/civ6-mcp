from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codex_hl.live.ledger import (
    mirror_jsonl_to_episode_db,
    now_iso,
    read_jsonl_from_episode_db,
    to_jsonable,
)
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.schemas import (
    EpisodeStatus,
    LivePlanStep,
    LiveTurnPlan,
    StepStatus,
    canonical_json,
    plan_to_payload,
)
from codex_hl.live.state_machine import (
    LiveStateError,
    next_after_verifier,
    next_episode_after_arm,
    next_episode_after_context,
    next_episode_after_plan,
    next_step_after_arm,
    next_step_after_execute,
    require_episode_active,
)


LIVE_PLAN_EVENTS_LOGICAL_PATH = "raw/live_plan_events.jsonl"
LIVE_EVENTS_LOGICAL_PATH = "raw/live_events.jsonl"


@dataclass
class LiveEpisodeRecord:
    episode_id: str
    status: EpisodeStatus
    save_name: str
    target_turns: int
    mode: str
    runner: str
    branch_id: str = "b000"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LivePlanRecord:
    episode_id: str
    plan_id: str
    turn: int
    branch_id: str
    context_hash: str
    payload: dict[str, Any]
    submitted_at: str


@dataclass
class LiveStepRecord:
    episode_id: str
    plan_id: str
    step_id: str
    tool: str
    args: dict[str, Any]
    args_fingerprint: str
    allowed_mutation_level: str
    fragment_allowed: bool = False
    postconditions: list[dict[str, Any]] = field(default_factory=list)
    status: StepStatus = StepStatus.SUBMITTED
    request_id: str | None = None
    verifier_status: str | None = None
    pre_state_hash: str | None = None
    post_state_hash: str | None = None
    ledger_event_ids: list[str] = field(default_factory=list)


@dataclass
class LivePlanState:
    episode: LiveEpisodeRecord | None = None
    plans: dict[str, LivePlanRecord] = field(default_factory=dict)
    steps: dict[tuple[str, str], LiveStepRecord] = field(default_factory=dict)
    contexts: dict[tuple[int, str], dict[str, Any]] = field(default_factory=dict)


class LivePlanStore:
    """Append-only JSONL source for live episode plan lifecycle state."""

    def __init__(self, *, episode_root: Path, episode_id: str) -> None:
        self.episode_root = episode_root.resolve()
        self.episode_id = episode_id
        self.events_path = self.episode_root / LIVE_PLAN_EVENTS_LOGICAL_PATH

    @classmethod
    def for_episode_root(cls, episode_root: Path, episode_id: str) -> "LivePlanStore":
        return cls(episode_root=episode_root, episode_id=episode_id)

    def _read_events(self) -> list[dict[str, Any]]:
        db_rows = read_jsonl_from_episode_db(
            episode_root=self.episode_root,
            episode_id=self.episode_id,
            logical_path=LIVE_PLAN_EVENTS_LOGICAL_PATH,
        )
        if db_rows is not None:
            return db_rows
        if not self.events_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
        return rows

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "event_id": f"plan-{uuid.uuid4().hex}",
            "episode_id": self.episode_id,
            "ts": now_iso(),
            "event_type": event_type,
            "payload": to_jsonable(payload),
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
        mirror_jsonl_to_episode_db(
            episode_root=self.episode_root,
            episode_id=self.episode_id,
            logical_path=LIVE_PLAN_EVENTS_LOGICAL_PATH,
            source_path=self.events_path,
            kind="live_plan_events",
        )
        return row

    def replay(self) -> LivePlanState:
        state = LivePlanState()
        for row in self._read_events():
            event_type = str(row.get("event_type") or "")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            ts = str(row.get("ts") or "")
            if event_type == "EPISODE_STARTED":
                state.episode = LiveEpisodeRecord(
                    episode_id=str(payload.get("episode_id") or self.episode_id),
                    status=EpisodeStatus.EPISODE_STARTED,
                    save_name=str(payload.get("save_name") or ""),
                    target_turns=int(payload.get("target_turns") or 0),
                    mode=str(payload.get("mode") or ""),
                    runner=str(payload.get("runner") or ""),
                    branch_id=str(payload.get("branch_id") or "b000"),
                    created_at=ts,
                    updated_at=ts,
                )
            elif event_type == "TURN_CONTEXT_RECORDED" and state.episode is not None:
                state.episode.status = EpisodeStatus(str(payload.get("status")))
                state.episode.updated_at = ts
                state.contexts[
                    (
                        int(payload.get("turn") or 0),
                        str(payload.get("branch_id") or state.episode.branch_id),
                    )
                ] = dict(payload)
            elif event_type == "PLAN_SUBMITTED" and state.episode is not None:
                plan_payload = payload.get("plan")
                if isinstance(plan_payload, dict):
                    plan_id = str(plan_payload.get("plan_id"))
                    state.plans[plan_id] = LivePlanRecord(
                        episode_id=str(plan_payload.get("episode_id") or self.episode_id),
                        plan_id=plan_id,
                        turn=int(plan_payload.get("turn") or 0),
                        branch_id=str(plan_payload.get("branch_id") or "b000"),
                        context_hash=str(plan_payload.get("context_hash") or ""),
                        payload=dict(plan_payload),
                        submitted_at=ts,
                    )
                    for raw_step in plan_payload.get("steps") or []:
                        if not isinstance(raw_step, dict):
                            continue
                        step_id = str(raw_step.get("step_id") or "")
                        args = raw_step.get("args") if isinstance(raw_step.get("args"), dict) else {}
                        state.steps[(plan_id, step_id)] = LiveStepRecord(
                            episode_id=self.episode_id,
                            plan_id=plan_id,
                            step_id=step_id,
                            tool=str(raw_step.get("tool") or ""),
                            args=dict(args),
                            args_fingerprint=canonical_json(args),
                            allowed_mutation_level=str(
                                raw_step.get("allowed_mutation_level") or ""
                            ),
                            fragment_allowed=bool(raw_step.get("fragment_allowed", False)),
                            postconditions=list(raw_step.get("postconditions") or []),
                            status=StepStatus.SUBMITTED,
                        )
                    state.episode.status = EpisodeStatus.PLAN_SUBMITTED
                    state.episode.updated_at = ts
            elif event_type == "STEP_ARMED" and state.episode is not None:
                key = (str(payload.get("plan_id") or ""), str(payload.get("step_id") or ""))
                step = state.steps.get(key)
                if step is not None:
                    step.status = StepStatus.ARMED
                state.episode.status = EpisodeStatus.STEP_ARMED
                state.episode.updated_at = ts
            elif event_type == "STEP_EXECUTING" and state.episode is not None:
                key = (str(payload.get("plan_id") or ""), str(payload.get("step_id") or ""))
                step = state.steps.get(key)
                if step is not None:
                    step.status = StepStatus.EXECUTING
                    step.request_id = str(payload.get("request_id") or "")
                state.episode.status = EpisodeStatus.STEP_EXECUTING
                state.episode.updated_at = ts
            elif event_type == "STEP_RESULT_RECORDED" and state.episode is not None:
                key = (str(payload.get("plan_id") or ""), str(payload.get("step_id") or ""))
                step = state.steps.get(key)
                episode_status = EpisodeStatus(str(payload.get("episode_status")))
                step_status = StepStatus(str(payload.get("step_status")))
                if step is not None:
                    step.status = step_status
                    step.request_id = str(payload.get("request_id") or "")
                    step.verifier_status = str(payload.get("verifier_status") or "")
                    step.pre_state_hash = payload.get("pre_state_hash")
                    step.post_state_hash = payload.get("post_state_hash")
                    step.ledger_event_ids = list(payload.get("ledger_event_ids") or [])
                state.episode.status = episode_status
                state.episode.updated_at = ts
            elif event_type in {"EPISODE_ABORTED", "EPISODE_FINISHED", "EPISODE_FAILED"} and state.episode is not None:
                state.episode.status = EpisodeStatus(event_type)
                state.episode.updated_at = ts
        return state

    def get_episode(self) -> LiveEpisodeRecord:
        episode = self.replay().episode
        if episode is None:
            raise LiveStateError(f"active episode not found: {self.episode_id}")
        return episode

    def get_plan(self, plan_id: str) -> LivePlanRecord:
        plan = self.replay().plans.get(plan_id)
        if plan is None:
            raise LiveStateError(f"plan not found: {plan_id}")
        return plan

    def get_step(self, plan_id: str, step_id: str) -> LiveStepRecord:
        step = self.replay().steps.get((plan_id, step_id))
        if step is None:
            raise LiveStateError(f"step not found: {plan_id}/{step_id}")
        return step

    def start_episode(
        self,
        *,
        save_name: str,
        target_turns: int,
        mode: str,
        runner: str,
        branch_id: str = "b000",
    ) -> LiveEpisodeRecord:
        if self.events_path.exists():
            episode = self.get_episode()
            if not episode.status.is_terminal():
                raise LiveStateError(f"episode already active: {self.episode_id}")
        self._append_event(
            "EPISODE_STARTED",
            {
                "episode_id": self.episode_id,
                "status": EpisodeStatus.EPISODE_STARTED.value,
                "save_name": save_name,
                "target_turns": target_turns,
                "mode": mode,
                "runner": runner,
                "branch_id": branch_id,
            },
        )
        return self.get_episode()

    def record_turn_context(
        self,
        *,
        turn: int,
        branch_id: str,
        context_hash: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        episode = self.get_episode()
        new_status = next_episode_after_context(episode.status)
        self._append_event(
            "TURN_CONTEXT_RECORDED",
            {
                "status": new_status.value,
                "turn": turn,
                "branch_id": branch_id,
                "context_hash": context_hash,
                "context": payload,
            },
        )
        return {
            "episode_id": self.episode_id,
            "turn": turn,
            "branch_id": branch_id,
            "context_hash": context_hash,
            "status": "TURN_CONTEXT_RECORDED",
        }

    def submit_plan(self, plan: LiveTurnPlan) -> dict[str, Any]:
        if plan.episode_id != self.episode_id:
            raise LiveStateError(
                f"plan episode_id {plan.episode_id} does not match store {self.episode_id}"
            )
        state = self.replay()
        if state.episode is None:
            raise LiveStateError(f"active episode not found: {self.episode_id}")
        next_episode_after_plan(state.episode.status)
        context = state.contexts.get((plan.turn, plan.branch_id))
        if context is None:
            raise LiveStateError(
                f"turn context not found for turn {plan.turn} branch {plan.branch_id}"
            )
        if context.get("context_hash") != plan.context_hash:
            raise LiveStateError("plan context_hash does not match latest turn context")
        if plan.plan_id in state.plans:
            raise LiveStateError(f"plan already submitted: {plan.plan_id}")
        self._append_event(
            "PLAN_SUBMITTED",
            {
                "status": EpisodeStatus.PLAN_SUBMITTED.value,
                "plan": plan_to_payload(plan),
            },
        )
        return {
            "accepted": True,
            "plan_id": plan.plan_id,
            "status": "PLAN_SUBMITTED",
            "step_count": len(plan.steps),
        }

    def arm_step(self, plan_id: str, step_id: str) -> dict[str, Any]:
        state = self.replay()
        if state.episode is None:
            raise LiveStateError(f"active episode not found: {self.episode_id}")
        new_episode_status = next_episode_after_arm(state.episode.status)
        step = state.steps.get((plan_id, step_id))
        if step is None:
            raise LiveStateError(f"step not found: {plan_id}/{step_id}")
        new_step_status = next_step_after_arm(step.status)
        self._append_event(
            "STEP_ARMED",
            {
                "status": new_episode_status.value,
                "step_status": new_step_status.value,
                "plan_id": plan_id,
                "step_id": step_id,
            },
        )
        return {"armed": True, "status": "STEP_ARMED", "plan_id": plan_id, "step_id": step_id}

    def mark_step_executing(self, plan_id: str, step_id: str, *, request_id: str) -> None:
        step = self.get_step(plan_id, step_id)
        next_step_after_execute(step.status)
        self._append_event(
            "STEP_EXECUTING",
            {
                "status": EpisodeStatus.STEP_EXECUTING.value,
                "step_status": StepStatus.EXECUTING.value,
                "plan_id": plan_id,
                "step_id": step_id,
                "request_id": request_id,
            },
        )

    def mark_step_result(
        self,
        plan_id: str,
        step_id: str,
        *,
        request_id: str,
        verifier_status: str,
        pre_state_hash: str | None = None,
        post_state_hash: str | None = None,
        ledger_event_ids: list[str] | None = None,
    ) -> None:
        episode_status, step_status = next_after_verifier(verifier_status)
        self._append_event(
            "STEP_RESULT_RECORDED",
            {
                "episode_status": episode_status.value,
                "step_status": step_status.value,
                "plan_id": plan_id,
                "step_id": step_id,
                "request_id": request_id,
                "verifier_status": verifier_status,
                "pre_state_hash": pre_state_hash,
                "post_state_hash": post_state_hash,
                "ledger_event_ids": ledger_event_ids or [],
            },
        )

    def abort_episode(self, *, reason: str = "") -> dict[str, Any]:
        episode = self.get_episode()
        require_episode_active(episode.status)
        self._append_event("EPISODE_ABORTED", {"reason": reason})
        return {"episode_id": self.episode_id, "status": EpisodeStatus.EPISODE_ABORTED.value}

    def fail_episode(self, *, reason: str = "") -> dict[str, Any]:
        episode = self.get_episode()
        require_episode_active(episode.status)
        self._append_event("EPISODE_FAILED", {"reason": reason})
        return {"episode_id": self.episode_id, "status": EpisodeStatus.EPISODE_FAILED.value}

    def finish_episode(self) -> dict[str, Any]:
        state = self.replay()
        if state.episode is None:
            raise LiveStateError(f"active episode not found: {self.episode_id}")
        require_episode_active(state.episode.status)
        if state.episode.status is EpisodeStatus.NEED_RECOVERY_PLAN:
            raise LiveStateError("episode is in NEED_RECOVERY_PLAN")
        unverified = [
            step
            for step in state.steps.values()
            if step.status is StepStatus.EXECUTED
            or (step.status is StepStatus.EXECUTING)
        ]
        if unverified:
            first = unverified[0]
            raise LiveStateError(
                f"unverified executed step: {first.plan_id}/{first.step_id}"
            )
        unplanned = self._unplanned_live_strict_mutations()
        if unplanned:
            raise LiveStateError(
                f"unplanned L2+ mutation exists in live strict: {unplanned[0].get('tool')}"
            )
        self._append_event("EPISODE_FINISHED", {"status": EpisodeStatus.EPISODE_FINISHED.value})
        return {"episode_id": self.episode_id, "status": EpisodeStatus.EPISODE_FINISHED.value}

    def _unplanned_live_strict_mutations(self) -> list[dict[str, Any]]:
        live_events = self.episode_root / LIVE_EVENTS_LOGICAL_PATH
        if not live_events.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in live_events.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            level = str(row.get("level") or row.get("mutation_level") or "")
            if (
                row.get("allowed") is True
                and row.get("unplanned_mutation") is True
                and level in {"L2", "L3", "L4", "L5"}
            ):
                rows.append(row)
        return rows

    @staticmethod
    def step_from_record(record: LiveStepRecord) -> LivePlanStep:
        return LivePlanStep(
            step_id=record.step_id,
            tool=record.tool,
            args=record.args,
            allowed_mutation_level=MutationLevel(record.allowed_mutation_level),
            postconditions=tuple(record.postconditions),
            fragment_allowed=record.fragment_allowed,
        )

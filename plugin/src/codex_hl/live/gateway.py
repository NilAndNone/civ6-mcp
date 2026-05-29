from __future__ import annotations

import inspect
import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal

from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.plan_store import LivePlanStore, LiveStepRecord
from codex_hl.live.schemas import StepStatus, canonical_json
from codex_hl.live.state_machine import LiveStateError
from codex_hl.live.verifier import StubVerifier


ActionSource = Literal["mcp", "legacy_runner", "live_plan", "fragment", "recovery"]
ActionStatus = Literal["executed", "rejected", "failed", "verified", "inconclusive"]


class GatewayMode(str, Enum):
    LEGACY_COMPAT = "legacy_compat"
    SHADOW = "shadow"
    LIVE_STRICT = "live_strict"


@dataclass(frozen=True)
class ActionRequest:
    source: ActionSource
    tool_name: str
    args: dict[str, Any]
    mutation_level: MutationLevel
    episode_id: str | None = None
    turn: int | None = None
    plan_id: str | None = None
    step_id: str | None = None
    context_hash: str | None = None
    idempotency_key: str | None = None
    branch_id: str | None = None
    original_tool_name: str | None = None
    request_id: str = field(default_factory=lambda: f"act-{uuid.uuid4().hex}")


@dataclass(frozen=True)
class ActionResult:
    request_id: str
    allowed: bool
    status: ActionStatus
    result: Any = None
    error: str | None = None
    error_code: str | None = None
    pre_state_hash: str | None = None
    post_state_hash: str | None = None
    verifier_status: str | None = None
    ledger_event_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StrictValidation:
    allowed: bool
    error_code: str | None = None
    message: str | None = None
    step: LiveStepRecord | None = None


class ActionGateway:
    """Unified mutation gateway for legacy shadow and live strict execution.

    LEGACY_COMPAT and SHADOW preserve legacy execution while recording
    provenance. LIVE_STRICT requires a stored active plan and an armed step.
    """

    def __init__(
        self,
        *,
        mode: GatewayMode | str = GatewayMode.LEGACY_COMPAT,
        ledger: EpisodeLedger | None = None,
        verifier: StubVerifier | None = None,
        plan_store: LivePlanStore | None = None,
    ) -> None:
        self.mode = self._coerce_mode(mode)
        self.ledger = ledger
        self.verifier = verifier or StubVerifier()
        self.plan_store = plan_store

    @staticmethod
    def _coerce_mode(mode: GatewayMode | str) -> GatewayMode:
        if isinstance(mode, GatewayMode):
            return mode
        return GatewayMode(str(mode).strip().lower())

    def _is_unplanned_mutation(self, request: ActionRequest) -> bool:
        if not request.mutation_level.is_game_mutation_or_higher():
            return False
        return not (request.plan_id and request.step_id)

    def _strict_validation(self, request: ActionRequest) -> StrictValidation:
        if self.mode is not GatewayMode.LIVE_STRICT:
            return StrictValidation(allowed=True)
        if not request.mutation_level.is_game_mutation_or_higher():
            return StrictValidation(allowed=True)
        missing = [
            name
            for name, value in (
                ("episode_id", request.episode_id),
                ("plan_id", request.plan_id),
                ("step_id", request.step_id),
            )
            if not value
        ]
        if missing:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_PLAN_STEP_REQUIRED",
                message=(
                    "LIVE_STRICT requires active episode_id, plan_id, and step_id "
                    f"for L2+ actions; missing {', '.join(missing)}."
                ),
            )
        if self.plan_store is None:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_PLAN_STORE_REQUIRED",
                message="LIVE_STRICT requires a live plan store for L2+ actions.",
            )
        if self.plan_store.episode_id != request.episode_id:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_EPISODE_MISMATCH",
                message=(
                    "request episode_id does not match the active live plan store: "
                    f"{request.episode_id}"
                ),
            )
        try:
            episode = self.plan_store.get_episode()
        except LiveStateError as exc:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_EPISODE_NOT_ACTIVE",
                message=str(exc),
            )
        if episode.status.is_terminal():
            return StrictValidation(
                allowed=False,
                error_code="LIVE_EPISODE_NOT_ACTIVE",
                message=f"episode is terminal: {episode.status.value}",
            )
        try:
            plan = self.plan_store.get_plan(str(request.plan_id))
        except LiveStateError as exc:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_PLAN_NOT_FOUND",
                message=str(exc),
            )
        try:
            step = self.plan_store.get_step(str(request.plan_id), str(request.step_id))
        except LiveStateError as exc:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_STEP_NOT_FOUND",
                message=str(exc),
            )
        if step.status is not StepStatus.ARMED:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_STEP_NOT_ARMED",
                message=(
                    f"step {request.plan_id}/{request.step_id} must be ARMED, "
                    f"got {step.status.value}."
                ),
            )
        if plan.context_hash != request.context_hash:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_CONTEXT_STALE",
                message="request context_hash does not match the submitted plan context_hash.",
            )
        if step.tool != request.tool_name:
            return StrictValidation(
                allowed=False,
                error_code="LIVE_TOOL_MISMATCH",
                message=(
                    f"step tool {step.tool} does not match request tool {request.tool_name}."
                ),
            )
        if step.args_fingerprint != canonical_json(request.args):
            return StrictValidation(
                allowed=False,
                error_code="LIVE_ARGS_MISMATCH",
                message="request args do not match the armed step args.",
            )
        if _mutation_level_rank(request.mutation_level) > _mutation_level_rank(
            MutationLevel(step.allowed_mutation_level)
        ):
            return StrictValidation(
                allowed=False,
                error_code="LIVE_MUTATION_LEVEL_DENIED",
                message=(
                    f"request mutation level {request.mutation_level.value} exceeds "
                    f"armed step allowance {step.allowed_mutation_level}."
                ),
            )
        return StrictValidation(allowed=True, step=step)

    async def execute(
        self,
        request: ActionRequest,
        fn: Callable[[], Awaitable[Any] | Any],
        *,
        state_reader: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]] | None = None,
    ) -> ActionResult:
        event_ids: list[str] = []
        unplanned = self._is_unplanned_mutation(request)
        strict = self._strict_validation(request)
        if not strict.allowed:
            if self.ledger is not None:
                event_ids.append(
                    self.ledger.append_event(
                        event_type="ACTION_REJECTED",
                        request=request,
                        mode=self.mode.value,
                        allowed=False,
                        status="rejected",
                        unplanned_mutation=unplanned,
                        error=strict.message,
                        payload={"error_code": strict.error_code},
                    )
                )
            return ActionResult(
                request_id=request.request_id,
                allowed=False,
                status="rejected",
                error=strict.message,
                error_code=strict.error_code,
                ledger_event_ids=event_ids,
            )

        if (
            self.mode is GatewayMode.LIVE_STRICT
            and request.mutation_level.is_game_mutation_or_higher()
            and self.plan_store is not None
        ):
            try:
                self.plan_store.mark_step_executing(
                    str(request.plan_id),
                    str(request.step_id),
                    request_id=request.request_id,
                )
            except LiveStateError as exc:
                if self.ledger is not None:
                    event_ids.append(
                        self.ledger.append_event(
                            event_type="ACTION_REJECTED",
                            request=request,
                            mode=self.mode.value,
                            allowed=False,
                            status="rejected",
                            unplanned_mutation=unplanned,
                            error=str(exc),
                            payload={"error_code": "LIVE_STEP_NOT_ARMED"},
                        )
                    )
                return ActionResult(
                    request_id=request.request_id,
                    allowed=False,
                    status="rejected",
                    error=str(exc),
                    error_code="LIVE_STEP_NOT_ARMED",
                    ledger_event_ids=event_ids,
                )

        should_verify_with_state = (
            self.mode is GatewayMode.LIVE_STRICT
            and request.mutation_level.is_game_mutation_or_higher()
            and strict.step is not None
            and state_reader is not None
        )
        pre_state: dict[str, Any] | None = None
        post_state: dict[str, Any] | None = None
        pre_state_hash: str | None = None
        post_state_hash: str | None = None
        if should_verify_with_state:
            assert state_reader is not None
            pre_state = await _read_state(state_reader)
            pre_state_hash = _state_hash(pre_state)

        if self.ledger is not None:
            event_ids.append(
                self.ledger.append_event(
                    event_type="ACTION_STARTED",
                    request=request,
                    mode=self.mode.value,
                    allowed=True,
                    status="executing",
                    unplanned_mutation=unplanned,
                )
            )

        try:
            value = fn()
            result = await value if inspect.isawaitable(value) else value
        except Exception as exc:  # noqa: BLE001 - record then preserve legacy error flow.
            if self.ledger is not None:
                event_ids.append(
                    self.ledger.append_event(
                        event_type="ACTION_FAILED",
                        request=request,
                        mode=self.mode.value,
                        allowed=True,
                        status="failed",
                        unplanned_mutation=unplanned,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            if (
                self.mode is GatewayMode.LIVE_STRICT
                and request.mutation_level.is_game_mutation_or_higher()
                and self.plan_store is not None
            ):
                self.plan_store.mark_step_result(
                    str(request.plan_id),
                    str(request.step_id),
                    request_id=request.request_id,
                    verifier_status="FAIL",
                    ledger_event_ids=event_ids,
                )
            raise

        if should_verify_with_state:
            assert state_reader is not None
            post_state = await _read_state(state_reader)
            post_state_hash = _state_hash(post_state)

        verification = self.verifier.verify(
            request=request,
            result=result,
            pre_state_hash=pre_state_hash,
            post_state_hash=post_state_hash,
            pre_state=pre_state,
            post_state=post_state,
            postconditions=strict.step.postconditions if strict.step is not None else None,
        )
        verifier_status = verification.status.value
        if self.ledger is not None:
            event_ids.append(
                self.ledger.append_event(
                    event_type="ACTION_FINISHED",
                    request=request,
                    mode=self.mode.value,
                    allowed=True,
                    status="executed",
                    unplanned_mutation=unplanned,
                    result=result,
                    pre_state_hash=pre_state_hash,
                    post_state_hash=post_state_hash,
                    verifier_status=verifier_status,
                    payload={"verifier": verification},
                )
            )
        if (
            self.mode is GatewayMode.LIVE_STRICT
            and request.mutation_level.is_game_mutation_or_higher()
            and self.plan_store is not None
        ):
            self.plan_store.mark_step_result(
                str(request.plan_id),
                str(request.step_id),
                request_id=request.request_id,
                verifier_status=verifier_status,
                pre_state_hash=pre_state_hash,
                post_state_hash=post_state_hash,
                ledger_event_ids=event_ids,
            )

        return ActionResult(
            request_id=request.request_id,
            allowed=True,
            status="executed",
            result=result,
            pre_state_hash=pre_state_hash,
            post_state_hash=post_state_hash,
            verifier_status=verifier_status,
            ledger_event_ids=event_ids,
        )


def _mutation_level_rank(level: MutationLevel) -> int:
    return {
        MutationLevel.L0_READ: 0,
        MutationLevel.L1_RUNTIME_SIDE_EFFECT: 1,
        MutationLevel.L2_LOW_GAME_MUTATION: 2,
        MutationLevel.L3_HIGH_GAME_MUTATION: 3,
        MutationLevel.L4_BOUNDARY_RECOVERY: 4,
        MutationLevel.L5_UNSAFE_ESCAPE: 5,
    }[level]


async def _read_state(
    state_reader: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]],
) -> dict[str, Any]:
    value = state_reader()
    state = await value if inspect.isawaitable(value) else value
    return state if isinstance(state, dict) else {"value": state}


def _state_hash(state: dict[str, Any] | None) -> str | None:
    if state is None:
        return None
    encoded = canonical_json(state).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

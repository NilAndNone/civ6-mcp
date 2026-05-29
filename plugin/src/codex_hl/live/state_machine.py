from __future__ import annotations

from codex_hl.live.schemas import EpisodeStatus, StepStatus


class LiveStateError(RuntimeError):
    """Raised when a live episode lifecycle transition is invalid."""


def require_episode_active(status: EpisodeStatus) -> None:
    if status.is_terminal():
        raise LiveStateError(f"episode is terminal: {status.value}")


def next_episode_after_context(status: EpisodeStatus) -> EpisodeStatus:
    require_episode_active(status)
    return EpisodeStatus.TURN_CONTEXT_READY


def next_episode_after_plan(status: EpisodeStatus) -> EpisodeStatus:
    require_episode_active(status)
    if status is EpisodeStatus.NEED_RECOVERY_PLAN:
        return EpisodeStatus.PLAN_SUBMITTED
    return EpisodeStatus.PLAN_SUBMITTED


def next_episode_after_arm(status: EpisodeStatus) -> EpisodeStatus:
    require_episode_active(status)
    return EpisodeStatus.STEP_ARMED


def next_step_after_arm(status: StepStatus) -> StepStatus:
    if status is not StepStatus.SUBMITTED:
        raise LiveStateError(f"step must be SUBMITTED before arm, got {status.value}")
    return StepStatus.ARMED


def next_step_after_execute(status: StepStatus) -> StepStatus:
    if status is not StepStatus.ARMED:
        raise LiveStateError(f"step must be ARMED before execute, got {status.value}")
    return StepStatus.EXECUTING


def next_after_verifier(verifier_status: str) -> tuple[EpisodeStatus, StepStatus]:
    normalized = verifier_status.strip().upper()
    if normalized == "PASS":
        return EpisodeStatus.STEP_VERIFIED, StepStatus.VERIFIED
    if normalized == "FAIL":
        return EpisodeStatus.NEED_RECOVERY_PLAN, StepStatus.FAILED
    return EpisodeStatus.STEP_EXECUTED, StepStatus.EXECUTED

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_hl.live.gateway import ActionGateway, GatewayMode
from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.plan_store import LivePlanStore


GATEWAY_MODE_ENV = "CODEX_HL_CIV6_LIVE_GATEWAY_MODE"
LEGACY_GATEWAY_MODE_ENV = "CODEX_HL_CIV6_GATEWAY_MODE"
LEGACY_RUNNER_GATEWAY_MODE_ENV = "CODEX_HL_CIV6_LEGACY_RUNNER_GATEWAY_MODE"
LEDGER_ROOT_ENV = "CODEX_HL_CIV6_LIVE_LEDGER_ROOT"
LIVE_EPISODE_ID_ENV = "CODEX_HL_CIV6_LIVE_EPISODE_ID"
LIVE_PLAN_ID_ENV = "CODEX_HL_CIV6_LIVE_PLAN_ID"
LIVE_STEP_ID_ENV = "CODEX_HL_CIV6_LIVE_STEP_ID"
LIVE_CONTEXT_HASH_ENV = "CODEX_HL_CIV6_LIVE_CONTEXT_HASH"
LIVE_BRANCH_ID_ENV = "CODEX_HL_CIV6_LIVE_BRANCH_ID"


@dataclass(frozen=True)
class LiveActionContext:
    episode_id: str | None = None
    turn: int | None = None
    plan_id: str | None = None
    step_id: str | None = None
    context_hash: str | None = None
    branch_id: str | None = None


def gateway_mode_from_env(
    default: GatewayMode = GatewayMode.LEGACY_COMPAT,
) -> GatewayMode:
    raw = os.environ.get(GATEWAY_MODE_ENV) or os.environ.get(LEGACY_GATEWAY_MODE_ENV)
    return _coerce_gateway_mode(raw, default)


def _coerce_gateway_mode(raw: str | None, default: GatewayMode) -> GatewayMode:
    if not raw:
        return default
    try:
        return GatewayMode(raw.strip().lower())
    except ValueError:
        return default


def legacy_runner_gateway_mode_from_env(
    default: GatewayMode = GatewayMode.SHADOW,
) -> GatewayMode:
    """Return the observation-runner gateway mode.

    The legacy observation runner cannot provide Phase 2 plan/step bindings, so
    it must not inherit the MCP/global live strict switch by accident.
    """

    mode = _coerce_gateway_mode(os.environ.get(LEGACY_RUNNER_GATEWAY_MODE_ENV), default)
    if mode is GatewayMode.LIVE_STRICT:
        return default
    return mode


def live_context_from_env(*, turn: int | None = None) -> LiveActionContext:
    return LiveActionContext(
        episode_id=os.environ.get(LIVE_EPISODE_ID_ENV),
        turn=turn,
        plan_id=os.environ.get(LIVE_PLAN_ID_ENV),
        step_id=os.environ.get(LIVE_STEP_ID_ENV),
        context_hash=os.environ.get(LIVE_CONTEXT_HASH_ENV),
        branch_id=os.environ.get(LIVE_BRANCH_ID_ENV),
    )


def action_gateway_for_episode(
    episode_root: Path,
    episode_id: str,
    *,
    store: Any | None = None,
    branch_id: str | None = None,
    mode: GatewayMode | None = None,
) -> ActionGateway:
    ledger = EpisodeLedger.for_episode_root(
        episode_root,
        episode_id,
        store=store,
        branch_id=branch_id,
    )
    return ActionGateway(
        mode=mode or legacy_runner_gateway_mode_from_env(),
        ledger=ledger,
    )


def default_mcp_episode_root() -> Path:
    configured = os.environ.get(LEDGER_ROOT_ENV)
    if configured:
        return Path(configured)
    return workspace_root() / "episodes" / "_live_shadow_mcp"


def workspace_root() -> Path:
    workspace = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
    return workspace


def live_episode_root(episode_id: str) -> Path:
    configured = os.environ.get(LEDGER_ROOT_ENV)
    if configured:
        root = Path(configured).resolve()
        return root if root.name == episode_id else root / episode_id
    return workspace_root() / "episodes" / episode_id


def live_plan_store_for_episode(episode_id: str) -> LivePlanStore:
    return LivePlanStore.for_episode_root(live_episode_root(episode_id), episode_id)


def action_gateway_for_mcp(
    *,
    episode_id: str | None = None,
    mode: GatewayMode | None = None,
) -> ActionGateway:
    ledger_episode_id = episode_id or "_live_shadow_mcp"
    episode_root = (
        live_episode_root(ledger_episode_id)
        if episode_id
        else default_mcp_episode_root()
    )
    ledger = EpisodeLedger.for_episode_root(
        episode_root,
        ledger_episode_id,
    )
    plan_store = live_plan_store_for_episode(episode_id) if episode_id else None
    return ActionGateway(
        mode=mode or gateway_mode_from_env(),
        ledger=ledger,
        plan_store=plan_store,
    )

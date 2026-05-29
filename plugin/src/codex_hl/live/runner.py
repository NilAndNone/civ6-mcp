"""CLI entry point for the Phase 3 live runner path.

The real live episode is driven by MCP lifecycle tools and JSON plan gating.
This CLI exists so the orchestrator can route ``--runner live`` away from the
legacy rules runner and into live episode artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from codex_hl.evidence.store import EpisodeStore
from codex_hl.live.context import live_episode_root
from codex_hl.live.ledger import now_iso
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.state_machine import LiveStateError


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def default_episode_id(save_name: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in save_name.lower()).strip("_")
    safe = safe or "save"
    return f"live_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def start_live_runner_episode(args: argparse.Namespace) -> dict[str, Any]:
    episode_id = args.episode_id or default_episode_id(args.save_name)
    episode_root = live_episode_root(episode_id)
    store = EpisodeStore(episode_root, episode_id)
    store.put_episode_header(
        {
            "episode_id": episode_id,
            "workflow": "live-json-plan",
            "save_name": args.save_name,
            "requested_turns": args.turns,
            "strategy_profile": args.strategy_profile,
            "runner_kind": "live",
            "candidate_package": str(args.candidate_package) if args.candidate_package else None,
            "created_at": now_iso(),
            "note": (
                "Phase 3 live runner artifact. Actual game actions must be "
                "driven through MCP start_live_episode/get_live_turn_context/"
                "submit_turn_plan/arm_live_step and gated mutating tools."
            ),
        },
        workflow="live-json-plan",
        save_name=args.save_name,
        requested_turns=args.turns,
        strategy_profile=args.strategy_profile,
    )
    store.close()
    plan_store = LivePlanStore.for_episode_root(episode_root, episode_id)
    try:
        status = plan_store.start_episode(
            save_name=args.save_name,
            target_turns=args.turns,
            mode="live_strict",
            runner="live-json-plan",
        ).status.value
    except LiveStateError:
        status = plan_store.get_episode().status.value
    return {
        "ok": True,
        "episode_id": episode_id,
        "runner_kind": "live",
        "status": status,
        "actual_turns": 0,
        "requires_mcp_runtime": True,
        "episode_root": str(episode_root),
        "ledger_db": str(episode_root / "episode.db"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-name", default="test 1")
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--episode-id")
    parser.add_argument("--strategy-profile", default="baseline_static")
    parser.add_argument("--candidate-package", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = start_live_runner_episode(args)
    except (OSError, LiveStateError) as exc:
        print(json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json_dumps(payload))


if __name__ == "__main__":
    main()

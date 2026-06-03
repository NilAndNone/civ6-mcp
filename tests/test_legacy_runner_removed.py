from __future__ import annotations

import pytest

from codex_hl.runs import orchestrator


def test_removed_runner_hard_fails_with_live_hint() -> None:
    args = orchestrator.parse_args(["--execute", "--runner", "legacy-baseline"])
    with pytest.raises(orchestrator.EvolutionError, match='runner "legacy-baseline".*removed.*observe-live'):
        orchestrator.validate_args(args)


def test_parse_still_recognizes_removed_runner_for_clear_error() -> None:
    args = orchestrator.parse_args(["--execute", "--runner", "legacy-baseline"])
    assert args.runner == "legacy-baseline"
    with pytest.raises(orchestrator.EvolutionError, match="removed"):
        orchestrator.validate_args(args)

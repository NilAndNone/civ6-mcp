from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from codex_hl.runs import orchestrator


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def make_asset_root(root: Path) -> Path:
    content = root / "assets" / "playbook.md"
    content.parent.mkdir(parents=True, exist_ok=True)
    content.write_text("# Asset\n\nRules.\n", encoding="utf-8")
    digest = orchestrator.strategy_registry.sha256_file(content)
    write_json(
        root / "catalog.json",
        {
            "schema_version": 1,
            "assets": [
                {
                    "asset_id": "strategy.playbook.observation",
                    "asset_type": "playbook",
                    "version": "1.0.0",
                    "content_path": "assets/playbook.md",
                    "content_sha256": digest,
                    "source_refs": ["tests"],
                    "applicability": ["tests"],
                    "risk_level": "high",
                    "rollback_path": "assets/playbook.md",
                    "capability_dimensions": ["planning"],
                    "status": "active",
                }
            ],
        },
    )
    write_jsonl(
        root / "change_ledger.jsonl",
        [
            {
                "ledger_id": "ledger-test",
                "event_type": "initial_migration",
                "recorded_at": "2026-05-29T00:00:00+08:00",
                "asset_id": "strategy.playbook.observation",
                "version": "1.0.0",
                "source_failure_ids": [],
                "source_episode_ids": [],
                "source_refs": ["tests"],
                "metric_refs": [],
                "human_or_auto_judgments": ["tests"],
                "notes": "test",
            }
        ],
    )
    return root


def args_for(tmp_path: Path, *, runner_kind: str | None, turns: int = 20) -> argparse.Namespace:
    return argparse.Namespace(
        workspace=tmp_path,
        asset_root=make_asset_root(tmp_path / "asset_root"),
        pool_root=None,
        output_dir=tmp_path / "evolution_run",
        run_id="evo_test",
        save_name="test 1",
        turns=turns,
        strategy_profile="baseline_static",
        runner=runner_kind,
        cycles=1,
        episodes_per_cycle=1,
        target_completed_episodes=1,
        episode_retries=0,
        extra_attempt_slots=0,
        baseline_episode=None,
        candidate_package=None,
        execute=True,
        allow_auto_confirmation=False,
        auto_iterate_strategy=False,
        auto_confirm_min_confidence="high",
        auto_confirm_categories=sorted(orchestrator.DEFAULT_AUTO_CONFIRM_CATEGORIES),
        candidate_runtime_applied=False,
        stop_on_checkpoint_alert=False,
        checkpoint_only=False,
        checkpoint_episodes=[],
        checkpoint_manifest=None,
        resume_manifest=None,
        preflight=False,
        require_preflight_ready=False,
        firetuner_port=4318,
        allow_merge=False,
    )


def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
    module = command[2]
    started = orchestrator.now_iso()
    if module == "codex_hl.live.driver":
        episode_id = command[command.index("--episode-id") + 1]
        stdout = json.dumps(
            {
                "episode_id": episode_id,
                "runner_kind": "live",
                "requires_mcp_runtime": False,
            }
        )
    elif module == "codex_hl.review.failure_labeling":
        episode_id = command[command.index("--episode-id") + 1]
        stdout = json.dumps({"episode_id": episode_id, "candidates": 0})
    else:
        raise AssertionError(command)
    return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())


def test_execute_without_runner_fails_clearly(tmp_path) -> None:
    with pytest.raises(orchestrator.EvolutionError, match="--execute requires --runner"):
        orchestrator.run_evolution(args_for(tmp_path, runner_kind=None), runner=fake_runner)


def test_execute_t3_without_runner_reaches_runner_gate(tmp_path) -> None:
    with pytest.raises(orchestrator.EvolutionError, match="--execute requires --runner"):
        orchestrator.run_evolution(args_for(tmp_path, runner_kind=None, turns=3), runner=fake_runner)


def test_removed_runner_hard_fails_before_launch(tmp_path) -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        calls.append(command)
        return fake_runner(command, cwd, env)

    with pytest.raises(orchestrator.EvolutionError, match='runner "legacy-baseline".*removed.*--runner live'):
        orchestrator.run_evolution(
            args_for(tmp_path, runner_kind="legacy-baseline"),
            runner=runner,
        )

    assert calls == []


def test_live_runner_uses_live_episode_path_not_old_rules_runner(tmp_path) -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        calls.append(command)
        return fake_runner(command, cwd, env)

    result = orchestrator.run_evolution(args_for(tmp_path, runner_kind="live", turns=3), runner=runner)

    assert result["status"] == "completed"
    assert calls[0][2] == "codex_hl.live.driver"
    assert "--turn-budget" in calls[0]
    assert calls[0][calls[0].index("--turn-budget") + 1] == "3"
    assert "codex_hl.live.driver" in [command[2] for command in calls]

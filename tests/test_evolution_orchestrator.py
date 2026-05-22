import argparse
import json
from pathlib import Path

import pytest

from codex_hl.evolution import orchestrator


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def make_asset_root(root: Path) -> Path:
    body = "# Asset\n\nRules.\n"
    content = root / "assets" / "playbook.md"
    content.parent.mkdir(parents=True, exist_ok=True)
    content.write_text(body, encoding="utf-8")
    digest = orchestrator.phase3_assets.sha256_file(content)
    write_json(
        root / "catalog.json",
        {
            "schema_version": 1,
            "assets": [
                {
                    "asset_id": "playbook.phase1_observation",
                    "asset_type": "playbook",
                    "version": "1.0.0",
                    "content_path": "assets/playbook.md",
                    "content_sha256": digest,
                    "source_refs": ["tests"],
                    "applicability": ["tests"],
                    "risk_level": "high",
                    "rollback_path": "assets/playbook.md",
                    "capability_dimensions": ["planning", "execution", "verification"],
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
                "recorded_at": "2026-05-21T00:00:00+08:00",
                "asset_id": "playbook.phase1_observation",
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


def make_t50_episode(
    workspace: Path,
    episode_id: str,
    *,
    cities: int,
    techs: int,
    civics: int,
    turns: int = 50,
) -> None:
    final_turn = turns + 1
    episode = workspace / "episodes" / episode_id
    write_json(
        episode / "derived" / "report_pack.json",
        {
            "episode_id": episode_id,
            "run": {"start_turn": 1, "final_turn": final_turn, "actual_turns": turns},
            "evidence_status": {
                "tool_mcp_raw_records": {"status": "PASS"},
                "turn_state_snapshots": {"status": "PASS"},
                "decision_records": {"status": "PASS"},
                "save_links": {"status": "PASS"},
            },
        },
    )
    write_json(
        episode
        / "raw"
        / "civ6_states"
        / f"state-{final_turn:04d}-T{final_turn:04d}-t{turns}_final.json",
        {
            "snapshot_id": "state-final",
            "episode_id": episode_id,
            "turn": final_turn,
            "overview": {
                "num_cities": cities,
                "science_yield": float(techs),
                "culture_yield": float(civics),
            },
            "research_civic": {
                "completed_tech_count": techs,
                "completed_civic_count": civics,
                "current_research": "Currency",
                "current_civic": "State Workforce",
            },
        },
    )


def base_args(tmp_path: Path, *, execute: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        workspace=tmp_path,
        asset_root=make_asset_root(tmp_path / "asset_root"),
        pool_root=None,
        output_dir=tmp_path / "evolution_run",
        run_id="evo_test",
        save_name="test 1",
        turns=50,
        strategy_profile="baseline_static",
        cycles=1,
        episodes_per_cycle=3,
        target_completed_episodes=None,
        episode_retries=0,
        extra_attempt_slots=0,
        baseline_episode=None,
        candidate_package=None,
        execute=execute,
        allow_auto_confirmation=False,
        auto_iterate_strategy=False,
        auto_confirm_min_confidence="high",
        auto_confirm_categories=sorted(orchestrator.DEFAULT_AUTO_CONFIRM_CATEGORIES),
        candidate_runtime_applied=False,
        allow_merge=False,
    )


def test_plan_mode_writes_manifest_without_running_commands(tmp_path):
    args = base_args(tmp_path, execute=False)

    result = orchestrator.run_evolution(args, runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")))

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "planned"
    assert len(result["planned_episodes"]) == 3
    assert manifest["status"] == "planned"
    assert not (tmp_path / "evolution_run" / "commands.jsonl").exists()


def test_plan_mode_supports_t20_episode_ids(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.turns = 20

    result = orchestrator.run_evolution(args, runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")))

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["planned_episodes"] == [
        "evo_test_c01_e01_t20",
        "evo_test_c01_e02_t20",
        "evo_test_c01_e03_t20",
    ]
    assert manifest["turns"] == 20
    assert manifest["strategy_profile"] == "baseline_static"


def test_plan_mode_uses_target_completed_episodes(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.target_completed_episodes = 5

    result = orchestrator.run_evolution(args, runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")))

    assert len(result["planned_episodes"]) == 5
    assert result["planned_episodes"][-1] == "evo_test_c02_e02_t50"


def test_parse_stdout_json_accepts_pretty_json():
    payload = orchestrator.parse_stdout_json(
        '{\n  "ok": true,\n  "candidates": 2\n}\n',
        step="phase4_candidates",
    )

    assert payload == {"ok": True, "candidates": 2}


def test_build_t50_validation_report_records_strategy_runtime_boundary(tmp_path):
    make_t50_episode(tmp_path, "baseline", cities=1, techs=2, civics=1)
    make_t50_episode(tmp_path, "candidate_a", cities=2, techs=3, civics=1)
    make_t50_episode(tmp_path, "candidate_b", cities=1, techs=4, civics=2)

    report = orchestrator.build_t50_validation_report(
        workspace=tmp_path,
        output_path=tmp_path / "report.json",
        baseline_episode="baseline",
        candidate_episodes=["candidate_a", "candidate_b"],
    )

    assert report["strategy_runtime_coupled"] is False
    assert report["scenario_results"][0]["status"] == "pass"
    assert report["scenario_results"][0]["t50_delta"]["num_cities"] == 1
    assert report["scenario_results"][1]["t50_delta"]["completed_tech_count"] == 2


def test_build_t20_validation_report_uses_t20_gate(tmp_path):
    make_t50_episode(tmp_path, "baseline", cities=1, techs=2, civics=1, turns=20)
    make_t50_episode(tmp_path, "candidate_a", cities=2, techs=3, civics=1, turns=20)

    report = orchestrator.build_t50_validation_report(
        workspace=tmp_path,
        output_path=tmp_path / "report.json",
        baseline_episode="baseline",
        candidate_episodes=["candidate_a"],
        target_turns=20,
    )

    assert report["report_kind"] == "multi_t20_validation_report"
    assert report["target_turns"] == 20
    assert report["scenario_results"][0]["status"] == "pass"
    assert report["scenario_results"][0]["t20_delta"]["num_cities"] == 1


def test_execute_runs_t50_phase2_and_optional_downstream(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.allow_auto_confirmation = True
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        calls.append(command)
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.phase1.observer":
            episode_id = command[command.index("--episode-id") + 1]
            turns = int(command[command.index("--turns") + 1])
            assert command[command.index("--strategy-profile") + 1] == args.strategy_profile
            index = int(episode_id.split("_e")[-1].split("_")[0])
            make_t50_episode(cwd, episode_id, cities=index, techs=index + 1, civics=index, turns=turns)
            stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
        elif module == "codex_hl.phase2.labeler" and "--apply-confirmation" not in command:
            episode_id = command[command.index("--episode-id") + 1]
            phase2 = cwd / "episodes" / episode_id / "phase2"
            write_jsonl(
                phase2 / "candidates.jsonl",
                [
                    {
                        "candidate_id": f"cand_{episode_id}",
                        "human_status": "pending",
                        "capability_category": "planning",
                        "confidence": "high",
                    }
                ],
            )
            stdout = json.dumps({"episode_id": episode_id, "phase2_dir": str(phase2), "candidates": 1})
        elif module == "codex_hl.phase2.labeler":
            episode_id = command[command.index("--episode-id") + 1]
            phase2 = cwd / "episodes" / episode_id / "phase2"
            write_jsonl(phase2 / "failures.jsonl", [{"failure_id": f"fail_{episode_id}"}])
            write_jsonl(phase2 / "regression_seeds.jsonl", [{"seed_id": f"seed_{episode_id}"}])
            stdout = json.dumps({"episode_id": episode_id, "failures": 1, "regression_seeds": 1})
        elif module == "codex_hl.phase4.improvements":
            episode_id = command[command.index("--episode-id") + 1]
            package = cwd / "episodes" / episode_id / "phase4" / "candidate_packages" / "impr_test" / "candidate.json"
            write_json(package, {"candidate_id": "impr_test"})
            write_jsonl(cwd / "episodes" / episode_id / "phase4" / "candidate_improvements.jsonl", [{"candidate_id": "impr_test"}])
            stdout = json.dumps({"episode_id": episode_id, "candidates": 1})
        elif module == "codex_hl.phase5.scenarios":
            episode_id = command[command.index("--episode-id") + 1]
            pool = cwd / "validation" / "regression_scenarios"
            write_jsonl(pool / "regression_scenarios.jsonl", [{"scenario_id": episode_id}])
            stdout = json.dumps({"episode_id": episode_id, "scenario_count": 1})
        else:
            raise AssertionError(command)
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    result = orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert len(result["episodes"]) == 3
    assert len(manifest["auto_confirmations"]) == 3
    assert manifest["validation_summary"]["scenario_count"] == 2
    assert Path(result["validation_report"]).exists()
    assert any(call[2] == "codex_hl.phase4.improvements" for call in calls)
    assert any(call[2] == "codex_hl.phase5.scenarios" for call in calls)


def test_allow_merge_requires_candidate_runtime_applied(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.allow_merge = True
    args.candidate_package = tmp_path / "candidate.json"

    with pytest.raises(orchestrator.EvolutionError, match="candidate-runtime-applied"):
        orchestrator.run_evolution(args)

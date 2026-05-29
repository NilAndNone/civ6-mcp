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
    body = "# Asset\n\nRules.\n"
    content = root / "assets" / "playbook.md"
    content.parent.mkdir(parents=True, exist_ok=True)
    content.write_text(body, encoding="utf-8")
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


def make_t50_episode(
    workspace: Path,
    episode_id: str,
    *,
    cities: int,
    techs: int,
    civics: int,
    era_score: int = 10,
    golden_threshold: int = 19,
    gold: int = 100,
    score: int = 50,
    governors: list[dict] | None = None,
    target_events: list[dict] | None = None,
    strategic_resources: list[dict] | None = None,
    unimproved_strategic_resources: list[dict] | None = None,
    tradable_players: list[dict] | None = None,
    war_targets: list[dict] | None = None,
    opportunities: list[str] | None = None,
    turns: int = 50,
    current_age: str | None = None,
    current_era: str | None = None,
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
                "era_score": era_score,
                "era_golden_threshold": golden_threshold,
                "gold": gold,
                "score": score,
            },
            "research_civic": {
                "completed_tech_count": techs,
                "completed_civic_count": civics,
                "current_research": "Currency",
                "current_civic": "State Workforce",
            },
            "empire": {
                "players": [
                    {
                        "pid": 0,
                        "era": current_era or "ERA_ANCIENT",
                        "age": current_age or "NORMAL",
                    }
                ]
            },
            "t50_strategy_audit": {
                "turn": final_turn,
                "current_era": current_era or "ERA_ANCIENT",
                "current_age": current_age or "NORMAL",
                "era_score": era_score,
                "golden_threshold": golden_threshold,
                "era_score_gap": max(0, golden_threshold - era_score),
                "gold": gold,
                "governors": governors if governors is not None else [],
                "strategic_resources": strategic_resources if strategic_resources is not None else [],
                "unimproved_strategic_resources": (
                    unimproved_strategic_resources
                    if unimproved_strategic_resources is not None
                    else []
                ),
                "tradable_players": tradable_players if tradable_players is not None else [],
                "war_targets": war_targets if war_targets is not None else [],
                "opportunities": opportunities if opportunities is not None else [],
                "golden_age_target_events": target_events if target_events is not None else [],
                "active_golden_age_target_events": [
                    event for event in (target_events or []) if event.get("active") is True
                ],
            },
        },
    )


def make_legacy_t50_episode_without_strategy_audit(
    workspace: Path,
    episode_id: str,
    *,
    final_era_score: int,
    final_gold: int,
) -> None:
    episode = workspace / "episodes" / episode_id
    write_json(
        episode / "derived" / "report_pack.json",
        {
            "episode_id": episode_id,
            "run": {"start_turn": 1, "final_turn": 51, "actual_turns": 50},
            "evidence_status": {
                "tool_mcp_raw_records": {"status": "PASS"},
                "turn_state_snapshots": {"status": "PASS"},
                "decision_records": {"status": "PASS"},
                "save_links": {"status": "PASS"},
            },
        },
    )
    for turn, era_score, gold in [(49, 8, 95), (50, 9, 160), (51, final_era_score, final_gold)]:
        write_json(
            episode / "raw" / "civ6_states" / f"state-{turn:04d}-T{turn:04d}.json",
            {
                "snapshot_id": f"state-{turn}",
                "episode_id": episode_id,
                "turn": turn,
                "overview": {
                    "num_cities": 3,
                    "science_yield": 10.0,
                    "culture_yield": 10.0,
                    "era_score": era_score,
                    "era_golden_threshold": 19,
                    "gold": gold,
                    "score": 87,
                },
                "research_civic": {
                    "completed_tech_count": 9,
                    "completed_civic_count": 9,
                    "current_research": "Iron Working",
                    "current_civic": "Games and Recreation",
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
        runner="legacy-baseline",
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


def test_plan_mode_with_resume_manifest_lists_only_remaining_episodes(tmp_path):
    source_manifest = tmp_path / "resume_manifest.json"
    write_json(
        source_manifest,
        {
            "run_id": "evo_test",
            "created_at": "2026-05-25T00:00:00+08:00",
            "status": "interrupted",
            "strategy_profile": "golden_age_push",
            "episodes": [
                {"episode_id": "evo_test_c01_e01_t50", "slot": 1},
                {"episode_id": "evo_test_c01_e02_t50", "slot": 2},
            ],
        },
    )
    args = base_args(tmp_path, execute=False)
    args.resume_manifest = source_manifest
    args.episodes_per_cycle = 2
    args.target_completed_episodes = 4

    result = orchestrator.run_evolution(
        args,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")),
    )

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["planned_episodes"] == [
        "evo_test_c02_e01_t50",
        "evo_test_c02_e02_t50",
    ]
    assert result["resumed_episode_count"] == 2
    assert result["remaining_episode_count"] == 2
    assert manifest["planned_episodes"] == result["planned_episodes"]
    assert manifest["episodes"][0]["episode_id"] == "evo_test_c01_e01_t50"


def test_plan_mode_with_resume_manifest_skips_failed_slots(tmp_path):
    source_manifest = tmp_path / "resume_manifest.json"
    write_json(
        source_manifest,
        {
            "run_id": "evo_test",
            "created_at": "2026-05-25T00:00:00+08:00",
            "status": "interrupted",
            "strategy_profile": "golden_age_push",
            "episodes": [
                {"episode_id": "evo_test_c01_e01_t50", "slot": 1},
                {"episode_id": "evo_test_c01_e02_t50", "slot": 2},
            ],
            "episode_failures": [
                {
                    "episode_id": "evo_test_c02_e01_t50",
                    "slot": 3,
                    "attempt": 0,
                    "error": "observation failed",
                }
            ],
        },
    )
    args = base_args(tmp_path, execute=False)
    args.resume_manifest = source_manifest
    args.episodes_per_cycle = 2
    args.target_completed_episodes = 4

    result = orchestrator.run_evolution(
        args,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")),
    )

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["planned_episodes"] == [
        "evo_test_c02_e02_t50",
        "evo_test_c03_e01_t50",
    ]
    assert manifest["resumed_episode_count"] == 2
    assert manifest["resumed_failure_count"] == 1
    assert manifest["t50_observation_attempt_count"] == 3


def test_plan_mode_rejects_resume_when_t50_attempt_budget_cannot_finish_target(tmp_path):
    source_manifest = tmp_path / "resume_manifest.json"
    failures = [
        {
            "episode_id": f"evo_test_c{index + 1:02d}_e01_t50",
            "slot": index + 1,
            "attempt": 0,
            "error": "observation failed",
        }
        for index in range(99)
    ]
    write_json(
        source_manifest,
        {
            "run_id": "evo_test",
            "created_at": "2026-05-25T00:00:00+08:00",
            "status": "interrupted",
            "strategy_profile": "golden_age_push",
            "episodes": [],
            "episode_failures": failures,
        },
    )
    args = base_args(tmp_path, execute=False)
    args.resume_manifest = source_manifest
    args.episodes_per_cycle = 10
    args.target_completed_episodes = 3

    with pytest.raises(orchestrator.EvolutionError, match="Only 1 T50 observation"):
        orchestrator.run_evolution(
            args,
            runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")),
        )

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "attempt_budget_limited"
    assert manifest["t50_observation_attempt_count"] == 99
    assert manifest["remaining_t50_observation_attempt_budget"] == 1
    assert manifest["planned_episodes"] == ["evo_test_c10_e10_t50"]


def test_t50_plan_defaults_to_ten_episode_checkpoints(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.episodes_per_cycle = None

    result = orchestrator.run_evolution(args, runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")))

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert len(result["planned_episodes"]) == 10
    assert result["planned_episodes"][-1] == "evo_test_c01_e10_t50"
    assert manifest["checkpoint_episode_interval"] == 10
    assert manifest["max_t50_episodes"] == 100


def test_preflight_records_connector_readiness_in_plan_manifest(tmp_path):
    save_dir = tmp_path / "saves"
    save_dir.mkdir()
    (save_dir / "test 1.Civ6Save").write_text("save", encoding="utf-8")
    args = base_args(tmp_path, execute=False)
    args.preflight = True

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        assert command[2] == "codex_hl.diagnostics.connector"
        assert "--port" in command
        started = orchestrator.now_iso()
        stdout = json.dumps(
            {
                "plugin_root": str(cwd / "plugin"),
                "save_dir": str(save_dir),
                "game_running": True,
                "firetuner_port": 4318,
                "firetuner_reachable": True,
            }
        )
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    result = orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "planned"
    assert result["preflight"]["ready"] is True
    assert manifest["preflight"]["save_exists"] is True
    assert manifest["preflight"]["blocking_reasons"] == []


def test_require_preflight_ready_stops_before_scheduling_when_connector_is_down(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.require_preflight_ready = True

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        assert command[2] == "codex_hl.diagnostics.connector"
        started = orchestrator.now_iso()
        stdout = json.dumps(
            {
                "plugin_root": str(cwd / "plugin"),
                "save_dir": str(tmp_path / "missing_saves"),
                "game_running": False,
                "firetuner_port": 4318,
                "firetuner_reachable": False,
            }
        )
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    with pytest.raises(orchestrator.EvolutionError, match="connector preflight not ready"):
        orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "preflight_failed"
    assert manifest["preflight_requested"] is True
    assert set(manifest["preflight"]["blocking_reasons"]) == {
        "save_not_found",
        "game_not_running",
        "firetuner_unreachable",
    }


def test_execute_with_failed_preflight_stops_before_observation(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.preflight = True
    calls: list[str] = []

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        calls.append(command[2])
        assert command[2] == "codex_hl.diagnostics.connector"
        started = orchestrator.now_iso()
        stdout = json.dumps(
            {
                "plugin_root": str(cwd / "plugin"),
                "save_dir": str(tmp_path / "missing_saves"),
                "game_running": False,
                "firetuner_port": 4318,
                "firetuner_reachable": False,
            }
        )
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    with pytest.raises(orchestrator.EvolutionError, match="connector preflight not ready"):
        orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert calls == ["codex_hl.diagnostics.connector"]
    assert manifest["status"] == "preflight_failed"
    assert manifest["execute"] is True


def test_t20_plan_keeps_short_exploration_default_cycle_size(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.turns = 20
    args.episodes_per_cycle = None

    result = orchestrator.run_evolution(args, runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")))

    assert len(result["planned_episodes"]) == 3
    assert result["planned_episodes"][-1] == "evo_test_c01_e03_t20"


def test_t50_plan_caps_total_episodes_at_one_hundred(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.episodes_per_cycle = 10
    args.target_completed_episodes = 101

    with pytest.raises(orchestrator.EvolutionError, match="capped at 100"):
        orchestrator.run_evolution(args, runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")))


def test_t50_execute_caps_total_observation_attempts_including_retries(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 10
    args.target_completed_episodes = 100
    args.episode_retries = 1
    args.extra_attempt_slots = 200
    observation_calls: list[str] = []

    def failing_runner(
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None,
    ) -> orchestrator.CommandResult:
        assert command[2] == "codex_hl.evidence.observation"
        observation_calls.append(command[command.index("--episode-id") + 1])
        started = orchestrator.now_iso()
        return orchestrator.CommandResult(command, 1, "", "observation failed", started, orchestrator.now_iso())

    with pytest.raises(orchestrator.EvolutionError, match="100-observation cap"):
        orchestrator.run_evolution(args, runner=failing_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert len(observation_calls) == 100
    assert manifest["t50_observation_attempt_count"] == 100
    assert len(manifest["episode_failures"]) == 100
    assert observation_calls[-1].endswith("_retry01")


def test_t50_execute_writes_partial_checkpoint_when_target_not_reached(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 10
    args.target_completed_episodes = 3
    observation_calls: list[str] = []

    def mixed_runner(
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None,
    ) -> orchestrator.CommandResult:
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.evidence.observation":
            episode_id = command[command.index("--episode-id") + 1]
            observation_calls.append(episode_id)
            if len(observation_calls) == 1:
                turns = int(command[command.index("--turns") + 1])
                make_t50_episode(
                    cwd,
                    episode_id,
                    cities=3,
                    techs=9,
                    civics=9,
                    era_score=12,
                    turns=turns,
                )
                stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
                return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())
            return orchestrator.CommandResult(command, 1, "", "observation failed", started, orchestrator.now_iso())
        if module == "codex_hl.review.failure_labeling":
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(review / "candidates.jsonl", [])
            stdout = json.dumps({"episode_id": episode_id, "review_dir": str(review), "candidates": 0})
            return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())
        raise AssertionError(command)

    with pytest.raises(orchestrator.EvolutionError, match="Only completed 1 episode"):
        orchestrator.run_evolution(args, runner=mixed_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((tmp_path / "evolution_run" / "checkpoint_partial.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "incomplete"
    assert manifest["partial_checkpoint"].endswith("checkpoint_partial.json")
    assert manifest["latest_checkpoint_summary"]["partial"] is True
    assert manifest["latest_checkpoint_summary"]["failure_count"] == 2
    assert checkpoint["episode_count"] == 1
    assert len(checkpoint["failures"]) == 2
    assert (tmp_path / "evolution_run" / "checkpoint_partial.md").exists()


def test_t50_checkpoint_triggers_on_observation_attempts_including_failures(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 10
    args.target_completed_episodes = 10
    args.extra_attempt_slots = 2
    args.stop_on_checkpoint_alert = True
    observation_calls: list[str] = []

    def mixed_runner(
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None,
    ) -> orchestrator.CommandResult:
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.evidence.observation":
            episode_id = command[command.index("--episode-id") + 1]
            observation_calls.append(episode_id)
            if len(observation_calls) <= 8:
                turns = int(command[command.index("--turns") + 1])
                make_t50_episode(
                    cwd,
                    episode_id,
                    cities=3,
                    techs=9,
                    civics=9,
                    era_score=12,
                    turns=turns,
                )
                stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
                return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())
            return orchestrator.CommandResult(command, 1, "", "observation failed", started, orchestrator.now_iso())
        if module == "codex_hl.review.failure_labeling":
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(review / "candidates.jsonl", [])
            stdout = json.dumps({"episode_id": episode_id, "review_dir": str(review), "candidates": 0})
            return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())
        raise AssertionError(command)

    result = orchestrator.run_evolution(args, runner=mixed_runner)

    checkpoint = json.loads((tmp_path / "evolution_run" / "checkpoint_c01.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "stopped_for_checkpoint_review"
    assert len(observation_calls) == 10
    assert checkpoint["observation_attempt_count"] == 10
    assert checkpoint["completed_episode_count"] == 8
    assert checkpoint["failure_count"] == 2
    assert checkpoint["episode_count"] == 8
    assert len(checkpoint["failures"]) == 2
    markdown = (tmp_path / "evolution_run" / "checkpoint_c01.md").read_text(encoding="utf-8")
    assert "| Slot | Attempt | Episode | Strategy | Error |" in markdown
    assert "observation failed" in markdown
    assert manifest["latest_checkpoint_summary"]["observation_attempt_count"] == 10
    assert manifest["latest_checkpoint_summary"]["completed_episode_count"] == 8
    assert manifest["latest_checkpoint_summary"]["failed_attempt_count"] == 2
    assert manifest["latest_checkpoint_summary"]["failure_count"] == 2
    assert manifest["latest_checkpoint_summary"]["markdown_report"].endswith("checkpoint_c01.md")


def test_t50_checkpoint_stops_after_all_failed_attempts(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 10
    args.target_completed_episodes = 10
    args.extra_attempt_slots = 10
    args.stop_on_checkpoint_alert = True
    observation_calls: list[str] = []

    def failing_runner(
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None,
    ) -> orchestrator.CommandResult:
        assert command[2] == "codex_hl.evidence.observation"
        observation_calls.append(command[command.index("--episode-id") + 1])
        started = orchestrator.now_iso()
        return orchestrator.CommandResult(command, 1, "", "observation failed", started, orchestrator.now_iso())

    result = orchestrator.run_evolution(args, runner=failing_runner)

    checkpoint = json.loads((tmp_path / "evolution_run" / "checkpoint_c01.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "stopped_for_checkpoint_review"
    assert len(observation_calls) == 10
    assert checkpoint["observation_attempt_count"] == 10
    assert checkpoint["completed_episode_count"] == 0
    assert checkpoint["failure_count"] == 10
    assert [alert["code"] for alert in checkpoint["checkpoint_alerts"]["alerts"]] == [
        "no_t50_pass_episode"
    ]
    assert checkpoint["checkpoint_alerts"]["recommendation"]["action"] == "stop_and_fix_strategy"
    assert manifest["latest_checkpoint_summary"]["checkpoint_alerts"]["stop_recommended"] is True


def test_checkpoint_only_builds_report_from_existing_episodes(tmp_path):
    make_t50_episode(tmp_path, "checkpoint_ep_a", cities=3, techs=9, civics=9, era_score=12)
    make_t50_episode(
        tmp_path,
        "checkpoint_ep_b",
        cities=3,
        techs=10,
        civics=10,
        era_score=19,
        gold=20,
    )
    args = base_args(tmp_path, execute=False)
    args.checkpoint_only = True
    args.checkpoint_episodes = ["checkpoint_ep_a", "checkpoint_ep_b"]

    result = orchestrator.run_evolution(
        args,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")),
    )

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
    assert result["status"] == "checkpoint_reported"
    assert manifest["status"] == "checkpoint_reported"
    assert manifest["checkpoint_episodes"] == ["checkpoint_ep_a", "checkpoint_ep_b"]
    assert result["checkpoint_summary"]["observation_attempt_count"] == 2
    assert result["checkpoint_summary"]["completed_episode_count"] == 2
    assert result["checkpoint_summary"]["failed_attempt_count"] == 0
    assert result["checkpoint_summary"]["best_episode"] == "checkpoint_ep_b"
    assert checkpoint["best_episode"] == "checkpoint_ep_b"
    assert checkpoint["top_3"][0]["episode_id"] == "checkpoint_ep_b"


def test_checkpoint_only_requires_episode_ids(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.checkpoint_only = True

    with pytest.raises(orchestrator.EvolutionError, match="checkpoint-episodes or --checkpoint-manifest"):
        orchestrator.run_evolution(args)


def test_checkpoint_only_can_load_completed_episodes_from_manifest(tmp_path):
    make_t50_episode(tmp_path, "manifest_ep_a", cities=3, techs=9, civics=9, era_score=12)
    make_t50_episode(
        tmp_path,
        "manifest_ep_b",
        cities=3,
        techs=10,
        civics=10,
        era_score=19,
        gold=20,
    )
    source_manifest = tmp_path / "source_manifest.json"
    write_json(
        source_manifest,
        {
            "status": "stopped_for_checkpoint_review",
            "episodes": [
                {"episode_id": "manifest_ep_a"},
                {"episode_id": "manifest_ep_b"},
            ],
            "episode_failures": [
                {
                    "episode_id": "manifest_ep_failed",
                    "attempt": 1,
                    "error": "observation failed",
                }
            ],
        },
    )
    args = base_args(tmp_path, execute=False)
    args.checkpoint_only = True
    args.checkpoint_manifest = source_manifest

    result = orchestrator.run_evolution(
        args,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")),
    )

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
    assert result["status"] == "checkpoint_reported"
    assert manifest["checkpoint_manifest"] == str(source_manifest)
    assert manifest["checkpoint_episodes"] == ["manifest_ep_a", "manifest_ep_b"]
    assert manifest["episode_failures"][0]["episode_id"] == "manifest_ep_failed"
    assert result["checkpoint_summary"]["observation_attempt_count"] == 3
    assert result["checkpoint_summary"]["completed_episode_count"] == 2
    assert result["checkpoint_summary"]["failed_attempt_count"] == 1
    assert result["checkpoint_summary"]["failure_count"] == 1
    assert checkpoint["failures"][0]["episode_id"] == "manifest_ep_failed"
    assert checkpoint["best_episode"] == "manifest_ep_b"


def test_checkpoint_only_can_load_episode_ids_from_checkpoint_manifest(tmp_path):
    make_t50_episode(tmp_path, "checkpoint_manifest_ep", cities=3, techs=10, civics=10, era_score=19)
    source_manifest = tmp_path / "source_manifest.json"
    write_json(
        source_manifest,
        {
            "status": "checkpoint_reported",
            "checkpoint_episodes": ["checkpoint_manifest_ep"],
        },
    )
    args = base_args(tmp_path, execute=False)
    args.checkpoint_only = True
    args.checkpoint_manifest = source_manifest

    result = orchestrator.run_evolution(
        args,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("ran command")),
    )

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "checkpoint_reported"
    assert manifest["checkpoint_episodes"] == ["checkpoint_manifest_ep"]


def test_checkpoint_only_rejects_manifest_without_completed_episodes(tmp_path):
    source_manifest = tmp_path / "source_manifest.json"
    write_json(source_manifest, {"planned_episodes": ["planned_only"]})
    args = base_args(tmp_path, execute=False)
    args.checkpoint_only = True
    args.checkpoint_manifest = source_manifest

    with pytest.raises(orchestrator.EvolutionError, match="No completed episodes"):
        orchestrator.run_evolution(args)


def test_parse_stdout_json_accepts_pretty_json():
    payload = orchestrator.parse_stdout_json(
        '{\n  "ok": true,\n  "candidates": 2\n}\n',
        step="strategy_candidates",
    )

    assert payload == {"ok": True, "candidates": 2}


def test_json_dumps_escapes_unicode_for_windows_powershell_json_parsing():
    text = orchestrator.json_dumps({"current_research": "炼铁术"})

    assert text.isascii()
    assert "\\u70bc\\u94c1\\u672f" in text


def test_strategy_iteration_can_select_golden_age_push_profile():
    iteration = orchestrator.next_strategy_profile_from_review(
        current_profile="explore_scout_first",
        candidates=[
            {
                "title": "T50 科学文化低于目标",
                "expected_behavior": "及时研究写作并建设学院，清理蛮族，争取黄金时代。",
            }
        ],
    )

    assert iteration["to_profile"] == "golden_age_push"
    assert iteration["changed"] is True


def test_strategy_iteration_can_select_science_culture_t50_without_era_terms():
    iteration = orchestrator.next_strategy_profile_from_review(
        current_profile="explore_scout_first",
        candidates=[
            {
                "title": "T50 science and culture below target",
                "expected_behavior": "Research Writing, build Campus, and keep barbarian clearance active.",
            }
        ],
    )

    assert iteration["to_profile"] == "science_culture_t50"
    assert iteration["changed"] is True


def test_build_t50_validation_report_records_strategy_runtime_boundary(tmp_path):
    make_t50_episode(tmp_path, "baseline", cities=1, techs=2, civics=1)
    make_t50_episode(tmp_path, "candidate_a", cities=2, techs=3, civics=1)
    make_t50_episode(tmp_path, "candidate_b", cities=1, techs=4, civics=2, era_score=19)

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
    assert report["scenario_results"][1]["best_run_score"]["golden_age"] is True
    assert report["top_3"][0]["episode_id"] == "candidate_b"


def test_t50_best_run_ranking_prioritizes_golden_then_core_floor(tmp_path):
    make_t50_episode(
        tmp_path,
        "non_golden_big",
        cities=5,
        techs=12,
        civics=12,
        era_score=18,
        golden_threshold=19,
    )
    make_t50_episode(
        tmp_path,
        "golden_floor",
        cities=3,
        techs=10,
        civics=10,
        era_score=19,
        golden_threshold=19,
        gold=20,
    )

    ranked = orchestrator.rank_t50_episodes(
        tmp_path,
        ["non_golden_big", "golden_floor"],
        target_turns=50,
    )

    assert ranked[0]["episode_id"] == "golden_floor"
    assert ranked[0]["best_run_score"]["golden_age"] is True
    assert ranked[0]["best_run_score"]["core_floor_met"] is True
    assert ranked[0]["delta_from_current_best"]["era_score"] == 9
    assert ranked[0]["delta_from_current_best"]["gold"] == -454


def test_t50_best_run_score_uses_current_golden_age_after_era_rollover(tmp_path):
    make_t50_episode(
        tmp_path,
        "rolled_golden",
        cities=3,
        techs=9,
        civics=9,
        era_score=2,
        golden_threshold=18,
        current_era="ERA_CLASSICAL",
        current_age="GOLDEN",
    )

    ranked = orchestrator.rank_t50_episodes(
        tmp_path,
        ["rolled_golden"],
        target_turns=50,
    )

    assert ranked[0]["metrics"]["current_age"] == "GOLDEN"
    assert ranked[0]["best_run_score"]["golden_age"] is True


def test_checkpoint_report_records_top3_and_strategy_traces(tmp_path):
    make_t50_episode(tmp_path, "ep1", cities=2, techs=8, civics=8, era_score=12)
    make_t50_episode(
        tmp_path,
        "ep2",
        cities=3,
        techs=9,
        civics=9,
        era_score=19,
        gold=200,
        governors=[
            {
                "governor_type": "GOVERNOR_THE_EDUCATOR",
                "city": "Capital",
                "city_id": 1,
                "assigned": True,
            }
        ],
        target_events=[
            {"event_key": "tribal_village", "active": True},
            {"event_key": "first_strategic_resource_unit", "active": False},
        ],
        strategic_resources=[
            {"name": "HORSES", "stockpile": 18, "per_turn": 2, "surplus_after_reserve": 8}
        ],
        unimproved_strategic_resources=[{"name": "IRON", "x": 7, "y": 8}],
        tradable_players=[{"player_id": 1, "civ_name": "Neighbor"}],
        war_targets=[
            {
                "player_id": 1,
                "civ_name": "Neighbor",
                "available_actions": ["DECLARE_SURPRISE_WAR"],
                "favorable_attack_count": 1,
                "border_pressure_count": 0,
            }
        ],
        opportunities=["opportunistic_neighbor_war", "improve_strategic_resource"],
    )
    write_jsonl(
        tmp_path / "episodes" / "ep2" / "derived" / "decision_atoms.jsonl",
        [
            {
                "turn": 51,
                "selected_action": "purchase UNIT_HORSEMAN with gold",
                "trigger": "golden age gold spender",
            },
            {
                "turn": 51,
                "selected_action": "sell surplus strategic resource",
                "trigger": "strategic resource monetization",
            },
            {
                "turn": 51,
                "selected_action": "DECLARE_SURPRISE_WAR on Neighbor",
                "trigger": "opportunistic war gate",
            },
            {
                "turn": 52,
                "selected_action": "attack target",
                "trigger": "unit action review UNIT_WARRIOR 101",
                "execution": {
                    "tool": "unit_action",
                    "action": "attack target",
                    "target": {"is_opportunistic_war": True, "is_barbarian": False},
                },
            },
            {
                "turn": 52,
                "selected_action": "attack target",
                "trigger": "unit action review UNIT_SLINGER 102",
                "execution": {
                    "tool": "unit_action",
                    "action": "attack target",
                    "target": {"is_barbarian": True},
                },
            },
        ],
    )

    report = orchestrator.build_t50_checkpoint_report(
        workspace=tmp_path,
        output_path=tmp_path / "checkpoint.json",
        episode_ids=["ep1", "ep2"],
        failures=[],
    )

    assert report["top_3"][0]["episode_id"] == "ep2"
    assert report["observation_attempt_count"] == 2
    assert report["completed_episode_count"] == 2
    assert report["failure_count"] == 0
    assert report["best_eligibility"][0]["episode_id"] == "ep2"
    assert report["best_eligibility"][0]["golden_age"] is True
    assert report["best_eligibility"][0]["core_floor_met"] is False
    assert report["best_eligibility"][0]["eligible"] is False
    assert report["current_best_reference"]["episode_id"] == (
        "goal20_sciculture_clearpush_20260525_023950_c01_e01_t50_retry01"
    )
    assert report["top_3"][0]["delta_from_current_best"]["era_score"] == 9
    assert report["top_3"][0]["delta_from_current_best"]["num_cities"] == 0
    assert report["strategy_traces"][1]["gold_actions"][0]["selected_action"].startswith("purchase")
    assert report["gold_conversion_rates"]["ep2"] == 1.0
    assert report["era_score_curves"]["ep2"][0]["era_score"] == 19
    assert report["golden_age_event_summaries"]["ep2"]["active_counts"]["tribal_village"] == 1
    assert report["governor_assignment_statuses"]["ep2"]["status"] == "all_assigned"
    assert report["resource_trade_summaries"]["ep2"]["trade_count"] == 1
    assert report["resource_trade_summaries"]["ep2"]["turns_with_surplus_strategics"] == 1
    assert report["resource_trade_summaries"]["ep2"]["final_unimproved_strategic_resources"][0]["name"] == "IRON"
    assert report["war_action_summaries"]["ep2"]["war_action_count"] == 2
    assert report["war_action_summaries"]["ep2"]["turns_with_war_opportunity"] == 1
    assert report["checkpoint_alerts"]["review_recommended"] is True
    assert report["checkpoint_alerts"]["recommendation"]["action"] == "review_before_continuing"
    assert report["best_episode"] is None
    assert (tmp_path / "checkpoint.json").exists()
    markdown = (tmp_path / "checkpoint.md").read_text(encoding="utf-8")
    assert "# T50 Checkpoint Report" in markdown
    assert "Observation attempts" in markdown
    assert "Completed episodes" in markdown
    assert "Failed attempts" in markdown
    assert "Recommended action" in markdown
    assert "## Top 3 PASS Episodes" in markdown
    assert "## Best Eligibility" in markdown
    assert "| Episode | Eligible | Golden | Core Floor | Techs | Civics | Science | Culture | Era |" in markdown
    assert "## Golden Age Target Events" in markdown
    assert "tribal_village:1" in markdown
    assert "first_strategic_resource_unit:1" in markdown
    assert "ep2" in markdown
    assert "## Strategy Trace Summary" in markdown
    assert report["markdown_report"] == str(tmp_path / "checkpoint.md")


def test_checkpoint_trace_falls_back_to_overview_for_legacy_episodes(tmp_path):
    make_legacy_t50_episode_without_strategy_audit(
        tmp_path,
        "legacy_best",
        final_era_score=10,
        final_gold=474,
    )

    report = orchestrator.build_t50_checkpoint_report(
        workspace=tmp_path,
        output_path=tmp_path / "checkpoint.json",
        episode_ids=["legacy_best"],
        failures=[],
    )

    curve = report["era_score_curves"]["legacy_best"]
    assert [row["source"] for row in curve] == ["overview_fallback"] * 3
    assert curve[-1]["era_score"] == 10
    assert curve[-1]["golden_threshold"] == 19
    assert curve[-1]["era_score_gap"] == 9
    assert report["strategy_traces"][0]["gold_conversion"]["final_gold"] == 474
    assert report["strategy_traces"][0]["gold_conversion"]["pressure_turns"] == 2
    assert "idle_gold_not_converted" in {
        alert["code"] for alert in report["checkpoint_alerts"]["alerts"]
    }


def test_checkpoint_top3_only_ranks_t50_pass_episodes(tmp_path):
    make_t50_episode(
        tmp_path,
        "failed_golden",
        cities=5,
        techs=12,
        civics=12,
        era_score=19,
        turns=49,
    )
    make_t50_episode(
        tmp_path,
        "passed_non_golden",
        cities=3,
        techs=9,
        civics=9,
        era_score=12,
    )

    report = orchestrator.build_t50_checkpoint_report(
        workspace=tmp_path,
        output_path=tmp_path / "checkpoint.json",
        episode_ids=["failed_golden", "passed_non_golden"],
        failures=[],
    )

    assert report["top_3"][0]["episode_id"] == "passed_non_golden"
    assert [row["episode_id"] for row in report["ranked_pass_episodes"]] == ["passed_non_golden"]
    assert report["best_eligible_top_3"] == []
    assert report["best_episode"] is None
    assert {row["episode_id"] for row in report["ranked_episodes"]} == {
        "failed_golden",
        "passed_non_golden",
    }


def test_checkpoint_records_best_episode_only_when_golden_and_core_floor_pass(tmp_path):
    make_t50_episode(
        tmp_path,
        "golden_low_core",
        cities=4,
        techs=8,
        civics=8,
        era_score=19,
    )
    make_t50_episode(
        tmp_path,
        "golden_core_floor",
        cities=3,
        techs=10,
        civics=10,
        era_score=19,
        gold=20,
    )

    report = orchestrator.build_t50_checkpoint_report(
        workspace=tmp_path,
        output_path=tmp_path / "checkpoint.json",
        episode_ids=["golden_low_core", "golden_core_floor"],
        failures=[],
    )

    assert report["best_episode"] == "golden_core_floor"
    assert report["best_eligible_top_3"][0]["episode_id"] == "golden_core_floor"
    assert report["best_episode_requirements"]["golden_age_required"] is True
    assert report["checkpoint_alerts"]["stop_recommended"] is False


def test_checkpoint_alerts_recommend_stop_when_no_golden_pass(tmp_path):
    make_t50_episode(
        tmp_path,
        "passed_non_golden_a",
        cities=3,
        techs=9,
        civics=9,
        era_score=12,
    )
    make_t50_episode(
        tmp_path,
        "passed_non_golden_b",
        cities=4,
        techs=10,
        civics=10,
        era_score=18,
    )

    report = orchestrator.build_t50_checkpoint_report(
        workspace=tmp_path,
        output_path=tmp_path / "checkpoint.json",
        episode_ids=["passed_non_golden_a", "passed_non_golden_b"],
        failures=[],
    )

    assert report["checkpoint_alerts"]["stop_recommended"] is True
    assert {
        alert["code"] for alert in report["checkpoint_alerts"]["alerts"]
    } >= {"no_golden_age_pass_episode"}


def test_checkpoint_alerts_warn_on_idle_resources_and_unused_war_windows(tmp_path):
    make_t50_episode(
        tmp_path,
        "golden_with_missed_resource_and_war",
        cities=3,
        techs=10,
        civics=10,
        era_score=19,
        strategic_resources=[
            {"name": "HORSES", "stockpile": 22, "per_turn": 2, "surplus_after_reserve": 12}
        ],
        unimproved_strategic_resources=[{"name": "HORSES", "x": 4, "y": 5}],
        war_targets=[
            {
                "player_id": 2,
                "civ_name": "Neighbor",
                "available_actions": ["DECLARE_SURPRISE_WAR"],
                "favorable_attack_count": 1,
                "border_pressure_count": 1,
            }
        ],
        opportunities=["opportunistic_neighbor_war", "improve_strategic_resource"],
    )

    report = orchestrator.build_t50_checkpoint_report(
        workspace=tmp_path,
        output_path=tmp_path / "checkpoint.json",
        episode_ids=["golden_with_missed_resource_and_war"],
        failures=[],
    )

    alert_codes = {alert["code"] for alert in report["checkpoint_alerts"]["alerts"]}
    assert {
        "surplus_strategics_not_traded",
        "strategic_resource_unimproved",
        "war_opportunity_not_used",
    } <= alert_codes
    assert report["checkpoint_alerts"]["stop_recommended"] is False


def test_build_t50_validation_report_records_candidate_runtime_coupling(tmp_path):
    make_t50_episode(tmp_path, "baseline", cities=1, techs=2, civics=1)
    make_t50_episode(tmp_path, "candidate_a", cities=2, techs=3, civics=1)
    candidate = tmp_path / "candidate.json"
    write_json(candidate, {"candidate_id": "impr_test"})

    report = orchestrator.build_t50_validation_report(
        workspace=tmp_path,
        output_path=tmp_path / "report.json",
        baseline_episode="baseline",
        candidate_episodes=["candidate_a"],
        candidate_package=candidate,
        candidate_runtime_applied=True,
    )

    assert report["candidate_runtime_applied"] is True
    assert report["strategy_runtime_coupled"] is True
    assert report["candidate_package"] == str(candidate)


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


def test_execute_runs_t50_review_and_optional_downstream(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.allow_auto_confirmation = True
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        calls.append(command)
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.evidence.observation":
            episode_id = command[command.index("--episode-id") + 1]
            turns = int(command[command.index("--turns") + 1])
            assert command[command.index("--strategy-profile") + 1] == args.strategy_profile
            index = int(episode_id.split("_e")[-1].split("_")[0])
            make_t50_episode(cwd, episode_id, cities=index, techs=index + 1, civics=index, turns=turns)
            stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
        elif module == "codex_hl.review.failure_labeling" and "--apply-confirmation" not in command:
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(
                review / "candidates.jsonl",
                [
                    {
                        "candidate_id": f"cand_{episode_id}",
                        "human_status": "pending",
                        "capability_category": "planning",
                        "confidence": "high",
                    }
                ],
            )
            stdout = json.dumps({"episode_id": episode_id, "review_dir": str(review), "candidates": 1})
        elif module == "codex_hl.review.failure_labeling":
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(review / "failures.jsonl", [{"failure_id": f"fail_{episode_id}"}])
            write_jsonl(review / "regression_seeds.jsonl", [{"seed_id": f"seed_{episode_id}"}])
            stdout = json.dumps({"episode_id": episode_id, "failures": 1, "regression_seeds": 1})
        elif module == "codex_hl.strategy.candidates":
            episode_id = command[command.index("--episode-id") + 1]
            package = cwd / "episodes" / episode_id / "strategy" / "candidates" / "candidate_packages" / "impr_test" / "candidate.json"
            write_json(package, {"candidate_id": "impr_test"})
            write_jsonl(cwd / "episodes" / episode_id / "strategy" / "candidates" / "candidate_improvements.jsonl", [{"candidate_id": "impr_test"}])
            stdout = json.dumps({"episode_id": episode_id, "candidates": 1})
        elif module == "codex_hl.validation.scenarios":
            episode_id = command[command.index("--episode-id") + 1]
            pool = cwd / "validation" / "scenarios"
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
    assert any(call[2] == "codex_hl.strategy.candidates" for call in calls)
    assert any(call[2] == "codex_hl.validation.scenarios" for call in calls)


def test_execute_stops_after_checkpoint_alert_when_no_golden_age_pass(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 2
    args.target_completed_episodes = 4
    args.stop_on_checkpoint_alert = True
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        calls.append(command)
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.evidence.observation":
            episode_id = command[command.index("--episode-id") + 1]
            turns = int(command[command.index("--turns") + 1])
            make_t50_episode(
                cwd,
                episode_id,
                cities=3,
                techs=9,
                civics=9,
                era_score=12,
                turns=turns,
            )
            stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
        elif module == "codex_hl.review.failure_labeling":
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(review / "candidates.jsonl", [])
            stdout = json.dumps({"episode_id": episode_id, "review_dir": str(review), "candidates": 0})
        else:
            raise AssertionError(command)
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    result = orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads((tmp_path / "evolution_run" / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "stopped_for_checkpoint_review"
    assert len(result["episodes"]) == 2
    assert len([call for call in calls if call[2] == "codex_hl.evidence.observation"]) == 2
    assert len(result["checkpoints"]) == 1
    assert manifest["status"] == "stopped_for_checkpoint_review"
    assert manifest["latest_checkpoint_summary"]["checkpoint_alerts"]["stop_recommended"] is True
    assert manifest["latest_checkpoint_summary"]["markdown_report"].endswith("checkpoint_c01.md")
    assert {
        alert["code"]
        for alert in manifest["latest_checkpoint_summary"]["checkpoint_alerts"]["alerts"]
    } >= {"no_golden_age_pass_episode"}


def test_execute_can_resume_from_existing_manifest_without_rerunning_completed_slots(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 2
    args.target_completed_episodes = 4
    args.output_dir = tmp_path / "evolution_run"
    args.resume_manifest = args.output_dir / "manifest.json"
    make_t50_episode(tmp_path, "evo_test_c01_e01_t50", cities=3, techs=9, civics=9, era_score=12)
    make_t50_episode(tmp_path, "evo_test_c01_e02_t50", cities=3, techs=9, civics=9, era_score=12)
    write_json(
        args.resume_manifest,
        {
            "run_id": "evo_test",
            "created_at": "2026-05-25T00:00:00+08:00",
            "status": "interrupted",
            "strategy_profile": "golden_age_push",
            "episodes": [
                {"episode_id": "evo_test_c01_e01_t50", "slot": 1, "attempt": 0},
                {"episode_id": "evo_test_c01_e02_t50", "slot": 2, "attempt": 0},
            ],
            "review": [],
            "episode_failures": [],
        },
    )
    observation_episode_ids: list[str] = []

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.evidence.observation":
            episode_id = command[command.index("--episode-id") + 1]
            observation_episode_ids.append(episode_id)
            turns = int(command[command.index("--turns") + 1])
            make_t50_episode(
                cwd,
                episode_id,
                cities=3,
                techs=10,
                civics=10,
                era_score=19,
                gold=20,
                turns=turns,
            )
            stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
        elif module == "codex_hl.review.failure_labeling":
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(review / "candidates.jsonl", [])
            stdout = json.dumps({"episode_id": episode_id, "review_dir": str(review), "candidates": 0})
        else:
            raise AssertionError(command)
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    result = orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads(args.resume_manifest.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert observation_episode_ids == ["evo_test_c02_e01_t50", "evo_test_c02_e02_t50"]
    assert len(result["episodes"]) == 4
    assert manifest["resume_source"] == str(args.resume_manifest)
    assert manifest["completed_episode_count"] == 4
    assert manifest["episodes"][0]["episode_id"] == "evo_test_c01_e01_t50"
    assert manifest["episodes"][-1]["episode_id"] == "evo_test_c02_e02_t50"
    assert manifest["latest_checkpoint_summary"]["best_episode"] == "evo_test_c02_e01_t50"


def test_execute_resume_skips_failed_slots_and_counts_attempt_budget(tmp_path):
    args = base_args(tmp_path, execute=True)
    args.episodes_per_cycle = 2
    args.target_completed_episodes = 4
    args.extra_attempt_slots = 1
    args.output_dir = tmp_path / "evolution_run"
    args.resume_manifest = args.output_dir / "manifest.json"
    make_t50_episode(tmp_path, "evo_test_c01_e01_t50", cities=3, techs=9, civics=9, era_score=12)
    make_t50_episode(tmp_path, "evo_test_c01_e02_t50", cities=3, techs=9, civics=9, era_score=12)
    write_json(
        args.resume_manifest,
        {
            "run_id": "evo_test",
            "created_at": "2026-05-25T00:00:00+08:00",
            "status": "interrupted",
            "strategy_profile": "golden_age_push",
            "episodes": [
                {"episode_id": "evo_test_c01_e01_t50", "slot": 1, "attempt": 0},
                {"episode_id": "evo_test_c01_e02_t50", "slot": 2, "attempt": 0},
            ],
            "review": [],
            "episode_failures": [
                {
                    "episode_id": "evo_test_c02_e01_t50",
                    "slot": 3,
                    "attempt": 0,
                    "error": "observation failed",
                }
            ],
        },
    )
    observation_episode_ids: list[str] = []

    def fake_runner(command: list[str], cwd: Path, env: dict[str, str] | None) -> orchestrator.CommandResult:
        module = command[2]
        started = orchestrator.now_iso()
        if module == "codex_hl.evidence.observation":
            episode_id = command[command.index("--episode-id") + 1]
            observation_episode_ids.append(episode_id)
            turns = int(command[command.index("--turns") + 1])
            make_t50_episode(
                cwd,
                episode_id,
                cities=3,
                techs=10,
                civics=10,
                era_score=19,
                gold=20,
                turns=turns,
            )
            stdout = json.dumps({"episode_id": episode_id, "report_path": f"episodes/{episode_id}/outcome/report.html"})
        elif module == "codex_hl.review.failure_labeling":
            episode_id = command[command.index("--episode-id") + 1]
            review = cwd / "episodes" / episode_id / "review"
            write_jsonl(review / "candidates.jsonl", [])
            stdout = json.dumps({"episode_id": episode_id, "review_dir": str(review), "candidates": 0})
        else:
            raise AssertionError(command)
        return orchestrator.CommandResult(command, 0, stdout, "", started, orchestrator.now_iso())

    result = orchestrator.run_evolution(args, runner=fake_runner)

    manifest = json.loads(args.resume_manifest.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert observation_episode_ids == ["evo_test_c02_e02_t50", "evo_test_c03_e01_t50"]
    assert manifest["completed_episode_count"] == 4
    assert manifest["t50_observation_attempt_count"] == 5
    assert manifest["episodes"][-1]["episode_id"] == "evo_test_c03_e01_t50"


def test_allow_merge_requires_candidate_runtime_applied(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.allow_merge = True
    args.candidate_package = tmp_path / "candidate.json"

    with pytest.raises(orchestrator.EvolutionError, match="candidate-runtime-applied"):
        orchestrator.run_evolution(args)


def test_candidate_runtime_applied_requires_candidate_package(tmp_path):
    args = base_args(tmp_path, execute=False)
    args.candidate_runtime_applied = True

    with pytest.raises(orchestrator.EvolutionError, match="candidate-package"):
        orchestrator.run_evolution(args)

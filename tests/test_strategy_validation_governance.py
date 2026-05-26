import json
from pathlib import Path

import pytest

from codex_hl.governance import gates as automation
from codex_hl.strategy import candidates as improvements
from codex_hl.strategy import registry as assets
from codex_hl.validation import scenarios


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def make_asset_root(root: Path) -> Path:
    body = "# Observation Observation\n\nKeep evidence complete.\n"
    asset_body = root / "assets" / "playbook-observation.md"
    asset_body.parent.mkdir(parents=True, exist_ok=True)
    asset_body.write_text(body, encoding="utf-8")
    digest = assets.sha256_file(asset_body)
    write_json(
        root / "catalog.json",
        {
            "schema_version": 1,
            "assets": [
                {
                    "asset_id": "strategy.playbook.observation",
                    "asset_type": "playbook",
                    "version": "1.0.0",
                    "content_path": "assets/playbook-observation.md",
                    "content_sha256": digest,
                    "source_refs": ["tests"],
                    "applicability": ["test"],
                    "risk_level": "high",
                    "rollback_path": "assets/playbook-observation.md",
                    "capability_dimensions": ["planning", "verification"],
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
                "human_or_auto_judgments": ["unit test"],
                "notes": "test",
            }
        ],
    )
    return root


def make_confirmed_failure(workspace: Path, episode_id: str = "ep1") -> Path:
    review = workspace / "episodes" / episode_id / "review"
    failure = {
        "failure_id": "fail-001",
        "episode_id": episode_id,
        "title": "Unit was held without checking exploration value",
        "description": "The decision stayed local and did not inspect exploration alternatives.",
        "capability_category": "planning",
        "failure_type": "misjudgment",
        "confidence": "medium",
        "turn_range": [1, 3],
        "expected_behavior": "Review exploration alternatives before holding the unit.",
        "failed_behavior": "The unit was held without enough comparison.",
        "evidence_refs": [
            {"kind": "decision_atom", "id": "decision-001", "path": "derived/decision_atoms.jsonl"},
            {"kind": "tool_call", "id": "tool-001", "path": "raw/tool_calls.jsonl"},
            {"kind": "state_snapshot", "id": "state-001", "path": "raw/civ6_states/state-001.json"},
            {"kind": "save", "id": "save-001", "path": "raw/saves/save_index.jsonl"},
        ],
    }
    seed = {
        "seed_id": "seed-001",
        "source_failure_ids": ["fail-001"],
        "manual_review_required": True,
    }
    write_jsonl(review / "failures.jsonl", [failure])
    write_jsonl(review / "regression_seeds.jsonl", [seed])
    return review


def test_strategy_candidate_generates_candidate_packages_without_mutating_assets(tmp_path):
    asset_root = make_asset_root(tmp_path / "asset_root")
    make_confirmed_failure(tmp_path)
    before = (asset_root / "assets" / "playbook-observation.md").read_text(encoding="utf-8")

    result = improvements.generate_candidate_packages("ep1", workspace=tmp_path, asset_root=asset_root)

    candidate_path = (
        tmp_path
        / "episodes"
        / "ep1"
        / "strategy" / "candidates"
        / "candidate_packages"
        / "impr_5b84830751942d"
        / "candidate.json"
    )
    candidates = improvements.read_jsonl(tmp_path / "episodes" / "ep1" / "strategy" / "candidates" / "candidate_improvements.jsonl")
    candidate = improvements.read_json(candidate_path) if candidate_path.exists() else candidates[0]

    assert result["candidates"] == 1
    assert candidate["status"] == "candidate_only"
    assert candidate["auto_merge_allowed"] is False
    assert candidate["target_asset"]["asset_id"] == "strategy.playbook.observation"
    assert "proposed_content" in candidate["proposed_change"]
    assert (asset_root / "assets" / "playbook-observation.md").read_text(encoding="utf-8") == before
    assert (tmp_path / "episodes" / "ep1" / "strategy" / "candidates" / "strategy_candidate_review.html").exists()


def test_validation_scenario_ingests_failures_into_idempotent_scenario_pool(tmp_path):
    make_confirmed_failure(tmp_path)
    pool_root = tmp_path / "validation" / "scenarios"

    first = scenarios.ingest_episode_failures("ep1", workspace=tmp_path, pool_root=pool_root)
    second = scenarios.ingest_episode_failures("ep1", workspace=tmp_path, pool_root=pool_root)

    rows = scenarios.read_jsonl(pool_root / "regression_scenarios.jsonl")
    assert first["new_or_updated"] == 1
    assert second["scenario_count"] == 1
    assert len(rows) == 1
    assert rows[0]["source_failure_ids"] == ["fail-001"]
    assert rows[0]["runnable"] is False
    assert rows[0]["starting_save_refs"][0]["id"] == "save-001"
    assert (tmp_path / "episodes" / "ep1" / "validation" / "scenarios" / "scenario_ingest.json").exists()


def test_governance_evaluates_applies_and_rolls_back_guarded_merge(tmp_path):
    asset_root = make_asset_root(tmp_path / "asset_root")
    make_confirmed_failure(tmp_path)
    improvements.generate_candidate_packages("ep1", workspace=tmp_path, asset_root=asset_root)
    candidate = improvements.read_jsonl(tmp_path / "episodes" / "ep1" / "strategy" / "candidates" / "candidate_improvements.jsonl")[0]
    candidate_path = tmp_path / "candidate.json"
    write_json(candidate_path, candidate)
    validation_report = tmp_path / "validation_report.json"
    write_json(
        validation_report,
        {
            "schema_version": 1,
            "scenario_results": [
                {"scenario_id": "scn-1", "status": "pass", "t50_delta": {"num_cities": 1}},
                {"scenario_id": "scn-2", "status": "pass", "t50_delta": {"completed_tech_count": 1}},
            ],
            "regressions": [],
        },
    )
    asset_path = asset_root / "assets" / "playbook-observation.md"
    original = asset_path.read_text(encoding="utf-8")

    audit_only = automation.evaluate_candidate(
        candidate_path,
        validation_report,
        asset_root=asset_root,
        workspace=tmp_path,
    )
    assert audit_only["merge_allowed"] is True
    assert asset_path.read_text(encoding="utf-8") == original

    merged = automation.evaluate_candidate(
        candidate_path,
        validation_report,
        asset_root=asset_root,
        workspace=tmp_path,
        allow_merge=True,
    )
    assert merged["merge_result"]["event"] == "auto_merge_applied"
    assert "Strategy Candidate Lesson" in asset_path.read_text(encoding="utf-8")
    assert assets.validate_catalog(asset_root)["assets"][0]["version"] == "1.0.1"

    rollback = automation.rollback_from_audit(
        Path(merged["audit_dir"]),
        asset_root=asset_root,
        reason="unit test rollback",
    )
    assert rollback["event"] == "auto_rollback_applied"
    assert asset_path.read_text(encoding="utf-8") == original
    assert assets.validate_catalog(asset_root)["assets"][0]["version"] == "1.0.0"


def test_governance_rejects_single_scenario_merge(tmp_path):
    asset_root = make_asset_root(tmp_path / "asset_root")
    make_confirmed_failure(tmp_path)
    improvements.generate_candidate_packages("ep1", workspace=tmp_path, asset_root=asset_root)
    candidate = improvements.read_jsonl(tmp_path / "episodes" / "ep1" / "strategy" / "candidates" / "candidate_improvements.jsonl")[0]
    candidate_path = tmp_path / "candidate.json"
    write_json(candidate_path, candidate)
    validation_report = tmp_path / "validation_report.json"
    write_json(
        validation_report,
        {
            "schema_version": 1,
            "scenario_results": [
                {"scenario_id": "scn-1", "status": "pass", "t50_delta": {"num_cities": 1}}
            ],
            "regressions": [],
        },
    )

    decision = automation.evaluate_candidate(
        candidate_path,
        validation_report,
        asset_root=asset_root,
        workspace=tmp_path,
    )

    assert decision["merge_allowed"] is False
    assert decision["gates"]["multi_scenario_validation"] is False
    with pytest.raises(automation.GovernanceError):
        automation.evaluate_candidate(
            candidate_path,
            validation_report,
            asset_root=asset_root,
            workspace=tmp_path,
            allow_merge=True,
        )

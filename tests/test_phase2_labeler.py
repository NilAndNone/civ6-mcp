import json
from pathlib import Path

import pytest

from codex_hl.phase2 import labeler


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_episode(workspace: Path, episode_id: str = "ep_short") -> Path:
    episode = workspace / "episodes" / episode_id
    write_json(
        episode / "header.json",
        {
            "episode_id": episode_id,
            "observation_mode": "short_validation",
            "requested_turns": 3,
        },
    )
    write_jsonl(
        episode / "raw" / "tool_calls.jsonl",
        [
            {
                "tool_call_id": "tool-0001",
                "episode_id": episode_id,
                "turn": 1,
                "tool": "unit_action",
                "success": True,
                "result_raw": "FORTIFIED",
            },
            {
                "tool_call_id": "tool-0002",
                "episode_id": episode_id,
                "turn": 2,
                "tool": "set_city_production",
                "success": True,
                "result_raw": "builder",
            },
        ],
    )
    write_jsonl(episode / "raw" / "mcp.jsonl", [])
    write_json(
        episode / "raw" / "civ6_states" / "state-0001-T0001-turn_start_1.json",
        {
            "snapshot_id": "state-0001-T0001-turn_start_1",
            "episode_id": episode_id,
            "turn": 1,
            "overview": {"turn": 1},
        },
    )
    write_jsonl(
        episode / "raw" / "saves" / "save_index.jsonl",
        [
            {
                "save_id": "save-0001",
                "episode_id": episode_id,
                "turn": 1,
                "label": "phase1_start",
                "sha256": "abc123",
            }
        ],
    )
    (episode / "raw" / "saves" / "save-0001_phase1_start.Civ6Save").write_bytes(b"fake-save")
    write_jsonl(
        episode / "derived" / "decision_atoms.jsonl",
        [
            {
                "decision_id": "decision-0001",
                "episode_id": episode_id,
                "turn": 1,
                "trigger": "missing research target",
                "selected_action": "set tech TECH_MINING",
                "available_actions": ["set tech TECH_POTTERY", "set tech TECH_MINING"],
                "related_tool_call_ids": [],
                "related_state_snapshot_ids": ["state-0001-T0001-turn_start_1"],
                "related_save_ids": [],
                "evidence_ids": {
                    "tool_call_ids": [],
                    "state_snapshot_ids": ["state-0001-T0001-turn_start_1"],
                    "save_ids": [],
                },
            },
            {
                "decision_id": "decision-0002",
                "episode_id": episode_id,
                "turn": 1,
                "trigger": "unit action review UNIT_WARRIOR",
                "selected_action": "fortify",
                "available_actions": ["move to explored tile", "fortify/hold"],
                "related_tool_call_ids": ["tool-0001"],
                "related_state_snapshot_ids": ["state-0001-T0001-turn_start_1"],
                "related_save_ids": [],
                "evidence_ids": {
                    "tool_call_ids": ["tool-0001"],
                    "state_snapshot_ids": ["state-0001-T0001-turn_start_1"],
                    "save_ids": [],
                },
            },
            {
                "decision_id": "decision-0003",
                "episode_id": episode_id,
                "turn": 2,
                "trigger": "city production",
                "selected_action": "UNIT 建造者",
                "available_actions": ["UNIT 侦察兵", "UNIT 建造者"],
                "related_tool_call_ids": ["tool-0002"],
                "related_state_snapshot_ids": ["state-0001-T0001-turn_start_1"],
                "related_save_ids": [],
                "evidence_ids": {
                    "tool_call_ids": ["tool-0002"],
                    "state_snapshot_ids": ["state-0001-T0001-turn_start_1"],
                    "save_ids": [],
                },
            },
        ],
    )
    write_json(
        episode / "derived" / "report_pack.json",
        {
            "episode_id": episode_id,
            "run": {"start_turn": 1, "final_turn": 4, "actual_turns": 3},
            "counts": {
                "tool_calls": 2,
                "lua_exchanges": 0,
                "state_snapshots": 1,
                "decision_atoms": 3,
                "indexed_saves": 1,
            },
            "evidence_status": {
                "tool_mcp_raw_records": {"status": "PASS"},
                "turn_state_snapshots": {"status": "PASS"},
                "decision_records": {"status": "PASS"},
                "save_links": {"status": "PASS"},
            },
        },
    )
    (episode / "outcome").mkdir(parents=True, exist_ok=True)
    (episode / "outcome" / "phase1_short_run_report.html").write_text(
        "<html lang='zh-CN'>phase 1 report</html>", encoding="utf-8"
    )
    return episode


def test_candidate_generation_is_offline_and_gated(tmp_path):
    episode = make_episode(tmp_path)
    before_hash = labeler.build_phase1_input_manifest(episode)["aggregate_sha256"]

    result = labeler.generate_candidates("ep_short", workspace=tmp_path, session_id="sess-test")

    phase2 = episode / "phase2"
    candidates = labeler.read_jsonl(phase2 / "candidates.jsonl")
    manifest = labeler.read_json(phase2 / "MANIFEST.json")
    review = (phase2 / "phase2_review.html").read_text(encoding="utf-8")

    assert result["candidates"] >= 3
    assert manifest["phase1_input_hash"] == before_hash
    assert labeler.build_phase1_input_manifest(episode)["aggregate_sha256"] == before_hash
    assert (phase2 / "analyzer_runs").exists()
    assert not (phase2 / "failures.jsonl").exists()
    assert not (phase2 / "regression_seeds.jsonl").exists()
    assert any(c["human_status"] == "pending" for c in candidates)
    assert any(labeler.CAVEAT_TEXT in c.get("scope_caveats", []) for c in candidates)
    assert "pending" in review
    assert labeler.CAVEAT_TEXT in review


def test_label_page_supports_batch_card_review(tmp_path):
    make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path, session_id="sess-test")
    candidates = labeler.read_jsonl(tmp_path / "episodes" / "ep_short" / "phase2" / "candidates.jsonl")

    page = labeler.label_page(candidates, "ep_short")

    assert 'action="/confirm-batch"' in page
    assert "保存所有非 skip 项" in page
    assert "只保存这条" in page
    assert f'name="action__{candidates[0]["candidate_id"]}"' in page
    assert "skip / 不改这条" in page


def test_apply_confirmation_creates_formal_failures_and_one_to_one_seeds(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path, session_id="sess-test")
    phase2 = episode / "phase2"
    candidates = labeler.read_jsonl(phase2 / "candidates.jsonl")
    planning = next(c for c in candidates if c["capability_category"] == "planning")
    rejected = next(c for c in candidates if c["candidate_id"] != planning["candidate_id"])
    confirmation = phase2 / "confirmation" / "confirmation.jsonl"
    write_jsonl(
        confirmation,
        [
            {
                "candidate_id": planning["candidate_id"],
                "action": "modify",
                "modified_fields": {
                    "confidence": "high",
                    "confidence_rationale": "human reviewer confirmed the local T10 fragment.",
                },
                "reviewer": "human",
                "reviewer_note": "accept as local short-run planning failure",
                "reviewed_at": "2026-05-14T00:00:00+08:00",
            },
            {
                "candidate_id": rejected["candidate_id"],
                "action": "reject",
                "modified_fields": {},
                "reviewer": "human",
                "reviewer_note": "not a gameplay failure",
                "reviewed_at": "2026-05-14T00:01:00+08:00",
            },
        ],
    )

    result = labeler.apply_confirmation("ep_short", confirmation, workspace=tmp_path)

    failures = labeler.read_jsonl(phase2 / "failures.jsonl")
    seeds = labeler.read_jsonl(phase2 / "regression_seeds.jsonl")
    review = (phase2 / "phase2_review.html").read_text(encoding="utf-8")
    summary = labeler.read_json(phase2 / "phase2_summary.json")
    formal_text = (phase2 / "failures.jsonl").read_text(encoding="utf-8") + (
        phase2 / "regression_seeds.jsonl"
    ).read_text(encoding="utf-8")

    assert result["failures"] == 1
    assert len(failures) == 1
    assert len(seeds) == 1
    assert seeds[0]["source_failure_ids"] == [failures[0]["failure_id"]]
    assert seeds[0]["not_runnable_in_phase2"] is True
    assert seeds[0]["manual_review_required"] is True
    assert seeds[0]["asset_change_allowed"] is False
    assert failures[0]["human_status"] == "confirmed"
    assert failures[0]["claim_scope"] == "local_episode_fragment"
    assert failures[0]["not_a_long_horizon_conclusion"] is True
    assert failures[0]["not_evidence_for_asset_change"] is True
    assert failures[0]["requires_t50_or_multi_episode_followup"] is True
    assert labeler.CAVEAT_TEXT in review
    assert summary["one_failure_to_one_seed"] is True
    assert "rerun_command" not in formal_text
    assert "suggested_fix" not in formal_text


def test_apply_rejects_forbidden_confirmation_fields(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path)
    phase2 = episode / "phase2"
    candidate = labeler.read_jsonl(phase2 / "candidates.jsonl")[0]
    confirmation = phase2 / "confirmation" / "confirmation.jsonl"
    write_jsonl(
        confirmation,
        [
            {
                "candidate_id": candidate["candidate_id"],
                "action": "modify",
                "modified_fields": {"suggested_fix": "change strategy"},
                "reviewer": "human",
                "reviewer_note": "bad row",
                "reviewed_at": "2026-05-14T00:00:00+08:00",
            }
        ],
    )

    with pytest.raises(labeler.Phase2Error):
        labeler.apply_confirmation("ep_short", confirmation, workspace=tmp_path)

    assert not (phase2 / "failures.jsonl").exists()
    assert not (phase2 / "regression_seeds.jsonl").exists()


def test_all_rejected_confirmation_keeps_empty_formal_outputs(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path)
    phase2 = episode / "phase2"
    candidates = labeler.read_jsonl(phase2 / "candidates.jsonl")
    confirmation = phase2 / "confirmation" / "confirmation.jsonl"
    write_jsonl(
        confirmation,
        [
            {
                "candidate_id": candidate["candidate_id"],
                "action": "reject",
                "modified_fields": {},
                "reviewer": "human",
                "reviewer_note": "not accepted",
                "reviewed_at": "2026-05-14T00:00:00+08:00",
            }
            for candidate in candidates
        ],
    )

    result = labeler.apply_confirmation("ep_short", confirmation, workspace=tmp_path)

    assert result["failures"] == 0
    assert labeler.read_jsonl(phase2 / "failures.jsonl") == []
    assert labeler.read_jsonl(phase2 / "regression_seeds.jsonl") == []
    review = (phase2 / "phase2_review.html").read_text(encoding="utf-8")
    assert "No formal failures yet" in review

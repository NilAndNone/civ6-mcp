import json
import shutil
from pathlib import Path

import pytest

from codex_hl.evidence.store import rebuild_episode_db
from codex_hl.review import failure_labeling as labeler


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_episode(
    workspace: Path,
    episode_id: str = "ep_short",
    *,
    observation_mode: str = "short_validation",
    requested_turns: int = 3,
    actual_turns: int = 3,
    final_turn: int = 4,
) -> Path:
    episode = workspace / "episodes" / episode_id
    write_json(
        episode / "header.json",
        {
            "episode_id": episode_id,
            "observation_mode": observation_mode,
            "requested_turns": requested_turns,
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
                "label": "observation_start",
                "sha256": "abc123",
            }
        ],
    )
    (episode / "raw" / "saves" / "save-0001_observation_start.Civ6Save").write_bytes(b"fake-save")
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
            "run": {"start_turn": 1, "final_turn": final_turn, "actual_turns": actual_turns},
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
    (episode / "outcome" / "observation_report.html").write_text(
        "<html lang='zh-CN'>observation report</html>", encoding="utf-8"
    )
    return episode


def test_candidate_generation_is_offline_and_gated(tmp_path):
    episode = make_episode(tmp_path)
    before_hash = labeler.build_evidence_input_manifest(episode)["aggregate_sha256"]

    result = labeler.generate_candidates("ep_short", workspace=tmp_path, session_id="sess-test")

    review = episode / "review"
    candidates = labeler.read_jsonl(review / "candidates.jsonl")
    manifest = labeler.read_json(review / "MANIFEST.json")
    review_html = (review / "review.html").read_text(encoding="utf-8")

    assert result["candidates"] >= 3
    assert manifest["evidence_input_hash"] == before_hash
    assert labeler.build_evidence_input_manifest(episode)["aggregate_sha256"] == before_hash
    assert (review / "analyzer_runs").exists()
    assert not (review / "failures.jsonl").exists()
    assert not (review / "regression_seeds.jsonl").exists()
    assert any(c["human_status"] == "pending" for c in candidates)
    assert any(labeler.CAVEAT_TEXT in c.get("scope_caveats", []) for c in candidates)
    assert "pending" in review_html
    assert labeler.CAVEAT_TEXT in review_html


def test_candidate_generation_reads_db_only_observation_episode(tmp_path):
    episode = make_episode(tmp_path, "ep_db_only")
    rebuild_episode_db(episode)
    for child in episode.iterdir():
        if child.name == "episode.db":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    result = labeler.generate_candidates("ep_db_only", workspace=tmp_path, session_id="sess-db")
    candidates = labeler.read_jsonl(episode / "review" / "candidates.jsonl")
    manifest = labeler.read_json(episode / "review" / "MANIFEST.json")

    assert result["candidates"] >= 3
    assert manifest["input_manifest"]["storage_backend"] == "sqlite"
    assert any(
        ref.get("storage_backend") == "sqlite" and ref.get("artifact_id")
        for candidate in candidates
        for ref in candidate["evidence_refs"]
        if ref.get("path") == "derived/report_pack.json"
    )


def test_t20_candidate_generation_is_local_fragment_evidence(tmp_path):
    episode = make_episode(
        tmp_path,
        "ep_t20",
        observation_mode="t20_exploration",
        requested_turns=20,
        actual_turns=20,
        final_turn=21,
    )

    labeler.generate_candidates("ep_t20", workspace=tmp_path, session_id="sess-t20")

    review = episode / "review"
    candidates = labeler.read_jsonl(review / "candidates.jsonl")
    manifest = labeler.read_json(review / "MANIFEST.json")
    planning = [candidate for candidate in candidates if candidate["capability_category"] == "planning"]

    assert manifest["episode_mode"] == "t20_exploration"
    assert manifest["turn_target"] == "T20"
    assert manifest["local_episode_fragment"] is True
    assert planning
    assert all(candidate["claim_scope"] == "local_episode_fragment" for candidate in planning)
    assert all(labeler.CAVEAT_TEXT in candidate["scope_caveats"] for candidate in planning)


def test_t50_candidate_generation_detects_over_scout_no_expansion(tmp_path):
    episode = make_episode(
        tmp_path,
        "ep_t50_overscout",
        observation_mode="t50_observation",
        requested_turns=50,
        actual_turns=50,
        final_turn=50,
    )
    write_json(
        episode / "raw" / "civ6_states" / "state-0051-T0050-t50_final.json",
        {
            "snapshot_id": "state-0051-T0050-t50_final",
            "episode_id": "ep_t50_overscout",
            "turn": 50,
            "label": "t50_final",
            "overview": {"turn": 50, "num_cities": 1, "num_units": 6},
            "units": [
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SCOUT"},
            ],
        },
    )
    decisions = labeler.read_jsonl(episode / "derived" / "decision_atoms.jsonl")
    decisions.append(
        {
            "decision_id": "decision-0099",
            "episode_id": "ep_t50_overscout",
            "turn": 42,
            "trigger": "idle city production for capital",
            "selected_action": "UNIT UNIT_SCOUT",
            "available_actions": ["UNIT UNIT_SCOUT", "UNIT UNIT_SETTLER"],
            "related_tool_call_ids": ["tool-0002"],
            "related_state_snapshot_ids": ["state-0051-T0050-t50_final"],
            "related_save_ids": [],
            "evidence_ids": {
                "tool_call_ids": ["tool-0002"],
                "state_snapshot_ids": ["state-0051-T0050-t50_final"],
                "save_ids": [],
            },
        }
    )
    write_jsonl(episode / "derived" / "decision_atoms.jsonl", decisions)

    labeler.generate_candidates("ep_t50_overscout", workspace=tmp_path, session_id="sess-t50")

    candidates = labeler.read_jsonl(episode / "review" / "candidates.jsonl")
    overscout = next(
        candidate for candidate in candidates if "过度生产侦察兵" in candidate["title"]
    )
    assert overscout["confidence"] == "medium"
    assert overscout["episode_mode"] == "t50_observation"
    assert labeler.CAVEAT_TEXT not in overscout["scope_caveats"]


def test_t50_candidate_generation_detects_unsettled_settler_pathing(tmp_path):
    episode = make_episode(
        tmp_path,
        "ep_t50_unsettled",
        observation_mode="t50_observation",
        requested_turns=50,
        actual_turns=50,
        final_turn=50,
    )
    write_json(
        episode / "raw" / "civ6_states" / "state-0051-T0050-t50_final.json",
        {
            "snapshot_id": "state-0051-T0050-t50_final",
            "episode_id": "ep_t50_unsettled",
            "turn": 50,
            "label": "t50_final",
            "overview": {"turn": 50, "num_cities": 2, "num_units": 3},
            "units": [{"unit_type": "UNIT_SETTLER"}],
        },
    )
    decisions = labeler.read_jsonl(episode / "derived" / "decision_atoms.jsonl")
    decisions.extend(
        [
            {
                "decision_id": "decision-0101",
                "episode_id": "ep_t50_unsettled",
                "turn": 40,
                "trigger": "expansion settler action 123",
                "selected_action": "move toward best settle candidate",
                "outcome": "CAPTURE_MOVE|68,36|BLOCKED",
                "related_tool_call_ids": ["tool-0002"],
                "related_state_snapshot_ids": ["state-0051-T0050-t50_final"],
                "related_save_ids": [],
            },
            {
                "decision_id": "decision-0102",
                "episode_id": "ep_t50_unsettled",
                "turn": 41,
                "trigger": "expansion settler action 123",
                "selected_action": "move toward best settle candidate",
                "outcome": "CAPTURE_MOVE|68,36|BLOCKED",
                "related_tool_call_ids": ["tool-0002"],
                "related_state_snapshot_ids": ["state-0051-T0050-t50_final"],
                "related_save_ids": [],
            },
        ]
    )
    write_jsonl(episode / "derived" / "decision_atoms.jsonl", decisions)

    labeler.generate_candidates("ep_t50_unsettled", workspace=tmp_path, session_id="sess-t50")

    candidates = labeler.read_jsonl(episode / "review" / "candidates.jsonl")
    unsettled = next(
        candidate for candidate in candidates if "settler 扩张路径" in candidate["title"]
    )
    assert unsettled["confidence"] == "medium"
    assert unsettled["capability_category"] == "planning"


def test_t50_candidate_generation_detects_idle_builder_overproduction(tmp_path):
    episode = make_episode(
        tmp_path,
        "ep_t50_builders",
        observation_mode="t50_observation",
        requested_turns=50,
        actual_turns=50,
        final_turn=50,
    )
    write_json(
        episode / "raw" / "civ6_states" / "state-0051-T0050-t50_final.json",
        {
            "snapshot_id": "state-0051-T0050-t50_final",
            "episode_id": "ep_t50_builders",
            "turn": 50,
            "label": "t50_final",
            "overview": {"turn": 50, "num_cities": 3, "num_units": 6},
            "units": [
                {"unit_type": "UNIT_BUILDER"},
                {"unit_type": "UNIT_BUILDER"},
                {"unit_type": "UNIT_BUILDER"},
            ],
        },
    )
    decisions = labeler.read_jsonl(episode / "derived" / "decision_atoms.jsonl")
    tool_calls = labeler.read_jsonl(episode / "raw" / "tool_calls.jsonl")
    for index in range(3):
        tool_calls.append(
            {
                "tool_call_id": f"tool-builder-{index}",
                "episode_id": "ep_t50_builders",
                "turn": 44 + index,
                "tool": "unit_action",
                "success": True,
                "result_raw": "SKIPPED",
            }
        )
        decisions.append(
            {
                "decision_id": f"decision-builder-{index}",
                "episode_id": "ep_t50_builders",
                "turn": 44 + index,
                "trigger": f"unit action review UNIT_BUILDER {index}",
                "selected_action": "skip",
                "outcome": "SKIPPED",
                "related_tool_call_ids": [f"tool-builder-{index}"],
                "related_state_snapshot_ids": ["state-0051-T0050-t50_final"],
                "related_save_ids": [],
            }
        )
    write_jsonl(episode / "raw" / "tool_calls.jsonl", tool_calls)
    write_jsonl(episode / "derived" / "decision_atoms.jsonl", decisions)

    labeler.generate_candidates("ep_t50_builders", workspace=tmp_path, session_id="sess-t50")

    candidates = labeler.read_jsonl(episode / "review" / "candidates.jsonl")
    builder = next(candidate for candidate in candidates if "builder 过量" in candidate["title"])
    assert builder["confidence"] == "medium"
    assert builder["capability_category"] == "planning"


def test_t50_candidate_generation_detects_city_count_regression(tmp_path):
    episode = make_episode(
        tmp_path,
        "ep_t50_city_regression",
        observation_mode="t50_observation",
        requested_turns=50,
        actual_turns=50,
        final_turn=50,
    )
    write_json(
        episode / "raw" / "civ6_states" / "state-0035-T0035-turn_start_35.json",
        {
            "snapshot_id": "state-0035-T0035-turn_start_35",
            "episode_id": "ep_t50_city_regression",
            "turn": 35,
            "label": "turn_start_35",
            "overview": {"turn": 35, "num_cities": 3, "num_units": 4},
            "units": [],
        },
    )
    write_json(
        episode / "raw" / "civ6_states" / "state-0051-T0050-t50_final.json",
        {
            "snapshot_id": "state-0051-T0050-t50_final",
            "episode_id": "ep_t50_city_regression",
            "turn": 50,
            "label": "t50_final",
            "overview": {"turn": 50, "num_cities": 2, "num_units": 4},
            "units": [],
        },
    )

    labeler.generate_candidates(
        "ep_t50_city_regression", workspace=tmp_path, session_id="sess-t50"
    )

    candidates = labeler.read_jsonl(episode / "review" / "candidates.jsonl")
    regression = next(candidate for candidate in candidates if "城市数回落" in candidate["title"])
    assert regression["confidence"] == "medium"
    assert regression["capability_category"] == "planning"


def test_label_page_supports_batch_card_review(tmp_path):
    make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path, session_id="sess-test")
    candidates = labeler.read_jsonl(tmp_path / "episodes" / "ep_short" / "review" / "candidates.jsonl")

    page = labeler.label_page(candidates, "ep_short")

    assert 'action="/confirm-batch"' in page
    assert "保存所有非 skip 项" in page
    assert "只保存这条" in page
    assert f'name="action__{candidates[0]["candidate_id"]}"' in page
    assert "skip / 不改这条" in page


def test_apply_confirmation_creates_formal_failures_and_one_to_one_seeds(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path, session_id="sess-test")
    review = episode / "review"
    candidates = labeler.read_jsonl(review / "candidates.jsonl")
    planning = next(c for c in candidates if c["capability_category"] == "planning")
    rejected = next(c for c in candidates if c["candidate_id"] != planning["candidate_id"])
    confirmation = review / "confirmation" / "confirmation.jsonl"
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

    failures = labeler.read_jsonl(review / "failures.jsonl")
    seeds = labeler.read_jsonl(review / "regression_seeds.jsonl")
    review_html = (review / "review.html").read_text(encoding="utf-8")
    summary = labeler.read_json(review / "review_summary.json")
    formal_text = (review / "failures.jsonl").read_text(encoding="utf-8") + (
        review / "regression_seeds.jsonl"
    ).read_text(encoding="utf-8")

    assert result["failures"] == 1
    assert len(failures) == 1
    assert len(seeds) == 1
    assert seeds[0]["source_failure_ids"] == [failures[0]["failure_id"]]
    assert seeds[0]["not_runnable_in_review"] is True
    assert seeds[0]["manual_review_required"] is True
    assert seeds[0]["asset_change_allowed"] is False
    assert failures[0]["human_status"] == "confirmed"
    assert failures[0]["claim_scope"] == "local_episode_fragment"
    assert failures[0]["not_a_long_horizon_conclusion"] is True
    assert failures[0]["not_evidence_for_asset_change"] is True
    assert failures[0]["requires_t50_or_multi_episode_followup"] is True
    assert labeler.CAVEAT_TEXT in review_html
    assert summary["one_failure_to_one_seed"] is True
    assert "rerun_command" not in formal_text
    assert "suggested_fix" not in formal_text


def test_apply_confirmation_accepts_utf8_bom_jsonl(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path)
    review = episode / "review"
    candidate = labeler.read_jsonl(review / "candidates.jsonl")[0]
    confirmation = review / "confirmation" / "confirmation.jsonl"
    confirmation.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "candidate_id": candidate["candidate_id"],
        "action": "accept",
        "modified_fields": {},
        "reviewer": "coverage-test",
        "reviewer_note": "PowerShell-created UTF-8 BOM JSONL should be accepted.",
        "reviewed_at": "2026-05-21T00:00:00+08:00",
    }
    confirmation.write_text(
        json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8-sig",
    )

    result = labeler.apply_confirmation("ep_short", confirmation, workspace=tmp_path)

    assert result["failures"] == 1
    assert labeler.read_jsonl(review / "failures.jsonl")


def test_apply_rejects_forbidden_confirmation_fields(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path)
    review = episode / "review"
    candidate = labeler.read_jsonl(review / "candidates.jsonl")[0]
    confirmation = review / "confirmation" / "confirmation.jsonl"
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

    with pytest.raises(labeler.ReviewError):
        labeler.apply_confirmation("ep_short", confirmation, workspace=tmp_path)

    assert not (review / "failures.jsonl").exists()
    assert not (review / "regression_seeds.jsonl").exists()


def test_all_rejected_confirmation_keeps_empty_formal_outputs(tmp_path):
    episode = make_episode(tmp_path)
    labeler.generate_candidates("ep_short", workspace=tmp_path)
    review = episode / "review"
    candidates = labeler.read_jsonl(review / "candidates.jsonl")
    confirmation = review / "confirmation" / "confirmation.jsonl"
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
    assert labeler.read_jsonl(review / "failures.jsonl") == []
    assert labeler.read_jsonl(review / "regression_seeds.jsonl") == []
    review = (review / "review.html").read_text(encoding="utf-8")
    assert "No formal failures yet" in review

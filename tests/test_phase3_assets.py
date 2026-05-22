import json
from pathlib import Path

import pytest

from codex_hl.phase3 import assets


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_asset_library(
    root: Path,
    *,
    bad_hash: bool = False,
    omit_ledger: bool = False,
) -> Path:
    body = "# Test asset\n\nRules.\n"
    content_path = root / "assets" / "test.md"
    content_path.parent.mkdir(parents=True, exist_ok=True)
    content_path.write_text(body, encoding="utf-8")
    content_hash = assets.sha256_file(content_path)
    write_json(
        root / "catalog.json",
        {
            "schema_version": 1,
            "assets": [
                {
                    "asset_id": "prompt.test",
                    "asset_type": "prompt",
                    "version": "1.0.0",
                    "content_path": "assets/test.md",
                    "content_sha256": "0" * 64 if bad_hash else content_hash,
                    "source_refs": ["tests"],
                    "applicability": ["unit test"],
                    "risk_level": "low",
                    "rollback_path": "assets/test.md",
                    "capability_dimensions": ["planning"],
                    "status": "active",
                }
            ],
        },
    )
    if not omit_ledger:
        write_jsonl(
            root / "change_ledger.jsonl",
            [
                {
                    "ledger_id": "ledger-test",
                    "event_type": "initial_migration",
                    "recorded_at": "2026-05-21T00:00:00+08:00",
                    "asset_id": "prompt.test",
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
    else:
        write_jsonl(root / "change_ledger.jsonl", [])
    return root


def write_state(workspace: Path, episode_id: str, *, cities: int, techs: int, civics: int) -> None:
    write_json(
        workspace
        / "episodes"
        / episode_id
        / "raw"
        / "civ6_states"
        / "state-0051-T0051-t50_final.json",
        {
            "snapshot_id": f"{episode_id}-final",
            "episode_id": episode_id,
            "turn": 51,
            "overview": {
                "num_cities": cities,
                "science_yield": 3.5 + techs,
                "culture_yield": 1.5 + civics,
                "current_research": "货币",
                "current_civic": "国家劳动力",
            },
            "research_civic": {
                "completed_tech_count": techs,
                "completed_civic_count": civics,
                "current_research": "货币",
                "current_civic": "国家劳动力",
            },
        },
    )


def test_real_phase3_asset_library_checks():
    result = assets.check_asset_library()

    assert result["ok"] is True
    assert "prompt.default_boundary" in result["asset_ids"]
    assert result["active_asset_count"] >= 7


def test_validate_catalog_rejects_sha_mismatch(tmp_path):
    root = make_asset_library(tmp_path / "asset_root", bad_hash=True)

    with pytest.raises(assets.Phase3AssetError, match="content_sha256 mismatch"):
        assets.validate_catalog(root)


def test_validate_catalog_rejects_missing_ledger_coverage(tmp_path):
    root = make_asset_library(tmp_path / "asset_root", omit_ledger=True)

    with pytest.raises(assets.Phase3AssetError, match="change_ledger missing"):
        assets.validate_catalog(root)


def test_active_asset_snapshot_uses_validated_catalog(tmp_path):
    root = make_asset_library(tmp_path / "asset_root")

    snapshot = assets.active_asset_snapshot(root)

    assert snapshot["asset_count"] == 1
    assert snapshot["active_assets"][0]["asset_id"] == "prompt.test"
    assert snapshot["active_assets"][0]["content_sha256"] == assets.sha256_file(root / "assets" / "test.md")


def test_compare_t50_metrics_is_candidate_evidence_only(tmp_path):
    write_state(tmp_path, "baseline", cities=1, techs=5, civics=3)
    write_state(tmp_path, "candidate", cities=2, techs=7, civics=4)

    result = assets.compare_t50_metrics(
        "baseline",
        "candidate",
        workspace=tmp_path,
    )

    assert result["auto_merge_allowed"] is False
    assert result["claim_scope"] == "candidate_evidence_only"
    assert result["delta"]["num_cities"] == 1
    assert result["delta"]["completed_tech_count"] == 2
    assert result["delta"]["completed_civic_count"] == 1

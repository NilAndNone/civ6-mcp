import json
import shutil
from pathlib import Path

from codex_hl.evidence.store import rebuild_episode_db
from codex_hl.reports import acceptance


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def make_episode(
    workspace: Path,
    episode_id: str,
    *,
    cities: int,
    techs: int,
    civics: int,
    candidate_runtime: dict | None = None,
) -> None:
    episode = workspace / "episodes" / episode_id
    write_json(
        episode / "header.json",
        {
            "episode_id": episode_id,
            "candidate_runtime": candidate_runtime or {"status": "not_supplied", "runtime_effects": []},
        },
    )
    write_json(
        episode / "derived" / "report_pack.json",
        {
            "episode_id": episode_id,
            "run": {"actual_turns": 50, "final_turn": 51},
            "evidence_status": {
                "tool_mcp_raw_records": {"status": "PASS"},
                "turn_state_snapshots": {"status": "PASS"},
                "decision_records": {"status": "PASS"},
                "save_links": {"status": "PASS"},
            },
        },
    )
    write_json(
        episode / "raw" / "civ6_states" / "state-0051-T0051-t50_final.json",
        {
            "episode_id": episode_id,
            "turn": 51,
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
    write_jsonl(
        episode / "derived" / "decision_atoms.jsonl",
        [
            {
                "decision_id": "decision-0001",
                "selected_action": "UNIT_SETTLER" if candidate_runtime else "UNIT_BUILDER",
                "execution": {"action": "set_city_production"},
                "strategy_context": {
                    "candidate_id": candidate_runtime.get("candidate_id")
                }
                if candidate_runtime
                else {},
            }
        ],
    )


def test_build_acceptance_report_passes_with_candidate_runtime_evidence(tmp_path):
    package = tmp_path / "candidate.json"
    package_data = {
        "candidate_id": "impr_test",
        "source_episode_ids": ["source_ep"],
        "source_failure_ids": ["fail_test"],
    }
    write_json(package, package_data)
    package_sha = acceptance.strategy_registry.sha256_file(package)
    write_jsonl(
        tmp_path / "episodes" / "source_ep" / "review" / "failures.jsonl",
        [{"failure_id": "fail_test"}],
    )

    baseline = [f"baseline_{i}" for i in range(5)]
    candidate = [f"candidate_{i}" for i in range(5)]
    for episode_id in baseline:
        make_episode(tmp_path, episode_id, cities=1, techs=2, civics=1)
    runtime = {
        "status": "applied",
        "candidate_id": "impr_test",
        "package_sha256": package_sha,
        "runtime_effects": ["expansion_pressure"],
    }
    for episode_id in candidate:
        make_episode(tmp_path, episode_id, cities=2, techs=3, civics=2, candidate_runtime=runtime)

    report = acceptance.build_acceptance_report(
        workspace=tmp_path,
        output_dir=tmp_path / "out",
        baseline_episodes=baseline,
        candidate_episodes=candidate,
        candidate_package=package,
    )

    assert report["ok"] is True
    assert report["metric_comparison"]["improved_metrics"]
    assert Path(report["paths"]["json"]).exists()
    assert Path(report["paths"]["html"]).exists()


def test_acceptance_reads_db_only_observation_episodes(tmp_path):
    package = tmp_path / "candidate.json"
    package_data = {
        "candidate_id": "impr_db",
        "source_episode_ids": ["source_ep"],
        "source_failure_ids": ["fail_db"],
    }
    write_json(package, package_data)
    package_sha = acceptance.strategy_registry.sha256_file(package)
    write_jsonl(
        tmp_path / "episodes" / "source_ep" / "review" / "failures.jsonl",
        [{"failure_id": "fail_db"}],
    )
    make_episode(tmp_path, "baseline_db", cities=1, techs=2, civics=1)
    runtime = {
        "status": "applied",
        "candidate_id": "impr_db",
        "package_sha256": package_sha,
        "runtime_effects": ["expansion_pressure"],
    }
    make_episode(tmp_path, "candidate_db", cities=2, techs=3, civics=2, candidate_runtime=runtime)
    for episode_id in ["baseline_db", "candidate_db"]:
        episode = tmp_path / "episodes" / episode_id
        rebuild_episode_db(episode)
        for child in episode.iterdir():
            if child.name == "episode.db":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    report = acceptance.build_acceptance_report(
        workspace=tmp_path,
        output_dir=tmp_path / "out",
        baseline_episodes=["baseline_db"],
        candidate_episodes=["candidate_db"],
        candidate_package=package,
        required_sample_size=1,
    )

    assert report["ok"] is True

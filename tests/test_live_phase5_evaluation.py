from __future__ import annotations

import json
from pathlib import Path

from codex_hl.evidence.store import EpisodeStore
from codex_hl.live import evaluation
from codex_hl.live.gateway import ActionRequest
from codex_hl.live.ledger import EpisodeLedger
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import normalize_turn_plan


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def live_context(
    *,
    episode_id: str,
    turn: int,
    cities: int,
    science: float = 4.0,
    culture: float = 2.0,
    techs: int = 3,
    civics: int = 2,
    era_score: int = 5,
    threats: list[dict] | None = None,
    loyalty_per_turn: float = 1.0,
) -> dict:
    return {
        "episode_id": episode_id,
        "turn": turn,
        "branch_id": "b000",
        "context_hash": f"sha256:{episode_id}",
        "overview": {
            "turn": turn,
            "num_cities": cities,
            "total_population": cities + 2,
            "science_yield": science,
            "culture_yield": culture,
            "gold": 50,
            "gold_per_turn": 5,
            "score": cities * 10,
            "era_score": era_score,
            "era_golden_threshold": 19,
        },
        "research_civic": {
            "completed_tech_count": techs,
            "completed_civic_count": civics,
            "current_research": "TECH_WRITING",
            "current_civic": "CIVIC_CRAFTSMANSHIP",
        },
        "cities": [
            [
                {
                    "city_id": index + 1,
                    "name": f"City {index + 1}",
                    "loyalty": 100 - index * 5,
                    "loyalty_per_turn": loyalty_per_turn,
                }
                for index in range(cities)
            ]
        ],
        "units": [],
        "notifications": [],
        "threats": threats or [],
    }


def make_live_episode(
    workspace: Path,
    episode_id: str,
    *,
    final_turn: int = 21,
    cities: int = 2,
    verifier_statuses: list[str] | None = None,
    unplanned: bool = False,
    rejected_error: str | None = None,
    threats: list[dict] | None = None,
    loyalty_per_turn: float = 1.0,
) -> None:
    root = workspace / "episodes" / episode_id
    store = EpisodeStore(root, episode_id)
    store.put_episode_header(
        {
            "episode_id": episode_id,
            "workflow": "live-json-plan",
            "runner": "live-json-plan",
            "requested_turns": 20,
        },
        workflow="live-json-plan",
        requested_turns=20,
    )
    store.close()
    plan_store = LivePlanStore.for_episode_root(root, episode_id)
    plan_store.start_episode(
        save_name="test 1",
        target_turns=20,
        mode="live_strict",
        runner="live-json-plan",
    )
    context = live_context(
        episode_id=episode_id,
        turn=final_turn,
        cities=cities,
        threats=threats,
        loyalty_per_turn=loyalty_per_turn,
    )
    plan_store.record_turn_context(
        turn=final_turn,
        branch_id="b000",
        context_hash=context["context_hash"],
        payload=context,
    )
    ledger = EpisodeLedger.for_episode_root(root, episode_id)
    for index, status in enumerate(verifier_statuses or ["PASS"], start=1):
        tool = "end_turn" if status == "FAIL" else "set_research"
        request = ActionRequest(
            source="mcp",
            tool_name=tool,
            args={"index": index},
            mutation_level=MutationLevel.L4_BOUNDARY_RECOVERY
            if tool == "end_turn"
            else MutationLevel.L2_LOW_GAME_MUTATION,
            episode_id=episode_id,
            turn=final_turn - 1,
            plan_id=f"p{index:04d}",
            step_id=f"s{index:04d}",
            context_hash=context["context_hash"],
        )
        ledger.append_event(
            event_type="ACTION_FINISHED",
            request=request,
            mode="live_strict",
            allowed=True,
            status="executed",
            unplanned_mutation=unplanned,
            result="Turn did not advance" if status == "FAIL" else "OK",
            verifier_status=status,
            payload={
                "verifier": {
                    "status": status,
                    "objective_delta": {"turn_delta": 0 if status == "FAIL" else 1},
                    "reason": "turn did not advance" if status == "FAIL" else "ok",
                }
            },
        )
    if rejected_error:
        request = ActionRequest(
            source="mcp",
            tool_name="unit_action",
            args={"unit_id": 1, "action": "move"},
            mutation_level=MutationLevel.L3_HIGH_GAME_MUTATION,
            episode_id=episode_id,
            turn=final_turn,
            plan_id="p_reject",
            step_id="s_reject",
            context_hash=context["context_hash"],
        )
        ledger.append_event(
            event_type="ACTION_REJECTED",
            request=request,
            mode="live_strict",
            allowed=False,
            status="rejected",
            unplanned_mutation=False,
            error=rejected_error,
        )


def make_legacy_episode(
    workspace: Path,
    episode_id: str,
    *,
    turn: int = 20,
    cities: int = 1,
    science: float = 3.0,
    culture: float = 1.0,
    techs: int = 2,
    civics: int = 1,
    era_score: int = 4,
) -> None:
    root = workspace / "episodes" / episode_id
    write_json(
        root / "header.json",
        {
            "episode_id": episode_id,
            "workflow": "observation",
            "runner_kind": "legacy-baseline",
            "requested_turns": turn,
        },
    )
    write_json(
        root / "raw" / "civ6_states" / f"state-{turn:04d}-T{turn:04d}-final.json",
        {
            "turn": turn,
            "overview": {
                "turn": turn,
                "num_cities": cities,
                "total_population": cities + 1,
                "science_yield": science,
                "culture_yield": culture,
                "gold": 20,
                "gold_per_turn": 2,
                "score": cities * 8,
                "era_score": era_score,
                "era_golden_threshold": 19,
            },
            "research_civic": {
                "completed_tech_count": techs,
                "completed_civic_count": civics,
            },
            "cities": [[{"city_id": 1, "name": "Capital"}]],
        },
    )


def leave_live_step_executing(workspace: Path, episode_id: str) -> None:
    root = workspace / "episodes" / episode_id
    store = LivePlanStore.for_episode_root(root, episode_id)
    state = store.replay()
    context = next(iter(state.contexts.values()))
    turn = int(context["turn"])
    branch_id = str(context["branch_id"])
    context_hash = str(context["context_hash"])
    store.submit_plan(
        normalize_turn_plan(
            {
                "episode_id": episode_id,
                "plan_id": "plan_unfinished",
                "turn": turn,
                "branch_id": branch_id,
                "context_hash": context_hash,
                "steps": [
                    {
                        "step_id": "s_unfinished",
                        "tool": "set_research",
                        "args": {"tech_or_civic": "TECH_POTTERY", "category": "tech"},
                        "allowed_mutation_level": "L2",
                        "postconditions": [],
                    }
                ],
            }
        )
    )
    store.arm_step("plan_unfinished", "s_unfinished")
    store.mark_step_executing(
        "plan_unfinished",
        "s_unfinished",
        request_id="act-unfinished",
    )


def test_extract_live_phase5_metrics_from_ledger_and_context(tmp_path: Path) -> None:
    make_live_episode(
        tmp_path,
        "live_ep",
        final_turn=21,
        cities=2,
        verifier_statuses=["PASS", "FAIL"],
    )

    metrics = evaluation.extract_episode_metrics("live_ep", workspace=tmp_path, target_turns=20)

    assert metrics["turn_reached"] is True
    assert metrics["objective_metrics"]["num_cities"] == 2
    assert metrics["objective_metrics"]["city_retention_ok"] is True
    assert metrics["objective_metrics"]["completed_tech_count"] == 3
    assert metrics["objective_metrics_complete"] is True
    assert metrics["verifier"]["pass_rate"] == 0.5
    assert metrics["recovery_count"] == 1
    assert metrics["stuck_turn_count"] == 1
    assert metrics["failures"][0]["taxonomy"] == "recovery_protocol_failure"


def test_phase5_gate_uses_multi_episode_objective_delta_not_self_eval(tmp_path: Path) -> None:
    make_legacy_episode(tmp_path, "baseline", cities=1, science=3.0, culture=1.0)
    make_live_episode(tmp_path, "live_a", cities=2, verifier_statuses=["PASS", "PASS"])
    make_live_episode(tmp_path, "live_b", cities=3, verifier_statuses=["PASS", "PASS"])
    make_live_episode(tmp_path, "live_c", cities=4, verifier_statuses=["PASS", "PASS"])

    report = evaluation.build_phase5_report(
        workspace=tmp_path,
        baseline_episodes=["baseline"],
        candidate_episodes=["live_a", "live_b", "live_c"],
        target_turns=20,
        output_path=tmp_path / "phase5.json",
    )

    gate = report["strategy_candidate_gate"]
    assert gate["allowed"] is True
    assert gate["claim_basis"] == "objective_ledger_metrics_only"
    assert gate["gates"]["not_codex_self_eval"] is True
    assert gate["gate_parameters"]["min_candidate_episodes"] == 3
    assert report["aggregate"]["delta"]["num_cities"] == 2
    assert (tmp_path / "phase5.json").exists()
    assert (tmp_path / "phase5.md").exists()


def test_phase5_gate_rejects_single_live_episode(tmp_path: Path) -> None:
    make_legacy_episode(tmp_path, "baseline")
    make_live_episode(tmp_path, "live_a", cities=2, verifier_statuses=["PASS"])

    report = evaluation.build_phase5_report(
        workspace=tmp_path,
        baseline_episodes=["baseline"],
        candidate_episodes=["live_a"],
        target_turns=20,
    )

    assert report["strategy_candidate_gate"]["allowed"] is False
    assert report["strategy_candidate_gate"]["gates"]["multi_episode_reproduced"] is False


def test_phase5_gate_rejects_unverified_live_steps(tmp_path: Path) -> None:
    make_legacy_episode(tmp_path, "baseline", cities=1)
    make_live_episode(tmp_path, "live_a", cities=2, verifier_statuses=["PASS"])
    make_live_episode(tmp_path, "live_b", cities=2, verifier_statuses=["PASS"])
    make_live_episode(tmp_path, "live_c", cities=2, verifier_statuses=["PASS"])
    leave_live_step_executing(tmp_path, "live_b")

    report = evaluation.build_phase5_report(
        workspace=tmp_path,
        baseline_episodes=["baseline"],
        candidate_episodes=["live_a", "live_b", "live_c"],
        target_turns=20,
    )

    live_b = next(row for row in report["candidate_episodes"] if row["episode_id"] == "live_b")
    assert live_b["step_status_counts"]["EXECUTING"] == 1
    assert live_b["unverified_step_count"] == 1
    assert report["strategy_candidate_gate"]["allowed"] is False
    assert report["strategy_candidate_gate"]["gates"]["live_strict_no_unverified_steps"] is False


def test_phase5_gate_rejects_codex_self_eval_provenance() -> None:
    baseline = {
        "evidence_kind": "legacy-baseline",
        "objective_metrics_complete": True,
        "failures": [],
        "provenance": {
            "objective_metrics_source": "legacy_state_snapshot",
            "codex_self_eval_used": False,
        },
    }
    candidate = {
        "evidence_kind": "live",
        "objective_metrics_complete": True,
        "unplanned_mutation_count": 0,
        "unverified_step_count": 0,
        "verifier": {"total": 1, "inconclusive": 0},
        "evidence": {"live_plan_events_rows": 1},
        "failures": [],
        "provenance": {
            "objective_metrics_source": "live_plan_context",
            "objective_metrics_path": "raw/live_plan_events.jsonl",
            "codex_self_eval_used": False,
        },
    }
    bad_candidate = {
        **candidate,
        "provenance": {
            **candidate["provenance"],
            "codex_self_eval_used": True,
        },
    }

    gate = evaluation.evaluate_strategy_candidate_gate(
        baseline_rows=[baseline],
        candidate_rows=[candidate, bad_candidate, candidate],
        comparison_delta={"num_cities": 1},
    )

    assert gate["allowed"] is False
    assert gate["gates"]["not_codex_self_eval"] is False


def test_phase5_gate_requires_target_two_cities_and_clean_live_strict_steps() -> None:
    baseline = {
        "evidence_kind": "legacy-baseline",
        "turn_reached": True,
        "objective_metrics_complete": True,
        "objective_metrics": {"num_cities": 2},
        "failures": [],
        "provenance": {
            "objective_metrics_source": "legacy_state_snapshot",
            "codex_self_eval_used": False,
        },
    }
    clean_candidate = {
        "evidence_kind": "live",
        "turn_reached": True,
        "objective_metrics_complete": True,
        "objective_metrics": {"num_cities": 2},
        "unplanned_mutation_count": 0,
        "unverified_step_count": 0,
        "verifier": {"total": 1, "inconclusive": 0},
        "evidence": {"live_plan_events_rows": 1},
        "failures": [],
        "provenance": {
            "objective_metrics_source": "live_plan_context",
            "objective_metrics_path": "raw/live_plan_events.jsonl",
            "codex_self_eval_used": False,
        },
    }
    dirty_candidate = {
        **clean_candidate,
        "turn_reached": False,
        "objective_metrics": {"num_cities": 1},
        "unplanned_mutation_count": 1,
        "unverified_step_count": 1,
    }

    gate = evaluation.evaluate_strategy_candidate_gate(
        baseline_rows=[baseline],
        candidate_rows=[clean_candidate, dirty_candidate, clean_candidate],
        comparison_delta={"num_cities": 1},
    )

    assert gate["allowed"] is False
    assert gate["gates"]["target_turn_reached"] is False
    assert gate["gates"]["candidate_min_two_cities"] is False
    assert gate["gates"]["live_strict_unplanned_mutation_zero"] is False
    assert gate["gates"]["live_strict_no_unverified_steps"] is False


def test_phase5_objective_metrics_capture_loyalty_and_threat_pressure(tmp_path: Path) -> None:
    make_live_episode(
        tmp_path,
        "live_risk",
        cities=2,
        verifier_statuses=["PASS"],
        threats=[{"kind": "barbarian", "distance": 3}],
        loyalty_per_turn=-2.0,
    )

    metrics = evaluation.extract_episode_metrics("live_risk", workspace=tmp_path, target_turns=20)

    objective = metrics["objective_metrics"]
    assert objective["threat_pressure"] == 1
    assert objective["min_city_loyalty"] == 95
    assert objective["loyalty_risk_city_count"] == 2


def test_phase5_failure_taxonomy_classifies_rejections(tmp_path: Path) -> None:
    make_legacy_episode(tmp_path, "baseline")
    make_live_episode(
        tmp_path,
        "live_a",
        verifier_statuses=["PASS"],
        rejected_error="args mismatch with armed step",
    )
    make_live_episode(
        tmp_path,
        "live_b",
        verifier_statuses=["PASS"],
        rejected_error="FireTuner timeout while reading post-state",
    )

    report = evaluation.build_phase5_report(
        workspace=tmp_path,
        baseline_episodes=["baseline"],
        candidate_episodes=["live_a", "live_b"],
        target_turns=20,
    )

    assert report["failure_taxonomy"]["args_mismatch"] == 1
    assert report["failure_taxonomy"]["civ6_firetuner_instability"] == 1
    assert report["strategy_candidate_gate"]["gates"]["failure_taxonomy_complete"] is True


def test_phase5_failure_taxonomy_classifies_turn_delta_conflict() -> None:
    taxonomy = evaluation.classify_failure(
        {
            "event_type": "ACTION_FINISHED",
            "tool": "end_turn",
            "verifier_status": "INCONCLUSIVE",
            "payload": {
                "verifier": {
                    "reason": "state/result turn delta conflict",
                    "objective_delta": {
                        "state_turn_delta": 2,
                        "result_turn_delta": 0,
                    },
                }
            },
        }
    )

    assert taxonomy == "verifier_too_strict"

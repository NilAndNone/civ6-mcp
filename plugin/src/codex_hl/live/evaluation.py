"""Phase 5 live evaluation and governance-gate reporting.

This module consumes completed evidence only. It never starts Civ6, replays a
save, executes MCP tools, or mutates strategy assets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from codex_hl.evidence.store import EpisodeReader, EpisodeStoreError
from codex_hl.live.ledger import LIVE_EVENTS_LOGICAL_PATH, now_iso
from codex_hl.live.plan_store import LIVE_PLAN_EVENTS_LOGICAL_PATH, LivePlanStore
from codex_hl.strategy.registry import NUMERIC_T50_METRICS


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
WORKFLOW_NAME = "Live Phase 5 Evaluation"

FAILURE_TAXONOMY = {
    "state_representation_gap",
    "invalid_plan_schema",
    "stale_context",
    "args_mismatch",
    "tool_bug",
    "civ6_firetuner_instability",
    "verifier_too_strict",
    "model_strategic_error",
    "recovery_protocol_failure",
    "evidence_export_failure",
}

OBJECTIVE_METRICS = [
    "final_turn",
    "num_cities",
    "total_population",
    "science_yield",
    "culture_yield",
    "gold",
    "gold_per_turn",
    "score",
    "completed_tech_count",
    "completed_civic_count",
    "era_score",
    "golden_age_gap",
    "military_strength",
    "barb_threat_count",
]

REQUIRED_GATE_METRICS = [
    "final_turn",
    "num_cities",
    "science_yield",
    "culture_yield",
    "completed_tech_count",
    "completed_civic_count",
    "era_score",
]

COMPARISON_METRICS = [
    "num_cities",
    "completed_tech_count",
    "completed_civic_count",
    "science_yield",
    "culture_yield",
    "era_score",
]


class LiveEvaluationError(RuntimeError):
    """User-facing Phase 5 evaluation error."""


def json_dumps(data: Any, *, indent: int | None = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(data) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        if parsed.is_integer():
            return int(parsed)
        return parsed
    return None


def _clean_number(value: Any) -> Any:
    number = _number(value)
    if isinstance(number, float) and number.is_integer():
        return int(number)
    return number


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _flatten_dict_rows(rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
        elif isinstance(row, list):
            result.extend(item for item in row if isinstance(item, dict))
    return result


def _read_json(reader: EpisodeReader, logical_path: str) -> dict[str, Any]:
    try:
        return reader.read_json(logical_path)
    except (FileNotFoundError, EpisodeStoreError, json.JSONDecodeError):
        return {}


def _read_jsonl_with_issues(
    reader: EpisodeReader,
    logical_path: str,
    evidence_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        return reader.read_jsonl(logical_path)
    except (FileNotFoundError, EpisodeStoreError, json.JSONDecodeError) as exc:
        evidence_issues.append(
            {
                "taxonomy": "evidence_export_failure",
                "logical_path": logical_path,
                "error": str(exc),
            }
        )
        return []


def _episode_reader(workspace: Path, episode_id: str) -> EpisodeReader:
    episode_root = workspace / "episodes" / episode_id
    if not episode_root.exists():
        raise LiveEvaluationError(f"episode not found: {episode_root}")
    return EpisodeReader(episode_root)


def _is_live_episode(reader: EpisodeReader, header: dict[str, Any]) -> bool:
    workflow = str(header.get("workflow") or "").lower()
    runner = str(header.get("runner_kind") or header.get("runner") or "").lower()
    return (
        "live" in workflow
        or "live" in runner
        or reader.has_artifact(LIVE_PLAN_EVENTS_LOGICAL_PATH)
        or reader.has_artifact(LIVE_EVENTS_LOGICAL_PATH)
    )


def _latest_live_context(
    workspace: Path,
    episode_id: str,
    evidence_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    episode_root = workspace / "episodes" / episode_id
    try:
        state = LivePlanStore.for_episode_root(episode_root, episode_id).replay()
    except (OSError, json.JSONDecodeError, EpisodeStoreError) as exc:
        evidence_issues.append(
            {
                "taxonomy": "evidence_export_failure",
                "logical_path": LIVE_PLAN_EVENTS_LOGICAL_PATH,
                "error": str(exc),
            }
        )
        return {}
    contexts: list[dict[str, Any]] = []
    for payload in state.contexts.values():
        context = _safe_dict(payload.get("context"))
        if context:
            contexts.append(context)
    if not contexts:
        return {}
    return max(contexts, key=lambda row: int(_number(row.get("turn")) or 0))


def _latest_legacy_state(reader: EpisodeReader) -> tuple[str | None, dict[str, Any]]:
    states: list[tuple[int, str, dict[str, Any]]] = []
    for logical_path, state in reader.state_rows():
        turn = _number(state.get("turn"))
        if isinstance(turn, (int, float)):
            states.append((int(turn), str(logical_path), state))
    if not states:
        return None, {}
    preferred = [row for row in states if "t50_final" in Path(row[1]).name or "t20_final" in Path(row[1]).name]
    _, logical_path, state = max(preferred or states, key=lambda row: (row[0], row[1]))
    return logical_path, state


def _count_barb_threats(context: dict[str, Any], live_events: list[dict[str, Any]]) -> int:
    notifications = _safe_list(context.get("notifications"))
    count = 0
    for item in notifications:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get(key) or "") for key in ("type_name", "message", "resolution_hint")).lower()
        if "barbarian" in text or "threat" in text:
            count += 1
    if count:
        return count
    last_result = ""
    for row in reversed(live_events):
        payload = _safe_dict(row.get("payload"))
        result = payload.get("result")
        if isinstance(result, str) and result:
            last_result = result.lower()
            break
    return last_result.count("threat:")


def _objective_metrics_from_context(
    context: dict[str, Any],
    *,
    final_turn: int | None,
    live_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    overview = _safe_dict(context.get("overview"))
    research_civic = _safe_dict(context.get("research_civic"))
    cities = _flatten_dict_rows(context.get("cities"))
    city_count = _clean_number(overview.get("num_cities"))
    if city_count is None and cities:
        city_count = len(cities)
    era_score = _clean_number(overview.get("era_score"))
    golden_threshold = _clean_number(overview.get("era_golden_threshold"))
    golden_age_gap = None
    if isinstance(era_score, (int, float)) and isinstance(golden_threshold, (int, float)):
        golden_age_gap = max(0, golden_threshold - era_score)
    return {
        "final_turn": final_turn,
        "num_cities": city_count,
        "total_population": _clean_number(overview.get("total_population")),
        "science_yield": _clean_number(overview.get("science_yield")),
        "culture_yield": _clean_number(overview.get("culture_yield")),
        "gold": _clean_number(overview.get("gold")),
        "gold_per_turn": _clean_number(overview.get("gold_per_turn") or overview.get("gold_income")),
        "score": _clean_number(overview.get("score")),
        "completed_tech_count": _clean_number(research_civic.get("completed_tech_count")),
        "completed_civic_count": _clean_number(research_civic.get("completed_civic_count")),
        "current_research": research_civic.get("current_research") or overview.get("current_research"),
        "current_civic": research_civic.get("current_civic") or overview.get("current_civic"),
        "era_score": era_score,
        "golden_age_gap": golden_age_gap,
        "military_strength": _clean_number(
            overview.get("military_strength")
            or overview.get("military")
            or overview.get("soldiers")
        ),
        "barb_threat_count": _count_barb_threats(context, live_events or []),
    }


def _objective_metrics_from_state(state: dict[str, Any]) -> dict[str, Any]:
    overview = _safe_dict(state.get("overview"))
    research_civic = _safe_dict(state.get("research_civic"))
    final_turn = int(_number(state.get("turn") or overview.get("turn")) or 0)
    context = {
        "overview": overview,
        "research_civic": research_civic,
        "cities": state.get("cities"),
        "notifications": state.get("notifications"),
    }
    return _objective_metrics_from_context(context, final_turn=final_turn)


def _verifier_counts(live_events: list[dict[str, Any]]) -> dict[str, Any]:
    finished = [row for row in live_events if row.get("event_type") == "ACTION_FINISHED"]
    counts = Counter(str(row.get("verifier_status") or "") for row in finished if row.get("verifier_status"))
    total = sum(counts.values())
    passed = counts.get("PASS", 0)
    return {
        "total": total,
        "pass": passed,
        "fail": counts.get("FAIL", 0),
        "inconclusive": counts.get("INCONCLUSIVE", 0),
        "pass_rate": (passed / total) if total else None,
    }


def _step_status_counts(workspace: Path, episode_id: str) -> dict[str, int]:
    try:
        state = LivePlanStore.for_episode_root(
            workspace / "episodes" / episode_id,
            episode_id,
        ).replay()
    except (OSError, json.JSONDecodeError, EpisodeStoreError):
        return {}
    return dict(Counter(step.status.value for step in state.steps.values()))


def _plan_counts(plan_events: list[dict[str, Any]]) -> dict[str, Any]:
    submitted = len([row for row in plan_events if row.get("event_type") == "PLAN_SUBMITTED"])
    invalid = len(
        [
            row
            for row in plan_events
            if str(row.get("event_type") or "").endswith(("REJECTED", "FAILED"))
        ]
    )
    return {
        "submitted": submitted,
        "invalid": invalid,
        "invalid_plan_rate": invalid / (submitted + invalid) if (submitted + invalid) else 0.0,
    }


def _result_turn_delta(row: dict[str, Any]) -> Any:
    verifier = _safe_dict(_safe_dict(row.get("payload")).get("verifier"))
    delta = _safe_dict(verifier.get("objective_delta"))
    return delta.get("turn_delta")


def _stuck_turn_count(live_events: list[dict[str, Any]]) -> int:
    count = 0
    for row in live_events:
        if row.get("event_type") != "ACTION_FINISHED" or row.get("tool") != "end_turn":
            continue
        if row.get("verifier_status") != "PASS" or _result_turn_delta(row) != 1:
            count += 1
    return count


def _error_text(row: dict[str, Any]) -> str:
    payload = _safe_dict(row.get("payload"))
    parts = [
        row.get("event_type"),
        row.get("tool"),
        row.get("status"),
        row.get("verifier_status"),
        payload.get("error"),
        payload.get("error_code"),
        payload.get("result"),
        _safe_dict(payload.get("verifier")).get("reason"),
    ]
    return " ".join(str(part) for part in parts if part is not None).lower()


def classify_failure(row: dict[str, Any]) -> str:
    text = _error_text(row)
    event_type = str(row.get("event_type") or "")
    tool = str(row.get("tool") or "")
    verifier_status = str(row.get("verifier_status") or "")
    if "context_hash" in text or "stale" in text:
        return "stale_context"
    if "args" in text and "match" in text:
        return "args_mismatch"
    if "schema" in text or "duplicate step" in text or "not armed" in text or "plan" in text:
        return "invalid_plan_schema"
    if "firetuner" in text or "connection" in text or "timeout" in text or "port" in text:
        return "civ6_firetuner_instability"
    if event_type == "ACTION_REJECTED":
        return "invalid_plan_schema"
    if event_type == "ACTION_FAILED":
        return "tool_bug"
    if verifier_status == "INCONCLUSIVE":
        return "state_representation_gap"
    if verifier_status == "FAIL" and tool == "end_turn":
        return "recovery_protocol_failure"
    if verifier_status == "FAIL":
        return "model_strategic_error"
    return "tool_bug"


def _failure_rows(
    live_events: list[dict[str, Any]],
    evidence_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in live_events:
        event_type = str(row.get("event_type") or "")
        verifier_status = str(row.get("verifier_status") or "")
        if event_type not in {"ACTION_REJECTED", "ACTION_FAILED"} and verifier_status not in {
            "FAIL",
            "INCONCLUSIVE",
        }:
            continue
        taxonomy = classify_failure(row)
        failures.append(
            {
                "taxonomy": taxonomy,
                "event_id": row.get("event_id"),
                "turn": row.get("turn"),
                "plan_id": row.get("plan_id"),
                "step_id": row.get("step_id"),
                "tool": row.get("tool"),
                "verifier_status": row.get("verifier_status"),
                "reason": _safe_dict(_safe_dict(row.get("payload")).get("verifier")).get("reason")
                or _safe_dict(row.get("payload")).get("error")
                or _safe_dict(row.get("payload")).get("result"),
            }
        )
    for issue in evidence_issues:
        if issue.get("taxonomy") == "evidence_export_failure":
            failures.append(dict(issue))
    return failures


def _metrics_complete(metrics: dict[str, Any], required: list[str] = REQUIRED_GATE_METRICS) -> bool:
    return all(metrics.get(key) is not None for key in required)


def extract_episode_metrics(
    episode_id: str,
    *,
    workspace: Path = WORKSPACE_ROOT,
    target_turns: int | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    reader = _episode_reader(workspace, episode_id)
    header = _read_json(reader, "header.json")
    evidence_issues: list[dict[str, Any]] = []
    live = _is_live_episode(reader, header)
    if live:
        live_events = _read_jsonl_with_issues(reader, LIVE_EVENTS_LOGICAL_PATH, evidence_issues)
        plan_events = _read_jsonl_with_issues(reader, LIVE_PLAN_EVENTS_LOGICAL_PATH, evidence_issues)
        context = _latest_live_context(workspace, episode_id, evidence_issues)
        overview = _safe_dict(context.get("overview"))
        final_turn = int(_number(context.get("turn") or overview.get("turn")) or 0)
        objective = _objective_metrics_from_context(
            context,
            final_turn=final_turn,
            live_events=live_events,
        )
        plan_counts = _plan_counts(plan_events)
        verifier = _verifier_counts(live_events)
        unplanned = len(
            [
                row
                for row in live_events
                if row.get("unplanned_mutation") is True
                and str(row.get("level") or row.get("mutation_level") or "") in {"L2", "L3", "L4", "L5"}
            ]
        )
        target = target_turns or int(_number(header.get("requested_turns")) or 0)
        if not target:
            try:
                episode = LivePlanStore.for_episode_root(
                    workspace / "episodes" / episode_id,
                    episode_id,
                ).get_episode()
                target = episode.target_turns
            except Exception:  # noqa: BLE001 - evaluation should report evidence gaps.
                target = 0
        failures = _failure_rows(live_events, evidence_issues)
        return {
            "episode_id": episode_id,
            "runner_kind": header.get("runner_kind") or header.get("runner") or "live",
            "evidence_kind": "live",
            "target_turns": target,
            "turn_reached": bool(target and final_turn >= target),
            "objective_metrics": objective,
            "objective_metrics_complete": _metrics_complete(objective),
            "unplanned_mutation_count": unplanned,
            "verifier": verifier,
            "recovery_count": verifier["fail"]
            + verifier["inconclusive"]
            + len([row for row in live_events if row.get("event_type") in {"ACTION_FAILED", "ACTION_REJECTED"}]),
            "stuck_turn_count": _stuck_turn_count(live_events),
            "invalid_plan_count": plan_counts["invalid"],
            "invalid_plan_rate": plan_counts["invalid_plan_rate"],
            "plan_count": plan_counts["submitted"],
            "step_status_counts": _step_status_counts(workspace, episode_id),
            "failure_count": len(failures),
            "failures": failures,
            "evidence": {
                "storage_backend": reader.backend,
                "live_events_rows": len(live_events),
                "live_plan_events_rows": len(plan_events),
                "issues": evidence_issues,
            },
        }
    state_path, state = _latest_legacy_state(reader)
    if not state:
        evidence_issues.append(
            {
                "taxonomy": "evidence_export_failure",
                "logical_path": "raw/civ6_states/*.json",
                "error": "No final state snapshot found",
            }
        )
    objective = _objective_metrics_from_state(state)
    target = target_turns or int(_number(header.get("requested_turns")) or 0)
    return {
        "episode_id": episode_id,
        "runner_kind": header.get("runner_kind") or header.get("runner") or "legacy-baseline",
        "evidence_kind": "legacy-baseline",
        "target_turns": target,
        "turn_reached": bool(target and (_number(objective.get("final_turn")) or 0) >= target),
        "objective_metrics": objective,
        "objective_metrics_complete": _metrics_complete(objective),
        "unplanned_mutation_count": 0,
        "verifier": {"total": 0, "pass": 0, "fail": 0, "inconclusive": 0, "pass_rate": None},
        "recovery_count": 0,
        "stuck_turn_count": 0,
        "invalid_plan_count": 0,
        "invalid_plan_rate": 0.0,
        "plan_count": 0,
        "step_status_counts": {},
        "failure_count": len(evidence_issues),
        "failures": [dict(issue) for issue in evidence_issues],
        "evidence": {
            "storage_backend": reader.backend,
            "state_path": state_path,
            "issues": evidence_issues,
        },
    }


def _average(values: list[float | int]) -> float | int | None:
    if not values:
        return None
    result = sum(float(value) for value in values) / len(values)
    return int(result) if result.is_integer() else result


def aggregate_objective_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    for key in OBJECTIVE_METRICS:
        values = [
            metrics.get(key)
            for row in rows
            for metrics in [_safe_dict(row.get("objective_metrics"))]
            if isinstance(metrics.get(key), (int, float))
        ]
        aggregate[key] = _average(values)
    return aggregate


def metric_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    keys: list[str] = COMPARISON_METRICS,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key in keys:
        base = baseline.get(key)
        cand = candidate.get(key)
        if isinstance(base, (int, float)) and isinstance(cand, (int, float)):
            value = float(cand) - float(base)
            delta[key] = int(value) if value.is_integer() else value
        else:
            delta[key] = None
    return delta


def taxonomy_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for failure in _safe_list(row.get("failures")):
            taxonomy = failure.get("taxonomy") if isinstance(failure, dict) else None
            if taxonomy:
                counter[str(taxonomy)] += 1
    return dict(sorted(counter.items()))


def evaluate_strategy_candidate_gate(
    *,
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    comparison_delta: dict[str, Any],
) -> dict[str, Any]:
    all_rows = baseline_rows + candidate_rows
    taxonomy_values = {
        str(failure.get("taxonomy"))
        for row in all_rows
        for failure in _safe_list(row.get("failures"))
        if isinstance(failure, dict) and failure.get("taxonomy")
    }
    comparable_deltas = {
        key: value
        for key, value in comparison_delta.items()
        if key in NUMERIC_T50_METRICS or key == "era_score"
        if isinstance(value, (int, float))
    }
    gates = {
        "baseline_present": bool(baseline_rows),
        "multi_episode_reproduced": len(candidate_rows) >= 2,
        "live_strict_unplanned_mutation_zero": all(
            int(row.get("unplanned_mutation_count") or 0) == 0
            for row in candidate_rows
            if row.get("evidence_kind") == "live"
        ),
        "verifier_evidence_complete": all(
            (
                row.get("evidence_kind") != "live"
                or (
                    _safe_dict(row.get("verifier")).get("total", 0) > 0
                    and _safe_dict(row.get("verifier")).get("inconclusive", 0) == 0
                )
            )
            for row in candidate_rows
        ),
        "objective_metrics_complete": all(
            bool(row.get("objective_metrics_complete")) for row in all_rows
        ),
        "objective_delta_over_baseline": any(
            value > 0 for value in comparable_deltas.values()
        ),
        "no_objective_metric_regression": all(
            value >= 0 for value in comparable_deltas.values()
        ),
        "failure_taxonomy_complete": taxonomy_values.issubset(FAILURE_TAXONOMY),
        "not_codex_self_eval": True,
    }
    return {
        "allowed": all(gates.values()),
        "gates": gates,
        "comparison_delta": comparison_delta,
        "claim_basis": "objective_ledger_metrics_only",
        "not_general_proof": True,
        "notes": [
            "This gate is audit-only and does not merge strategy assets.",
            "Codex rationale or self-evaluation is not used as outcome authority.",
            "A failed gate may still be useful evidence for Review or future scenarios.",
        ],
    }


def build_phase5_report(
    *,
    workspace: Path = WORKSPACE_ROOT,
    baseline_episodes: list[str],
    candidate_episodes: list[str],
    target_turns: int,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if not baseline_episodes:
        raise LiveEvaluationError("at least one baseline episode is required")
    if not candidate_episodes:
        raise LiveEvaluationError("at least one candidate/live episode is required")
    workspace = workspace.resolve()
    baseline_rows = [
        extract_episode_metrics(episode_id, workspace=workspace, target_turns=target_turns)
        for episode_id in baseline_episodes
    ]
    candidate_rows = [
        extract_episode_metrics(episode_id, workspace=workspace, target_turns=target_turns)
        for episode_id in candidate_episodes
    ]
    baseline_avg = aggregate_objective_metrics(baseline_rows)
    candidate_avg = aggregate_objective_metrics(candidate_rows)
    delta = metric_delta(baseline_avg, candidate_avg)
    report = {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "report_kind": f"phase5_t{target_turns}_live_eval",
        "generated_at": now_iso(),
        "workspace": str(workspace),
        "target_turns": target_turns,
        "baseline_episodes": baseline_rows,
        "candidate_episodes": candidate_rows,
        "aggregate": {
            "baseline": baseline_avg,
            "candidate": candidate_avg,
            "delta": delta,
        },
        "failure_taxonomy": taxonomy_summary(candidate_rows),
    }
    report["strategy_candidate_gate"] = evaluate_strategy_candidate_gate(
        baseline_rows=baseline_rows,
        candidate_rows=candidate_rows,
        comparison_delta=delta,
    )
    if output_path is not None:
        output_path = output_path.resolve()
        write_json(output_path, report)
        markdown_path = output_path.with_suffix(".md")
        write_text(markdown_path, render_markdown(report) + "\n")
        report["outputs"] = {
            "json": str(output_path),
            "markdown": str(markdown_path),
        }
        write_json(output_path, report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    target = report.get("target_turns")
    gate = _safe_dict(report.get("strategy_candidate_gate"))
    gates = _safe_dict(gate.get("gates"))
    delta = _safe_dict(_safe_dict(report.get("aggregate")).get("delta"))
    lines = [
        f"# Phase 5 T{target} Live Evaluation",
        "",
        f"- Gate allowed: `{str(gate.get('allowed')).lower()}`",
        f"- Claim basis: `{gate.get('claim_basis')}`",
        f"- Baseline episodes: `{len(_safe_list(report.get('baseline_episodes')))}`",
        f"- Candidate episodes: `{len(_safe_list(report.get('candidate_episodes')))}`",
        "",
        "## Objective Delta",
        "",
        "| Metric | Delta |",
        "|---|---:|",
    ]
    for key in COMPARISON_METRICS:
        lines.append(f"| `{key}` | `{delta.get(key)}` |")
    lines.extend(["", "## Gates", "", "| Gate | Pass |", "|---|---:|"])
    for key, value in gates.items():
        lines.append(f"| `{key}` | `{str(value).lower()}` |")
    taxonomy = _safe_dict(report.get("failure_taxonomy"))
    lines.extend(["", "## Failure Taxonomy", ""])
    if taxonomy:
        lines.extend(["| Taxonomy | Count |", "|---|---:|"])
        for key, value in taxonomy.items():
            lines.append(f"| `{key}` | `{value}` |")
    else:
        lines.append("No candidate failures recorded.")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This report is read-only evidence evaluation.",
            "- It does not run Civ6, replay saves, execute fragments, or merge strategy assets.",
            "- Strategy candidate promotion requires objective deltas and all gates to pass.",
        ]
    )
    return "\n".join(lines)


def _parse_episode_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--target-turns", type=int, default=20)
    parser.add_argument(
        "--baseline-episode",
        action="append",
        default=[],
        help="Baseline episode id. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--candidate-episode",
        action="append",
        default=[],
        help="Live/candidate episode id. May be repeated or comma-separated.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        report = build_phase5_report(
            workspace=args.workspace,
            baseline_episodes=_parse_episode_list(args.baseline_episode),
            candidate_episodes=_parse_episode_list(args.candidate_episode),
            target_turns=args.target_turns,
            output_path=args.output,
        )
    except (LiveEvaluationError, OSError, EpisodeStoreError, json.JSONDecodeError) as exc:
        print(json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json_dumps(report))


if __name__ == "__main__":
    main()

"""Build the v0.0.2 strategy-improvement acceptance report.

This verifier consumes completed evidence. It does not start Civ6, replay games,
or mutate Phase 3 assets.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_hl.evolution import orchestrator
from codex_hl.phase3 import assets as phase3_assets


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
TARGET_VERSION = "0.0.2"
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_TARGET_TURNS = 50


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return orchestrator.read_jsonl(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_html(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def average(values: list[float | int]) -> float | None:
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def metric_summary(workspace: Path, episodes: list[str]) -> dict[str, Any]:
    rows = [phase3_assets.extract_t50_metrics(episode, workspace=workspace) for episode in episodes]
    averages: dict[str, float | None] = {}
    for key in phase3_assets.NUMERIC_T50_METRICS:
        values = [
            row["metrics"].get(key)
            for row in rows
            if isinstance(row.get("metrics"), dict)
            and isinstance(row["metrics"].get(key), (int, float))
        ]
        averages[key] = average(values)
    return {"episodes": rows, "averages": averages}


def episode_header(workspace: Path, episode_id: str) -> dict[str, Any]:
    return read_json(workspace / "episodes" / episode_id / "header.json")


def episode_decisions(workspace: Path, episode_id: str) -> list[dict[str, Any]]:
    return read_jsonl(workspace / "episodes" / episode_id / "derived" / "decision_atoms.jsonl")


def selected_action(decision: dict[str, Any]) -> str:
    return str(decision.get("selected_action") or "")


def decision_execution_action(decision: dict[str, Any]) -> str:
    execution = decision.get("execution") or {}
    if not isinstance(execution, dict):
        return ""
    return str(execution.get("action") or "")


def behavior_counts(workspace: Path, episodes: list[str]) -> dict[str, int]:
    counts = {
        "candidate_strategy_decisions": 0,
        "automate_explore": 0,
        "settler_production": 0,
        "scout_production": 0,
        "found_city": 0,
        "move_settler": 0,
    }
    for episode_id in episodes:
        for decision in episode_decisions(workspace, episode_id):
            strategy = decision.get("strategy_context") or {}
            if isinstance(strategy, dict) and strategy.get("candidate_id"):
                counts["candidate_strategy_decisions"] += 1
            action = selected_action(decision)
            execution_action = decision_execution_action(decision)
            if action == "automate_explore" or execution_action == "automate_explore":
                counts["automate_explore"] += 1
            if "UNIT_SETTLER" in action:
                counts["settler_production"] += 1
            if "UNIT_SCOUT" in action:
                counts["scout_production"] += 1
            if action == "found_city on current tile" or execution_action == "found_city":
                counts["found_city"] += 1
            if "move toward best settle candidate" in action:
                counts["move_settler"] += 1
    return counts


def candidate_package_source_verified(workspace: Path, package: dict[str, Any]) -> dict[str, Any]:
    source_failure_ids = set(str(value) for value in package.get("source_failure_ids") or [])
    source_episode_ids = [str(value) for value in package.get("source_episode_ids") or []]
    found: set[str] = set()
    failure_paths: list[str] = []
    for episode_id in source_episode_ids:
        path = workspace / "episodes" / episode_id / "phase2" / "failures.jsonl"
        if not path.exists():
            continue
        failure_paths.append(str(path))
        for row in read_jsonl(path):
            failure_id = row.get("failure_id")
            if failure_id in source_failure_ids:
                found.add(str(failure_id))
    missing = sorted(source_failure_ids - found)
    return {
        "ok": bool(source_failure_ids) and not missing,
        "source_failure_ids": sorted(source_failure_ids),
        "source_episode_ids": source_episode_ids,
        "verified_failure_ids": sorted(found),
        "missing_failure_ids": missing,
        "failure_paths": failure_paths,
    }


def candidate_runtime_evidence(
    *,
    workspace: Path,
    candidate_episodes: list[str],
    package: dict[str, Any],
    package_path: Path,
) -> dict[str, Any]:
    candidate_id = package.get("candidate_id")
    package_sha = phase3_assets.sha256_file(package_path)
    rows: list[dict[str, Any]] = []
    all_applied = True
    for episode_id in candidate_episodes:
        header = episode_header(workspace, episode_id)
        runtime = header.get("candidate_runtime") or {}
        decisions = episode_decisions(workspace, episode_id)
        strategy_decisions = [
            decision
            for decision in decisions
            if isinstance(decision.get("strategy_context"), dict)
            and decision["strategy_context"].get("candidate_id") == candidate_id
        ]
        applied = (
            isinstance(runtime, dict)
            and runtime.get("status") == "applied"
            and runtime.get("candidate_id") == candidate_id
            and runtime.get("package_sha256") == package_sha
            and bool(strategy_decisions)
        )
        all_applied = all_applied and applied
        rows.append(
            {
                "episode_id": episode_id,
                "applied": applied,
                "runtime_status": runtime.get("status") if isinstance(runtime, dict) else None,
                "candidate_id": runtime.get("candidate_id") if isinstance(runtime, dict) else None,
                "runtime_effects": runtime.get("runtime_effects", []) if isinstance(runtime, dict) else [],
                "strategy_decision_count": len(strategy_decisions),
            }
        )
    return {
        "ok": all_applied,
        "candidate_id": candidate_id,
        "package_sha256": package_sha,
        "episodes": rows,
    }


def baseline_runtime_evidence(workspace: Path, baseline_episodes: list[str]) -> dict[str, Any]:
    rows = []
    ok = True
    for episode_id in baseline_episodes:
        header = episode_header(workspace, episode_id)
        runtime = header.get("candidate_runtime") or {}
        status = runtime.get("status") if isinstance(runtime, dict) else None
        clean = status in {None, "not_supplied"}
        ok = ok and clean
        rows.append({"episode_id": episode_id, "candidate_runtime_status": status, "clean": clean})
    return {"ok": ok, "episodes": rows}


def evidence_gate(workspace: Path, episodes: list[str], target_turns: int) -> dict[str, Any]:
    rows = []
    ok = True
    for episode_id in episodes:
        passed = orchestrator.episode_turns_passed(workspace, episode_id, target_turns=target_turns)
        pack = orchestrator.load_episode_report_pack(workspace, episode_id)
        rows.append(
            {
                "episode_id": episode_id,
                "passed": passed,
                "actual_turns": (pack.get("run") or {}).get("actual_turns"),
                "final_turn": (pack.get("run") or {}).get("final_turn"),
            }
        )
        ok = ok and passed
    return {"ok": ok, "episodes": rows}


def render_html(report: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    checks = "".join(
        f"<tr><td>{esc(check['name'])}</td><td>{'PASS' if check['ok'] else 'FAIL'}</td><td>{esc(check['detail'])}</td></tr>"
        for check in report["checks"]
    )
    metrics = "".join(
        f"<tr><td>{esc(key)}</td><td>{esc(values['baseline_avg'])}</td><td>{esc(values['candidate_avg'])}</td><td>{esc(values['delta'])}</td></tr>"
        for key, values in report["metric_comparison"]["numeric_metrics"].items()
    )
    behavior = "".join(
        f"<tr><td>{esc(key)}</td><td>{esc(values['baseline'])}</td><td>{esc(values['candidate'])}</td><td>{esc(values['delta'])}</td></tr>"
        for key, values in report["behavior_difference"]["counts"].items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>v0.0.2 Strategy Improvement Acceptance</title>
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 32px; color: #172033; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
th, td {{ border: 1px solid #d7deea; padding: 8px 10px; text-align: left; vertical-align: top; }}
th {{ background: #f4f7fb; }}
.pass {{ color: #166534; font-weight: 700; }}
.fail {{ color: #b91c1c; font-weight: 700; }}
code {{ background: #f4f7fb; padding: 1px 4px; border-radius: 4px; }}
</style>
<h1>v0.0.2 策略改进验收</h1>
<p>结论：<span class="{ 'pass' if report['ok'] else 'fail' }">{'PASS' if report['ok'] else 'FAIL'}</span></p>
<p>候选包：<code>{esc(report['candidate_package']['path'])}</code></p>
<h2>检查项</h2>
<table><tr><th>项目</th><th>状态</th><th>证据</th></tr>{checks}</table>
<h2>T50 主指标均值</h2>
<table><tr><th>指标</th><th>baseline</th><th>candidate</th><th>delta</th></tr>{metrics}</table>
<h2>行为差异</h2>
<table><tr><th>行为计数</th><th>baseline</th><th>candidate</th><th>delta</th></tr>{behavior}</table>
<h2>Episode</h2>
<p>Baseline: {esc(', '.join(report['baseline_episodes']))}</p>
<p>Candidate: {esc(', '.join(report['candidate_episodes']))}</p>
</html>
"""


def build_acceptance_report(
    *,
    workspace: Path,
    output_dir: Path,
    baseline_episodes: list[str],
    candidate_episodes: list[str],
    candidate_package: Path,
    target_turns: int = DEFAULT_TARGET_TURNS,
    required_sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> dict[str, Any]:
    package_path = candidate_package.resolve()
    package = read_json(package_path)
    baseline_gate = evidence_gate(workspace, baseline_episodes, target_turns)
    candidate_gate = evidence_gate(workspace, candidate_episodes, target_turns)
    package_source = candidate_package_source_verified(workspace, package)
    runtime_evidence = candidate_runtime_evidence(
        workspace=workspace,
        candidate_episodes=candidate_episodes,
        package=package,
        package_path=package_path,
    )
    baseline_runtime = baseline_runtime_evidence(workspace, baseline_episodes)

    baseline_metrics = metric_summary(workspace, baseline_episodes)
    candidate_metrics = metric_summary(workspace, candidate_episodes)
    numeric_metrics: dict[str, dict[str, float | None]] = {}
    improved: list[str] = []
    regressed: list[str] = []
    for key in phase3_assets.NUMERIC_T50_METRICS:
        baseline_avg = baseline_metrics["averages"].get(key)
        candidate_avg = candidate_metrics["averages"].get(key)
        delta = (
            candidate_avg - baseline_avg
            if isinstance(baseline_avg, (int, float)) and isinstance(candidate_avg, (int, float))
            else None
        )
        numeric_metrics[key] = {
            "baseline_avg": baseline_avg,
            "candidate_avg": candidate_avg,
            "delta": delta,
        }
        if isinstance(delta, (int, float)):
            if delta > 0:
                improved.append(key)
            elif delta < 0:
                regressed.append(key)

    baseline_behavior = behavior_counts(workspace, baseline_episodes)
    candidate_behavior = behavior_counts(workspace, candidate_episodes)
    behavior_delta = {
        key: {
            "baseline": baseline_behavior.get(key, 0),
            "candidate": candidate_behavior.get(key, 0),
            "delta": candidate_behavior.get(key, 0) - baseline_behavior.get(key, 0),
        }
        for key in sorted(set(baseline_behavior) | set(candidate_behavior))
    }
    behavior_diff_ok = (
        candidate_behavior["candidate_strategy_decisions"] > 0
        and any(value["delta"] != 0 for value in behavior_delta.values())
    )

    checks = [
        {
            "name": "5 baseline T50 episodes",
            "ok": (
                len(baseline_episodes) == required_sample_size
                and len(set(baseline_episodes)) == required_sample_size
                and baseline_gate["ok"]
            ),
            "detail": (
                f"{len(baseline_episodes)} episodes; unique={len(set(baseline_episodes))}; "
                f"evidence gate={baseline_gate['ok']}"
            ),
        },
        {
            "name": "5 candidate T50 episodes",
            "ok": (
                len(candidate_episodes) == required_sample_size
                and len(set(candidate_episodes)) == required_sample_size
                and candidate_gate["ok"]
            ),
            "detail": (
                f"{len(candidate_episodes)} episodes; unique={len(set(candidate_episodes))}; "
                f"evidence gate={candidate_gate['ok']}"
            ),
        },
        {
            "name": "candidate playbook comes from formal failure",
            "ok": package_source["ok"],
            "detail": ", ".join(package_source["verified_failure_ids"]) or "no source failure verified",
        },
        {
            "name": "candidate runner read candidate playbook",
            "ok": runtime_evidence["ok"],
            "detail": f"candidate_id={runtime_evidence['candidate_id']}",
        },
        {
            "name": "baseline did not use candidate runtime",
            "ok": baseline_runtime["ok"],
            "detail": "baseline headers have no applied candidate runtime",
        },
        {
            "name": "auditable behavior difference",
            "ok": behavior_diff_ok,
            "detail": f"candidate strategy decisions={candidate_behavior['candidate_strategy_decisions']}",
        },
        {
            "name": "at least one T50 main metric improved",
            "ok": bool(improved),
            "detail": ", ".join(improved) or "none",
        },
        {
            "name": "no obvious T50 main metric regression",
            "ok": not regressed,
            "detail": ", ".join(regressed) or "none",
        },
    ]

    report = {
        "schema_version": 1,
        "version": TARGET_VERSION,
        "report_kind": "v0.0.2_strategy_improvement_acceptance",
        "generated_at": now_iso(),
        "workspace": str(workspace),
        "target_turns": target_turns,
        "required_sample_size": required_sample_size,
        "baseline_episodes": baseline_episodes,
        "candidate_episodes": candidate_episodes,
        "candidate_package": {
            "path": str(package_path),
            "candidate_id": package.get("candidate_id"),
            "source_failure_ids": package.get("source_failure_ids") or [],
            "source_episode_ids": package.get("source_episode_ids") or [],
        },
        "checks": checks,
        "evidence_gates": {
            "baseline": baseline_gate,
            "candidate": candidate_gate,
            "candidate_runtime": runtime_evidence,
            "baseline_runtime": baseline_runtime,
            "candidate_package_source": package_source,
        },
        "metric_comparison": {
            "numeric_metrics": numeric_metrics,
            "improved_metrics": improved,
            "regressed_metrics": regressed,
        },
        "behavior_difference": {"counts": behavior_delta},
        "governance_audit_conclusion": (
            "Candidate satisfies v0.0.2 validation evidence for possible governance review; "
            "this report does not merge assets."
            if all(check["ok"] for check in checks)
            else "Do not enter governance merge; v0.0.2 evidence is incomplete or failing."
        ),
    }
    report["ok"] = all(check["ok"] for check in checks)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "v0.0.2_acceptance_report.json"
    html_path = output_dir / "v0.0.2_acceptance_report.html"
    write_json(json_path, report)
    report["paths"] = {"json": str(json_path), "html": str(html_path)}
    write_json(json_path, report)
    write_html(html_path, render_html(report))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--candidate-package", type=Path, required=True)
    parser.add_argument("--baseline-episodes", nargs="+", required=True)
    parser.add_argument("--candidate-episodes", nargs="+", required=True)
    parser.add_argument("--target-turns", type=int, default=DEFAULT_TARGET_TURNS)
    parser.add_argument("--required-sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    workspace = args.workspace.resolve()
    output_dir = (
        args.output_dir
        or workspace / "evolution" / "runs" / f"v0.0.2_acceptance_{now_stamp()}"
    ).resolve()
    report = build_acceptance_report(
        workspace=workspace,
        output_dir=output_dir,
        baseline_episodes=args.baseline_episodes,
        candidate_episodes=args.candidate_episodes,
        candidate_package=args.candidate_package,
        target_turns=args.target_turns,
        required_sample_size=args.required_sample_size,
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "json": report["paths"]["json"],
                "html": report["paths"]["html"],
            },
            ensure_ascii=False,
        )
    )
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

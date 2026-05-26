"""Validation regression scenario pool.

This module converts confirmed real failures into passive regression scenarios.
It does not replay saves or start Civilization VI.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
WORKFLOW_NAME = "Validation Scenario Pool"


class ValidationScenarioError(RuntimeError):
    """User-facing Validation Scenario error."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_id(*parts: Any, length: int = 14) -> str:
    payload = "\x1f".join(
        json.dumps(part, ensure_ascii=False, sort_keys=True, default=str) for part in parts
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationScenarioError(f"Invalid JSONL: {path}:{line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValidationScenarioError(f"Expected object in {path}:{line_no}")
        rows.append(row)
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def evidence_by_kind(failure: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    refs = failure.get("evidence_refs")
    if not isinstance(refs, list):
        return []
    return [ref for ref in refs if isinstance(ref, dict) and ref.get("kind") == kind]


def build_scenario(episode_id: str, failure: dict[str, Any], seeds: list[dict[str, Any]]) -> dict[str, Any]:
    failure_id = str(failure.get("failure_id") or stable_id(failure))
    linked_seeds = [seed for seed in seeds if failure_id in (seed.get("source_failure_ids") or [])]
    save_refs = evidence_by_kind(failure, "save")
    if not save_refs:
        save_refs = [
            {"kind": "save", "note": "No direct save evidence; inspect Observation save_index before making this runnable."}
        ]
    return {
        "schema_version": 1,
        "scenario_id": "scn_" + stable_id(episode_id, failure_id),
        "workflow": WORKFLOW_NAME,
        "status": "active",
        "validation_mode": "passive_until_replay_harness",
        "runnable": False,
        "manual_review_required": True,
        "created_at": now_iso(),
        "source_episode_ids": [episode_id],
        "source_failure_ids": [failure_id],
        "source_seed_ids": [seed.get("seed_id") for seed in linked_seeds if seed.get("seed_id")],
        "capability_dimensions": [
            failure.get("capability_category") or failure.get("capability_dimension") or "verification"
        ],
        "scenario_type": failure.get("failure_type") or "incident",
        "scenario_description": failure.get("description") or failure.get("title") or failure_id,
        "starting_save_refs": save_refs,
        "trigger_conditions": {
            "turn_range": failure.get("turn_range"),
            "evidence_refs": failure.get("evidence_refs", []),
        },
        "related_logs": {
            "tool_calls": evidence_by_kind(failure, "tool_call"),
            "state_snapshots": evidence_by_kind(failure, "state_snapshot"),
            "decision_atoms": evidence_by_kind(failure, "decision_atom"),
        },
        "expected_behavior": failure.get("expected_behavior"),
        "failed_behavior": failure.get("failed_behavior"),
        "acceptance_criteria": [
            "Future candidate handles the trigger without reproducing the failed behavior.",
            "No forbidden replay, rerun, or asset merge happens during scenario registration.",
            "Scenario becomes runnable only after a dedicated replay harness is implemented.",
        ],
    }


def upsert_scenarios(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row.get("scenario_id")): row for row in existing if row.get("scenario_id")}
    for row in incoming:
        by_id[str(row["scenario_id"])] = row
    return [by_id[key] for key in sorted(by_id)]


def render_review(scenarios: list[dict[str, Any]]) -> str:
    rows = "\n".join(
        f"<tr><td>{html.escape(s['scenario_id'])}</td><td>{html.escape(str(s['scenario_type']))}</td>"
        f"<td>{html.escape(', '.join(map(str, s.get('source_failure_ids', []))))}</td>"
        f"<td>{html.escape(str(s.get('runnable')))}</td></tr>"
        for s in scenarios
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Validation Scenarios</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; margin: 28px; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
  </style>
</head>
<body>
  <h1>Validation Scenario Pool</h1>
  <p>这些 scenario 来自真实 confirmed failure。当前只登记，不启动 Civ6，不 replay。</p>
  <table><thead><tr><th>scenario</th><th>type</th><th>failure</th><th>runnable</th></tr></thead><tbody>{rows}</tbody></table>
</body>
</html>
"""


def ingest_episode_failures(
    episode_id: str,
    *,
    workspace: Path = WORKSPACE_ROOT,
    pool_root: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    pool_root = (pool_root or workspace / "validation" / "scenarios").resolve()
    review_dir = workspace / "episodes" / episode_id / "review"
    failures = read_jsonl(review_dir / "failures.jsonl")
    if not failures:
        raise ValidationScenarioError(f"No confirmed Review failures found: {review_dir / 'failures.jsonl'}")
    seeds = read_jsonl(review_dir / "regression_seeds.jsonl")
    incoming = [build_scenario(episode_id, failure, seeds) for failure in failures]
    scenario_path = pool_root / "regression_scenarios.jsonl"
    merged = upsert_scenarios(read_jsonl(scenario_path), incoming)
    write_jsonl(scenario_path, merged)
    manifest = {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "generated_at": now_iso(),
        "pool_root": str(pool_root),
        "scenario_count": len(merged),
        "new_or_updated": len(incoming),
        "source_episode_id": episode_id,
        "runnable": False,
        "outputs": {
            "scenarios": "regression_scenarios.jsonl",
            "review": "scenario_pool.html",
        },
    }
    write_json(pool_root / "MANIFEST.json", manifest)
    (pool_root / "scenario_pool.html").write_text(render_review(merged), encoding="utf-8")
    episode_validation_scenarios = workspace / "episodes" / episode_id / "validation" / "scenarios"
    write_json(
        episode_validation_scenarios / "scenario_ingest.json",
        {
            "schema_version": 1,
            "workflow": WORKFLOW_NAME,
            "generated_at": now_iso(),
            "pool_root": str(pool_root),
            "scenario_ids": [row["scenario_id"] for row in incoming],
        },
    )
    return {
        "ok": True,
        "episode_id": episode_id,
        "pool_root": str(pool_root),
        "new_or_updated": len(incoming),
        "scenario_count": len(merged),
        "review": str(pool_root / "scenario_pool.html"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest confirmed failures into the validation scenario pool.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--pool-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = ingest_episode_failures(
            args.episode_id,
            workspace=args.workspace,
            pool_root=args.pool_root,
        )
    except (ValidationScenarioError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

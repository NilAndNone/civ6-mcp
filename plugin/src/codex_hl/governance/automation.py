"""Guarded L4/L5 asset governance.

The default action is audit-only evaluation. Asset files change only when the
caller passes --allow-merge and every gate passes. Rollback requires an existing
merge audit directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_hl.phase3 import assets as phase3_assets


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
PHASE_NAME = "L4/L5 Guarded Asset Governance"
MAIN_METRICS = set(phase3_assets.NUMERIC_T50_METRICS)


class GovernanceError(RuntimeError):
    """User-facing governance error."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_id(*parts: Any, length: int = 14) -> str:
    payload = "\x1f".join(
        json.dumps(part, ensure_ascii=False, sort_keys=True, default=str) for part in parts
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise GovernanceError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GovernanceError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validation_scenarios(report: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = report.get("scenario_results")
    if isinstance(scenarios, list):
        return [row for row in scenarios if isinstance(row, dict)]
    scenarios = report.get("scenarios")
    if isinstance(scenarios, list):
        return [row for row in scenarios if isinstance(row, dict)]
    return []


def scenario_passed(row: dict[str, Any]) -> bool:
    return str(row.get("status") or row.get("result") or "").lower() == "pass"


def row_regressions(row: dict[str, Any]) -> list[Any]:
    regressions = row.get("regressions")
    if isinstance(regressions, list):
        return regressions
    if row.get("regression") is True:
        return [row]
    return []


def extract_metric_deltas(report: dict[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}

    def add_from(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if key in MAIN_METRICS and isinstance(item, (int, float)):
                deltas[key] = deltas.get(key, 0.0) + float(item)

    add_from(report.get("delta"))
    add_from(report.get("t50_delta"))
    for row in validation_scenarios(report):
        add_from(row.get("delta"))
        add_from(row.get("t50_delta"))
        metrics = row.get("metrics")
        if isinstance(metrics, dict):
            add_from(metrics.get("delta"))
            add_from(metrics.get("t50_delta"))
    return deltas


def find_asset(catalog: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for asset in catalog.get("assets", []):
        if asset.get("asset_id") == asset_id:
            return asset
    raise GovernanceError(f"Asset not found in catalog: {asset_id}")


def evaluate_gates(
    candidate: dict[str, Any],
    validation_report: dict[str, Any],
    *,
    asset_root: Path,
) -> dict[str, Any]:
    target = candidate.get("target_asset") if isinstance(candidate.get("target_asset"), dict) else {}
    target_asset_id = target.get("asset_id")
    if not isinstance(target_asset_id, str):
        raise GovernanceError("candidate.target_asset.asset_id is required")
    catalog = phase3_assets.validate_catalog(asset_root)
    asset = find_asset(catalog, target_asset_id)
    asset_path = phase3_assets.resolve_catalog_path(asset_root, asset["content_path"])
    current_hash = phase3_assets.sha256_file(asset_path)
    scenarios = validation_scenarios(validation_report)
    deltas = extract_metric_deltas(validation_report)
    regressions = []
    for row in scenarios:
        regressions.extend(row_regressions(row))
    top_regressions = validation_report.get("regressions")
    if isinstance(top_regressions, list):
        regressions.extend(top_regressions)

    gates = {
        "multi_scenario_validation": len(scenarios) >= 2,
        "all_scenarios_passed": bool(scenarios) and all(scenario_passed(row) for row in scenarios),
        "t50_main_metric_improved": any(value > 0 for key, value in deltas.items() if key in MAIN_METRICS),
        "no_t50_main_metric_regression": all(value >= 0 for key, value in deltas.items() if key in MAIN_METRICS),
        "no_regression_records": not regressions,
        "target_asset_hash_matches": current_hash == target.get("current_sha256"),
        "candidate_has_failure_source": bool(candidate.get("source_failure_ids")),
        "rollback_plan_present": isinstance(candidate.get("rollback_plan"), dict),
        "candidate_is_not_premerged": candidate.get("auto_merge_allowed") is False
        and candidate.get("status") == "candidate_only",
    }
    return {
        "gates": gates,
        "merge_allowed": all(gates.values()),
        "metric_deltas": deltas,
        "scenario_count": len(scenarios),
        "regression_count": len(regressions),
        "target_asset": asset,
        "target_asset_path": str(asset_path),
        "current_hash": current_hash,
    }


def update_catalog_asset(catalog_path: Path, asset_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    catalog = read_json(catalog_path)
    for asset in catalog.get("assets", []):
        if asset.get("asset_id") == asset_id:
            asset.update(updates)
            write_json(catalog_path, catalog)
            return asset
    raise GovernanceError(f"Asset not found in catalog: {asset_id}")


def apply_merge(
    candidate: dict[str, Any],
    *,
    asset_root: Path,
    audit_dir: Path,
    validation_report_path: Path,
) -> dict[str, Any]:
    target = candidate["target_asset"]
    asset = phase3_assets.validate_catalog(asset_root, require_ledger=False)
    current_asset = find_asset(asset, target["asset_id"])
    asset_path = phase3_assets.resolve_catalog_path(asset_root, current_asset["content_path"])
    before_bytes = asset_path.read_bytes()
    before_content = before_bytes.decode("utf-8")
    proposed_content = candidate.get("proposed_change", {}).get("proposed_content")
    if not isinstance(proposed_content, str) or not proposed_content.strip():
        raise GovernanceError("candidate.proposed_change.proposed_content is required for merge")
    if sha256_text(proposed_content) != target.get("proposed_sha256"):
        raise GovernanceError("candidate proposed content hash does not match target proposed_sha256")
    rollback_snapshot = {
        "schema_version": 1,
        "asset_id": target["asset_id"],
        "content_path": current_asset["content_path"],
        "previous_version": current_asset["version"],
        "previous_sha256": phase3_assets.sha256_file(asset_path),
        "previous_content": before_content,
        "catalog_before": current_asset,
        "created_at": now_iso(),
    }
    write_json(audit_dir / "rollback_snapshot.json", rollback_snapshot)
    asset_path.write_bytes(proposed_content.encode("utf-8"))
    new_sha = phase3_assets.sha256_file(asset_path)
    if new_sha != target["proposed_sha256"]:
        asset_path.write_bytes(before_bytes)
        raise GovernanceError("written asset hash mismatch; restored previous content")
    updated_asset = update_catalog_asset(
        asset_root / "catalog.json",
        target["asset_id"],
        {
            "version": target["proposed_version"],
            "content_sha256": new_sha,
            "source_refs": sorted(
                set(current_asset.get("source_refs", []))
                | {f"phase4_candidate:{candidate['candidate_id']}", str(validation_report_path)}
            ),
            "capability_dimensions": sorted(
                set(current_asset.get("capability_dimensions", []))
                | set(target.get("capability_dimensions", []))
            ),
        },
    )
    ledger_row = {
        "ledger_id": "ledger-" + stable_id("auto_merge", candidate["candidate_id"], now_iso()),
        "event_type": "auto_merge",
        "recorded_at": now_iso(),
        "asset_id": target["asset_id"],
        "version": target["proposed_version"],
        "source_failure_ids": candidate.get("source_failure_ids", []),
        "source_episode_ids": candidate.get("source_episode_ids", []),
        "source_refs": [f"phase4_candidate:{candidate['candidate_id']}", str(validation_report_path)],
        "metric_refs": [str(validation_report_path)],
        "human_or_auto_judgments": [
            "L4/L5 governance allowed merge after multi-scenario validation gates passed."
        ],
        "notes": "Auto-merge is reversible through the audit rollback snapshot.",
    }
    append_jsonl(asset_root / "change_ledger.jsonl", ledger_row)
    result = {
        "schema_version": 1,
        "event": "auto_merge_applied",
        "candidate_id": candidate["candidate_id"],
        "asset_id": target["asset_id"],
        "previous_version": rollback_snapshot["previous_version"],
        "new_version": target["proposed_version"],
        "new_sha256": new_sha,
        "updated_asset": updated_asset,
        "ledger_id": ledger_row["ledger_id"],
        "audit_dir": str(audit_dir),
    }
    write_json(audit_dir / "merge_result.json", result)
    return result


def evaluate_candidate(
    candidate_package: Path,
    validation_report_path: Path,
    *,
    asset_root: Path = phase3_assets.ASSET_ROOT,
    workspace: Path = WORKSPACE_ROOT,
    allow_merge: bool = False,
) -> dict[str, Any]:
    candidate_package = candidate_package.resolve()
    validation_report_path = validation_report_path.resolve()
    asset_root = asset_root.resolve()
    candidate = read_json(candidate_package)
    validation_report = read_json(validation_report_path)
    gate_result = evaluate_gates(candidate, validation_report, asset_root=asset_root)
    decision_id = "gov_" + stable_id(candidate.get("candidate_id"), validation_report_path, gate_result)
    audit_dir = workspace.resolve() / "automation" / "audits" / decision_id
    decision = {
        "schema_version": 1,
        "phase": PHASE_NAME,
        "decision_id": decision_id,
        "created_at": now_iso(),
        "candidate_package": str(candidate_package),
        "validation_report": str(validation_report_path),
        "asset_root": str(asset_root),
        "candidate_id": candidate.get("candidate_id"),
        "merge_allowed": gate_result["merge_allowed"],
        "allow_merge_flag": allow_merge,
        "gates": gate_result["gates"],
        "metric_deltas": gate_result["metric_deltas"],
        "scenario_count": gate_result["scenario_count"],
        "regression_count": gate_result["regression_count"],
        "audit_dir": str(audit_dir),
    }
    write_json(audit_dir / "merge_decision.json", decision)
    if allow_merge:
        if not gate_result["merge_allowed"]:
            raise GovernanceError(f"Merge refused; failed gates: {decision['gates']}")
        decision["merge_result"] = apply_merge(
            candidate,
            asset_root=asset_root,
            audit_dir=audit_dir,
            validation_report_path=validation_report_path,
        )
        write_json(audit_dir / "merge_decision.json", decision)
    return decision


def rollback_from_audit(
    audit_dir: Path,
    *,
    asset_root: Path = phase3_assets.ASSET_ROOT,
    reason: str = "manual rollback",
) -> dict[str, Any]:
    audit_dir = audit_dir.resolve()
    asset_root = asset_root.resolve()
    snapshot = read_json(audit_dir / "rollback_snapshot.json")
    asset_id = str(snapshot["asset_id"])
    asset_path = phase3_assets.resolve_catalog_path(asset_root, str(snapshot["content_path"]))
    asset_path.write_bytes(str(snapshot["previous_content"]).encode("utf-8"))
    restored_sha = phase3_assets.sha256_file(asset_path)
    if restored_sha != snapshot["previous_sha256"]:
        raise GovernanceError("rollback restore hash mismatch")
    update_catalog_asset(
        asset_root / "catalog.json",
        asset_id,
        {
            "version": snapshot["previous_version"],
            "content_sha256": restored_sha,
        },
    )
    ledger_row = {
        "ledger_id": "ledger-" + stable_id("auto_rollback", asset_id, now_iso()),
        "event_type": "auto_rollback",
        "recorded_at": now_iso(),
        "asset_id": asset_id,
        "version": snapshot["previous_version"],
        "source_failure_ids": [],
        "source_episode_ids": [],
        "source_refs": [str(audit_dir)],
        "metric_refs": [],
        "human_or_auto_judgments": [reason],
        "notes": "Rollback restored the asset content and catalog hash from rollback_snapshot.json.",
    }
    append_jsonl(asset_root / "change_ledger.jsonl", ledger_row)
    result = {
        "schema_version": 1,
        "event": "auto_rollback_applied",
        "asset_id": asset_id,
        "restored_version": snapshot["previous_version"],
        "restored_sha256": restored_sha,
        "ledger_id": ledger_row["ledger_id"],
        "audit_dir": str(audit_dir),
        "reason": reason,
    }
    write_json(audit_dir / "rollback_result.json", result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate, merge, or roll back Codex HL assets.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--evaluate", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--candidate-package", type=Path)
    parser.add_argument("--validation-report", type=Path)
    parser.add_argument("--asset-root", type=Path, default=phase3_assets.ASSET_ROOT)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--allow-merge", action="store_true")
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--reason", default="manual rollback")
    args = parser.parse_args(argv)
    if args.evaluate and (not args.candidate_package or not args.validation_report):
        parser.error("--evaluate requires --candidate-package and --validation-report")
    if args.rollback and not args.audit_dir:
        parser.error("--rollback requires --audit-dir")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        if args.evaluate:
            payload = evaluate_candidate(
                args.candidate_package,
                args.validation_report,
                asset_root=args.asset_root,
                workspace=args.workspace,
                allow_merge=args.allow_merge,
            )
        else:
            payload = rollback_from_audit(
                args.audit_dir,
                asset_root=args.asset_root,
                reason=args.reason,
            )
    except (GovernanceError, phase3_assets.Phase3AssetError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

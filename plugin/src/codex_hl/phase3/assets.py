"""Phase 3 asset registry validation and T50 metric comparison.

This module is intentionally read-only for gameplay state. It validates the
versioned asset catalog and can compare already-recorded T50 episodes, but it
does not generate strategy changes, replay saves, merge assets, or roll back
files.
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


MODULE_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()

REQUIRED_ASSET_FIELDS = {
    "asset_id",
    "asset_type",
    "version",
    "content_path",
    "content_sha256",
    "source_refs",
    "applicability",
    "risk_level",
    "rollback_path",
    "capability_dimensions",
    "status",
}
ASSET_TYPES = {"prompt", "playbook", "tool_policy", "memory"}
RISK_LEVELS = {"low", "medium", "high"}
STATUSES = {"active", "archived"}
CAPABILITY_DIMENSIONS = {
    "planning",
    "execution",
    "memory/state",
    "tool grounding",
    "verification",
    "recovery",
}
NUMERIC_T50_METRICS = [
    "num_cities",
    "completed_tech_count",
    "completed_civic_count",
    "science_yield",
    "culture_yield",
]


class Phase3AssetError(RuntimeError):
    """User-facing Phase 3 validation error."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def candidate_asset_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("CODEX_HL_CIV6_PHASE3_ASSET_ROOT")
    if env_root:
        roots.append(Path(env_root).resolve())
    parents = list(MODULE_PATH.parents)
    if len(parents) > 3:
        roots.append(parents[3] / "assets" / "codex_hl" / "phase3")
    if len(parents) > 2:
        roots.append(parents[2] / "assets" / "codex_hl" / "phase3")
    roots.append(WORKSPACE_ROOT / "plugin" / "assets" / "codex_hl" / "phase3")
    roots.append(WORKSPACE_ROOT / "assets" / "codex_hl" / "phase3")

    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def default_asset_root() -> Path:
    for root in candidate_asset_roots():
        if (root / "catalog.json").exists():
            return root
    return candidate_asset_roots()[0]


ASSET_ROOT = default_asset_root()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise Phase3AssetError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise Phase3AssetError(f"Expected JSON object: {path}")
    return data


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise Phase3AssetError(f"Missing JSONL file: {path}") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Phase3AssetError(f"Invalid JSONL: {path}:{line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise Phase3AssetError(f"Expected JSON object in {path}:{line_no}")
        rows.append(row)
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_catalog_path(asset_root: Path, rel_path: str) -> Path:
    candidate = (asset_root / rel_path).resolve()
    root = asset_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise Phase3AssetError(f"Path escapes asset root: {rel_path}") from exc
    return candidate


def _require_string(row: dict[str, Any], key: str, *, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Phase3AssetError(f"{context}.{key} must be a non-empty string")
    return value


def _require_string_list(row: dict[str, Any], key: str, *, context: str) -> list[str]:
    value = row.get(key)
    if not isinstance(value, list) or not value:
        raise Phase3AssetError(f"{context}.{key} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise Phase3AssetError(f"{context}.{key} must contain only non-empty strings")
    return value


def load_catalog(asset_root: Path = ASSET_ROOT) -> dict[str, Any]:
    catalog_path = asset_root / "catalog.json"
    if not catalog_path.exists():
        raise Phase3AssetError(f"Missing Phase 3 catalog: {catalog_path}")
    return read_json(catalog_path)


def validate_catalog(asset_root: Path = ASSET_ROOT, *, require_ledger: bool = True) -> dict[str, Any]:
    catalog = load_catalog(asset_root)
    assets = catalog.get("assets")
    if catalog.get("schema_version") != 1:
        raise Phase3AssetError("catalog.schema_version must be 1")
    if not isinstance(assets, list) or not assets:
        raise Phase3AssetError("catalog.assets must be a non-empty list")

    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, asset in enumerate(assets):
        context = f"assets[{index}]"
        if not isinstance(asset, dict):
            raise Phase3AssetError(f"{context} must be an object")
        fields = set(asset)
        if fields != REQUIRED_ASSET_FIELDS:
            missing = sorted(REQUIRED_ASSET_FIELDS - fields)
            extra = sorted(fields - REQUIRED_ASSET_FIELDS)
            raise Phase3AssetError(f"{context} fields mismatch; missing={missing}; extra={extra}")

        asset_id = _require_string(asset, "asset_id", context=context)
        if asset_id in seen_ids:
            raise Phase3AssetError(f"Duplicate asset_id: {asset_id}")
        seen_ids.add(asset_id)

        asset_type = _require_string(asset, "asset_type", context=context)
        if asset_type not in ASSET_TYPES:
            raise Phase3AssetError(f"{asset_id}.asset_type must be one of {sorted(ASSET_TYPES)}")
        risk = _require_string(asset, "risk_level", context=context)
        if risk not in RISK_LEVELS:
            raise Phase3AssetError(f"{asset_id}.risk_level must be one of {sorted(RISK_LEVELS)}")
        status = _require_string(asset, "status", context=context)
        if status not in STATUSES:
            raise Phase3AssetError(f"{asset_id}.status must be one of {sorted(STATUSES)}")

        _require_string(asset, "version", context=context)
        _require_string_list(asset, "source_refs", context=context)
        _require_string_list(asset, "applicability", context=context)
        dimensions = _require_string_list(asset, "capability_dimensions", context=context)
        invalid_dimensions = sorted(set(dimensions) - CAPABILITY_DIMENSIONS)
        if invalid_dimensions:
            raise Phase3AssetError(f"{asset_id}.capability_dimensions invalid: {invalid_dimensions}")

        content_path = resolve_catalog_path(asset_root, _require_string(asset, "content_path", context=context))
        if not content_path.exists():
            raise Phase3AssetError(f"{asset_id}.content_path missing: {content_path}")
        actual_hash = sha256_file(content_path)
        if actual_hash != asset["content_sha256"]:
            raise Phase3AssetError(
                f"{asset_id}.content_sha256 mismatch: catalog={asset['content_sha256']} actual={actual_hash}"
            )
        rollback_path = resolve_catalog_path(asset_root, _require_string(asset, "rollback_path", context=context))
        if not rollback_path.exists():
            raise Phase3AssetError(f"{asset_id}.rollback_path missing: {rollback_path}")
        validated.append(asset)

    if require_ledger:
        validate_ledger(asset_root, validated)
    return {**catalog, "assets": validated}


def validate_ledger(asset_root: Path, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger_path = asset_root / "change_ledger.jsonl"
    rows = read_jsonl(ledger_path)
    coverage: set[tuple[str, str]] = set()
    for row_index, row in enumerate(rows):
        context = f"change_ledger[{row_index}]"
        asset_id = _require_string(row, "asset_id", context=context)
        version = _require_string(row, "version", context=context)
        _require_string(row, "event_type", context=context)
        _require_string(row, "recorded_at", context=context)
        if not isinstance(row.get("source_failure_ids"), list):
            raise Phase3AssetError(f"{context}.source_failure_ids must be a list")
        if not isinstance(row.get("source_episode_ids"), list):
            raise Phase3AssetError(f"{context}.source_episode_ids must be a list")
        if not isinstance(row.get("source_refs"), list) or not row["source_refs"]:
            raise Phase3AssetError(f"{context}.source_refs must be a non-empty list")
        if not isinstance(row.get("human_or_auto_judgments"), list) or not row["human_or_auto_judgments"]:
            raise Phase3AssetError(f"{context}.human_or_auto_judgments must be a non-empty list")
        coverage.add((asset_id, version))

    missing = [
        f"{asset['asset_id']}@{asset['version']}"
        for asset in assets
        if (asset["asset_id"], asset["version"]) not in coverage
    ]
    if missing:
        raise Phase3AssetError(f"change_ledger missing asset/version coverage: {missing}")
    return rows


def active_asset_snapshot(asset_root: Path = ASSET_ROOT) -> dict[str, Any]:
    catalog = validate_catalog(asset_root)
    active_assets = [
        {
            "asset_id": asset["asset_id"],
            "asset_type": asset["asset_type"],
            "version": asset["version"],
            "content_path": asset["content_path"],
            "content_sha256": asset["content_sha256"],
            "risk_level": asset["risk_level"],
            "capability_dimensions": asset["capability_dimensions"],
        }
        for asset in catalog["assets"]
        if asset["status"] == "active"
    ]
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "phase": "Phase 3 Asset System",
        "source_catalog": str((asset_root / "catalog.json").resolve()),
        "active_assets": active_assets,
        "asset_count": len(active_assets),
        "notes": [
            "This is an asset version snapshot, not an asset change approval.",
            "Memory assets are low-trust references and cannot replace current Civ6 state checks.",
        ],
    }


def write_active_asset_snapshot(path: Path, asset_root: Path = ASSET_ROOT) -> dict[str, Any]:
    snapshot = active_asset_snapshot(asset_root)
    write_json(path, snapshot)
    return snapshot


def list_active_assets(asset_root: Path = ASSET_ROOT) -> dict[str, Any]:
    return active_asset_snapshot(asset_root)


def _load_episode_final_state(episode_id: str, *, workspace: Path = WORKSPACE_ROOT) -> tuple[Path, dict[str, Any]]:
    state_dir = workspace / "episodes" / episode_id / "raw" / "civ6_states"
    if not state_dir.exists():
        raise Phase3AssetError(f"Missing episode state directory: {state_dir}")

    states: list[tuple[int, Path, dict[str, Any]]] = []
    for path in sorted(state_dir.glob("*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Phase3AssetError(f"Invalid state JSON: {path}: {exc}") from exc
        turn = state.get("turn")
        if isinstance(turn, int):
            states.append((turn, path, state))
    if not states:
        raise Phase3AssetError(f"No turn states found under: {state_dir}")

    preferred = [item for item in states if "t50_final" in item[1].name]
    return max(preferred or states, key=lambda item: (item[0], item[1].name))[1:]


def extract_t50_metrics(episode_id: str, *, workspace: Path = WORKSPACE_ROOT) -> dict[str, Any]:
    state_path, state = _load_episode_final_state(episode_id, workspace=workspace)
    overview = state.get("overview") if isinstance(state.get("overview"), dict) else {}
    research_civic = (
        state.get("research_civic") if isinstance(state.get("research_civic"), dict) else {}
    )
    metrics = {
        "num_cities": overview.get("num_cities"),
        "completed_tech_count": research_civic.get("completed_tech_count"),
        "completed_civic_count": research_civic.get("completed_civic_count"),
        "current_research": research_civic.get("current_research") or overview.get("current_research"),
        "current_civic": research_civic.get("current_civic") or overview.get("current_civic"),
        "science_yield": overview.get("science_yield"),
        "culture_yield": overview.get("culture_yield"),
    }
    return {
        "episode_id": episode_id,
        "state_path": str(state_path),
        "turn": state.get("turn"),
        "metrics": metrics,
    }


def compare_t50_metrics(
    baseline_episode: str,
    candidate_episode: str,
    *,
    workspace: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    baseline = extract_t50_metrics(baseline_episode, workspace=workspace)
    candidate = extract_t50_metrics(candidate_episode, workspace=workspace)
    delta: dict[str, int | float | None] = {}
    for key in NUMERIC_T50_METRICS:
        base_value = baseline["metrics"].get(key)
        cand_value = candidate["metrics"].get(key)
        if isinstance(base_value, (int, float)) and isinstance(cand_value, (int, float)):
            delta[key] = cand_value - base_value
        else:
            delta[key] = None
    return {
        "schema_version": 1,
        "phase": "Phase 3 T50 Metric Review",
        "generated_at": now_iso(),
        "claim_scope": "candidate_evidence_only",
        "auto_merge_allowed": False,
        "not_general_proof": True,
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
        "notes": [
            "A single test 1 comparison is candidate evidence only.",
            "This command does not generate an asset diff, merge an asset, replay a save, or roll back files.",
        ],
    }


def check_asset_library(asset_root: Path = ASSET_ROOT) -> dict[str, Any]:
    catalog = validate_catalog(asset_root)
    active = [asset for asset in catalog["assets"] if asset["status"] == "active"]
    return {
        "ok": True,
        "asset_root": str(asset_root.resolve()),
        "asset_count": len(catalog["assets"]),
        "active_asset_count": len(active),
        "asset_ids": [asset["asset_id"] for asset in catalog["assets"]],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Codex HL Civ6 Phase 3 assets.")
    parser.add_argument("--asset-root", type=Path, default=ASSET_ROOT)
    parser.add_argument("--check", action="store_true", help="validate the Phase 3 asset catalog")
    parser.add_argument("--list", action="store_true", help="list active assets")
    parser.add_argument("--compare-t50", action="store_true", help="compare two recorded T50 episodes")
    parser.add_argument("--baseline-episode")
    parser.add_argument("--candidate-episode")
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    args = parser.parse_args(argv)
    if args.compare_t50 and (not args.baseline_episode or not args.candidate_episode):
        parser.error("--compare-t50 requires --baseline-episode and --candidate-episode")
    if not (args.check or args.list or args.compare_t50):
        parser.error("choose one of --check, --list, or --compare-t50")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        if args.check:
            payload = check_asset_library(args.asset_root)
        elif args.list:
            payload = list_active_assets(args.asset_root)
        else:
            payload = compare_t50_metrics(
                args.baseline_episode,
                args.candidate_episode,
                workspace=args.workspace.resolve(),
            )
    except Phase3AssetError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

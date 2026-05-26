"""Strategy candidate improvement packages.

Strategy candidates can propose asset changes from confirmed review failures, but they must
not apply them. The output is an auditable package that later validation and
governance tools can review.
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

from codex_hl.strategy import registry as strategy_registry


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
WORKFLOW_NAME = "Strategy Candidate Improvement Packages"
CAPABILITY_DIMENSIONS = strategy_registry.CAPABILITY_DIMENSIONS


class StrategyCandidateError(RuntimeError):
    """User-facing Strategy Candidate error."""


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
        raise StrategyCandidateError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StrategyCandidateError(f"Expected JSON object: {path}")
    return value


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
            raise StrategyCandidateError(f"Invalid JSONL: {path}:{line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise StrategyCandidateError(f"Expected JSON object in {path}:{line_no}")
        rows.append(row)
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def assert_under(path: Path, base: Path) -> None:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise StrategyCandidateError(f"Refusing to write outside {base}: {path}") from exc


def bump_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        parts[2] = str(int(parts[2]) + 1)
        return ".".join(parts)
    return f"{version}.strategy_candidate"


def failure_capability(failure: dict[str, Any]) -> str:
    value = failure.get("capability_category") or failure.get("capability_dimension")
    if isinstance(value, str) and value in CAPABILITY_DIMENSIONS:
        return value
    dims = failure.get("capability_dimensions")
    if isinstance(dims, list):
        for dim in dims:
            if isinstance(dim, str) and dim in CAPABILITY_DIMENSIONS:
                return dim
    return "verification"


def select_target_asset(failure: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    capability = failure_capability(failure)
    active_assets = [asset for asset in catalog["assets"] if asset["status"] == "active"]
    matching = [
        asset
        for asset in active_assets
        if capability in asset.get("capability_dimensions", [])
        and asset.get("asset_type") in {"playbook", "tool_policy", "prompt", "memory"}
    ]
    if not matching:
        matching = [asset for asset in active_assets if asset.get("asset_id") == "strategy.memory.low_trust"]
    if not matching:
        raise StrategyCandidateError(f"No active asset can receive capability {capability!r}")
    priority = {"playbook": 0, "tool_policy": 1, "prompt": 2, "memory": 3}
    return sorted(matching, key=lambda asset: (priority.get(asset["asset_type"], 9), asset["asset_id"]))[0]


def content_appendix(failure: dict[str, Any], capability: str) -> str:
    title = str(failure.get("title") or failure.get("failure_id") or "confirmed failure")
    failure_id = str(failure.get("failure_id") or "unknown_failure")
    description = str(failure.get("description") or failure.get("failed_behavior") or "")
    expected = str(failure.get("expected_behavior") or "Keep behavior grounded in current evidence.")
    failed = str(failure.get("failed_behavior") or description)
    return (
        "\n\n"
        "## Strategy Candidate Lesson\n\n"
        f"- Source failure: `{failure_id}`\n"
        f"- Capability: `{capability}`\n"
        f"- Title: {title}\n"
        f"- Expected behavior: {expected}\n"
        f"- Failed behavior: {failed}\n"
        "- Review status: candidate only; apply only through L4/L5 governance after multi-scenario validation.\n"
    )


def build_candidate_for_failure(
    failure: dict[str, Any],
    *,
    episode_id: str,
    asset_root: Path,
    catalog: dict[str, Any],
    seeds: list[dict[str, Any]],
) -> dict[str, Any]:
    target = select_target_asset(failure, catalog)
    target_path = strategy_registry.resolve_catalog_path(asset_root, target["content_path"])
    current_content = target_path.read_text(encoding="utf-8")
    capability = failure_capability(failure)
    appendix = content_appendix(failure, capability)
    proposed_content = current_content.rstrip() + appendix
    proposed_sha = hashlib.sha256(proposed_content.encode("utf-8")).hexdigest()
    source_failure_id = str(failure.get("failure_id") or stable_id(failure))
    candidate_id = "impr_" + stable_id(episode_id, source_failure_id, target["asset_id"])
    scenario_refs = [
        {
            "seed_id": seed.get("seed_id"),
            "source_failure_ids": seed.get("source_failure_ids"),
            "manual_review_required": seed.get("manual_review_required", True),
        }
        for seed in seeds
        if source_failure_id in (seed.get("source_failure_ids") or [])
    ]
    if not scenario_refs:
        scenario_refs.append(
            {
                "source_failure_ids": [source_failure_id],
                "manual_review_required": True,
                "note": "Validation should convert this failure into a regression scenario before merge.",
            }
        )
    return {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "candidate_id": candidate_id,
        "status": "candidate_only",
        "auto_merge_allowed": False,
        "created_at": now_iso(),
        "source_episode_ids": [episode_id],
        "source_failure_ids": [source_failure_id],
        "source_failure": {
            "title": failure.get("title"),
            "failure_type": failure.get("failure_type"),
            "capability_category": failure.get("capability_category"),
            "confidence": failure.get("confidence"),
            "evidence_refs": failure.get("evidence_refs", []),
        },
        "target_asset": {
            "asset_id": target["asset_id"],
            "asset_type": target["asset_type"],
            "current_version": target["version"],
            "proposed_version": bump_patch(str(target["version"])),
            "content_path": target["content_path"],
            "current_sha256": target["content_sha256"],
            "proposed_sha256": proposed_sha,
            "risk_level": target["risk_level"],
            "capability_dimensions": sorted(set(target["capability_dimensions"]) | {capability}),
        },
        "proposed_change": {
            "change_type": "append_reviewed_lesson",
            "rationale": "Confirmed Review failure produced a candidate lesson for a matching active asset.",
            "content_appendix": appendix,
            "proposed_content": proposed_content,
        },
        "asset_diff": {
            "format": "text_append",
            "current_sha256": target["content_sha256"],
            "proposed_sha256": proposed_sha,
            "diff_summary": f"Append one reviewed Strategy Candidate lesson to {target['asset_id']}.",
        },
        "validation_plan": {
            "required_before_merge": True,
            "minimum_scenarios": 2,
            "scenario_refs": scenario_refs,
            "required_metrics": [
                "T50 main metrics must improve on at least one numeric metric.",
                "No T50 main metric may regress.",
                "All regression scenarios must pass.",
            ],
            "side_effect_checks": [
                "No new forbidden Review fields.",
                "No replay or Civ6 run triggered by candidate generation.",
                "Human-readable audit report exists before merge.",
            ],
        },
        "risk_assessment": {
            "risk_level": target["risk_level"],
            "possible_side_effects": [
                "Overfitting to one episode.",
                "Changing broad behavior from a narrow failure.",
                "Reducing evidence grounding if applied without scenario validation.",
            ],
        },
        "rollback_plan": {
            "rollback_asset_id": target["asset_id"],
            "rollback_version": target["version"],
            "rollback_sha256": target["content_sha256"],
            "rollback_path": target["rollback_path"],
        },
    }


def render_review(candidates: list[dict[str, Any]], episode_id: str) -> str:
    cards = []
    for candidate in candidates:
        target = candidate["target_asset"]
        cards.append(
            f"""
<article class="card">
  <p class="eyebrow">{html.escape(candidate["candidate_id"])}</p>
  <h2>{html.escape(str(candidate["source_failure"].get("title") or candidate["source_failure_ids"][0]))}</h2>
  <p><strong>Target:</strong> {html.escape(target["asset_id"])} {html.escape(target["current_version"])} -> {html.escape(target["proposed_version"])}</p>
  <p><strong>Status:</strong> candidate only; no asset file has been modified.</p>
  <p><strong>Diff:</strong> {html.escape(candidate["asset_diff"]["diff_summary"])}</p>
  <p><strong>Merge gate:</strong> {html.escape("; ".join(candidate["validation_plan"]["required_metrics"]))}</p>
</article>
"""
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Strategy Candidate Improvements - {html.escape(episode_id)}</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; margin: 28px; color: #1f2937; line-height: 1.55; }}
    .card {{ border: 1px solid #d1d5db; border-left: 4px solid #2563eb; border-radius: 6px; padding: 14px; margin: 14px 0; }}
    .eyebrow {{ color: #64748b; font-family: Consolas, monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Strategy Candidate 候选改进包</h1>
  <p>这些候选只来自已确认 Review failure，不会修改资产。进入 L4/L5 前必须完成多场景验证。</p>
  {''.join(cards) if cards else '<p>No candidates.</p>'}
</body>
</html>
"""


def generate_candidate_packages(
    episode_id: str,
    *,
    workspace: Path = WORKSPACE_ROOT,
    asset_root: Path = strategy_registry.ASSET_ROOT,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    asset_root = asset_root.resolve()
    review_dir = workspace / "episodes" / episode_id / "review"
    strategy_candidate_dir = workspace / "episodes" / episode_id / "strategy" / "candidates"
    failures = read_jsonl(review_dir / "failures.jsonl")
    if not failures:
        raise StrategyCandidateError(f"No confirmed Review failures found: {review_dir / 'failures.jsonl'}")
    seeds = read_jsonl(review_dir / "regression_seeds.jsonl")
    catalog = strategy_registry.validate_catalog(asset_root)
    candidates = [
        build_candidate_for_failure(
            failure,
            episode_id=episode_id,
            asset_root=asset_root,
            catalog=catalog,
            seeds=seeds,
        )
        for failure in failures
    ]
    assert_under(strategy_candidate_dir, workspace / "episodes" / episode_id)
    package_root = strategy_candidate_dir / "candidate_packages"
    for candidate in candidates:
        package_dir = package_root / candidate["candidate_id"]
        write_json(package_dir / "candidate.json", candidate)
        write_json(package_dir / "asset_diff.json", candidate["asset_diff"])
        write_json(package_dir / "validation_plan.json", candidate["validation_plan"])
        write_json(
            package_dir / "evidence_pack.json",
            {
                "schema_version": 1,
                "candidate_id": candidate["candidate_id"],
                "source_episode_ids": candidate["source_episode_ids"],
                "source_failure_ids": candidate["source_failure_ids"],
                "source_failure": candidate["source_failure"],
            },
        )
    write_jsonl(strategy_candidate_dir / "candidate_improvements.jsonl", candidates)
    manifest = {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "generated_at": now_iso(),
        "episode_id": episode_id,
        "candidate_count": len(candidates),
        "source_failure_count": len(failures),
        "asset_root": str(asset_root),
        "auto_merge_allowed": False,
        "outputs": {
            "candidate_improvements": "candidate_improvements.jsonl",
            "candidate_packages": "candidate_packages/",
            "review": "strategy_candidate_review.html",
        },
    }
    write_json(strategy_candidate_dir / "MANIFEST.json", manifest)
    (strategy_candidate_dir / "strategy_candidate_review.html").write_text(render_review(candidates, episode_id), encoding="utf-8")
    return {
        "ok": True,
        "episode_id": episode_id,
        "strategy_candidate_dir": str(strategy_candidate_dir),
        "candidates": len(candidates),
        "review": str(strategy_candidate_dir / "strategy_candidate_review.html"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Strategy candidate improvement packages.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--asset-root", type=Path, default=strategy_registry.ASSET_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = generate_candidate_packages(
            args.episode_id,
            workspace=args.workspace,
            asset_root=args.asset_root,
        )
    except (StrategyCandidateError, strategy_registry.StrategyAssetError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

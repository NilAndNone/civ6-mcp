"""Offline Review v1 failure labeling for existing Observation episodes.

This module deliberately never starts Civilization VI and never writes outside
``episodes/<episode_id>/review``.  It turns already-recorded Observation evidence
into auditable candidate failures, then requires explicit human confirmation
before producing formal failures and passive regression seeds.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from codex_hl.evidence.store import EpisodeReader


ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
WORKFLOW_NAME = "Review Offline Failure Labeling"
TOOL_VERSION = "0.0.2"
CAVEAT_TEXT = (
    "该 high confidence 只适用于 T10/T20 local_episode_fragment；"
    "不是长期战略结论，不是资产修改证据，需要 T50 或 multi-episode follow-up。"
)

FORBIDDEN_FIELDS = {
    "suggested_fix",
    "asset_diff",
    "prompt_update",
    "playbook_change",
    "tool_policy_change",
    "memory_update",
    "strategy_patch",
    "replay_target",
    "rerun_command",
    "arena_run",
    "replay_from_save",
    "auto_rerun",
}
CONFIDENCE_VALUES = {"low", "medium", "high"}
CAPABILITY_CATEGORIES = {
    "planning",
    "execution",
    "memory/state",
    "tool grounding",
    "verification",
    "recovery",
    "unmapped",
}
FAILURE_TYPES = {"incident", "degradation", "misjudgment", "evidence_gap"}
LOCAL_FRAGMENT_MODES = {"short_validation", "t20_exploration"}
EPISODE_MODES = LOCAL_FRAGMENT_MODES | {"t50_observation", "multi_episode_followup"}
CONFIRMATION_ACTIONS = {"accept", "reject", "modify"}
MODIFIABLE_FIELDS = {
    "capability_category",
    "failure_type",
    "confidence",
    "confidence_rationale",
    "scope_caveats",
    "evidence_refs",
    "turn_range",
    "title",
    "description",
    "expected_behavior",
    "failed_behavior",
    "claim_scope",
}


class ReviewError(RuntimeError):
    """User-facing Review validation error."""


@dataclass
class EvidenceBundle:
    workspace: Path
    episode_id: str
    episode_root: Path
    review_dir: Path
    header: dict[str, Any]
    report_pack: dict[str, Any]
    decisions: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    mcp_events: list[dict[str, Any]]
    states: dict[str, dict[str, Any]]
    saves: list[dict[str, Any]]
    input_manifest: dict[str, Any]
    episode_mode: str
    turn_target: str
    start_turn: int | None
    final_turn: int | None
    actual_turns: int | None
    human_baseline_missing: bool
    storage_backend: str = "files"
    artifact_index: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def evidence_input_hash(self) -> str:
        return str(self.input_manifest["aggregate_sha256"])


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(*parts: Any, length: int = 16) -> str:
    payload = "\x1f".join(json.dumps(part, ensure_ascii=False, sort_keys=True) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def json_dumps(data: Any, *, indent: int | None = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Invalid JSON in {path}: {exc}") from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"Invalid JSONL in {path}:{line_no}: {exc}") from exc
        if not isinstance(value, dict):
            raise ReviewError(f"Expected object in {path}:{line_no}")
        rows.append(value)
    return rows


def assert_under(path: Path, base: Path) -> None:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise ReviewError(f"Refusing to write outside {base}: {path}") from exc


def atomic_write_text(path: Path, text: str, *, review_dir: Path | None = None) -> None:
    if review_dir is not None:
        assert_under(path, review_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, data: Any, *, review_dir: Path) -> None:
    atomic_write_text(path, json_dumps(data) + "\n", review_dir=review_dir)


def write_jsonl(path: Path, rows: list[dict[str, Any]], *, review_dir: Path) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n" for row in rows)
    atomic_write_text(path, text, review_dir=review_dir)


def append_jsonl(path: Path, row: dict[str, Any], *, review_dir: Path) -> None:
    assert_under(path, review_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def path_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def hash_paths(paths: list[Path], root: Path) -> dict[str, Any]:
    rows = []
    h = hashlib.sha256()
    for path in sorted(paths, key=lambda p: path_rel(p, root)):
        rel = path_rel(path, root)
        digest = sha256_file(path)
        rows.append(
            {
                "path": rel,
                "sha256": digest,
                "size_bytes": path.stat().st_size,
            }
        )
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\0")
    return {"sha256": h.hexdigest(), "files": rows}


def build_evidence_input_manifest(
    episode_root: Path, human_baseline_path: Path | None = None
) -> dict[str, Any]:
    required_rel = [
        "header.json",
        "raw/tool_calls.jsonl",
        "raw/mcp.jsonl",
        "raw/saves/save_index.jsonl",
        "derived/decision_atoms.jsonl",
        "derived/report_pack.json",
    ]
    reader = EpisodeReader(episode_root)

    if reader.backend == "sqlite":
        state_rels = reader.logical_paths(prefix="raw/civ6_states/")
        outcome_rels = [
            path
            for path in reader.logical_paths(prefix="outcome/")
            if "report" in Path(path).name
        ]
        missing = [path for path in required_rel if not reader.has_artifact(path)]
        if not state_rels:
            missing.append("raw/civ6_states/*.json")
        if not outcome_rels:
            missing.append("outcome/*report*")
        if missing:
            raise ReviewError(
                "Missing required Observation inputs: " + ", ".join(sorted(missing))
            )
        raw_rels = reader.logical_paths(prefix="raw/")
        observation_rels = sorted(set(required_rel + state_rels + raw_rels + outcome_rels))
    else:
        required = [episode_root / Path(path) for path in required_rel]
        state_files = sorted((episode_root / "raw" / "civ6_states").glob("*.json"))
        outcome_files = sorted((episode_root / "outcome").glob("*report*"))
        missing = [path_rel(path, episode_root) for path in required if not path.exists()]
        if not state_files:
            missing.append("raw/civ6_states/*.json")
        if not outcome_files:
            missing.append("outcome/*report*")
        if missing:
            raise ReviewError(
                "Missing required Observation inputs: " + ", ".join(sorted(missing))
            )

        raw_files = [p for p in (episode_root / "raw").rglob("*") if p.is_file()]
        observation_files = sorted(
            set(required + state_files + raw_files + outcome_files),
            key=lambda p: path_rel(p, episode_root),
        )
        observation_rels = [path_rel(path, episode_root) for path in observation_files]

    optional_inputs: list[dict[str, Any]] = []
    if human_baseline_path is not None:
        if not human_baseline_path.exists():
            raise ReviewError(f"Human baseline file not found: {human_baseline_path}")
        optional_inputs.append(
            {
                "path": str(human_baseline_path.resolve()),
                "sha256": sha256_file(human_baseline_path),
                "size_bytes": human_baseline_path.stat().st_size,
                "kind": "human_baseline",
            }
        )

    if reader.backend == "sqlite":
        files_hash = reader.hash_logical_paths(observation_rels)
        groups = {
            "header": reader.hash_logical_paths(["header.json"]),
            "raw": reader.hash_logical_paths(reader.logical_paths(prefix="raw/")),
            "decision_atoms": reader.hash_logical_paths(["derived/decision_atoms.jsonl"]),
            "report_pack": reader.hash_logical_paths(["derived/report_pack.json"]),
            "outcome_observation": reader.hash_logical_paths(outcome_rels),
        }
    else:
        observation_files = [episode_root / Path(path) for path in observation_rels]
        files_hash = hash_paths(observation_files, episode_root)
        groups = {
            "header": hash_paths([episode_root / "header.json"], episode_root),
            "raw": hash_paths(
                [episode_root / Path(path) for path in observation_rels if path.startswith("raw/")],
                episode_root,
            ),
            "decision_atoms": hash_paths(
                [episode_root / "derived" / "decision_atoms.jsonl"], episode_root
            ),
            "report_pack": hash_paths(
                [episode_root / "derived" / "report_pack.json"], episode_root
            ),
            "outcome_observation": hash_paths(
                [
                    episode_root / Path(path)
                    for path in observation_rels
                    if path.startswith("outcome/") and "report" in Path(path).name
                ],
                episode_root,
            ),
        }
    aggregate = hashlib.sha256()
    aggregate.update(files_hash["sha256"].encode("ascii"))
    for item in optional_inputs:
        aggregate.update(str(item["path"]).encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(item["sha256"]).encode("ascii"))
        aggregate.update(b"\0")

    return {
        "generated_at": now_iso(),
        "storage_backend": reader.backend,
        "aggregate_sha256": aggregate.hexdigest(),
        "groups": groups,
        "files": files_hash["files"],
        "optional_inputs": optional_inputs,
        "protected_inputs": [
            "header.json",
            "raw/",
            "derived/decision_atoms.jsonl",
            "derived/report_pack.json",
            "outcome/*report*",
        ],
    }


def detect_episode_mode(
    header: dict[str, Any], report_pack: dict[str, Any]
) -> tuple[str, str, int | None, int | None, int | None]:
    run = report_pack.get("run", {}) if isinstance(report_pack.get("run"), dict) else {}
    actual_turns = run.get("actual_turns") or header.get("requested_turns")
    start_turn = run.get("start_turn")
    final_turn = run.get("final_turn")
    mode = header.get("observation_mode")
    if mode not in EPISODE_MODES:
        if actual_turns == 50:
            mode = "t50_observation"
        elif actual_turns == 20:
            mode = "t20_exploration"
        elif isinstance(actual_turns, int) and actual_turns <= 20:
            mode = "short_validation"
        else:
            mode = "multi_episode_followup"

    if mode == "t50_observation":
        turn_target = "T50"
    elif isinstance(actual_turns, int) and actual_turns > 10:
        turn_target = "T20"
    else:
        turn_target = "T10"
    return mode, turn_target, start_turn, final_turn, actual_turns


def is_local_fragment_mode(mode: Any) -> bool:
    return str(mode) in LOCAL_FRAGMENT_MODES


def load_evidence_bundle(
    episode_id: str,
    *,
    workspace: Path = ROOT,
    human_baseline_path: Path | None = None,
) -> EvidenceBundle:
    workspace = workspace.resolve()
    episode_root = workspace / "episodes" / episode_id
    if not episode_root.exists():
        raise ReviewError(f"Episode not found: {episode_root}")
    review_dir = episode_root / "review"
    reader = EpisodeReader(episode_root)
    input_manifest = build_evidence_input_manifest(episode_root, human_baseline_path)
    header = reader.read_json("header.json")
    report_pack = reader.read_json("derived/report_pack.json")
    decisions = reader.read_jsonl("derived/decision_atoms.jsonl")
    tool_calls = reader.read_jsonl("raw/tool_calls.jsonl")
    mcp_events = reader.read_jsonl("raw/mcp.jsonl")
    saves = reader.read_jsonl("raw/saves/save_index.jsonl")
    states: dict[str, dict[str, Any]] = {}
    for state_path, state in reader.state_rows():
        snapshot_id = str(state.get("snapshot_id") or Path(state_path).stem)
        states[snapshot_id] = state

    mode, turn_target, start_turn, final_turn, actual_turns = detect_episode_mode(
        header, report_pack
    )
    baseline_present = bool(human_baseline_path) or bool(
        header.get("human_baseline_ref")
        or report_pack.get("human_baseline")
        or report_pack.get("human_baseline_ref")
    )
    return EvidenceBundle(
        workspace=workspace,
        episode_id=episode_id,
        episode_root=episode_root,
        review_dir=review_dir,
        header=header,
        report_pack=report_pack,
        decisions=decisions,
        tool_calls=tool_calls,
        mcp_events=mcp_events,
        states=states,
        saves=saves,
        input_manifest=input_manifest,
        episode_mode=mode,
        turn_target=turn_target,
        start_turn=start_turn,
        final_turn=final_turn,
        actual_turns=actual_turns,
        human_baseline_missing=not baseline_present,
        storage_backend=reader.backend,
        artifact_index={
            file_row["path"]: file_row
            for file_row in input_manifest.get("files", [])
            if isinstance(file_row, dict) and file_row.get("path")
        },
    )


def unique_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ref in refs:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def refs_for_decisions(bundle: EvidenceBundle, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = [
        {"kind": "episode", "id": bundle.episode_id},
        {"kind": "report_pack", "path": "derived/report_pack.json"},
    ]
    for decision in decisions:
        decision_id = str(decision.get("decision_id", ""))
        if decision_id:
            refs.append(
                {
                    "kind": "decision_atom",
                    "id": decision_id,
                    "path": "derived/decision_atoms.jsonl",
                    "turn": decision.get("turn"),
                }
            )
        evidence_ids = decision.get("evidence_ids") if isinstance(decision.get("evidence_ids"), dict) else {}
        for state_id in evidence_ids.get("state_snapshot_ids") or decision.get("related_state_snapshot_ids") or []:
            refs.append(
                {
                    "kind": "state_snapshot",
                    "id": state_id,
                    "path": f"raw/civ6_states/{state_id}.json",
                    "turn": decision.get("turn"),
                }
            )
        for tool_id in evidence_ids.get("tool_call_ids") or decision.get("related_tool_call_ids") or []:
            refs.append(
                {
                    "kind": "tool_call",
                    "id": tool_id,
                    "path": "raw/tool_calls.jsonl",
                    "turn": decision.get("turn"),
                }
            )
        for save_id in evidence_ids.get("save_ids") or decision.get("related_save_ids") or []:
            refs.append(
                {
                    "kind": "save",
                    "id": save_id,
                    "path": "raw/saves/save_index.jsonl",
                    "turn": decision.get("turn"),
                }
            )
    return unique_refs(refs)


def refs_for_report(bundle: EvidenceBundle, *, reason: str) -> list[dict[str, Any]]:
    return [
        {"kind": "episode", "id": bundle.episode_id},
        {"kind": "report_pack", "path": "derived/report_pack.json", "reason": reason},
    ]


def state_turn(state: dict[str, Any]) -> int:
    value = state.get("turn")
    return value if isinstance(value, int) else -1


def latest_state_entry(bundle: EvidenceBundle) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    if not bundle.states:
        return None, None
    return max(bundle.states.items(), key=lambda item: state_turn(item[1]))


def state_overview(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    overview = state.get("overview")
    if isinstance(overview, dict):
        return overview
    snapshot = state.get("snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("overview"), dict):
        return snapshot["overview"]
    return {}


def state_units(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    units = state.get("units")
    if isinstance(units, list):
        return [unit for unit in units if isinstance(unit, dict)]
    snapshot = state.get("snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("units"), list):
        return [unit for unit in snapshot["units"] if isinstance(unit, dict)]
    return []


def count_unit_type(state: dict[str, Any] | None, unit_type: str) -> int:
    return sum(1 for unit in state_units(state) if unit.get("unit_type") == unit_type)


def state_city_count(state: dict[str, Any] | None) -> int | None:
    count = state_overview(state).get("num_cities")
    return count if isinstance(count, int) else None


def max_city_count_entry(
    bundle: EvidenceBundle,
) -> tuple[str | None, dict[str, Any] | None, int | None]:
    best_id: str | None = None
    best_state: dict[str, Any] | None = None
    best_count: int | None = None
    for state_id, state in bundle.states.items():
        count = state_city_count(state)
        if isinstance(count, int) and (best_count is None or count > best_count):
            best_id = state_id
            best_state = state
            best_count = count
    return best_id, best_state, best_count


def ref_for_state(state_id: str | None, state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state_id:
        return None
    return {
        "kind": "state_snapshot",
        "id": state_id,
        "path": f"raw/civ6_states/{state_id}.json",
        "turn": state_turn(state or {}),
    }


def add_storage_ref(bundle: EvidenceBundle, ref: dict[str, Any]) -> dict[str, Any]:
    out = dict(ref)
    path = out.get("path")
    if isinstance(path, str):
        artifact = bundle.artifact_index.get(path)
        if artifact:
            out.setdefault("storage_backend", artifact.get("storage_backend", bundle.storage_backend))
            if artifact.get("artifact_id") is not None:
                out.setdefault("artifact_id", artifact.get("artifact_id"))
            if artifact.get("sha256") is not None:
                out.setdefault("sha256", artifact.get("sha256"))
    elif out.get("kind") == "episode":
        out.setdefault("storage_backend", bundle.storage_backend)
    return out


def add_storage_refs(bundle: EvidenceBundle, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [add_storage_ref(bundle, ref) for ref in refs]


def make_candidate(
    bundle: EvidenceBundle,
    *,
    rule_id: str,
    title: str,
    description: str,
    capability_category: str,
    failure_type: str,
    confidence: str,
    confidence_rationale: str,
    evidence_refs: list[dict[str, Any]],
    expected_behavior: str | None,
    failed_behavior: str,
    turn_range: list[int | None],
    source_analyzer_run_id: str,
    prompt_hash: str,
    session_id: str | None,
    source_kind: str = "heuristic",
    scope_caveats: list[str] | None = None,
    extra_identity: Any = None,
) -> dict[str, Any]:
    if capability_category not in CAPABILITY_CATEGORIES:
        raise ReviewError(f"Invalid capability_category: {capability_category}")
    if failure_type not in FAILURE_TYPES:
        raise ReviewError(f"Invalid failure_type: {failure_type}")
    if confidence not in CONFIDENCE_VALUES:
        raise ReviewError(f"Invalid confidence: {confidence}")
    caveats = list(scope_caveats or [])
    candidate = {
        "candidate_id": "cand_"
        + stable_id(bundle.episode_id, rule_id, extra_identity or evidence_refs, length=12),
        "episode_id": bundle.episode_id,
        "episode_mode": bundle.episode_mode,
        "turn_target": bundle.turn_target,
        "turn_range": turn_range,
        "capability_category": capability_category,
        "failure_type": failure_type,
        "title": title,
        "description": description,
        "expected_behavior": expected_behavior,
        "failed_behavior": failed_behavior,
        "evidence_refs": add_storage_refs(bundle, evidence_refs),
        "source_analyzer_run_id": source_analyzer_run_id,
        "source_kind": source_kind,
        "model": None,
        "provider": None,
        "temperature": None,
        "session_id": session_id,
        "prompt_hash": prompt_hash,
        "input_hash": bundle.evidence_input_hash,
        "confidence": confidence,
        "confidence_rationale": confidence_rationale,
        "scope_caveats": caveats,
        "human_status": "pending",
        "human_baseline_missing": bundle.human_baseline_missing,
        "created_at": now_iso(),
    }
    if is_local_fragment_mode(bundle.episode_mode) and capability_category == "planning":
        candidate["claim_scope"] = "local_episode_fragment"
        candidate["not_a_long_horizon_conclusion"] = True
        candidate["not_evidence_for_asset_change"] = True
        candidate["requires_t50_or_multi_episode_followup"] = True
        if CAVEAT_TEXT not in candidate["scope_caveats"]:
            candidate["scope_caveats"].append(CAVEAT_TEXT)
    return candidate


def text_blob(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()


def decision_turn_range(decisions: list[dict[str, Any]], bundle: EvidenceBundle) -> list[int | None]:
    turns = [d.get("turn") for d in decisions if isinstance(d.get("turn"), int)]
    if not turns:
        return [bundle.start_turn, bundle.final_turn]
    return [min(turns), max(turns)]


def generate_rule_candidates(
    bundle: EvidenceBundle,
    *,
    analyzer_run_id: str,
    prompt_hash: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if is_local_fragment_mode(bundle.episode_mode) and bundle.human_baseline_missing:
        candidates.append(
            make_candidate(
                bundle,
                rule_id="short_validation_human_baseline_missing",
                title="短跑缺少人类基线，候选判断需要人工补证",
                description=(
                    "该 episode 可进入候选审阅，但没有记录同局面的人类 T10/T20 基线；"
                    "正式确认前需要人工判断这些差异是否真是失败。"
                ),
                capability_category="verification",
                failure_type="evidence_gap",
                confidence="low",
                confidence_rationale="Observation report_pack 没有人类基线引用。",
                evidence_refs=refs_for_report(bundle, reason="human_baseline_missing"),
                expected_behavior="短跑审阅最好包含同任务、同开局的人类 T10/T20 简短基线。",
                failed_behavior="当前 episode 没有可机器验证的人类基线引用。",
                turn_range=[bundle.start_turn, bundle.final_turn],
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                scope_caveats=["missing_human_baseline=true"],
                extra_identity="human_baseline_missing",
            )
        )

    hold_decisions = [
        d
        for d in bundle.decisions
        if ("fortify" in text_blob(d.get("selected_action")) or "驻守" in text_blob(d.get("selected_action")))
        and ("unit" in text_blob(d.get("trigger")) or "勇士" in text_blob(d))
    ]
    if hold_decisions:
        decision_ids = [str(d.get("decision_id")) for d in hold_decisions if d.get("decision_id")]
        candidates.append(
            make_candidate(
                bundle,
                rule_id="early_unit_hold_review",
                title="早期单位持续驻守可能错过探索价值",
                description=(
                    "短跑中单位行动多次选择驻守/hold。该行为可能只是 Observation 为避免推测性操作的保守边界，"
                    "也可能在 T10/T20 人类基线对照下暴露探索规划失败。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="medium",
                confidence_rationale=(
                    "检测到早期单位驻守决策；需要人工基线判断这是否低于合理玩家的探索节奏。"
                ),
                evidence_refs=refs_for_decisions(bundle, hold_decisions[:6]),
                expected_behavior="在短跑局部片段中，单位行动应能说明探索、驻守或跳过的局部收益取舍。",
                failed_behavior=(
                    "单位被保守驻守，证据中没有可审计的探索目标或与人类基线的差异解释。"
                ),
                turn_range=decision_turn_range(hold_decisions, bundle),
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity=decision_ids,
            )
        )

    builder_decisions = [
        d
        for d in bundle.decisions
        if (
            "builder" in text_blob(d.get("selected_action"))
            or "建造者" in text_blob(d.get("selected_action"))
        )
        and (
            "scout" in text_blob(d.get("available_actions"))
            or "侦察兵" in text_blob(d.get("available_actions"))
        )
    ]
    if builder_decisions:
        decision_ids = [str(d.get("decision_id")) for d in builder_decisions if d.get("decision_id")]
        candidates.append(
            make_candidate(
                bundle,
                rule_id="early_production_builder_over_scout_review",
                title="早期生产选择建造者而非侦察兵需要人类基线审阅",
                description=(
                    "城市早期生产在可选侦察兵时选择建造者。该选择可能合理，但 Review v1 需要把"
                    "与人类 T10/T20 基线的差异显式放入审阅队列。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="medium",
                confidence_rationale="检测到早期生产候选包含侦察兵而实际选择建造者。",
                evidence_refs=refs_for_decisions(bundle, builder_decisions),
                expected_behavior="早期生产选择应能解释探索、改良和增长节奏之间的局部取舍。",
                failed_behavior="选择建造者的证据缺少与人类短跑基线的显式差异说明。",
                turn_range=decision_turn_range(builder_decisions, bundle),
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity=decision_ids,
            )
        )

    mining_decisions = [
        d
        for d in bundle.decisions
        if "tech_mining" in text_blob(d.get("selected_action"))
        or "采矿业" in text_blob(d.get("selected_action"))
    ]
    if mining_decisions:
        decision_ids = [str(d.get("decision_id")) for d in mining_decisions if d.get("decision_id")]
        candidates.append(
            make_candidate(
                bundle,
                rule_id="opening_research_static_priority_review",
                title="开局科技按固定优先级选择，需要审阅是否偏离局面",
                description=(
                    "Observation 记录显示科技选择来自固定早期优先级，而不是从当前地图资源、人类基线"
                    "或可见目标推导。Review 只把它作为候选，不直接判定失败。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="low",
                confidence_rationale="固定优先级本身不足以证明失败，但适合进入短跑审阅。",
                evidence_refs=refs_for_decisions(bundle, mining_decisions),
                expected_behavior="短跑审阅应能说明开局科技选择是否与局面和人类基线一致。",
                failed_behavior="当前证据只说明使用了固定优先级，缺少与局面目标的显式比较。",
                turn_range=decision_turn_range(mining_decisions, bundle),
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity=decision_ids,
            )
        )

    latest_state_id, latest_state = latest_state_entry(bundle)
    overview = state_overview(latest_state)
    scout_count = count_unit_type(latest_state, "UNIT_SCOUT")
    city_count = overview.get("num_cities")
    scout_production_decisions = [
        d
        for d in bundle.decisions
        if "unit_scout" in text_blob(d.get("selected_action"))
        and "production" in text_blob(d.get("trigger"))
    ]
    if (
        bundle.episode_mode == "t50_observation"
        and isinstance(city_count, int)
        and city_count <= 1
        and scout_count >= 4
        and scout_production_decisions
    ):
        refs = refs_for_decisions(bundle, scout_production_decisions[-6:])
        state_ref = ref_for_state(latest_state_id, latest_state)
        if state_ref:
            refs.append(state_ref)
        candidates.append(
            make_candidate(
                bundle,
                rule_id="t50_over_scout_no_expansion_review",
                title="T50 过度生产侦察兵导致扩张停滞",
                description=(
                    "T50 最终状态显示城市数仍为 1，且单位构成中过多侦察兵；"
                    "生产决策多次继续选择 UNIT_SCOUT，需要确认探索收益是否已经压过扩张节奏。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="medium",
                confidence_rationale=(
                    f"T50 final: cities={city_count}, scouts={scout_count}; "
                    f"scout production decisions={len(scout_production_decisions)}."
                ),
                evidence_refs=unique_refs(refs),
                expected_behavior=(
                    "完整 T50 运行中，开局探索应有上限；达到基本地图信息后应转向 settler/builder "
                    "或其他扩张、成长、科研节奏。"
                ),
                failed_behavior=(
                    f"T50 仍只有 {city_count} 城且有 {scout_count} 个侦察兵，"
                    "证据显示 production selector 没有从探索切换到扩张。"
                ),
                turn_range=decision_turn_range(scout_production_decisions, bundle),
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity={
                    "latest_state_id": latest_state_id,
                    "city_count": city_count,
                    "scout_count": scout_count,
                    "decision_ids": [
                        d.get("decision_id") for d in scout_production_decisions[-6:]
                    ],
                },
            )
        )

    settler_count = count_unit_type(latest_state, "UNIT_SETTLER")
    blocked_settler_decisions = [
        d
        for d in bundle.decisions
        if "expansion settler action" in text_blob(d.get("trigger"))
        and "blocked" in text_blob(d.get("outcome"))
    ]
    if (
        bundle.episode_mode == "t50_observation"
        and isinstance(city_count, int)
        and city_count < 3
        and (settler_count > 0 or len(blocked_settler_decisions) >= 2)
    ):
        refs = refs_for_decisions(bundle, blocked_settler_decisions[-6:])
        if not blocked_settler_decisions:
            refs = refs_for_report(bundle, reason="settler_unsettled_at_t50")
        state_ref = ref_for_state(latest_state_id, latest_state)
        if state_ref:
            refs.append(state_ref)
        candidates.append(
            make_candidate(
                bundle,
                rule_id="t50_settler_pathing_or_unsettled_review",
                title="T50 settler 扩张路径未稳定转化为第三城",
                description=(
                    "T50 证据显示城市数仍低于 3，且 settler 仍未落城或扩张路径多次 BLOCKED；"
                    "需要审阅 settle target 选择、路径阻塞处理和护送风险。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="medium",
                confidence_rationale=(
                    f"T50 final: cities={city_count}, settlers={settler_count}, "
                    f"blocked_settler_moves={len(blocked_settler_decisions)}."
                ),
                evidence_refs=unique_refs(refs),
                expected_behavior=(
                    "T50 扩张策略应把至少一个后续 settler 稳定转化为新增城市；"
                    "遇到 BLOCKED 路径时应切换候选目标或保守重规划。"
                ),
                failed_behavior=(
                    f"T50 仍只有 {city_count} 城，settler_count={settler_count}，"
                    f"blocked settler move decisions={len(blocked_settler_decisions)}。"
                ),
                turn_range=decision_turn_range(blocked_settler_decisions, bundle),
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity={
                    "latest_state_id": latest_state_id,
                    "city_count": city_count,
                    "settler_count": settler_count,
                    "blocked_decision_ids": [
                        d.get("decision_id") for d in blocked_settler_decisions[-6:]
                    ],
                },
            )
        )

    builder_count = count_unit_type(latest_state, "UNIT_BUILDER")
    builder_skip_decisions = [
        d
        for d in bundle.decisions
        if "unit action review unit_builder" in text_blob(d.get("trigger"))
        and "skip" in text_blob(d.get("selected_action"))
    ]
    if (
        bundle.episode_mode == "t50_observation"
        and builder_count >= 3
        and len(builder_skip_decisions) >= 3
    ):
        refs = refs_for_decisions(bundle, builder_skip_decisions[-8:])
        state_ref = ref_for_state(latest_state_id, latest_state)
        if state_ref:
            refs.append(state_ref)
        candidates.append(
            make_candidate(
                bundle,
                rule_id="t50_idle_builder_overproduction_review",
                title="T50 builder 过量且未转化为改良",
                description=(
                    "T50 证据显示多个 builder 留在单位列表中，并且多次 builder 行动被 skip；"
                    "需要确认生产上限和 builder 任务执行是否把建造者转化为实际地块改良。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="medium",
                confidence_rationale=(
                    f"T50 final: builders={builder_count}; "
                    f"builder skip decisions={len(builder_skip_decisions)}."
                ),
                evidence_refs=unique_refs(refs),
                expected_behavior=(
                    "T50 中期以后 builder 应有生产上限，并应移动到高价值任务格执行改良；"
                    "若任务不可达，应转向 trader/district/building，而不是继续堆积 builder。"
                ),
                failed_behavior=(
                    f"T50 仍有 {builder_count} 个 builder，且记录到 "
                    f"{len(builder_skip_decisions)} 次 builder skip。"
                ),
                turn_range=decision_turn_range(builder_skip_decisions, bundle),
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity={
                    "latest_state_id": latest_state_id,
                    "builder_count": builder_count,
                    "builder_skip_decision_ids": [
                        d.get("decision_id") for d in builder_skip_decisions[-8:]
                    ],
                },
            )
        )

    max_city_state_id, max_city_state, max_city_count = max_city_count_entry(bundle)
    if (
        bundle.episode_mode == "t50_observation"
        and isinstance(city_count, int)
        and isinstance(max_city_count, int)
        and max_city_count > city_count
        and max_city_count >= 3
    ):
        refs = refs_for_report(bundle, reason="city_count_regressed_before_t50")
        max_ref = ref_for_state(max_city_state_id, max_city_state)
        final_ref = ref_for_state(latest_state_id, latest_state)
        if max_ref:
            refs.append(max_ref)
        if final_ref:
            refs.append(final_ref)
        candidates.append(
            make_candidate(
                bundle,
                rule_id="t50_city_count_regressed_review",
                title="T50 前已扩张城市数回落",
                description=(
                    "Episode 中曾达到至少 3 城，但 T50 最终城市数更低；"
                    "需要审阅新城防守、敌军威胁、settler/escort 和中期生产节奏。"
                ),
                capability_category="planning",
                failure_type="misjudgment",
                confidence="medium",
                confidence_rationale=(
                    f"max_cities={max_city_count}; final_cities={city_count}; "
                    f"max_state={max_city_state_id}; final_state={latest_state_id}."
                ),
                evidence_refs=unique_refs(refs),
                expected_behavior=(
                    "T50 策略不仅要落第三城，还要通过足够的防守、驻军或保守扩张维持城市数。"
                ),
                failed_behavior=(
                    f"城市数曾达到 {max_city_count}，但 T50 结算只有 {city_count}。"
                ),
                turn_range=[bundle.start_turn, bundle.final_turn],
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                extra_identity={
                    "max_state_id": max_city_state_id,
                    "latest_state_id": latest_state_id,
                    "max_city_count": max_city_count,
                    "final_city_count": city_count,
                },
            )
        )

    failed_tool_calls = [
        row for row in bundle.tool_calls if row.get("success") is False or row.get("error")
    ]
    if failed_tool_calls:
        refs = refs_for_report(bundle, reason="tool_call_errors")
        for row in failed_tool_calls[:5]:
            refs.append(
                {
                    "kind": "tool_call",
                    "id": row.get("tool_call_id"),
                    "path": "raw/tool_calls.jsonl",
                    "turn": row.get("turn"),
                }
            )
        candidates.append(
            make_candidate(
                bundle,
                rule_id="tool_call_error_review",
                title="Observation 工具错误需要确认是否影响 episode 可信度",
                description="Observation 证据中存在失败的高层工具调用；需要审阅它是否只是可恢复事件，还是影响结论的执行/验证失败。",
                capability_category="tool grounding",
                failure_type="incident",
                confidence="low",
                confidence_rationale="工具错误已在 raw/tool_calls.jsonl 中保留，但 report_pack 可能仍整体 PASS。",
                evidence_refs=unique_refs(refs),
                expected_behavior="工具错误应可追踪，并且不应破坏短跑证据链。",
                failed_behavior="至少一个工具调用失败，需要人工判断影响范围。",
                turn_range=[bundle.start_turn, bundle.final_turn],
                source_analyzer_run_id=analyzer_run_id,
                prompt_hash=prompt_hash,
                session_id=session_id,
                scope_caveats=["tool error may be recovered by later evidence"],
                extra_identity=[row.get("tool_call_id") for row in failed_tool_calls[:5]],
            )
        )

    evidence_status = bundle.report_pack.get("evidence_status")
    if isinstance(evidence_status, dict):
        failed_sections = [
            name
            for name, section in evidence_status.items()
            if isinstance(section, dict) and section.get("status") != "PASS"
        ]
        if failed_sections:
            candidates.append(
                make_candidate(
                    bundle,
                    rule_id="observation_evidence_status_gap",
                    title="Observation 四类证据存在未通过项",
                    description="report_pack.evidence_status 中至少一项不是 PASS，Review 只能生成 evidence_gap 候选。",
                    capability_category="verification",
                    failure_type="evidence_gap",
                    confidence="medium",
                    confidence_rationale=f"未通过项：{', '.join(failed_sections)}。",
                    evidence_refs=refs_for_report(bundle, reason="evidence_status_not_pass"),
                    expected_behavior="Observation episode 应完整覆盖工具日志、状态快照、决策记录和存档关联。",
                    failed_behavior="至少一个 Observation 证据类别未通过本地报告契约。",
                    turn_range=[bundle.start_turn, bundle.final_turn],
                    source_analyzer_run_id=analyzer_run_id,
                    prompt_hash=prompt_hash,
                    session_id=session_id,
                    extra_identity=failed_sections,
                )
            )

    return dedupe_candidates(candidates)


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        cid = str(candidate.get("candidate_id"))
        if cid in seen:
            continue
        seen.add(cid)
        out.append(candidate)
    return out


def build_analyzer_prompt(bundle: EvidenceBundle) -> str:
    run = bundle.report_pack.get("run", {})
    counts = bundle.report_pack.get("counts", {})
    return (
        "Review v1 rules-only analyzer input\n"
        f"episode_id: {bundle.episode_id}\n"
        f"episode_mode: {bundle.episode_mode}\n"
        f"turn_target: {bundle.turn_target}\n"
        f"turn_range: {run.get('start_turn')}..{run.get('final_turn')}\n"
        f"actual_turns: {run.get('actual_turns')}\n"
        f"counts: {json.dumps(counts, ensure_ascii=False, sort_keys=True)}\n"
        "contract: generate candidate failures only; do not write formal failures, seeds, "
        "replay commands, asset changes, or strategy fixes.\n"
    )


def archive_analyzer_run(
    bundle: EvidenceBundle,
    *,
    run_id: str,
    prompt_text: str,
    candidates: list[dict[str, Any]],
    session_id: str | None,
) -> None:
    run_dir = bundle.review_dir / "analyzer_runs" / run_id
    prompt_hash = sha256_text(prompt_text)
    provenance = {
        "run_id": run_id,
        "episode_id": bundle.episode_id,
        "source_kind": "heuristic",
        "analyzer": "deterministic_rules",
        "provider": None,
        "model": None,
        "temperature": None,
        "session_id": session_id,
        "prompt_hash": prompt_hash,
        "input_hash": bundle.evidence_input_hash,
        "created_at": now_iso(),
        "note": "Rules-only candidate generator; no external model API call was made.",
    }
    llm_request = {
        "kind": "deterministic_rules",
        "external_model_api_called": False,
        "allowed_outputs": ["candidate_failures"],
        "forbidden_fields": sorted(FORBIDDEN_FIELDS),
    }
    llm_response = {
        "kind": "rules_only_result",
        "candidate_count": len(candidates),
        "llm_unavailable": True,
        "note": "No LLM response is present because the plugin does not call external model APIs in v1.",
    }
    dedupe = {
        "strategy": "stable candidate_id from episode, rule, and evidence identity",
        "candidate_ids": [candidate["candidate_id"] for candidate in candidates],
        "duplicates_removed": 0,
    }
    write_json(run_dir / "provenance.json", provenance, review_dir=bundle.review_dir)
    write_json(run_dir / "input_manifest.json", bundle.input_manifest, review_dir=bundle.review_dir)
    atomic_write_text(run_dir / "prompt.txt", prompt_text, review_dir=bundle.review_dir)
    write_json(run_dir / "llm_request.json", llm_request, review_dir=bundle.review_dir)
    write_json(run_dir / "llm_response.raw.json", llm_response, review_dir=bundle.review_dir)
    write_jsonl(run_dir / "candidate_failures.jsonl", candidates, review_dir=bundle.review_dir)
    write_json(run_dir / "dedupe_manifest.json", dedupe, review_dir=bundle.review_dir)


def contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_FIELDS:
                return key
            found = contains_forbidden_key(nested)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = contains_forbidden_key(item)
            if found:
                return found
    return None


def validate_candidate(candidate: dict[str, Any]) -> None:
    required = [
        "candidate_id",
        "episode_id",
        "episode_mode",
        "capability_category",
        "failure_type",
        "confidence",
        "confidence_rationale",
        "evidence_refs",
        "source_analyzer_run_id",
        "source_kind",
        "prompt_hash",
        "input_hash",
        "scope_caveats",
        "human_status",
    ]
    missing = [field for field in required if field not in candidate]
    if missing:
        raise ReviewError(
            f"Candidate {candidate.get('candidate_id', '<unknown>')} missing fields: {', '.join(missing)}"
        )
    forbidden = contains_forbidden_key(candidate)
    if forbidden:
        raise ReviewError(
            f"Candidate {candidate.get('candidate_id')} contains forbidden field: {forbidden}"
        )
    if candidate["episode_mode"] not in EPISODE_MODES:
        raise ReviewError(f"Invalid episode_mode in candidate {candidate['candidate_id']}")
    if candidate["capability_category"] not in CAPABILITY_CATEGORIES:
        raise ReviewError(f"Invalid capability_category in candidate {candidate['candidate_id']}")
    if candidate["failure_type"] not in FAILURE_TYPES:
        raise ReviewError(f"Invalid failure_type in candidate {candidate['candidate_id']}")
    if candidate["confidence"] not in CONFIDENCE_VALUES:
        raise ReviewError(f"Invalid confidence in candidate {candidate['candidate_id']}")
    if candidate["source_kind"] not in {"heuristic", "llm", "merged"}:
        raise ReviewError(f"Invalid source_kind in candidate {candidate['candidate_id']}")
    if candidate["human_status"] != "pending":
        raise ReviewError(f"Candidate {candidate['candidate_id']} must start with human_status=pending")
    if not isinstance(candidate["evidence_refs"], list) or not candidate["evidence_refs"]:
        raise ReviewError(f"Candidate {candidate['candidate_id']} needs evidence_refs")
    if not isinstance(candidate["scope_caveats"], list):
        raise ReviewError(f"Candidate {candidate['candidate_id']} scope_caveats must be a list")


def validate_evidence_refs(bundle: EvidenceBundle, refs: list[dict[str, Any]]) -> None:
    decision_ids = {str(row.get("decision_id")) for row in bundle.decisions}
    tool_ids = {str(row.get("tool_call_id")) for row in bundle.tool_calls}
    mcp_ids = {str(row.get("call_id")) for row in bundle.mcp_events}
    state_ids = set(bundle.states)
    save_ids = {str(row.get("save_id")) for row in bundle.saves}
    for ref in refs:
        kind = ref.get("kind")
        ref_id = ref.get("id")
        if kind == "episode":
            if ref_id != bundle.episode_id:
                raise ReviewError(f"Evidence ref episode mismatch: {ref}")
        elif kind == "decision_atom":
            if str(ref_id) not in decision_ids:
                raise ReviewError(f"Unknown decision evidence ref: {ref}")
        elif kind == "tool_call":
            if str(ref_id) not in tool_ids:
                raise ReviewError(f"Unknown tool_call evidence ref: {ref}")
        elif kind == "mcp_event":
            if str(ref_id) not in mcp_ids:
                raise ReviewError(f"Unknown mcp_event evidence ref: {ref}")
        elif kind == "state_snapshot":
            if str(ref_id) not in state_ids:
                raise ReviewError(f"Unknown state_snapshot evidence ref: {ref}")
        elif kind == "save":
            if str(ref_id) not in save_ids:
                raise ReviewError(f"Unknown save evidence ref: {ref}")
        elif kind == "report_pack":
            if "derived/report_pack.json" not in bundle.artifact_index and not (
                bundle.episode_root / "derived" / "report_pack.json"
            ).exists():
                raise ReviewError(f"Missing report_pack for evidence ref: {ref}")
        elif kind == "absent_evidence":
            if not ref.get("reason"):
                raise ReviewError(f"absent_evidence ref requires reason: {ref}")
        else:
            raise ReviewError(f"Unsupported evidence ref kind: {ref}")


def load_review_candidates(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    path = bundle.review_dir / "candidates.jsonl"
    if not path.exists():
        raise ReviewError(f"Missing candidates.jsonl. Run candidate generation first: {path}")
    candidates = read_jsonl(path)
    for candidate in candidates:
        validate_candidate(candidate)
        validate_evidence_refs(bundle, candidate["evidence_refs"])
    return candidates


def load_confirmation_rows(path: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    for row in rows:
        candidate_id = row.get("candidate_id")
        action = row.get("action")
        if not candidate_id:
            raise ReviewError(f"Confirmation row missing candidate_id: {row}")
        if action not in CONFIRMATION_ACTIONS:
            raise ReviewError(f"Invalid confirmation action for {candidate_id}: {action}")
        if action == "modify" and not isinstance(row.get("modified_fields"), dict):
            raise ReviewError(f"modify confirmation needs modified_fields object: {candidate_id}")
        if contains_forbidden_key(row):
            forbidden = contains_forbidden_key(row)
            raise ReviewError(f"Confirmation row contains forbidden field {forbidden}: {candidate_id}")
    return rows


def latest_confirmation_by_candidate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[str(row["candidate_id"])] = row
    return out


def apply_modified_fields(candidate: dict[str, Any], modified_fields: dict[str, Any]) -> dict[str, Any]:
    disallowed = sorted(set(modified_fields) - MODIFIABLE_FIELDS)
    if disallowed:
        raise ReviewError(
            f"modified_fields contains unsupported keys for {candidate['candidate_id']}: {', '.join(disallowed)}"
        )
    merged = dict(candidate)
    for key, value in modified_fields.items():
        merged[key] = value
    validate_candidate({**merged, "human_status": "pending"})
    return merged


def enforce_short_planning_caveat(row: dict[str, Any]) -> dict[str, Any]:
    if is_local_fragment_mode(row.get("episode_mode")) and row.get("capability_category") == "planning":
        row["claim_scope"] = "local_episode_fragment"
        row["not_a_long_horizon_conclusion"] = True
        row["not_evidence_for_asset_change"] = True
        row["requires_t50_or_multi_episode_followup"] = True
        caveats = list(row.get("scope_caveats") or [])
        if CAVEAT_TEXT not in caveats:
            caveats.append(CAVEAT_TEXT)
        row["scope_caveats"] = caveats
    return row


def build_failure(
    bundle: EvidenceBundle,
    candidate: dict[str, Any],
    confirmation: dict[str, Any],
) -> dict[str, Any]:
    candidate = enforce_short_planning_caveat(dict(candidate))
    rationale = (
        confirmation.get("reviewer_note")
        or candidate.get("confidence_rationale")
        or "Human reviewer accepted this candidate."
    )
    failure = {
        "failure_id": "fail_" + stable_id(candidate["candidate_id"], bundle.evidence_input_hash, length=12),
        "candidate_id": candidate["candidate_id"],
        "episode_id": bundle.episode_id,
        "episode_mode": candidate["episode_mode"],
        "turn_range": candidate.get("turn_range") or [bundle.start_turn, bundle.final_turn],
        "capability_category": candidate["capability_category"],
        "failure_type": candidate["failure_type"],
        "confidence": candidate["confidence"],
        "title": candidate.get("title"),
        "failed_behavior": candidate.get("failed_behavior"),
        "expected_behavior": candidate.get("expected_behavior"),
        "evidence_refs": candidate["evidence_refs"],
        "human_status": "confirmed",
        "reviewer": confirmation.get("reviewer") or "human",
        "reviewer_rationale": rationale,
        "reviewed_at": confirmation.get("reviewed_at") or now_iso(),
        "scope_caveats": candidate.get("scope_caveats") or [],
        "evidence_input_hash": bundle.evidence_input_hash,
        "source_candidate": {
            "source_analyzer_run_id": candidate.get("source_analyzer_run_id"),
            "source_kind": candidate.get("source_kind"),
            "prompt_hash": candidate.get("prompt_hash"),
            "input_hash": candidate.get("input_hash"),
        },
    }
    enforce_short_planning_caveat(failure)
    forbidden = contains_forbidden_key(failure)
    if forbidden:
        raise ReviewError(f"Formal failure contains forbidden field: {forbidden}")
    validate_evidence_refs(bundle, failure["evidence_refs"])
    return failure


def as_int_turn(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def find_start_save(bundle: EvidenceBundle, turn_range: list[Any]) -> tuple[str | None, str | None]:
    start_turn = as_int_turn(turn_range[0] if turn_range else None)
    best: dict[str, Any] | None = None
    for save in bundle.saves:
        turn = save.get("turn")
        if start_turn is None or (isinstance(turn, int) and turn <= start_turn):
            if best is None or (
                isinstance(turn, int)
                and isinstance(best.get("turn"), int)
                and turn >= best["turn"]
            ):
                best = save
    if best is None and bundle.saves:
        best = bundle.saves[0]
    if not best:
        return None, None
    return best.get("save_id"), best.get("sha256")


def build_seed(bundle: EvidenceBundle, failure: dict[str, Any]) -> dict[str, Any]:
    turn_range = failure.get("turn_range") or [bundle.start_turn, bundle.final_turn]
    start_save_id, start_save_sha256 = find_start_save(bundle, turn_range)
    seed = {
        "seed_id": "seed_" + stable_id(failure["failure_id"], bundle.evidence_input_hash, length=12),
        "source_failure_ids": [failure["failure_id"]],
        "episode_id": bundle.episode_id,
        "turn_range": turn_range,
        "start_save_id": start_save_id,
        "start_save_sha256": start_save_sha256,
        "trigger_condition": failure.get("title") or failure.get("failure_type"),
        "expected_behavior": failure.get("expected_behavior"),
        "failed_behavior": failure.get("failed_behavior") or failure.get("title") or "",
        "evidence_refs": failure["evidence_refs"],
        "not_runnable_in_review": True,
        "manual_review_required": True,
        "asset_change_allowed": False,
    }
    forbidden = contains_forbidden_key(seed)
    if forbidden:
        raise ReviewError(f"Regression seed contains forbidden field: {forbidden}")
    if len(seed["source_failure_ids"]) != 1:
        raise ReviewError("Review v1 requires exactly one source_failure_id per seed")
    return seed


def load_current_confirmations(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    path = bundle.review_dir / "confirmation" / "confirmation.jsonl"
    return read_jsonl(path) if path.exists() else []


def load_formal_rows(bundle: EvidenceBundle) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failures_path = bundle.review_dir / "failures.jsonl"
    seeds_path = bundle.review_dir / "regression_seeds.jsonl"
    failures = read_jsonl(failures_path) if failures_path.exists() else []
    seeds = read_jsonl(seeds_path) if seeds_path.exists() else []
    return failures, seeds


def analyzer_run_ids(bundle: EvidenceBundle) -> list[str]:
    runs_dir = bundle.review_dir / "analyzer_runs"
    if not runs_dir.exists():
        return []
    return sorted(path.name for path in runs_dir.iterdir() if path.is_dir())


def output_hashes(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    if not bundle.review_dir.exists():
        return []
    rows = []
    for path in sorted(bundle.review_dir.rglob("*"), key=lambda p: path_rel(p, bundle.review_dir)):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        rows.append(
            {
                "path": path_rel(path, bundle.review_dir),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return rows


def build_manifest(
    bundle: EvidenceBundle,
    *,
    confirmation_file_hash: str | None = None,
    apply_timestamp: str | None = None,
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    failures = failures or []
    return {
        "workflow": WORKFLOW_NAME,
        "tool_version": TOOL_VERSION,
        "episode_id": bundle.episode_id,
        "generated_at": now_iso(),
        "input_manifest": bundle.input_manifest,
        "evidence_input_hash": bundle.evidence_input_hash,
        "output_files": output_hashes(bundle),
        "analyzer_run_ids": analyzer_run_ids(bundle),
        "confirmation_file_hash": confirmation_file_hash,
        "apply_timestamp": apply_timestamp,
        "short_validation": bundle.episode_mode == "short_validation",
        "local_episode_fragment": is_local_fragment_mode(bundle.episode_mode),
        "episode_mode": bundle.episode_mode,
        "turn_target": bundle.turn_target,
        "high_confidence_local_planning_failure": any(
            is_local_fragment_mode(failure.get("episode_mode"))
            and failure.get("capability_category") == "planning"
            and failure.get("confidence") == "high"
            for failure in failures
        ),
        "review_write_boundary": "episodes/<episode_id>/review/",
        "forbidden_fields": sorted(FORBIDDEN_FIELDS),
    }


def write_manifest(
    bundle: EvidenceBundle,
    *,
    confirmation_file_hash: str | None = None,
    apply_timestamp: str | None = None,
    failures: list[dict[str, Any]] | None = None,
) -> None:
    manifest = build_manifest(
        bundle,
        confirmation_file_hash=confirmation_file_hash,
        apply_timestamp=apply_timestamp,
        failures=failures,
    )
    write_json(bundle.review_dir / "MANIFEST.json", manifest, review_dir=bundle.review_dir)


def candidate_status(candidate: dict[str, Any], confirmations: dict[str, dict[str, Any]]) -> str:
    confirmation = confirmations.get(str(candidate["candidate_id"]))
    if not confirmation:
        return "pending"
    if confirmation.get("action") == "reject":
        return "rejected"
    return "confirmed"


def render_refs(refs: list[dict[str, Any]]) -> str:
    items = []
    for ref in refs:
        label = html.escape(
            " ".join(
                str(part)
                for part in [
                    ref.get("kind"),
                    ref.get("id") or ref.get("path"),
                    f"T{ref.get('turn')}" if ref.get("turn") is not None else "",
                ]
                if part
            )
        )
        items.append(f"<li><code>{label}</code></li>")
    return "<ul>" + "".join(items) + "</ul>"


def render_review_html(
    bundle: EvidenceBundle,
    candidates: list[dict[str, Any]],
    confirmation_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    seeds: list[dict[str, Any]],
) -> str:
    confirmations = latest_confirmation_by_candidate(confirmation_rows)
    analyzer_rows = []
    for run_id in analyzer_run_ids(bundle):
        provenance_path = bundle.review_dir / "analyzer_runs" / run_id / "provenance.json"
        provenance = read_json(provenance_path) if provenance_path.exists() else {"run_id": run_id}
        analyzer_rows.append(
            "<tr>"
            f"<td><code>{html.escape(run_id)}</code></td>"
            f"<td>{html.escape(str(provenance.get('source_kind') or provenance.get('analyzer')))}</td>"
            f"<td><code>{html.escape(str(provenance.get('prompt_hash', ''))[:16])}</code></td>"
            f"<td><code>{html.escape(str(provenance.get('input_hash', ''))[:16])}</code></td>"
            f"<td>{html.escape(str(provenance.get('session_id') or ''))}</td>"
            "</tr>"
        )

    candidate_rows = []
    for candidate in candidates:
        status = candidate_status(candidate, confirmations)
        caveat = ""
        if (
            is_local_fragment_mode(candidate.get("episode_mode"))
            and candidate.get("capability_category") == "planning"
        ):
            caveat = f'<p class="caveat">{html.escape(CAVEAT_TEXT)}</p>'
        candidate_rows.append(
            "<section class='candidate'>"
            f"<h3><code>{html.escape(candidate['candidate_id'])}</code> {html.escape(candidate.get('title') or '')}</h3>"
            "<div class='meta'>"
            f"<span class='{html.escape(status)}'>{html.escape(status)}</span>"
            f"<span>{html.escape(candidate.get('capability_category', ''))}</span>"
            f"<span>{html.escape(candidate.get('failure_type', ''))}</span>"
            f"<span>confidence={html.escape(candidate.get('confidence', ''))}</span>"
            f"<span>{html.escape(candidate.get('episode_mode', ''))}</span>"
            "</div>"
            f"<p>{html.escape(candidate.get('description') or '')}</p>"
            f"<p><strong>failed_behavior</strong>: {html.escape(str(candidate.get('failed_behavior') or ''))}</p>"
            f"<p><strong>expected_behavior</strong>: {html.escape(str(candidate.get('expected_behavior') or ''))}</p>"
            f"<p><strong>confidence rationale</strong>: {html.escape(candidate.get('confidence_rationale') or '')}</p>"
            f"{caveat}"
            "<h4>Evidence refs</h4>"
            f"{render_refs(candidate.get('evidence_refs') or [])}"
            "</section>"
        )

    seed_by_failure = {
        (seed.get("source_failure_ids") or [""])[0]: seed for seed in seeds if seed.get("source_failure_ids")
    }
    formal_rows = []
    for failure in failures:
        seed = seed_by_failure.get(failure.get("failure_id"))
        formal_rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(failure.get('failure_id')))}</code></td>"
            f"<td><code>{html.escape(str(failure.get('candidate_id')))}</code></td>"
            f"<td>{html.escape(str(failure.get('capability_category')))}</td>"
            f"<td>{html.escape(str(failure.get('confidence')))}</td>"
            f"<td><code>{html.escape(str(seed.get('seed_id') if seed else 'missing'))}</code></td>"
            "</tr>"
        )

    rejected = sum(1 for row in confirmations.values() if row.get("action") == "reject")
    confirmed = sum(1 for row in confirmations.values() if row.get("action") in {"accept", "modify"})
    pending = max(0, len(candidates) - rejected - confirmed)
    high_planning = any(
        is_local_fragment_mode(failure.get("episode_mode"))
        and failure.get("capability_category") == "planning"
        and failure.get("confidence") == "high"
        for failure in failures
    )
    high_caveat = (
        f"<p class='caveat'>{html.escape(CAVEAT_TEXT)}</p>" if high_planning else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Codex HL Civ6 Review 审计快照 - {html.escape(bundle.episode_id)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 32px; line-height: 1.55; color: #1f2933; background: #f7f7f4; }}
    h1, h2, h3 {{ color: #14213d; }}
    code {{ background: #eceff3; padding: 1px 4px; border-radius: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; background: white; }}
    th, td {{ border: 1px solid #cfd6dd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #e8eef3; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 18px 0; }}
    .tile {{ background: white; border: 1px solid #cfd6dd; padding: 12px; border-radius: 6px; }}
    .candidate {{ background: white; border: 1px solid #cfd6dd; border-radius: 6px; padding: 14px; margin: 14px 0; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }}
    .meta span {{ border: 1px solid #cfd6dd; border-radius: 999px; padding: 2px 8px; background: #f2f5f7; }}
    .pending {{ color: #7a4b00; font-weight: 700; }}
    .confirmed {{ color: #176d35; font-weight: 700; }}
    .rejected {{ color: #8a1f1f; font-weight: 700; }}
    .caveat {{ color: #b00020; font-weight: 800; }}
    .muted {{ color: #5d6975; }}
  </style>
</head>
<body>
  <h1>Codex HL Civ6 Review 审计快照</h1>
  <p class="muted">只读 Observation episode；所有 Review 产物位于 <code>episodes/{html.escape(bundle.episode_id)}/review/</code>。</p>
  <div class="summary">
    <div class="tile"><strong>episode</strong><br><code>{html.escape(bundle.episode_id)}</code></div>
    <div class="tile"><strong>mode</strong><br>{html.escape(bundle.episode_mode)} / {html.escape(bundle.turn_target)}</div>
    <div class="tile"><strong>candidates</strong><br>{len(candidates)}</div>
    <div class="tile"><strong>human status</strong><br><span class="confirmed">{confirmed} confirmed</span> · <span class="rejected">{rejected} rejected</span> · <span class="pending">{pending} pending</span></div>
    <div class="tile"><strong>formal failures</strong><br>{len(failures)}</div>
    <div class="tile"><strong>regression seeds</strong><br>{len(seeds)}</div>
  </div>
  <p><strong>Observation input hash</strong>: <code>{html.escape(bundle.evidence_input_hash)}</code></p>
  <p><strong>human_baseline_missing</strong>: <code>{str(bundle.human_baseline_missing).lower()}</code></p>
  {high_caveat}

  <h2>Analyzer Provenance</h2>
  <table>
    <tr><th>run_id</th><th>source</th><th>prompt_hash</th><th>input_hash</th><th>session_id</th></tr>
    {''.join(analyzer_rows) if analyzer_rows else '<tr><td colspan="5">No analyzer runs recorded.</td></tr>'}
  </table>

  <h2>Candidate Failures</h2>
  {''.join(candidate_rows) if candidate_rows else '<p>No candidate failures generated.</p>'}

  <h2>Formal Failure / Regression Seed Mapping</h2>
  <table>
    <tr><th>failure_id</th><th>candidate_id</th><th>category</th><th>confidence</th><th>seed_id</th></tr>
    {''.join(formal_rows) if formal_rows else '<tr><td colspan="5">No formal failures yet. Human confirmation and explicit apply are required.</td></tr>'}
  </table>
</body>
</html>
"""


def write_review(
    bundle: EvidenceBundle,
    candidates: list[dict[str, Any]],
    confirmation_rows: list[dict[str, Any]] | None = None,
    failures: list[dict[str, Any]] | None = None,
    seeds: list[dict[str, Any]] | None = None,
) -> None:
    existing_failures, existing_seeds = load_formal_rows(bundle)
    html_text = render_review_html(
        bundle,
        candidates,
        confirmation_rows if confirmation_rows is not None else load_current_confirmations(bundle),
        failures if failures is not None else existing_failures,
        seeds if seeds is not None else existing_seeds,
    )
    atomic_write_text(bundle.review_dir / "review.html", html_text, review_dir=bundle.review_dir)


def build_review_summary(
    bundle: EvidenceBundle,
    candidates: list[dict[str, Any]],
    confirmation_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    seeds: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    confirmations = latest_confirmation_by_candidate(confirmation_rows)
    rejected = [cid for cid, row in confirmations.items() if row.get("action") == "reject"]
    confirmed = [failure["failure_id"] for failure in failures]
    seed_ids = [seed["seed_id"] for seed in seeds]
    high_local_planning = [
        failure["failure_id"]
        for failure in failures
        if is_local_fragment_mode(failure.get("episode_mode"))
        and failure.get("capability_category") == "planning"
        and failure.get("confidence") == "high"
    ]
    summary = {
        "episode_id": bundle.episode_id,
        "episode_mode": bundle.episode_mode,
        "turn_target": bundle.turn_target,
        "evidence_input_hash": bundle.evidence_input_hash,
        "candidate_count": len(candidates),
        "confirmed_failure_count": len(failures),
        "rejected_candidate_ids": rejected,
        "failure_ids": confirmed,
        "seed_ids": seed_ids,
        "one_failure_to_one_seed": len(failures) == len(seeds)
        and all(len(seed.get("source_failure_ids", [])) == 1 for seed in seeds),
        "short_validation_caveat": CAVEAT_TEXT,
        "high_confidence_local_planning_failure_ids": high_local_planning,
        "out_of_scope_rejections": [],
        "generated_at": now_iso(),
    }
    md = [
        f"# Review v1 Summary: {bundle.episode_id}",
        "",
        f"- episode_mode: `{bundle.episode_mode}`",
        f"- turn_target: `{bundle.turn_target}`",
        f"- evidence_input_hash: `{bundle.evidence_input_hash}`",
        f"- candidates: `{len(candidates)}`",
        f"- confirmed failures: `{len(failures)}`",
        f"- regression seeds: `{len(seeds)}`",
        f"- rejected candidates: `{len(rejected)}`",
        "",
        "## Short Validation Caveat",
        "",
        f"<span style=\"color:#b00020;font-weight:800\">{CAVEAT_TEXT}</span>",
        "",
        "## Failure To Seed Mapping",
        "",
    ]
    if failures:
        seed_by_failure = {
            (seed.get("source_failure_ids") or [""])[0]: seed for seed in seeds if seed.get("source_failure_ids")
        }
        for failure in failures:
            seed = seed_by_failure.get(failure["failure_id"])
            md.append(
                f"- `{failure['failure_id']}` ← `{failure['candidate_id']}` → `{seed.get('seed_id') if seed else 'missing'}`"
            )
    else:
        md.append("- No confirmed failures.")
    md.append("")
    return summary, "\n".join(md)


def generate_candidates(
    episode_id: str,
    *,
    workspace: Path = ROOT,
    human_baseline_path: Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    bundle = load_evidence_bundle(
        episode_id, workspace=workspace, human_baseline_path=human_baseline_path
    )
    bundle.review_dir.mkdir(parents=True, exist_ok=True)
    prompt_text = build_analyzer_prompt(bundle)
    prompt_hash = sha256_text(prompt_text)
    run_id = f"heuristic_{now_stamp()}_{stable_id(bundle.episode_id, bundle.evidence_input_hash, length=8)}"
    candidates = generate_rule_candidates(
        bundle,
        analyzer_run_id=run_id,
        prompt_hash=prompt_hash,
        session_id=session_id,
    )
    for candidate in candidates:
        validate_candidate(candidate)
        validate_evidence_refs(bundle, candidate["evidence_refs"])
    write_jsonl(bundle.review_dir / "candidates.jsonl", candidates, review_dir=bundle.review_dir)
    archive_analyzer_run(
        bundle,
        run_id=run_id,
        prompt_text=prompt_text,
        candidates=candidates,
        session_id=session_id,
    )
    write_review(bundle, candidates)
    write_manifest(bundle)
    return {
        "episode_id": bundle.episode_id,
        "review_dir": str(bundle.review_dir),
        "candidates": len(candidates),
        "review_path": str(bundle.review_dir / "review.html"),
        "manifest_path": str(bundle.review_dir / "MANIFEST.json"),
    }


def ensure_evidence_hash_unchanged(bundle: EvidenceBundle) -> None:
    manifest_path = bundle.review_dir / "MANIFEST.json"
    if not manifest_path.exists():
        raise ReviewError("Missing Review MANIFEST.json; generate candidates before apply.")
    previous = read_json(manifest_path)
    previous_hash = previous.get("evidence_input_hash") or (
        previous.get("input_manifest", {}).get("aggregate_sha256")
        if isinstance(previous.get("input_manifest"), dict)
        else None
    )
    if previous_hash and previous_hash != bundle.evidence_input_hash:
        raise ReviewError(
            "Observation input hash changed after candidate generation. "
            f"previous={previous_hash}, current={bundle.evidence_input_hash}"
        )


def apply_confirmation(
    episode_id: str,
    confirmation_path: Path,
    *,
    workspace: Path = ROOT,
    human_baseline_path: Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    bundle = load_evidence_bundle(
        episode_id, workspace=workspace, human_baseline_path=human_baseline_path
    )
    ensure_evidence_hash_unchanged(bundle)
    candidates = load_review_candidates(bundle)
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    confirmation_rows = load_confirmation_rows(confirmation_path)
    for row in confirmation_rows:
        if row["candidate_id"] not in candidates_by_id:
            raise ReviewError(f"Unknown confirmation candidate_id: {row['candidate_id']}")

    failures: list[dict[str, Any]] = []
    confirmations = latest_confirmation_by_candidate(confirmation_rows)
    for candidate_id, confirmation in confirmations.items():
        if confirmation.get("action") == "reject":
            continue
        candidate = candidates_by_id[candidate_id]
        if confirmation.get("action") == "modify":
            candidate = apply_modified_fields(candidate, confirmation.get("modified_fields") or {})
        failures.append(build_failure(bundle, candidate, confirmation))

    seeds = [build_seed(bundle, failure) for failure in failures]
    if len(seeds) != len(failures):
        raise ReviewError("Review v1 requires one regression seed per failure")

    confirmation_dir = bundle.review_dir / "confirmation"
    confirmation_dir.mkdir(parents=True, exist_ok=True)
    canonical_confirmation = confirmation_dir / "confirmation.jsonl"
    confirmation_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n" for row in confirmation_rows
    )
    atomic_write_text(
        canonical_confirmation,
        confirmation_text,
        review_dir=bundle.review_dir,
    )
    apply_timestamp = now_iso()
    audit_row = {
        "ts": apply_timestamp,
        "event": "apply_confirmation",
        "episode_id": bundle.episode_id,
        "confirmation_source": str(confirmation_path),
        "confirmation_sha256": sha256_text(confirmation_text),
        "accepted_or_modified": len(failures),
        "rejected": sum(1 for row in confirmations.values() if row.get("action") == "reject"),
        "session_id": session_id,
    }
    append_jsonl(
        confirmation_dir / "confirmation_audit.jsonl",
        audit_row,
        review_dir=bundle.review_dir,
    )
    write_jsonl(bundle.review_dir / "failures.jsonl", failures, review_dir=bundle.review_dir)
    write_jsonl(
        bundle.review_dir / "regression_seeds.jsonl",
        seeds,
        review_dir=bundle.review_dir,
    )
    summary_json, summary_md = build_review_summary(
        bundle, candidates, confirmation_rows, failures, seeds
    )
    write_json(bundle.review_dir / "review_summary.json", summary_json, review_dir=bundle.review_dir)
    atomic_write_text(
        bundle.review_dir / "review_summary.md",
        summary_md,
        review_dir=bundle.review_dir,
    )
    write_review(bundle, candidates, confirmation_rows, failures, seeds)
    write_manifest(
        bundle,
        confirmation_file_hash=sha256_text(confirmation_text),
        apply_timestamp=apply_timestamp,
        failures=failures,
    )
    return {
        "episode_id": bundle.episode_id,
        "review_dir": str(bundle.review_dir),
        "failures": len(failures),
        "regression_seeds": len(seeds),
        "review_path": str(bundle.review_dir / "review.html"),
        "summary_path": str(bundle.review_dir / "review_summary.md"),
    }


def field_name(prefix: str, candidate_id: str) -> str:
    return f"{prefix}__{candidate_id}"


def checked(value: str, current: str) -> str:
    return " checked" if value == current else ""


def render_candidate_card(
    candidate: dict[str, Any],
    confirmations: dict[str, dict[str, Any]],
) -> str:
    candidate_id = str(candidate["candidate_id"])
    status = candidate_status(candidate, confirmations)
    confirmation = confirmations.get(candidate_id, {})
    evidence_items = "".join(
        "<li>"
        + html.escape(
            f"{ref.get('kind', 'evidence')}: "
            f"{ref.get('id') or ref.get('path') or ref.get('reason') or ''}"
        )
        + "</li>"
        for ref in candidate.get("evidence_refs", [])[:6]
    )
    if not evidence_items:
        evidence_items = "<li>No evidence refs recorded.</li>"
    current_note = html.escape(str(confirmation.get("reviewer_note") or ""))
    current_action = html.escape(str(confirmation.get("action") or "pending"))
    caveats = "".join(
        f"<li>{html.escape(str(caveat))}</li>" for caveat in candidate.get("scope_caveats", [])
    )
    caveat_block = (
        f"<details class=\"caveats\"><summary>scope caveats</summary><ul>{caveats}</ul></details>"
        if caveats
        else ""
    )
    return f"""
    <article class="candidate {html.escape(status)}">
      <header class="candidate-head">
        <div>
          <div class="eyebrow">{html.escape(candidate_id)}</div>
          <h2>{html.escape(str(candidate.get("title") or "Untitled candidate"))}</h2>
        </div>
        <div class="status-stack">
          <span class="status {html.escape(status)}">{html.escape(status)}</span>
          <span class="meta">current: {current_action}</span>
        </div>
      </header>
      <div class="chips">
        <span>{html.escape(str(candidate.get("capability_category") or "unmapped"))}</span>
        <span>{html.escape(str(candidate.get("failure_type") or "unknown"))}</span>
        <span>confidence: {html.escape(str(candidate.get("confidence") or "unknown"))}</span>
        <span>turns: {html.escape(str(candidate.get("turn_range") or ""))}</span>
      </div>
      <p class="desc">{html.escape(str(candidate.get("description") or ""))}</p>
      <div class="comparison">
        <section>
          <h3>expected</h3>
          <p>{html.escape(str(candidate.get("expected_behavior") or ""))}</p>
        </section>
        <section>
          <h3>observed</h3>
          <p>{html.escape(str(candidate.get("failed_behavior") or ""))}</p>
        </section>
      </div>
      <details>
        <summary>evidence refs</summary>
        <ul>{evidence_items}</ul>
      </details>
      {caveat_block}
      <fieldset class="decision">
        <legend>标注动作</legend>
        <label><input type="radio" name="{html.escape(field_name('action', candidate_id))}" value="skip" checked> skip / 不改这条</label>
        <label><input type="radio" name="{html.escape(field_name('action', candidate_id))}" value="accept"> accept / 确认失败</label>
        <label><input type="radio" name="{html.escape(field_name('action', candidate_id))}" value="reject"> reject / 不是失败</label>
        <label><input type="radio" name="{html.escape(field_name('action', candidate_id))}" value="modify"> modify / 接受但改字段</label>
      </fieldset>
      <label class="note-label" for="{html.escape(field_name('reviewer_note', candidate_id))}">reviewer note</label>
      <textarea id="{html.escape(field_name('reviewer_note', candidate_id))}" name="{html.escape(field_name('reviewer_note', candidate_id))}" rows="3" placeholder="写你为什么接受或拒绝；短跑结论请说明只适用于局部片段。">{current_note}</textarea>
      <label class="note-label" for="{html.escape(field_name('modified_fields', candidate_id))}">modified_fields JSON，仅 modify 时使用</label>
      <textarea class="modified-fields" id="{html.escape(field_name('modified_fields', candidate_id))}" name="{html.escape(field_name('modified_fields', candidate_id))}" rows="4" disabled>{{}}</textarea>
      <button class="secondary" type="submit" name="single_candidate" value="{html.escape(candidate_id)}">只保存这条</button>
    </article>
    """


def label_page(
    candidates: list[dict[str, Any]],
    episode_id: str,
    confirmation_rows: list[dict[str, Any]] | None = None,
    notice: str = "",
) -> str:
    confirmations = latest_confirmation_by_candidate(confirmation_rows or [])
    confirmed = sum(1 for candidate in candidates if candidate_status(candidate, confirmations) == "confirmed")
    rejected = sum(1 for candidate in candidates if candidate_status(candidate, confirmations) == "rejected")
    pending = max(0, len(candidates) - confirmed - rejected)
    cards = "\n".join(render_candidate_card(candidate, confirmations) for candidate in candidates)
    notice_html = f'<div class="notice">{html.escape(notice)}</div>' if notice else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Review Label - {html.escape(episode_id)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18202a;
      --muted: #5d6875;
      --line: #d9dee5;
      --panel: #ffffff;
      --page: #f4f6f8;
      --blue: #1d4f91;
      --green: #166534;
      --red: #9f2727;
      --amber: #8a5a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--page);
      color: var(--ink);
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.45;
    }}
    .shell {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 2;
      margin: -24px -24px 20px;
      padding: 18px 24px;
      background: rgba(244, 246, 248, 0.96);
      border-bottom: 1px solid var(--line);
    }}
    .topline {{ display: flex; gap: 16px; align-items: flex-start; justify-content: space-between; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; font-weight: 700; }}
    .sub {{ margin: 0; color: var(--muted); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }}
    a.button, button {{
      border: 1px solid var(--blue);
      background: var(--blue);
      color: #fff;
      padding: 9px 13px;
      border-radius: 6px;
      font: inherit;
      font-weight: 650;
      text-decoration: none;
      cursor: pointer;
    }}
    button.secondary {{
      margin-top: 10px;
      border-color: var(--line);
      background: #fff;
      color: var(--ink);
    }}
    .counts {{ display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 10px; margin-top: 14px; }}
    .count {{ border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 10px; }}
    .count strong {{ display: block; font-size: 20px; }}
    .reviewer-row {{ display: grid; grid-template-columns: minmax(160px, 240px) 1fr; gap: 12px; margin: 16px 0; }}
    label {{ font-weight: 650; }}
    input, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }}
    textarea {{ font-family: Consolas, "Microsoft YaHei", monospace; resize: vertical; }}
    .hint, .meta {{ color: var(--muted); font-size: 13px; }}
    .notice {{ margin: 12px 0; border: 1px solid #adc7ec; background: #eaf2ff; color: #123d74; padding: 10px 12px; border-radius: 6px; }}
    .candidate {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 16px;
      margin: 14px 0;
    }}
    .candidate.confirmed {{ border-left: 5px solid var(--green); }}
    .candidate.rejected {{ border-left: 5px solid var(--red); }}
    .candidate.pending {{ border-left: 5px solid var(--amber); }}
    .candidate-head {{ display: flex; gap: 16px; justify-content: space-between; align-items: flex-start; }}
    .eyebrow {{ color: var(--muted); font-size: 12px; font-family: Consolas, monospace; }}
    h2 {{ margin: 3px 0 0; font-size: 18px; line-height: 1.25; }}
    h3 {{ margin: 0 0 4px; font-size: 13px; text-transform: uppercase; color: var(--muted); }}
    .status-stack {{ text-align: right; min-width: 130px; }}
    .status {{
      display: inline-block;
      border-radius: 999px;
      padding: 4px 9px;
      font-weight: 700;
      font-size: 12px;
    }}
    .status.confirmed {{ background: #e7f6eb; color: var(--green); }}
    .status.rejected {{ background: #fdecec; color: var(--red); }}
    .status.pending {{ background: #fff5d6; color: var(--amber); }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }}
    .chips span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      color: #2c3948;
      background: #f8fafc;
      font-size: 12px;
    }}
    .desc {{ margin: 10px 0; }}
    .comparison {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }}
    .comparison section {{ border: 1px solid var(--line); border-radius: 6px; padding: 10px; background: #fbfcfd; }}
    .comparison p {{ margin: 0; }}
    details {{ margin: 10px 0; }}
    summary {{ cursor: pointer; color: var(--blue); font-weight: 650; }}
    .caveats {{ color: #653d00; }}
    .decision {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      margin-top: 12px;
    }}
    .decision legend {{ padding: 0 4px; color: var(--muted); font-weight: 700; }}
    .decision label {{
      display: flex;
      align-items: center;
      gap: 7px;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 9px;
      background: #fff;
      font-weight: 600;
    }}
    .decision input {{ width: auto; }}
    .note-label {{ display: block; margin: 11px 0 5px; }}
    .modified-fields[disabled] {{ background: #f1f3f5; color: #8b949e; }}
    @media (max-width: 820px) {{
      .topline, .candidate-head {{ display: block; }}
      .actions {{ justify-content: flex-start; margin-top: 12px; }}
      .counts, .reviewer-row, .comparison, .decision {{ grid-template-columns: 1fr; }}
      .status-stack {{ text-align: left; margin-top: 10px; }}
    }}
  </style>
</head>
<body>
  <form class="shell" method="post" action="/confirm-batch">
    <section class="topbar">
      <div class="topline">
        <div>
          <h1>Review 人工标注</h1>
          <p class="sub">每条候选默认是 skip；你可以一次选多条后保存，也可以只保存单张卡。保存只写 confirmation，正式 failure/seed 仍需后续 apply。</p>
          <p class="hint">重复保存同一 candidate 没关系；apply 时以 confirmation.jsonl 中最后一次人工标注为准。</p>
        </div>
        <div class="actions">
          <a class="button" href="/review.html" target="_blank">审计快照</a>
          <button type="submit">保存所有非 skip 项</button>
        </div>
      </div>
      <div class="counts">
        <div class="count"><strong>{len(candidates)}</strong>candidate</div>
        <div class="count"><strong>{confirmed}</strong>confirmed</div>
        <div class="count"><strong>{rejected}</strong>rejected</div>
        <div class="count"><strong>{pending}</strong>pending</div>
      </div>
      <div class="reviewer-row">
        <label>reviewer<input name="reviewer" value="human"></label>
        <div class="hint">判断标准：accept 只用于你确认的失败；reject 用于证据不足或不是失败；modify 只改允许字段，不能写修复、重跑、资产变更。</div>
      </div>
      {notice_html}
    </section>
    {cards}
  </form>
  <script>
    function refreshModifiedFields() {{
      document.querySelectorAll(".candidate").forEach(function(card) {{
        const checked = card.querySelector("input[type=radio]:checked");
        const fields = card.querySelector(".modified-fields");
        if (!checked || !fields) return;
        fields.disabled = checked.value !== "modify";
      }});
    }}
    document.addEventListener("change", refreshModifiedFields);
    refreshModifiedFields();
  </script>
</body>
</html>
"""


def form_value(form: dict[str, list[str]], key: str, default: str = "") -> str:
    return (form.get(key) or [default])[0]


def build_confirmation_row_from_form(
    candidate_id: str,
    action: str,
    reviewer: str,
    note: str,
    modified_raw: str,
    reviewed_at: str,
) -> dict[str, Any]:
    if action not in CONFIRMATION_ACTIONS:
        raise ReviewError(f"invalid action for {candidate_id}: {action}")
    modified_fields = json.loads(modified_raw or "{}")
    if not isinstance(modified_fields, dict):
        raise ReviewError(f"modified_fields must be a JSON object: {candidate_id}")
    row = {
        "candidate_id": candidate_id,
        "action": action,
        "modified_fields": modified_fields if action == "modify" else {},
        "reviewer": reviewer or "human",
        "reviewer_note": note,
        "reviewed_at": reviewed_at,
    }
    load_confirmation_rows_from_values([row])
    return row


def run_label_server(bundle: EvidenceBundle, candidates: list[dict[str, Any]], *, idle_timeout: int) -> None:
    confirmation_dir = bundle.review_dir / "confirmation"
    confirmation_dir.mkdir(parents=True, exist_ok=True)
    candidate_ids = {candidate["candidate_id"] for candidate in candidates}
    last_request = {"time": time.monotonic()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            last_request["time"] = time.monotonic()
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/review.html":
                self._send(200, (bundle.review_dir / "review.html").read_text(encoding="utf-8"))
                return
            query = urllib.parse.parse_qs(parsed.query)
            notice = ""
            if query.get("saved"):
                notice = f"已保存 {query['saved'][0]} 条 confirmation。"
            elif query.get("noop"):
                notice = "没有保存：所有候选都是 skip。"
            self._send(200, label_page(candidates, bundle.episode_id, load_current_confirmations(bundle), notice))

        def do_POST(self) -> None:  # noqa: N802
            last_request["time"] = time.monotonic()
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in {"/confirm", "/confirm-batch"}:
                self._send(404, "not found", "text/plain; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            form = urllib.parse.parse_qs(body)
            try:
                reviewed_at = now_iso()
                reviewer = form_value(form, "reviewer", "human") or "human"
                rows: list[dict[str, Any]] = []
                if parsed.path == "/confirm":
                    candidate_id = form_value(form, "candidate_id")
                    if candidate_id not in candidate_ids:
                        raise ReviewError(f"unknown candidate_id: {candidate_id}")
                    rows.append(
                        build_confirmation_row_from_form(
                            candidate_id,
                            form_value(form, "action"),
                            reviewer,
                            form_value(form, "reviewer_note"),
                            form_value(form, "modified_fields", "{}"),
                            reviewed_at,
                        )
                    )
                else:
                    single_candidate = form_value(form, "single_candidate")
                    target_ids = [single_candidate] if single_candidate else [str(c["candidate_id"]) for c in candidates]
                    for candidate_id in target_ids:
                        if candidate_id not in candidate_ids:
                            raise ReviewError(f"unknown candidate_id: {candidate_id}")
                        action = form_value(form, field_name("action", candidate_id), "skip")
                        if action == "skip":
                            continue
                        rows.append(
                            build_confirmation_row_from_form(
                                candidate_id,
                                action,
                                reviewer,
                                form_value(form, field_name("reviewer_note", candidate_id)),
                                form_value(form, field_name("modified_fields", candidate_id), "{}"),
                                reviewed_at,
                            )
                        )
            except Exception as exc:  # noqa: BLE001 - user form validation.
                self._send(400, html.escape(str(exc)), "text/plain; charset=utf-8")
                return
            for row in rows:
                append_jsonl(
                    confirmation_dir / "confirmation.jsonl",
                    row,
                    review_dir=bundle.review_dir,
                )
                append_jsonl(
                    confirmation_dir / "confirmation_audit.jsonl",
                    {
                        "ts": now_iso(),
                        "event": "label_server_confirmation",
                        "candidate_id": row["candidate_id"],
                        "action": row["action"],
                        "client": self.client_address[0],
                    },
                    review_dir=bundle.review_dir,
                )
            self.send_response(303)
            if rows:
                self.send_header("Location", f"/?saved={len(rows)}")
            else:
                self.send_header("Location", "/?noop=1")
            self.end_headers()

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.timeout = 1.0
    host, port = httpd.server_address
    print(
        json.dumps(
            {
                "label_url": f"http://{host}:{port}/",
                "bind_host": host,
                "writes_only": str(confirmation_dir),
                "idle_timeout_seconds": idle_timeout,
            },
            ensure_ascii=False,
        )
    )
    try:
        while time.monotonic() - last_request["time"] < idle_timeout:
            httpd.handle_request()
    finally:
        httpd.server_close()


def load_confirmation_rows_from_values(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        action = row.get("action")
        if action not in CONFIRMATION_ACTIONS:
            raise ReviewError(f"Invalid confirmation action: {action}")
        if row.get("candidate_id") is None:
            raise ReviewError("Confirmation row missing candidate_id")
        if action == "modify" and not isinstance(row.get("modified_fields"), dict):
            raise ReviewError("modify confirmation needs modified_fields object")
        forbidden = contains_forbidden_key(row)
        if forbidden:
            raise ReviewError(f"Confirmation row contains forbidden field: {forbidden}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument(
        "--workspace",
        default=str(ROOT),
        help="Repository root containing episodes/. Defaults to current workspace.",
    )
    parser.add_argument(
        "--human-baseline",
        help="Optional human T10/T20 baseline file to include in the Review input manifest.",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("CODEX_SESSION_ID"),
        help="Optional current Codex/agent session id for analyzer provenance.",
    )
    parser.add_argument("--label", action="store_true", help="Start the restricted localhost labeler.")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=900,
        help="Idle seconds before --label server exits.",
    )
    parser.add_argument(
        "--apply-confirmation",
        help="Explicitly apply a confirmation JSONL file to generate formal failures and passive seeds.",
    )
    args = parser.parse_args(argv)
    if args.label and args.apply_confirmation:
        parser.error("--label and --apply-confirmation are mutually exclusive")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    workspace = Path(args.workspace).resolve()
    human_baseline = Path(args.human_baseline).resolve() if args.human_baseline else None
    try:
        if args.apply_confirmation:
            result = apply_confirmation(
                args.episode_id,
                Path(args.apply_confirmation).resolve(),
                workspace=workspace,
                human_baseline_path=human_baseline,
                session_id=args.session_id,
            )
            print(json.dumps(result, ensure_ascii=False))
            return
        result = generate_candidates(
            args.episode_id,
            workspace=workspace,
            human_baseline_path=human_baseline,
            session_id=args.session_id,
        )
        print(json.dumps(result, ensure_ascii=False))
        if args.label:
            bundle = load_evidence_bundle(
                args.episode_id,
                workspace=workspace,
                human_baseline_path=human_baseline,
            )
            candidates = read_jsonl(bundle.review_dir / "candidates.jsonl")
            run_label_server(bundle, candidates, idle_timeout=args.idle_timeout)
    except (ReviewError, OSError, ValueError) as exc:
        print(f"Review failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

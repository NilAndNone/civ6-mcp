"""Multi-turn evolution orchestration for Codex HL Civ6.

This module is the first explicit self-evolution control plane.  It can run
multiple real T20/T50 observations, generate Review candidates, optionally apply a
restricted auto-confirmation policy, build Strategy Candidate/5 artifacts, and create a
validation report for governance.  Asset merge remains guarded: the orchestrator
will not call ``--allow-merge`` unless the caller explicitly asks and asserts
that the validation report was produced from a candidate-runtime run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from codex_hl.evidence.store import EpisodeReader
from codex_hl.strategy import registry as strategy_registry


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
WORKFLOW_NAME = "Codex HL Evolution Orchestrator"
T20_TURNS = 20
T50_TURNS = 50
DEFAULT_OBSERVATION_TURNS = T50_TURNS
SUPPORTED_OBSERVATION_TURNS = {T20_TURNS, T50_TURNS}
RUNNER_LIVE = "live"
RUNNER_LEGACY_BASELINE = "legacy-baseline"
SUPPORTED_RUNNERS = {RUNNER_LIVE, RUNNER_LEGACY_BASELINE}
DEFAULT_STRATEGY_PROFILE = "baseline_static"
EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE = "explore_scout_first"
SCIENCE_CULTURE_T50_STRATEGY_PROFILE = "science_culture_t50"
GOLDEN_AGE_PUSH_STRATEGY_PROFILE = "golden_age_push"
SUPPORTED_STRATEGY_PROFILES = {
    DEFAULT_STRATEGY_PROFILE,
    EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE,
    SCIENCE_CULTURE_T50_STRATEGY_PROFILE,
    GOLDEN_AGE_PUSH_STRATEGY_PROFILE,
}
DEFAULT_EXTRA_ATTEMPT_SLOTS = 5
DEFAULT_EPISODES_PER_CYCLE = 3
T50_CHECKPOINT_EPISODES = 10
MAX_T50_EPISODES = 100
T50_CRITICAL_CHECKPOINT_ALERTS = {"no_t50_pass_episode", "no_golden_age_pass_episode"}
DEFAULT_FIRETUNER_PORT = 4318
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
DEFAULT_AUTO_CONFIRM_CATEGORIES = {"planning", "execution", "verification", "recovery"}
CURRENT_BEST_CORE_FLOOR = {
    "completed_tech_count": 9,
    "completed_civic_count": 9,
    "science_yield": 10.0,
    "culture_yield": 10.0,
}
CURRENT_BEST_REFERENCE_EPISODE = "goal20_sciculture_clearpush_20260525_023950_c01_e01_t50_retry01"
CURRENT_BEST_REFERENCE_METRICS = {
    "num_cities": 3,
    "completed_tech_count": 9,
    "completed_civic_count": 9,
    "science_yield": 10.0,
    "culture_yield": 10.0,
    "era_score": 10,
    "era_golden_threshold": 19,
    "era_score_gap": 9,
    "gold": 474.0,
    "score": 87,
}
CURRENT_BEST_COMPARISON_KEYS = [
    "num_cities",
    "completed_tech_count",
    "completed_civic_count",
    "science_yield",
    "culture_yield",
    "era_score",
    "era_score_gap",
    "gold",
    "score",
]
T50_GOLD_CONVERSION_IDLE_THRESHOLD = 120


class EvolutionError(RuntimeError):
    """User-facing evolution orchestration error."""


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    ended_at: str


CommandRunner = Callable[[list[str], Path, dict[str, str] | None], CommandResult]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, indent=2, sort_keys=False)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise EvolutionError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvolutionError(f"Expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvolutionError(f"Invalid JSONL: {path}:{line_no}: {exc}") from exc
        if not isinstance(value, dict):
            raise EvolutionError(f"Expected JSON object in {path}:{line_no}")
        rows.append(value)
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(data) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def run_subprocess(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> CommandResult:
    started = now_iso()
    merged_env = os.environ.copy()
    merged_env.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        merged_env.update(env)
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        env=merged_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        started_at=started,
        ended_at=now_iso(),
    )


def command_log_row(result: CommandResult, *, step: str, ok: bool) -> dict[str, Any]:
    return {
        "ts": now_iso(),
        "step": step,
        "ok": ok,
        "returncode": result.returncode,
        "command": result.args,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def require_success(result: CommandResult, *, step: str, command_log: Path) -> None:
    ok = result.returncode == 0
    append_jsonl(command_log, command_log_row(result, step=step, ok=ok))
    if not ok:
        raise EvolutionError(f"{step} failed with exit {result.returncode}: {result.stderr[-1000:]}")


def parse_stdout_json(stdout: str, *, step: str) -> dict[str, Any]:
    stripped_stdout = stdout.strip()
    if stripped_stdout:
        try:
            value = json.loads(stripped_stdout)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict):
                return value
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise EvolutionError(f"{step} did not print a JSON object")


def confidence_meets(value: Any, minimum: str) -> bool:
    return CONFIDENCE_ORDER.get(str(value), -1) >= CONFIDENCE_ORDER[minimum]


def make_run_id(prefix: str = "evolve") -> str:
    return f"{prefix}_{now_stamp()}"


def episode_id_for(
    run_id: str,
    cycle: int,
    index: int,
    *,
    turns: int = DEFAULT_OBSERVATION_TURNS,
) -> str:
    return f"{run_id}_c{cycle:02d}_e{index:02d}_t{turns}"


def cycle_index_for_slot(slot: int, episodes_per_cycle: int) -> tuple[int, int]:
    cycle = ((slot - 1) // episodes_per_cycle) + 1
    index = ((slot - 1) % episodes_per_cycle) + 1
    return cycle, index


def python_module_command(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def civ6_save_filename(save_name: str) -> str:
    if save_name.lower().endswith(".civ6save"):
        return save_name
    return f"{save_name}.Civ6Save"


def build_connector_preflight(
    debug_payload: dict[str, Any],
    *,
    save_name: str,
    command: list[str],
) -> dict[str, Any]:
    save_dir = debug_payload.get("save_dir")
    save_path: str | None = None
    save_exists = False
    if save_dir:
        candidate = Path(str(save_dir)) / civ6_save_filename(save_name)
        save_path = str(candidate)
        save_exists = candidate.exists()

    game_running = bool(debug_payload.get("game_running"))
    firetuner_reachable = bool(debug_payload.get("firetuner_reachable"))
    blocking_reasons: list[str] = []
    if not save_exists:
        blocking_reasons.append("save_not_found")
    if not game_running:
        blocking_reasons.append("game_not_running")
    if not firetuner_reachable:
        blocking_reasons.append("firetuner_unreachable")

    return {
        "ok": True,
        "ready": not blocking_reasons,
        "save_name": save_name,
        "save_path": save_path,
        "save_exists": save_exists,
        "game_running": game_running,
        "firetuner_port": debug_payload.get("firetuner_port"),
        "firetuner_reachable": firetuner_reachable,
        "blocking_reasons": blocking_reasons,
        "debug_payload": debug_payload,
        "command": command,
    }


def run_connector_preflight(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    save_name: str,
    firetuner_port: int,
) -> dict[str, Any]:
    command = python_module_command(
        "codex_hl.diagnostics.connector",
        "--port",
        str(firetuner_port),
    )
    result = runner(command, workspace, {"CODEX_HL_CIV6_WORKSPACE": str(workspace)})
    ok = result.returncode == 0
    append_jsonl(command_log, command_log_row(result, step="connector_preflight", ok=ok))
    if not ok:
        return {
            "ok": False,
            "ready": False,
            "save_name": save_name,
            "save_path": None,
            "save_exists": False,
            "game_running": False,
            "firetuner_port": firetuner_port,
            "firetuner_reachable": False,
            "blocking_reasons": ["diagnostic_failed"],
            "error": result.stderr[-1000:] or result.stdout[-1000:],
            "command": command,
        }
    try:
        debug_payload = parse_stdout_json(result.stdout, step="connector_preflight")
    except EvolutionError as exc:
        return {
            "ok": False,
            "ready": False,
            "save_name": save_name,
            "save_path": None,
            "save_exists": False,
            "game_running": False,
            "firetuner_port": firetuner_port,
            "firetuner_reachable": False,
            "blocking_reasons": ["invalid_diagnostic_json"],
            "error": str(exc),
            "command": command,
        }
    return build_connector_preflight(debug_payload, save_name=save_name, command=command)


def run_observation(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    save_name: str,
    episode_id: str,
    turns: int,
    strategy_profile: str,
    asset_root: Path | None,
    candidate_package: Path | None = None,
) -> dict[str, Any]:
    env = {"CODEX_HL_CIV6_WORKSPACE": str(workspace)}
    if asset_root is not None:
        env["CODEX_HL_CIV6_STRATEGY_ASSET_ROOT"] = str(asset_root)
    command = python_module_command(
        "codex_hl.evidence.observation",
        "--save-name",
        save_name,
        "--turns",
        str(turns),
        "--episode-id",
        episode_id,
        "--strategy-profile",
        strategy_profile,
    )
    if candidate_package is not None:
        command.extend(["--candidate-package", str(candidate_package.resolve())])
    env["CODEX_HL_CIV6_RUNNER_KIND"] = RUNNER_LEGACY_BASELINE
    result = runner(command, workspace, env)
    require_success(
        result,
        step=f"legacy_baseline_observation_t{turns}:{episode_id}",
        command_log=command_log,
    )
    payload = parse_stdout_json(result.stdout, step=f"observation_t{turns}")
    payload.setdefault("episode_id", episode_id)
    payload["runner_kind"] = RUNNER_LEGACY_BASELINE
    payload["runner_deprecation"] = {
        "deprecated": True,
        "message": "legacy-baseline is retained only for baseline comparison and report rebuild compatibility.",
    }
    return payload


def run_live_observation(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    save_name: str,
    episode_id: str,
    turns: int,
    strategy_profile: str,
    asset_root: Path | None,
    candidate_package: Path | None = None,
) -> dict[str, Any]:
    env = {
        "CODEX_HL_CIV6_WORKSPACE": str(workspace),
        "CODEX_HL_CIV6_LIVE_GATEWAY_MODE": "live_strict",
        "CODEX_HL_CIV6_RUNNER_KIND": RUNNER_LIVE,
    }
    if asset_root is not None:
        env["CODEX_HL_CIV6_STRATEGY_ASSET_ROOT"] = str(asset_root)
    command = python_module_command(
        "codex_hl.live.runner",
        "--save-name",
        save_name,
        "--turns",
        str(turns),
        "--episode-id",
        episode_id,
        "--strategy-profile",
        strategy_profile,
    )
    if candidate_package is not None:
        command.extend(["--candidate-package", str(candidate_package.resolve())])
    result = runner(command, workspace, env)
    require_success(result, step=f"live_observation_t{turns}:{episode_id}", command_log=command_log)
    payload = parse_stdout_json(result.stdout, step=f"live_observation_t{turns}")
    payload.setdefault("episode_id", episode_id)
    payload["runner_kind"] = RUNNER_LIVE
    return payload


def run_review_candidates(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    session_id: str,
) -> dict[str, Any]:
    result = runner(
        python_module_command(
            "codex_hl.review.failure_labeling",
            "--workspace",
            str(workspace),
            "--episode-id",
            episode_id,
            "--session-id",
            session_id,
        ),
        workspace,
        {"CODEX_HL_CIV6_WORKSPACE": str(workspace)},
    )
    require_success(result, step=f"review_candidates:{episode_id}", command_log=command_log)
    return parse_stdout_json(result.stdout, step="review_candidates")


def selected_auto_confirmations(
    candidates: list[dict[str, Any]],
    *,
    min_confidence: str,
    categories: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("human_status") not in {None, "pending"}:
            continue
        if str(candidate.get("capability_category")) not in categories:
            continue
        if not confidence_meets(candidate.get("confidence"), min_confidence):
            continue
        selected.append(
            {
                "candidate_id": candidate["candidate_id"],
                "action": "accept",
                "modified_fields": {},
                "reviewer": "codex-hl-evolution-auto",
                "reviewer_note": (
                    "Auto-confirmed by explicit evolution policy. "
                    "Use only with multi-episode validation and guarded governance."
                ),
                "reviewed_at": now_iso(),
            }
        )
    return selected


def apply_auto_confirmation(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    min_confidence: str,
    categories: set[str],
) -> dict[str, Any]:
    review_dir = workspace / "episodes" / episode_id / "review"
    candidates = read_jsonl(review_dir / "candidates.jsonl")
    rows = selected_auto_confirmations(
        candidates,
        min_confidence=min_confidence,
        categories=categories,
    )
    confirmation_path = review_dir / "confirmation" / "auto_evolution_confirmation.jsonl"
    write_jsonl(confirmation_path, rows)
    if not rows:
        return {
            "episode_id": episode_id,
            "confirmation_path": str(confirmation_path),
            "selected": 0,
            "applied": False,
        }
    result = runner(
        python_module_command(
            "codex_hl.review.failure_labeling",
            "--workspace",
            str(workspace),
            "--episode-id",
            episode_id,
            "--apply-confirmation",
            str(confirmation_path),
        ),
        workspace,
        {"CODEX_HL_CIV6_WORKSPACE": str(workspace)},
    )
    require_success(result, step=f"review_apply:{episode_id}", command_log=command_log)
    payload = parse_stdout_json(result.stdout, step="review_apply")
    payload["confirmation_path"] = str(confirmation_path)
    payload["selected"] = len(rows)
    payload["applied"] = True
    return payload


def next_strategy_profile_from_review(
    *,
    current_profile: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    text = "\n".join(
        " ".join(
            str(candidate.get(key) or "")
            for key in ["title", "description", "failed_behavior", "expected_behavior"]
        )
        for candidate in candidates
    )
    reasons: list[str] = []
    next_profile = current_profile
    lower_text = text.lower()
    if current_profile != GOLDEN_AGE_PUSH_STRATEGY_PROFILE and (
        "时代得分" in text
        or "黄金时代" in text
        or "era score" in lower_text
        or "golden age" in lower_text
    ):
        next_profile = GOLDEN_AGE_PUSH_STRATEGY_PROFILE
        reasons.append("review_t50_golden_age_priority_candidate")
    elif current_profile in {DEFAULT_STRATEGY_PROFILE, EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE} and (
        "科学" in text
        or "文化" in text
        or "学院" in text
        or "写作" in text
        or "蛮族" in text
        or "science" in lower_text
        or "culture" in lower_text
        or "campus" in lower_text
        or "writing" in lower_text
        or "barbarian" in lower_text
    ):
        next_profile = SCIENCE_CULTURE_T50_STRATEGY_PROFILE
        reasons.append("review_t50_science_culture_or_security_candidate")
    elif current_profile == DEFAULT_STRATEGY_PROFILE and (
        "早期单位持续驻守" in text
        or "侦察兵" in text
        or "探索价值" in text
        or "建造者而非侦察兵" in text
    ):
        next_profile = EXPLORE_SCOUT_FIRST_STRATEGY_PROFILE
        reasons.append("review_repeated_opening_exploration_candidate")
    return {
        "from_profile": current_profile,
        "to_profile": next_profile,
        "changed": next_profile != current_profile,
        "reason_codes": reasons,
    }


def run_strategy_candidates(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    asset_root: Path,
) -> dict[str, Any]:
    result = runner(
        python_module_command(
            "codex_hl.strategy.candidates",
            "--workspace",
            str(workspace),
            "--asset-root",
            str(asset_root),
            "--episode-id",
            episode_id,
        ),
        workspace,
        {"CODEX_HL_CIV6_WORKSPACE": str(workspace)},
    )
    require_success(result, step=f"strategy_candidates:{episode_id}", command_log=command_log)
    return parse_stdout_json(result.stdout, step="strategy_candidates")


def run_validation_scenarios(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    pool_root: Path,
) -> dict[str, Any]:
    result = runner(
        python_module_command(
            "codex_hl.validation.scenarios",
            "--workspace",
            str(workspace),
            "--pool-root",
            str(pool_root),
            "--episode-id",
            episode_id,
        ),
        workspace,
        {"CODEX_HL_CIV6_WORKSPACE": str(workspace)},
    )
    require_success(result, step=f"validation_scenarios:{episode_id}", command_log=command_log)
    return parse_stdout_json(result.stdout, step="validation_scenarios")


def evidence_passed(report_pack: dict[str, Any]) -> bool:
    statuses = report_pack.get("evidence_status")
    if not isinstance(statuses, dict):
        return False
    return bool(statuses) and all(
        isinstance(row, dict) and row.get("status") == "PASS" for row in statuses.values()
    )


def load_episode_report_pack(workspace: Path, episode_id: str) -> dict[str, Any]:
    reader = EpisodeReader(workspace / "episodes" / episode_id)
    return reader.read_json("derived/report_pack.json")


def episode_ids_from_manifest(path: Path) -> list[str]:
    manifest = read_json(path)
    rows = manifest.get("episodes")
    if not isinstance(rows, list) or not rows:
        rows = manifest.get("checkpoint_episodes")
    if not isinstance(rows, list):
        return []
    episode_ids: list[str] = []
    for row in rows:
        if isinstance(row, str):
            episode_id = row
        elif isinstance(row, dict):
            episode_id = str(row.get("episode_id") or "")
        else:
            episode_id = ""
        if episode_id:
            episode_ids.append(episode_id)
    return episode_ids


def episode_failures_from_manifest(path: Path) -> list[dict[str, Any]]:
    manifest = read_json(path)
    rows = manifest.get("episode_failures")
    if not isinstance(rows, list):
        rows = manifest.get("failures")
    if not isinstance(rows, list):
        return []
    failures: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            failures.append(dict(row))
    return failures


def episode_rows_from_manifest(path: Path) -> list[dict[str, Any]]:
    manifest = read_json(path)
    rows = manifest.get("episodes")
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            episode_id = str(row.get("episode_id") or "")
            if episode_id:
                normalized.append(dict(row))
        elif isinstance(row, str) and row:
            normalized.append({"episode_id": row})
    return normalized


def max_recorded_slot(rows: list[dict[str, Any]]) -> int:
    slots = [row.get("slot") for row in rows if isinstance(row.get("slot"), int)]
    return max(slots) if slots else len(rows)


def recorded_observation_attempt_count(
    episode_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> int:
    completed_count = len(
        [row for row in episode_rows if isinstance(row, dict) and row.get("episode_id")]
    )
    failure_count = len([row for row in failure_rows if isinstance(row, dict)])
    return completed_count + failure_count


def episode_turns_passed(workspace: Path, episode_id: str, *, target_turns: int) -> bool:
    report_pack = load_episode_report_pack(workspace, episode_id)
    run = report_pack.get("run") if isinstance(report_pack.get("run"), dict) else {}
    return run.get("actual_turns") == target_turns and evidence_passed(report_pack)


def t50_episode_passed(workspace: Path, episode_id: str) -> bool:
    return episode_turns_passed(workspace, episode_id, target_turns=T50_TURNS)


def metric_delta(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float | int | None]:
    delta: dict[str, float | int | None] = {}
    for key in strategy_registry.NUMERIC_T50_METRICS:
        base_value = base.get(key)
        cand_value = candidate.get(key)
        if isinstance(base_value, (int, float)) and isinstance(cand_value, (int, float)):
            delta[key] = cand_value - base_value
        else:
            delta[key] = None
    return delta


def number_metric(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = metrics.get(key, default)
    return float(value) if isinstance(value, (int, float)) else default


def optional_number(metrics: dict[str, Any], key: str) -> int | float | None:
    value = metrics.get(key)
    return value if isinstance(value, (int, float)) else None


def final_state_agent_row(state: dict[str, Any]) -> dict[str, Any]:
    empire = state.get("empire") if isinstance(state.get("empire"), dict) else {}
    players = empire.get("players") if isinstance(empire.get("players"), list) else []
    for player in players:
        if isinstance(player, dict) and (player.get("pid") == 0 or player.get("is_agent") is True):
            return player
    return players[0] if players and isinstance(players[0], dict) else {}


def metrics_indicate_golden_age(metrics: dict[str, Any]) -> bool:
    current_age = str(metrics.get("current_age") or "").upper()
    if current_age in {"GOLDEN", "HEROIC"}:
        return True
    era_score = int(number_metric(metrics, "era_score", 0))
    golden_threshold = int(number_metric(metrics, "era_golden_threshold", 0))
    return golden_threshold > 0 and era_score >= golden_threshold


def extract_t50_best_run_metrics(workspace: Path, episode_id: str) -> dict[str, Any]:
    base = strategy_registry.extract_t50_metrics(episode_id, workspace=workspace)
    state_path, state = strategy_registry._load_episode_final_state(episode_id, workspace=workspace)
    overview = state.get("overview") if isinstance(state.get("overview"), dict) else {}
    audit = state.get("t50_strategy_audit") if isinstance(state.get("t50_strategy_audit"), dict) else {}
    agent = final_state_agent_row(state)
    metrics = dict(base["metrics"])
    era_score = overview.get("era_score", audit.get("era_score"))
    golden_threshold = overview.get("era_golden_threshold", audit.get("golden_threshold"))
    if isinstance(era_score, (int, float)):
        metrics["era_score"] = era_score
    if isinstance(golden_threshold, (int, float)):
        metrics["era_golden_threshold"] = golden_threshold
        metrics["era_score_gap"] = max(0, int(golden_threshold) - int(era_score or 0))
    if isinstance(overview.get("gold"), (int, float)):
        metrics["gold"] = overview["gold"]
    if isinstance(overview.get("score"), (int, float)):
        metrics["score"] = overview["score"]
    current_age = audit.get("current_age") or agent.get("age")
    if current_age:
        metrics["current_age"] = str(current_age).upper()
    current_era = audit.get("current_era") or agent.get("era")
    if current_era:
        metrics["current_era"] = str(current_era).upper()
    return {
        "episode_id": episode_id,
        "state_path": str(state_path),
        "turn": base.get("turn"),
        "metrics": metrics,
    }


def t50_best_run_score(metrics: dict[str, Any], *, passed: bool) -> dict[str, Any]:
    era_score = int(number_metric(metrics, "era_score", 0))
    golden_age = metrics_indicate_golden_age(metrics)
    core_floor_met = all(
        number_metric(metrics, key, -1) >= threshold
        for key, threshold in CURRENT_BEST_CORE_FLOOR.items()
    )
    weighted_score = (
        number_metric(metrics, "num_cities") * 140
        + number_metric(metrics, "completed_tech_count") * 45
        + number_metric(metrics, "completed_civic_count") * 45
        + number_metric(metrics, "science_yield") * 12
        + number_metric(metrics, "culture_yield") * 12
        + number_metric(metrics, "score") * 2
        + era_score * 25
        - number_metric(metrics, "gold") * 0.05
    )
    return {
        "passed": passed,
        "golden_age": golden_age,
        "core_floor_met": core_floor_met,
        "weighted_score": round(weighted_score, 3),
        "rank_key": [
            1 if passed else 0,
            1 if golden_age else 0,
            1 if core_floor_met else 0,
            round(weighted_score, 3),
        ],
        "core_floor": CURRENT_BEST_CORE_FLOOR,
    }


def metric_delta_from_current_best(metrics: dict[str, Any]) -> dict[str, float | int | None]:
    delta: dict[str, float | int | None] = {}
    for key in CURRENT_BEST_COMPARISON_KEYS:
        value = metrics.get(key)
        reference = CURRENT_BEST_REFERENCE_METRICS.get(key)
        if isinstance(value, (int, float)) and isinstance(reference, (int, float)):
            delta[key] = value - reference
        else:
            delta[key] = None
    return delta


def current_best_reference_payload() -> dict[str, Any]:
    return {
        "episode_id": CURRENT_BEST_REFERENCE_EPISODE,
        "metrics": dict(CURRENT_BEST_REFERENCE_METRICS),
        "core_floor": dict(CURRENT_BEST_CORE_FLOOR),
        "best_run_score": t50_best_run_score(
            CURRENT_BEST_REFERENCE_METRICS,
            passed=True,
        ),
    }


def rank_t50_episodes(workspace: Path, episode_ids: list[str], *, target_turns: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode_id in episode_ids:
        passed = episode_turns_passed(workspace, episode_id, target_turns=target_turns)
        metrics = extract_t50_best_run_metrics(workspace, episode_id)
        score = t50_best_run_score(metrics["metrics"], passed=passed)
        rows.append(
            {
                "episode_id": episode_id,
                "status": "pass" if passed else "fail",
                "turn": metrics.get("turn"),
                "metrics": metrics["metrics"],
                "best_run_score": score,
                "delta_from_current_best": metric_delta_from_current_best(metrics["metrics"]),
            }
        )
    return sorted(rows, key=lambda row: row["best_run_score"]["rank_key"], reverse=True)


def pass_only_t50_ranking(ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in ranking if row.get("status") == "pass"]


def eligible_best_t50_runs(ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in pass_only_t50_ranking(ranking)
        if (row.get("best_run_score") or {}).get("golden_age") is True
        and (row.get("best_run_score") or {}).get("core_floor_met") is True
    ]


def best_eligibility_rows(ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in pass_only_t50_ranking(ranking):
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        score = row.get("best_run_score") if isinstance(row.get("best_run_score"), dict) else {}
        core_floor = {
            key: {
                "value": optional_number(metrics, key),
                "threshold": threshold,
                "met": number_metric(metrics, key, -1) >= threshold,
            }
            for key, threshold in CURRENT_BEST_CORE_FLOOR.items()
        }
        golden_age = score.get("golden_age") is True
        core_floor_met = score.get("core_floor_met") is True
        rows.append(
            {
                "episode_id": row.get("episode_id"),
                "eligible": golden_age and core_floor_met,
                "passed": True,
                "golden_age": golden_age,
                "core_floor_met": core_floor_met,
                "era_score": optional_number(metrics, "era_score"),
                "era_golden_threshold": optional_number(metrics, "era_golden_threshold"),
                "core_floor": core_floor,
            }
        )
    return rows


def decision_execution(row: dict[str, Any]) -> dict[str, Any]:
    execution = row.get("execution")
    return execution if isinstance(execution, dict) else {}


def decision_text(row: dict[str, Any]) -> str:
    execution = decision_execution(row)
    parts = [
        row.get("trigger", ""),
        row.get("selected_action", ""),
        row.get("current_goal", ""),
        row.get("rationale", ""),
        row.get("outcome", ""),
        execution.get("tool", ""),
        execution.get("action", ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def is_gold_conversion_action(row: dict[str, Any]) -> bool:
    selected = str(row.get("selected_action", "") or "").lower()
    text = decision_text(row)
    return (
        "gold" in text
        and any(term in text for term in ["purchase", "buy", "upgrade", "tile"])
    ) or any(
        term in selected
        for term in [
            "purchase",
            "buy ",
            "upgrade ",
            "tile purchase",
        ]
    )


def is_resource_trade_action(row: dict[str, Any]) -> bool:
    text = decision_text(row)
    return any(
        term in text
        for term in [
            "strategic resource monetization",
            "sell surplus strategic resource",
            "test strategic resource sale",
            "resource trade",
            "propose_trade",
            "test_trade",
        ]
    )


def is_war_action(row: dict[str, Any]) -> bool:
    selected = str(row.get("selected_action", "") or "").lower()
    trigger = str(row.get("trigger", "") or "").lower()
    execution = decision_execution(row)
    target = execution.get("target")
    candidate = execution.get("candidate")
    target_is_war = isinstance(target, dict) and (
        target.get("is_opportunistic_war") is True
        or target.get("owner_id") is not None
        and target.get("is_barbarian") is not True
    )
    candidate_is_war = isinstance(candidate, dict) and (
        candidate.get("action") is not None
        and "war" in str(candidate.get("action", "")).lower()
    )
    if "opportunistic war gate" in trigger:
        return True
    if candidate_is_war:
        return True
    if "declare" in selected and "war" in selected:
        return True
    if selected in {"attack target", "move toward war target"} and target_is_war:
        return True
    if selected == "reposition ranged unit" and target_is_war:
        return True
    return False


def summarize_gold_conversion(
    audits: list[dict[str, Any]],
    gold_actions: list[dict[str, Any]],
    resource_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_values = [
        number_metric(audit, "gold")
        for audit in audits
        if isinstance(audit.get("gold"), (int, float))
    ]
    pressure_turns = sum(
        1
        for audit in audits
        if number_metric(audit, "gold") >= T50_GOLD_CONVERSION_IDLE_THRESHOLD
    )
    action_turns = {
        row.get("turn")
        for row in gold_actions
        if isinstance(row.get("turn"), int)
    }
    if pressure_turns:
        gold_conversion_rate = round(min(1.0, len(action_turns) / pressure_turns), 3)
    else:
        gold_conversion_rate = 0.0
    return {
        "gold_conversion_rate": gold_conversion_rate,
        "gold_action_count": len(gold_actions),
        "gold_action_turn_count": len(action_turns),
        "resource_trade_count": len(resource_trades),
        "pressure_turns": pressure_turns,
        "idle_threshold": T50_GOLD_CONVERSION_IDLE_THRESHOLD,
        "start_gold": gold_values[0] if gold_values else None,
        "final_gold": gold_values[-1] if gold_values else None,
        "max_gold": max(gold_values) if gold_values else None,
        "final_idle_gold": (
            gold_values[-1] >= T50_GOLD_CONVERSION_IDLE_THRESHOLD
            if gold_values
            else None
        ),
    }


def summarize_governor_assignment(audits: list[dict[str, Any]]) -> dict[str, Any]:
    final_governors: list[dict[str, Any]] = []
    for audit in reversed(audits):
        governors = audit.get("governors")
        if isinstance(governors, list):
            final_governors = [
                row for row in governors if isinstance(row, dict)
            ]
            break
    assigned = [row for row in final_governors if row.get("assigned") is True]
    unassigned = [row for row in final_governors if row.get("assigned") is not True]
    if not final_governors:
        status = "none_recorded"
    elif unassigned:
        status = "unassigned_governors"
    else:
        status = "all_assigned"
    return {
        "status": status,
        "all_assigned": not unassigned,
        "assigned_count": len(assigned),
        "unassigned_count": len(unassigned),
        "governors": final_governors,
    }


def summarize_golden_age_target_events(audits: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    active_counts: dict[str, int] = {}
    for audit in audits:
        for event in audit.get("golden_age_target_events") or []:
            if not isinstance(event, dict):
                continue
            key = str(event.get("event_key") or "")
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            if event.get("active") is True:
                active_counts[key] = active_counts.get(key, 0) + 1
    return {
        "observed_counts": counts,
        "active_counts": active_counts,
        "active_event_keys": sorted(active_counts, key=lambda key: (-active_counts[key], key)),
    }


def latest_list_from_audits(audits: list[dict[str, Any]], key: str) -> list[Any]:
    for audit in reversed(audits):
        value = audit.get(key)
        if isinstance(value, list):
            return value
    return []


def summarize_resource_activity(
    audits: list[dict[str, Any]],
    resource_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    final_strategics = latest_list_from_audits(audits, "strategic_resources")
    final_unimproved = latest_list_from_audits(audits, "unimproved_strategic_resources")
    final_tradable_players = latest_list_from_audits(audits, "tradable_players")
    turns_with_unimproved = sum(
        1 for audit in audits if audit.get("unimproved_strategic_resources")
    )
    turns_with_surplus = sum(
        1
        for audit in audits
        if any(
            number_metric(row, "surplus_after_reserve") > 0
            for row in (audit.get("strategic_resources") or [])
            if isinstance(row, dict)
        )
    )
    return {
        "trade_count": len(resource_trades),
        "trade_actions": resource_trades,
        "turns_with_surplus_strategics": turns_with_surplus,
        "turns_with_unimproved_strategics": turns_with_unimproved,
        "final_strategic_resources": final_strategics,
        "final_unimproved_strategic_resources": final_unimproved,
        "final_tradable_players": final_tradable_players,
    }


def summarize_war_activity(
    audits: list[dict[str, Any]],
    war_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    final_war_targets = latest_list_from_audits(audits, "war_targets")
    turns_with_war_targets = sum(1 for audit in audits if audit.get("war_targets"))
    turns_with_war_opportunity = sum(
        1
        for audit in audits
        if "opportunistic_neighbor_war" in (audit.get("opportunities") or [])
    )
    return {
        "war_action_count": len(war_actions),
        "war_actions": war_actions,
        "turns_with_war_targets": turns_with_war_targets,
        "turns_with_war_opportunity": turns_with_war_opportunity,
        "final_war_targets": final_war_targets,
    }


def markdown_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def metric_cell(metrics: dict[str, Any], key: str) -> str:
    return markdown_value(metrics.get(key))


def trace_by_episode(strategy_traces: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(trace.get("episode_id")): trace for trace in strategy_traces}


def core_floor_cell(eligibility: dict[str, Any], key: str) -> str:
    core_floor = eligibility.get("core_floor") if isinstance(eligibility.get("core_floor"), dict) else {}
    row = core_floor.get(key) if isinstance(core_floor.get(key), dict) else {}
    return f"{markdown_value(row.get('value'))}/{markdown_value(row.get('threshold'))}"


def count_map_markdown(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    parts = [
        f"{key}:{value[key]}"
        for key in sorted(value)
    ]
    return ", ".join(markdown_value(part) for part in parts)


def checkpoint_report_markdown(report: dict[str, Any]) -> str:
    checkpoint_alerts = report.get("checkpoint_alerts") if isinstance(report.get("checkpoint_alerts"), dict) else {}
    recommendation = (
        checkpoint_alerts.get("recommendation")
        if isinstance(checkpoint_alerts.get("recommendation"), dict)
        else {}
    )
    lines = [
        "# T50 Checkpoint Report",
        "",
        f"- Generated: {markdown_value(report.get('generated_at'))}",
        f"- Observation attempts: {markdown_value(report.get('observation_attempt_count'))}",
        f"- Completed episodes: {markdown_value(report.get('completed_episode_count'))}",
        f"- Failed attempts: {markdown_value(report.get('failure_count'))}",
        f"- Best eligible episode: {markdown_value(report.get('best_episode')) or 'None'}",
        f"- Recommended action: {markdown_value(recommendation.get('action'))}",
        f"- Current best reference: {markdown_value((report.get('current_best_reference') or {}).get('episode_id'))}",
        "",
        "## Top 3 PASS Episodes",
        "",
        "| Rank | Episode | Golden | Core | Cities | Techs | Civics | Science | Culture | Era | Gap | Gold | Delta Era | Delta Gold |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    top_rows = report.get("top_3") if isinstance(report.get("top_3"), list) else []
    if top_rows:
        for index, row in enumerate(top_rows, start=1):
            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            score = row.get("best_run_score") if isinstance(row.get("best_run_score"), dict) else {}
            delta = row.get("delta_from_current_best") if isinstance(row.get("delta_from_current_best"), dict) else {}
            era = f"{metric_cell(metrics, 'era_score')}/{metric_cell(metrics, 'era_golden_threshold')}"
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(index),
                        markdown_value(row.get("episode_id")),
                        markdown_value(score.get("golden_age")),
                        markdown_value(score.get("core_floor_met")),
                        metric_cell(metrics, "num_cities"),
                        metric_cell(metrics, "completed_tech_count"),
                        metric_cell(metrics, "completed_civic_count"),
                        metric_cell(metrics, "science_yield"),
                        metric_cell(metrics, "culture_yield"),
                        era,
                        metric_cell(metrics, "era_score_gap"),
                        metric_cell(metrics, "gold"),
                        markdown_value(delta.get("era_score")),
                        markdown_value(delta.get("gold")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("|  | No T50 PASS episodes |  |  |  |  |  |  |  |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## Best Eligibility",
            "",
            "| Episode | Eligible | Golden | Core Floor | Techs | Civics | Science | Culture | Era |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    eligibility_rows = (
        report.get("best_eligibility") if isinstance(report.get("best_eligibility"), list) else []
    )
    if eligibility_rows:
        for row in eligibility_rows:
            if not isinstance(row, dict):
                continue
            era = (
                f"{markdown_value(row.get('era_score'))}/{markdown_value(row.get('era_golden_threshold'))}"
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_value(row.get("episode_id")),
                        markdown_value(row.get("eligible")),
                        markdown_value(row.get("golden_age")),
                        markdown_value(row.get("core_floor_met")),
                        core_floor_cell(row, "completed_tech_count"),
                        core_floor_cell(row, "completed_civic_count"),
                        core_floor_cell(row, "science_yield"),
                        core_floor_cell(row, "culture_yield"),
                        era,
                    ]
                )
                + " |"
            )
    else:
        lines.append("| No T50 PASS episodes |  |  |  |  |  |  |  |  |")

    lines.extend(["", "## Alerts", ""])
    alerts = (report.get("checkpoint_alerts") or {}).get("alerts")
    if isinstance(alerts, list) and alerts:
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            code = markdown_value(alert.get("code"))
            severity = markdown_value(alert.get("severity"))
            message = markdown_value(alert.get("message"))
            next_step = markdown_value(alert.get("next_step"))
            lines.append(f"- {severity}: `{code}` - {message}")
            if next_step:
                lines.append(f"  Next: {next_step}")
    else:
        lines.append("- None")

    traces = report.get("strategy_traces") if isinstance(report.get("strategy_traces"), list) else []
    traces_by_episode = trace_by_episode(traces)
    lines.extend(
        [
            "",
            "## Strategy Trace Summary",
            "",
            "| Episode | Era Start-End | Final Gap | Gold Start-End | Gold Conversion | Governor Status | Resource Trades | War Actions |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    episode_order = [
        str(row.get("episode_id"))
        for row in (report.get("ranked_episodes") or [])
        if isinstance(row, dict) and row.get("episode_id")
    ]
    if not episode_order:
        episode_order = sorted(traces_by_episode)
    for episode_id in episode_order:
        trace = traces_by_episode.get(episode_id, {})
        curve = trace.get("era_score_curve") if isinstance(trace.get("era_score_curve"), list) else []
        first = curve[0] if curve and isinstance(curve[0], dict) else {}
        final = curve[-1] if curve and isinstance(curve[-1], dict) else {}
        gold_conversion = trace.get("gold_conversion") if isinstance(trace.get("gold_conversion"), dict) else {}
        governors = trace.get("governor_assignment_status") if isinstance(trace.get("governor_assignment_status"), dict) else {}
        resources = trace.get("resource_activity") if isinstance(trace.get("resource_activity"), dict) else {}
        war = trace.get("war_activity") if isinstance(trace.get("war_activity"), dict) else {}
        era_range = (
            f"{markdown_value(first.get('era_score'))}-{markdown_value(final.get('era_score'))}/"
            f"{markdown_value(final.get('golden_threshold'))}"
            if curve
            else ""
        )
        gold_range = (
            f"{markdown_value(gold_conversion.get('start_gold'))}-{markdown_value(gold_conversion.get('final_gold'))}"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_value(episode_id),
                    era_range,
                    markdown_value(final.get("era_score_gap")),
                    gold_range,
                    markdown_value(gold_conversion.get("gold_conversion_rate")),
                    markdown_value(governors.get("status")),
                    markdown_value(resources.get("trade_count")),
                    markdown_value(war.get("war_action_count")),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Golden Age Target Events",
            "",
            "| Episode | Active Event Keys | Active Counts | Observed Counts |",
            "| --- | --- | --- | --- |",
        ]
    )
    event_summaries = (
        report.get("golden_age_event_summaries")
        if isinstance(report.get("golden_age_event_summaries"), dict)
        else {}
    )
    if episode_order:
        for episode_id in episode_order:
            summary = (
                event_summaries.get(episode_id)
                if isinstance(event_summaries.get(episode_id), dict)
                else {}
            )
            active_keys = summary.get("active_event_keys") if isinstance(summary, dict) else []
            active_key_text = (
                ", ".join(markdown_value(key) for key in active_keys)
                if isinstance(active_keys, list)
                else ""
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_value(episode_id),
                        active_key_text,
                        count_map_markdown(summary.get("active_counts")),
                        count_map_markdown(summary.get("observed_counts")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| No completed episodes |  |  |  |")

    lines.extend(["", "## Failures", ""])
    failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    if failures:
        lines.extend(
            [
                "| Slot | Attempt | Episode | Strategy | Error |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for failure in failures:
            if isinstance(failure, dict):
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            markdown_value(failure.get("slot")),
                            markdown_value(failure.get("attempt")),
                            markdown_value(failure.get("episode_id")),
                            markdown_value(failure.get("strategy_profile")),
                            markdown_value(failure.get("error") or failure.get("reason")),
                        ]
                    )
                    + " |"
                )
    else:
        lines.append("- None recorded in this checkpoint.")
    lines.append("")
    return "\n".join(lines)


def build_t50_checkpoint_alerts(report: dict[str, Any]) -> dict[str, Any]:
    ranking = report.get("ranked_episodes") if isinstance(report.get("ranked_episodes"), list) else []
    pass_rows = report.get("ranked_pass_episodes") if isinstance(report.get("ranked_pass_episodes"), list) else []
    traces = report.get("strategy_traces") if isinstance(report.get("strategy_traces"), list) else []
    alerts: list[dict[str, Any]] = []

    if report.get("observation_attempt_count", report.get("episode_count", 0)) and not pass_rows:
        alerts.append(
            {
                "code": "no_t50_pass_episode",
                "severity": "critical",
                "message": "No completed T50 PASS episode exists in this checkpoint.",
                "next_step": "Stop the batch and inspect episode failures before continuing.",
            }
        )
    golden_pass_rows = [
        row
        for row in pass_rows
        if (row.get("best_run_score") or {}).get("golden_age") is True
    ]
    if pass_rows and not golden_pass_rows:
        alerts.append(
            {
                "code": "no_golden_age_pass_episode",
                "severity": "critical",
                "message": "T50 PASS episodes exist, but none reached the golden-age threshold.",
                "next_step": "Revise the golden_age_push priority before spending more episodes.",
            }
        )
    if golden_pass_rows and not report.get("best_episode"):
        alerts.append(
            {
                "code": "no_best_eligible_episode",
                "severity": "warning",
                "message": "At least one PASS episode reached golden age, but none also met the core science/culture floor.",
                "next_step": "Tune science/culture preservation before accepting a final best run.",
            }
        )
    idle_gold_traces = [
        trace
        for trace in traces
        if (trace.get("gold_conversion") or {}).get("final_idle_gold") is True
        and float((trace.get("gold_conversion") or {}).get("gold_conversion_rate") or 0.0) == 0.0
    ]
    if idle_gold_traces:
        alerts.append(
            {
                "code": "idle_gold_not_converted",
                "severity": "warning",
                "message": "One or more episodes ended with idle gold and no recorded gold conversion action.",
                "episode_ids": [trace.get("episode_id") for trace in idle_gold_traces],
                "next_step": "Inspect purchase, upgrade, and tile-buying availability in those traces.",
            }
        )
    unassigned_governor_traces = [
        trace
        for trace in traces
        if (trace.get("governor_assignment_status") or {}).get("status")
        == "unassigned_governors"
    ]
    if unassigned_governor_traces:
        alerts.append(
            {
                "code": "governor_unassigned",
                "severity": "warning",
                "message": "One or more episodes ended with an appointed governor still assigned to NONE.",
                "episode_ids": [trace.get("episode_id") for trace in unassigned_governor_traces],
                "next_step": "Inspect governor appointment and assignment tool calls.",
            }
        )
    idle_resource_traces = [
        trace
        for trace in traces
        if (trace.get("resource_activity") or {}).get("turns_with_surplus_strategics", 0) > 0
        and (trace.get("resource_activity") or {}).get("trade_count", 0) == 0
    ]
    if idle_resource_traces:
        alerts.append(
            {
                "code": "surplus_strategics_not_traded",
                "severity": "warning",
                "message": "One or more episodes had surplus strategic resources but no recorded resource trade.",
                "episode_ids": [trace.get("episode_id") for trace in idle_resource_traces],
                "next_step": "Inspect get_trade_options, test_trade, and propose_trade availability for Horses/Iron.",
            }
        )
    unimproved_resource_traces = [
        trace
        for trace in traces
        if (trace.get("resource_activity") or {}).get("final_unimproved_strategic_resources")
    ]
    if unimproved_resource_traces:
        alerts.append(
            {
                "code": "strategic_resource_unimproved",
                "severity": "warning",
                "message": "One or more episodes ended with Horses or Iron still unimproved.",
                "episode_ids": [trace.get("episode_id") for trace in unimproved_resource_traces],
                "next_step": "Inspect builder task selection, strategic tile buying, and worker positioning.",
            }
        )
    unused_war_opportunity_traces = [
        trace
        for trace in traces
        if (trace.get("war_activity") or {}).get("turns_with_war_opportunity", 0) > 0
        and (trace.get("war_activity") or {}).get("war_action_count", 0) == 0
    ]
    if unused_war_opportunity_traces:
        alerts.append(
            {
                "code": "war_opportunity_not_used",
                "severity": "warning",
                "message": "One or more episodes had an opportunistic war window but no recorded war action.",
                "episode_ids": [trace.get("episode_id") for trace in unused_war_opportunity_traces],
                "next_step": "Inspect declaration gates and tactical movement or attack estimates.",
            }
        )
    missing_event_traces = [
        trace
        for trace in traces
        if not ((trace.get("golden_age_event_summary") or {}).get("active_event_keys") or [])
    ]
    if missing_event_traces:
        alerts.append(
            {
                "code": "no_active_golden_age_target_events",
                "severity": "info",
                "message": "One or more episodes had no active golden-age target event evidence in the audit trace.",
                "episode_ids": [trace.get("episode_id") for trace in missing_event_traces],
                "next_step": "Check whether state snapshots lack notifications, diplomacy, resources, or threat coverage.",
            }
        )

    critical_codes = {
        alert["code"] for alert in alerts if alert.get("severity") == "critical"
    }
    best_episode = report.get("best_episode")
    if best_episode:
        recommendation = {
            "action": "accept_best_candidate",
            "reason": "At least one PASS episode reached golden age and met the current core science/culture floor.",
            "episode_id": best_episode,
        }
    elif critical_codes & T50_CRITICAL_CHECKPOINT_ALERTS:
        recommendation = {
            "action": "stop_and_fix_strategy",
            "reason": "A critical checkpoint gate failed; continuing would spend more T50 budget without a valid direction.",
        }
    elif alerts:
        recommendation = {
            "action": "review_before_continuing",
            "reason": "The checkpoint has non-critical warnings that should be inspected before spending the next 10 attempts.",
        }
    else:
        recommendation = {
            "action": "continue_next_checkpoint",
            "reason": "No checkpoint alerts were raised.",
        }
    return {
        "alerts": alerts,
        "critical_alert_count": len(critical_codes),
        "review_recommended": bool(alerts),
        "stop_recommended": bool(critical_codes & T50_CRITICAL_CHECKPOINT_ALERTS),
        "recommendation": recommendation,
        "ranked_episode_count": len(ranking),
    }


def audit_curve_row_from_state(state: dict[str, Any]) -> dict[str, Any] | None:
    audit = state.get("t50_strategy_audit")
    if isinstance(audit, dict):
        return {
            "source": "t50_strategy_audit",
            "turn": audit.get("turn", state.get("turn")),
            "era_score": audit.get("era_score"),
            "golden_threshold": audit.get("golden_threshold"),
            "era_score_gap": audit.get("era_score_gap"),
            "gold": audit.get("gold"),
            "governors": audit.get("governors", []),
            "strategic_resources": audit.get("strategic_resources", []),
            "unimproved_strategic_resources": audit.get("unimproved_strategic_resources", []),
            "tradable_players": audit.get("tradable_players", []),
            "war_targets": audit.get("war_targets", []),
            "opportunities": audit.get("opportunities", []),
            "golden_age_target_events": audit.get("golden_age_target_events", []),
            "active_golden_age_target_events": audit.get("active_golden_age_target_events", []),
        }

    overview = state.get("overview") if isinstance(state.get("overview"), dict) else {}
    era_score = optional_number(overview, "era_score")
    golden_threshold = optional_number(overview, "era_golden_threshold")
    gold = optional_number(overview, "gold")
    if era_score is None and golden_threshold is None and gold is None:
        return None
    return {
        "source": "overview_fallback",
        "turn": state.get("turn"),
        "era_score": era_score,
        "golden_threshold": golden_threshold,
        "era_score_gap": (
            max(0, int(golden_threshold) - int(era_score or 0))
            if golden_threshold is not None
            else None
        ),
        "gold": gold,
        "governors": state.get("governors", []) if isinstance(state.get("governors"), list) else [],
        "strategic_resources": [],
        "unimproved_strategic_resources": [],
        "tradable_players": [],
        "war_targets": [],
        "opportunities": [],
        "golden_age_target_events": [],
        "active_golden_age_target_events": [],
    }


def load_episode_strategy_trace(workspace: Path, episode_id: str) -> dict[str, Any]:
    reader = EpisodeReader(workspace / "episodes" / episode_id)
    audits: list[dict[str, Any]] = []
    for _path, state in reader.state_rows():
        audit_row = audit_curve_row_from_state(state)
        if audit_row is not None:
            audits.append(audit_row)
    decisions = reader.read_jsonl("derived/decision_atoms.jsonl")
    gold_actions = [row for row in decisions if is_gold_conversion_action(row)]
    resource_trades = [row for row in decisions if is_resource_trade_action(row)]
    war_actions = [row for row in decisions if is_war_action(row)]
    governor_status = summarize_governor_assignment(audits)
    gold_conversion = summarize_gold_conversion(audits, gold_actions, resource_trades)
    golden_age_event_summary = summarize_golden_age_target_events(audits)
    resource_activity = summarize_resource_activity(audits, resource_trades)
    war_activity = summarize_war_activity(audits, war_actions)
    return {
        "episode_id": episode_id,
        "era_score_curve": audits,
        "golden_age_event_summary": golden_age_event_summary,
        "gold_actions": gold_actions,
        "gold_conversion_rate": gold_conversion["gold_conversion_rate"],
        "gold_conversion": gold_conversion,
        "governor_assignment_status": governor_status,
        "resource_trades": resource_trades,
        "resource_activity": resource_activity,
        "war_actions": war_actions,
        "war_activity": war_activity,
    }


def build_t50_checkpoint_report(
    *,
    workspace: Path,
    output_path: Path,
    episode_ids: list[str],
    failures: list[dict[str, Any]],
    target_turns: int = T50_TURNS,
    observation_attempt_count: int | None = None,
) -> dict[str, Any]:
    ranking = rank_t50_episodes(workspace, episode_ids, target_turns=target_turns)
    pass_ranking = pass_only_t50_ranking(ranking)
    eligible_best = eligible_best_t50_runs(ranking)
    eligibility = best_eligibility_rows(ranking)
    strategy_traces = [
        load_episode_strategy_trace(workspace, episode_id) for episode_id in episode_ids
    ]
    completed_episode_count = len(episode_ids)
    failure_count = len(failures)
    if observation_attempt_count is None:
        observation_attempt_count = completed_episode_count + failure_count
    report = {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "report_kind": f"t{target_turns}_checkpoint_report",
        "generated_at": now_iso(),
        "workspace": str(workspace),
        "observation_attempt_count": observation_attempt_count,
        "completed_episode_count": completed_episode_count,
        "failed_attempt_count": failure_count,
        "failure_count": failure_count,
        "episode_count": completed_episode_count,
        "current_best_reference": current_best_reference_payload(),
        "top_3": pass_ranking[:3],
        "ranked_pass_episodes": pass_ranking,
        "best_eligibility": eligibility,
        "best_eligible_top_3": eligible_best[:3],
        "best_episode": eligible_best[0]["episode_id"] if eligible_best else None,
        "best_episode_requirements": {
            "t50_pass_required": True,
            "golden_age_required": True,
            "core_floor_required": CURRENT_BEST_CORE_FLOOR,
            "current_best_reference_episode": CURRENT_BEST_REFERENCE_EPISODE,
        },
        "ranked_episodes": ranking,
        "failures": failures,
        "gold_conversion_rates": {
            trace["episode_id"]: trace["gold_conversion_rate"] for trace in strategy_traces
        },
        "era_score_curves": {
            trace["episode_id"]: trace["era_score_curve"] for trace in strategy_traces
        },
        "golden_age_event_summaries": {
            trace["episode_id"]: trace["golden_age_event_summary"] for trace in strategy_traces
        },
        "governor_assignment_statuses": {
            trace["episode_id"]: trace["governor_assignment_status"] for trace in strategy_traces
        },
        "resource_trade_summaries": {
            trace["episode_id"]: trace["resource_activity"] for trace in strategy_traces
        },
        "war_action_summaries": {
            trace["episode_id"]: trace["war_activity"] for trace in strategy_traces
        },
        "strategy_traces": strategy_traces,
    }
    report["checkpoint_alerts"] = build_t50_checkpoint_alerts(report)
    markdown_path = output_path.with_suffix(".md")
    report["markdown_report"] = str(markdown_path)
    write_json(output_path, report)
    write_text(markdown_path, checkpoint_report_markdown(report) + "\n")
    return report


def record_t50_checkpoint(
    *,
    manifest: dict[str, Any],
    workspace: Path,
    checkpoint_path: Path,
    episode_ids: list[str],
    target_turns: int,
    observation_attempt_count: int | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    failures = [
        row
        for row in (manifest.get("episode_failures") or [])
        if isinstance(row, dict)
    ]
    checkpoint = build_t50_checkpoint_report(
        workspace=workspace,
        output_path=checkpoint_path,
        episode_ids=episode_ids,
        failures=failures,
        target_turns=target_turns,
        observation_attempt_count=observation_attempt_count,
    )
    checkpoint_path_text = str(checkpoint_path)
    checkpoints = manifest.setdefault("checkpoints", [])
    if checkpoint_path_text not in checkpoints:
        checkpoints.append(checkpoint_path_text)
    summary = {
        "path": checkpoint_path_text,
        "markdown_report": checkpoint.get("markdown_report"),
        "observation_attempt_count": checkpoint.get("observation_attempt_count"),
        "completed_episode_count": checkpoint.get("completed_episode_count"),
        "episode_count": checkpoint["episode_count"],
        "top_episode": checkpoint["top_3"][0]["episode_id"] if checkpoint["top_3"] else None,
        "best_episode": checkpoint.get("best_episode"),
        "failed_attempt_count": checkpoint.get("failed_attempt_count"),
        "failure_count": checkpoint.get("failure_count"),
        "checkpoint_alerts": checkpoint.get("checkpoint_alerts"),
    }
    if partial:
        summary["partial"] = True
    manifest["latest_checkpoint_summary"] = summary
    return checkpoint


def build_t50_validation_report(
    *,
    workspace: Path,
    output_path: Path,
    baseline_episode: str,
    candidate_episodes: list[str],
    target_turns: int = T50_TURNS,
    candidate_package: Path | None = None,
    candidate_runtime_applied: bool = False,
) -> dict[str, Any]:
    baseline_metrics = strategy_registry.extract_t50_metrics(baseline_episode, workspace=workspace)
    baseline_values = baseline_metrics["metrics"]
    scenario_results: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for episode_id in candidate_episodes:
        metrics = strategy_registry.extract_t50_metrics(episode_id, workspace=workspace)
        best_metrics = extract_t50_best_run_metrics(workspace, episode_id)
        delta = metric_delta(baseline_values, metrics["metrics"])
        passed = episode_turns_passed(workspace, episode_id, target_turns=target_turns)
        row = {
            "scenario_id": episode_id,
            "episode_id": episode_id,
            "status": "pass" if passed else "fail",
            "baseline_episode": baseline_episode,
            "candidate_runtime_applied": candidate_runtime_applied,
            "turn": metrics.get("turn"),
            "metrics": metrics["metrics"],
            "best_run_metrics": best_metrics["metrics"],
            "best_run_score": t50_best_run_score(best_metrics["metrics"], passed=passed),
            f"t{target_turns}_delta": delta,
        }
        if target_turns != T50_TURNS:
            row["metric_delta"] = delta
        scenario_results.append(row)
        if not passed:
            regressions.append(
                {
                    "episode_id": episode_id,
                    "reason": f"T{target_turns} evidence gate failed",
                }
            )
    report = {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "report_kind": f"multi_t{target_turns}_validation_report",
        "target_turns": target_turns,
        "generated_at": now_iso(),
        "workspace": str(workspace),
        "baseline": baseline_metrics,
        "candidate_package": str(candidate_package) if candidate_package else None,
        "candidate_runtime_applied": candidate_runtime_applied,
        "strategy_runtime_coupled": bool(candidate_runtime_applied and candidate_package),
        "strategy_runtime_note": (
            "Candidate package was supplied to the Observation runner and the caller asserted "
            "--candidate-runtime-applied for this validation."
            if candidate_runtime_applied and candidate_package
            else (
                "This report can validate observed T"
                f"{target_turns} metrics, but it is not proof that a Strategy Candidate asset candidate "
                "changed gameplay behavior unless the caller supplies a candidate package and "
                "--candidate-runtime-applied after running with a strategy-aware runtime."
            )
        ),
        "scenario_results": scenario_results,
        "top_3": pass_only_t50_ranking(
            sorted(
                scenario_results,
                key=lambda row: row["best_run_score"]["rank_key"],
                reverse=True,
            )
        )[:3],
        "best_eligible_top_3": eligible_best_t50_runs(
            sorted(
                scenario_results,
                key=lambda row: row["best_run_score"]["rank_key"],
                reverse=True,
            )
        )[:3],
        "regressions": regressions,
    }
    write_json(output_path, report)
    return report


def run_governance(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    candidate_package: Path,
    validation_report: Path,
    asset_root: Path,
    allow_merge: bool,
) -> dict[str, Any]:
    args = python_module_command(
        "codex_hl.governance.gates",
        "--evaluate",
        "--workspace",
        str(workspace),
        "--asset-root",
        str(asset_root),
        "--candidate-package",
        str(candidate_package),
        "--validation-report",
        str(validation_report),
    )
    if allow_merge:
        args.append("--allow-merge")
    result = runner(args, workspace, {"CODEX_HL_CIV6_WORKSPACE": str(workspace)})
    require_success(result, step="governance_evaluate", command_log=command_log)
    return parse_stdout_json(result.stdout, step="governance_evaluate")


def copy_asset_root(source: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def validate_args(args: argparse.Namespace) -> None:
    runner_kind = getattr(args, "runner", None)
    if runner_kind is not None and runner_kind not in SUPPORTED_RUNNERS:
        allowed = ", ".join(sorted(SUPPORTED_RUNNERS))
        raise EvolutionError(f"--runner must be one of: {allowed}")
    if args.execute and not runner_kind:
        raise EvolutionError("--execute requires --runner live or --runner legacy-baseline")
    if args.cycles < 1:
        raise EvolutionError("--cycles must be >= 1")
    if args.episodes_per_cycle is None:
        args.episodes_per_cycle = (
            T50_CHECKPOINT_EPISODES
            if args.turns == T50_TURNS
            else DEFAULT_EPISODES_PER_CYCLE
        )
    if args.episodes_per_cycle < 1:
        raise EvolutionError("--episodes-per-cycle must be >= 1")
    if args.target_completed_episodes is not None and args.target_completed_episodes < 1:
        raise EvolutionError("--target-completed-episodes must be >= 1")
    if args.episode_retries < 0:
        raise EvolutionError("--episode-retries must be >= 0")
    if args.extra_attempt_slots < 0:
        raise EvolutionError("--extra-attempt-slots must be >= 0")
    if args.turns not in SUPPORTED_OBSERVATION_TURNS:
        allowed = ", ".join(str(turns) for turns in sorted(SUPPORTED_OBSERVATION_TURNS))
        raise EvolutionError(f"--turns must be one of: {allowed}")
    target_completed = args.target_completed_episodes or (args.cycles * args.episodes_per_cycle)
    if args.turns == T50_TURNS and target_completed > MAX_T50_EPISODES:
        raise EvolutionError(f"T50 evolution is capped at {MAX_T50_EPISODES} episodes")
    if args.strategy_profile not in SUPPORTED_STRATEGY_PROFILES:
        allowed = ", ".join(sorted(SUPPORTED_STRATEGY_PROFILES))
        raise EvolutionError(f"--strategy-profile must be one of: {allowed}")
    if args.auto_confirm_min_confidence not in CONFIDENCE_ORDER:
        raise EvolutionError("--auto-confirm-min-confidence must be low, medium, or high")
    if args.allow_merge and not args.candidate_runtime_applied:
        raise EvolutionError(
            "--allow-merge requires --candidate-runtime-applied. "
            "Do not merge from a report that only observed the current runtime."
        )
    if args.candidate_runtime_applied and not args.candidate_package:
        raise EvolutionError("--candidate-runtime-applied requires --candidate-package")
    if args.allow_merge and not args.candidate_package:
        raise EvolutionError("--allow-merge requires --candidate-package")
    if args.candidate_package and not args.candidate_package.exists():
        raise EvolutionError(f"--candidate-package does not exist: {args.candidate_package}")
    if args.stop_on_checkpoint_alert and args.turns != T50_TURNS:
        raise EvolutionError("--stop-on-checkpoint-alert is only supported for T50 runs")
    if args.firetuner_port < 1 or args.firetuner_port > 65535:
        raise EvolutionError("--firetuner-port must be between 1 and 65535")
    if args.checkpoint_only and args.execute:
        raise EvolutionError("--checkpoint-only cannot be combined with --execute")
    if args.checkpoint_only and not args.checkpoint_episodes and not args.checkpoint_manifest:
        raise EvolutionError("--checkpoint-only requires --checkpoint-episodes or --checkpoint-manifest")
    if args.checkpoint_manifest and not args.checkpoint_manifest.exists():
        raise EvolutionError(f"--checkpoint-manifest does not exist: {args.checkpoint_manifest}")
    if args.resume_manifest and not args.resume_manifest.exists():
        raise EvolutionError(f"--resume-manifest does not exist: {args.resume_manifest}")
    if args.resume_manifest and args.checkpoint_only:
        raise EvolutionError("--resume-manifest cannot be combined with --checkpoint-only")
    if args.require_preflight_ready:
        args.preflight = True


def run_evolution(args: argparse.Namespace, *, runner: CommandRunner = run_subprocess) -> dict[str, Any]:
    validate_args(args)
    workspace = args.workspace.resolve()
    asset_root = args.asset_root.resolve()
    resume_source = args.resume_manifest.resolve() if args.resume_manifest else None
    resume_manifest = read_json(resume_source) if resume_source else None
    run_id = args.run_id or str((resume_manifest or {}).get("run_id") or make_run_id())
    run_dir = (
        args.output_dir
        or (resume_source.parent if resume_source else workspace / "evolution" / "runs" / run_id)
    ).resolve()
    command_log = run_dir / "commands.jsonl"
    pool_root = (args.pool_root or workspace / "validation" / "scenarios").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    target_completed = args.target_completed_episodes or (args.cycles * args.episodes_per_cycle)
    runner_kind = getattr(args, "runner", None)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "workflow": WORKFLOW_NAME,
        "run_id": run_id,
        "created_at": now_iso(),
        "workspace": str(workspace),
        "asset_root": str(asset_root),
        "save_name": args.save_name,
        "turns": args.turns,
        "initial_strategy_profile": args.strategy_profile,
        "strategy_profile": args.strategy_profile,
        "runner_kind": runner_kind,
        "runner_deprecation": (
            {
                "deprecated": True,
                "message": (
                    "legacy-baseline is retained only for baseline comparison "
                    "and report rebuild compatibility."
                ),
            }
            if runner_kind == RUNNER_LEGACY_BASELINE
            else None
        ),
        "auto_iterate_strategy": args.auto_iterate_strategy,
        "target_completed_episodes": target_completed,
        "episode_retries": args.episode_retries,
        "extra_attempt_slots": args.extra_attempt_slots,
        "cycles": args.cycles,
        "episodes_per_cycle": args.episodes_per_cycle,
        "checkpoint_episode_interval": (
            args.episodes_per_cycle if args.turns == T50_TURNS else None
        ),
        "max_t50_episodes": MAX_T50_EPISODES if args.turns == T50_TURNS else None,
        "max_t50_observation_attempts": MAX_T50_EPISODES if args.turns == T50_TURNS else None,
        "execute": args.execute,
        "allow_auto_confirmation": args.allow_auto_confirmation,
        "auto_confirm_min_confidence": args.auto_confirm_min_confidence,
        "allow_merge": args.allow_merge,
        "candidate_runtime_applied": args.candidate_runtime_applied,
        "stop_on_checkpoint_alert": args.stop_on_checkpoint_alert,
        "checkpoint_only": args.checkpoint_only,
        "checkpoint_episodes": list(args.checkpoint_episodes or []),
        "checkpoint_manifest": str(args.checkpoint_manifest) if args.checkpoint_manifest else None,
        "resume_manifest": str(resume_source) if resume_source else None,
        "preflight_requested": args.preflight,
        "require_preflight_ready": args.require_preflight_ready,
        "firetuner_port": args.firetuner_port,
        "preflight": None,
        "episodes": [],
        "review": [],
        "auto_confirmations": [],
        "strategy_iterations": [],
        "episode_failures": [],
        "strategy_candidates": [],
        "validation_scenarios": [],
        "candidate_packages": [],
        "validation_report": None,
        "checkpoints": [],
        "governance": None,
        "safety": {
            "no_merge_without_allow_merge": True,
            "no_auto_confirmation_without_flag": True,
            "merge_requires_candidate_runtime_applied": True,
        },
    }
    if resume_manifest is not None:
        resumed_rows = episode_rows_from_manifest(resume_source)
        manifest.update(
            {
                "created_at": resume_manifest.get("created_at", manifest["created_at"]),
                "resume_source": str(resume_source),
                "resumed_at": now_iso(),
                "episodes": resumed_rows,
                "review": list(resume_manifest.get("review") or []),
                "auto_confirmations": list(resume_manifest.get("auto_confirmations") or []),
                "strategy_iterations": list(resume_manifest.get("strategy_iterations") or []),
                "episode_failures": list(resume_manifest.get("episode_failures") or []),
                "strategy_candidates": list(resume_manifest.get("strategy_candidates") or []),
                "validation_scenarios": list(resume_manifest.get("validation_scenarios") or []),
                "candidate_packages": list(resume_manifest.get("candidate_packages") or []),
                "checkpoints": list(resume_manifest.get("checkpoints") or []),
                "validation_report": resume_manifest.get("validation_report"),
                "governance": resume_manifest.get("governance"),
                "completed_episode_count": len(resumed_rows),
            }
        )

    strategy_registry.validate_catalog(asset_root)

    if args.checkpoint_only:
        episode_ids = [str(episode_id) for episode_id in args.checkpoint_episodes]
        checkpoint_failures: list[dict[str, Any]] = []
        if args.checkpoint_manifest:
            checkpoint_manifest_path = args.checkpoint_manifest.resolve()
            manifest_episode_ids = episode_ids_from_manifest(checkpoint_manifest_path)
            episode_ids.extend(
                episode_id
                for episode_id in manifest_episode_ids
                if episode_id not in episode_ids
            )
            checkpoint_failures = episode_failures_from_manifest(checkpoint_manifest_path)
        if not episode_ids:
            raise EvolutionError("No completed episodes found for checkpoint report")
        manifest["checkpoint_episodes"] = episode_ids
        manifest["episode_failures"] = checkpoint_failures
        checkpoint_path = run_dir / "checkpoint_manual.json"
        checkpoint = build_t50_checkpoint_report(
            workspace=workspace,
            output_path=checkpoint_path,
            episode_ids=episode_ids,
            failures=checkpoint_failures,
            target_turns=args.turns,
        )
        manifest["status"] = "checkpoint_reported"
        manifest["checkpoints"].append(str(checkpoint_path))
        manifest["latest_checkpoint_summary"] = {
            "path": str(checkpoint_path),
            "markdown_report": checkpoint.get("markdown_report"),
            "observation_attempt_count": checkpoint.get("observation_attempt_count"),
            "completed_episode_count": checkpoint.get("completed_episode_count"),
            "episode_count": checkpoint["episode_count"],
            "failed_attempt_count": checkpoint.get("failed_attempt_count"),
            "failure_count": checkpoint.get("failure_count"),
            "top_episode": checkpoint["top_3"][0]["episode_id"] if checkpoint["top_3"] else None,
            "best_episode": checkpoint.get("best_episode"),
            "checkpoint_alerts": checkpoint.get("checkpoint_alerts"),
        }
        write_json(run_dir / "manifest.json", manifest)
        return {
            "ok": True,
            "status": "checkpoint_reported",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "checkpoint": str(checkpoint_path),
            "checkpoint_summary": manifest["latest_checkpoint_summary"],
            "manifest": str(run_dir / "manifest.json"),
        }

    if args.preflight:
        preflight = run_connector_preflight(
            runner=runner,
            workspace=workspace,
            command_log=command_log,
            save_name=args.save_name,
            firetuner_port=args.firetuner_port,
        )
        manifest["preflight"] = preflight
        if (args.require_preflight_ready or args.execute) and not preflight.get("ready"):
            manifest["status"] = "preflight_failed"
            write_json(run_dir / "manifest.json", manifest)
            reasons = ", ".join(str(reason) for reason in preflight.get("blocking_reasons") or [])
            raise EvolutionError(f"connector preflight not ready: {reasons}")

    if not args.execute:
        existing_rows = [
            row
            for row in (manifest.get("episodes") or [])
            if isinstance(row, dict)
        ]
        existing_failure_rows = [
            row
            for row in (manifest.get("episode_failures") or [])
            if isinstance(row, dict)
        ]
        observation_attempt_count = recorded_observation_attempt_count(
            existing_rows,
            existing_failure_rows,
        )
        start_slot = max_recorded_slot(existing_rows + existing_failure_rows)
        remaining_completed = max(0, target_completed - len(existing_rows))
        planned_count = remaining_completed
        remaining_attempt_budget: int | None = None
        if args.turns == T50_TURNS:
            remaining_attempt_budget = max(0, MAX_T50_EPISODES - observation_attempt_count)
            planned_count = min(remaining_completed, remaining_attempt_budget)
        planned = [
            episode_id_for(
                run_id,
                cycle_index_for_slot(slot, args.episodes_per_cycle)[0],
                cycle_index_for_slot(slot, args.episodes_per_cycle)[1],
                turns=args.turns,
            )
            for slot in range(start_slot + 1, start_slot + planned_count + 1)
        ]
        manifest["planned_episodes"] = planned
        manifest["resumed_episode_count"] = len(existing_rows)
        manifest["resumed_failure_count"] = len(existing_failure_rows)
        if args.turns == T50_TURNS:
            manifest["t50_observation_attempt_count"] = observation_attempt_count
            manifest["remaining_t50_observation_attempt_budget"] = remaining_attempt_budget
        manifest["remaining_episode_count"] = len(planned)
        if args.turns == T50_TURNS and planned_count < remaining_completed:
            manifest["status"] = "attempt_budget_limited"
            write_json(run_dir / "manifest.json", manifest)
            raise EvolutionError(
                f"Only {remaining_attempt_budget} T50 observation attempt(s) remain, "
                f"but {remaining_completed} completed episode(s) are still needed for target {target_completed}."
            )
        manifest["status"] = "planned"
        write_json(run_dir / "manifest.json", manifest)
        return {
            "ok": True,
            "status": "planned",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "planned_episodes": planned,
            "resumed_episode_count": len(existing_rows),
            "remaining_episode_count": len(planned),
            "manifest": str(run_dir / "manifest.json"),
            "preflight": manifest["preflight"],
        }

    manifest["status"] = "running"
    write_json(run_dir / "manifest.json", manifest)

    episode_ids = [
        str(row.get("episode_id"))
        for row in (manifest.get("episodes") or [])
        if isinstance(row, dict) and row.get("episode_id")
    ]
    current_strategy_profile = str(manifest.get("strategy_profile") or args.strategy_profile)
    observation_attempt_count = recorded_observation_attempt_count(
        [
            row
            for row in (manifest.get("episodes") or [])
            if isinstance(row, dict)
        ],
        [
            row
            for row in (manifest.get("episode_failures") or [])
            if isinstance(row, dict)
        ],
    )
    if args.turns == T50_TURNS:
        manifest["t50_observation_attempt_count"] = observation_attempt_count
    slot = max_recorded_slot(
        [
            row
            for row in (manifest.get("episodes") or [])
            if isinstance(row, dict)
        ]
        + [
            row
            for row in (manifest.get("episode_failures") or [])
            if isinstance(row, dict)
        ]
    )
    max_slots = max(slot, target_completed) + args.extra_attempt_slots
    while (
        len(episode_ids) < target_completed
        and slot < max_slots
        and (args.turns != T50_TURNS or observation_attempt_count < MAX_T50_EPISODES)
    ):
        slot += 1
        cycle, index = cycle_index_for_slot(slot, args.episodes_per_cycle)
        base_episode_id = episode_id_for(run_id, cycle, index, turns=args.turns)
        observation: dict[str, Any] | None = None
        for attempt in range(args.episode_retries + 1):
            if args.turns == T50_TURNS and observation_attempt_count >= MAX_T50_EPISODES:
                break
            if args.turns == T50_TURNS:
                observation_attempt_count += 1
                manifest["t50_observation_attempt_count"] = observation_attempt_count
            episode_id = (
                base_episode_id
                if attempt == 0
                else f"{base_episode_id}_retry{attempt:02d}"
            )
            try:
                observation_runner = (
                    run_live_observation
                    if runner_kind == RUNNER_LIVE
                    else run_observation
                )
                observation = observation_runner(
                    runner=runner,
                    workspace=workspace,
                    command_log=command_log,
                    save_name=args.save_name,
                    episode_id=episode_id,
                    turns=args.turns,
                    strategy_profile=current_strategy_profile,
                    asset_root=asset_root,
                    candidate_package=args.candidate_package if args.candidate_runtime_applied else None,
                )
                observation["strategy_profile"] = current_strategy_profile
                observation["slot"] = slot
                observation["attempt"] = attempt
                observation["runner_kind"] = runner_kind
                break
            except EvolutionError as exc:
                manifest["episode_failures"].append(
                    {
                        "slot": slot,
                        "episode_id": episode_id,
                        "attempt": attempt,
                        "strategy_profile": current_strategy_profile,
                        "error": str(exc),
                        "recorded_at": now_iso(),
                    }
                )
                if (
                    args.turns == T50_TURNS
                    and args.episodes_per_cycle > 0
                    and observation_attempt_count % args.episodes_per_cycle == 0
                ):
                    checkpoint_index = observation_attempt_count // args.episodes_per_cycle
                    checkpoint_path = run_dir / f"checkpoint_c{checkpoint_index:02d}.json"
                    checkpoint = record_t50_checkpoint(
                        manifest=manifest,
                        workspace=workspace,
                        checkpoint_path=checkpoint_path,
                        episode_ids=episode_ids,
                        target_turns=args.turns,
                        observation_attempt_count=observation_attempt_count,
                    )
                    if (
                        args.stop_on_checkpoint_alert
                        and (checkpoint.get("checkpoint_alerts") or {}).get("stop_recommended")
                    ):
                        manifest["status"] = "stopped_for_checkpoint_review"
                        manifest["stopped_at_checkpoint"] = str(checkpoint_path)
                        manifest["stopped_at"] = now_iso()
                        write_json(run_dir / "manifest.json", manifest)
                        return {
                            "ok": True,
                            "status": "stopped_for_checkpoint_review",
                            "run_id": run_id,
                            "run_dir": str(run_dir),
                            "episodes": episode_ids,
                            "validation_report": manifest["validation_report"],
                            "checkpoints": manifest["checkpoints"],
                            "governance": manifest["governance"],
                            "manifest": str(run_dir / "manifest.json"),
                            "preflight": manifest["preflight"],
                        }
                write_json(run_dir / "manifest.json", manifest)
                if attempt >= args.episode_retries:
                    observation = None

        if observation is None:
            continue

        episode_ids.append(str(observation["episode_id"]))
        manifest["episodes"].append(observation)
        manifest["completed_episode_count"] = len(episode_ids)
        write_json(run_dir / "manifest.json", manifest)

        review = run_review_candidates(
            runner=runner,
            workspace=workspace,
            command_log=command_log,
            episode_id=str(observation["episode_id"]),
            session_id=run_id,
        )
        manifest["review"].append(review)

        candidates = read_jsonl(
            workspace / "episodes" / str(observation["episode_id"]) / "review" / "candidates.jsonl"
        )
        if args.auto_iterate_strategy:
            iteration = next_strategy_profile_from_review(
                current_profile=current_strategy_profile,
                candidates=candidates,
            )
            iteration["episode_id"] = str(observation["episode_id"])
            iteration["slot"] = slot
            iteration["candidate_count"] = len(candidates)
            manifest["strategy_iterations"].append(iteration)
            current_strategy_profile = str(iteration["to_profile"])
            manifest["strategy_profile"] = current_strategy_profile

        if args.allow_auto_confirmation:
            auto = apply_auto_confirmation(
                runner=runner,
                workspace=workspace,
                command_log=command_log,
                episode_id=str(observation["episode_id"]),
                min_confidence=args.auto_confirm_min_confidence,
                categories=set(args.auto_confirm_categories),
            )
            manifest["auto_confirmations"].append(auto)
            if auto.get("applied"):
                strategy_candidate = run_strategy_candidates(
                    runner=runner,
                    workspace=workspace,
                    command_log=command_log,
                    episode_id=str(observation["episode_id"]),
                    asset_root=asset_root,
                )
                manifest["strategy_candidates"].append(strategy_candidate)
                validation_scenario = run_validation_scenarios(
                    runner=runner,
                    workspace=workspace,
                    command_log=command_log,
                    episode_id=str(observation["episode_id"]),
                    pool_root=pool_root,
                )
                manifest["validation_scenarios"].append(validation_scenario)
        if (
            args.turns == T50_TURNS
            and args.episodes_per_cycle > 0
            and observation_attempt_count % args.episodes_per_cycle == 0
        ):
            checkpoint_index = observation_attempt_count // args.episodes_per_cycle
            checkpoint_path = run_dir / f"checkpoint_c{checkpoint_index:02d}.json"
            checkpoint = record_t50_checkpoint(
                manifest=manifest,
                workspace=workspace,
                checkpoint_path=checkpoint_path,
                episode_ids=episode_ids,
                target_turns=args.turns,
                observation_attempt_count=observation_attempt_count,
            )
            if (
                args.stop_on_checkpoint_alert
                and (checkpoint.get("checkpoint_alerts") or {}).get("stop_recommended")
            ):
                manifest["status"] = "stopped_for_checkpoint_review"
                manifest["stopped_at_checkpoint"] = str(checkpoint_path)
                manifest["stopped_at"] = now_iso()
                write_json(run_dir / "manifest.json", manifest)
                return {
                    "ok": True,
                    "status": "stopped_for_checkpoint_review",
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "episodes": episode_ids,
                    "validation_report": manifest["validation_report"],
                    "checkpoints": manifest["checkpoints"],
                    "governance": manifest["governance"],
                    "manifest": str(run_dir / "manifest.json"),
                    "preflight": manifest["preflight"],
                }
        write_json(run_dir / "manifest.json", manifest)

    if len(episode_ids) < target_completed:
        if args.turns == T50_TURNS and episode_ids:
            checkpoint_path = run_dir / "checkpoint_partial.json"
            record_t50_checkpoint(
                manifest=manifest,
                workspace=workspace,
                checkpoint_path=checkpoint_path,
                episode_ids=episode_ids,
                target_turns=args.turns,
                observation_attempt_count=observation_attempt_count,
                partial=True,
            )
            manifest["partial_checkpoint"] = str(checkpoint_path)
            manifest["status"] = "incomplete"
            manifest["incomplete_reason"] = "target_not_reached"
            write_json(run_dir / "manifest.json", manifest)
        if args.turns == T50_TURNS and observation_attempt_count >= MAX_T50_EPISODES:
            raise EvolutionError(
                f"Only completed {len(episode_ids)} episode(s), below target {target_completed}, "
                f"before reaching the T50 {MAX_T50_EPISODES}-observation cap. "
                f"Inspect {run_dir / 'manifest.json'} before scheduling more games."
            )
        if manifest.get("status") != "incomplete":
            manifest["status"] = "incomplete"
            manifest["incomplete_reason"] = "target_not_reached"
            write_json(run_dir / "manifest.json", manifest)
        raise EvolutionError(
            f"Only completed {len(episode_ids)} episode(s), below target {target_completed}. "
            f"Increase --extra-attempt-slots or inspect {run_dir / 'manifest.json'}."
        )

    strategy_candidate_packages = sorted(workspace.glob("episodes/*/strategy/candidates/candidate_packages/*/candidate.json"))
    manifest["candidate_packages"] = [str(path) for path in strategy_candidate_packages]

    baseline_episode = args.baseline_episode or (episode_ids[0] if episode_ids else None)
    candidate_episodes = [episode for episode in episode_ids if episode != baseline_episode]
    if baseline_episode and candidate_episodes:
        validation_path = run_dir / f"multi_t{args.turns}_validation_report.json"
        report = build_t50_validation_report(
            workspace=workspace,
            output_path=validation_path,
            baseline_episode=baseline_episode,
            candidate_episodes=candidate_episodes,
            target_turns=args.turns,
            candidate_package=args.candidate_package,
            candidate_runtime_applied=args.candidate_runtime_applied,
        )
        manifest["validation_report"] = str(validation_path)
        manifest["validation_summary"] = {
            "scenario_count": len(report["scenario_results"]),
            "regression_count": len(report["regressions"]),
            "candidate_runtime_applied": report["candidate_runtime_applied"],
            "strategy_runtime_coupled": report["strategy_runtime_coupled"],
        }

    if args.candidate_package and manifest["validation_report"]:
        governance = run_governance(
            runner=runner,
            workspace=workspace,
            command_log=command_log,
            candidate_package=args.candidate_package.resolve(),
            validation_report=Path(str(manifest["validation_report"])),
            asset_root=asset_root,
            allow_merge=args.allow_merge,
        )
        manifest["governance"] = governance

    manifest["status"] = "completed"
    manifest["completed_at"] = now_iso()
    write_json(run_dir / "manifest.json", manifest)
    return {
        "ok": True,
        "status": "completed",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "episodes": episode_ids,
        "validation_report": manifest["validation_report"],
        "checkpoints": manifest["checkpoints"],
        "governance": manifest["governance"],
        "manifest": str(run_dir / "manifest.json"),
        "preflight": manifest["preflight"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--asset-root", type=Path, default=strategy_registry.ASSET_ROOT)
    parser.add_argument("--pool-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--save-name", default="test 1")
    parser.add_argument(
        "--turns",
        type=int,
        default=DEFAULT_OBSERVATION_TURNS,
        choices=sorted(SUPPORTED_OBSERVATION_TURNS),
        help="Observation length per game. Use 20 for local strategy exploration, 50 for validation.",
    )
    parser.add_argument(
        "--strategy-profile",
        default=DEFAULT_STRATEGY_PROFILE,
        choices=sorted(SUPPORTED_STRATEGY_PROFILES),
        help="Runtime strategy profile to pass into Observation observations.",
    )
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument(
        "--episodes-per-cycle",
        type=int,
        default=None,
        help="Checkpoint interval. Defaults to 10 for T50 runs and 3 for shorter exploration.",
    )
    parser.add_argument(
        "--target-completed-episodes",
        type=int,
        help="Keep running scheduled slots until this many observations complete.",
    )
    parser.add_argument(
        "--episode-retries",
        type=int,
        default=0,
        help="Retry a failed Observation observation under a retry-suffixed episode id.",
    )
    parser.add_argument(
        "--extra-attempt-slots",
        type=int,
        default=DEFAULT_EXTRA_ATTEMPT_SLOTS,
        help="Extra scheduled slots allowed after failures when chasing target completions.",
    )
    parser.add_argument("--baseline-episode")
    parser.add_argument("--candidate-package", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually launch Civ6 observations. Without this, only a plan manifest is written.",
    )
    parser.add_argument(
        "--runner",
        choices=sorted(SUPPORTED_RUNNERS),
        help=(
            "Required with --execute. Use live for the JSON-plan live path, "
            "or legacy-baseline for deprecated baseline comparison."
        ),
    )
    parser.add_argument(
        "--allow-auto-confirmation",
        action="store_true",
        help="Apply a restricted auto-confirmation policy to Review candidates.",
    )
    parser.add_argument(
        "--auto-iterate-strategy",
        action="store_true",
        help="Use Review candidates to switch runtime strategy profile during the run.",
    )
    parser.add_argument(
        "--auto-confirm-min-confidence",
        default="high",
        choices=sorted(CONFIDENCE_ORDER),
    )
    parser.add_argument(
        "--auto-confirm-categories",
        nargs="*",
        default=sorted(DEFAULT_AUTO_CONFIRM_CATEGORIES),
    )
    parser.add_argument(
        "--candidate-runtime-applied",
        action="store_true",
        help="Assert that validation episodes were run with the candidate strategy active.",
    )
    parser.add_argument(
        "--stop-on-checkpoint-alert",
        action="store_true",
        help="For T50 runs, stop after a checkpoint when critical strategy alerts recommend review.",
    )
    parser.add_argument(
        "--checkpoint-only",
        action="store_true",
        help="Build a checkpoint report for existing episode ids without launching new observations.",
    )
    parser.add_argument(
        "--checkpoint-episodes",
        nargs="*",
        default=[],
        help="Episode ids to include when --checkpoint-only is used.",
    )
    parser.add_argument(
        "--checkpoint-manifest",
        type=Path,
        help="Existing evolution manifest whose completed episodes should be checkpointed.",
    )
    parser.add_argument(
        "--resume-manifest",
        type=Path,
        help="Existing evolution manifest to resume from instead of starting from slot 1.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run safe connector diagnostics and record save/Civ6/FireTuner readiness before planning or executing.",
    )
    parser.add_argument(
        "--require-preflight-ready",
        action="store_true",
        help="Run preflight and stop before scheduling if the save, Civ6 process, or FireTuner port is not ready.",
    )
    parser.add_argument(
        "--firetuner-port",
        type=int,
        default=DEFAULT_FIRETUNER_PORT,
        help="FireTuner localhost port to check during preflight.",
    )
    parser.add_argument(
        "--allow-merge",
        action="store_true",
        help="Forward --allow-merge to governance after validation gates pass.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = run_evolution(args)
    except (EvolutionError, strategy_registry.StrategyAssetError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

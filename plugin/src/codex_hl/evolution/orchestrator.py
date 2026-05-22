"""Multi-turn evolution orchestration for Codex HL Civ6.

This module is the first explicit self-evolution control plane.  It can run
multiple real T20/T50 observations, generate Phase 2 candidates, optionally apply a
restricted auto-confirmation policy, build Phase 4/5 artifacts, and create a
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

from codex_hl.phase3 import assets as phase3_assets


WORKSPACE_ROOT = Path(os.environ.get("CODEX_HL_CIV6_WORKSPACE") or Path.cwd()).resolve()
PHASE_NAME = "Codex HL Evolution Orchestrator"
T20_TURNS = 20
T50_TURNS = 50
DEFAULT_OBSERVATION_TURNS = T50_TURNS
SUPPORTED_OBSERVATION_TURNS = {T20_TURNS, T50_TURNS}
DEFAULT_STRATEGY_PROFILE = "baseline_static"
SUPPORTED_STRATEGY_PROFILES = {DEFAULT_STRATEGY_PROFILE, "explore_scout_first"}
DEFAULT_EXTRA_ATTEMPT_SLOTS = 5
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
DEFAULT_AUTO_CONFIRM_CATEGORIES = {"planning", "execution", "verification", "recovery"}


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
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


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


def run_phase1_observation(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    save_name: str,
    episode_id: str,
    turns: int,
    strategy_profile: str,
    asset_root: Path | None,
) -> dict[str, Any]:
    env = {"CODEX_HL_CIV6_WORKSPACE": str(workspace)}
    if asset_root is not None:
        env["CODEX_HL_CIV6_PHASE3_ASSET_ROOT"] = str(asset_root)
    result = runner(
        python_module_command(
            "codex_hl.phase1.observer",
            "--save-name",
            save_name,
            "--turns",
            str(turns),
            "--episode-id",
            episode_id,
            "--strategy-profile",
            strategy_profile,
        ),
        workspace,
        env,
    )
    require_success(result, step=f"phase1_t{turns}:{episode_id}", command_log=command_log)
    payload = parse_stdout_json(result.stdout, step=f"phase1_t{turns}")
    payload.setdefault("episode_id", episode_id)
    return payload


def run_phase2_candidates(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    session_id: str,
) -> dict[str, Any]:
    result = runner(
        python_module_command(
            "codex_hl.phase2.labeler",
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
    require_success(result, step=f"phase2_candidates:{episode_id}", command_log=command_log)
    return parse_stdout_json(result.stdout, step="phase2_candidates")


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
    phase2_dir = workspace / "episodes" / episode_id / "phase2"
    candidates = read_jsonl(phase2_dir / "candidates.jsonl")
    rows = selected_auto_confirmations(
        candidates,
        min_confidence=min_confidence,
        categories=categories,
    )
    confirmation_path = phase2_dir / "confirmation" / "auto_evolution_confirmation.jsonl"
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
            "codex_hl.phase2.labeler",
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
    require_success(result, step=f"phase2_apply:{episode_id}", command_log=command_log)
    payload = parse_stdout_json(result.stdout, step="phase2_apply")
    payload["confirmation_path"] = str(confirmation_path)
    payload["selected"] = len(rows)
    payload["applied"] = True
    return payload


def next_strategy_profile_from_phase2(
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
    if current_profile == DEFAULT_STRATEGY_PROFILE and (
        "早期单位持续驻守" in text
        or "侦察兵" in text
        or "探索价值" in text
        or "建造者而非侦察兵" in text
    ):
        next_profile = "explore_scout_first"
        reasons.append("phase2_repeated_opening_exploration_candidate")
    return {
        "from_profile": current_profile,
        "to_profile": next_profile,
        "changed": next_profile != current_profile,
        "reason_codes": reasons,
    }


def run_phase4_candidates(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    asset_root: Path,
) -> dict[str, Any]:
    result = runner(
        python_module_command(
            "codex_hl.phase4.improvements",
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
    require_success(result, step=f"phase4_candidates:{episode_id}", command_log=command_log)
    return parse_stdout_json(result.stdout, step="phase4_candidates")


def run_phase5_scenarios(
    *,
    runner: CommandRunner,
    workspace: Path,
    command_log: Path,
    episode_id: str,
    pool_root: Path,
) -> dict[str, Any]:
    result = runner(
        python_module_command(
            "codex_hl.phase5.scenarios",
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
    require_success(result, step=f"phase5_scenarios:{episode_id}", command_log=command_log)
    return parse_stdout_json(result.stdout, step="phase5_scenarios")


def evidence_passed(report_pack: dict[str, Any]) -> bool:
    statuses = report_pack.get("evidence_status")
    if not isinstance(statuses, dict):
        return False
    return bool(statuses) and all(
        isinstance(row, dict) and row.get("status") == "PASS" for row in statuses.values()
    )


def load_episode_report_pack(workspace: Path, episode_id: str) -> dict[str, Any]:
    return read_json(workspace / "episodes" / episode_id / "derived" / "report_pack.json")


def episode_turns_passed(workspace: Path, episode_id: str, *, target_turns: int) -> bool:
    report_pack = load_episode_report_pack(workspace, episode_id)
    run = report_pack.get("run") if isinstance(report_pack.get("run"), dict) else {}
    return run.get("actual_turns") == target_turns and evidence_passed(report_pack)


def t50_episode_passed(workspace: Path, episode_id: str) -> bool:
    return episode_turns_passed(workspace, episode_id, target_turns=T50_TURNS)


def metric_delta(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float | int | None]:
    delta: dict[str, float | int | None] = {}
    for key in phase3_assets.NUMERIC_T50_METRICS:
        base_value = base.get(key)
        cand_value = candidate.get(key)
        if isinstance(base_value, (int, float)) and isinstance(cand_value, (int, float)):
            delta[key] = cand_value - base_value
        else:
            delta[key] = None
    return delta


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
    baseline_metrics = phase3_assets.extract_t50_metrics(baseline_episode, workspace=workspace)
    baseline_values = baseline_metrics["metrics"]
    scenario_results: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for episode_id in candidate_episodes:
        metrics = phase3_assets.extract_t50_metrics(episode_id, workspace=workspace)
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
        "phase": PHASE_NAME,
        "report_kind": f"multi_t{target_turns}_validation_report",
        "target_turns": target_turns,
        "generated_at": now_iso(),
        "workspace": str(workspace),
        "baseline": baseline_metrics,
        "candidate_package": str(candidate_package) if candidate_package else None,
        "candidate_runtime_applied": candidate_runtime_applied,
        "strategy_runtime_coupled": False,
        "strategy_runtime_note": (
            "Current Phase 1 runner still uses static blocker-resolution priorities. "
            f"This report can validate observed T{target_turns} metrics, but it is not proof that a "
            "Phase 4 asset candidate changed gameplay behavior unless the caller supplies "
            "--candidate-runtime-applied after running with a strategy-aware runtime."
        ),
        "scenario_results": scenario_results,
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
        "codex_hl.governance.automation",
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
    if args.cycles < 1:
        raise EvolutionError("--cycles must be >= 1")
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
    if args.allow_merge and not args.candidate_package:
        raise EvolutionError("--allow-merge requires --candidate-package")


def run_evolution(args: argparse.Namespace, *, runner: CommandRunner = run_subprocess) -> dict[str, Any]:
    validate_args(args)
    workspace = args.workspace.resolve()
    asset_root = args.asset_root.resolve()
    run_id = args.run_id or make_run_id()
    run_dir = (args.output_dir or workspace / "evolution" / "runs" / run_id).resolve()
    command_log = run_dir / "commands.jsonl"
    pool_root = (args.pool_root or workspace / "validation" / "regression_scenarios").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    target_completed = args.target_completed_episodes or (args.cycles * args.episodes_per_cycle)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "phase": PHASE_NAME,
        "run_id": run_id,
        "created_at": now_iso(),
        "workspace": str(workspace),
        "asset_root": str(asset_root),
        "save_name": args.save_name,
        "turns": args.turns,
        "initial_strategy_profile": args.strategy_profile,
        "strategy_profile": args.strategy_profile,
        "auto_iterate_strategy": args.auto_iterate_strategy,
        "target_completed_episodes": target_completed,
        "episode_retries": args.episode_retries,
        "extra_attempt_slots": args.extra_attempt_slots,
        "cycles": args.cycles,
        "episodes_per_cycle": args.episodes_per_cycle,
        "execute": args.execute,
        "allow_auto_confirmation": args.allow_auto_confirmation,
        "auto_confirm_min_confidence": args.auto_confirm_min_confidence,
        "allow_merge": args.allow_merge,
        "candidate_runtime_applied": args.candidate_runtime_applied,
        "episodes": [],
        "phase2": [],
        "auto_confirmations": [],
        "strategy_iterations": [],
        "episode_failures": [],
        "phase4": [],
        "phase5": [],
        "candidate_packages": [],
        "validation_report": None,
        "governance": None,
        "safety": {
            "no_merge_without_allow_merge": True,
            "no_auto_confirmation_without_flag": True,
            "merge_requires_candidate_runtime_applied": True,
        },
    }

    phase3_assets.validate_catalog(asset_root)

    if not args.execute:
        planned = [
            episode_id_for(
                run_id,
                cycle_index_for_slot(slot, args.episodes_per_cycle)[0],
                cycle_index_for_slot(slot, args.episodes_per_cycle)[1],
                turns=args.turns,
            )
            for slot in range(1, target_completed + 1)
        ]
        manifest["planned_episodes"] = planned
        manifest["status"] = "planned"
        write_json(run_dir / "manifest.json", manifest)
        return {
            "ok": True,
            "status": "planned",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "planned_episodes": planned,
            "manifest": str(run_dir / "manifest.json"),
        }

    manifest["status"] = "running"
    write_json(run_dir / "manifest.json", manifest)

    episode_ids: list[str] = []
    current_strategy_profile = args.strategy_profile
    max_slots = target_completed + args.extra_attempt_slots
    slot = 0
    while len(episode_ids) < target_completed and slot < max_slots:
        slot += 1
        cycle, index = cycle_index_for_slot(slot, args.episodes_per_cycle)
        base_episode_id = episode_id_for(run_id, cycle, index, turns=args.turns)
        observation: dict[str, Any] | None = None
        for attempt in range(args.episode_retries + 1):
            episode_id = (
                base_episode_id
                if attempt == 0
                else f"{base_episode_id}_retry{attempt:02d}"
            )
            try:
                observation = run_phase1_observation(
                    runner=runner,
                    workspace=workspace,
                    command_log=command_log,
                    save_name=args.save_name,
                    episode_id=episode_id,
                    turns=args.turns,
                    strategy_profile=current_strategy_profile,
                    asset_root=asset_root,
                )
                observation["strategy_profile"] = current_strategy_profile
                observation["slot"] = slot
                observation["attempt"] = attempt
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
                write_json(run_dir / "manifest.json", manifest)
                if attempt >= args.episode_retries:
                    observation = None

        if observation is None:
            continue

        episode_ids.append(str(observation["episode_id"]))
        manifest["episodes"].append(observation)
        manifest["completed_episode_count"] = len(episode_ids)
        write_json(run_dir / "manifest.json", manifest)

        phase2 = run_phase2_candidates(
            runner=runner,
            workspace=workspace,
            command_log=command_log,
            episode_id=str(observation["episode_id"]),
            session_id=run_id,
        )
        manifest["phase2"].append(phase2)

        candidates = read_jsonl(
            workspace / "episodes" / str(observation["episode_id"]) / "phase2" / "candidates.jsonl"
        )
        if args.auto_iterate_strategy:
            iteration = next_strategy_profile_from_phase2(
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
                phase4 = run_phase4_candidates(
                    runner=runner,
                    workspace=workspace,
                    command_log=command_log,
                    episode_id=str(observation["episode_id"]),
                    asset_root=asset_root,
                )
                manifest["phase4"].append(phase4)
                phase5 = run_phase5_scenarios(
                    runner=runner,
                    workspace=workspace,
                    command_log=command_log,
                    episode_id=str(observation["episode_id"]),
                    pool_root=pool_root,
                )
                manifest["phase5"].append(phase5)
        write_json(run_dir / "manifest.json", manifest)

    if len(episode_ids) < target_completed:
        raise EvolutionError(
            f"Only completed {len(episode_ids)} episode(s), below target {target_completed}. "
            f"Increase --extra-attempt-slots or inspect {run_dir / 'manifest.json'}."
        )

    phase4_packages = sorted(workspace.glob("episodes/*/phase4/candidate_packages/*/candidate.json"))
    manifest["candidate_packages"] = [str(path) for path in phase4_packages]

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
        "governance": manifest["governance"],
        "manifest": str(run_dir / "manifest.json"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--asset-root", type=Path, default=phase3_assets.ASSET_ROOT)
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
        help="Runtime strategy profile to pass into Phase 1 observations.",
    )
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--episodes-per-cycle", type=int, default=3)
    parser.add_argument(
        "--target-completed-episodes",
        type=int,
        help="Keep running scheduled slots until this many observations complete.",
    )
    parser.add_argument(
        "--episode-retries",
        type=int,
        default=0,
        help="Retry a failed Phase 1 observation under a retry-suffixed episode id.",
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
        "--allow-auto-confirmation",
        action="store_true",
        help="Apply a restricted auto-confirmation policy to Phase 2 candidates.",
    )
    parser.add_argument(
        "--auto-iterate-strategy",
        action="store_true",
        help="Use Phase 2 candidates to switch runtime strategy profile during the run.",
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
        "--allow-merge",
        action="store_true",
        help="Forward --allow-merge to governance after validation gates pass.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = run_evolution(args)
    except (EvolutionError, phase3_assets.Phase3AssetError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

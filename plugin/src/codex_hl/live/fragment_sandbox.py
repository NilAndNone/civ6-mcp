from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from codex_hl.live.ledger import (
    LIVE_EVENTS_LOGICAL_PATH,
    EpisodeLedger,
    mirror_jsonl_to_episode_db,
    now_iso,
    read_jsonl_from_episode_db,
    to_jsonable,
)
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.plan_store import LivePlanStore
from codex_hl.live.schemas import StepStatus, canonical_json


FRAGMENT_FEATURE_ENV = "CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS"
LIVE_FRAGMENTS_LOGICAL_PATH = "raw/live_fragments.jsonl"
MAX_SOURCE_BYTES = 16_384
MAX_WORKER_OUTPUT_BYTES = 65_536
WORKER_TIMEOUT_SECONDS = 3.0

ALLOWED_FRAGMENT_TOOLS = {
    "city_action",
    "purchase_item",
    "purchase_tile",
    "set_city_production",
    "set_research",
    "unit_action",
}
ALLOWED_HELPERS = {"read_context", "assert_precondition", "assert_postcondition"}
_BANNED_NAMES = {
    "__builtins__",
    "__import__",
    "compile",
    "eval",
    "exec",
    "globals",
    "locals",
    "open",
    "subprocess",
}
_BANNED_NODES = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.AsyncWith,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.DictComp,
    ast.For,
    ast.GeneratorExp,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Lambda,
    ast.ListComp,
    ast.Match,
    ast.NamedExpr,
    ast.Nonlocal,
    ast.Raise,
    ast.SetComp,
    ast.Try,
    ast.While,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)


class FragmentSandboxError(RuntimeError):
    """User-facing live fragment sandbox error."""


def fragments_enabled() -> bool:
    return os.environ.get(FRAGMENT_FEATURE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_fragments_enabled() -> None:
    if not fragments_enabled():
        raise FragmentSandboxError(
            f"live fragments are disabled; set {FRAGMENT_FEATURE_ENV}=1 to enable"
        )


def source_sha256(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _stable_fragment_id(
    *,
    episode_id: str,
    plan_id: str,
    step_id: str,
    context_hash: str,
    source_hash: str,
) -> str:
    payload = canonical_json(
        {
            "context_hash": context_hash,
            "episode_id": episode_id,
            "plan_id": plan_id,
            "source_hash": source_hash,
            "step_id": step_id,
        }
    )
    return "frag_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:14]


def analyze_fragment_source(source: str) -> dict[str, Any]:
    """Analyze fragment source in a subprocess and return a safe call plan."""

    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise FragmentSandboxError(
            f"fragment source exceeds {MAX_SOURCE_BYTES} bytes"
        )
    payload = json.dumps({"source": source}, ensure_ascii=False)
    env = os.environ.copy()
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = (
        src_root
        if not env.get("PYTHONPATH")
        else src_root + os.pathsep + str(env["PYTHONPATH"])
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "codex_hl.live.fragment_sandbox", "--worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(payload, timeout=WORKER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.communicate()
        raise FragmentSandboxError("fragment analysis timed out") from exc
    if len(stdout.encode("utf-8")) > MAX_WORKER_OUTPUT_BYTES:
        raise FragmentSandboxError("fragment worker output exceeded limit")
    if not stdout.strip() and stderr.strip():
        raise FragmentSandboxError(f"fragment worker failed: {stderr.strip()}")
    try:
        result = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FragmentSandboxError(
            f"fragment worker returned invalid JSON: {stderr.strip()}"
        ) from exc
    if not result.get("ok"):
        raise FragmentSandboxError(str(result.get("error") or "fragment rejected"))
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        raise FragmentSandboxError("fragment worker returned invalid analysis")
    return analysis


def _analyze_fragment_source_in_process(source: str) -> dict[str, Any]:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise FragmentSandboxError(
            f"fragment source exceeds {MAX_SOURCE_BYTES} bytes"
        )
    try:
        module = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise FragmentSandboxError(f"fragment syntax error: {exc}") from exc
    _reject_banned_ast(module)
    run_function = _find_run_function(module)
    calls = _extract_run_calls(run_function)
    _validate_helper_order(calls)
    mutating = [call for call in calls if call["kind"] == "mutation"]
    if len(mutating) != 1:
        raise FragmentSandboxError(
            f"fragment must contain exactly one mutating live call, got {len(mutating)}"
        )
    mutation = mutating[0]
    preconditions = [
        call["condition"]
        for call in calls
        if call["kind"] == "helper" and call["name"] == "assert_precondition"
    ]
    postconditions = [
        call["condition"]
        for call in calls
        if call["kind"] == "helper" and call["name"] == "assert_postcondition"
    ]
    return {
        "schema_version": 1,
        "source_sha256": source_sha256(source),
        "tool_name": mutation["name"],
        "args": mutation["args"],
        "preconditions": preconditions,
        "postconditions": postconditions,
        "calls": calls,
    }


def _reject_banned_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODES):
            raise FragmentSandboxError(
                f"fragment uses forbidden syntax: {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and (
            node.id in _BANNED_NAMES or node.id.startswith("__")
        ):
            raise FragmentSandboxError(f"fragment uses forbidden name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise FragmentSandboxError(f"fragment uses forbidden attribute: {node.attr}")


def _find_run_function(module: ast.Module) -> ast.FunctionDef:
    run_functions = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    ]
    if len(run_functions) != 1:
        raise FragmentSandboxError("fragment must define exactly one run(live) function")
    run_function = run_functions[0]
    if run_function.decorator_list:
        raise FragmentSandboxError("fragment run() decorators are forbidden")
    if len(run_function.args.args) != 1 or run_function.args.args[0].arg != "live":
        raise FragmentSandboxError("fragment entrypoint must be run(live)")
    if run_function.args.vararg or run_function.args.kwarg:
        raise FragmentSandboxError("fragment run() cannot use *args or **kwargs")
    return run_function


def _extract_run_calls(run_function: ast.FunctionDef) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for statement in run_function.body:
        call: ast.Call | None = None
        if isinstance(statement, ast.Expr):
            if isinstance(statement.value, ast.Constant) and isinstance(
                statement.value.value, str
            ):
                continue
            if not isinstance(statement.value, ast.Call):
                raise FragmentSandboxError("fragment expression must be a live.* call")
            call = statement.value
        elif isinstance(statement, ast.Assign):
            _validate_assignment_targets(statement.targets)
            if not isinstance(statement.value, ast.Call):
                raise FragmentSandboxError(
                    "fragment assignments can only bind live.* call results"
                )
            call = statement.value
        elif isinstance(statement, ast.Return):
            if isinstance(statement.value, ast.Call):
                calls.append(_extract_live_call(statement.value))
            else:
                _validate_safe_return(statement.value)
            continue
        else:
            raise FragmentSandboxError(
                f"fragment statement is not allowed: {type(statement).__name__}"
            )
        calls.append(_extract_live_call(call))
    return calls


def _validate_assignment_targets(targets: list[ast.expr]) -> None:
    for target in targets:
        if not isinstance(target, ast.Name) or target.id.startswith("__"):
            raise FragmentSandboxError("fragment assignments can only target names")


def _extract_live_call(call: ast.Call) -> dict[str, Any]:
    if not isinstance(call.func, ast.Attribute) or not isinstance(
        call.func.value, ast.Name
    ):
        raise FragmentSandboxError("fragment calls must target live.*")
    if call.func.value.id != "live":
        raise FragmentSandboxError("fragment calls must target live.*")
    name = call.func.attr
    if name not in ALLOWED_HELPERS and name not in ALLOWED_FRAGMENT_TOOLS:
        raise FragmentSandboxError(f"fragment live.{name} is not allowed")
    if name in ALLOWED_FRAGMENT_TOOLS and call.args:
        raise FragmentSandboxError("mutating fragment calls must use keyword args")
    args = _literal_kwargs(call.keywords)
    if name == "read_context":
        if call.args or args:
            raise FragmentSandboxError("live.read_context() takes no arguments")
        return {"kind": "helper", "name": name, "args": {}}
    if name in {"assert_precondition", "assert_postcondition"}:
        if len(call.args) != 1 or not isinstance(call.args[0], ast.Constant):
            raise FragmentSandboxError(f"live.{name} requires one string condition")
        condition_name = call.args[0].value
        if not isinstance(condition_name, str) or not condition_name.strip():
            raise FragmentSandboxError(f"live.{name} requires one string condition")
        return {
            "kind": "helper",
            "name": name,
            "args": args,
            "condition": {"type": condition_name.strip(), **args},
        }
    return {"kind": "mutation", "name": name, "args": args}


def _validate_helper_order(calls: list[dict[str, Any]]) -> None:
    mutation_seen = False
    for call in calls:
        if call.get("kind") == "mutation":
            mutation_seen = True
            continue
        if call.get("kind") != "helper":
            continue
        name = str(call.get("name") or "")
        if name == "assert_precondition" and mutation_seen:
            raise FragmentSandboxError(
                "fragment preconditions must appear before the mutating call"
            )
        if name == "assert_postcondition" and not mutation_seen:
            raise FragmentSandboxError(
                "fragment postconditions must appear after the mutating call"
            )


def _literal_kwargs(keywords: list[ast.keyword]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for keyword in keywords:
        if keyword.arg is None:
            raise FragmentSandboxError("fragment **kwargs are forbidden")
        if keyword.arg.startswith("__"):
            raise FragmentSandboxError("fragment dunder kwargs are forbidden")
        args[keyword.arg] = _literal_value(keyword.value)
    return args


def _literal_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, (str, int, float, bool)):
            return node.value
        raise FragmentSandboxError("fragment constants must be JSON-compatible")
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal_value(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        value: dict[str, Any] = {}
        for raw_key, raw_value in zip(node.keys, node.values):
            if raw_key is None:
                raise FragmentSandboxError("fragment dict unpacking is forbidden")
            key = _literal_value(raw_key)
            if not isinstance(key, str):
                raise FragmentSandboxError("fragment dict keys must be strings")
            value[key] = _literal_value(raw_value)
        return value
    raise FragmentSandboxError(
        f"fragment arguments must be JSON literals, got {type(node).__name__}"
    )


def _validate_safe_return(node: ast.AST | None) -> None:
    if node is None:
        return
    if isinstance(node, ast.Name):
        if node.id.startswith("__") or node.id in _BANNED_NAMES:
            raise FragmentSandboxError(f"fragment returns forbidden name: {node.id}")
        return
    if isinstance(node, ast.Constant):
        return
    if isinstance(node, (ast.List, ast.Tuple)):
        for item in node.elts:
            _validate_safe_return(item)
        return
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if key is not None:
                _validate_safe_return(key)
            _validate_safe_return(value)
        return
    raise FragmentSandboxError(
        f"fragment return expression is not allowed: {type(node).__name__}"
    )


def append_fragment_event(
    *,
    episode_root: Path,
    episode_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(payload)
    request_id = str(payload.get("request_id") or f"fragment-{uuid.uuid4().hex}")
    status = _fragment_event_status(event_type)
    error = payload.get("error") if isinstance(payload.get("error"), str) else None
    result = payload.get("result")
    ledger = EpisodeLedger.for_episode_root(episode_root, episode_id)
    ledger_event_id = ledger.append_event(
        event_type=event_type,
        request=SimpleNamespace(
            request_id=request_id,
            episode_id=episode_id,
            turn=payload.get("turn"),
            branch_id=payload.get("branch_id"),
            plan_id=payload.get("plan_id"),
            step_id=payload.get("step_id"),
            tool_name=payload.get("tool_name") or "live_fragment",
            source="fragment",
            mutation_level=MutationLevel.L1_RUNTIME_SIDE_EFFECT,
            context_hash=payload.get("context_hash"),
            args=payload.get("args") if isinstance(payload.get("args"), dict) else {},
        ),
        mode=str(payload.get("mode") or "live_strict"),
        allowed=status != "rejected",
        status=status,
        unplanned_mutation=False,
        result=result,
        error=error,
        payload=payload,
    )
    payload.setdefault("ledger_event_ids", [ledger_event_id])
    path = episode_root / LIVE_FRAGMENTS_LOGICAL_PATH
    row = {
        "event_id": f"fragment-{uuid.uuid4().hex}",
        "episode_id": episode_id,
        "ts": now_iso(),
        "event_type": event_type,
        "fragment_id": payload.get("fragment_id"),
        "plan_id": payload.get("plan_id"),
        "step_id": payload.get("step_id"),
        "context_hash": payload.get("context_hash"),
        "ledger_event_ids": [ledger_event_id],
        "payload": to_jsonable(payload),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
    mirror_jsonl_to_episode_db(
        episode_root=episode_root,
        episode_id=episode_id,
        logical_path=LIVE_FRAGMENTS_LOGICAL_PATH,
        source_path=path,
        kind="live_fragments",
    )
    return row


def read_fragment_events(*, episode_root: Path, episode_id: str) -> list[dict[str, Any]]:
    ledger_events = _read_fragment_ledger_events(
        episode_root=episode_root, episode_id=episode_id
    )
    if ledger_events:
        return ledger_events
    return _read_fragment_compat_events(episode_root=episode_root, episode_id=episode_id)


def read_fragment_compat_events(
    *, episode_root: Path, episode_id: str
) -> list[dict[str, Any]]:
    return _read_fragment_compat_events(episode_root=episode_root, episode_id=episode_id)


def _read_fragment_ledger_events(
    *, episode_root: Path, episode_id: str
) -> list[dict[str, Any]]:
    rows = read_jsonl_from_episode_db(
        episode_root=episode_root,
        episode_id=episode_id,
        logical_path=LIVE_EVENTS_LOGICAL_PATH,
    )
    path = episode_root / LIVE_EVENTS_LOGICAL_PATH
    if rows is None and path.exists():
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return [
        row
        for row in rows or []
        if isinstance(row, dict) and str(row.get("event_type") or "").startswith("FRAGMENT_")
    ]


def _read_fragment_compat_events(
    *, episode_root: Path, episode_id: str
) -> list[dict[str, Any]]:
    db_rows = read_jsonl_from_episode_db(
        episode_root=episode_root,
        episode_id=episode_id,
        logical_path=LIVE_FRAGMENTS_LOGICAL_PATH,
    )
    if db_rows is not None:
        return db_rows
    path = episode_root / LIVE_FRAGMENTS_LOGICAL_PATH
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fragment_event_status(event_type: str) -> str:
    if event_type.endswith("_REJECTED"):
        return "rejected"
    if event_type.endswith("_STARTED"):
        return "executing"
    if event_type.endswith("_REGISTERED"):
        return "registered"
    if event_type.endswith("_FINISHED"):
        return "executed"
    return "recorded"


def register_fragment_binding(
    *,
    plan_store: LivePlanStore,
    source: str,
    episode_id: str,
    plan_id: str,
    step_id: str,
    context_hash: str,
) -> dict[str, Any]:
    require_fragments_enabled()
    step = _validate_step_binding(
        plan_store=plan_store,
        plan_id=plan_id,
        step_id=step_id,
        context_hash=context_hash,
        require_armed=False,
    )
    analysis = analyze_fragment_source(source)
    _validate_analysis_matches_step(analysis, step_tool=step.tool, step_args=step.args)
    _validate_fragment_postconditions_match_step(
        analysis.get("postconditions", []), step.postconditions
    )
    source_hash = str(analysis["source_sha256"])
    fragment_id = _stable_fragment_id(
        episode_id=episode_id,
        plan_id=plan_id,
        step_id=step_id,
        context_hash=context_hash,
        source_hash=source_hash,
    )
    binding = {
        "schema_version": 1,
        "fragment_id": fragment_id,
        "episode_id": episode_id,
        "plan_id": plan_id,
        "step_id": step_id,
        "context_hash": context_hash,
        "source_sha256": source_hash,
        "source_size_bytes": len(source.encode("utf-8")),
        "tool_name": analysis["tool_name"],
        "args": analysis["args"],
        "preconditions": analysis.get("preconditions", []),
        "postconditions": analysis.get("postconditions", []),
        "calls": analysis.get("calls", []),
        "status": "registered",
    }
    event = append_fragment_event(
        episode_root=plan_store.episode_root,
        episode_id=episode_id,
        event_type="FRAGMENT_REGISTERED",
        payload=binding,
    )
    binding["ledger_event_ids"] = list(event.get("ledger_event_ids") or [])
    return binding


def validate_fragment_execution_binding(
    *,
    plan_store: LivePlanStore,
    fragment_id: str,
    episode_id: str,
    plan_id: str,
    step_id: str,
    context_hash: str,
) -> dict[str, Any]:
    require_fragments_enabled()
    binding = read_registered_fragment(
        episode_root=plan_store.episode_root,
        episode_id=episode_id,
        fragment_id=fragment_id,
    )
    if binding is None:
        raise FragmentSandboxError(f"fragment is not registered: {fragment_id}")
    for key, expected in (
        ("episode_id", episode_id),
        ("plan_id", plan_id),
        ("step_id", step_id),
        ("context_hash", context_hash),
    ):
        if binding.get(key) != expected:
            raise FragmentSandboxError(f"fragment {key} binding mismatch")
    step = _validate_step_binding(
        plan_store=plan_store,
        plan_id=plan_id,
        step_id=step_id,
        context_hash=context_hash,
        require_armed=True,
    )
    _validate_analysis_matches_step(binding, step_tool=step.tool, step_args=step.args)
    _validate_fragment_postconditions_match_step(
        binding.get("postconditions", []), step.postconditions
    )
    return binding


def read_registered_fragment(
    *,
    episode_root: Path,
    episode_id: str,
    fragment_id: str,
) -> dict[str, Any] | None:
    main_events = _read_fragment_ledger_events(
        episode_root=episode_root, episode_id=episode_id
    )
    payload = _find_registered_fragment_payload(main_events, fragment_id)
    if payload is not None:
        return payload
    compat_events = _read_fragment_compat_events(
        episode_root=episode_root, episode_id=episode_id
    )
    return _find_registered_fragment_payload(compat_events, fragment_id)


def _find_registered_fragment_payload(
    events: list[dict[str, Any]], fragment_id: str
) -> dict[str, Any] | None:
    for row in reversed(events):
        if row.get("event_type") != "FRAGMENT_REGISTERED":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if payload.get("fragment_id") == fragment_id:
            return dict(payload)
    return None


def _validate_step_binding(
    *,
    plan_store: LivePlanStore,
    plan_id: str,
    step_id: str,
    context_hash: str,
    require_armed: bool,
):
    plan = plan_store.get_plan(plan_id)
    if plan.context_hash != context_hash:
        raise FragmentSandboxError("fragment context_hash does not match plan")
    step = plan_store.get_step(plan_id, step_id)
    if not step.fragment_allowed:
        raise FragmentSandboxError(f"step does not allow fragments: {plan_id}/{step_id}")
    if require_armed and step.status is not StepStatus.ARMED:
        raise FragmentSandboxError(
            f"fragment step must be ARMED before execution, got {step.status.value}"
        )
    return step


def _validate_analysis_matches_step(
    analysis: dict[str, Any],
    *,
    step_tool: str,
    step_args: dict[str, Any],
) -> None:
    if analysis.get("tool_name") != step_tool:
        raise FragmentSandboxError(
            f"fragment tool {analysis.get('tool_name')} does not match step tool {step_tool}"
        )
    args = analysis.get("args") if isinstance(analysis.get("args"), dict) else {}
    if canonical_json(args) != canonical_json(step_args):
        raise FragmentSandboxError("fragment args do not match planned step args")


def _validate_fragment_postconditions_match_step(
    fragment_postconditions: Any, step_postconditions: Any
) -> None:
    fragment_checks = list(fragment_postconditions or [])
    step_checks = list(step_postconditions or [])
    if canonical_json(fragment_checks) != canonical_json(step_checks):
        raise FragmentSandboxError(
            "fragment postconditions do not match planned step postconditions"
        )


def execute_fragment_pre_helpers(
    *,
    plan_store: LivePlanStore,
    binding: dict[str, Any],
) -> list[dict[str, Any]]:
    """Interpret safe helper calls that must run before the mutating call."""

    trace: list[dict[str, Any]] = []
    context: dict[str, Any] | None = None
    for call in _binding_calls(binding):
        if call.get("kind") == "mutation":
            return trace
        if call.get("kind") != "helper":
            continue
        name = str(call.get("name") or "")
        if name == "read_context":
            context = _fragment_context_for_binding(plan_store=plan_store, binding=binding)
            trace.append(
                {
                    "name": "read_context",
                    "status": "PASS",
                    "context_hash": binding.get("context_hash"),
                    "summary": _context_summary(context),
                }
            )
        elif name == "assert_precondition":
            context = context or _fragment_context_for_binding(
                plan_store=plan_store, binding=binding
            )
            condition = _call_condition(call)
            _assert_fragment_precondition(condition, context)
            trace.append(
                {
                    "name": "assert_precondition",
                    "status": "PASS",
                    "condition": condition,
                }
            )
        elif name == "assert_postcondition":
            raise FragmentSandboxError(
                "fragment postconditions must appear after the mutating call"
            )
    return trace


def execute_fragment_post_helpers(
    *,
    plan_store: LivePlanStore,
    binding: dict[str, Any],
) -> list[dict[str, Any]]:
    """Interpret safe helper calls that appear after the mutating call."""

    del plan_store
    trace: list[dict[str, Any]] = []
    mutation_seen = False
    for call in _binding_calls(binding):
        if call.get("kind") == "mutation":
            mutation_seen = True
            continue
        if not mutation_seen or call.get("kind") != "helper":
            continue
        name = str(call.get("name") or "")
        if name == "assert_precondition":
            raise FragmentSandboxError(
                "fragment preconditions must appear before the mutating call"
            )
        if name == "assert_postcondition":
            trace.append(
                {
                    "name": "assert_postcondition",
                    "status": "DEFERRED_TO_VERIFIER",
                    "condition": _call_condition(call),
                }
            )
        elif name == "read_context":
            trace.append(
                {
                    "name": "read_context",
                    "status": "PASS",
                    "context_hash": binding.get("context_hash"),
                    "summary": "submitted turn context",
                }
            )
    return trace


def _binding_calls(binding: dict[str, Any]) -> list[dict[str, Any]]:
    calls = binding.get("calls") if isinstance(binding.get("calls"), list) else []
    return [dict(call) for call in calls if isinstance(call, dict)]


def _call_condition(call: dict[str, Any]) -> dict[str, Any]:
    condition = call.get("condition")
    if not isinstance(condition, dict):
        raise FragmentSandboxError("fragment assertion is missing a condition payload")
    return dict(condition)


def _fragment_context_for_binding(
    *, plan_store: LivePlanStore, binding: dict[str, Any]
) -> dict[str, Any]:
    plan = plan_store.get_plan(str(binding.get("plan_id") or ""))
    state = plan_store.replay()
    row = state.contexts.get((plan.turn, plan.branch_id))
    if row is None:
        raise FragmentSandboxError("fragment turn context is not recorded")
    if row.get("context_hash") != binding.get("context_hash"):
        raise FragmentSandboxError("fragment turn context hash does not match binding")
    context = row.get("context") if isinstance(row.get("context"), dict) else row
    if not isinstance(context, dict):
        raise FragmentSandboxError("fragment turn context payload is invalid")
    payload = dict(context)
    payload.setdefault("context_hash", row.get("context_hash"))
    return payload


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    cities = context.get("cities") if isinstance(context.get("cities"), list) else []
    units = context.get("units") if isinstance(context.get("units"), list) else []
    return {
        "city_count": len(cities),
        "unit_count": len(units),
        "turn": (context.get("overview") or {}).get("turn")
        if isinstance(context.get("overview"), dict)
        else None,
    }


def _assert_fragment_precondition(
    condition: dict[str, Any], context: dict[str, Any]
) -> None:
    condition_type = str(condition.get("type") or "")
    if condition_type == "unit_exists":
        if _find_context_row(context.get("units"), condition.get("unit_id")) is None:
            raise FragmentSandboxError(
                f"fragment precondition failed: unit_exists {condition.get('unit_id')}"
            )
        return
    if condition_type == "city_exists":
        if _find_context_row(context.get("cities"), condition.get("city_id")) is None:
            raise FragmentSandboxError(
                f"fragment precondition failed: city_exists {condition.get('city_id')}"
            )
        return
    raise FragmentSandboxError(
        f"unsupported fragment precondition type: {condition_type}"
    )


def _find_context_row(rows: Any, value: Any) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifiers = (
            row.get("unit_id"),
            row.get("unit_index"),
            row.get("id"),
            row.get("city_id"),
            row.get("index"),
        )
        if any(str(identifier) == str(value) for identifier in identifiers if identifier is not None):
            return row
    return None


def _worker_main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        source = payload.get("source")
        if not isinstance(source, str):
            raise FragmentSandboxError("worker payload source must be a string")
        analysis = _analyze_fragment_source_in_process(source)
        print(json.dumps({"ok": True, "analysis": analysis}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - worker returns structured rejection.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Live fragment sandbox worker.")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args(argv)
    if args.worker:
        raise SystemExit(_worker_main())
    parser.error("--worker is required")


if __name__ == "__main__":
    main()

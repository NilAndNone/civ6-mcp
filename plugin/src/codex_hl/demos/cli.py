"""CLI for recording human-play Civ6 demonstrations to SQLite."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from codex_hl.demos.recorder import (
    HumanDemoError,
    SqliteDemoRecorder,
    apply_snapshot_quality_to_rule,
    build_rule_inference,
    build_state_delta,
    default_db_path,
    extract_action_facts,
    fact_counts_by_category,
    make_demo_id,
    write_report,
)
from codex_hl.evidence.observation import (
    DEFAULT_SAVE_NAME,
    WORKFLOW_LABEL,
    RecordingConnection,
    capture_state,
    required_tool_with_retries,
    t50_strategy_audit,
    to_jsonable,
)
from civ6_connector.connection import GameConnection
from civ6_connector.game_state import GameState


COMMANDS = {
    "start",
    "advance",
    "record-inference",
    "correct",
    "note",
    "finish",
    "report-only",
    "self-play",
    "watch",
}

def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 4) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


HUMAN_DEMO_KEY_READ_CONCURRENCY = 1
HUMAN_DEMO_READ_CONCURRENCY = _env_int("CODEX_HL_HUMAN_DEMO_READ_CONCURRENCY", 2)
HUMAN_DEMO_FULL_READ_INTERVAL = _env_int(
    "CODEX_HL_HUMAN_DEMO_FULL_READ_INTERVAL", 5, minimum=1, maximum=50
)


def parse_tags(text: str) -> list[str]:
    return [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]


def prompt_required(input_fn: Callable[[str], str], prompt: str, *, required: bool) -> str:
    while True:
        value = input_fn(prompt).strip()
        if value or not required:
            return value
        print("该字段不能为空；请输入一句简短说明。")


def _add_common_demo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save-name", default=DEFAULT_SAVE_NAME)
    parser.add_argument("--demo-id")
    parser.add_argument("--db", type=Path)


def _add_action_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--action-id")
    parser.add_argument("--turn", type=int)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record human-play Civ6 turns into a separate SQLite database."
    )
    sub = parser.add_subparsers(dest="command")

    start = sub.add_parser("start", help="Create/resume a demo and capture the first before snapshot.")
    _add_common_demo_args(start)
    start.add_argument("--turns", type=int, default=20)

    advance = sub.add_parser("advance", help="Capture after, compute delta, and create a pending inferred action.")
    _add_common_demo_args(advance)

    infer = sub.add_parser("record-inference", help="Write Codex-generated inference for an action.")
    _add_common_demo_args(infer)
    _add_action_target_args(infer)
    infer.add_argument("--summary", required=True)
    infer.add_argument("--rationale", default="")
    infer.add_argument("--confidence", choices=["high", "medium", "low"], default="medium")
    infer.add_argument("--needs-review", action=argparse.BooleanOptionalAction, default=None)
    infer.add_argument("--evidence-json", default="[]")
    infer.add_argument("--input-json", default="{}")

    correct = sub.add_parser("correct", help="Apply a human correction to the latest or selected action.")
    _add_common_demo_args(correct)
    _add_action_target_args(correct)
    correct.add_argument("--text", required=True)
    correct.add_argument("--allow-completed", action="store_true")

    note = sub.add_parser("note", help="Append a manual demo note.")
    _add_common_demo_args(note)
    note.add_argument("--turn", type=int)
    note.add_argument("--note", required=True)

    finish = sub.add_parser("finish", help="Complete the demo session and generate the report.")
    _add_common_demo_args(finish)
    finish.add_argument("--status", default="completed")

    report = sub.add_parser("report-only", help="Regenerate the HTML report from SQLite.")
    _add_common_demo_args(report)

    self_play = sub.add_parser(
        "self-play",
        help="Let Codex operate the current Civ6 session and record the turns.",
    )
    _add_common_demo_args(self_play)
    self_play.add_argument("--turns", type=int, default=5)

    watch = sub.add_parser(
        "watch",
        help="Watch for human end-turn transitions and auto-record each completed turn.",
    )
    _add_common_demo_args(watch)
    watch.add_argument("--poll-seconds", type=float, default=3.0)
    watch.add_argument("--stable-seconds", type=float, default=4.0)
    watch.add_argument(
        "--max-turns",
        type=int,
        default=0,
        help="Maximum turns to auto-record; 0 means run until interrupted.",
    )
    watch.add_argument(
        "--pause-on-skip",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pause if the observed turn jumps by more than one.",
    )
    watch.add_argument(
        "--stop-on-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop after a recorded action that needs review.",
    )
    watch.add_argument(
        "--stop-on-periodic-question",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop when the recorder reaches a periodic strategy question.",
    )

    return parser


def _build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record human-play Civ6 turns into a separate SQLite database."
    )
    parser.add_argument("--save-name", default=DEFAULT_SAVE_NAME)
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--demo-id")
    parser.add_argument("--db", type=Path)
    parser.add_argument(
        "--reuse-running-game",
        action="store_true",
        default=True,
        help="Attach to the current Civ6 session. This is the only v1 runtime mode.",
    )
    parser.add_argument(
        "--note-required",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require a non-empty summary and rationale for each recorded turn.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Regenerate the HTML report from an existing SQLite database.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(argv) if argv is not None else sys.argv[1:]
    first = raw[0] if raw else None
    if first in COMMANDS or first in {"-h", "--help"}:
        args = _build_parser().parse_args(raw)
    else:
        args = _build_legacy_parser().parse_args(raw)
        args.command = "legacy-report-only" if args.report_only else "legacy-interactive"

    if getattr(args, "turns", 1) < 1:
        raise SystemExit("--turns must be >= 1")
    if getattr(args, "max_turns", 0) < 0:
        raise SystemExit("--max-turns must be >= 0")
    if getattr(args, "poll_seconds", 1.0) <= 0:
        raise SystemExit("--poll-seconds must be > 0")
    if getattr(args, "stable_seconds", 0.0) < 0:
        raise SystemExit("--stable-seconds must be >= 0")
    if args.command in {"legacy-report-only", "report-only"} and not args.db and not args.demo_id:
        raise SystemExit("report-only requires --db or --demo-id")
    if (
        args.command != "start"
        and args.command not in {"legacy-interactive", "self-play"}
        and not args.db
        and not args.demo_id
    ):
        raise SystemExit(f"{args.command} requires --db or --demo-id")
    return args


def resolve_demo_paths(args: argparse.Namespace) -> tuple[str, Path]:
    db_path_arg = args.db.resolve() if args.db else None
    demo_id = args.demo_id
    if not demo_id and db_path_arg and getattr(args, "command", None) != "start":
        demo_id = infer_demo_id_from_db(db_path_arg)
    demo_id = demo_id or make_demo_id()
    db_path = db_path_arg if db_path_arg else default_db_path(demo_id).resolve()
    return demo_id, db_path


def infer_demo_id_from_db(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT demo_id
            FROM demo_sessions
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error as exc:
        raise HumanDemoError(f"Could not read demo id from SQLite database: {db_path}: {exc}") from exc
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    return str(row[0])


def _load_json_arg(text: str, *, name: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HumanDemoError(f"{name} must be valid JSON: {exc}") from exc


def choose_pending_action(
    recorder: SqliteDemoRecorder, input_fn: Callable[[str], str]
) -> tuple[str | None, dict | None]:
    pending = recorder.pending_before_snapshots()
    if not pending:
        return None, None

    latest = pending[0]
    snapshot_id = str(latest["snapshot_id"])
    turn = int(latest["turn"])
    choice = input_fn(
        f"发现未完成的 before 快照 {snapshot_id} (T{turn})。输入 c 继续补 after，输入 d 放弃："
    ).strip().lower()
    if choice == "c":
        return snapshot_id, recorder.load_snapshot(snapshot_id)
    recorder.record_manual_note(
        turn=turn,
        note=f"abandoned pending before snapshot {snapshot_id}",
    )
    return None, None


async def _capture_snapshot(
    recorder: SqliteDemoRecorder, label: str
) -> tuple[int, str, dict]:
    return await _capture_snapshot_parallel(recorder, label)


def _object_field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


async def _capture_overview(
    recorder: SqliteDemoRecorder,
) -> tuple[str, Any]:
    conn = RecordingConnection(recorder)
    gs = GameState(conn)
    try:
        return await required_tool_with_retries(
            recorder,
            "get_game_overview",
            {},
            gs.get_game_overview,
            attempts=5,
            delay_seconds=3.0,
        )
    finally:
        await conn.disconnect()


async def _parallel_snapshot_tool(
    recorder: SqliteDemoRecorder,
    *,
    turn: int,
    name: str,
    snapshot_key: str,
    field: str,
    params: dict[str, Any],
    fn: Callable[[GameState], Awaitable[Any]],
) -> tuple[str | None, str, Any | None, dict[str, str] | None]:
    conn = RecordingConnection(recorder)
    gs = GameState(conn)
    try:
        call_id, value = await recorder.tool_call(
            name, params, lambda: fn(gs), turn=turn
        )
        return call_id, snapshot_key, value, None
    except Exception as exc:  # noqa: BLE001 - snapshot should preserve gaps.
        gap = {
            "field": field,
            "reason": f"{type(exc).__name__}: {exc}",
            "next_step": f"Repair or add a read-only MCP query for {field}.",
        }
        recorder.add_gap(gap["field"], gap["reason"], gap["next_step"])
        return None, snapshot_key, None, gap
    finally:
        await conn.disconnect()


SnapshotRead = tuple[
    str,
    str,
    str,
    dict[str, Any],
    Callable[[GameState], Awaitable[Any]],
]


def _overview_count(overview: Any, key: str) -> int:
    try:
        return int(_object_field(overview, key) or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_cities_value(value: Any) -> tuple[Any, Any]:
    if isinstance(value, tuple):
        return value[0], value[1]
    if value:
        return value, []
    return [], []


def _city_count(value: Any) -> int:
    cities, _ = _normalize_cities_value(value)
    return len(cities or [])


def _critical_retry_reads(overview: Any, captured: dict[str, Any]) -> list[SnapshotRead]:
    retries: list[SnapshotRead] = []
    if _city_count(captured.get("cities_value")) < _overview_count(overview, "num_cities"):
        retries.append(("get_cities", "cities_value", "cities", {"retry": "critical"}, lambda gs: gs.get_cities()))
    if _overview_count(overview, "num_units") > 0 and captured.get("units") is None:
        retries.append(("get_units", "units", "units", {"retry": "critical"}, lambda gs: gs.get_units()))
    if captured.get("research_civic") is None:
        retries.append(("get_tech_civics", "research_civic", "research_civic", {"retry": "critical"}, lambda gs: gs.get_tech_civics()))
    if captured.get("historic_moments") is None:
        retries.append(("get_historic_moments", "historic_moments", "historic_moments", {"retry": "critical"}, lambda gs: gs.get_historic_moments()))
    return retries


def _full_snapshot_due(turn: int) -> bool:
    return turn <= 1 or HUMAN_DEMO_FULL_READ_INTERVAL <= 1 or turn % HUMAN_DEMO_FULL_READ_INTERVAL == 0


async def _run_snapshot_reads(
    recorder: SqliteDemoRecorder,
    *,
    turn: int,
    reads: list[SnapshotRead],
    concurrency: int,
    captured: dict[str, Any],
    related: list[str],
    gaps: list[dict[str, str]],
    overwrite: bool = True,
) -> None:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_read(read: SnapshotRead) -> tuple[str | None, str, Any | None, dict[str, str] | None]:
        name, snapshot_key, field, params, fn = read
        async with semaphore:
            return await _parallel_snapshot_tool(
                recorder,
                turn=turn,
                name=name,
                snapshot_key=snapshot_key,
                field=field,
                params=params,
                fn=fn,
            )

    for call_id, snapshot_key, value, gap in await asyncio.gather(
        *(run_read(read) for read in reads)
    ):
        if call_id:
            related.append(call_id)
        if gap:
            gaps.append(gap)
        if overwrite or captured.get(snapshot_key) is None:
            captured[snapshot_key] = value


async def _capture_snapshot_parallel(
    recorder: SqliteDemoRecorder, label: str
) -> tuple[int, str, dict[str, Any]]:
    start_seq = recorder.tool_seq
    start = time.perf_counter()
    gaps: list[dict[str, str]] = []
    related: list[str] = []

    overview_call_id, overview = await _capture_overview(recorder)
    related.append(overview_call_id)
    turn = int(getattr(overview, "turn", 0))
    if recorder.start_turn is None:
        recorder.start_turn = turn

    key_reads: list[SnapshotRead] = [
        ("get_cities", "cities_value", "cities", {}, lambda gs: gs.get_cities()),
        ("get_units", "units", "units", {}, lambda gs: gs.get_units()),
        ("get_tech_civics", "research_civic", "research_civic", {}, lambda gs: gs.get_tech_civics()),
        ("get_historic_moments", "historic_moments", "historic_moments", {}, lambda gs: gs.get_historic_moments()),
        ("get_policies", "policies", "civic.policies", {}, lambda gs: gs.get_policies()),
    ]
    turn_reads: list[SnapshotRead] = [
        ("get_notifications", "notifications", "notifications", {}, lambda gs: gs.get_notifications()),
        ("get_threat_scan", "threats", "threats", {}, lambda gs: gs.get_threat_scan()),
        ("get_pantheon_beliefs", "pantheon_status", "religion.pantheon", {}, lambda gs: gs.get_pantheon_status()),
    ]
    full_reads: list[SnapshotRead] = [
        ("get_game_identity", "identity", "empire.identity", {}, lambda gs: gs.get_game_identity()),
        ("get_diary_snapshot", "empire", "empire.diary_snapshot", {}, lambda gs: gs.get_diary_snapshot()),
        ("get_governors", "governors", "governors", {}, lambda gs: gs.get_governors()),
        ("get_empire_resources", "resources", "empire.resources", {}, lambda gs: gs.get_empire_resources()),
        ("get_diplomacy", "diplomacy", "diplomacy", {}, lambda gs: gs.get_diplomacy()),
        ("get_victory_progress", "victory", "victory", {}, lambda gs: gs.get_victory_progress()),
        ("get_trade_routes", "trade_routes", "trade_routes", {}, lambda gs: gs.get_trade_routes()),
        ("get_strategic_map", "strategic_map", "exploration.strategic_map", {}, lambda gs: gs.get_strategic_map()),
        ("get_religion_beliefs", "religion_founding_status", "religion.founding", {}, lambda gs: gs.get_religion_founding_status()),
        ("get_great_people", "great_people", "great_people", {}, lambda gs: gs.get_great_people()),
    ]
    full_due = _full_snapshot_due(turn)
    skipped_reads = [] if full_due else [field for _, _, field, _, _ in full_reads]
    captured: dict[str, Any] = {}
    await _run_snapshot_reads(
        recorder,
        turn=turn,
        reads=key_reads,
        concurrency=HUMAN_DEMO_KEY_READ_CONCURRENCY,
        captured=captured,
        related=related,
        gaps=gaps,
    )
    await _run_snapshot_reads(
        recorder,
        turn=turn,
        reads=turn_reads,
        concurrency=HUMAN_DEMO_READ_CONCURRENCY,
        captured=captured,
        related=related,
        gaps=gaps,
    )
    if full_due:
        await _run_snapshot_reads(
            recorder,
            turn=turn,
            reads=full_reads,
            concurrency=HUMAN_DEMO_READ_CONCURRENCY,
            captured=captured,
            related=related,
            gaps=gaps,
        )
    retries = _critical_retry_reads(overview, captured)
    if retries:
        await _run_snapshot_reads(
            recorder,
            turn=turn,
            reads=retries,
            concurrency=1,
            captured=captured,
            related=related,
            gaps=gaps,
        )

    cities, city_distances = _normalize_cities_value(captured.get("cities_value"))

    production_by_city: dict[str, Any] = {}
    production_reads: list[SnapshotRead] = []
    for city in cities or []:
        city_id = _object_field(city, "city_id")
        if city_id is None:
            continue
        production_reads.append(
            (
                "get_city_production",
                str(city_id),
                f"production.city_{city_id}",
                {"city_id": city_id},
                lambda gs, city_id=city_id: gs.list_city_production(city_id),
            )
        )

    production_captured: dict[str, Any] = {}
    await _run_snapshot_reads(
        recorder,
        turn=turn,
        reads=production_reads,
        concurrency=1,
        captured=production_captured,
        related=related,
        gaps=gaps,
    )
    production_by_city = {
        city_id: value for city_id, value in production_captured.items()
    }

    snapshot = {
        "workflow": WORKFLOW_LABEL,
        "capture_mode": "tiered_read",
        "capture_policy": {
            "key_read_concurrency": HUMAN_DEMO_KEY_READ_CONCURRENCY,
            "read_concurrency": HUMAN_DEMO_READ_CONCURRENCY,
            "full_read_interval": HUMAN_DEMO_FULL_READ_INTERVAL,
            "full_reads_due": full_due,
            "skipped_reads": skipped_reads,
        },
        "turn": turn,
        "overview": overview,
        "identity": captured.get("identity"),
        "empire": captured.get("empire"),
        "cities": cities,
        "city_distances": city_distances,
        "units": captured.get("units"),
        "notifications": captured.get("notifications"),
        "historic_moments": captured.get("historic_moments"),
        "threats": captured.get("threats"),
        "research_civic": captured.get("research_civic"),
        "policies": captured.get("policies"),
        "governors": captured.get("governors"),
        "production": production_by_city,
        "resources": captured.get("resources"),
        "diplomacy": captured.get("diplomacy"),
        "victory": captured.get("victory"),
        "trade_routes": captured.get("trade_routes"),
        "strategic_map": captured.get("strategic_map"),
        "pantheon_status": captured.get("pantheon_status"),
        "religion_founding_status": captured.get("religion_founding_status"),
        "great_people": captured.get("great_people"),
        "known_gaps": gaps,
    }
    snapshot["t50_strategy_audit"] = t50_strategy_audit(snapshot)
    snapshot["capture_timing"] = recorder.tool_timing_summary(
        start_seq=start_seq,
        wall_ms=int((time.perf_counter() - start) * 1000),
    )

    for key in [
        "cities",
        "units",
        "research_civic",
        "policies",
        "historic_moments",
        "production",
    ]:
        if snapshot.get(key) is None:
            gap = {
                "field": key,
                "reason": "Current parallel read returned no data for this snapshot field.",
                "next_step": "Repair the corresponding Civ6 MCP query before using this demo as evidence.",
            }
            snapshot["known_gaps"].append(gap)
            recorder.add_gap(gap["field"], gap["reason"], gap["next_step"])

    snapshot_id = recorder.record_state(turn, label, snapshot, related)
    return turn, snapshot_id, snapshot


async def run_start(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        recorder.record_manual_note(
            turn=None,
            note=(
                "codex_conversation_driver:start; "
                f"requested_turns={getattr(args, 'turns', None)}; "
                "interaction=Codex says start/好了/结束录制"
            ),
        )
        turn, before_id, snapshot = await _capture_snapshot(recorder, "turn_001_before")
        return {
            "command": "start",
            "demo_id": demo_id,
            "db_path": str(db_path),
            "turn": turn,
            "before_snapshot_id": before_id,
            "next_phrase": "好了",
            "overview": snapshot.get("overview"),
            "capture_timing": snapshot.get("capture_timing"),
        }
    finally:
        recorder.close()


async def run_advance(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        pending = recorder.pending_before_snapshots()
        if not pending:
            raise HumanDemoError("No pending before snapshot found. Say/start with the start command first.")
        before_row = pending[0]
        before_id = str(before_row["snapshot_id"])
        before_turn = int(before_row["turn"])
        before_snapshot = recorder.load_snapshot(before_id)
        index = recorder.action_seq + 1
        after_turn, after_id, after_snapshot = await _capture_snapshot(
            recorder, f"turn_{index:03d}_after"
        )
        if after_turn <= before_turn:
            recorder.record_manual_note(
                turn=before_turn,
                note=(
                    f"after snapshot turn {after_turn} did not advance beyond "
                    f"before turn {before_turn}; Codex should ask for retry or review."
                ),
            )
        delta = build_state_delta(before_snapshot, after_snapshot)
        facts = extract_action_facts(before_snapshot, after_snapshot, delta)
        rule = apply_snapshot_quality_to_rule(
            build_rule_inference(delta, facts=facts),
            before_snapshot,
            after_snapshot,
        )
        action_id = recorder.record_human_turn(
            turn=before_turn,
            before_snapshot_id=before_id,
            after_snapshot_id=after_id,
            summary=str(rule["summary"]),
            rationale=str(rule["rationale"]),
            tags=[],
            delta=delta,
            inferred_summary=str(rule["summary"]),
            inferred_rationale=str(rule["rationale"]),
            confidence=str(rule["confidence"]),
            needs_review=bool(rule["needs_review"]),
            evidence=list(rule["evidence"]),
            facts=facts,
            status="pending_codex_inference",
        )
        recorder.record_inference_audit(
            action_id=action_id,
            turn=before_turn,
            event="rule_facts",
            input_payload={"delta": delta},
            output_payload=rule,
        )
        next_before_id = recorder.clone_state_snapshot(
            after_id, f"turn_{index + 1:03d}_before"
        )
        return {
            "command": "advance",
            "demo_id": demo_id,
            "db_path": str(db_path),
            "turn": before_turn,
            "after_turn": after_turn,
            "action_id": action_id,
            "before_snapshot_id": before_id,
            "after_snapshot_id": after_id,
            "next_before_turn": after_turn,
            "next_before_snapshot_id": next_before_id,
            "delta": delta,
            "facts": facts,
            "fact_counts_by_category": fact_counts_by_category(facts),
            "rule_inference": rule,
            "capture_timing": after_snapshot.get("capture_timing"),
            "before_capture_timing": before_snapshot.get("capture_timing"),
            "periodic_question_due": before_turn > 0 and before_turn % 10 == 0,
            "periodic_question": (
                "接下来 10 回合你的重点是什么？"
                if before_turn > 0 and before_turn % 10 == 0
                else None
            ),
        }
    finally:
        recorder.close()


def run_record_inference(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path = resolve_demo_paths(args)
    evidence = _load_json_arg(args.evidence_json, name="--evidence-json")
    input_payload = _load_json_arg(args.input_json, name="--input-json")
    if not isinstance(evidence, list):
        raise HumanDemoError("--evidence-json must decode to a JSON list")
    if not isinstance(input_payload, dict):
        raise HumanDemoError("--input-json must decode to a JSON object")
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        action_id = recorder.record_codex_inference(
            action_id=args.action_id,
            turn=args.turn,
            summary=args.summary,
            rationale=args.rationale,
            confidence=args.confidence,
            needs_review=args.needs_review,
            evidence=evidence,
            input_payload=input_payload,
        )
        return {
            "command": "record-inference",
            "demo_id": demo_id,
            "db_path": str(db_path),
            "action_id": action_id,
        }
    finally:
        recorder.close()


def run_correct(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        action_id = recorder.correct_action(
            text=args.text,
            action_id=args.action_id,
            turn=args.turn,
            allow_completed=args.allow_completed,
        )
        return {
            "command": "correct",
            "demo_id": demo_id,
            "db_path": str(db_path),
            "action_id": action_id,
        }
    finally:
        recorder.close()


def run_note(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        note_id = recorder.record_manual_note(turn=args.turn, note=args.note)
        return {
            "command": "note",
            "demo_id": demo_id,
            "db_path": str(db_path),
            "note_id": note_id,
        }
    finally:
        recorder.close()


def run_finish(args: argparse.Namespace) -> dict[str, str]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        recorder.complete_session(args.status)
    finally:
        recorder.close()
    report_path = write_report(db_path)
    return {
        "command": "finish",
        "demo_id": demo_id,
        "db_path": str(db_path),
        "report_path": str(report_path),
    }


SELF_PLAY_TECH_PRIORITY = [
    "TECH_ASTROLOGY",
    "TECH_MINING",
    "TECH_POTTERY",
    "TECH_ANIMAL_HUSBANDRY",
]
SELF_PLAY_PRODUCTION_PRIORITY = [
    "UNIT_SLINGER",
    "UNIT_SCOUT",
    "UNIT_BUILDER",
    "BUILDING_MONUMENT",
    "UNIT_WARRIOR",
]
IDLE_PRODUCTION = {None, "", "NONE", "nothing", "CORRUPTED_QUEUE"}


def _json_dict(value: Any) -> dict[str, Any]:
    value = to_jsonable(value)
    return value if isinstance(value, dict) else {}


def _json_list(value: Any) -> list[Any]:
    value = to_jsonable(value)
    return value if isinstance(value, list) else []


def _meaningful_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "none", "null", "no research"} else text


def _pick_option(
    options: list[Any], *, type_key: str, priorities: list[str]
) -> dict[str, Any] | None:
    rows = [_json_dict(option) for option in options]
    rows = [row for row in rows if row]
    for wanted in priorities:
        for row in rows:
            if wanted in {row.get(type_key), row.get("item_name"), row.get("name")}:
                return row
    if not rows:
        return None
    return sorted(rows, key=lambda row: int(row.get("turns") or row.get("cost") or 9999))[0]


def _city_current_production(city: dict[str, Any]) -> str:
    return str(city.get("currently_building") or city.get("current_production") or "")


async def _set_idle_city_production_live(
    gs: GameState, actions: list[dict[str, Any]], *, reason: str
) -> None:
    try:
        cities_value = await gs.get_cities()
    except Exception as exc:  # noqa: BLE001 - self-play should record the gap.
        actions.append(
            {
                "kind": "live_city_read_failed",
                "result": f"{type(exc).__name__}: {exc}",
                "rationale": reason,
            }
        )
        return
    cities, _ = _normalize_cities_value(cities_value)
    for city in [_json_dict(city) for city in cities or []]:
        city_id = city.get("city_id") or city.get("id")
        if city_id is None:
            continue
        current = _city_current_production(city)
        if current not in IDLE_PRODUCTION:
            continue
        try:
            options = await gs.list_city_production(int(city_id))
            selected = _pick_option(
                options,
                type_key="item_name",
                priorities=SELF_PLAY_PRODUCTION_PRIORITY,
            )
            if not selected:
                actions.append(
                    {
                        "kind": "live_city_production_missing_options",
                        "city_id": city_id,
                        "city_name": city.get("name"),
                        "rationale": reason,
                    }
                )
                continue
            item_name = str(selected.get("item_name"))
            category = str(selected.get("category") or "UNIT")
            result = await gs.set_city_production(int(city_id), category, item_name)
            actions.append(
                {
                    "kind": "set_city_production",
                    "city_id": city_id,
                    "city_name": city.get("name"),
                    "selection": item_name,
                    "category": category,
                    "result": result,
                    "rationale": reason,
                }
            )
        except Exception as exc:  # noqa: BLE001 - record self-play action gap.
            actions.append(
                {
                    "kind": "live_city_production_failed",
                    "city_id": city_id,
                    "city_name": city.get("name"),
                    "result": f"{type(exc).__name__}: {exc}",
                    "rationale": reason,
                }
            )


async def _codex_self_play_actions(
    gs: GameState, snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    overview = _json_dict(snapshot.get("overview"))
    research_civic = _json_dict(snapshot.get("research_civic"))

    if not _meaningful_text(research_civic.get("current_research") or overview.get("current_research")):
        selected = _pick_option(
            _json_list(research_civic.get("available_techs")),
            type_key="tech_type",
            priorities=SELF_PLAY_TECH_PRIORITY,
        )
        if selected:
            tech = str(selected.get("tech_type") or selected.get("name"))
            result = await gs.set_research(tech)
            actions.append(
                {
                    "kind": "set_research",
                    "selection": tech,
                    "result": result,
                    "rationale": "ensure the self-play validation turn has an active science path",
                }
            )

    if not _meaningful_text(research_civic.get("current_civic") or overview.get("current_civic")):
        selected = _pick_option(
            _json_list(research_civic.get("available_civics")),
            type_key="civic_type",
            priorities=["CIVIC_CODE_OF_LAWS"],
        )
        if selected:
            civic = str(selected.get("civic_type") or selected.get("name"))
            result = await gs.set_civic(civic)
            actions.append(
                {
                    "kind": "set_civic",
                    "selection": civic,
                    "result": result,
                    "rationale": "ensure the self-play validation turn has an active civic path",
                }
            )

    production = _json_dict(snapshot.get("production"))
    for city in [_json_dict(city) for city in _json_list(snapshot.get("cities"))]:
        city_id = city.get("city_id") or city.get("id")
        if city_id is None:
            continue
        current = _city_current_production(city)
        if current not in IDLE_PRODUCTION:
            actions.append(
                {
                    "kind": "continue_production",
                    "city_id": city_id,
                    "city_name": city.get("name"),
                    "selection": current,
                    "turns_left": city.get("production_turns_left"),
                    "rationale": "keep existing city production for validation continuity",
                }
            )
            continue
        selected = _pick_option(
            _json_list(production.get(str(city_id))),
            type_key="item_name",
            priorities=SELF_PLAY_PRODUCTION_PRIORITY,
        )
        if selected:
            item_name = str(selected.get("item_name"))
            category = str(selected.get("category") or "UNIT")
            result = await gs.set_city_production(int(city_id), category, item_name)
            actions.append(
                {
                    "kind": "set_city_production",
                    "city_id": city_id,
                    "city_name": city.get("name"),
                    "selection": item_name,
                    "category": category,
                    "result": result,
                    "rationale": "fill missing production before ending turn",
                }
            )

    units = [_json_dict(unit) for unit in _json_list(snapshot.get("units"))]
    cities = _json_list(snapshot.get("cities"))
    for unit in units:
        unit_type = str(unit.get("unit_type") or unit.get("name") or "")
        unit_id = unit.get("unit_id") or unit.get("id")
        if unit_id is None:
            continue
        unit_index = int(unit_id) % 65536
        if "SETTLER" in unit_type.upper() or "开拓者" in unit_type:
            if not cities:
                result = await gs.found_city(unit_index)
                actions.append(
                    {
                        "kind": "found_city",
                        "unit_id": unit_id,
                        "unit_type": unit_type,
                        "result": result,
                        "rationale": "open the validation run by founding the capital",
                    }
            )
            continue
        if float(unit.get("moves_remaining") or 0) > 0:
            result = await gs.automate_explore(unit_index)
            actions.append(
                {
                    "kind": "automate_explore",
                    "unit_id": unit_id,
                    "unit_type": unit_type,
                    "result": result,
                    "rationale": "let the available unit reveal nearby map during validation",
                }
            )
            break

    await _set_idle_city_production_live(
        gs,
        actions,
        reason="set production for any city created or left idle before ending turn",
    )

    skip_result = await gs.skip_remaining_units()
    actions.append(
        {
            "kind": "skip_remaining_units",
            "result": skip_result,
            "rationale": "clear remaining unit prompts before ending turn",
        }
    )
    end_result = await gs.end_turn()
    actions.append(
        {
            "kind": "end_turn",
            "result": end_result,
            "rationale": "advance the self-play validation loop by one turn",
        }
    )
    if "Action Required" in str(end_result):
        await _set_idle_city_production_live(
            gs,
            actions,
            reason="repair action-required production prompt after turn advance",
        )
    if str(end_result).lower().startswith("error"):
        await _set_idle_city_production_live(
            gs,
            actions,
            reason="repair action-required production prompt before one end-turn retry",
        )
        retry_skip = await gs.skip_remaining_units()
        retry_end = await gs.end_turn()
        actions.extend(
            [
                {
                    "kind": "retry_skip_remaining_units",
                    "result": retry_skip,
                    "rationale": "retry after end-turn blocker",
                },
                {
                    "kind": "retry_end_turn",
                    "result": retry_end,
                    "rationale": "retry end turn once after clearing blockers",
                },
            ]
        )
    return actions


def _actions_summary(actions: list[dict[str, Any]]) -> str:
    bits = []
    for action in actions:
        selected = action.get("selection")
        city = action.get("city_name") or action.get("city_id")
        if selected and city:
            bits.append(f"{action['kind']} {city}: {selected}")
        elif selected:
            bits.append(f"{action['kind']} {selected}")
        else:
            bits.append(str(action.get("kind")))
    return "；".join(bits)


async def run_self_play(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    write_conn = GameConnection()
    write_gs = GameState(write_conn)
    action_payloads: list[dict[str, Any]] = []
    try:
        recorder.record_manual_note(
            turn=None,
            note=(
                "actor=codex_self_play_validation; "
                f"requested_turns={args.turns}; recorder=read_only; "
                "writes=separate GameConnection"
            ),
        )
        for index in range(args.turns):
            before_turn, before_id, before_snapshot = await _capture_snapshot(
                recorder, f"turn_{index + 1:03d}_before"
            )
            actions = await _codex_self_play_actions(write_gs, before_snapshot)
            recorder.record_manual_note(
                turn=before_turn,
                note=f"codex_self_play_actions:{json.dumps(actions, ensure_ascii=False, default=str)}",
            )
            await write_conn.disconnect()
            await asyncio.sleep(0.8)
            after_turn, after_id, after_snapshot = await _capture_snapshot(
                recorder, f"turn_{index + 1:03d}_after"
            )
            if after_turn <= before_turn:
                recorder.record_manual_note(
                    turn=before_turn,
                    note=(
                        f"self-play after snapshot turn {after_turn} did not advance "
                        f"beyond before turn {before_turn}"
                    ),
                )
            delta = build_state_delta(before_snapshot, after_snapshot)
            facts = extract_action_facts(before_snapshot, after_snapshot, delta)
            rule = apply_snapshot_quality_to_rule(
                build_rule_inference(delta, facts=facts),
                before_snapshot,
                after_snapshot,
            )
            action_id = recorder.record_human_turn(
                turn=before_turn,
                before_snapshot_id=before_id,
                after_snapshot_id=after_id,
                summary=str(rule["summary"]),
                rationale=(
                    f"Codex self-play actions: {_actions_summary(actions)}. "
                    f"{rule['rationale']}"
                ),
                tags=["codex_self_play_validation"],
                delta=delta,
                inferred_summary=str(rule["summary"]),
                inferred_rationale=str(rule["rationale"]),
                confidence=str(rule["confidence"]),
                needs_review=bool(rule["needs_review"]),
                evidence=list(rule["evidence"]),
                facts=facts,
                status="codex_self_play_validation",
            )
            recorder.record_inference_audit(
                action_id=action_id,
                turn=before_turn,
                event="codex_self_play_actions",
                input_payload={"before_snapshot_id": before_id},
                output_payload={
                    "actions": actions,
                    "rule": rule,
                    "fact_counts_by_category": fact_counts_by_category(facts),
                },
            )
            action_payloads.append(
                {
                    "turn": before_turn,
                    "after_turn": after_turn,
                    "action_id": action_id,
                    "summary": rule["summary"],
                    "confidence": rule["confidence"],
                    "needs_review": rule["needs_review"],
                    "fact_counts_by_category": fact_counts_by_category(facts),
                    "before_capture_timing": before_snapshot.get("capture_timing"),
                    "after_capture_timing": after_snapshot.get("capture_timing"),
                    "actions": actions,
                }
            )
        recorder.complete_session("completed")
    finally:
        try:
            await write_conn.disconnect()
        finally:
            recorder.close()
    report_path = write_report(db_path)
    return {
        "command": "self-play",
        "demo_id": demo_id,
        "db_path": str(db_path),
        "report_path": str(report_path),
        "turns_requested": args.turns,
        "turns_recorded": len(action_payloads),
        "actions": action_payloads,
    }


async def run_recording(
    args: argparse.Namespace,
    *,
    input_fn: Callable[[str], str] = input,
) -> dict[str, str]:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(
        demo_id=demo_id,
        save_name=args.save_name,
        db_path=db_path,
    )
    conn = RecordingConnection(recorder)
    gs = GameState(conn)
    report_path: Path | None = None
    status = "completed"
    try:
        pending_snapshot_id, pending_snapshot = choose_pending_action(recorder, input_fn)
        for index in range(args.turns):
            if pending_snapshot_id and pending_snapshot:
                before_id = pending_snapshot_id
                before_snapshot = pending_snapshot
                before_turn = int(
                    before_snapshot.get("turn")
                    or (before_snapshot.get("overview") or {}).get("turn")
                    or 0
                )
                pending_snapshot_id = None
                pending_snapshot = None
            else:
                before_turn, before_id, before_snapshot = await capture_state(
                    recorder,
                    gs,
                    f"turn_{index + 1:03d}_before",
                )

            print(
                f"T{before_turn} before 已写入 SQLite: {before_id}\n"
                "请在 Civ6 中手动完成本回合并进入下一回合，然后回到这里按 Enter。"
            )
            input_fn("")

            after_turn, after_id, after_snapshot = await capture_state(
                recorder,
                gs,
                f"turn_{index + 1:03d}_after",
            )
            if after_turn <= before_turn:
                recorder.record_manual_note(
                    turn=before_turn,
                    note=(
                        f"after snapshot turn {after_turn} did not advance beyond "
                        f"before turn {before_turn}"
                    ),
                )

            summary = prompt_required(
                input_fn,
                "这回合主要做了什么：",
                required=args.note_required,
            )
            rationale = prompt_required(
                input_fn,
                "为什么这样做：",
                required=args.note_required,
            )
            tags = parse_tags(input_fn("标签，可用逗号分隔（可空）："))
            delta = build_state_delta(before_snapshot, after_snapshot)
            recorder.record_human_turn(
                turn=before_turn,
                before_snapshot_id=before_id,
                after_snapshot_id=after_id,
                summary=summary,
                rationale=rationale,
                tags=tags,
                delta=delta,
            )
        recorder.complete_session(status)
        report_path = write_report(db_path)
        return {
            "demo_id": demo_id,
            "db_path": str(db_path),
            "report_path": str(report_path),
        }
    except Exception:
        status = "interrupted"
        recorder.complete_session(status)
        raise
    finally:
        try:
            await conn.disconnect()
        finally:
            recorder.close()


def run_report_only(args: argparse.Namespace) -> dict[str, str]:
    demo_id, db_path = resolve_demo_paths(args)
    if not db_path.exists():
        raise HumanDemoError(f"SQLite database does not exist: {db_path}")
    report_path = write_report(db_path)
    return {
        "command": "report-only",
        "demo_id": demo_id,
        "db_path": str(db_path),
        "report_path": str(report_path),
    }


def _watch_transition_status(
    before_turn: int, observed_turn: int, *, pause_on_skip: bool
) -> str:
    if observed_turn <= before_turn:
        return "waiting"
    if observed_turn == before_turn + 1:
        return "ready"
    if pause_on_skip:
        raise HumanDemoError(
            f"Watch observed turn jump from T{before_turn} to T{observed_turn}; "
            "pause and record or correct this transition manually."
        )
    return "ready"


def _watch_print(event: str, payload: dict[str, Any]) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False, default=str), flush=True)


async def _watch_read_turn(gs: GameState) -> tuple[int, Any]:
    overview = await gs.get_game_overview()
    try:
        turn = int(_object_field(overview, "turn") or 0)
    except (TypeError, ValueError) as exc:
        raise HumanDemoError(f"Watch could not read a valid turn from overview: {overview}") from exc
    if turn <= 0:
        raise HumanDemoError(f"Watch read invalid turn from overview: {overview}")
    return turn, overview


def _watch_pending_before(args: argparse.Namespace) -> tuple[str, Path, str, int]:
    demo_id, db_path = resolve_demo_paths(args)
    if not db_path.exists():
        raise HumanDemoError(f"SQLite database does not exist: {db_path}")
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        pending = recorder.pending_before_snapshots()
        if not pending:
            raise HumanDemoError(
                "No pending before snapshot found. Run start first or check that watch has not already recorded this turn."
            )
        before_row = pending[0]
        before_id = str(before_row["snapshot_id"])
        before_turn = int(before_row["turn"])
        return demo_id, db_path, before_id, before_turn
    finally:
        recorder.close()


def _watch_record_note(args: argparse.Namespace, note: str, *, turn: int | None = None) -> None:
    demo_id, db_path = resolve_demo_paths(args)
    recorder = SqliteDemoRecorder(demo_id=demo_id, save_name=args.save_name, db_path=db_path)
    try:
        recorder.record_manual_note(turn=turn, note=note)
    finally:
        recorder.close()


def _watch_action_summary(result: dict[str, object]) -> dict[str, object]:
    rule = result.get("rule_inference")
    rule_dict = rule if isinstance(rule, dict) else {}
    return {
        "action_id": result.get("action_id"),
        "turn": result.get("turn"),
        "after_turn": result.get("after_turn"),
        "summary": rule_dict.get("summary"),
        "confidence": rule_dict.get("confidence"),
        "needs_review": rule_dict.get("needs_review"),
        "fact_counts_by_category": result.get("fact_counts_by_category"),
        "capture_timing": result.get("capture_timing"),
        "periodic_question_due": result.get("periodic_question_due"),
        "periodic_question": result.get("periodic_question"),
    }


async def run_watch(args: argparse.Namespace) -> dict[str, object]:
    demo_id, db_path, _, before_turn = _watch_pending_before(args)
    _watch_record_note(
        args,
        note=(
            "watch:start; "
            f"poll_seconds={args.poll_seconds}; stable_seconds={args.stable_seconds}; "
            f"max_turns={args.max_turns}; pause_on_skip={args.pause_on_skip}; "
            f"stop_on_review={args.stop_on_review}; "
            f"stop_on_periodic_question={args.stop_on_periodic_question}"
        ),
    )
    _watch_print(
        "watch_started",
        {
            "demo_id": demo_id,
            "db_path": str(db_path),
            "pending_before_turn": before_turn,
            "poll_seconds": args.poll_seconds,
            "stable_seconds": args.stable_seconds,
            "max_turns": args.max_turns,
        },
    )

    recorded: list[dict[str, object]] = []
    status = "running"
    conn = GameConnection()
    gs = GameState(conn)
    try:
        while args.max_turns <= 0 or len(recorded) < args.max_turns:
            _, _, before_id, before_turn = _watch_pending_before(args)
            _watch_print(
                "watch_waiting",
                {"before_snapshot_id": before_id, "before_turn": before_turn},
            )
            while True:
                observed_turn, _ = await _watch_read_turn(gs)
                status_text = _watch_transition_status(
                    before_turn,
                    observed_turn,
                    pause_on_skip=bool(args.pause_on_skip),
                )
                if status_text == "ready":
                    _watch_print(
                        "turn_detected",
                        {"before_turn": before_turn, "observed_turn": observed_turn},
                    )
                    if args.stable_seconds:
                        await asyncio.sleep(float(args.stable_seconds))
                    stable_turn, _ = await _watch_read_turn(gs)
                    _watch_transition_status(
                        before_turn,
                        stable_turn,
                        pause_on_skip=bool(args.pause_on_skip),
                    )
                    if stable_turn == observed_turn:
                        break
                    _watch_print(
                        "turn_not_stable",
                        {
                            "before_turn": before_turn,
                            "observed_turn": observed_turn,
                            "stable_turn": stable_turn,
                        },
                    )
                    continue
                await asyncio.sleep(float(args.poll_seconds))

            await conn.disconnect()
            result = await run_advance(args)
            action_summary = _watch_action_summary(result)
            recorded.append(action_summary)
            _watch_print("turn_recorded", action_summary)

            rule = result.get("rule_inference")
            needs_review = bool(rule.get("needs_review")) if isinstance(rule, dict) else False
            if args.stop_on_review and needs_review:
                status = "paused_review"
                break
            if args.stop_on_periodic_question and result.get("periodic_question_due"):
                status = "paused_periodic_question"
                break

            conn = GameConnection()
            gs = GameState(conn)
        else:
            status = "max_turns_reached" if args.max_turns > 0 else "running"
    finally:
        await conn.disconnect()
    _watch_record_note(args, note=f"watch:{status}; recorded_turns={len(recorded)}")
    return {
        "command": "watch",
        "demo_id": demo_id,
        "db_path": str(db_path),
        "status": status,
        "recorded_turns": len(recorded),
        "records": recorded,
    }


def dispatch(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "start":
        return asyncio.run(run_start(args))
    if args.command == "advance":
        return asyncio.run(run_advance(args))
    if args.command == "record-inference":
        return run_record_inference(args)
    if args.command == "correct":
        return run_correct(args)
    if args.command == "note":
        return run_note(args)
    if args.command == "finish":
        return run_finish(args)
    if args.command in {"report-only", "legacy-report-only"}:
        return run_report_only(args)
    if args.command == "self-play":
        return asyncio.run(run_self_play(args))
    if args.command == "watch":
        return asyncio.run(run_watch(args))
    return asyncio.run(run_recording(args))


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = dispatch(args)
        print(json.dumps(payload, ensure_ascii=False, default=str))
    except HumanDemoError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()

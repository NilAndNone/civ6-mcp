"""CLI for recording human-play Civ6 demonstrations to SQLite."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Callable

from codex_hl.demos.recorder import (
    HumanDemoError,
    SqliteDemoRecorder,
    build_rule_inference,
    build_state_delta,
    default_db_path,
    make_demo_id,
    write_report,
)
from codex_hl.evidence.observation import DEFAULT_SAVE_NAME, RecordingConnection, capture_state
from civ6_connector.game_state import GameState


COMMANDS = {
    "start",
    "advance",
    "record-inference",
    "correct",
    "note",
    "finish",
    "report-only",
}


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
    if args.command in {"legacy-report-only", "report-only"} and not args.db and not args.demo_id:
        raise SystemExit("report-only requires --db or --demo-id")
    if args.command != "start" and args.command not in {"legacy-interactive"} and not args.db and not args.demo_id:
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
    conn = RecordingConnection(recorder)
    gs = GameState(conn)
    try:
        return await capture_state(recorder, gs, label)
    finally:
        await conn.disconnect()


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
        rule = build_rule_inference(delta)
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
            "rule_inference": rule,
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

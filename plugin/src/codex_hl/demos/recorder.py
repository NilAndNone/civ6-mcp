"""SQLite storage for human-play Civ6 demonstrations.

This module intentionally keeps human demonstrations separate from Observation
``episodes/`` evidence.  The database is local reference evidence only; it does
not produce candidate assets or mutate the strategy asset registry.
"""

from __future__ import annotations

import html
import json
import sqlite3
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable

from codex_hl.evidence.observation import (
    ROOT,
    now_iso,
    now_stamp,
    run_git,
    short_text,
    to_jsonable,
)


SCHEMA_VERSION = 3
HUMAN_DEMOS_ROOT = ROOT / "human_demos"
READ_ONLY_TOOL_PREFIXES = ("get_",)
READ_ONLY_TOOL_NAMES = frozenset(
    {
        "list_city_production",
    }
)
FORBIDDEN_RECORDING_TOOLS = frozenset(
    {
        "end_turn",
        "end_turn_retry",
        "end_turn_after_diplomacy",
        "set_research",
        "set_civic",
        "set_city_production",
        "unit_action",
        "purchase_tile",
        "queue_wc_votes",
        "respond_to_diplomacy",
        "respond_to_trade",
        "run_lua",
    }
)


class HumanDemoError(RuntimeError):
    """User-facing human-demo recording error."""


def make_demo_id() -> str:
    return f"human_demo_{now_stamp()}"


def default_db_path(demo_id: str) -> Path:
    return HUMAN_DEMOS_ROOT / demo_id / "demo.sqlite"


def json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)


def json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS demo_sessions (
            demo_id TEXT PRIMARY KEY,
            save_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL,
            repo_commit TEXT NOT NULL,
            repo_status TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS state_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            turn INTEGER NOT NULL,
            label TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS human_actions (
            action_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            turn INTEGER NOT NULL,
            before_snapshot_id TEXT NOT NULL REFERENCES state_snapshots(snapshot_id),
            after_snapshot_id TEXT NOT NULL REFERENCES state_snapshots(snapshot_id),
            summary TEXT NOT NULL,
            rationale TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            inferred_summary TEXT,
            inferred_rationale TEXT,
            confidence TEXT NOT NULL DEFAULT 'unknown',
            needs_review INTEGER NOT NULL DEFAULT 1,
            user_correction TEXT,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'manual',
            updated_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS state_deltas (
            delta_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            turn INTEGER NOT NULL,
            before_snapshot_id TEXT NOT NULL REFERENCES state_snapshots(snapshot_id),
            after_snapshot_id TEXT NOT NULL REFERENCES state_snapshots(snapshot_id),
            delta_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS action_facts (
            fact_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            action_id TEXT NOT NULL REFERENCES human_actions(action_id),
            turn INTEGER NOT NULL,
            category TEXT NOT NULL,
            kind TEXT NOT NULL,
            subject_id TEXT,
            subject_name TEXT,
            metric TEXT,
            before_json TEXT,
            after_json TEXT,
            delta_json TEXT,
            summary TEXT NOT NULL,
            importance TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            call_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            turn INTEGER,
            tool TEXT NOT NULL,
            params_json TEXT NOT NULL,
            result_json TEXT,
            success INTEGER NOT NULL,
            error_json TEXT,
            duration_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lua_exchanges (
            exchange_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            context TEXT NOT NULL,
            request TEXT NOT NULL,
            response_json TEXT,
            success INTEGER NOT NULL,
            error_json TEXT,
            duration_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS manual_notes (
            note_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            turn INTEGER,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inference_audit (
            audit_id TEXT PRIMARY KEY,
            demo_id TEXT NOT NULL REFERENCES demo_sessions(demo_id),
            action_id TEXT REFERENCES human_actions(action_id),
            turn INTEGER,
            event TEXT NOT NULL,
            input_json TEXT NOT NULL,
            output_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_state_snapshots_demo_turn
            ON state_snapshots(demo_id, turn);
        CREATE INDEX IF NOT EXISTS idx_human_actions_demo_turn
            ON human_actions(demo_id, turn);
        CREATE INDEX IF NOT EXISTS idx_state_deltas_demo_turn
            ON state_deltas(demo_id, turn);
        CREATE INDEX IF NOT EXISTS idx_action_facts_demo_turn
            ON action_facts(demo_id, turn);
        CREATE INDEX IF NOT EXISTS idx_action_facts_demo_action
            ON action_facts(demo_id, action_id);
        CREATE INDEX IF NOT EXISTS idx_action_facts_demo_category
            ON action_facts(demo_id, category, kind);
        CREATE INDEX IF NOT EXISTS idx_inference_audit_demo_action
            ON inference_audit(demo_id, action_id);
        """
    )
    _ensure_column(conn, "human_actions", "inferred_summary", "TEXT")
    _ensure_column(conn, "human_actions", "inferred_rationale", "TEXT")
    _ensure_column(
        conn, "human_actions", "confidence", "TEXT NOT NULL DEFAULT 'unknown'"
    )
    _ensure_column(
        conn, "human_actions", "needs_review", "INTEGER NOT NULL DEFAULT 1"
    )
    _ensure_column(conn, "human_actions", "user_correction", "TEXT")
    _ensure_column(
        conn, "human_actions", "evidence_json", "TEXT NOT NULL DEFAULT '[]'"
    )
    _ensure_column(conn, "human_actions", "status", "TEXT NOT NULL DEFAULT 'manual'")
    _ensure_column(conn, "human_actions", "updated_at", "TEXT")
    conn.commit()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    columns: set[str] = set()
    for row in conn.execute(f"PRAGMA table_info({table})"):
        try:
            columns.add(str(row["name"]))
        except (TypeError, KeyError):
            columns.add(str(row[1]))
    return columns


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    if column in _table_columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _count_rows(conn: sqlite3.Connection, table: str, demo_id: str) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE demo_id = ?", (demo_id,)
    ).fetchone()
    return int(row["count"] if row else 0)


def is_read_only_recording_tool(name: str) -> bool:
    if name in FORBIDDEN_RECORDING_TOOLS:
        return False
    return name.startswith(READ_ONLY_TOOL_PREFIXES) or name in READ_ONLY_TOOL_NAMES


class SqliteDemoRecorder:
    """Recorder adapter compatible with Observation ``capture_state``."""

    def __init__(self, *, demo_id: str, save_name: str, db_path: Path) -> None:
        self.demo_id = demo_id
        self.episode_id = demo_id
        self.save_name = save_name
        self.db_path = db_path.resolve()
        self.conn = open_db(self.db_path)
        init_schema(self.conn)

        self.tool_seq = _count_rows(self.conn, "tool_calls", self.demo_id)
        self.lua_seq = _count_rows(self.conn, "lua_exchanges", self.demo_id)
        self.state_seq = _count_rows(self.conn, "state_snapshots", self.demo_id)
        self.action_seq = _count_rows(self.conn, "human_actions", self.demo_id)
        self.delta_seq = _count_rows(self.conn, "state_deltas", self.demo_id)
        self.fact_seq = _count_rows(self.conn, "action_facts", self.demo_id)
        self.note_seq = _count_rows(self.conn, "manual_notes", self.demo_id)
        self.audit_seq = _count_rows(self.conn, "inference_audit", self.demo_id)
        self.missing_fields: list[dict[str, str]] = []
        self.tool_error_count = 0
        self.lua_error_count = 0
        self.start_turn: int | None = None
        self.start_time = now_iso()

        self._ensure_session()

    def _ensure_session(self) -> None:
        self.conn.execute(
            """
            INSERT INTO demo_sessions (
                demo_id, save_name, started_at, ended_at, status,
                repo_commit, repo_status, schema_version
            )
            VALUES (?, ?, ?, NULL, 'running', ?, ?, ?)
            ON CONFLICT(demo_id) DO UPDATE SET
                save_name = excluded.save_name,
                ended_at = CASE
                    WHEN demo_sessions.status = 'completed' THEN demo_sessions.ended_at
                    ELSE NULL
                END,
                status = CASE
                    WHEN demo_sessions.status = 'completed' THEN demo_sessions.status
                    ELSE 'running'
                END,
                repo_commit = excluded.repo_commit,
                repo_status = excluded.repo_status,
                schema_version = excluded.schema_version
            """,
            (
                self.demo_id,
                self.save_name,
                self.start_time,
                run_git(["rev-parse", "HEAD"]),
                run_git(["status", "--short"]),
                SCHEMA_VERSION,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add_gap(self, field: str, reason: str, next_step: str) -> None:
        self.missing_fields.append(
            {"field": field, "reason": reason, "next_step": next_step}
        )

    def timeline(self, line: str) -> None:
        # Kept for compatibility with Observation capture_state. Human-visible notes
        # are recorded explicitly via record_manual_note().
        _ = line

    def codex_output(self, kind: str, turn: int | None, content: Any) -> None:
        self.record_manual_note(
            turn=turn,
            note=f"codex_output:{kind}: {short_text(content, 1000)}",
        )

    async def log_lua(
        self,
        context: str,
        lua_code: str,
        timeout: float,
        fn: Callable[[], Awaitable[list[str]]],
    ) -> list[str]:
        _ = timeout
        self.lua_seq += 1
        exchange_id = f"lua-{self.lua_seq:05d}"
        start = time.perf_counter()
        response_json: str | None = None
        error_json: str | None = None
        success = 0
        try:
            result = await fn()
            success = 1
            response_json = json_dumps(result)
            return result
        except Exception as exc:  # noqa: BLE001 - raw evidence capture.
            self.lua_error_count += 1
            error_json = json_dumps(
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.conn.execute(
                """
                INSERT INTO lua_exchanges (
                    exchange_id, demo_id, context, request, response_json,
                    success, error_json, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exchange_id,
                    self.demo_id,
                    context,
                    lua_code,
                    response_json,
                    success,
                    error_json,
                    duration_ms,
                ),
            )
            self.conn.commit()

    async def tool_call(
        self,
        name: str,
        params: dict[str, Any],
        fn: Callable[[], Awaitable[Any]],
        *,
        turn: int | None = None,
    ) -> tuple[str, Any]:
        if not is_read_only_recording_tool(name):
            raise HumanDemoError(
                f"Human demo recording is strict read-only; refused tool `{name}`."
            )
        self.tool_seq += 1
        call_id = f"tool-{self.tool_seq:05d}"
        start = time.perf_counter()
        result_json: str | None = None
        error_json: str | None = None
        success = 0
        try:
            result = await fn()
            success = 1
            result_json = json_dumps(result)
            return call_id, result
        except Exception as exc:  # noqa: BLE001 - raw evidence capture.
            self.tool_error_count += 1
            error_json = json_dumps(
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.conn.execute(
                """
                INSERT INTO tool_calls (
                    call_id, demo_id, turn, tool, params_json, result_json,
                    success, error_json, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    self.demo_id,
                    turn,
                    name,
                    json_dumps(params),
                    result_json,
                    success,
                    error_json,
                    duration_ms,
                ),
            )
            self.conn.commit()

    def record_state(
        self,
        turn: int,
        label: str,
        snapshot: dict[str, Any],
        related_tool_call_ids: list[str],
    ) -> str:
        self.state_seq += 1
        snapshot_id = f"state-{self.state_seq:04d}-T{turn:04d}-{label}"
        captured_at = now_iso()
        payload = {
            **snapshot,
            "snapshot_id": snapshot_id,
            "demo_id": self.demo_id,
            "turn": turn,
            "label": label,
            "captured_at": captured_at,
            "related_tool_call_ids": related_tool_call_ids,
        }
        self.conn.execute(
            """
            INSERT INTO state_snapshots (
                snapshot_id, demo_id, turn, label, captured_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                self.demo_id,
                turn,
                label,
                captured_at,
                json_dumps(payload),
            ),
        )
        self.conn.commit()
        return snapshot_id

    def clone_state_snapshot(self, source_snapshot_id: str, label: str) -> str:
        source = self.load_snapshot(source_snapshot_id)
        turn = int(
            source.get("turn")
            or (source.get("overview") or {}).get("turn")
            or 0
        )
        related = list(source.get("related_tool_call_ids") or [])
        snapshot = {
            key: value
            for key, value in source.items()
            if key
            not in {
                "snapshot_id",
                "demo_id",
                "label",
                "captured_at",
                "related_tool_call_ids",
            }
        }
        return self.record_state(turn, label, snapshot, related)

    def record_human_turn(
        self,
        *,
        turn: int,
        before_snapshot_id: str,
        after_snapshot_id: str,
        summary: str,
        rationale: str,
        tags: list[str],
        delta: dict[str, Any],
        inferred_summary: str | None = None,
        inferred_rationale: str | None = None,
        confidence: str = "manual",
        needs_review: bool = False,
        user_correction: str | None = None,
        evidence: list[Any] | None = None,
        facts: list[dict[str, Any]] | None = None,
        status: str = "manual",
    ) -> str:
        before_snapshot = self.load_snapshot(before_snapshot_id)
        after_snapshot = self.load_snapshot(after_snapshot_id)
        action_facts = (
            list(facts)
            if facts is not None
            else extract_action_facts(before_snapshot, after_snapshot, delta)
        )
        action_seq = self.action_seq + 1
        delta_seq = self.delta_seq + 1
        fact_seq = self.fact_seq
        action_id = f"human-action-{action_seq:04d}"
        delta_id = f"state-delta-{delta_seq:04d}"
        created_at = now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO human_actions (
                    action_id, demo_id, turn, before_snapshot_id,
                    after_snapshot_id, summary, rationale, tags_json,
                    inferred_summary, inferred_rationale, confidence,
                    needs_review, user_correction, evidence_json, status,
                    updated_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    self.demo_id,
                    turn,
                    before_snapshot_id,
                    after_snapshot_id,
                    summary.strip(),
                    rationale.strip(),
                    json_dumps(tags),
                    inferred_summary.strip() if inferred_summary else None,
                    inferred_rationale.strip() if inferred_rationale else None,
                    confidence,
                    1 if needs_review else 0,
                    user_correction.strip() if user_correction else None,
                    json_dumps(evidence or []),
                    status,
                    created_at,
                    created_at,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO state_deltas (
                    delta_id, demo_id, turn, before_snapshot_id,
                    after_snapshot_id, delta_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    delta_id,
                    self.demo_id,
                    turn,
                    before_snapshot_id,
                    after_snapshot_id,
                    json_dumps(delta),
                ),
            )
            for fact in action_facts:
                fact_seq += 1
                fact_id = f"action-fact-{fact_seq:05d}"
                self.conn.execute(
                    """
                    INSERT INTO action_facts (
                        fact_id, demo_id, action_id, turn, category, kind,
                        subject_id, subject_name, metric, before_json, after_json,
                        delta_json, summary, importance, source, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact_id,
                        self.demo_id,
                        action_id,
                        turn,
                        fact.get("category"),
                        fact.get("kind"),
                        fact.get("subject_id"),
                        fact.get("subject_name"),
                        fact.get("metric"),
                        _json_or_none(fact.get("before")),
                        _json_or_none(fact.get("after")),
                        _json_or_none(fact.get("delta")),
                        fact.get("summary"),
                        fact.get("importance"),
                        fact.get("source") or "snapshot_delta",
                        created_at,
                    ),
                )
        self.action_seq = action_seq
        self.delta_seq = delta_seq
        self.fact_seq = fact_seq
        return action_id

    def record_inference_audit(
        self,
        *,
        action_id: str | None,
        turn: int | None,
        event: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
    ) -> str:
        self.audit_seq += 1
        audit_id = f"inference-audit-{self.audit_seq:04d}"
        self.conn.execute(
            """
            INSERT INTO inference_audit (
                audit_id, demo_id, action_id, turn, event,
                input_json, output_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                self.demo_id,
                action_id,
                turn,
                event,
                json_dumps(input_payload),
                json_dumps(output_payload),
                now_iso(),
            ),
        )
        self.conn.commit()
        return audit_id

    def tool_timing_summary(
        self, *, start_seq: int = 0, wall_ms: int | None = None, limit: int = 8
    ) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT call_id, tool, success, duration_ms, error_json
            FROM tool_calls
            WHERE demo_id = ?
              AND CAST(SUBSTR(call_id, 6) AS INTEGER) > ?
            ORDER BY CAST(SUBSTR(call_id, 6) AS INTEGER)
            """,
            (self.demo_id, start_seq),
        ).fetchall()
        slowest = sorted(rows, key=lambda row: int(row["duration_ms"]), reverse=True)[
            :limit
        ]
        failed = [row for row in rows if not int(row["success"])]
        return {
            "wall_ms": wall_ms,
            "tool_call_count": len(rows),
            "failed_tool_count": len(failed),
            "sum_tool_duration_ms": sum(int(row["duration_ms"]) for row in rows),
            "slowest_tools": [
                {
                    "call_id": row["call_id"],
                    "tool": row["tool"],
                    "success": bool(row["success"]),
                    "duration_ms": int(row["duration_ms"]),
                    "error": short_text(json_loads(row["error_json"]), 240)
                    if row["error_json"]
                    else None,
                }
                for row in slowest
            ],
        }

    def latest_action(self) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT *
            FROM human_actions
            WHERE demo_id = ?
            ORDER BY turn DESC, created_at DESC
            LIMIT 1
            """,
            (self.demo_id,),
        ).fetchone()

    def find_action(
        self, *, action_id: str | None = None, turn: int | None = None
    ) -> sqlite3.Row:
        if action_id:
            row = self.conn.execute(
                "SELECT * FROM human_actions WHERE demo_id = ? AND action_id = ?",
                (self.demo_id, action_id),
            ).fetchone()
        elif turn is not None:
            row = self.conn.execute(
                """
                SELECT *
                FROM human_actions
                WHERE demo_id = ? AND turn = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (self.demo_id, turn),
            ).fetchone()
        else:
            row = self.latest_action()
        if row is None:
            if action_id:
                target = action_id
            elif turn is not None:
                target = f"T{turn}"
            else:
                target = "latest action"
            raise HumanDemoError(f"Missing human action: {target}")
        return row

    def record_codex_inference(
        self,
        *,
        action_id: str | None,
        turn: int | None,
        summary: str,
        rationale: str = "",
        confidence: str = "medium",
        needs_review: bool | None = None,
        evidence: list[Any] | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
    ) -> str:
        session = self.conn.execute(
            "SELECT status FROM demo_sessions WHERE demo_id = ?", (self.demo_id,)
        ).fetchone()
        if session is not None and str(session["status"]) == "completed":
            raise HumanDemoError(
                "This demo session is completed; inference updates are frozen after report generation."
            )
        row = self.find_action(action_id=action_id, turn=turn)
        resolved_action_id = str(row["action_id"])
        resolved_turn = int(row["turn"])
        if needs_review is None:
            needs_review = confidence.lower() == "low"
        updated_at = now_iso()
        self.conn.execute(
            """
            UPDATE human_actions
            SET summary = ?,
                rationale = ?,
                inferred_summary = ?,
                inferred_rationale = ?,
                confidence = ?,
                needs_review = ?,
                evidence_json = ?,
                status = 'inferred',
                updated_at = ?
            WHERE demo_id = ? AND action_id = ?
            """,
            (
                summary.strip(),
                rationale.strip(),
                summary.strip(),
                rationale.strip() or None,
                confidence,
                1 if needs_review else 0,
                json_dumps(evidence or []),
                updated_at,
                self.demo_id,
                resolved_action_id,
            ),
        )
        self.conn.commit()
        self.record_inference_audit(
            action_id=resolved_action_id,
            turn=resolved_turn,
            event="codex_inference",
            input_payload=input_payload or {},
            output_payload=output_payload
            or {
                "summary": summary,
                "rationale": rationale,
                "confidence": confidence,
                "needs_review": needs_review,
                "evidence": evidence or [],
            },
        )
        return resolved_action_id

    def correct_action(
        self,
        *,
        text: str,
        action_id: str | None = None,
        turn: int | None = None,
        allow_completed: bool = False,
    ) -> str:
        session = self.conn.execute(
            "SELECT status FROM demo_sessions WHERE demo_id = ?", (self.demo_id,)
        ).fetchone()
        if (
            session is not None
            and str(session["status"]) == "completed"
            and not allow_completed
        ):
            raise HumanDemoError(
                "This demo session is completed; corrections are frozen after report generation."
            )
        row = self.find_action(action_id=action_id, turn=turn)
        resolved_action_id = str(row["action_id"])
        resolved_turn = int(row["turn"])
        correction = text.strip()
        self.conn.execute(
            """
            UPDATE human_actions
            SET summary = ?,
                rationale = ?,
                user_correction = ?,
                confidence = 'human_corrected',
                needs_review = 0,
                status = 'corrected',
                updated_at = ?
            WHERE demo_id = ? AND action_id = ?
            """,
            (
                correction,
                correction,
                correction,
                now_iso(),
                self.demo_id,
                resolved_action_id,
            ),
        )
        self.conn.commit()
        self.record_inference_audit(
            action_id=resolved_action_id,
            turn=resolved_turn,
            event="human_correction",
            input_payload={"target_turn": turn, "target_action_id": action_id},
            output_payload={"correction": correction},
        )
        return resolved_action_id

    def record_manual_note(self, *, turn: int | None, note: str) -> str:
        self.note_seq += 1
        note_id = f"note-{self.note_seq:04d}"
        self.conn.execute(
            """
            INSERT INTO manual_notes (note_id, demo_id, turn, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (note_id, self.demo_id, turn, note, now_iso()),
        )
        self.conn.commit()
        return note_id

    def complete_session(self, status: str = "completed") -> None:
        self.conn.execute(
            """
            UPDATE demo_sessions
            SET ended_at = ?, status = ?
            WHERE demo_id = ?
            """,
            (now_iso(), status, self.demo_id),
        )
        self.conn.commit()

    def pending_before_snapshots(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT s.*
                FROM state_snapshots s
                WHERE s.demo_id = ?
                  AND s.label LIKE '%_before'
                  AND NOT EXISTS (
                    SELECT 1 FROM human_actions a
                    WHERE a.before_snapshot_id = s.snapshot_id
                  )
                ORDER BY s.captured_at DESC
                """,
                (self.demo_id,),
            )
        )

    def load_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT payload_json FROM state_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise HumanDemoError(f"Missing state snapshot: {snapshot_id}")
        payload = json_loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise HumanDemoError(f"Invalid state snapshot payload: {snapshot_id}")
        return payload


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_dict(value: Any) -> dict[str, Any]:
    converted = to_jsonable(value)
    return converted if isinstance(converted, dict) else {}


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _numeric_delta(before: Any, after: Any) -> float | int | None:
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return after - before
    return None


def _overview_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "turn",
        "num_cities",
        "num_units",
        "science_yield",
        "culture_yield",
        "gold",
        "gold_per_turn",
        "gold_income",
        "faith",
        "diplomatic_favor",
        "favor_per_turn",
        "score",
        "total_population",
        "total_maintenance",
        "unit_maintenance",
        "era_score",
        "era_golden_threshold",
    ]
    b_overview = _as_dict(before.get("overview"))
    a_overview = _as_dict(after.get("overview"))
    diff: dict[str, Any] = {}
    for key in keys:
        b_value = b_overview.get(key)
        a_value = a_overview.get(key)
        if b_value != a_value:
            diff[key] = {
                "before": b_value,
                "after": a_value,
                "delta": _numeric_delta(b_value, a_value),
            }
    return diff


def _collection_by_id(items: Any, keys: list[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_as_list(to_jsonable(items))):
        if not isinstance(raw, dict):
            continue
        row_key = None
        for key in keys:
            value = raw.get(key)
            if value not in {None, ""}:
                row_key = str(value)
                break
        if row_key is None:
            row_key = f"row-{index}-{hash(json_dumps(raw))}"
        rows[row_key] = raw
    return rows


def _changed_fields(
    before: dict[str, Any], after: dict[str, Any], fields: list[str]
) -> dict[str, dict[str, Any]]:
    changed: dict[str, dict[str, Any]] = {}
    for field in fields:
        b_value = before.get(field)
        a_value = after.get(field)
        if b_value != a_value:
            changed[field] = {
                "before": b_value,
                "after": a_value,
                "delta": _numeric_delta(b_value, a_value),
            }
    return changed


def _city_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_rows = _collection_by_id(before.get("cities"), ["city_id", "id", "name"])
    after_rows = _collection_by_id(after.get("cities"), ["city_id", "id", "name"])
    fields = [
        "name",
        "population",
        "current_production",
        "production",
        "production_turns_left",
        "housing",
        "amenities",
        "food_surplus",
    ]
    changed = {
        key: _changed_fields(before_rows[key], after_rows[key], fields)
        for key in sorted(set(before_rows) & set(after_rows))
        if _changed_fields(before_rows[key], after_rows[key], fields)
    }
    return {
        "before_count": len(before_rows),
        "after_count": len(after_rows),
        "added": sorted(set(after_rows) - set(before_rows)),
        "removed": sorted(set(before_rows) - set(after_rows)),
        "changed": changed,
    }


def _unit_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_rows = _collection_by_id(
        before.get("units"), ["unit_id", "id", "name", "unit_name"]
    )
    after_rows = _collection_by_id(
        after.get("units"), ["unit_id", "id", "name", "unit_name"]
    )
    fields = [
        "unit_type",
        "name",
        "x",
        "y",
        "health",
        "hp",
        "moves_remaining",
        "movement",
        "experience",
        "level",
        "activity_type",
        "promotion_available",
    ]
    changed: dict[str, Any] = {}
    moved: dict[str, Any] = {}
    for key in sorted(set(before_rows) & set(after_rows)):
        field_delta = _changed_fields(before_rows[key], after_rows[key], fields)
        if field_delta:
            changed[key] = field_delta
        b_pos = (before_rows[key].get("x"), before_rows[key].get("y"))
        a_pos = (after_rows[key].get("x"), after_rows[key].get("y"))
        if b_pos != a_pos:
            moved[key] = {"before": b_pos, "after": a_pos}
    return {
        "before_count": len(before_rows),
        "after_count": len(after_rows),
        "added": sorted(set(after_rows) - set(before_rows)),
        "removed": sorted(set(before_rows) - set(after_rows)),
        "moved": moved,
        "changed": changed,
    }


def _observed_field_changed(before: dict[str, Any], after: dict[str, Any], key: str) -> bool:
    if before.get(key) is None or after.get(key) is None:
        return False
    return before.get(key) != after.get(key)


def _count_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> dict[str, int | bool]:
    if before.get(key) is None or after.get(key) is None:
        return {
            "before_count": len(_as_list(before.get(key))),
            "after_count": len(_as_list(after.get(key))),
            "delta": 0,
            "observed": False,
        }
    before_count = len(_as_list(before.get(key)))
    after_count = len(_as_list(after.get(key)))
    return {
        "before_count": before_count,
        "after_count": after_count,
        "delta": after_count - before_count,
        "observed": True,
    }


def _policy_slots_by_index(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    policies = _as_dict(snapshot.get("policies"))
    slots: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_as_list(policies.get("slots"))):
        if not isinstance(raw, dict):
            continue
        slot_index = raw.get("slot_index")
        key = str(slot_index if slot_index not in {None, ""} else index)
        slots[key] = raw
    return slots


def _policy_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_slots = _policy_slots_by_index(before)
    after_slots = _policy_slots_by_index(after)
    changed = {
        key: {
            "before": before_slots.get(key),
            "after": after_slots.get(key),
        }
        for key in sorted(set(before_slots) | set(after_slots), key=str)
        if before_slots.get(key) != after_slots.get(key)
    }
    return {
        "before_count": len(before_slots),
        "after_count": len(after_slots),
        "changed": changed,
    }


def _historic_moments_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_rows = _collection_by_id(before.get("historic_moments"), ["moment_id", "id", "ID"])
    after_rows = _collection_by_id(after.get("historic_moments"), ["moment_id", "id", "ID"])
    return {
        "before_count": len(before_rows),
        "after_count": len(after_rows),
        "added": sorted(set(after_rows) - set(before_rows), key=str),
        "removed": sorted(set(before_rows) - set(after_rows), key=str),
        "changed": {
            key: {"before": before_rows[key], "after": after_rows[key]}
            for key in sorted(set(before_rows) & set(after_rows), key=str)
            if before_rows[key] != after_rows[key]
        },
    }


OVERVIEW_FACT_LABELS = {
    "num_cities": "城市数",
    "num_units": "单位数",
    "science_yield": "科技值",
    "culture_yield": "文化值",
    "gold": "金币",
    "gold_per_turn": "每回合金币",
    "gold_income": "金币收入",
    "faith": "信仰",
    "diplomatic_favor": "外交支持",
    "favor_per_turn": "每回合外交支持",
    "score": "分数",
    "total_population": "总人口",
    "total_maintenance": "维护费",
    "unit_maintenance": "单位维护费",
    "era_score": "时代分",
    "era_golden_threshold": "黄金时代门槛",
}


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json_dumps(value)


def _fact(
    *,
    category: str,
    kind: str,
    summary: str,
    importance: str,
    subject_id: Any = None,
    subject_name: Any = None,
    metric: str | None = None,
    before: Any = None,
    after: Any = None,
    delta: Any = None,
    source: str = "snapshot_delta",
) -> dict[str, Any]:
    return {
        "category": category,
        "kind": kind,
        "subject_id": None if subject_id is None else str(subject_id),
        "subject_name": None if subject_name is None else str(subject_name),
        "metric": metric,
        "before": before,
        "after": after,
        "delta": delta,
        "summary": summary,
        "importance": importance,
        "source": source,
    }


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _overview_fact_summary(
    metric: str, label: str, change: dict[str, Any], after_snapshot: dict[str, Any]
) -> str:
    if metric != "era_score":
        return f"{label} {change.get('before')} -> {change.get('after')}"

    after_overview = _as_dict(after_snapshot.get("overview"))
    threshold = after_overview.get("era_golden_threshold")
    after_score = _numeric_value(change.get("after"))
    threshold_value = _numeric_value(threshold)
    details = []
    if threshold not in {None, ""}:
        details.append(f"黄金门槛 {threshold}")
    if after_score is not None and threshold_value is not None:
        gap = max(0.0, threshold_value - after_score)
        details.append(f"距黄金时代差 {_format_number(gap)}")
    suffix = f"（{'，'.join(details)}）" if details else ""
    return f"{label} {change.get('before')} -> {change.get('after')}{suffix}"


def _overview_fact_importance(metric: str) -> str:
    if metric == "era_score":
        return "high"
    if metric in {"science_yield", "culture_yield", "gold", "gold_per_turn", "gold_income"}:
        return "medium"
    return "low"


def _entity_name(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return None


def _meaningful_value(*values: Any) -> Any | None:
    for value in values:
        if value not in {None, "", "None"}:
            return value
    return None


def _is_idle_production(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"", "none", "null", "nothing", "corrupted_queue"}


def _city_collection_has_added(
    before_city: dict[str, Any],
    after_city: dict[str, Any],
    key: str,
    item: str,
) -> bool:
    def aliases(value: str) -> set[str]:
        values = {value}
        if value.startswith("BUILDING_"):
            values.add(value.removeprefix("BUILDING_"))
        if value.startswith("DISTRICT_"):
            values.add(value.removeprefix("DISTRICT_"))
        return values

    item_aliases = aliases(str(item))
    before_values = {str(value) for value in _as_list(before_city.get(key))}
    for value in _as_list(after_city.get(key)):
        text = str(value)
        if text in before_values:
            continue
        text_base = text.split("@", 1)[0]
        if item_aliases & aliases(text_base):
            return True
    return False


def _production_completion_observed(
    before_production: Any,
    before_city: dict[str, Any],
    after_city: dict[str, Any],
    before_units: dict[str, dict[str, Any]],
    after_units: dict[str, dict[str, Any]],
) -> bool:
    item = str(before_production or "")
    if item.startswith("PROJECT_"):
        return True
    if item.startswith("UNIT_"):
        added_unit_ids = set(after_units) - set(before_units)
        return any(
            str(after_units[unit_id].get("unit_type") or "") == item
            for unit_id in added_unit_ids
        )
    if item.startswith("BUILDING_"):
        return _city_collection_has_added(before_city, after_city, "buildings", item)
    if item.startswith("DISTRICT_"):
        return _city_collection_has_added(before_city, after_city, "districts", item)
    return False


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _purchase_gold_cost(snapshot: dict[str, Any], item_name: str) -> float | None:
    production = snapshot.get("production")
    if not isinstance(production, dict):
        return None
    for options in production.values():
        for option in _as_list(options):
            if not isinstance(option, dict):
                continue
            if option.get("item_name") != item_name:
                continue
            return _number(option.get("gold_cost"))
    return None


FAITH_PURCHASABLE_CIVILIAN_UNITS = {
    "UNIT_BUILDER",
    "UNIT_SETTLER",
    "UNIT_TRADER",
}


def _is_faith_purchasable_civilian_unit(unit: dict[str, Any]) -> bool:
    return str(unit.get("unit_type") or "") in FAITH_PURCHASABLE_CIVILIAN_UNITS


def _unit_position(row: dict[str, Any]) -> tuple[Any, Any]:
    return (row.get("x"), row.get("y"))


def _unit_strength_total(row: dict[str, Any]) -> float:
    return (_number(row.get("combat_strength")) or 0.0) + (
        _number(row.get("ranged_strength")) or 0.0
    )


def _is_unit_upgrade_candidate(before_unit: dict[str, Any], after_unit: dict[str, Any]) -> bool:
    before_type = str(before_unit.get("unit_type") or "")
    after_type = str(after_unit.get("unit_type") or "")
    civilian_types = {
        "UNIT_BUILDER",
        "UNIT_SETTLER",
        "UNIT_TRADER",
        "UNIT_MISSIONARY",
        "UNIT_APOSTLE",
        "UNIT_GREAT_PROPHET",
    }
    if _unit_position(before_unit) != _unit_position(after_unit):
        return False
    if before_type == after_type or before_type in civilian_types or after_type in civilian_types:
        return False
    if not before_type.startswith("UNIT_") or not after_type.startswith("UNIT_"):
        return False
    return _unit_strength_total(after_unit) > _unit_strength_total(before_unit)


def _research_option(
    research_civic: dict[str, Any],
    option_key: str,
    current_name: str,
    type_key: str,
) -> dict[str, Any]:
    for option in _as_list(research_civic.get(option_key)):
        if not isinstance(option, dict):
            continue
        if option.get("name") == current_name or option.get(type_key) == current_name:
            return option
    return {}


def _current_strategy_fact(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    kind: str,
    label: str,
    current_key: str,
    turns_key: str,
    option_key: str,
    type_key: str,
) -> dict[str, Any] | None:
    before_rc = _as_dict(before.get("research_civic"))
    after_rc = _as_dict(after.get("research_civic"))
    before_overview = _as_dict(before.get("overview"))
    after_overview = _as_dict(after.get("overview"))
    current = _meaningful_value(after_rc.get(current_key), after_overview.get(current_key))
    if current is None:
        return None
    current_text = str(current)
    option = _research_option(after_rc, option_key, current_text, type_key)
    turns = after_rc.get(turns_key)
    progress = option.get("progress_pct")
    subject_id = option.get(type_key)
    before_payload = {
        "name": _meaningful_value(
            before_rc.get(current_key), before_overview.get(current_key)
        ),
        "turns": before_rc.get(turns_key),
    }
    after_payload = {
        "name": current_text,
        "turns": turns,
        "progress_pct": progress,
        type_key: subject_id,
    }
    detail = f"{turns}回合" if turns not in {None, -1} else "回合数未知"
    if progress not in {None, ""}:
        detail = f"{detail}，进度{progress}%"
    return _fact(
        category="strategy",
        kind=kind,
        subject_id=subject_id,
        subject_name=current_text,
        metric=current_key,
        before=before_payload,
        after=after_payload,
        summary=f"{label}选择 {current_text}（{detail}）",
        importance="high",
        source="after_snapshot",
    )


def _completed_strategy_fact(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    kind: str,
    label: str,
    current_key: str,
    turns_key: str,
    option_key: str,
    type_key: str,
) -> dict[str, Any] | None:
    before_rc = _as_dict(before.get("research_civic"))
    after_rc = _as_dict(after.get("research_civic"))
    before_overview = _as_dict(before.get("overview"))
    after_overview = _as_dict(after.get("overview"))
    completed = _meaningful_value(
        before_rc.get(current_key), before_overview.get(current_key)
    )
    selected = _meaningful_value(after_rc.get(current_key), after_overview.get(current_key))
    if completed is None:
        return None
    completed_text = str(completed)
    if completed_text in {"None", "none", "null", ""} or completed_text == str(selected):
        return None
    turns = _number(before_rc.get(turns_key))
    completed_count_key = (
        "completed_tech_count"
        if current_key == "current_research"
        else "completed_civic_count"
    )
    before_completed_count = _number(before_rc.get(completed_count_key))
    after_completed_count = _number(after_rc.get(completed_count_key))
    count_increased = (
        before_completed_count is not None
        and after_completed_count is not None
        and after_completed_count > before_completed_count
    )
    if not count_increased and (turns is None or turns > 1):
        return None
    option = _research_option(before_rc, option_key, completed_text, type_key)
    selected_text = None if selected is None else str(selected)
    after_text = selected_text if selected_text not in {None, "None", "none", "null", ""} else None
    suffix = f"，随后选择 {after_text}" if after_text else "，等待后续选择"
    return _fact(
        category="strategy",
        kind=kind,
        subject_id=option.get(type_key),
        subject_name=completed_text,
        metric=current_key,
        before={
            "name": completed_text,
            "turns": before_rc.get(turns_key),
            "progress_pct": option.get("progress_pct"),
            type_key: option.get(type_key),
        },
        after={"current": after_text},
        summary=f"{label}完成 {completed_text}{suffix}",
        importance="high",
        source=(
            "before_snapshot+after_snapshot+completed_count"
            if count_increased
            else "before_snapshot+after_snapshot"
        ),
    )


def _option_by_type(rows: Any, type_key: str) -> dict[str, dict[str, Any]]:
    options: dict[str, dict[str, Any]] = {}
    for option in _as_list(rows):
        if not isinstance(option, dict):
            continue
        option_type = option.get(type_key)
        if option_type not in {None, ""}:
            options[str(option_type)] = option
    return options


def _boosted_strategy_facts(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    kind: str,
    label: str,
    option_key: str,
    type_key: str,
) -> list[dict[str, Any]]:
    before_rc = _as_dict(before.get("research_civic"))
    after_rc = _as_dict(after.get("research_civic"))
    before_options = _option_by_type(before_rc.get(option_key), type_key)
    after_options = _option_by_type(after_rc.get(option_key), type_key)
    facts: list[dict[str, Any]] = []
    for option_type in sorted(set(before_options) & set(after_options)):
        before_option = before_options[option_type]
        after_option = after_options[option_type]
        if bool(before_option.get("boosted")) or not bool(after_option.get("boosted")):
            continue
        name = _meaningful_value(after_option.get("name"), before_option.get("name"), option_type)
        boost_desc = _meaningful_value(
            after_option.get("boost_desc"), before_option.get("boost_desc")
        )
        before_progress = before_option.get("progress_pct")
        after_progress = after_option.get("progress_pct")
        progress = ""
        if before_progress not in {None, ""} or after_progress not in {None, ""}:
            progress = f"，进度 {before_progress} -> {after_progress}"
        facts.append(
            _fact(
                category="strategy",
                kind=kind,
                subject_id=option_type,
                subject_name=name,
                metric="boosted",
                before=before_option,
                after=after_option,
                delta={"boosted": True},
                summary=f"{label}触发尤里卡/鼓舞 {name}（{boost_desc}）{progress}",
                importance="high",
                source="research_civic_delta",
            )
        )
    return facts


def _parse_unimproved_resources(city: dict[str, Any]) -> dict[tuple[int, int], str]:
    resources: dict[tuple[int, int], str] = {}
    values = [str(value) for value in _as_list(city.get("unimproved_resources"))]
    index = 0
    while index < len(values):
        raw = values[index]
        if "@" not in raw:
            index += 1
            continue
        resource, coord = raw.split("@", 1)
        if "," in coord:
            x_text, y_text = coord.split(",", 1)
            next_index = index + 1
        else:
            x_text = coord
            y_text = values[index + 1] if index + 1 < len(values) else ""
            next_index = index + 2
        x = _number(x_text)
        y = _number(y_text)
        if x is not None and y is not None:
            resources[(int(x), int(y))] = resource
        index = next_index
    return resources


def _removed_unimproved_resource_at(
    before_cities: dict[str, dict[str, Any]],
    after_cities: dict[str, dict[str, Any]],
    x: Any,
    y: Any,
) -> tuple[str, str] | None:
    x_num = _number(x)
    y_num = _number(y)
    if x_num is None or y_num is None:
        return None
    pos = (int(x_num), int(y_num))
    for city_id in sorted(set(before_cities) & set(after_cities)):
        before_city = before_cities[city_id]
        after_city = after_cities[city_id]
        before_resources = _parse_unimproved_resources(before_city)
        after_resources = _parse_unimproved_resources(after_city)
        resource = before_resources.get(pos)
        if resource and pos not in after_resources:
            city_name = _entity_name(after_city, "name") or _entity_name(before_city, "name") or city_id
            return resource, city_name
    return None


def _changed_resource_facts(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    if before.get("resources") is None or after.get("resources") is None:
        return []
    before_resources = to_jsonable(before.get("resources"))
    after_resources = to_jsonable(after.get("resources"))
    if before_resources == after_resources:
        return []
    facts: list[dict[str, Any]] = []
    if isinstance(before_resources, dict) and isinstance(after_resources, dict):
        keys = sorted(set(before_resources) | set(after_resources))
        for key in keys:
            if before_resources.get(key) == after_resources.get(key):
                continue
            facts.append(
                _fact(
                    category="economy",
                    kind="resource_changed",
                    metric=str(key),
                    before=before_resources.get(key),
                    after=after_resources.get(key),
                    summary=f"资源 {key} 发生变化",
                    importance="medium",
                )
            )
    if facts:
        return facts
    return [
        _fact(
            category="economy",
            kind="resource_changed",
            metric="resources",
            before=before_resources,
            after=after_resources,
            summary="资源或库存状态发生变化",
            importance="medium",
        )
    ]


def extract_action_facts(
    before: dict[str, Any], after: dict[str, Any], delta: dict[str, Any]
) -> list[dict[str, Any]]:
    """Normalize one before/after transition into queryable action facts."""
    before_json = to_jsonable(before)
    after_json = to_jsonable(after)
    if not isinstance(before_json, dict) or not isinstance(after_json, dict):
        raise HumanDemoError("Action facts require dictionary snapshots")

    facts: list[dict[str, Any]] = []
    before_cities = _collection_by_id(before_json.get("cities"), ["city_id", "id", "name"])
    after_cities = _collection_by_id(after_json.get("cities"), ["city_id", "id", "name"])
    before_units = _collection_by_id(
        before_json.get("units"), ["unit_id", "id", "name", "unit_name"]
    )
    after_units = _collection_by_id(
        after_json.get("units"), ["unit_id", "id", "name", "unit_name"]
    )

    added_city_ids = sorted(set(after_cities) - set(before_cities))
    removed_unit_ids = sorted(set(before_units) - set(after_units))
    founded_city_by_unit: dict[str, str] = {}
    claimed_city_ids: set[str] = set()
    for unit_id in removed_unit_ids:
        unit = before_units[unit_id]
        unit_type = str(unit.get("unit_type") or "")
        unit_name = _entity_name(unit, "name", "unit_name", "unit_type") or ""
        if unit_type != "UNIT_SETTLER" and "开拓者" not in unit_name:
            continue
        for city_id in added_city_ids:
            if city_id in claimed_city_ids:
                continue
            city = after_cities[city_id]
            if city.get("x") == unit.get("x") and city.get("y") == unit.get("y"):
                founded_city_by_unit[unit_id] = city_id
                claimed_city_ids.add(city_id)
                break

    for city_id in added_city_ids:
        city = after_cities[city_id]
        name = _entity_name(city, "name") or city_id
        x = city.get("x")
        y = city.get("y")
        where = f" ({x},{y})" if x is not None and y is not None else ""
        facts.append(
            _fact(
                category="city",
                kind="city_added",
                subject_id=city_id,
                subject_name=name,
                before=None,
                after=city,
                summary=f"新增城市 {name}{where}",
                importance="high",
            )
        )
        founder_unit_id = next(
            (
                unit_id
                for unit_id, founded_city_id in founded_city_by_unit.items()
                if founded_city_id == city_id
            ),
            None,
        )
        if founder_unit_id is not None:
            founder = before_units[founder_unit_id]
            facts.append(
                _fact(
                    category="city",
                    kind="city_founded_by_settler",
                    subject_id=city_id,
                    subject_name=name,
                    metric="founder_unit",
                    before=founder,
                    after=city,
                    delta={"consumed_unit_id": founder_unit_id},
                    summary=f"开拓者在 ({x},{y}) 建立城市 {name}",
                    importance="high",
                    source="snapshot_delta",
                )
            )

    for city_id in sorted(set(before_cities) - set(after_cities)):
        city = before_cities[city_id]
        name = _entity_name(city, "name") or city_id
        facts.append(
            _fact(
                category="city",
                kind="city_removed",
                subject_id=city_id,
                subject_name=name,
                before=city,
                after=None,
                summary=f"城市 {name} 消失或失去控制",
                importance="high",
            )
        )

    for city_id in sorted(set(before_cities) & set(after_cities)):
        before_city = before_cities[city_id]
        after_city = after_cities[city_id]
        name = _entity_name(after_city, "name") or _entity_name(before_city, "name") or city_id
        for metric in [
            "population",
            "production_turns_left",
            "housing",
            "amenities",
            "food_surplus",
            "loyalty",
        ]:
            before_value = before_city.get(metric)
            after_value = after_city.get(metric)
            if before_value == after_value:
                continue
            facts.append(
                _fact(
                    category="city",
                    kind="city_changed",
                    subject_id=city_id,
                    subject_name=name,
                    metric=metric,
                    before=before_value,
                    after=after_value,
                    delta=_numeric_delta(before_value, after_value),
                    summary=f"城市 {name} 的 {metric} {before_value} -> {after_value}",
                    importance="medium",
                )
            )

    tech_completed = _completed_strategy_fact(
        before_json,
        after_json,
        kind="tech_completed",
        label="科技",
        current_key="current_research",
        turns_key="current_research_turns",
        option_key="available_techs",
        type_key="tech_type",
    )
    if tech_completed:
        facts.append(tech_completed)
    tech_fact = _current_strategy_fact(
        before_json,
        after_json,
        kind="tech_selected",
        label="科技",
        current_key="current_research",
        turns_key="current_research_turns",
        option_key="available_techs",
        type_key="tech_type",
    )
    if tech_fact:
        facts.append(tech_fact)
    facts.extend(
        _boosted_strategy_facts(
            before_json,
            after_json,
            kind="tech_boosted",
            label="科技",
            option_key="available_techs",
            type_key="tech_type",
        )
    )
    civic_completed = _completed_strategy_fact(
        before_json,
        after_json,
        kind="civic_completed",
        label="市政",
        current_key="current_civic",
        turns_key="current_civic_turns",
        option_key="available_civics",
        type_key="civic_type",
    )
    if civic_completed:
        facts.append(civic_completed)
    civic_fact = _current_strategy_fact(
        before_json,
        after_json,
        kind="civic_selected",
        label="市政",
        current_key="current_civic",
        turns_key="current_civic_turns",
        option_key="available_civics",
        type_key="civic_type",
    )
    if civic_fact:
        facts.append(civic_fact)
    facts.extend(
        _boosted_strategy_facts(
            before_json,
            after_json,
            kind="civic_boosted",
            label="市政",
            option_key="available_civics",
            type_key="civic_type",
        )
    )

    before_pantheon = _as_dict(before_json.get("pantheon_status"))
    after_pantheon = _as_dict(after_json.get("pantheon_status"))
    before_belief = _meaningful_value(
        before_pantheon.get("current_belief"),
        before_pantheon.get("current_belief_name"),
    )
    after_belief = _meaningful_value(
        after_pantheon.get("current_belief"),
        after_pantheon.get("current_belief_name"),
    )
    if after_belief is not None and before_belief != after_belief:
        belief_name = _meaningful_value(
            after_pantheon.get("current_belief_name"),
            after_pantheon.get("current_belief"),
        )
        facts.append(
            _fact(
                category="religion",
                kind="pantheon_selected",
                subject_id=after_pantheon.get("current_belief"),
                subject_name=belief_name,
                metric="current_belief",
                before=before_belief,
                after=after_belief,
                summary=f"万神殿选择 {belief_name}",
                importance="high",
                source="pantheon_status",
            )
        )
        if after_pantheon.get("current_belief") == "BELIEF_RELIGIOUS_SETTLEMENTS":
            for unit_id in sorted(set(after_units) - set(before_units)):
                unit = after_units[unit_id]
                unit_type = str(unit.get("unit_type") or "")
                unit_name = _entity_name(unit, "name", "unit_name", "unit_type") or unit_id
                if unit_type == "UNIT_SETTLER" or "开拓者" in unit_name:
                    facts.append(
                        _fact(
                            category="religion",
                            kind="religious_settlements_free_settler",
                            subject_id=unit_id,
                            subject_name=unit_name,
                            metric="free_unit",
                            before=None,
                            after=unit,
                            summary="宗教移民触发免费开拓者",
                            importance="high",
                            source="pantheon_status+unit_delta",
                        )
                    )

    for city_id, city in sorted(after_cities.items()):
        production = city.get("currently_building") or city.get("current_production")
        name = _entity_name(city, "name") or city_id
        turns_left = city.get("production_turns_left")
        before_city = before_cities.get(city_id, {})
        before_production = before_city.get("currently_building") or before_city.get(
            "current_production"
        )
        completion_observed = (
            before_production is not None
            and not _is_idle_production(before_production)
            and _production_completion_observed(
                before_production,
                before_city,
                city,
                before_units,
                after_units,
            )
        )
        if _is_idle_production(production):
            if before_production is not None and not _is_idle_production(before_production):
                facts.append(
                    _fact(
                        category="production",
                        kind=(
                            "production_completed"
                            if completion_observed
                            else "production_pending"
                        ),
                        subject_id=city_id,
                        subject_name=name,
                        metric="currently_building",
                        before={
                            "currently_building": before_production,
                            "turns_left": before_city.get("production_turns_left"),
                        },
                        after={"currently_building": production, "turns_left": turns_left},
                        summary=(
                            f"{name} 完成或结束 {before_production}，当前待选择生产"
                            if completion_observed
                            else f"{name} 当前待选择生产；未确认完成 {before_production}"
                        ),
                        importance="high",
                        source=(
                            "after_snapshot+completion_observed"
                            if completion_observed
                            else "after_snapshot+completion_unconfirmed"
                        ),
                    )
                )
            continue
        if completion_observed:
            facts.append(
                _fact(
                    category="production",
                    kind="production_completed",
                    subject_id=city_id,
                    subject_name=name,
                    metric="currently_building",
                    before={
                        "currently_building": before_production,
                        "turns_left": before_city.get("production_turns_left"),
                    },
                    after={"currently_building": production, "turns_left": turns_left},
                    summary=(
                        f"{name} 完成 {before_production}，"
                        f"随后生产 {production}（{turns_left}回合）"
                    ),
                    importance="high",
                    source="after_snapshot+completion_observed",
                )
            )
        facts.append(
            _fact(
                category="production",
                kind="production_selected",
                subject_id=city_id,
                subject_name=name,
                metric="currently_building",
                before={
                    "currently_building": before_production,
                    "turns_left": before_city.get("production_turns_left"),
                },
                after={"currently_building": production, "turns_left": turns_left},
                summary=f"{name} 生产 {production}（{turns_left}回合）",
                importance="high",
                source="after_snapshot",
            )
        )

    added_unit_ids = sorted(set(after_units) - set(before_units))
    before_overview = _as_dict(before_json.get("overview"))
    after_overview = _as_dict(after_json.get("overview"))
    before_gold = _number(before_overview.get("gold"))
    after_gold = _number(after_overview.get("gold"))
    before_faith = _number(before_overview.get("faith"))
    after_faith = _number(after_overview.get("faith"))
    before_turn = _number(before_overview.get("turn") or before_json.get("turn"))
    after_turn = _number(after_overview.get("turn") or after_json.get("turn"))
    gold_income = _number(
        before_overview.get("gold_per_turn")
        or before_overview.get("gold_income")
        or after_overview.get("gold_per_turn")
        or after_overview.get("gold_income")
        or 0
    )
    spend_estimate = None
    if before_gold is not None and after_gold is not None:
        turn_income = gold_income or 0.0
        if before_turn is not None and after_turn is not None and after_turn > before_turn:
            spend_estimate = before_gold + turn_income - after_gold
        else:
            spend_estimate = before_gold - after_gold
    if len(added_unit_ids) == 1 and spend_estimate is not None and spend_estimate > 0:
        unit_id = added_unit_ids[0]
        unit = after_units[unit_id]
        unit_type = str(unit.get("unit_type") or "")
        cost = _purchase_gold_cost(before_json, unit_type)
        if cost is not None and abs(spend_estimate - cost) <= max(1.0, cost * 0.05):
            name = _entity_name(unit, "name", "unit_name", "unit_type") or unit_id
            facts.append(
                _fact(
                    category="economy",
                    kind="unit_purchased",
                    subject_id=unit_id,
                    subject_name=name,
                    metric="gold",
                    before={"gold": before_gold, "gold_per_turn": gold_income},
                    after={"gold": after_gold, "unit": unit},
                    delta={"gold_spent": cost, "net_gold_delta": after_gold - before_gold},
                    summary=(
                        f"花费约 {cost:g} 金币购买{name}"
                        f"（金币 {before_gold:g} -> {after_gold:g}）"
                    ),
                    importance="high",
                    source="overview_gold_delta+unit_delta+production_options",
                )
            )

    faith_purchase_units = [
        unit_id
        for unit_id in added_unit_ids
        if _is_faith_purchasable_civilian_unit(after_units[unit_id])
    ]
    if (
        faith_purchase_units
        and before_faith is not None
        and after_faith is not None
        and after_faith < before_faith
    ):
        faith_income = _number(
            before_overview.get("faith_per_turn")
            or before_overview.get("faith_income")
            or after_overview.get("faith_per_turn")
            or after_overview.get("faith_income")
        )
        net_faith_delta = round(after_faith - before_faith, 1)
        if (
            faith_income is not None
            and before_turn is not None
            and after_turn is not None
            and after_turn > before_turn
        ):
            faith_spent = before_faith + (faith_income or 0.0) - after_faith
            spend_label = f"估算花费 {round(faith_spent, 1):g}"
            spend_delta = {"faith_spent_estimate": round(faith_spent, 1)}
        else:
            faith_spent = before_faith - after_faith
            spend_label = f"净消耗 {round(faith_spent, 1):g}"
            spend_delta = {"faith_spent_lower_bound": round(faith_spent, 1)}
        faith_spent = round(faith_spent, 1)
        purchased_units = [after_units[unit_id] for unit_id in faith_purchase_units]
        purchased_names = [
            _entity_name(unit, "name", "unit_name", "unit_type") or unit_id
            for unit_id, unit in zip(faith_purchase_units, purchased_units)
        ]
        facts.append(
            _fact(
                category="economy",
                kind="faith_civilian_units_purchased",
                subject_id=",".join(faith_purchase_units),
                subject_name="、".join(purchased_names),
                metric="faith",
                before={"faith": before_faith, "faith_per_turn_estimate": faith_income},
                after={"faith": after_faith, "units": purchased_units},
                delta={
                    **spend_delta,
                    "net_faith_delta": net_faith_delta,
                    "unit_count": len(purchased_units),
                    "unit_types": [
                        str(unit.get("unit_type") or "") for unit in purchased_units
                    ],
                },
                summary=(
                    f"使用信仰购买民用单位 {'、'.join(purchased_names)}"
                    f"（信仰 {before_faith:g} -> {after_faith:g}，"
                    f"{spend_label}）"
                ),
                importance="high",
                source="overview_faith_delta+unit_delta",
            )
        )

    upgraded_units: dict[str, tuple[str, dict[str, Any]]] = {}
    claimed_added_upgrade_units: set[str] = set()
    for before_unit_id in removed_unit_ids:
        before_unit = before_units[before_unit_id]
        for after_unit_id in added_unit_ids:
            if after_unit_id in claimed_added_upgrade_units:
                continue
            after_unit = after_units[after_unit_id]
            if not _is_unit_upgrade_candidate(before_unit, after_unit):
                continue
            before_name = (
                _entity_name(before_unit, "name", "unit_name", "unit_type")
                or before_unit_id
            )
            after_name = (
                _entity_name(after_unit, "name", "unit_name", "unit_type")
                or after_unit_id
            )
            gold_delta = None if before_gold is None or after_gold is None else after_gold - before_gold
            gold_spent = (
                round(spend_estimate, 1)
                if spend_estimate is not None and spend_estimate > 0
                else None
            )
            spend_text = f"花费约 {gold_spent:g} 金币" if gold_spent is not None else "花费金币"
            facts.append(
                _fact(
                    category="unit",
                    kind="unit_upgraded",
                    subject_id=after_unit_id,
                    subject_name=after_name,
                    metric="upgrade",
                    before=before_unit,
                    after=after_unit,
                    delta={
                        "from_unit_id": before_unit_id,
                        "gold_spent_estimate": gold_spent,
                        "net_gold_delta": gold_delta,
                    },
                    summary=f"{spend_text}将{before_name}升级为{after_name}",
                    importance="high",
                    source="unit_delta+gold_delta",
                )
            )
            upgraded_units[before_unit_id] = (after_unit_id, after_unit)
            claimed_added_upgrade_units.add(after_unit_id)
            break

    for unit_id in added_unit_ids:
        unit = after_units[unit_id]
        name = _entity_name(unit, "name", "unit_name", "unit_type") or unit_id
        facts.append(
            _fact(
                category="unit",
                kind="unit_added",
                subject_id=unit_id,
                subject_name=name,
                before=None,
                after=unit,
                summary=f"新增单位 {name}",
                importance="medium",
            )
        )

    for unit_id in removed_unit_ids:
        unit = before_units[unit_id]
        name = _entity_name(unit, "name", "unit_name", "unit_type") or unit_id
        founded_city_id = founded_city_by_unit.get(unit_id)
        founded_city = after_cities.get(founded_city_id, {}) if founded_city_id else {}
        founded_city_name = _entity_name(founded_city, "name") if founded_city else None
        upgrade = upgraded_units.get(unit_id)
        upgraded_name = (
            _entity_name(upgrade[1], "name", "unit_name", "unit_type") if upgrade else None
        )
        facts.append(
            _fact(
                category="unit",
                kind="unit_removed",
                subject_id=unit_id,
                subject_name=name,
                before=unit,
                after=None,
                summary=(
                    f"{name} 用于建立城市 {founded_city_name}"
                    if founded_city_name
                    else f"{name} 已升级为 {upgraded_name}"
                    if upgraded_name
                    else f"单位 {name} 消失或被消耗"
                ),
                importance="high" if founded_city_name or upgraded_name else "medium",
                source=(
                    "snapshot_delta+city_added"
                    if founded_city_name
                    else "snapshot_delta+unit_upgrade"
                    if upgraded_name
                    else "snapshot_delta"
                ),
            )
        )

    for unit_id in sorted(set(before_units) & set(after_units)):
        before_unit = before_units[unit_id]
        after_unit = after_units[unit_id]
        name = (
            _entity_name(after_unit, "name", "unit_name", "unit_type")
            or _entity_name(before_unit, "name", "unit_name", "unit_type")
            or unit_id
        )
        before_pos = [before_unit.get("x"), before_unit.get("y")]
        after_pos = [after_unit.get("x"), after_unit.get("y")]
        if before_pos != after_pos:
            facts.append(
                _fact(
                    category="unit",
                    kind="unit_moved",
                    subject_id=unit_id,
                    subject_name=name,
                    metric="position",
                    before=before_pos,
                    after=after_pos,
                    summary=f"{name} 从 ({before_pos[0]},{before_pos[1]}) 移动到 ({after_pos[0]},{after_pos[1]})",
                    importance="high",
                )
            )
        before_charges = before_unit.get("build_charges")
        after_charges = after_unit.get("build_charges")
        charge_delta = _numeric_delta(before_charges, after_charges)
        if charge_delta is not None and charge_delta < 0:
            facts.append(
                _fact(
                    category="builder",
                    kind="builder_charge_used",
                    subject_id=unit_id,
                    subject_name=name,
                    metric="build_charges",
                    before=before_charges,
                    after=after_charges,
                    delta=charge_delta,
                    summary=(
                        f"{name} 消耗 {abs(charge_delta)} 次建造次数"
                        f"（{before_charges} -> {after_charges}）"
                    ),
                    importance="high",
                )
            )
            improved_resource = _removed_unimproved_resource_at(
                before_cities,
                after_cities,
                after_unit.get("x"),
                after_unit.get("y"),
            )
            if improved_resource is not None:
                resource, city_name = improved_resource
                facts.append(
                    _fact(
                        category="builder",
                        kind="builder_resource_improved",
                        subject_id=unit_id,
                        subject_name=name,
                        metric="unimproved_resources",
                        before={
                            "resource": resource,
                            "x": after_unit.get("x"),
                            "y": after_unit.get("y"),
                            "city": city_name,
                            "build_charges": before_charges,
                        },
                        after={
                            "resource": resource,
                            "x": after_unit.get("x"),
                            "y": after_unit.get("y"),
                            "city": city_name,
                            "build_charges": after_charges,
                        },
                        delta={"build_charges": charge_delta},
                        summary=(
                            f"{name} 在 ({after_unit.get('x')},{after_unit.get('y')}) "
                            f"改良 {resource}（{city_name}）"
                        ),
                        importance="high",
                        source="snapshot_delta+city_unimproved_resources",
                    )
                )
        for metric in [
            "health",
            "hp",
            "moves_remaining",
            "movement",
            "experience",
            "level",
            "activity_type",
            "promotion_available",
        ]:
            before_value = before_unit.get(metric)
            after_value = after_unit.get(metric)
            if before_value == after_value:
                continue
            facts.append(
                _fact(
                    category="unit",
                    kind="unit_changed",
                    subject_id=unit_id,
                    subject_name=name,
                    metric=metric,
                    before=before_value,
                    after=after_value,
                    delta=_numeric_delta(before_value, after_value),
                    summary=f"{name} 的 {metric} {before_value} -> {after_value}",
                    importance="medium",
                )
            )

    overview_delta = delta.get("overview") if isinstance(delta, dict) else {}
    if isinstance(overview_delta, dict):
        for metric, label in OVERVIEW_FACT_LABELS.items():
            change = overview_delta.get(metric)
            if not isinstance(change, dict):
                continue
            facts.append(
                _fact(
                    category="overview",
                    kind="overview_metric_changed",
                    metric=metric,
                    before=change.get("before"),
                    after=change.get("after"),
                    delta=change.get("delta"),
                    summary=_overview_fact_summary(metric, label, change, after_json),
                    importance=_overview_fact_importance(metric),
                )
            )

    facts.extend(_changed_resource_facts(before_json, after_json))

    historic_delta = delta.get("historic_moments") if isinstance(delta, dict) else {}
    if isinstance(historic_delta, dict):
        after_moments = _collection_by_id(
            after_json.get("historic_moments"), ["moment_id", "id", "ID"]
        )
        for moment_id in historic_delta.get("added") or []:
            moment = after_moments.get(str(moment_id), {})
            score = moment.get("era_score")
            description = (
                moment.get("instance_description")
                or moment.get("description")
                or moment.get("name")
                or moment.get("moment_type")
                or moment_id
            )
            score_text = f"+{score}" if score not in {None, ""} else "+?"
            facts.append(
                _fact(
                    category="historic_moment",
                    kind="historic_moment_added",
                    subject_id=moment_id,
                    subject_name=moment.get("moment_type") or moment.get("name"),
                    metric="era_score",
                    before=None,
                    after=moment,
                    delta=score,
                    summary=f"历史时刻 {score_text}: {description}",
                    importance="high",
                    source="history_manager",
                )
            )

    policy_delta = delta.get("policies") if isinstance(delta, dict) else {}
    if isinstance(policy_delta, dict):
        for slot_key, change in (policy_delta.get("changed") or {}).items():
            if not isinstance(change, dict):
                continue
            before_slot = _as_dict(change.get("before"))
            after_slot = _as_dict(change.get("after"))
            slot_type = (
                after_slot.get("slot_type")
                or before_slot.get("slot_type")
                or f"slot {slot_key}"
            )
            before_policy = _meaningful_value(
                before_slot.get("current_policy_name"),
                before_slot.get("current_policy"),
            )
            after_policy = _meaningful_value(
                after_slot.get("current_policy_name"),
                after_slot.get("current_policy"),
            )
            facts.append(
                _fact(
                    category="policy",
                    kind="policy_changed",
                    subject_id=slot_key,
                    subject_name=slot_type,
                    metric="current_policy",
                    before=before_slot,
                    after=after_slot,
                    summary=f"政策槽 {slot_type} {before_policy or '空'} -> {after_policy or '空'}",
                    importance="high",
                )
            )

    risk = delta.get("risk") if isinstance(delta, dict) else {}
    if isinstance(risk, dict):
        for metric, label in [("notifications", "通知"), ("threats", "威胁")]:
            change = risk.get(metric)
            if isinstance(change, dict) and change.get("delta"):
                facts.append(
                    _fact(
                        category="risk",
                        kind="risk_changed",
                        metric=metric,
                        before=change.get("before_count"),
                        after=change.get("after_count"),
                        delta=change.get("delta"),
                        summary=f"{label}数量 {change.get('before_count')} -> {change.get('after_count')}",
                        importance="medium",
                    )
                )

    if delta.get("map_changed"):
        facts.append(
            _fact(
                category="map",
                kind="map_changed",
                metric="strategic_map",
                before="before_snapshot",
                after="after_snapshot",
                summary="战略地图或探索摘要发生变化",
                importance="low",
            )
        )

    for flag, category, label in [
        ("diplomacy_changed", "diplomacy", "外交状态发生变化"),
        ("victory_changed", "victory", "胜利进度发生变化"),
    ]:
        if delta.get(flag):
            facts.append(
                _fact(
                    category=category,
                    kind=flag,
                    metric=flag,
                    before=before_json.get(category),
                    after=after_json.get(category),
                    summary=label,
                    importance="medium",
                )
            )
    return facts


def build_state_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_json = to_jsonable(before)
    after_json = to_jsonable(after)
    if not isinstance(before_json, dict) or not isinstance(after_json, dict):
        raise HumanDemoError("State delta requires dictionary snapshots")

    before_turn = _value(before_json.get("overview"), "turn", before_json.get("turn"))
    after_turn = _value(after_json.get("overview"), "turn", after_json.get("turn"))
    return {
        "turn": {"before": before_turn, "after": after_turn},
        "overview": _overview_delta(before_json, after_json),
        "cities": _city_delta(before_json, after_json),
        "units": _unit_delta(before_json, after_json),
        "research_civic_changed": before_json.get("research_civic")
        != after_json.get("research_civic"),
        "production_changed": before_json.get("production") != after_json.get("production"),
        "policies": _policy_delta(before_json, after_json),
        "policies_changed": before_json.get("policies") != after_json.get("policies"),
        "resources_changed": _observed_field_changed(before_json, after_json, "resources"),
        "diplomacy_changed": _observed_field_changed(before_json, after_json, "diplomacy"),
        "victory_changed": _observed_field_changed(before_json, after_json, "victory"),
        "risk": {
        "notifications": _count_delta(before_json, after_json, "notifications"),
        "threats": _count_delta(before_json, after_json, "threats"),
        },
        "historic_moments": _historic_moments_delta(before_json, after_json),
        "map_changed": _observed_field_changed(before_json, after_json, "strategic_map"),
        "known_gap_count": {
            "before": len(_as_list(before_json.get("known_gaps"))),
            "after": len(_as_list(after_json.get("known_gaps"))),
        },
    }


def _change_label(change: dict[str, Any]) -> str:
    return f"{change.get('before')} -> {change.get('after')}"


def _city_name_from_change(city_id: str, changes: dict[str, Any]) -> str:
    name_change = changes.get("name") if isinstance(changes, dict) else None
    if isinstance(name_change, dict):
        return str(name_change.get("after") or name_change.get("before") or city_id)
    return city_id


def build_inference_facts(delta: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract deterministic facts for Codex to summarize in conversation."""
    facts: list[dict[str, Any]] = []
    units = delta.get("units") if isinstance(delta, dict) else {}
    if isinstance(units, dict):
        for unit_id, move in (units.get("moved") or {}).items():
            facts.append(
                {
                    "kind": "unit_moved",
                    "importance": "high",
                    "summary": (
                        f"单位 {unit_id} 从 {tuple(move.get('before') or [])} "
                        f"移动到 {tuple(move.get('after') or [])}"
                    ),
                    "evidence": move,
                }
            )
        for unit_id in units.get("added") or []:
            facts.append(
                {
                    "kind": "unit_added",
                    "importance": "medium",
                    "summary": f"新增单位 {unit_id}",
                    "evidence": {"unit_id": unit_id},
                }
            )
        for unit_id in units.get("removed") or []:
            facts.append(
                {
                    "kind": "unit_removed",
                    "importance": "medium",
                    "summary": f"单位 {unit_id} 消失或被消耗",
                    "evidence": {"unit_id": unit_id},
                }
            )

    cities = delta.get("cities") if isinstance(delta, dict) else {}
    if isinstance(cities, dict):
        for city_id in cities.get("added") or []:
            facts.append(
                {
                    "kind": "city_added",
                    "importance": "high",
                    "summary": f"新增城市 {city_id}",
                    "evidence": {"city_id": city_id},
                }
            )
        for city_id in cities.get("removed") or []:
            facts.append(
                {
                    "kind": "city_removed",
                    "importance": "high",
                    "summary": f"城市 {city_id} 消失或失去控制",
                    "evidence": {"city_id": city_id},
                }
            )
        for city_id, changes in (cities.get("changed") or {}).items():
            city_name = _city_name_from_change(str(city_id), changes)
            for field in ["current_production", "production"]:
                change = changes.get(field) if isinstance(changes, dict) else None
                if isinstance(change, dict):
                    facts.append(
                        {
                            "kind": "production_changed",
                            "importance": "high",
                            "summary": (
                                f"城市 {city_name} 的 {field} "
                                f"从 {change.get('before')} 变为 {change.get('after')}"
                            ),
                            "evidence": {"city": city_id, field: change},
                        }
                    )
            for field in ["population", "production_turns_left", "housing", "amenities"]:
                change = changes.get(field) if isinstance(changes, dict) else None
                if isinstance(change, dict):
                    facts.append(
                        {
                            "kind": f"city_{field}_changed",
                            "importance": "medium",
                            "summary": f"城市 {city_name} 的 {field} {_change_label(change)}",
                            "evidence": {"city": city_id, field: change},
                        }
                    )

    overview = delta.get("overview") if isinstance(delta, dict) else {}
    if isinstance(overview, dict):
        for key in [
            "science_yield",
            "culture_yield",
            "gold",
            "gold_per_turn",
            "faith",
            "era_score",
            "num_cities",
            "num_units",
        ]:
            change = overview.get(key)
            if isinstance(change, dict):
                importance = "medium" if key in {"era_score", "num_cities"} else "low"
                facts.append(
                    {
                        "kind": f"overview_{key}_changed",
                        "importance": importance,
                        "summary": f"{key} {_change_label(change)}",
                        "evidence": {key: change},
                    }
                )

    for key, label in [
        ("research_civic_changed", "科技或市政状态发生变化"),
        ("production_changed", "城市可生产项或生产状态发生变化"),
        ("resources_changed", "资源或库存状态发生变化"),
        ("diplomacy_changed", "外交状态发生变化"),
        ("victory_changed", "胜利进度发生变化"),
        ("map_changed", "战略地图或探索摘要发生变化"),
    ]:
        if delta.get(key):
            importance = "medium" if key != "map_changed" else "low"
            facts.append(
                {
                    "kind": key,
                    "importance": importance,
                    "summary": label,
                    "evidence": {key: True},
                }
            )

    risk = delta.get("risk") if isinstance(delta, dict) else {}
    if isinstance(risk, dict):
        for key in ["notifications", "threats"]:
            change = risk.get(key)
            if isinstance(change, dict) and change.get("delta"):
                facts.append(
                    {
                        "kind": f"{key}_count_changed",
                        "importance": "medium",
                        "summary": f"{key} 数量 {change.get('before_count')} -> {change.get('after_count')}",
                        "evidence": {key: change},
                    }
                )
    return facts


FACT_KIND_ORDER = {
    "historic_moment_added": 5,
    "pantheon_selected": 6,
    "religious_settlements_free_settler": 7,
    "city_added": 10,
    "city_founded_by_settler": 11,
    "unit_upgraded": 17,
    "unit_purchased": 18,
    "faith_civilian_units_purchased": 18,
    "production_completed": 19,
    "production_pending": 19,
    "production_selected": 20,
    "builder_charge_used": 25,
    "tech_completed": 28,
    "tech_boosted": 29,
    "tech_selected": 30,
    "civic_completed": 30,
    "civic_selected": 31,
    "civic_boosted": 32,
    "unit_moved": 40,
    "unit_added": 41,
    "unit_removed": 42,
    "unit_changed": 43,
    "overview_metric_changed": 50,
    "resource_changed": 60,
    "risk_changed": 80,
    "map_changed": 90,
}
FACT_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}
OVERVIEW_METRIC_ORDER = {
    "era_score": 0,
    "era_golden_threshold": 1,
    "science_yield": 2,
    "culture_yield": 3,
    "gold": 4,
    "gold_per_turn": 5,
    "gold_income": 6,
    "faith": 7,
    "num_cities": 8,
    "num_units": 9,
    "score": 10,
    "total_population": 11,
}


def _fact_sort_key(fact: dict[str, Any]) -> tuple[int, int, int, str]:
    kind = str(fact.get("kind") or "")
    metric = str(fact.get("metric") or "")
    importance = str(fact.get("importance") or "medium").lower()
    return (
        FACT_KIND_ORDER.get(kind, 70),
        OVERVIEW_METRIC_ORDER.get(metric, 99),
        FACT_IMPORTANCE_ORDER.get(importance, 1),
        str(fact.get("summary") or ""),
    )


def _fact_evidence(fact: dict[str, Any]) -> dict[str, Any]:
    if "evidence" in fact:
        evidence = fact.get("evidence")
    else:
        evidence = {
            "subject_id": fact.get("subject_id"),
            "subject_name": fact.get("subject_name"),
            "metric": fact.get("metric"),
            "before": fact.get("before"),
            "after": fact.get("after"),
            "delta": fact.get("delta"),
        }
        evidence = {key: value for key, value in evidence.items() if value is not None}
    return {
        "kind": fact.get("kind"),
        "category": fact.get("category"),
        "summary": fact.get("summary"),
        "evidence": evidence,
    }


def fact_counts_by_category(facts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fact in facts:
        category = str(fact.get("category") or "other")
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _overview_int(snapshot: dict[str, Any], key: str) -> int:
    overview = _as_dict(snapshot.get("overview"))
    value = overview.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _snapshot_cities(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for raw in _as_list(to_jsonable(snapshot.get("cities"))):
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def snapshot_quality_issues(
    snapshot: dict[str, Any], *, label: str = "snapshot"
) -> list[str]:
    """Return critical capture gaps that make a turn summary incomplete."""
    issues: list[str] = []
    expected_cities = _overview_int(snapshot, "num_cities")
    expected_units = _overview_int(snapshot, "num_units")
    cities = _snapshot_cities(snapshot)

    if expected_cities > 0 and not cities:
        issues.append(f"{label}.cities missing despite overview num_cities={expected_cities}")
    elif expected_cities > 0 and len(cities) < expected_cities:
        issues.append(
            f"{label}.cities incomplete: captured {len(cities)} of {expected_cities}"
        )

    for city in cities:
        if "currently_building" not in city and "current_production" not in city:
            city_name = city.get("name") or city.get("city_id") or "unknown city"
            issues.append(f"{label}.production missing current item for {city_name}")

    if expected_units > 0 and snapshot.get("units") is None:
        issues.append(f"{label}.units missing despite overview num_units={expected_units}")
    if snapshot.get("research_civic") is None:
        issues.append(f"{label}.research_civic missing")
    return issues


def apply_snapshot_quality_to_rule(
    rule: dict[str, Any],
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
) -> dict[str, Any]:
    issues = [
        *snapshot_quality_issues(before_snapshot, label="before"),
        *snapshot_quality_issues(after_snapshot, label="after"),
    ]
    if not issues:
        return rule

    adjusted = dict(rule)
    confidence = str(adjusted.get("confidence") or "low").lower()
    adjusted["confidence"] = "medium" if confidence == "high" else confidence
    if adjusted["confidence"] not in {"medium", "low"}:
        adjusted["confidence"] = "medium"
    adjusted["needs_review"] = True
    adjusted["capture_quality_issues"] = issues
    issue_text = "；".join(issues[:4])
    summary = str(adjusted.get("summary") or "")
    adjusted["summary"] = (
        f"采集缺口需复核：{issue_text}。"
        + (f" 原自动摘要：{summary}" if summary else "")
    )
    rationale = str(adjusted.get("rationale") or "")
    adjusted["rationale"] = (
        rationale
        + (" " if rationale else "")
        + "关键字段采集不完整，摘要不得标记为高置信。"
    )
    return adjusted


def build_rule_inference(
    delta: dict[str, Any], facts: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    facts = list(facts) if facts is not None else build_inference_facts(delta)
    facts = sorted(facts, key=_fact_sort_key)
    high = [fact for fact in facts if fact.get("importance") == "high"]
    medium = [fact for fact in facts if fact.get("importance") == "medium"]
    if high:
        confidence = "high"
    elif medium:
        confidence = "medium"
    elif facts:
        confidence = "low"
    else:
        confidence = "low"

    selected = facts[:8]
    if selected:
        summary = "；".join(str(fact["summary"]) for fact in selected if fact.get("summary"))
    else:
        summary = "没有从前后快照中识别出明确人工动作"
    evidence = [_fact_evidence(fact) for fact in selected[:6]]
    return {
        "summary": summary,
        "rationale": "由 before/after 结构化事实明细自动推断，等待 Codex 对话层压缩确认。",
        "confidence": confidence,
        "needs_review": confidence == "low",
        "facts": facts,
        "evidence": evidence,
        "fact_counts_by_category": fact_counts_by_category(facts),
    }


def _report_counts(conn: sqlite3.Connection, demo_id: str) -> dict[str, int]:
    return {
        table: _count_rows(conn, table, demo_id)
        for table in [
            "state_snapshots",
            "human_actions",
            "state_deltas",
            "action_facts",
            "tool_calls",
            "lua_exchanges",
            "manual_notes",
            "inference_audit",
        ]
    }


def render_report(db_path: Path) -> str:
    conn = open_db(db_path)
    try:
        session = conn.execute("SELECT * FROM demo_sessions LIMIT 1").fetchone()
        if session is None:
            raise HumanDemoError(f"No demo session found in {db_path}")
        demo_id = str(session["demo_id"])
        counts = _report_counts(conn, demo_id)
        rows = conn.execute(
            """
            SELECT a.*, d.delta_json
            FROM human_actions a
            LEFT JOIN state_deltas d
              ON d.before_snapshot_id = a.before_snapshot_id
             AND d.after_snapshot_id = a.after_snapshot_id
            WHERE a.demo_id = ?
            ORDER BY a.turn, a.created_at
            """,
            (demo_id,),
        ).fetchall()
        if _table_exists(conn, "action_facts"):
            fact_rows = conn.execute(
                """
                SELECT *
                FROM action_facts
                WHERE demo_id = ?
                ORDER BY turn, fact_id
                """,
                (demo_id,),
            ).fetchall()
        else:
            fact_rows = []
        notes = conn.execute(
            """
            SELECT *
            FROM manual_notes
            WHERE demo_id = ?
            ORDER BY turn, created_at
            """,
            (demo_id,),
        ).fetchall()
    finally:
        conn.close()

    action_rows = []
    for row in rows:
        delta = json_loads(row["delta_json"]) or {}
        overview = delta.get("overview") if isinstance(delta, dict) else {}
        overview_bits = []
        if isinstance(overview, dict):
            for key in ["num_cities", "num_units", "science_yield", "culture_yield", "gold"]:
                if key in overview:
                    item = overview[key]
                    overview_bits.append(
                        f"{html.escape(key)}: {html.escape(str(item.get('before')))} -> {html.escape(str(item.get('after')))}"
                    )
        action_rows.append(
            "<tr>"
            f"<td>T{html.escape(str(row['turn']))}</td>"
            f"<td>{html.escape(str(row['summary']))}</td>"
            f"<td>{html.escape(str(row['confidence']))}</td>"
            f"<td>{'是' if int(row['needs_review']) else '否'}</td>"
            f"<td>{html.escape(str(row['user_correction'] or ''))}</td>"
            f"<td>{html.escape(str(row['rationale']))}</td>"
            f"<td>{html.escape(', '.join(json_loads(row['tags_json']) or []))}</td>"
            f"<td>{'<br>'.join(overview_bits) if overview_bits else '无关键概览变化'}</td>"
            "</tr>"
        )
    structured_fact_rows = []
    for row in fact_rows:
        before = json_loads(row["before_json"])
        after = json_loads(row["after_json"])
        delta_value = json_loads(row["delta_json"])
        subject = row["subject_name"] or row["subject_id"] or ""
        values = []
        if before is not None or after is not None:
            values.append(
                f"{html.escape(short_text(before, 120))} -> {html.escape(short_text(after, 120))}"
            )
        if delta_value is not None:
            values.append(f"delta={html.escape(short_text(delta_value, 80))}")
        structured_fact_rows.append(
            "<tr>"
            f"<td>T{html.escape(str(row['turn']))}</td>"
            f"<td>{html.escape(str(row['category']))}</td>"
            f"<td>{html.escape(str(row['kind']))}</td>"
            f"<td>{html.escape(str(subject))}</td>"
            f"<td>{html.escape(str(row['metric'] or ''))}</td>"
            f"<td>{html.escape(str(row['summary']))}</td>"
            f"<td>{html.escape(str(row['importance']))}</td>"
            f"<td>{'<br>'.join(values) if values else ''}</td>"
            "</tr>"
        )
    low_conf_rows = [
        row
        for row in rows
        if str(row["confidence"]).lower() == "low" or int(row["needs_review"])
    ]
    low_conf_html = "".join(
        "<li>"
        f"T{html.escape(str(row['turn']))}: "
        f"{html.escape(str(row['summary']))} "
        f"({html.escape(str(row['confidence']))})"
        "</li>"
        for row in low_conf_rows
    )
    note_rows = "".join(
        "<tr>"
        f"<td>{html.escape('' if row['turn'] is None else 'T' + str(row['turn']))}</td>"
        f"<td>{html.escape(str(row['note']))}</td>"
        f"<td>{html.escape(str(row['created_at']))}</td>"
        "</tr>"
        for row in notes
    )

    count_cards = "".join(
        f"<div class=\"card\"><strong>{html.escape(key)}</strong><br>{value}</div>"
        for key, value in counts.items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Human Demo Report - {html.escape(demo_id)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 32px; color: #111827; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; }}
    .meta, .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 12px; background: #f9fafb; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; vertical-align: top; }}
    th {{ background: #f3f4f6; text-align: left; }}
    code {{ background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>人类操作录制报告</h1>
  <p>这是独立 SQLite 参考证据，不是 Observation 自动观测、候选 playbook 或资产合并。</p>
  <section class="meta">
    <div class="card"><strong>demo_id</strong><br><code>{html.escape(demo_id)}</code></div>
    <div class="card"><strong>save_name</strong><br>{html.escape(str(session['save_name']))}</div>
    <div class="card"><strong>status</strong><br>{html.escape(str(session['status']))}</div>
    <div class="card"><strong>schema</strong><br>{html.escape(str(session['schema_version']))}</div>
  </section>
  <h2>记录计数</h2>
  <section class="cards">{count_cards}</section>
  <h2>低置信 / 待复核回合</h2>
  <ul>{low_conf_html if low_conf_html else '<li>没有低置信或待复核回合。</li>'}</ul>
  <h2>人工回合记录</h2>
  <table>
    <tr><th>回合</th><th>动作摘要</th><th>置信度</th><th>待复核</th><th>你的纠正原文</th><th>理由/来源</th><th>标签</th><th>概览变化</th></tr>
    {''.join(action_rows) if action_rows else '<tr><td colspan="8">暂无人工动作记录。</td></tr>'}
  </table>
  <h2>结构化变化明细</h2>
  <table>
    <tr><th>回合</th><th>类别</th><th>类型</th><th>对象</th><th>指标</th><th>摘要</th><th>重要性</th><th>前后值</th></tr>
    {''.join(structured_fact_rows) if structured_fact_rows else '<tr><td colspan="8">暂无结构化变化明细。</td></tr>'}
  </table>
  <h2>阶段备注</h2>
  <table>
    <tr><th>回合</th><th>备注</th><th>时间</th></tr>
    {note_rows if note_rows else '<tr><td colspan="3">暂无阶段备注。</td></tr>'}
  </table>
</body>
</html>
"""


def write_report(db_path: Path, output_path: Path | None = None) -> Path:
    output_path = output_path or db_path.with_name("report.html")
    output_path.write_text(render_report(db_path), encoding="utf-8")
    return output_path

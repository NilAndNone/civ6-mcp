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


SCHEMA_VERSION = 2
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
        status: str = "manual",
    ) -> str:
        self.action_seq += 1
        self.delta_seq += 1
        action_id = f"human-action-{self.action_seq:04d}"
        delta_id = f"state-delta-{self.delta_seq:04d}"
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
        "faith",
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


def _count_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> dict[str, int]:
    before_count = len(_as_list(before.get(key)))
    after_count = len(_as_list(after.get(key)))
    return {
        "before_count": before_count,
        "after_count": after_count,
        "delta": after_count - before_count,
    }


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
        "resources_changed": before_json.get("resources") != after_json.get("resources"),
        "diplomacy_changed": before_json.get("diplomacy") != after_json.get("diplomacy"),
        "victory_changed": before_json.get("victory") != after_json.get("victory"),
        "risk": {
            "notifications": _count_delta(before_json, after_json, "notifications"),
            "threats": _count_delta(before_json, after_json, "threats"),
        },
        "map_changed": before_json.get("strategic_map") != after_json.get("strategic_map"),
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


def build_rule_inference(delta: dict[str, Any]) -> dict[str, Any]:
    facts = build_inference_facts(delta)
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

    selected = facts[:5]
    if selected:
        summary = "；".join(str(fact["summary"]) for fact in selected)
    else:
        summary = "没有从前后快照中识别出明确人工动作"
    evidence = [
        {
            "kind": fact.get("kind"),
            "summary": fact.get("summary"),
            "evidence": fact.get("evidence"),
        }
        for fact in selected[:3]
    ]
    return {
        "summary": summary,
        "rationale": "由 before/after 状态差分自动推断，等待 Codex 对话层压缩确认。",
        "confidence": confidence,
        "needs_review": confidence == "low",
        "facts": facts,
        "evidence": evidence,
    }


def _report_counts(conn: sqlite3.Connection, demo_id: str) -> dict[str, int]:
    return {
        table: _count_rows(conn, table, demo_id)
        for table in [
            "state_snapshots",
            "human_actions",
            "state_deltas",
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

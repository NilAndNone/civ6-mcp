"""SQLite-backed Observation episode artifact storage.

Each Observation episode owns one ``episode.db`` under its episode directory.  The
database stores both structured evidence rows and the complete artifact payloads
that used to be represented only as files.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = 1
DB_FILENAME = "episode.db"


JSONL_KINDS = {
    "raw/tool_calls.jsonl": "tool_calls",
    "raw/mcp.jsonl": "mcp_events",
    "raw/codex_outputs.jsonl": "codex_outputs",
    "derived/decision_atoms.jsonl": "decision_atoms",
    "raw/saves/save_index.jsonl": "saves",
}

REPORT_KINDS = {
    "derived/report_pack.json",
    "outcome/observation_report.html",
    "outcome/observation_report.draft.html",
    "outcome/agent_report.md",
    "outcome/agent_audit_report.html",
    "assets_snapshot/manifest.json",
    "derived/timeline.md",
    "outcome/human_notes.md",
    "assets_snapshot/active_assets.json",
}


class EpisodeStoreError(RuntimeError):
    """Raised when episode DB content cannot be read or written safely."""


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: int
    episode_id: str
    logical_path: str
    kind: str
    media_type: str
    encoding: str | None
    size_bytes: int
    sha256: str
    metadata: dict[str, Any]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def json_dumps(data: Any, *, indent: int | None = None) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)


def json_loads_object(text: str, *, path_hint: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise EpisodeStoreError(f"Expected JSON object in {path_hint}")
    return value


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def episode_db_path(episode_root: Path) -> Path:
    return episode_root / DB_FILENAME


def has_episode_db(episode_root: Path) -> bool:
    return episode_db_path(episode_root).exists()


def safe_logical_path(path: str | Path) -> str:
    value = Path(path).as_posix() if isinstance(path, Path) else str(path).replace("\\", "/")
    value = value.strip("/")
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise EpisodeStoreError(f"Unsafe episode artifact path: {path}")
    if value == DB_FILENAME or value.endswith(f"/{DB_FILENAME}"):
        raise EpisodeStoreError("episode.db is database storage, not an artifact payload")
    return value


def logical_path_for(episode_root: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(episode_root.resolve())
    except ValueError as exc:
        raise EpisodeStoreError(f"Path is outside episode root: {path}") from exc
    return safe_logical_path(rel)


def artifact_kind_for_path(logical_path: str) -> str:
    logical_path = safe_logical_path(logical_path)
    if logical_path == "header.json":
        return "header"
    if logical_path.startswith("raw/civ6_states/") and logical_path.endswith(".json"):
        return "state_snapshot"
    if logical_path.startswith("raw/saves/") and logical_path.endswith(".Civ6Save"):
        return "save_file"
    if logical_path in JSONL_KINDS:
        return JSONL_KINDS[logical_path]
    if logical_path == "derived/report_pack.json":
        return "report_pack"
    if logical_path.endswith(".html"):
        return "html_report"
    if logical_path.endswith(".md"):
        return "markdown"
    if logical_path.endswith(".json"):
        return "json"
    if logical_path.endswith(".jsonl"):
        return "jsonl"
    return "artifact"


def media_type_for_path(logical_path: str, *, is_binary: bool = False) -> str:
    if is_binary:
        return "application/octet-stream"
    if logical_path.endswith(".json"):
        return "application/json"
    if logical_path.endswith(".jsonl"):
        return "application/x-ndjson"
    if logical_path.endswith(".html"):
        return "text/html"
    if logical_path.endswith(".md"):
        return "text/markdown"
    return "text/plain"


def _json_or_none(data: Any) -> str | None:
    if data is None:
        return None
    return json_dumps(data)


def _object_from_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    value = json.loads(text)
    return value if isinstance(value, dict) else {}


class EpisodeStore:
    """Read/write access to a single episode's SQLite artifact store."""

    def __init__(
        self,
        episode_root: Path,
        episode_id: str | None = None,
        *,
        create: bool = True,
        reset: bool = False,
    ) -> None:
        self.episode_root = episode_root.resolve()
        self.episode_id = episode_id or self.episode_root.name
        self.db_path = episode_db_path(self.episode_root)
        if not create and not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        self.episode_root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self._init_schema()
        if reset:
            self.reset()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO episodes(episode_id, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (self.episode_id, now_iso(), now_iso()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR REPLACE INTO schema_meta(key, value)
            VALUES ('schema_version', '1');

            CREATE TABLE IF NOT EXISTS episodes(
                episode_id TEXT PRIMARY KEY,
                workflow TEXT,
                save_name TEXT,
                requested_turns INTEGER,
                start_turn INTEGER,
                final_turn INTEGER,
                strategy_profile TEXT,
                header_json TEXT,
                candidate_runtime_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts(
                artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                logical_path TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                media_type TEXT NOT NULL,
                encoding TEXT,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                content_text TEXT,
                content_blob BLOB,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(episode_id) REFERENCES episodes(episode_id)
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind);
            CREATE INDEX IF NOT EXISTS idx_artifacts_path ON artifacts(logical_path);

            CREATE TABLE IF NOT EXISTS tool_calls(
                episode_id TEXT NOT NULL,
                tool_call_id TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                turn INTEGER,
                tool TEXT,
                success INTEGER,
                ts_start TEXT,
                ts_end TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(episode_id, tool_call_id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS mcp_events(
                episode_id TEXT NOT NULL,
                call_id TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                context TEXT,
                success INTEGER,
                ts_start TEXT,
                ts_end TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(episode_id, call_id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS codex_outputs(
                output_id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                kind TEXT,
                turn INTEGER,
                ts TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS state_snapshots(
                episode_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                turn INTEGER,
                label TEXT,
                ts TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(episode_id, snapshot_id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS decision_atoms(
                episode_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                turn INTEGER,
                trigger TEXT,
                selected_action TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(episode_id, decision_id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS saves(
                episode_id TEXT NOT NULL,
                save_id TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                save_artifact_id INTEGER,
                turn INTEGER,
                label TEXT,
                event TEXT,
                decision_id TEXT,
                source_path TEXT,
                episode_path TEXT,
                size_bytes INTEGER,
                sha256 TEXT,
                ts TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(episode_id, save_id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id),
                FOREIGN KEY(save_artifact_id) REFERENCES artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS reports(
                episode_id TEXT NOT NULL,
                logical_path TEXT NOT NULL,
                artifact_id INTEGER NOT NULL,
                report_type TEXT NOT NULL,
                generated_at TEXT,
                payload_json TEXT,
                PRIMARY KEY(episode_id, logical_path),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
            );
            """
        )
        self.conn.commit()

    def reset(self) -> None:
        self.conn.executescript(
            """
            DELETE FROM reports;
            DELETE FROM saves;
            DELETE FROM decision_atoms;
            DELETE FROM state_snapshots;
            DELETE FROM codex_outputs;
            DELETE FROM mcp_events;
            DELETE FROM tool_calls;
            DELETE FROM artifacts;
            DELETE FROM episodes;
            """
        )
        self.conn.commit()

    def _artifact_id(self, logical_path: str) -> int | None:
        row = self.conn.execute(
            "SELECT artifact_id FROM artifacts WHERE logical_path = ?",
            (safe_logical_path(logical_path),),
        ).fetchone()
        return int(row["artifact_id"]) if row else None

    def has_artifact(self, logical_path: str) -> bool:
        return self._artifact_id(logical_path) is not None

    def put_episode_header(
        self,
        header: dict[str, Any],
        *,
        workflow: str | None = None,
        save_name: str | None = None,
        requested_turns: int | None = None,
        start_turn: int | None = None,
        final_turn: int | None = None,
        strategy_profile: str | None = None,
    ) -> int:
        artifact_id = self.put_json_artifact("header.json", header, kind="header")
        self.conn.execute(
            """
            INSERT INTO episodes(
                episode_id, workflow, save_name, requested_turns, start_turn, final_turn,
                strategy_profile, header_json, candidate_runtime_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET
                workflow = COALESCE(excluded.workflow, episodes.workflow),
                save_name = COALESCE(excluded.save_name, episodes.save_name),
                requested_turns = COALESCE(excluded.requested_turns, episodes.requested_turns),
                start_turn = COALESCE(excluded.start_turn, episodes.start_turn),
                final_turn = COALESCE(excluded.final_turn, episodes.final_turn),
                strategy_profile = COALESCE(excluded.strategy_profile, episodes.strategy_profile),
                header_json = excluded.header_json,
                candidate_runtime_json = excluded.candidate_runtime_json,
                updated_at = excluded.updated_at
            """,
            (
                self.episode_id,
                workflow,
                save_name or header.get("save_name"),
                requested_turns if requested_turns is not None else header.get("requested_turns"),
                start_turn,
                final_turn,
                strategy_profile or header.get("strategy_profile"),
                json_dumps(header),
                _json_or_none(header.get("candidate_runtime")),
                now_iso(),
                now_iso(),
            ),
        )
        self.conn.commit()
        return artifact_id

    def update_episode_run(
        self,
        *,
        save_name: str | None = None,
        requested_turns: int | None = None,
        start_turn: int | None = None,
        final_turn: int | None = None,
        strategy_profile: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE episodes SET
                save_name = COALESCE(?, save_name),
                requested_turns = COALESCE(?, requested_turns),
                start_turn = COALESCE(?, start_turn),
                final_turn = COALESCE(?, final_turn),
                strategy_profile = COALESCE(?, strategy_profile),
                updated_at = ?
            WHERE episode_id = ?
            """,
            (
                save_name,
                requested_turns,
                start_turn,
                final_turn,
                strategy_profile,
                now_iso(),
                self.episode_id,
            ),
        )
        self.conn.commit()

    def put_text_artifact(
        self,
        logical_path: str,
        text: str,
        *,
        kind: str | None = None,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        payload = text.encode("utf-8")
        artifact_id = self._put_artifact_payload(
            logical_path,
            kind=kind or artifact_kind_for_path(logical_path),
            media_type=media_type or media_type_for_path(logical_path),
            encoding="utf-8",
            size_bytes=len(payload),
            sha256=sha256_bytes(payload),
            content_text=text,
            content_blob=None,
            metadata=metadata,
        )
        if logical_path in REPORT_KINDS:
            self._upsert_report(logical_path, artifact_id, None)
        return artifact_id

    def put_json_artifact(
        self,
        logical_path: str,
        data: Any,
        *,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
        indent: int | None = 2,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        text = json_dumps(data, indent=indent)
        artifact_id = self.put_text_artifact(
            logical_path,
            text,
            kind=kind or artifact_kind_for_path(logical_path),
            media_type="application/json",
            metadata=metadata,
        )
        if logical_path.startswith("raw/civ6_states/") and isinstance(data, dict):
            self._upsert_state_snapshot(logical_path, data, artifact_id)
        if logical_path in REPORT_KINDS:
            self._upsert_report(logical_path, artifact_id, data if isinstance(data, dict) else None)
        return artifact_id

    def put_binary_artifact(
        self,
        logical_path: str,
        payload: bytes,
        *,
        kind: str | None = None,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        return self._put_artifact_payload(
            logical_path,
            kind=kind or artifact_kind_for_path(logical_path),
            media_type=media_type or media_type_for_path(logical_path, is_binary=True),
            encoding=None,
            size_bytes=len(payload),
            sha256=sha256_bytes(payload),
            content_text=None,
            content_blob=payload,
            metadata=metadata,
        )

    def put_file_artifact(
        self,
        logical_path: str,
        source_path: Path,
        *,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        artifact_kind = kind or artifact_kind_for_path(logical_path)
        suffix = source_path.suffix.lower()
        if suffix in {".json", ".jsonl", ".html", ".md", ".txt"}:
            text = source_path.read_text(encoding="utf-8")
            artifact_id = self.put_text_artifact(
                logical_path,
                text,
                kind=artifact_kind,
                media_type=media_type_for_path(logical_path),
                metadata=metadata,
            )
            self._index_text_artifact(logical_path, text, artifact_id, artifact_kind)
            return artifact_id
        return self.put_binary_artifact(
            logical_path,
            source_path.read_bytes(),
            kind=artifact_kind,
            metadata=metadata,
        )

    def _put_artifact_payload(
        self,
        logical_path: str,
        *,
        kind: str,
        media_type: str,
        encoding: str | None,
        size_bytes: int,
        sha256: str,
        content_text: str | None,
        content_blob: bytes | None,
        metadata: dict[str, Any] | None,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        existing = self._artifact_id(logical_path)
        ts = now_iso()
        if existing is None:
            cur = self.conn.execute(
                """
                INSERT INTO artifacts(
                    episode_id, logical_path, kind, media_type, encoding, size_bytes,
                    sha256, content_text, content_blob, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.episode_id,
                    logical_path,
                    kind,
                    media_type,
                    encoding,
                    size_bytes,
                    sha256,
                    content_text,
                    content_blob,
                    _json_or_none(metadata),
                    ts,
                    ts,
                ),
            )
            artifact_id = int(cur.lastrowid)
        else:
            self.conn.execute(
                """
                UPDATE artifacts SET
                    kind = ?, media_type = ?, encoding = ?, size_bytes = ?, sha256 = ?,
                    content_text = ?, content_blob = ?, metadata_json = ?, updated_at = ?
                WHERE artifact_id = ?
                """,
                (
                    kind,
                    media_type,
                    encoding,
                    size_bytes,
                    sha256,
                    content_text,
                    content_blob,
                    _json_or_none(metadata),
                    ts,
                    existing,
                ),
            )
            artifact_id = existing
        self.conn.commit()
        return artifact_id

    def append_jsonl(
        self,
        logical_path: str,
        row: dict[str, Any],
        *,
        kind: str | None = None,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        line = json_dumps(row) + "\n"
        old = self.read_text(logical_path, default="")
        artifact_id = self.put_text_artifact(
            logical_path,
            old + line,
            kind=kind or artifact_kind_for_path(logical_path),
            media_type="application/x-ndjson",
        )
        self._index_jsonl_row(logical_path, row, artifact_id)
        return artifact_id

    def replace_jsonl(
        self,
        logical_path: str,
        rows: Iterable[dict[str, Any]],
        *,
        kind: str | None = None,
    ) -> int:
        logical_path = safe_logical_path(logical_path)
        rows = list(rows)
        artifact_id = self.put_text_artifact(
            logical_path,
            "".join(json_dumps(row) + "\n" for row in rows),
            kind=kind or artifact_kind_for_path(logical_path),
            media_type="application/x-ndjson",
        )
        self._delete_structured_for(logical_path)
        for row in rows:
            self._index_jsonl_row(logical_path, row, artifact_id)
        return artifact_id

    def read_text(self, logical_path: str, *, default: str | None = None) -> str:
        row = self.conn.execute(
            "SELECT content_text FROM artifacts WHERE logical_path = ?",
            (safe_logical_path(logical_path),),
        ).fetchone()
        if row is None:
            if default is not None:
                return default
            raise FileNotFoundError(logical_path)
        return str(row["content_text"] or "")

    def read_bytes(self, logical_path: str) -> bytes:
        row = self.conn.execute(
            "SELECT content_blob, content_text, encoding FROM artifacts WHERE logical_path = ?",
            (safe_logical_path(logical_path),),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(logical_path)
        blob = row["content_blob"]
        if blob is not None:
            return bytes(blob)
        return str(row["content_text"] or "").encode(row["encoding"] or "utf-8")

    def read_json(self, logical_path: str) -> dict[str, Any]:
        return json_loads_object(self.read_text(logical_path), path_hint=logical_path)

    def read_jsonl(self, logical_path: str) -> list[dict[str, Any]]:
        text = self.read_text(logical_path, default="")
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise EpisodeStoreError(f"Expected JSON object in {logical_path}:{line_no}")
            rows.append(value)
        return rows

    def state_rows(self) -> list[tuple[str, dict[str, Any]]]:
        rows = self.conn.execute(
            """
            SELECT a.logical_path, s.payload_json
            FROM state_snapshots s
            JOIN artifacts a ON a.artifact_id = s.artifact_id
            WHERE s.episode_id = ?
            ORDER BY s.turn, s.snapshot_id, a.logical_path
            """,
            (self.episode_id,),
        ).fetchall()
        if rows:
            return [(str(row["logical_path"]), json.loads(row["payload_json"])) for row in rows]
        return [
            (artifact.logical_path, self.read_json(artifact.logical_path))
            for artifact in self.artifacts(prefix="raw/civ6_states/")
            if artifact.logical_path.endswith(".json")
        ]

    def artifacts(self, *, prefix: str | None = None) -> list[ArtifactRecord]:
        sql = "SELECT * FROM artifacts WHERE episode_id = ?"
        params: list[Any] = [self.episode_id]
        if prefix is not None:
            sql += " AND logical_path LIKE ?"
            params.append(safe_logical_path(prefix) + "%")
        sql += " ORDER BY logical_path"
        rows = self.conn.execute(sql, params).fetchall()
        return [
            ArtifactRecord(
                artifact_id=int(row["artifact_id"]),
                episode_id=str(row["episode_id"]),
                logical_path=str(row["logical_path"]),
                kind=str(row["kind"]),
                media_type=str(row["media_type"]),
                encoding=row["encoding"],
                size_bytes=int(row["size_bytes"]),
                sha256=str(row["sha256"]),
                metadata=_object_from_json(row["metadata_json"]),
            )
            for row in rows
        ]

    def artifact_ref(self, logical_path: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT artifact_id, logical_path, kind, sha256, size_bytes
            FROM artifacts
            WHERE logical_path = ?
            """,
            (safe_logical_path(logical_path),),
        ).fetchone()
        if row is None:
            return None
        return {
            "storage_backend": "sqlite",
            "artifact_id": int(row["artifact_id"]),
            "path": str(row["logical_path"]),
            "kind": str(row["kind"]),
            "sha256": str(row["sha256"]),
            "size_bytes": int(row["size_bytes"]),
        }

    def manifest_file_rows(
        self,
        *,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        excluded = {safe_logical_path(item) for item in (exclude or set())}
        return [
            {
                "path": artifact.logical_path,
                "artifact_id": artifact.artifact_id,
                "storage_backend": "sqlite",
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
            }
            for artifact in self.artifacts()
            if artifact.logical_path not in excluded
        ]

    def hash_logical_paths(self, logical_paths: Iterable[str]) -> dict[str, Any]:
        rows = []
        h = hashlib.sha256()
        for logical_path in sorted({safe_logical_path(path) for path in logical_paths}):
            ref = self.artifact_ref(logical_path)
            if ref is None:
                continue
            rows.append(
                {
                    "path": logical_path,
                    "artifact_id": ref["artifact_id"],
                    "storage_backend": "sqlite",
                    "sha256": ref["sha256"],
                    "size_bytes": ref["size_bytes"],
                }
            )
            h.update(logical_path.encode("utf-8"))
            h.update(b"\0")
            h.update(str(ref["sha256"]).encode("ascii"))
            h.update(b"\0")
        return {"sha256": h.hexdigest(), "files": rows}

    def export_artifact(self, logical_path: str) -> Path:
        logical_path = safe_logical_path(logical_path)
        destination = self.episode_root / Path(logical_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        row = self.conn.execute(
            """
            SELECT content_text, content_blob, encoding
            FROM artifacts
            WHERE logical_path = ?
            """,
            (logical_path,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(logical_path)
        if row["content_blob"] is not None:
            destination.write_bytes(bytes(row["content_blob"]))
        else:
            destination.write_text(str(row["content_text"] or ""), encoding=row["encoding"] or "utf-8")
        return destination

    def export_legacy_tree(self) -> list[Path]:
        return [self.export_artifact(artifact.logical_path) for artifact in self.artifacts()]

    def import_legacy_tree(self, *, reset: bool = True) -> None:
        if reset:
            self.reset()
            self.conn.execute(
                """
                INSERT OR IGNORE INTO episodes(episode_id, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (self.episode_id, now_iso(), now_iso()),
            )
            self.conn.commit()
        paths = sorted(
            path
            for path in self.episode_root.rglob("*")
            if path.is_file() and path.name != DB_FILENAME
        )
        for path in paths:
            logical_path = logical_path_for(self.episode_root, path)
            self.put_file_artifact(logical_path, path)

    def _index_text_artifact(
        self,
        logical_path: str,
        text: str,
        artifact_id: int,
        kind: str,
    ) -> None:
        if logical_path.endswith(".json"):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return
            if not isinstance(value, dict):
                return
            if logical_path == "header.json":
                self.put_episode_header(value)
            elif logical_path.startswith("raw/civ6_states/"):
                self._upsert_state_snapshot(logical_path, value, artifact_id)
            elif logical_path in REPORT_KINDS:
                self._upsert_report(logical_path, artifact_id, value)
        elif logical_path.endswith(".jsonl"):
            try:
                rows = self.read_jsonl(logical_path)
            except Exception:
                return
            self._delete_structured_for(logical_path)
            for row in rows:
                self._index_jsonl_row(logical_path, row, artifact_id)
        elif logical_path in REPORT_KINDS:
            self._upsert_report(logical_path, artifact_id, None)

    def _delete_structured_for(self, logical_path: str) -> None:
        if logical_path == "raw/tool_calls.jsonl":
            self.conn.execute("DELETE FROM tool_calls WHERE episode_id = ?", (self.episode_id,))
        elif logical_path == "raw/mcp.jsonl":
            self.conn.execute("DELETE FROM mcp_events WHERE episode_id = ?", (self.episode_id,))
        elif logical_path == "raw/codex_outputs.jsonl":
            self.conn.execute("DELETE FROM codex_outputs WHERE episode_id = ?", (self.episode_id,))
        elif logical_path == "derived/decision_atoms.jsonl":
            self.conn.execute("DELETE FROM decision_atoms WHERE episode_id = ?", (self.episode_id,))
        elif logical_path == "raw/saves/save_index.jsonl":
            self.conn.execute("DELETE FROM saves WHERE episode_id = ?", (self.episode_id,))
        self.conn.commit()

    def _index_jsonl_row(self, logical_path: str, row: dict[str, Any], artifact_id: int) -> None:
        if logical_path == "raw/tool_calls.jsonl":
            self._upsert_tool_call(row, artifact_id)
        elif logical_path == "raw/mcp.jsonl":
            self._upsert_mcp_event(row, artifact_id)
        elif logical_path == "raw/codex_outputs.jsonl":
            self._insert_codex_output(row, artifact_id)
        elif logical_path == "derived/decision_atoms.jsonl":
            self._upsert_decision_atom(row, artifact_id)
        elif logical_path == "raw/saves/save_index.jsonl":
            self._upsert_save(row, artifact_id)
        self.conn.commit()

    def _upsert_tool_call(self, row: dict[str, Any], artifact_id: int) -> None:
        call_id = str(row.get("tool_call_id") or f"tool-row-{sha256_bytes(json_dumps(row).encode())[:12]}")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tool_calls(
                episode_id, tool_call_id, artifact_id, turn, tool, success,
                ts_start, ts_end, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                call_id,
                artifact_id,
                row.get("turn"),
                row.get("tool"),
                _bool_to_int(row.get("success")),
                row.get("ts_start"),
                row.get("ts_end"),
                json_dumps(row),
            ),
        )

    def _upsert_mcp_event(self, row: dict[str, Any], artifact_id: int) -> None:
        call_id = str(row.get("call_id") or f"mcp-row-{sha256_bytes(json_dumps(row).encode())[:12]}")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO mcp_events(
                episode_id, call_id, artifact_id, context, success,
                ts_start, ts_end, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                call_id,
                artifact_id,
                row.get("context"),
                _bool_to_int(row.get("success")),
                row.get("ts_start"),
                row.get("ts_end"),
                json_dumps(row),
            ),
        )

    def _insert_codex_output(self, row: dict[str, Any], artifact_id: int) -> None:
        self.conn.execute(
            """
            INSERT INTO codex_outputs(episode_id, artifact_id, kind, turn, ts, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                artifact_id,
                row.get("kind"),
                row.get("turn"),
                row.get("ts"),
                json_dumps(row),
            ),
        )

    def _upsert_state_snapshot(
        self,
        logical_path: str,
        row: dict[str, Any],
        artifact_id: int,
    ) -> None:
        snapshot_id = str(row.get("snapshot_id") or Path(logical_path).stem)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO state_snapshots(
                episode_id, snapshot_id, artifact_id, turn, label, ts, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                snapshot_id,
                artifact_id,
                row.get("turn"),
                row.get("label"),
                row.get("ts"),
                json_dumps(row),
            ),
        )
        self.conn.commit()

    def _upsert_decision_atom(self, row: dict[str, Any], artifact_id: int) -> None:
        decision_id = str(row.get("decision_id") or f"decision-row-{sha256_bytes(json_dumps(row).encode())[:12]}")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO decision_atoms(
                episode_id, decision_id, artifact_id, turn, trigger, selected_action, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                decision_id,
                artifact_id,
                row.get("turn"),
                row.get("trigger"),
                row.get("selected_action"),
                json_dumps(row),
            ),
        )

    def _upsert_save(self, row: dict[str, Any], artifact_id: int) -> None:
        save_id = str(row.get("save_id") or f"save-row-{sha256_bytes(json_dumps(row).encode())[:12]}")
        save_artifact_id = row.get("save_artifact_id")
        if save_artifact_id is None:
            episode_path = row.get("episode_path")
            if episode_path:
                try:
                    logical_path = logical_path_for(self.episode_root, Path(str(episode_path)))
                except EpisodeStoreError:
                    logical_path = "raw/saves/" + Path(str(episode_path)).name
                save_artifact_id = self._artifact_id(logical_path)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO saves(
                episode_id, save_id, artifact_id, save_artifact_id, turn, label, event,
                decision_id, source_path, episode_path, size_bytes, sha256, ts, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                save_id,
                artifact_id,
                save_artifact_id,
                row.get("turn"),
                row.get("label"),
                row.get("event"),
                row.get("decision_id"),
                row.get("source_path"),
                row.get("episode_path"),
                row.get("size_bytes"),
                row.get("sha256"),
                row.get("ts"),
                json_dumps(row),
            ),
        )

    def _upsert_report(
        self,
        logical_path: str,
        artifact_id: int,
        payload: dict[str, Any] | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO reports(
                episode_id, logical_path, artifact_id, report_type, generated_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.episode_id,
                logical_path,
                artifact_id,
                artifact_kind_for_path(logical_path),
                now_iso(),
                _json_or_none(payload),
            ),
        )
        self.conn.commit()


def _bool_to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    return None


class EpisodeReader:
    """SQLite-first reader with file-tree fallback for old episodes."""

    def __init__(self, episode_root: Path) -> None:
        self.episode_root = episode_root.resolve()
        self.episode_id = self.episode_root.name
        self.store: EpisodeStore | None = None
        if has_episode_db(self.episode_root):
            self.store = EpisodeStore(self.episode_root, create=False)

    @property
    def backend(self) -> str:
        return "sqlite" if self.store is not None else "files"

    def has_artifact(self, logical_path: str) -> bool:
        logical_path = safe_logical_path(logical_path)
        if self.store is not None:
            return self.store.has_artifact(logical_path)
        return (self.episode_root / Path(logical_path)).exists()

    def artifact_ref(self, logical_path: str) -> dict[str, Any] | None:
        logical_path = safe_logical_path(logical_path)
        if self.store is not None:
            return self.store.artifact_ref(logical_path)
        path = self.episode_root / Path(logical_path)
        if not path.exists() or not path.is_file():
            return None
        data = path.read_bytes()
        return {
            "storage_backend": "files",
            "path": logical_path,
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
        }

    def read_text(self, logical_path: str) -> str:
        logical_path = safe_logical_path(logical_path)
        if self.store is not None and self.store.has_artifact(logical_path):
            return self.store.read_text(logical_path)
        return (self.episode_root / Path(logical_path)).read_text(encoding="utf-8-sig")

    def read_bytes(self, logical_path: str) -> bytes:
        logical_path = safe_logical_path(logical_path)
        if self.store is not None and self.store.has_artifact(logical_path):
            return self.store.read_bytes(logical_path)
        return (self.episode_root / Path(logical_path)).read_bytes()

    def read_json(self, logical_path: str) -> dict[str, Any]:
        if self.store is not None and self.store.has_artifact(logical_path):
            return self.store.read_json(logical_path)
        return json_loads_object(self.read_text(logical_path), path_hint=logical_path)

    def read_jsonl(self, logical_path: str) -> list[dict[str, Any]]:
        logical_path = safe_logical_path(logical_path)
        if self.store is not None and self.store.has_artifact(logical_path):
            return self.store.read_jsonl(logical_path)
        path = self.episode_root / Path(logical_path)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise EpisodeStoreError(f"Expected JSON object in {logical_path}:{line_no}")
            rows.append(value)
        return rows

    def state_rows(self) -> list[tuple[str, dict[str, Any]]]:
        if self.store is not None:
            return self.store.state_rows()
        state_dir = self.episode_root / "raw" / "civ6_states"
        rows: list[tuple[str, dict[str, Any]]] = []
        for path in sorted(state_dir.glob("*.json")):
            logical_path = logical_path_for(self.episode_root, path)
            rows.append((logical_path, json_loads_object(path.read_text(encoding="utf-8"), path_hint=logical_path)))
        return rows

    def logical_paths(self, *, prefix: str | None = None) -> list[str]:
        if self.store is not None:
            return [artifact.logical_path for artifact in self.store.artifacts(prefix=prefix)]
        root = self.episode_root / Path(prefix or "")
        if not root.exists():
            return []
        if root.is_file():
            return [safe_logical_path(prefix or root.name)]
        return [
            logical_path_for(self.episode_root, path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]

    def hash_logical_paths(self, logical_paths: Iterable[str]) -> dict[str, Any]:
        if self.store is not None:
            return self.store.hash_logical_paths(logical_paths)
        rows = []
        h = hashlib.sha256()
        for logical_path in sorted({safe_logical_path(path) for path in logical_paths}):
            path = self.episode_root / Path(logical_path)
            if not path.exists() or not path.is_file():
                continue
            digest = sha256_bytes(path.read_bytes())
            rows.append(
                {
                    "path": logical_path,
                    "storage_backend": "files",
                    "sha256": digest,
                    "size_bytes": path.stat().st_size,
                }
            )
            h.update(logical_path.encode("utf-8"))
            h.update(b"\0")
            h.update(digest.encode("ascii"))
            h.update(b"\0")
        return {"sha256": h.hexdigest(), "files": rows}


def reader_for_path(path: Path) -> tuple[EpisodeReader, str] | None:
    resolved = path.resolve()
    parts = resolved.parts
    if "episodes" not in parts:
        return None
    index = len(parts) - 1 - list(reversed(parts)).index("episodes")
    if index + 1 >= len(parts):
        return None
    episode_root = Path(*parts[: index + 2])
    try:
        logical_path = logical_path_for(episode_root, resolved)
    except EpisodeStoreError:
        return None
    if not has_episode_db(episode_root):
        return None
    return EpisodeReader(episode_root), logical_path


def rebuild_episode_db(episode_root: Path) -> EpisodeStore:
    store = EpisodeStore(episode_root, episode_root.name, create=True, reset=True)
    store.import_legacy_tree(reset=False)
    return store

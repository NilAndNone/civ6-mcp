from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


LIVE_EVENTS_LOGICAL_PATH = "raw/live_events.jsonl"

_SEQ_CACHE: dict[tuple[str, str], int] = {}
_SEQ_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_SEQ_LOCKS_GUARD = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(to_jsonable(item) for item in value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def mirror_jsonl_to_episode_db(
    *,
    episode_root: Path,
    episode_id: str,
    logical_path: str,
    source_path: Path,
    kind: str,
) -> None:
    """Mirror a live JSONL artifact into episode.db when DB storage exists."""
    if not source_path.exists():
        return
    from codex_hl.evidence.store import EpisodeStore, has_episode_db

    if not has_episode_db(episode_root):
        return
    store = EpisodeStore(episode_root, episode_id, create=False)
    try:
        store.put_file_artifact(logical_path, source_path, kind=kind)
    finally:
        store.close()


def read_jsonl_from_episode_db(
    *,
    episode_root: Path,
    episode_id: str,
    logical_path: str,
) -> list[dict[str, Any]] | None:
    from codex_hl.evidence.store import EpisodeStore, has_episode_db

    if not has_episode_db(episode_root):
        return None
    store = EpisodeStore(episode_root, episode_id, create=False)
    try:
        return store.read_jsonl(logical_path)
    except FileNotFoundError:
        return None
    finally:
        store.close()


class EpisodeLedger:
    """Append-only Phase 1 live event ledger.

    Phase 1 deliberately keeps this lightweight: JSONL is the exported artifact,
    and Observation episodes can also mirror each append through EpisodeStore.
    """

    def __init__(
        self,
        *,
        episode_id: str,
        event_path: Path,
        store: Any | None = None,
        branch_id: str | None = None,
    ) -> None:
        self.episode_id = episode_id
        self.event_path = event_path
        self.store = store
        self.branch_id = branch_id
        self._seq_key = (self.episode_id, str(self.event_path.resolve()))
        self._seq_lock = self._lock_for_key(self._seq_key)
        with self._seq_lock:
            if self._seq_key not in _SEQ_CACHE:
                _SEQ_CACHE[self._seq_key] = self._read_last_seq()
            self._seq = _SEQ_CACHE[self._seq_key]

    @staticmethod
    def _lock_for_key(key: tuple[str, str]) -> threading.Lock:
        with _SEQ_LOCKS_GUARD:
            lock = _SEQ_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _SEQ_LOCKS[key] = lock
            return lock

    @classmethod
    def for_episode_root(
        cls,
        episode_root: Path,
        episode_id: str,
        *,
        store: Any | None = None,
        branch_id: str | None = None,
    ) -> "EpisodeLedger":
        return cls(
            episode_id=episode_id,
            event_path=episode_root / LIVE_EVENTS_LOGICAL_PATH,
            store=store,
            branch_id=branch_id,
        )

    def _read_last_seq(self) -> int:
        rows: list[dict[str, Any]] = []
        if self.store is not None:
            try:
                rows = self.store.read_jsonl(LIVE_EVENTS_LOGICAL_PATH)
            except FileNotFoundError:
                rows = []
        else:
            db_rows = read_jsonl_from_episode_db(
                episode_root=self.event_path.parent.parent,
                episode_id=self.episode_id,
                logical_path=LIVE_EVENTS_LOGICAL_PATH,
            )
            if db_rows is not None:
                rows = db_rows
        if not rows and self.event_path.exists():
            rows = [
                json.loads(line)
                for line in self.event_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        if not rows:
            return 0
        return max(int(row.get("seq") or 0) for row in rows)

    def append_event(
        self,
        *,
        event_type: str,
        request: Any,
        mode: str,
        allowed: bool,
        status: str,
        unplanned_mutation: bool,
        result: Any = None,
        error: str | None = None,
        pre_state_hash: str | None = None,
        post_state_hash: str | None = None,
        verifier_status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        with self._seq_lock:
            current_seq = _SEQ_CACHE.get(self._seq_key)
            if current_seq is None:
                current_seq = self._read_last_seq()
            self._seq = current_seq + 1
            _SEQ_CACHE[self._seq_key] = self._seq
            event_id = f"live-{self._seq:06d}-{uuid.uuid4().hex[:8]}"
            level = getattr(request, "mutation_level", None)
            level_value = getattr(level, "value", level)
            event_payload = {
                "request_id": getattr(request, "request_id", None),
                "mode": mode,
                "result": result,
                "error": error,
                **(payload or {}),
            }
            original_tool = getattr(request, "original_tool_name", None)
            if original_tool:
                event_payload["original_tool"] = original_tool
            row = {
                "event_id": event_id,
                "episode_id": getattr(request, "episode_id", None) or self.episode_id,
                "seq": self._seq,
                "ts": now_iso(),
                "turn": getattr(request, "turn", None),
                "branch_id": getattr(request, "branch_id", None) or self.branch_id,
                "event_type": event_type,
                "plan_id": getattr(request, "plan_id", None),
                "step_id": getattr(request, "step_id", None),
                "tool": getattr(request, "tool_name", None),
                "source": getattr(request, "source", None),
                "level": level_value,
                "mutation_level": level_value,
                "context_hash": getattr(request, "context_hash", None),
                "pre_state_hash": pre_state_hash,
                "post_state_hash": post_state_hash,
                "verifier_status": verifier_status,
                "args": to_jsonable(getattr(request, "args", {})),
                "allowed": allowed,
                "status": status,
                "unplanned_mutation": unplanned_mutation,
                "payload": to_jsonable(event_payload),
            }
            if self.store is not None:
                self.store.append_jsonl(
                    LIVE_EVENTS_LOGICAL_PATH,
                    row,
                    kind="live_events",
                )
                self.store.export_artifact(LIVE_EVENTS_LOGICAL_PATH)
                return event_id

            self.event_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(to_jsonable(row), ensure_ascii=False, sort_keys=False)
                    + "\n"
                )
            mirror_jsonl_to_episode_db(
                episode_root=self.event_path.parent.parent,
                episode_id=self.episode_id,
                logical_path=LIVE_EVENTS_LOGICAL_PATH,
                source_path=self.event_path,
                kind="live_events",
            )
            return event_id

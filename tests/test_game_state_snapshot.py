from __future__ import annotations

import asyncio
from types import SimpleNamespace

from civ6_connector import game_state
from civ6_connector.game_state import GameState


class SnapshotConnection:
    def __init__(self) -> None:
        self.read_calls: list[str] = []
        self.write_calls: list[str] = []

    async def execute_read(self, lua: str) -> list[str]:
        self.read_calls.append(lua)
        return []

    async def execute_write(self, lua: str) -> list[str]:
        self.write_calls.append(lua)
        return []


def test_take_snapshot_uses_ingame_units_query(monkeypatch) -> None:
    conn = SnapshotConnection()
    gs = GameState(conn)  # type: ignore[arg-type]

    monkeypatch.setattr(game_state.lq, "build_units_query", lambda: "UNITS_QUERY")
    monkeypatch.setattr(game_state.lq, "build_cities_query", lambda: "CITIES_QUERY")
    monkeypatch.setattr(game_state.lq, "build_stockpile_query", lambda: "STOCKPILE_QUERY")
    monkeypatch.setattr(game_state.lq, "parse_units_response", lambda lines: [])
    monkeypatch.setattr(game_state.lq, "parse_cities_response", lambda lines: ([], []))
    monkeypatch.setattr(game_state.lq, "parse_stockpile_response", lambda lines: [])

    overview = SimpleNamespace(turn=41, current_research="TECH_APPRENTICESHIP", current_civic="CIVIC_POLITICAL_PHILOSOPHY")

    asyncio.run(gs._take_snapshot(overview))  # noqa: SLF001 - regression guard for snapshot internals.

    assert "UNITS_QUERY" in conn.write_calls
    assert "UNITS_QUERY" not in conn.read_calls

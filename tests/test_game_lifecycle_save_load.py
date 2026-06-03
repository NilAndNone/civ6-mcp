from __future__ import annotations

import asyncio
from pathlib import Path


class FrontEndConn:
    def __init__(self) -> None:
        self.lua_states = {5: "LoadGameMenu"}
        self.gamecore_index = None
        self.ingame_index = None
        self.in_state_calls: list[tuple[int, str]] = []
        self.write_calls: list[str] = []

    async def execute_in_state(
        self, state_index: int, lua_code: str, timeout: float = 5.0
    ) -> list[str]:
        self.in_state_calls.append((state_index, lua_code))
        if "UI.QuerySaveGameList" in lua_code:
            return ["QUERY_SENT|5"]
        return ["RESULT|FOUND|test 1.Civ6Save"]

    async def execute_write(self, lua_code: str, timeout: float = 5.0) -> list[str]:
        self.write_calls.append(lua_code)
        raise AssertionError("Front-end load must not use InGame execute_write")


class InGameConn:
    def __init__(self) -> None:
        self.lua_states: dict[int, str] = {}
        self.gamecore_index = 3
        self.ingame_index = 120
        self.write_calls: list[str] = []
        self._checks = 0

    async def execute_write(self, lua_code: str, timeout: float = 5.0) -> list[str]:
        self.write_calls.append(lua_code)
        if "UI.QuerySaveGameList" in lua_code:
            return ["QUERY_SENT"]
        self._checks += 1
        return ["RESULT|FOUND"]


class InGameNotFoundConn(InGameConn):
    async def execute_write(self, lua_code: str, timeout: float = 5.0) -> list[str]:
        self.write_calls.append(lua_code)
        if "UI.QuerySaveGameList" in lua_code:
            return ["QUERY_SENT"]
        self._checks += 1
        return ["RESULT|NOT_FOUND"]


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "plugin" / "src" / "civ6_connector" / "server.py"


def test_load_game_save_uses_frontend_state_before_ingame_write() -> None:
    from civ6_connector.game_lifecycle import load_game_save

    conn = FrontEndConn()
    result = asyncio.run(load_game_save(conn, "test 1"))

    assert result == "Loading save: test 1.Civ6Save via front-end Lua state 5."
    assert conn.in_state_calls
    assert conn.write_calls == []


def test_load_game_save_uses_public_ingame_lua_query() -> None:
    from civ6_connector.game_lifecycle import load_game_save

    conn = InGameConn()
    result = asyncio.run(load_game_save(conn, 'quote " save'))

    assert result.startswith("Loading save: quote \" save.")
    assert len(conn.write_calls) == 2
    assert 'local target = "quote \\" save";' in conn.write_calls[0]
    assert "UI.QuerySaveGameList" in conn.write_calls[0]


def test_load_game_save_can_disable_ocr_menu_fallback() -> None:
    from civ6_connector.game_lifecycle import load_game_save

    conn = InGameNotFoundConn()
    result = asyncio.run(load_game_save(conn, "missing", allow_ocr_fallback=False))

    assert "OCR/menu fallback is disabled" in result
    assert len(conn.write_calls) >= 2


def test_server_recovery_routes_save_loads_through_common_helper() -> None:
    text = SERVER_PATH.read_text(encoding="utf-8")

    assert "async def _load_game_save_for_recovery(" in text
    assert "restart_result = await _load_game_save_for_recovery(" in text
    assert "lambda: _load_game_save_for_recovery(" in text
    assert "result2 = await _load_game_save_for_recovery(" in text


def test_server_keeps_restart_and_load_as_helper_fallback_only() -> None:
    text = SERVER_PATH.read_text(encoding="utf-8")
    direct_calls = [
        line.strip()
        for line in text.splitlines()
        if "game_launcher.restart_and_load(" in line
    ]

    assert direct_calls == ["return await game_launcher.restart_and_load(save_name)"]

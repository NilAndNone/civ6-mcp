from __future__ import annotations

import asyncio
import importlib
import sys
import types
from typing import Any


class FakeGameState:
    async def get_game_overview(self) -> dict[str, Any]:
        return {"turn": 7, "num_cities": 1}

    async def get_cities(self) -> list[dict[str, Any]]:
        return [{"city_id": 1, "name": "Capital", "loyalty": 100}]

    async def get_units(self) -> list[dict[str, Any]]:
        return []

    async def get_notifications(self) -> list[dict[str, Any]]:
        return []

    async def get_tech_civics(self) -> dict[str, Any]:
        return {"current_research": "TECH_POTTERY"}

    async def get_threat_scan(self) -> list[dict[str, Any]]:
        return [{"kind": "barbarian", "distance": 4}]

    async def get_empire_resources(self) -> dict[str, Any]:
        return {"gold": 30}

    async def get_diplomacy(self) -> dict[str, Any]:
        return {"known_players": []}

    async def get_trade_routes(self) -> list[dict[str, Any]]:
        return []

    async def list_city_production(self, city_id: int) -> list[dict[str, Any]]:
        return [{"city_id": city_id, "item_name": "UNIT_SCOUT"}]


def load_server_module(monkeypatch):
    uvicorn = types.ModuleType("uvicorn")
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)

    mcp = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")

    class DummyContext:
        pass

    class DummyFastMCP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def tool(self, *args, **kwargs):
            def decorate(fn):
                return fn

            return decorate

    fastmcp.Context = DummyContext
    fastmcp.FastMCP = DummyFastMCP
    monkeypatch.setitem(sys.modules, "mcp", mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp)

    fastapi = types.ModuleType("fastapi")
    fastapi_middleware = types.ModuleType("fastapi.middleware")
    fastapi_cors = types.ModuleType("fastapi.middleware.cors")
    fastapi_responses = types.ModuleType("fastapi.responses")

    class DummyFastAPI:
        def __init__(self, *args, **kwargs) -> None:
            self.state = types.SimpleNamespace()

        def add_middleware(self, *args, **kwargs) -> None:
            pass

        def exception_handler(self, *args, **kwargs):
            def decorate(fn):
                return fn

            return decorate

        def get(self, *args, **kwargs):
            def decorate(fn):
                return fn

            return decorate

    class DummyRequest:
        pass

    def dummy_query(*args, **kwargs):
        return None

    class DummyJSONResponse:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class DummyCORSMiddleware:
        pass

    fastapi.FastAPI = DummyFastAPI
    fastapi.Query = dummy_query
    fastapi.Request = DummyRequest
    fastapi_cors.CORSMiddleware = DummyCORSMiddleware
    fastapi_responses.JSONResponse = DummyJSONResponse
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "fastapi.middleware", fastapi_middleware)
    monkeypatch.setitem(sys.modules, "fastapi.middleware.cors", fastapi_cors)
    monkeypatch.setitem(sys.modules, "fastapi.responses", fastapi_responses)

    sys.modules.pop("civ6_connector.server", None)
    return importlib.import_module("civ6_connector.server")


def test_live_context_capture_includes_human_demo_observation_fields(monkeypatch) -> None:
    server = load_server_module(monkeypatch)
    monkeypatch.setattr(server, "_get_game", lambda _ctx: FakeGameState())

    state = asyncio.run(server._capture_live_observation_state(object()))

    assert state["threats"] == [{"kind": "barbarian", "distance": 4}]
    assert state["resources"] == {"gold": 30}
    assert state["diplomacy"] == {"known_players": []}
    assert state["trade_routes"] == []
    assert state["production"]["1"] == [{"city_id": 1, "item_name": "UNIT_SCOUT"}]
    assert {gap["field"] for gap in state["known_gaps"]} >= {
        "policies",
        "pantheon_status",
        "religion_founding_status",
    }

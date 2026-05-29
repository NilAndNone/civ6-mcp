from __future__ import annotations

from pathlib import Path

from codex_hl.live.actions import (
    ACTION_REGISTRY,
    CITY_ACTION_LEVELS,
    UNIT_ACTION_LEVELS,
    classify_action,
)
from codex_hl.live.inventory import discover_mcp_tools, discover_server_action_cases
from codex_hl.live.mutation_levels import ActionKind, MutationLevel


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "plugin" / "src" / "civ6_connector" / "server.py"


def test_non_readonly_mcp_tools_are_registered() -> None:
    tools = discover_mcp_tools(SERVER_PATH)

    unregistered = sorted(
        tool.name for tool in tools if not tool.read_only_hint and tool.name not in ACTION_REGISTRY
    )

    assert unregistered == []


def test_registry_specs_have_action_kind_and_level() -> None:
    for name, spec in ACTION_REGISTRY.items():
        assert name == spec.tool_name
        assert isinstance(spec.action_kind, ActionKind)
        assert isinstance(spec.mutation_level, MutationLevel)
        assert spec.description


def test_fragment_wrapper_registry_describes_delegated_mutation_level() -> None:
    spec = ACTION_REGISTRY["execute_live_fragment"]

    assert spec.mutation_level is MutationLevel.L1_RUNTIME_SIDE_EFFECT
    assert "bound tool" in spec.description
    assert "source=fragment" in spec.description


def test_required_mutation_levels_are_pinned() -> None:
    expected = {
        "set_research": MutationLevel.L2_LOW_GAME_MUTATION,
        "set_policies": MutationLevel.L2_LOW_GAME_MUTATION,
        "promote_unit": MutationLevel.L2_LOW_GAME_MUTATION,
        "send_envoy": MutationLevel.L2_LOW_GAME_MUTATION,
        "choose_pantheon": MutationLevel.L2_LOW_GAME_MUTATION,
        "choose_dedication": MutationLevel.L2_LOW_GAME_MUTATION,
        "set_city_production": MutationLevel.L3_HIGH_GAME_MUTATION,
        "purchase_item": MutationLevel.L3_HIGH_GAME_MUTATION,
        "propose_trade": MutationLevel.L3_HIGH_GAME_MUTATION,
        "appoint_governor": MutationLevel.L3_HIGH_GAME_MUTATION,
        "assign_governor": MutationLevel.L3_HIGH_GAME_MUTATION,
        "end_turn": MutationLevel.L4_BOUNDARY_RECOVERY,
        "load_save": MutationLevel.L4_BOUNDARY_RECOVERY,
        "load_game_save": MutationLevel.L4_BOUNDARY_RECOVERY,
        "restart_and_load": MutationLevel.L4_BOUNDARY_RECOVERY,
        "dismiss_popup": MutationLevel.L4_BOUNDARY_RECOVERY,
        "run_lua": MutationLevel.L5_UNSAFE_ESCAPE,
    }

    for tool_name, level in expected.items():
        assert ACTION_REGISTRY[tool_name].mutation_level is level


def test_dynamic_raw_lua_classification_marks_boundary_and_unsafe_paths() -> None:
    assert (
        classify_action("run_lua", {"context": "ingame", "code": "print('ok')"}).mutation_level
        is MutationLevel.L4_BOUNDARY_RECOVERY
    )
    assert (
        classify_action(
            "run_lua",
            {"context": "gamecore", "code": "Players[0]:GetTechs():SetResearchingTech(1)"},
        ).mutation_level
        is MutationLevel.L5_UNSAFE_ESCAPE
    )


def test_unit_and_city_action_cases_are_fully_classified() -> None:
    discovered_unit_actions = set(discover_server_action_cases(SERVER_PATH, "unit_action"))
    discovered_city_actions = set(discover_server_action_cases(SERVER_PATH, "city_action"))

    assert discovered_unit_actions == set(UNIT_ACTION_LEVELS)
    assert discovered_city_actions == set(CITY_ACTION_LEVELS)
    assert UNIT_ACTION_LEVELS["fortify"] is MutationLevel.L2_LOW_GAME_MUTATION
    assert UNIT_ACTION_LEVELS["move"] is MutationLevel.L3_HIGH_GAME_MUTATION
    assert UNIT_ACTION_LEVELS["found_city"] is MutationLevel.L3_HIGH_GAME_MUTATION
    assert CITY_ACTION_LEVELS["attack"] is MutationLevel.L3_HIGH_GAME_MUTATION
    assert CITY_ACTION_LEVELS["raze"] is MutationLevel.L3_HIGH_GAME_MUTATION

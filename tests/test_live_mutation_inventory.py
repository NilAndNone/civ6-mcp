from __future__ import annotations

from pathlib import Path

from codex_hl.live.actions import ACTION_REGISTRY, GAME_STATE_METHOD_LEVELS
from codex_hl.live.inventory import (
    build_mutation_inventory,
    discover_game_state_methods,
    discover_observation_direct_mutations,
)
from codex_hl.live.mutation_levels import MutationLevel


ROOT = Path(__file__).resolve().parents[1]
GAME_STATE_PATH = ROOT / "plugin" / "src" / "civ6_connector" / "game_state.py"
DRIVER_PATH = ROOT / "plugin" / "src" / "codex_hl" / "live" / "driver.py"
SERVER_PATH = ROOT / "plugin" / "src" / "civ6_connector" / "server.py"


def test_registered_l2_plus_actions_are_in_inventory() -> None:
    inventory = build_mutation_inventory(
        server_path=SERVER_PATH,
        game_state_path=GAME_STATE_PATH,
        observation_path=DRIVER_PATH,
    )
    inventory_tools = {entry.name for entry in inventory.mcp_tools}

    registered_l2_plus = {
        name
        for name, spec in ACTION_REGISTRY.items()
        if spec.mutation_level.is_game_mutation_or_higher()
    }

    assert registered_l2_plus <= inventory_tools


def test_registered_l2_plus_game_state_methods_have_method_classification() -> None:
    discovered = {method.name for method in discover_game_state_methods(GAME_STATE_PATH)}

    for spec in ACTION_REGISTRY.values():
        if not spec.mutation_level.is_game_mutation_or_higher():
            continue
        for method in spec.game_state_methods:
            assert method in discovered
            assert method in GAME_STATE_METHOD_LEVELS
            assert GAME_STATE_METHOD_LEVELS[method].is_game_mutation_or_higher()


def test_driver_direct_mutations_are_flagged_for_gateway() -> None:
    calls = discover_observation_direct_mutations(DRIVER_PATH)
    observed = {(call.symbol, call.mutation_level) for call in calls}

    required = {
        ("set_research", MutationLevel.L2_LOW_GAME_MUTATION),
        ("set_civic", MutationLevel.L2_LOW_GAME_MUTATION),
        ("choose_pantheon", MutationLevel.L2_LOW_GAME_MUTATION),
        ("set_policies", MutationLevel.L2_LOW_GAME_MUTATION),
        ("choose_dedication", MutationLevel.L2_LOW_GAME_MUTATION),
        ("set_city_production", MutationLevel.L3_HIGH_GAME_MUTATION),
        ("respond_to_deal", MutationLevel.L3_HIGH_GAME_MUTATION),
        ("diplomacy_respond", MutationLevel.L3_HIGH_GAME_MUTATION),
        ("move_unit", MutationLevel.L3_HIGH_GAME_MUTATION),
        ("found_city", MutationLevel.L3_HIGH_GAME_MUTATION),
        ("skip_remaining_units", MutationLevel.L3_HIGH_GAME_MUTATION),
        ("end_turn", MutationLevel.L4_BOUNDARY_RECOVERY),
        ("reconnect", MutationLevel.L4_BOUNDARY_RECOVERY),
        ("disconnect", MutationLevel.L4_BOUNDARY_RECOVERY),
    }

    assert required <= observed
    assert all(call.requires_future_gateway for call in calls if call.mutation_level.is_game_mutation_or_higher())


def test_inventory_covers_save_load_restart_and_raw_lua_paths() -> None:
    inventory = build_mutation_inventory(
        server_path=SERVER_PATH,
        game_state_path=GAME_STATE_PATH,
        observation_path=DRIVER_PATH,
    )
    boundary_names = {entry.name for entry in inventory.boundary_paths}

    assert {
        "save_game",
        "load_save",
        "load_game_save",
        "front_end_load_game_save",
        "restart_and_load",
        "run_lua",
        "GameConnection.execute_write",
        "GameConnection.execute_in_state",
    } <= boundary_names

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from codex_hl.live.mutation_levels import ActionKind, MutationLevel


@dataclass(frozen=True)
class ActionSpec:
    """Static action classification metadata.

    This is deliberately descriptive only. Phase 0 must not route execution
    through this registry or change legacy behavior.
    """

    tool_name: str
    mutation_level: MutationLevel
    action_kind: ActionKind
    game_state_methods: tuple[str, ...] = ()
    checkpoint_policy: str = "auto_by_level"
    description: str = ""


UNIT_ACTION_LEVELS: dict[str, MutationLevel] = {
    "fortify": MutationLevel.L2_LOW_GAME_MUTATION,
    "skip": MutationLevel.L2_LOW_GAME_MUTATION,
    "heal": MutationLevel.L2_LOW_GAME_MUTATION,
    "alert": MutationLevel.L2_LOW_GAME_MUTATION,
    "sleep": MutationLevel.L2_LOW_GAME_MUTATION,
    "move": MutationLevel.L3_HIGH_GAME_MUTATION,
    "attack": MutationLevel.L3_HIGH_GAME_MUTATION,
    "found_city": MutationLevel.L3_HIGH_GAME_MUTATION,
    "improve": MutationLevel.L3_HIGH_GAME_MUTATION,
    "repair": MutationLevel.L3_HIGH_GAME_MUTATION,
    "remove_improvement": MutationLevel.L3_HIGH_GAME_MUTATION,
    "remove_feature": MutationLevel.L3_HIGH_GAME_MUTATION,
    "build_route": MutationLevel.L3_HIGH_GAME_MUTATION,
    "automate": MutationLevel.L3_HIGH_GAME_MUTATION,
    "delete": MutationLevel.L3_HIGH_GAME_MUTATION,
    "trade_route": MutationLevel.L3_HIGH_GAME_MUTATION,
    "activate": MutationLevel.L3_HIGH_GAME_MUTATION,
    "sacrifice_charges": MutationLevel.L3_HIGH_GAME_MUTATION,
    "spread_religion": MutationLevel.L3_HIGH_GAME_MUTATION,
    "teleport": MutationLevel.L3_HIGH_GAME_MUTATION,
}


CITY_ACTION_LEVELS: dict[str, MutationLevel] = {
    "attack": MutationLevel.L3_HIGH_GAME_MUTATION,
    "keep": MutationLevel.L3_HIGH_GAME_MUTATION,
    "reject": MutationLevel.L3_HIGH_GAME_MUTATION,
    "raze": MutationLevel.L3_HIGH_GAME_MUTATION,
    "liberate_founder": MutationLevel.L3_HIGH_GAME_MUTATION,
    "liberate_previous": MutationLevel.L3_HIGH_GAME_MUTATION,
}


GAME_STATE_METHOD_LEVELS: dict[str, MutationLevel] = {
    "spy_travel": MutationLevel.L3_HIGH_GAME_MUTATION,
    "spy_mission": MutationLevel.L3_HIGH_GAME_MUTATION,
    "move_unit": MutationLevel.L3_HIGH_GAME_MUTATION,
    "attack_unit": MutationLevel.L3_HIGH_GAME_MUTATION,
    "city_attack": MutationLevel.L3_HIGH_GAME_MUTATION,
    "resolve_city_capture": MutationLevel.L3_HIGH_GAME_MUTATION,
    "found_city": MutationLevel.L3_HIGH_GAME_MUTATION,
    "fortify_unit": MutationLevel.L2_LOW_GAME_MUTATION,
    "skip_unit": MutationLevel.L2_LOW_GAME_MUTATION,
    "skip_remaining_units": MutationLevel.L3_HIGH_GAME_MUTATION,
    "automate_explore": MutationLevel.L3_HIGH_GAME_MUTATION,
    "heal_unit": MutationLevel.L2_LOW_GAME_MUTATION,
    "alert_unit": MutationLevel.L2_LOW_GAME_MUTATION,
    "sleep_unit": MutationLevel.L2_LOW_GAME_MUTATION,
    "delete_unit": MutationLevel.L3_HIGH_GAME_MUTATION,
    "improve_tile": MutationLevel.L3_HIGH_GAME_MUTATION,
    "remove_feature": MutationLevel.L3_HIGH_GAME_MUTATION,
    "repair_improvement": MutationLevel.L3_HIGH_GAME_MUTATION,
    "remove_improvement": MutationLevel.L3_HIGH_GAME_MUTATION,
    "sacrifice_builder_charges": MutationLevel.L3_HIGH_GAME_MUTATION,
    "build_route": MutationLevel.L3_HIGH_GAME_MUTATION,
    "set_city_production": MutationLevel.L3_HIGH_GAME_MUTATION,
    "purchase_item": MutationLevel.L3_HIGH_GAME_MUTATION,
    "set_research": MutationLevel.L2_LOW_GAME_MUTATION,
    "set_civic": MutationLevel.L2_LOW_GAME_MUTATION,
    "diplomacy_respond": MutationLevel.L3_HIGH_GAME_MUTATION,
    "send_diplomatic_action": MutationLevel.L3_HIGH_GAME_MUTATION,
    "respond_to_deal": MutationLevel.L3_HIGH_GAME_MUTATION,
    "propose_trade": MutationLevel.L3_HIGH_GAME_MUTATION,
    "propose_peace": MutationLevel.L3_HIGH_GAME_MUTATION,
    "form_alliance": MutationLevel.L3_HIGH_GAME_MUTATION,
    "set_policies": MutationLevel.L2_LOW_GAME_MUTATION,
    "appoint_governor": MutationLevel.L3_HIGH_GAME_MUTATION,
    "assign_governor": MutationLevel.L3_HIGH_GAME_MUTATION,
    "promote_governor": MutationLevel.L3_HIGH_GAME_MUTATION,
    "promote_unit": MutationLevel.L2_LOW_GAME_MUTATION,
    "send_envoy": MutationLevel.L2_LOW_GAME_MUTATION,
    "choose_pantheon": MutationLevel.L2_LOW_GAME_MUTATION,
    "found_religion": MutationLevel.L3_HIGH_GAME_MUTATION,
    "upgrade_unit": MutationLevel.L3_HIGH_GAME_MUTATION,
    "choose_dedication": MutationLevel.L2_LOW_GAME_MUTATION,
    "purchase_tile": MutationLevel.L3_HIGH_GAME_MUTATION,
    "change_government": MutationLevel.L3_HIGH_GAME_MUTATION,
    "recruit_great_person": MutationLevel.L3_HIGH_GAME_MUTATION,
    "patronize_great_person": MutationLevel.L3_HIGH_GAME_MUTATION,
    "reject_great_person": MutationLevel.L3_HIGH_GAME_MUTATION,
    "make_trade_route": MutationLevel.L3_HIGH_GAME_MUTATION,
    "activate_great_person": MutationLevel.L3_HIGH_GAME_MUTATION,
    "spread_religion": MutationLevel.L3_HIGH_GAME_MUTATION,
    "teleport_to_city": MutationLevel.L3_HIGH_GAME_MUTATION,
    "vote_world_congress": MutationLevel.L3_HIGH_GAME_MUTATION,
    "submit_congress": MutationLevel.L4_BOUNDARY_RECOVERY,
    "queue_wc_votes": MutationLevel.L3_HIGH_GAME_MUTATION,
    "set_city_focus": MutationLevel.L2_LOW_GAME_MUTATION,
    "end_turn": MutationLevel.L4_BOUNDARY_RECOVERY,
    "dismiss_popup": MutationLevel.L4_BOUNDARY_RECOVERY,
    "load_save": MutationLevel.L4_BOUNDARY_RECOVERY,
    "load_game_save": MutationLevel.L4_BOUNDARY_RECOVERY,
    "execute_lua": MutationLevel.L5_UNSAFE_ESCAPE,
}


def _spec(
    tool_name: str,
    level: MutationLevel,
    kind: ActionKind,
    methods: tuple[str, ...] = (),
    description: str = "",
) -> ActionSpec:
    return ActionSpec(
        tool_name=tool_name,
        mutation_level=level,
        action_kind=kind,
        game_state_methods=methods,
        description=description or f"{tool_name} classification",
    )


ACTION_REGISTRY: dict[str, ActionSpec] = {
    "start_live_episode": _spec(
        "start_live_episode",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Create live episode artifacts; does not mutate Civ6 game state.",
    ),
    "get_live_turn_context": _spec(
        "get_live_turn_context",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Capture and store a read-only live turn context.",
    ),
    "submit_turn_plan": _spec(
        "submit_turn_plan",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Append a JSON live turn plan to the episode ledger.",
    ),
    "arm_live_step": _spec(
        "arm_live_step",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Arm one submitted live step in the episode ledger.",
    ),
    "abort_live_episode": _spec(
        "abort_live_episode",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Abort a live episode ledger without mutating Civ6 game state.",
    ),
    "finish_live_episode": _spec(
        "finish_live_episode",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Finalize a live episode ledger after lifecycle checks.",
    ),
    "register_live_fragment": _spec(
        "register_live_fragment",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Register one optional safe fragment against a live plan step.",
    ),
    "execute_live_fragment": _spec(
        "execute_live_fragment",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        (
            "Execute one registered safe fragment wrapper; the bound tool records "
            "its real mutation level through ActionGateway source=fragment."
        ),
    ),
    "spy_action": _spec(
        "spy_action",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.SPY_ACTION,
        ("spy_travel", "spy_mission"),
        "Move a spy or launch a spy mission.",
    ),
    "appoint_governor": _spec(
        "appoint_governor",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GOVERNANCE,
        ("appoint_governor",),
        "Spend a governor title to appoint a governor.",
    ),
    "assign_governor": _spec(
        "assign_governor",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GOVERNANCE,
        ("assign_governor",),
        "Assign an appointed governor to a city.",
    ),
    "promote_governor": _spec(
        "promote_governor",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GOVERNANCE,
        ("promote_governor",),
        "Spend a governor title on a promotion.",
    ),
    "promote_unit": _spec(
        "promote_unit",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.UNIT_ACTION,
        ("promote_unit",),
        "Apply a promotion to an eligible unit.",
    ),
    "send_envoy": _spec(
        "send_envoy",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("send_envoy",),
        "Spend an envoy token at a city-state.",
    ),
    "choose_pantheon": _spec(
        "choose_pantheon",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.RELIGION,
        ("choose_pantheon",),
        "Choose a pantheon belief.",
    ),
    "get_religion_beliefs": _spec(
        "get_religion_beliefs",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Read religion founding options; registered because the MCP tool lacks readOnlyHint.",
    ),
    "found_religion": _spec(
        "found_religion",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.RELIGION,
        ("found_religion",),
        "Found a religion with selected beliefs.",
    ),
    "upgrade_unit": _spec(
        "upgrade_unit",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.UNIT_ACTION,
        ("upgrade_unit",),
        "Spend resources to upgrade a unit.",
    ),
    "get_dedications": _spec(
        "get_dedications",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Read dedication options; registered because the MCP tool lacks readOnlyHint.",
    ),
    "choose_dedication": _spec(
        "choose_dedication",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.GOVERNANCE,
        ("choose_dedication",),
        "Select an era dedication.",
    ),
    "respond_to_trade": _spec(
        "respond_to_trade",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("respond_to_deal",),
        "Accept or reject a pending deal.",
    ),
    "propose_trade": _spec(
        "propose_trade",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("propose_trade",),
        "Commit a trade proposal unless called in preview mode.",
    ),
    "propose_peace": _spec(
        "propose_peace",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("propose_peace",),
        "Propose peace to a civilization.",
    ),
    "set_policies": _spec(
        "set_policies",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.GOVERNANCE,
        ("set_policies",),
        "Change government policy-card assignments.",
    ),
    "respond_to_diplomacy": _spec(
        "respond_to_diplomacy",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("diplomacy_respond",),
        "Respond to a diplomacy encounter.",
    ),
    "send_diplomatic_action": _spec(
        "send_diplomatic_action",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("send_diplomatic_action",),
        "Send delegation, friendship, denouncement, war, or related diplomacy action.",
    ),
    "form_alliance": _spec(
        "form_alliance",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.DIPLOMACY,
        ("form_alliance",),
        "Form an alliance with another civilization.",
    ),
    "city_action": _spec(
        "city_action",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.CITY_ACTION,
        ("city_attack", "resolve_city_capture"),
        "City attack or captured-city resolution action.",
    ),
    "unit_action": _spec(
        "unit_action",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.UNIT_ACTION,
        (
            "move_unit",
            "attack_unit",
            "fortify_unit",
            "skip_unit",
            "found_city",
            "improve_tile",
            "repair_improvement",
            "remove_improvement",
            "remove_feature",
            "build_route",
            "automate_explore",
            "heal_unit",
            "alert_unit",
            "sleep_unit",
            "delete_unit",
            "make_trade_route",
            "activate_great_person",
            "sacrifice_builder_charges",
            "spread_religion",
            "teleport_to_city",
        ),
        "Unit command multiplexer; use UNIT_ACTION_LEVELS for sub-action level.",
    ),
    "skip_remaining_units": _spec(
        "skip_remaining_units",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.UNIT_ACTION,
        ("skip_remaining_units",),
        "Finish moves for all remaining units.",
    ),
    "set_city_production": _spec(
        "set_city_production",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.PRODUCTION,
        ("set_city_production",),
        "Set a city build queue item.",
    ),
    "purchase_item": _spec(
        "purchase_item",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.PRODUCTION,
        ("purchase_item",),
        "Purchase a unit or building immediately.",
    ),
    "set_research": _spec(
        "set_research",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.RESEARCH_CIVIC,
        ("set_research", "set_civic"),
        "Choose a technology or civic target.",
    ),
    "end_turn": _spec(
        "end_turn",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.TURN_BOUNDARY,
        ("end_turn",),
        "Advance the turn boundary and run blocker/recovery logic.",
    ),
    "purchase_tile": _spec(
        "purchase_tile",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.TILE,
        ("purchase_tile",),
        "Buy a city tile with gold.",
    ),
    "change_government": _spec(
        "change_government",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GOVERNANCE,
        ("change_government",),
        "Switch government type.",
    ),
    "get_gp_advisor": _spec(
        "get_gp_advisor",
        MutationLevel.L1_RUNTIME_SIDE_EFFECT,
        ActionKind.RUNTIME_SIDE_EFFECT,
        (),
        "Read Great Person activation advice; registered because the MCP tool lacks readOnlyHint.",
    ),
    "recruit_great_person": _spec(
        "recruit_great_person",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GREAT_PERSON,
        ("recruit_great_person",),
        "Recruit a Great Person with points.",
    ),
    "patronize_great_person": _spec(
        "patronize_great_person",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GREAT_PERSON,
        ("patronize_great_person",),
        "Purchase a Great Person with gold or faith.",
    ),
    "reject_great_person": _spec(
        "reject_great_person",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.GREAT_PERSON,
        ("reject_great_person",),
        "Pass on a Great Person.",
    ),
    "queue_wc_votes": _spec(
        "queue_wc_votes",
        MutationLevel.L3_HIGH_GAME_MUTATION,
        ActionKind.WORLD_CONGRESS,
        ("queue_wc_votes",),
        "Register votes for a World Congress session.",
    ),
    "set_city_focus": _spec(
        "set_city_focus",
        MutationLevel.L2_LOW_GAME_MUTATION,
        ActionKind.PRODUCTION,
        ("set_city_focus",),
        "Set citizen yield focus for a city.",
    ),
    "dismiss_popup": _spec(
        "dismiss_popup",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.UI_RECOVERY,
        ("dismiss_popup",),
        "Dismiss a blocking UI popup.",
    ),
    "run_lua": _spec(
        "run_lua",
        MutationLevel.L5_UNSAFE_ESCAPE,
        ActionKind.RAW_LUA,
        ("execute_lua",),
        "Arbitrary Lua escape hatch; arg-sensitive classifier can identify ingame L4 paths.",
    ),
    "load_save": _spec(
        "load_save",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.SAVE_LOAD,
        ("load_save",),
        "Load a save by index.",
    ),
    "load_game_save": _spec(
        "load_game_save",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.SAVE_LOAD,
        ("load_game_save",),
        "Load a save by name.",
    ),
    "kill_game": _spec(
        "kill_game",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.PROCESS_LIFECYCLE,
        (),
        "Kill the Civ6 process.",
    ),
    "launch_game": _spec(
        "launch_game",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.PROCESS_LIFECYCLE,
        (),
        "Launch the Civ6 process.",
    ),
    "load_save_from_menu": _spec(
        "load_save_from_menu",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.SAVE_LOAD,
        (),
        "Load a save through menu automation.",
    ),
    "restart_and_load": _spec(
        "restart_and_load",
        MutationLevel.L4_BOUNDARY_RECOVERY,
        ActionKind.PROCESS_LIFECYCLE,
        (),
        "Load a save through the shared Lua path, with GUI restart fallback.",
    ),
}

ACTION_ALIASES: dict[str, str] = {
    "end_turn_retry": "end_turn",
    "end_turn_after_diplomacy": "end_turn",
    "respond_to_trade_decline_for_end_turn": "respond_to_trade",
    "respond_to_diplomacy_for_end_turn": "respond_to_diplomacy",
    "respond_to_diplomacy_exit_for_end_turn": "respond_to_diplomacy",
}


_RAW_LUA_WRITE_RE = re.compile(
    r"RequestOperation|SetResearchingTech|SetProgressingCivic|Change[A-Z]|"
    r"Set[A-Z]|SaveGame|LoadGame|UnitManager|CityManager|DiplomacyManager|"
    r"NotificationManager\.SendActivated|Network\.SaveGame"
)


def canonical_action_name(tool_name: str) -> str:
    """Map observation-only aliases to their registered action tool."""

    return ACTION_ALIASES.get(tool_name, tool_name)


def is_registered_action_tool(tool_name: str) -> bool:
    return canonical_action_name(tool_name) in ACTION_REGISTRY


def _classify_raw_lua(args: dict[str, Any]) -> ActionSpec:
    base = ACTION_REGISTRY["run_lua"]
    context = str(args.get("context", "gamecore") or "gamecore").lower()
    code = str(args.get("code", "") or "")
    if _RAW_LUA_WRITE_RE.search(code):
        return replace(
            base,
            mutation_level=MutationLevel.L5_UNSAFE_ESCAPE,
            description="Raw Lua contains write-like API usage.",
        )
    if context == "ingame":
        return replace(
            base,
            mutation_level=MutationLevel.L4_BOUNDARY_RECOVERY,
            description="Raw Lua in InGame context can mutate UI/game state.",
        )
    return base


def classify_action(tool_name: str, args: dict[str, Any] | None = None) -> ActionSpec:
    """Return the initial Phase 0 classification for a tool call."""

    args = args or {}
    tool_name = canonical_action_name(tool_name)
    spec = ACTION_REGISTRY[tool_name]
    if tool_name == "unit_action":
        action = str(args.get("action", "") or "").lower()
        if action in UNIT_ACTION_LEVELS:
            return replace(spec, mutation_level=UNIT_ACTION_LEVELS[action])
    if tool_name == "city_action":
        action = str(args.get("action", "") or "").lower()
        if action in CITY_ACTION_LEVELS:
            return replace(spec, mutation_level=CITY_ACTION_LEVELS[action])
    if tool_name == "propose_trade" and str(args.get("mode", "")).lower() == "test":
        return replace(
            spec,
            mutation_level=MutationLevel.L1_RUNTIME_SIDE_EFFECT,
            description="Trade preview mode calls test_trade and should not commit a deal.",
        )
    if tool_name == "run_lua":
        return _classify_raw_lua(args)
    return spec

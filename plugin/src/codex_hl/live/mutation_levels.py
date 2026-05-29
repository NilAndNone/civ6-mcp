from __future__ import annotations

from enum import Enum


class MutationLevel(str, Enum):
    """Coarse mutation risk level for future ActionGateway policy."""

    L0_READ = "L0"
    L1_RUNTIME_SIDE_EFFECT = "L1"
    L2_LOW_GAME_MUTATION = "L2"
    L3_HIGH_GAME_MUTATION = "L3"
    L4_BOUNDARY_RECOVERY = "L4"
    L5_UNSAFE_ESCAPE = "L5"

    @property
    def label(self) -> str:
        return {
            MutationLevel.L0_READ: "pure_read",
            MutationLevel.L1_RUNTIME_SIDE_EFFECT: "runtime_side_effect",
            MutationLevel.L2_LOW_GAME_MUTATION: "low_game_mutation",
            MutationLevel.L3_HIGH_GAME_MUTATION: "high_game_mutation",
            MutationLevel.L4_BOUNDARY_RECOVERY: "boundary_recovery",
            MutationLevel.L5_UNSAFE_ESCAPE: "unsafe_escape",
        }[self]

    def is_game_mutation_or_higher(self) -> bool:
        return self in {
            MutationLevel.L2_LOW_GAME_MUTATION,
            MutationLevel.L3_HIGH_GAME_MUTATION,
            MutationLevel.L4_BOUNDARY_RECOVERY,
            MutationLevel.L5_UNSAFE_ESCAPE,
        }


class ActionKind(str, Enum):
    """Initial Phase 0 labels for grouping tools and GameState methods."""

    PURE_READ = "pure_read"
    RUNTIME_SIDE_EFFECT = "runtime_side_effect"
    UNIT_ACTION = "unit_action"
    CITY_ACTION = "city_action"
    SPY_ACTION = "spy_action"
    RESEARCH_CIVIC = "research_civic"
    PRODUCTION = "production"
    DIPLOMACY = "diplomacy"
    GOVERNANCE = "governance"
    RELIGION = "religion"
    GREAT_PERSON = "great_person"
    TILE = "tile"
    WORLD_CONGRESS = "world_congress"
    TURN_BOUNDARY = "turn_boundary"
    SAVE_LOAD = "save_load"
    PROCESS_LIFECYCLE = "process_lifecycle"
    UI_RECOVERY = "ui_recovery"
    RAW_LUA = "raw_lua"

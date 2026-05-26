import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "plugin" / "src"


def load_runner_module():
    sys.path.insert(0, str(PLUGIN_SRC))
    try:
        return importlib.import_module("codex_hl.phase1.observer")
    finally:
        sys.path.remove(str(PLUGIN_SRC))


@pytest.mark.parametrize("turns", [3, 10, 20, 50])
def test_phase1_observe_accepts_short_runs_t20_and_t50(monkeypatch, turns):
    module = load_runner_module()
    monkeypatch.setattr(sys, "argv", ["codex-hl-civ6-phase1-observe", "--turns", str(turns)])

    args = module.parse_args()

    assert args.turns == turns


@pytest.mark.parametrize("turns", [1, 11, 19, 21, 49, 51])
def test_phase1_observe_rejects_unsupported_turn_counts(monkeypatch, turns):
    module = load_runner_module()
    monkeypatch.setattr(sys, "argv", ["codex-hl-civ6-phase1-observe", "--turns", str(turns)])

    with pytest.raises(SystemExit):
        module.parse_args()


def test_phase1_observe_accepts_explicit_strategy_profile(monkeypatch):
    module = load_runner_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codex-hl-civ6-phase1-observe",
            "--turns",
            "20",
            "--strategy-profile",
            "explore_scout_first",
        ],
    )

    args = module.parse_args()

    assert args.strategy_profile == "explore_scout_first"


def test_phase1_observe_accepts_science_culture_t50_profile(monkeypatch):
    module = load_runner_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codex-hl-civ6-phase1-observe",
            "--turns",
            "50",
            "--strategy-profile",
            "science_culture_t50",
        ],
    )

    args = module.parse_args()

    assert args.strategy_profile == "science_culture_t50"


def test_phase1_observe_accepts_candidate_package(monkeypatch, tmp_path):
    module = load_runner_module()
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codex-hl-civ6-phase1-observe",
            "--turns",
            "50",
            "--candidate-package",
            str(candidate),
        ],
    )

    args = module.parse_args()

    assert args.candidate_package == candidate


def test_candidate_package_runtime_drives_expansion_priority(tmp_path):
    module = load_runner_module()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "candidate_id": "impr_test",
                "status": "candidate_only",
                "source_episode_ids": ["ep1"],
                "source_failure_ids": ["fail_city_count"],
                "source_failure": {
                    "title": "T50 前已扩张城市数回落",
                    "capability_category": "planning",
                },
                "target_asset": {
                    "asset_id": "playbook.phase1_observation",
                    "asset_type": "playbook",
                    "current_version": "1.0.0",
                    "proposed_version": "1.0.1",
                    "content_path": "assets/playbook-phase1-observation.md",
                },
                "proposed_change": {
                    "content_appendix": "需要通过 scout、settler、defense 维持城市扩张。",
                },
            }
        ),
        encoding="utf-8",
    )

    runtime = module.load_candidate_runtime(candidate)

    class Recorder:
        strategy_profile = "baseline_static"
        candidate_runtime = runtime

    priority = module.production_priority_for(Recorder(), {"cities": [], "units": []})

    assert runtime["status"] == "applied"
    assert runtime["candidate_id"] == "impr_test"
    assert priority.index("UNIT_SCOUT") < priority.index("UNIT_SETTLER")
    assert module.should_auto_explore_unit(Recorder(), "UNIT_SCOUT", {"units": []})


def test_candidate_package_runtime_detects_user_t50_strategy_terms(tmp_path):
    module = load_runner_module()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "candidate_id": "impr_user_notes",
                "status": "candidate_only",
                "source_episode_ids": ["ep1"],
                "source_failure_ids": ["fail_user_notes"],
                "source_failure": {
                    "title": "T50 science and culture below target",
                    "capability_category": "planning",
                },
                "target_asset": {"asset_type": "playbook"},
                "proposed_change": {
                    "content_appendix": (
                        "Settle along river/fresh water, clear barbarian camps, "
                        "research Writing, build Campus, use Horsemen, and pursue "
                        "10+ science/culture plus golden age era score."
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    runtime = module.load_candidate_runtime(candidate)

    assert {
        "river_settlement",
        "barbarian_clearance",
        "science_culture_push",
        "horseman_pressure",
        "era_score_push",
    }.issubset(set(runtime["runtime_effects"]))


def test_end_turn_result_requests_diplomacy_response():
    module = load_runner_module()

    assert module.end_turn_result_requests_diplomacy_response(
        "Cannot end turn: diplomacy encounter pending. Use respond_to_diplomacy to handle it."
    )
    assert not module.end_turn_result_requests_diplomacy_response("Turn advanced to 7")


def test_resolve_end_turn_diplomacy_blocker_responds_and_retries():
    module = load_runner_module()

    class Session:
        other_player_id = 3
        other_civ_name = "Other Civ"
        other_leader_name = "Other Leader"
        deal_summary = ""
        buttons = ""
        is_at_war = False

    class FakeRecorder:
        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class FakeGameState:
        def __init__(self):
            self.responses = []

        async def get_diplomacy_sessions(self):
            return [Session()]

        async def diplomacy_respond(self, other_player_id, response):
            self.responses.append((other_player_id, response))
            if response == "POSITIVE":
                return "OK:RESPONDED|POSITIVE|SESSION_CONTINUES"
            return "OK:RESPONDED|EXIT|SESSION_CLOSED"

        async def end_turn(self):
            return "Turn advanced to 7"

    recorder = FakeRecorder()
    gs = FakeGameState()

    result = asyncio.run(
        module.resolve_end_turn_diplomacy_blocker(
            recorder,
            gs,
            6,
            "state-0006",
            {},
            "Cannot end turn: diplomacy encounter pending. Use respond_to_diplomacy to handle it.",
        )
    )

    assert result == "Turn advanced to 7"
    assert gs.responses == [(3, "POSITIVE"), (3, "EXIT")]
    assert [call[0] for call in recorder.calls] == [
        "get_diplomacy_sessions_for_end_turn",
        "respond_to_diplomacy_for_end_turn",
        "respond_to_diplomacy_exit_for_end_turn",
        "end_turn_after_diplomacy",
    ]
    assert recorder.decisions[0]["selected_action"] == (
        "auto-resolve diplomacy blocker and retry end_turn"
    )


def test_resolve_end_turn_diplomacy_blocker_handles_layered_prompt():
    module = load_runner_module()

    class Session:
        other_player_id = 1
        other_civ_name = "Layered Civ"
        other_leader_name = "Layered Leader"
        deal_summary = ""
        buttons = ""
        is_at_war = False

    class FakeRecorder:
        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class FakeGameState:
        def __init__(self):
            self.end_turn_attempts = 0

        async def get_diplomacy_sessions(self):
            return [Session()]

        async def diplomacy_respond(self, other_player_id, response):
            if response == "POSITIVE":
                return "OK:RESPONDED|POSITIVE|SESSION_CONTINUES"
            return "OK:RESPONDED|EXIT|SESSION_CLOSED"

        async def end_turn(self):
            self.end_turn_attempts += 1
            if self.end_turn_attempts == 1:
                return "Use respond_to_diplomacy to handle it, then end_turn again."
            return "Turn 13 -> 14"

    recorder = FakeRecorder()
    gs = FakeGameState()

    result = asyncio.run(
        module.resolve_end_turn_diplomacy_blocker(
            recorder,
            gs,
            13,
            "state-0013",
            {},
            "Cannot end turn: diplomacy encounter pending. Use respond_to_diplomacy to handle it.",
        )
    )

    assert result == "Turn 13 -> 14"
    assert [call[0] for call in recorder.calls].count("end_turn_after_diplomacy") == 2
    assert [decision["execution"]["attempt"] for decision in recorder.decisions] == [1, 2]


def test_explore_scout_first_caps_scout_production():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(), {"units": [Unit("UNIT_SCOUT"), Unit("UNIT_SCOUT")]}
    )

    assert priority.index("UNIT_SETTLER") < priority.index("UNIT_SCOUT")


def test_explore_scout_first_counts_queued_scouts_for_cap():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    class City:
        currently_building = "UNIT_SCOUT"

    priority = module.production_priority_for(
        Recorder(), {"cities": [City()], "units": [Unit("UNIT_SCOUT")]}
    )

    assert priority.index("UNIT_SETTLER") < priority.index("UNIT_SCOUT")


def test_explore_scout_first_counts_same_turn_planned_scouts_for_cap():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(),
        {"units": [Unit("UNIT_SCOUT")]},
        {"UNIT_SCOUT": 1},
    )

    assert priority.index("UNIT_SETTLER") < priority.index("UNIT_SCOUT")


def test_explore_profile_prioritizes_military_before_extra_settler_after_two_cities():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(),
        {
            "cities": [{"name": "A"}, {"name": "B"}],
            "units": [Unit("UNIT_SCOUT"), Unit("UNIT_SCOUT"), Unit("UNIT_WARRIOR")],
        },
    )

    assert priority.index("UNIT_SLINGER") < priority.index("UNIT_SETTLER")


def test_explore_profile_prioritizes_military_after_three_cities_until_escort_ready():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(),
        {
            "cities": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "units": [
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SLINGER"),
                Unit("UNIT_WARRIOR"),
            ],
        },
    )

    assert priority.index("UNIT_SLINGER") < priority.index("UNIT_SETTLER")
    assert priority.index("UNIT_WARRIOR") < priority.index("UNIT_SETTLER")


def test_explore_profile_prioritizes_fourth_city_after_three_city_escort_ready():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(),
        {
            "cities": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "units": [
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SLINGER"),
                Unit("UNIT_SLINGER"),
                Unit("UNIT_WARRIOR"),
                Unit("UNIT_BUILDER"),
            ],
        },
    )

    assert priority.index("UNIT_SETTLER") < priority.index("DISTRICT_CAMPUS")
    assert priority.index("UNIT_SETTLER") < priority.index("UNIT_TRADER")


def test_explore_profile_prioritizes_infrastructure_when_settler_already_exists():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(),
        {
            "cities": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "units": [
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SLINGER"),
                Unit("UNIT_SLINGER"),
                Unit("UNIT_WARRIOR"),
                Unit("UNIT_SETTLER"),
            ],
        },
    )

    assert priority.index("UNIT_BUILDER") < priority.index("UNIT_SETTLER")
    assert priority.index("DISTRICT_CAMPUS") < priority.index("UNIT_SETTLER")


def test_explore_profile_caps_builders_after_three_cities():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    priority = module.production_priority_for(
        Recorder(),
        {
            "cities": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "units": [
                Unit("UNIT_SCOUT"),
                Unit("UNIT_SCOUT"),
                Unit("UNIT_BUILDER"),
                Unit("UNIT_BUILDER"),
                Unit("UNIT_SLINGER"),
                Unit("UNIT_WARRIOR"),
            ],
        },
    )

    assert priority.index("UNIT_TRADER") < priority.index("UNIT_BUILDER")
    assert priority.index("DISTRICT_CAMPUS") < priority.index("UNIT_BUILDER")


def test_science_culture_profile_prioritizes_writing_path():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "science_culture_t50"

    priority = module.tech_priority_for(Recorder())

    assert priority.index("TECH_WRITING") < priority.index("TECH_MINING")
    assert priority.index("TECH_ARCHERY") < priority.index("TECH_HORSEBACK_RIDING")


def test_golden_age_push_prioritizes_resource_reveal_techs_before_pottery():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.tech_priority_for(Recorder())

    assert priority.index("TECH_ANIMAL_HUSBANDRY") < priority.index("TECH_POTTERY")
    assert priority.index("TECH_MINING") < priority.index("TECH_POTTERY")
    assert priority.index("TECH_ARCHERY") < priority.index("TECH_HORSEBACK_RIDING")
    assert priority.index("TECH_ARCHERY") < priority.index("TECH_WRITING")
    assert priority.index("TECH_HORSEBACK_RIDING") < priority.index("TECH_POTTERY")
    assert priority.index("TECH_HORSEBACK_RIDING") < priority.index("TECH_WRITING")
    assert priority.index("TECH_HORSEBACK_RIDING") < priority.index("TECH_ASTROLOGY")


def test_golden_age_push_prioritizes_mysticism_for_religion_policy():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.civic_priority_for(Recorder())

    assert priority.index("CIVIC_MYSTICISM") < priority.index("CIVIC_EARLY_EMPIRE")


def test_science_culture_profile_prioritizes_barbarian_defense_when_threat_visible():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "science_culture_t50"

    class Threat:
        owner_id = 63
        owner_name = "Barbarian"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {"science_yield": 4.0, "culture_yield": 3.0},
            "cities": [{"name": "A"}, {"name": "B"}],
            "units": [{"unit_type": "UNIT_SCOUT"}, {"unit_type": "UNIT_WARRIOR"}],
            "threats": [Threat()],
        },
    )

    assert priority.index("UNIT_SLINGER") < priority.index("DISTRICT_CAMPUS")
    assert priority.index("UNIT_ARCHER") < priority.index("BUILDING_MONUMENT")


def test_science_culture_profile_stops_ranged_overproduction_after_clearance_cap():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "science_culture_t50"

    class Threat:
        owner_id = 63
        owner_name = "Barbarian"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {"science_yield": 5.4, "culture_yield": 4.3},
            "cities": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "units": [
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_ARCHER"},
                {"unit_type": "UNIT_ARCHER"},
                {"unit_type": "UNIT_WARRIOR"},
            ],
            "threats": [Threat()],
        },
    )

    assert priority.index("BUILDING_MONUMENT") < priority.index("UNIT_SLINGER")
    assert priority.index("DISTRICT_CAMPUS") < priority.index("UNIT_ARCHER")


def test_science_culture_profile_prioritizes_campus_and_monument_below_yield_floor():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "science_culture_t50"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {"science_yield": 6.4, "culture_yield": 5.9},
            "cities": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "units": [
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_ARCHER"},
                {"unit_type": "UNIT_WARRIOR"},
            ],
            "threats": [],
        },
    )

    assert priority.index("BUILDING_MONUMENT") < priority.index("UNIT_SETTLER")
    assert priority.index("DISTRICT_CAMPUS") < priority.index("UNIT_SETTLER")


def test_builder_tasks_prefer_assigned_urgent_target():
    module = load_runner_module()

    class Unit:
        unit_id = 42

    class Task:
        def __init__(self, nearest_builder_id, priority, distance):
            self.nearest_builder_id = nearest_builder_id
            self.priority = priority
            self.distance = distance

    ranked = module.ranked_builder_tasks_for_unit(
        [
            Task(99, "urgent", 1),
            Task(42, "normal", 1),
            Task(42, "urgent", 4),
        ],
        Unit(),
    )

    assert ranked[0].nearest_builder_id == 42
    assert ranked[0].priority == "urgent"


def test_builder_tasks_prefer_horses_and_iron_within_same_priority():
    module = load_runner_module()

    class Unit:
        unit_id = 42

    class Task:
        def __init__(self, resource, resource_class, distance):
            self.nearest_builder_id = 42
            self.priority = "urgent"
            self.resource = resource
            self.resource_class = resource_class
            self.distance = distance

    ranked = module.ranked_builder_tasks_for_unit(
        [
            Task("NITER", "strategic", 1),
            Task("DIAMONDS", "luxury", 1),
            Task("HORSES", "strategic", 4),
            Task("IRON", "strategic", 5),
        ],
        Unit(),
    )

    assert [task.resource for task in ranked[:2]] == ["HORSES", "IRON"]


def test_builder_tasks_can_prefer_strategic_resource_over_generic_urgent_task():
    module = load_runner_module()

    class Unit:
        unit_id = 42

    class Task:
        def __init__(self, resource, resource_class, priority, distance):
            self.nearest_builder_id = 42
            self.priority = priority
            self.resource = resource
            self.resource_class = resource_class
            self.distance = distance

    ranked = module.ranked_builder_tasks_for_unit(
        [
            Task("", "bonus", "urgent", 1),
            Task("HORSES", "strategic", "high", 4),
        ],
        Unit(),
        prefer_strategic=True,
    )

    assert ranked[0].resource == "HORSES"


def test_handle_units_routes_builder_to_strategic_before_current_bonus_tile():
    module = load_runner_module()

    class Unit:
        unit_id = 42
        unit_index = 42
        unit_type = "UNIT_BUILDER"
        x = 10
        y = 10
        moves_remaining = 2
        valid_improvements = ["IMPROVEMENT_FARM", "IMPROVEMENT_PASTURE"]

    class Task:
        def __init__(self, x, y, improvement, resource, resource_class, priority, distance):
            self.nearest_builder_id = 42
            self.x = x
            self.y = y
            self.improvement = improvement
            self.resource = resource
            self.resource_class = resource_class
            self.priority = priority
            self.distance = distance
            self.city_name = "Capital"

    class OwnedHorse:
        name = "HORSES"
        resource_class = "strategic"
        improved = False
        x = 12
        y = 10

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_builder_tasks(self):
            return (
                [
                    Task(10, 10, "IMPROVEMENT_FARM", "WHEAT", "bonus", "urgent", 0),
                    Task(12, 10, "IMPROVEMENT_PASTURE", "HORSES", "strategic", "high", 2),
                ],
                [],
            )

        async def improve_tile(self, unit_index, improvement):
            raise AssertionError("builder should not spend the turn on the bonus tile")

        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVED|{unit_index}|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            20,
            "state-0020",
            {
                "overview": {"turn": 20, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "resources": ([], [OwnedHorse()], [], {}),
                "threats": [],
            },
        )
    )

    move_call = next(call for call in recorder.calls if call[1].get("action") == "move")
    assert move_call[1]["target_x"] == 12
    assert move_call[1]["target_y"] == 10
    assert recorder.decisions[0]["selected_action"] == "move to IMPROVEMENT_PASTURE target"


def test_builder_tasks_skip_unreliable_lumber_mill_without_resource():
    module = load_runner_module()

    class Unit:
        valid_improvements = []

    class Task:
        improvement = "IMPROVEMENT_LUMBER_MILL"
        resource = ""
        resource_class = ""

    assert not module.builder_task_is_usable_now(Task(), Unit())


def test_golden_age_map_targets_prioritize_tribal_village_for_scout():
    module = load_runner_module()

    class Unit:
        unit_type = "UNIT_SCOUT"
        x = 10
        y = 10

    class Tile:
        def __init__(self, x, y, improvement="", feature="", resource=""):
            self.x = x
            self.y = y
            self.improvement = improvement
            self.feature = feature
            self.resource = resource

    ranked = module.ranked_golden_age_map_targets_for_unit(
        Unit(),
        [
            Tile(11, 10, improvement="IMPROVEMENT_BARBARIAN_CAMP"),
            Tile(13, 10, improvement="IMPROVEMENT_GOODY_HUT"),
        ],
    )

    assert ranked[0]["event_key"] == "tribal_village"
    assert ranked[0]["x"] == 13


def test_golden_age_map_targets_route_combat_unit_to_camp():
    module = load_runner_module()

    class Unit:
        unit_type = "UNIT_WARRIOR"
        x = 10
        y = 10

    class Tile:
        x = 12
        y = 11
        improvement = "IMPROVEMENT_BARBARIAN_CAMP"
        feature = ""
        resource = ""

    ranked = module.ranked_golden_age_map_targets_for_unit(Unit(), [Tile()])

    assert ranked[0]["event_key"] == "clear_barbarian_camp"
    assert ranked[0]["distance"] == 2


def test_golden_age_map_targets_skip_recently_blocked_target():
    module = load_runner_module()

    class Recorder:
        blocked_map_targets = {}

    class Unit:
        unit_id = 12
        unit_type = "UNIT_WARRIOR"
        x = 10
        y = 10

    class Tile:
        def __init__(self, x, y):
            self.x = x
            self.y = y
            self.improvement = "IMPROVEMENT_BARBARIAN_CAMP"
            self.feature = ""
            self.resource = ""

    ranked = module.ranked_golden_age_map_targets_for_unit(
        Unit(),
        [Tile(12, 10), Tile(14, 10)],
    )
    module.remember_blocked_golden_age_map_target(Recorder, Unit(), ranked[0], 20)

    filtered = module.filter_blocked_golden_age_map_targets(
        Recorder,
        Unit(),
        ranked,
        21,
    )

    assert len(filtered) == 1
    assert filtered[0]["x"] == 14


def test_golden_age_wounded_scout_can_claim_adjacent_tribal_village():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Unit:
        unit_type = "UNIT_SCOUT"

    assert module.should_move_to_critical_map_target_while_wounded(
        Recorder(),
        Unit(),
        {"event_key": "tribal_village", "distance": 1},
    )
    assert not module.should_move_to_critical_map_target_while_wounded(
        Recorder(),
        Unit(),
        {"event_key": "clear_barbarian_camp", "distance": 1},
    )


def test_warrior_auto_explore_stops_after_scout_exists():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    assert not module.should_auto_explore_unit(
        Recorder(), "UNIT_WARRIOR", {"units": [{"unit_type": "UNIT_SCOUT"}]}
    )


def test_golden_age_push_auto_explores_early_warrior_despite_scout():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    early_snapshot = {
        "overview": {"turn": 8, "era_score": 3, "era_golden_threshold": 19},
        "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
        "units": [{"unit_type": "UNIT_WARRIOR"}, {"unit_type": "UNIT_SCOUT"}],
    }
    late_snapshot = {
        **early_snapshot,
        "overview": {"turn": 13, "era_score": 3, "era_golden_threshold": 19},
    }

    assert module.should_auto_explore_unit(Recorder(), "UNIT_WARRIOR", early_snapshot)
    assert not module.should_auto_explore_unit(Recorder(), "UNIT_WARRIOR", late_snapshot)


def test_best_settle_candidate_prefers_highest_score():
    module = load_runner_module()

    class Candidate:
        def __init__(self, x, y, score):
            self.x = x
            self.y = y
            self.score = score

    selected = module.best_settle_candidate(
        [Candidate(1, 1, 4.0), Candidate(2, 2, 7.5), Candidate(3, 3, 6.0)]
    )

    assert (selected.x, selected.y) == (2, 2)


def test_ranked_settle_candidates_can_prefer_fresh_water_for_river_strategy():
    module = load_runner_module()

    class Candidate:
        def __init__(self, x, y, score, water_type):
            self.x = x
            self.y = y
            self.score = score
            self.water_type = water_type

    selected = module.best_settle_candidate(
        [
            Candidate(1, 1, 8.0, "none"),
            Candidate(2, 2, 6.5, "fresh"),
            Candidate(3, 3, 7.0, "coast"),
        ],
        prefer_fresh=True,
    )

    assert (selected.x, selected.y) == (2, 2)


def test_ranked_settle_candidates_prefers_fresh_water_over_higher_raw_score():
    module = load_runner_module()

    class Candidate:
        def __init__(self, x, y, score, water_type):
            self.x = x
            self.y = y
            self.score = score
            self.water_type = water_type

    selected = module.best_settle_candidate(
        [
            Candidate(69, 44, 140.0, "none"),
            Candidate(70, 45, 94.0, "fresh"),
        ],
        prefer_fresh=True,
    )

    assert (selected.x, selected.y) == (70, 45)


def test_golden_age_strategic_settle_prefers_horse_cluster_over_raw_score():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Candidate:
        def __init__(self, x, y, score, water_type="none"):
            self.x = x
            self.y = y
            self.score = score
            self.water_type = water_type

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 5

    ranked = module.ranked_settle_candidates_for_strategy(
        Recorder(),
        {
            "overview": {"turn": 16, "era_score": 5, "era_golden_threshold": 19},
            "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
            "resources": ([], [], [NearHorse()], {}),
        },
        [
            Candidate(70, 45, 160.0, "fresh"),
            Candidate(66, 39, 90.0, "none"),
        ],
        prefer_fresh=True,
    )

    assert (ranked[0].x, ranked[0].y) == (66, 39)
    assert module.strategic_resource_distance_for_candidate(ranked[0], {"resources": ([], [], [NearHorse()], {})}) <= 3


def test_handle_units_moves_opening_settler_toward_fresh_water_candidate():
    module = load_runner_module()

    class Unit:
        unit_id = 20
        unit_index = 20
        unit_type = "UNIT_SETTLER"
        x = 10
        y = 10
        moves_remaining = 2

    class Candidate:
        def __init__(self, x, y, score, water_type):
            self.x = x
            self.y = y
            self.score = score
            self.water_type = water_type

    class FakeRecorder:
        strategy_profile = "science_culture_t50"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, *_args):
            raise AssertionError("opening settle scan should not fail")

    class FakeGameState:
        async def get_global_settle_scan(self):
            return [
                Candidate(10, 10, 8.0, "none"),
                Candidate(11, 10, 5.0, "fresh"),
            ]

        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVED|{unit_index}|{target_x},{target_y}"

        async def found_city(self, unit_index):
            raise AssertionError("opening settler should move before founding")

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            1,
            "state-0001",
            {"units": [Unit()], "cities": [], "threats": []},
        )
    )

    assert recorder.calls[1][0] == "unit_action"
    assert recorder.calls[1][1]["action"] == "move"
    assert recorder.calls[1][1]["target_x"] == 11
    assert recorder.decisions[0]["selected_action"] == "move settler toward fresh water"


def test_handle_units_founds_opening_city_when_current_tile_is_fresh_water():
    module = load_runner_module()

    class Unit:
        unit_id = 20
        unit_index = 20
        unit_type = "UNIT_SETTLER"
        x = 10
        y = 10
        moves_remaining = 2

    class Candidate:
        def __init__(self, x, y, score, water_type):
            self.x = x
            self.y = y
            self.score = score
            self.water_type = water_type

    class FakeRecorder:
        strategy_profile = "science_culture_t50"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, *_args):
            raise AssertionError("opening settle scan should not fail")

    class FakeGameState:
        async def get_global_settle_scan(self):
            return [
                Candidate(10, 10, 6.0, "fresh"),
                Candidate(11, 10, 8.0, "none"),
            ]

        async def move_unit(self, unit_index, target_x, target_y):
            raise AssertionError("current fresh-water tile should be founded")

        async def found_city(self, unit_index):
            return "FOUNDED|10,10"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            1,
            "state-0001",
            {"units": [Unit()], "cities": [], "threats": []},
        )
    )

    assert recorder.calls[1][0] == "unit_action"
    assert recorder.calls[1][1]["action"] == "found_city"
    assert recorder.decisions[0]["selected_action"] == "found_city on current tile"


def test_handle_units_holds_unescorted_settler_when_barbarian_blocks_long_path():
    module = load_runner_module()

    class Unit:
        unit_id = 40
        unit_index = 40
        unit_type = "UNIT_SETTLER"
        x = 10
        y = 10
        moves_remaining = 2

    class Candidate:
        x = 18
        y = 14
        score = 120.0
        water_type = "fresh"

    class Threat:
        owner_id = 63
        owner_name = "Barbarian"
        x = 13
        y = 11

    class FakeRecorder:
        strategy_profile = "science_culture_t50"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, *_args):
            raise AssertionError("settle scan should not fail")

    class FakeGameState:
        async def found_city(self, unit_index):
            return "FAILED|too close"

        async def get_global_settle_scan(self):
            return [Candidate()]

        async def move_unit(self, unit_index, target_x, target_y):
            raise AssertionError("unsafe settler path should not be moved")

        async def skip_unit(self, unit_index):
            return "SKIPPED"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            28,
            "state-0028",
            {
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [Threat()],
            },
        )
    )

    assert recorder.calls[-1][1]["action"] == "skip"
    assert recorder.decisions[0]["selected_action"] == "hold settler for barbarian safety"


def test_handle_units_moves_golden_age_settler_to_near_candidate_under_barbarian_pressure():
    module = load_runner_module()

    class Unit:
        unit_id = 40
        unit_index = 40
        unit_type = "UNIT_SETTLER"
        x = 10
        y = 10
        moves_remaining = 2

    class FarCandidate:
        x = 28
        y = 18
        score = 130.0
        water_type = "fresh"

    class NearCandidate:
        x = 13
        y = 12
        score = 118.0
        water_type = "none"

    class Threat:
        owner_id = 63
        owner_name = "Barbarian"
        x = 12
        y = 11

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, *_args):
            raise AssertionError("settle scan should not fail")

    class FakeGameState:
        async def found_city(self, unit_index):
            return "FAILED|too close"

        async def get_global_settle_scan(self):
            return [FarCandidate(), NearCandidate()]

        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVED|{target_x},{target_y}"

        async def skip_unit(self, unit_index):
            raise AssertionError("near settle candidate should be used before skipping")

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            28,
            "state-0028",
            {
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [Threat()],
            },
        )
    )

    move_call = next(call for call in recorder.calls if call[1].get("action") == "move")
    assert move_call[1]["target_x"] == 13
    assert move_call[1]["target_y"] == 12
    assert recorder.decisions[0]["selected_action"] == "move toward nearby safe settle candidate"


def test_handle_units_moves_settler_toward_horses_before_found_city():
    module = load_runner_module()

    class Unit:
        unit_id = 44
        unit_index = 44
        unit_type = "UNIT_SETTLER"
        x = 67
        y = 42
        moves_remaining = 2

    class Candidate:
        def __init__(self, x, y, score, water_type="none"):
            self.x = x
            self.y = y
            self.score = score
            self.water_type = water_type

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 5

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_global_settle_scan(self):
            return [
                Candidate(67, 42, 160.0, "fresh"),
                Candidate(66, 39, 90.0, "none"),
            ]

        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVED|{target_x},{target_y}"

        async def found_city(self, unit_index):
            raise AssertionError("strategic settle pre-scan should move before founding")

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {
                "overview": {"turn": 18, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "resources": ([], [], [NearHorse()], {}),
                "threats": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["get_global_settle_scan", "unit_action"]
    assert recorder.calls[1][1]["target_x"] == 66
    assert recorder.calls[1][1]["target_y"] == 39
    assert recorder.decisions[0]["selected_action"] == "move toward strategic resource settle candidate"


def test_ranked_trade_destinations_prefers_quest_and_yields():
    module = load_runner_module()

    class Destination:
        def __init__(
            self,
            city_name,
            x,
            y,
            origin_yields,
            dest_yields,
            is_domestic=False,
            has_quest=False,
        ):
            self.city_name = city_name
            self.owner_name = "Domestic" if is_domestic else "City State"
            self.x = x
            self.y = y
            self.origin_yields = origin_yields
            self.dest_yields = dest_yields
            self.is_domestic = is_domestic
            self.has_quest = has_quest
            self.has_trading_post = False

    ranked = module.ranked_trade_destinations(
        [
            Destination("Low", 1, 1, "Gold:2", "", is_domestic=False),
            Destination("Domestic", 2, 2, "Food:2 Prod:1", "Food:1", is_domestic=True),
            Destination("Quest", 3, 3, "Gold:1", "", has_quest=True),
        ]
    )

    assert ranked[0].city_name == "Quest"
    assert ranked[1].city_name == "Domestic"


def test_handle_units_repositions_adjacent_ranged_barbarian_target_for_science_culture_profile():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_SLINGER"
        x = 10
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100
        targets = ["UNIT_SCOUT@11,10(35hp)"]

    class Threat:
        unit_type = "UNIT_SCOUT"
        x = 11
        y = 10
        hp = 35
        max_hp = 100
        distance = 1
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    class FakeRecorder:
        strategy_profile = "science_culture_t50"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class FakeGameState:
        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVED|{unit_index}|{target_x},{target_y}"

        async def attack_unit(self, unit_index, target_x, target_y):
            return f"RANGE_ATTACK|{unit_index}|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {"units": [Unit()], "cities": [{"name": "Capital"}], "threats": [Threat()]},
        )
    )

    assert recorder.calls[0][0] == "unit_action"
    assert recorder.calls[0][1]["action"] == "move"
    assert recorder.calls[0][1]["target_x"] == 9
    assert recorder.calls[0][1]["target_y"] == 10
    assert recorder.decisions[0]["selected_action"] == "reposition ranged unit"


def test_handle_units_golden_age_attacks_adjacent_low_hp_camp_defender():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_SLINGER"
        x = 10
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100
        combat_strength = 5
        ranged_strength = 15
        targets = ["UNIT_SPEARMAN@11,10(17hp)"]

    class Threat:
        unit_type = "UNIT_SPEARMAN"
        x = 11
        y = 10
        hp = 17
        max_hp = 100
        combat_strength = 25
        ranged_strength = 0
        distance = 1
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    class CampTile:
        x = 11
        y = 10
        improvement = "IMPROVEMENT_BARBARIAN_CAMP"
        feature = ""
        resource = ""

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_map_area(self, center_x, center_y, radius):
            return [CampTile()]

        async def attack_unit(self, unit_index, target_x, target_y):
            return f"RANGE_ATTACK|{unit_index}|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            21,
            "state-0021",
            {
                "overview": {"turn": 21, "era_score": 2, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [Threat()],
                "diplomacy": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["get_map_area", "unit_action"]
    assert recorder.calls[1][1]["action"] == "attack"
    assert recorder.calls[1][1]["target_x"] == 11
    assert recorder.decisions[0]["selected_action"] == "attack target"


def test_handle_units_golden_age_wounded_slinger_attacks_low_hp_barbarian():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_SLINGER"
        x = 10
        y = 10
        moves_remaining = 2
        health = 51
        max_health = 100
        combat_strength = 5
        ranged_strength = 15
        targets = ["UNIT_SPEARMAN@11,10(4hp)"]

    class Threat:
        unit_type = "UNIT_SPEARMAN"
        x = 11
        y = 10
        hp = 4
        max_hp = 100
        combat_strength = 25
        ranged_strength = 0
        distance = 1
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def attack_unit(self, unit_index, target_x, target_y):
            return f"RANGE_ATTACK|{unit_index}|{target_x},{target_y}"

        async def heal_unit(self, unit_index):
            raise AssertionError("low-hp barbarian kill should be taken before healing")

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            15,
            "state-0015",
            {
                "overview": {"turn": 15, "era_score": 4, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [Threat()],
                "diplomacy": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["unit_action"]
    assert recorder.calls[0][1]["action"] == "attack"
    assert recorder.calls[0][1]["target_x"] == 11
    assert recorder.decisions[0]["selected_action"] == "attack target"


def test_golden_age_ranked_attack_targets_skip_suicidal_barbarian_attack():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Threat:
        unit_type = "UNIT_SPEARMAN"
        x = 11
        y = 10
        hp = 100
        max_hp = 100
        combat_strength = 25
        ranged_strength = 0
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    unit = {
        "unit_id": 12,
        "unit_type": "UNIT_WARRIOR",
        "x": 10,
        "y": 10,
        "combat_strength": 20,
        "targets": ["UNIT_SPEARMAN@11,10(100hp)"],
    }

    ranked = module.ranked_attack_targets_for_unit(Recorder(), unit, [Threat()], 12, [])

    assert ranked == []


def test_golden_age_ranked_attack_targets_keep_low_hp_barbarian_kill():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Threat:
        unit_type = "UNIT_SPEARMAN"
        x = 11
        y = 10
        hp = 4
        max_hp = 100
        combat_strength = 25
        ranged_strength = 0
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    unit = {
        "unit_id": 12,
        "unit_type": "UNIT_SLINGER",
        "x": 10,
        "y": 10,
        "combat_strength": 5,
        "ranged_strength": 15,
        "targets": ["UNIT_SPEARMAN@11,10(4hp)"],
    }

    ranked = module.ranked_attack_targets_for_unit(Recorder(), unit, [Threat()], 15, [])

    assert len(ranked) == 1
    assert ranked[0]["x"] == 11


def test_golden_age_ranked_attack_targets_skip_wounded_melee_trade():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Threat:
        unit_type = "UNIT_SPEARMAN"
        x = 11
        y = 10
        hp = 26
        max_hp = 100
        combat_strength = 30
        ranged_strength = 0
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    unit = {
        "unit_id": 12,
        "unit_type": "UNIT_WARRIOR",
        "x": 10,
        "y": 10,
        "health": 26,
        "max_health": 100,
        "combat_strength": 18,
        "ranged_strength": 0,
        "targets": ["UNIT_SPEARMAN@11,10(26hp)"],
    }

    ranked = module.ranked_attack_targets_for_unit(Recorder(), unit, [Threat()], 14, [])

    assert ranked == []


def test_handle_units_golden_age_prioritizes_camp_defender_over_generic_barbarian():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_WARRIOR"
        x = 10
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100
        combat_strength = 20
        ranged_strength = 0
        targets = [
            "UNIT_BARBARIAN_HORSEMAN@10,11(66hp)",
            "UNIT_SPEARMAN@11,10(39hp)",
        ]

    class Threat:
        def __init__(self, unit_type, x, y, hp, combat_strength):
            self.unit_type = unit_type
            self.x = x
            self.y = y
            self.hp = hp
            self.max_hp = 100
            self.combat_strength = combat_strength
            self.ranged_strength = 0
            self.distance = 1
            self.owner_id = 63
            self.owner_name = "Barbarian"
            self.is_city_state = False

    class CampTile:
        x = 11
        y = 10
        improvement = "IMPROVEMENT_BARBARIAN_CAMP"
        feature = ""
        resource = ""

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_map_area(self, center_x, center_y, radius):
            return [CampTile()]

        async def attack_unit(self, unit_index, target_x, target_y):
            return f"MELEE_ATTACK|{unit_index}|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            14,
            "state-0014",
            {
                "overview": {"turn": 14, "era_score": 1, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [
                    Threat("UNIT_BARBARIAN_HORSEMAN", 10, 11, 66, 20),
                    Threat("UNIT_SPEARMAN", 11, 10, 39, 25),
                ],
                "diplomacy": [],
            },
        )
    )

    assert recorder.calls[1][1]["action"] == "attack"
    assert recorder.calls[1][1]["target_x"] == 11
    assert recorder.calls[1][1]["target_y"] == 10


def test_handle_units_activates_great_prophet_and_founds_choral_music():
    module = load_runner_module()

    class Unit:
        unit_id = 99
        unit_index = 99
        unit_type = "UNIT_GREAT_PROPHET"
        x = 12
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100

    class AdvisorCity:
        city_name = "Capital"
        district_x = 12
        district_y = 10
        can_activate = True
        distance = 0

    class Advisor:
        target_district = "DISTRICT_HOLY_SITE"
        cities = [AdvisorCity()]

    class Belief:
        def __init__(self, belief_type):
            self.belief_type = belief_type

    class ReligionStatus:
        has_religion = False
        available_religions = [("RELIGION_CONFUCIANISM", "Confucianism")]
        beliefs_by_class = {
            "BELIEF_CLASS_FOLLOWER": [Belief("BELIEF_CHORAL_MUSIC")],
            "BELIEF_CLASS_FOUNDER": [Belief("BELIEF_STEWARDSHIP")],
        }

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_gp_advisor(self, unit_index):
            return Advisor()

        async def activate_great_person(self, unit_index):
            return "OK:GP_ACTIVATED|prophet"

        async def get_religion_founding_status(self):
            return ReligionStatus()

        async def found_religion(self, religion_type, follower_belief, founder_belief):
            return f"OK:RELIGION_FOUNDED|{religion_type}|{follower_belief}|{founder_belief}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            35,
            "state-0035",
            {
                "overview": {
                    "turn": 35,
                    "religions_founded": 1,
                    "religions_max": 5,
                    "our_religion": None,
                },
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [],
                "diplomacy": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == [
        "get_gp_advisor",
        "unit_action",
        "get_religion_beliefs",
        "found_religion",
    ]
    assert recorder.calls[1][1]["action"] == "activate"
    assert recorder.calls[3][1]["follower_belief"] == "BELIEF_CHORAL_MUSIC"
    assert recorder.decisions[0]["selected_action"] == "activate Great Prophet"
    assert "BELIEF_CHORAL_MUSIC" in recorder.decisions[1]["selected_action"]


def test_handle_units_attacks_non_adjacent_barbarian_target_for_science_culture_profile():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_ARCHER"
        x = 10
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100
        targets = ["UNIT_SCOUT@12,10(35hp)"]

    class Threat:
        unit_type = "UNIT_SCOUT"
        x = 12
        y = 10
        hp = 35
        max_hp = 100
        distance = 2
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    class FakeRecorder:
        strategy_profile = "science_culture_t50"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class FakeGameState:
        async def attack_unit(self, unit_index, target_x, target_y):
            return f"RANGE_ATTACK|{unit_index}|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {"units": [Unit()], "cities": [{"name": "Capital"}], "threats": [Threat()]},
        )
    )

    assert recorder.calls[0][0] == "unit_action"
    assert recorder.calls[0][1]["action"] == "attack"
    assert recorder.calls[0][1]["target_x"] == 12
    assert recorder.decisions[0]["selected_action"] == "attack target"


def test_handle_units_moves_clearing_unit_toward_visible_barbarian_without_attack_target():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_SLINGER"
        x = 10
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100
        targets = []

    class Threat:
        unit_type = "UNIT_WARRIOR"
        x = 14
        y = 10
        hp = 100
        max_hp = 100
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    class FakeRecorder:
        strategy_profile = "science_culture_t50"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class FakeGameState:
        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVING_TO|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            30,
            "state-0030",
            {"units": [Unit()], "cities": [{"name": "Capital"}], "threats": [Threat()]},
        )
    )

    assert recorder.calls[0][1]["action"] == "move"
    assert recorder.calls[0][1]["target_x"] == 14
    assert recorder.decisions[0]["selected_action"] == "move toward barbarian threat"


def test_handle_units_moves_golden_age_unit_toward_revealed_camp_before_generic_barbarian():
    module = load_runner_module()

    class Unit:
        unit_id = 12
        unit_index = 12
        unit_type = "UNIT_WARRIOR"
        x = 10
        y = 10
        moves_remaining = 2
        health = 100
        max_health = 100
        targets = []

    class Threat:
        unit_type = "UNIT_WARRIOR"
        x = 20
        y = 20
        hp = 100
        max_hp = 100
        owner_id = 63
        owner_name = "Barbarian"
        is_city_state = False

    class CampTile:
        x = 12
        y = 12
        improvement = "IMPROVEMENT_BARBARIAN_CAMP"
        feature = ""
        resource = ""

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_map_area(self, center_x, center_y, radius):
            assert (center_x, center_y) == (10, 10)
            assert radius == module.GOLDEN_AGE_PUSH_MAP_TARGET_SCAN_RADIUS
            return [CampTile()]

        async def move_unit(self, unit_index, target_x, target_y):
            return f"MOVING_TO|{target_x},{target_y}"

    recorder = FakeRecorder()

    asyncio.run(
        module.handle_units(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {
                "overview": {"era_score": 2, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Unit()],
                "cities": [{"name": "Capital"}],
                "threats": [Threat()],
                "diplomacy": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["get_map_area", "unit_action"]
    assert recorder.calls[1][1]["action"] == "move"
    assert recorder.calls[1][1]["target_x"] == 12
    assert recorder.calls[1][1]["target_y"] == 12
    assert recorder.decisions[0]["selected_action"] == "move toward era-score map target"
    assert recorder.decisions[0]["execution"]["target"]["event_key"] == "clear_barbarian_camp"
    assert recorder.gaps == []


def test_handle_units_starts_idle_trader_route():
    module = load_runner_module()

    class Unit:
        unit_id = 851972
        unit_index = 4
        unit_type = "UNIT_TRADER"
        x = 63
        y = 41
        moves_remaining = 2
        health = 100
        max_health = 100

    class Destination:
        city_name = "Second City"
        owner_name = "Domestic"
        x = 64
        y = 42
        is_domestic = True
        has_quest = False
        has_trading_post = False
        origin_yields = "Food:2 Prod:1"
        dest_yields = "Food:1"

    class FakeRecorder:
        strategy_profile = "explore_scout_first"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, recommendation):
            self.gaps.append((field, reason, recommendation))

    class FakeGameState:
        def __init__(self):
            self.route = None

        async def get_trade_destinations(self, unit_index):
            assert unit_index == 4
            return [Destination()]

        async def make_trade_route(self, unit_index, target_x, target_y):
            self.route = (unit_index, target_x, target_y)
            return "OK:TRADE_ROUTE|Second City"

    recorder = FakeRecorder()
    gs = FakeGameState()

    asyncio.run(
        module.handle_units(
            recorder,
            gs,
            42,
            "state-0042",
            {"units": [Unit()], "cities": [{"name": "Capital"}], "trade_routes": None},
        )
    )

    assert gs.route == (4, 64, 42)
    assert [call[0] for call in recorder.calls] == ["get_trade_destinations", "unit_action"]
    assert recorder.decisions[0]["selected_action"] == "start best trade route"


def test_policy_assignments_fill_empty_slots_by_priority():
    module = load_runner_module()

    class Slot:
        def __init__(self, slot_index, slot_type, current_policy=None):
            self.slot_index = slot_index
            self.slot_type = slot_type
            self.current_policy = current_policy

    class Policy:
        def __init__(self, policy_type, slot_type):
            self.policy_type = policy_type
            self.slot_type = slot_type

    class Status:
        slots = [
            Slot(0, "SLOT_MILITARY"),
            Slot(1, "SLOT_ECONOMIC", "POLICY_GOD_KING"),
            Slot(2, "SLOT_ECONOMIC"),
        ]
        available_policies = [
            Policy("POLICY_DISCIPLINE", "SLOT_MILITARY"),
            Policy("POLICY_AGOGE", "SLOT_MILITARY"),
            Policy("POLICY_GOD_KING", "SLOT_ECONOMIC"),
            Policy("POLICY_URBAN_PLANNING", "SLOT_ECONOMIC"),
        ]

    assert module.policy_assignments_for_empty_slots(Status()) == {
        0: "POLICY_AGOGE",
        2: "POLICY_URBAN_PLANNING",
    }


def test_unit_can_build_improvement_respects_valid_improvements():
    module = load_runner_module()

    class Unit:
        valid_improvements = ["IMPROVEMENT_FARM"]

    assert module.unit_can_build_improvement(Unit(), "IMPROVEMENT_FARM")
    assert not module.unit_can_build_improvement(Unit(), "IMPROVEMENT_LUMBER_MILL")


def test_episode_recorder_writes_active_asset_snapshot(monkeypatch, tmp_path):
    module = load_runner_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)

    recorder = module.EpisodeRecorder("ep_assets", "test 1")
    recorder.write_manifest()

    active_assets = json.loads(recorder.active_assets_path.read_text(encoding="utf-8"))
    manifest = json.loads(recorder.manifest_path.read_text(encoding="utf-8"))

    assert active_assets["asset_count"] >= 7
    assert manifest["asset_snapshot"]["status"] == "present"
    assert manifest["asset_snapshot"]["active_assets"][0]["asset_id"]


def test_report_only_view_reports_missing_active_asset_snapshot(monkeypatch, tmp_path):
    module = load_runner_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    episode = tmp_path / "episodes" / "old_ep"
    (episode / "raw" / "civ6_states").mkdir(parents=True)
    (episode / "raw" / "saves").mkdir(parents=True)
    (episode / "derived").mkdir(parents=True)
    (episode / "outcome").mkdir(parents=True)
    (episode / "header.json").write_text("{}", encoding="utf-8")
    (episode / "raw" / "tool_calls.jsonl").write_text("", encoding="utf-8")
    (episode / "raw" / "mcp.jsonl").write_text("", encoding="utf-8")
    (episode / "raw" / "saves" / "save_index.jsonl").write_text("", encoding="utf-8")
    (episode / "derived" / "decision_atoms.jsonl").write_text("", encoding="utf-8")
    (episode / "raw" / "civ6_states" / "state-0001.json").write_text(
        json.dumps({"snapshot_id": "state-0001", "turn": 1}),
        encoding="utf-8",
    )

    view = module.ExistingEpisodeReportView("old_ep")
    view.write_manifest()
    manifest = json.loads(view.manifest_path.read_text(encoding="utf-8"))

    assert not view.active_assets_path.exists()
    assert manifest["asset_snapshot"]["status"] == "missing"
    assert any(gap["field"] == "assets_snapshot.active_assets" for gap in view.missing_fields)


def test_phase1_observe_accepts_golden_age_push_profile(monkeypatch):
    module = load_runner_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codex-hl-civ6-phase1-observe",
            "--turns",
            "50",
            "--strategy-profile",
            "golden_age_push",
        ],
    )

    args = module.parse_args()

    assert args.strategy_profile == "golden_age_push"


def test_golden_age_push_prioritizes_military_when_era_gap_remains():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {"era_score": 10, "era_golden_threshold": 19},
            "cities": [{"name": "Capital"}, {"name": "Second"}, {"name": "Third"}],
            "units": [{"unit_type": "UNIT_WARRIOR"}, {"unit_type": "UNIT_SLINGER"}],
            "threats": [],
        },
    )

    assert priority.index("UNIT_HORSEMAN") < priority.index("BUILDING_MONUMENT")
    assert priority.index("UNIT_ARCHER") < priority.index("DISTRICT_CAMPUS")
    assert priority.index("PROJECT_HOLY_SITE_PRAYERS") < priority.index("UNIT_HORSEMAN")
    assert priority.index("DISTRICT_HOLY_SITE") < priority.index("BUILDING_MONUMENT")


def test_golden_age_push_ancient_prioritizes_scouting_before_extra_military():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {
                "era_name": "远古时代",
                "era_score": 1,
                "era_golden_threshold": 19,
            },
            "cities": [{"name": "Capital"}],
            "units": [{"unit_type": "UNIT_WARRIOR"}],
            "threats": [],
        },
    )

    assert priority.index("UNIT_SCOUT") < priority.index("UNIT_ARCHER")
    assert priority.index("UNIT_SCOUT") < priority.index("UNIT_SLINGER")


def test_golden_age_push_ancient_stops_replacing_scouts_after_opening_window():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {
                "turn": 28,
                "era_name": "杩滃彜鏃朵唬",
                "era_score": 4,
                "era_golden_threshold": 19,
            },
            "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT"}]},
            "cities": [{"name": "Capital"}, {"name": "Second"}],
            "units": [
                {"unit_type": "UNIT_WARRIOR"},
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_SCOUT"},
            ],
            "threats": [],
        },
    )

    assert priority.index("UNIT_SETTLER") < priority.index("UNIT_SCOUT")


def test_golden_age_push_ancient_expands_after_basic_screen():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {
                "era_name": "远古时代",
                "era_score": 3,
                "era_golden_threshold": 19,
            },
            "cities": [{"name": "Capital"}],
            "units": [
                {"unit_type": "UNIT_WARRIOR"},
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SCOUT"},
            ],
            "threats": [],
        },
    )

    assert priority.index("UNIT_SETTLER") < priority.index("UNIT_ARCHER")
    assert priority.index("UNIT_SETTLER") < priority.index("DISTRICT_CAMPUS")


def test_golden_age_push_reserves_builder_purchase_queue():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Settler:
        unit_type = "UNIT_SETTLER"

    class Scout:
        unit_type = "UNIT_SCOUT"

    class HorseStockpile:
        name = "HORSES"
        amount = 0
        cap = 25
        per_turn = 0
        demand = 0
        imported = 0

    class Option:
        category = "UNIT"
        item_name = "UNIT_BUILDER"
        gold_cost = 100

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {"turn": 16, "gold": 100, "era_score": 5, "era_golden_threshold": 19},
            "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
            "units": [Settler(), Scout(), Scout()],
            "production": {"1": [Option()]},
            "resources": ([HorseStockpile()], [], [], {}),
        },
    )

    assert priority.index("UNIT_SLINGER") < priority.index("UNIT_BUILDER")
    assert priority.index("BUILDING_MONUMENT") < priority.index("UNIT_BUILDER")


def test_golden_age_push_ancient_builds_builder_before_monument_when_settler_exists():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {
                "era_name": "杩滃彜鏃朵唬",
                "era_score": 3,
                "era_golden_threshold": 19,
            },
            "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT"}]},
            "cities": [{"name": "Capital"}],
            "units": [
                {"unit_type": "UNIT_WARRIOR"},
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SETTLER"},
            ],
            "threats": [],
        },
    )

    assert priority.index("UNIT_BUILDER") < priority.index("BUILDING_MONUMENT")


def test_golden_age_push_ancient_prioritizes_horse_builder_before_religion_project():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 2

    priority = module.production_priority_for(
        Recorder(),
        {
            "overview": {
                "turn": 18,
                "era_score": 5,
                "era_golden_threshold": 19,
            },
            "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
            "cities": [{"name": "Capital"}],
            "units": [
                {"unit_type": "UNIT_WARRIOR"},
                {"unit_type": "UNIT_SLINGER"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SCOUT"},
                {"unit_type": "UNIT_SETTLER"},
            ],
            "resources": ([], [], [NearHorse()], {}),
            "threats": [],
        },
    )

    assert priority.index("UNIT_HORSEMAN") < priority.index("PROJECT_HOLY_SITE_PRAYERS")
    assert priority.index("UNIT_BUILDER") < priority.index("PROJECT_HOLY_SITE_PRAYERS")
    assert priority.index("UNIT_BUILDER") < priority.index("DISTRICT_HOLY_SITE")


def test_golden_age_push_risks_settler_move_after_opening_if_no_adjacent_barbarian():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Settler:
        x = 62
        y = 41

    class Threat:
        owner_id = 63
        owner_name = "Barbarian"
        x = 60
        y = 39

    snapshot = {
        "overview": {"era_score": 12, "era_golden_threshold": 19},
        "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
        "threats": [Threat()],
    }

    assert module.should_risk_golden_age_settler_move(Recorder(), snapshot, Settler(), 24) is True
    Threat.x = 61
    Threat.y = 41
    assert module.should_risk_golden_age_settler_move(Recorder(), snapshot, Settler(), 24) is False


def test_maybe_choose_pantheon_prefers_divine_spark():
    module = load_runner_module()

    class Belief:
        def __init__(self, belief_type):
            self.belief_type = belief_type

    class Status:
        has_pantheon = False
        available_beliefs = [
            Belief("BELIEF_GOD_OF_THE_FORGE"),
            Belief("BELIEF_DIVINE_SPARK"),
        ]

    class Recorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class GameState:
        async def choose_pantheon(self, belief_type):
            return f"OK:PANTHEON_FOUNDED|{belief_type}"

    recorder = Recorder()

    asyncio.run(
        module.maybe_choose_pantheon(
            recorder,
            GameState(),
            12,
            "state-0012",
            {
                "overview": {"turn": 12},
                "cities": [{"name": "Capital"}],
                "units": [],
                "threats": [],
                "pantheon_status": Status(),
            },
        )
    )

    assert recorder.calls[0][0] == "choose_pantheon"
    assert recorder.calls[0][1]["belief_type"] == "BELIEF_DIVINE_SPARK"
    assert recorder.decisions[0]["selected_action"] == "choose BELIEF_DIVINE_SPARK"


def test_maybe_found_religion_uses_choral_music():
    module = load_runner_module()

    class Belief:
        def __init__(self, belief_type):
            self.belief_type = belief_type

    class Status:
        has_religion = False
        available_religions = [
            ("RELIGION_BUDDHISM", "Buddhism"),
            ("RELIGION_CONFUCIANISM", "Confucianism"),
        ]
        beliefs_by_class = {
            "BELIEF_CLASS_FOLLOWER": [Belief("BELIEF_CHORAL_MUSIC")],
            "BELIEF_CLASS_FOUNDER": [
                Belief("BELIEF_CHURCH_PROPERTY"),
                Belief("BELIEF_STEWARDSHIP"),
            ],
        }

    class Recorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class GameState:
        async def get_religion_founding_status(self):
            return Status()

        async def found_religion(self, religion_type, follower_belief, founder_belief):
            return f"OK:RELIGION_FOUNDED|{religion_type}|{follower_belief}|{founder_belief}"

    recorder = Recorder()

    asyncio.run(
        module.maybe_found_religion_with_choral(
            recorder,
            GameState(),
            40,
            "state-0040",
            {
                "overview": {
                    "turn": 40,
                    "religions_founded": 1,
                    "religions_max": 5,
                    "our_religion": None,
                },
                "cities": [{"name": "Capital"}],
                "units": [{"unit_type": "UNIT_GREAT_PROPHET"}],
                "threats": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == [
        "get_religion_beliefs",
        "found_religion",
    ]
    assert recorder.calls[1][1]["religion_type"] == "RELIGION_CONFUCIANISM"
    assert recorder.calls[1][1]["follower_belief"] == "BELIEF_CHORAL_MUSIC"
    assert recorder.calls[1][1]["founder_belief"] == "BELIEF_STEWARDSHIP"
    assert "BELIEF_CHORAL_MUSIC" in recorder.decisions[0]["selected_action"]


def test_golden_age_achieved_uses_current_age_after_rollover():
    module = load_runner_module()

    snapshot = {
        "overview": {
            "era_name": "古典时期",
            "era_score": 1,
            "era_golden_threshold": 18,
        },
        "empire": {
            "players": [
                {
                    "pid": 0,
                    "era": "ERA_CLASSICAL",
                    "age": "GOLDEN",
                }
            ]
        },
    }

    assert module.golden_age_achieved(snapshot) is True
    audit = module.t50_strategy_audit(snapshot)
    assert audit["current_age"] == "GOLDEN"
    assert audit["golden_age_achieved"] is True


def test_t50_strategy_audit_records_era_gold_governor_resource_and_war_targets():
    module = load_runner_module()

    class Governor:
        governor_type = "GOVERNOR_THE_EDUCATOR"
        name = "Pingala"
        assigned_city_id = -1
        assigned_city_name = "Unassigned"
        is_established = False
        turns_to_establish = 0

    class Governors:
        appointed = [Governor()]

    class Stockpile:
        name = "HORSES"
        amount = 30
        cap = 50
        per_turn = 2
        demand = 0
        imported = 0

    class OwnedResource:
        name = "HORSES"
        resource_class = "strategic"
        improved = False
        x = 5
        y = 6

    class Civ:
        player_id = 2
        civ_name = "Neighbor"
        leader_name = "Leader"
        has_met = True
        is_at_war = False
        diplomatic_state = "NEUTRAL"
        military_strength = 80
        available_actions = ["DECLARE_SURPRISE_WAR"]
        visible_cities = []

    class Notification:
        type_name = "NOTIFICATION_TRIBAL_VILLAGE"
        message = "Tribal village discovered near the capital."

    audit = module.t50_strategy_audit(
        {
            "turn": 34,
            "overview": {
                "era_name": "ERA_ANCIENT",
                "era_score": 10,
                "era_golden_threshold": 19,
                "gold": 474,
                "gold_per_turn": 12,
            },
            "governors": Governors(),
            "resources": ([Stockpile()], [OwnedResource()], [], {}),
            "diplomacy": [Civ()],
            "notifications": [Notification()],
            "threats": [],
        }
    )

    assert audit["era_score_gap"] == 9
    assert audit["gold_conversion_pressure"] is True
    assert audit["unassigned_governors"][0]["city"] == "NONE"
    assert audit["strategic_resources"][0]["surplus_after_reserve"] == 10
    assert audit["unimproved_strategic_resources"][0]["name"] == "HORSES"
    assert audit["war_targets"][0]["player_id"] == 2
    assert audit["active_golden_age_target_events"][0]["event_key"] == "meet_civilization"
    assert "tribal_village" in {
        event["event_key"] for event in audit["active_golden_age_target_events"]
    }


def test_golden_age_target_events_prioritize_explicit_era_score_paths():
    module = load_runner_module()

    class Notification:
        type_name = "NOTIFICATION_NATURAL_WONDER"
        message = "Natural wonder discovered."

    class ResearchCivic:
        completed_tech_count = 2
        completed_civic_count = 1

    events = module.golden_age_target_events(
        {
            "notifications": [Notification()],
            "research_civic": ResearchCivic(),
            "units": [{"unit_type": "UNIT_HORSEMAN"}],
            "cities": [],
            "diplomacy": [],
            "resources": ([], [], [], {}),
            "threats": [],
        }
    )

    by_key = {event["event_key"]: event for event in events}
    assert by_key["natural_wonder"]["active"] is True
    assert by_key["first_new_era_tech_or_civic"]["active"] is True
    assert by_key["first_strategic_resource_unit"]["active"] is True
    assert [event["event_key"] for event in events[:4]] == [
        "clear_barbarian_camp",
        "meet_civilization",
        "tribal_village",
        "natural_wonder",
    ]


def test_governor_assignment_target_prefers_pingala_science_culture_city():
    module = load_runner_module()

    class City:
        def __init__(self, city_id, name, science, culture, production):
            self.city_id = city_id
            self.name = name
            self.science = science
            self.culture = culture
            self.production = production
            self.population = 1

    target = module.governor_assignment_target(
        [
            City(1, "Capital", 3, 4, 5),
            City(2, "Campus City", 6, 5, 2),
        ],
        "GOVERNOR_THE_EDUCATOR",
    )

    assert target.city_id == 2


def test_maybe_handle_governance_blockers_assigns_after_appointment():
    module = load_runner_module()

    class GovernorType:
        governor_type = "GOVERNOR_THE_EDUCATOR"

    class Status:
        can_appoint = True
        available_to_appoint = [GovernorType()]
        appointed = []

    class City:
        city_id = 1
        name = "Capital"
        science = 5
        culture = 5
        production = 4
        population = 2

    class FakeRecorder:
        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_governors(self):
            return Status()

        async def appoint_governor(self, governor_type):
            return f"OK:APPOINTED|{governor_type}"

        async def assign_governor(self, governor_type, city_id):
            return f"OK:ASSIGNED|{governor_type}|{city_id}"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_handle_governance_blockers(
            recorder,
            FakeGameState(),
            21,
            "state-0021",
            {
                "notifications": "GOVERNOR_APPOINTMENT_AVAILABLE",
                "cities": [City()],
                "units": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == [
        "get_governors",
        "appoint_governor",
        "assign_governor",
    ]
    assert recorder.decisions[-1]["selected_action"] == "assign GOVERNOR_THE_EDUCATOR to Capital"


def test_maybe_handle_governance_blockers_sends_best_envoy_target():
    module = load_runner_module()

    class CityState:
        def __init__(self, player_id, name, city_state_type, envoys_sent=0):
            self.player_id = player_id
            self.name = name
            self.city_state_type = city_state_type
            self.envoys_sent = envoys_sent
            self.can_send_envoy = True

    class EnvoyStatus:
        tokens_available = 1
        city_states = [
            CityState(3, "Militaristic CS", "Militaristic"),
            CityState(4, "Scientific CS", "Scientific"),
        ]

    class Notification:
        type_name = "NOTIFICATION_GIVE_INFLUENCE_TOKEN"
        message = "Envoy token available."

    class FakeRecorder:
        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_city_states(self):
            return EnvoyStatus()

        async def send_envoy(self, player_id):
            return f"OK:ENVOY_SENT|{player_id}"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_handle_governance_blockers(
            recorder,
            FakeGameState(),
            20,
            "state-0020",
            {
                "notifications": [Notification()],
                "cities": [],
                "units": [],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["get_city_states", "send_envoy"]
    assert recorder.calls[1][1]["player_id"] == 4
    assert recorder.decisions[0]["selected_action"] == "send envoy to Scientific CS"


def test_select_gold_purchase_prefers_best_military_unit():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Option:
        def __init__(self, item_name, gold_cost):
            self.category = "UNIT"
            self.item_name = item_name
            self.gold_cost = gold_cost

    selected = module.select_gold_purchase(
        {
            "overview": {"gold": 220},
            "cities": [City()],
            "production": {
                "1": [
                    Option("UNIT_WARRIOR", 80),
                    Option("UNIT_HORSEMAN", 160),
                    Option("UNIT_BUILDER", 90),
                ]
            },
            "resources": ([], [], [], {}),
        }
    )

    assert selected["item_name"] == "UNIT_HORSEMAN"
    assert selected["reason"] == "military_unit"


def test_golden_age_ancient_gold_threshold_buys_slinger_over_extra_scout():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Unit:
        def __init__(self, unit_type):
            self.unit_type = unit_type

    class Option:
        def __init__(self, item_name, gold_cost):
            self.category = "UNIT"
            self.item_name = item_name
            self.gold_cost = gold_cost

    snapshot = {
        "overview": {"gold": 65, "era_score": 1, "era_golden_threshold": 19},
        "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
        "cities": [City()],
        "units": [Unit("UNIT_SCOUT"), Unit("UNIT_SCOUT"), Unit("UNIT_WARRIOR")],
        "production": {"1": [Option("UNIT_SCOUT", 60), Option("UNIT_SLINGER", 65)]},
        "resources": ([], [], [], {}),
    }

    selected = module.select_gold_purchase(snapshot)

    assert module.golden_age_gold_spend_threshold(snapshot) == 65
    assert selected["item_name"] == "UNIT_SLINGER"


def test_golden_age_gold_purchase_skips_scout_after_opening_window():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Unit:
        unit_type = "UNIT_SCOUT"

    class Option:
        category = "UNIT"
        item_name = "UNIT_SCOUT"
        gold_cost = 60

    selected = module.select_gold_purchase(
        {
            "overview": {
                "turn": 24,
                "gold": 70,
                "era_score": 8,
                "era_golden_threshold": 19,
            },
            "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
            "cities": [City()],
            "units": [Unit()],
            "production": {"1": [Option()]},
            "resources": ([], [], [], {}),
        }
    )

    assert selected is None


def test_maybe_spend_gold_buys_builder_before_basic_military_for_horse_path():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Settler:
        unit_type = "UNIT_SETTLER"

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 2

    class Option:
        def __init__(self, item_name, gold_cost):
            self.category = "UNIT"
            self.item_name = item_name
            self.gold_cost = gold_cost

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def purchase_item(self, city_id, category, item_name, yield_type):
            return f"PURCHASED|{item_name}"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {
                "overview": {"turn": 18, "gold": 90, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Settler()],
                "cities": [City()],
                "production": {"1": [Option("UNIT_SLINGER", 65), Option("UNIT_BUILDER", 90)]},
                "resources": ([], [], [NearHorse()], {}),
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["purchase_item"]
    assert recorder.calls[0][1]["item_name"] == "UNIT_BUILDER"
    assert recorder.decisions[0]["selected_action"] == "purchase UNIT_BUILDER with gold"


def test_maybe_spend_gold_buys_builder_for_pending_strategic_settle():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Settler:
        unit_type = "UNIT_SETTLER"

    class HorseStockpile:
        name = "HORSES"
        amount = 0
        cap = 25
        per_turn = 0
        demand = 0
        imported = 0

    class Option:
        def __init__(self, item_name, gold_cost):
            self.category = "UNIT"
            self.item_name = item_name
            self.gold_cost = gold_cost

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def purchase_item(self, city_id, category, item_name, yield_type):
            return f"PURCHASED|{item_name}"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {
                "overview": {"turn": 18, "gold": 95, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Settler()],
                "cities": [City()],
                "production": {"1": [Option("UNIT_WARRIOR", 80), Option("UNIT_BUILDER", 90)]},
                "resources": ([HorseStockpile()], [], [], {}),
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["purchase_item"]
    assert recorder.calls[0][1]["item_name"] == "UNIT_BUILDER"
    assert recorder.decisions[0]["selected_action"] == "purchase UNIT_BUILDER with gold"


def test_maybe_spend_gold_does_not_fallback_after_blocked_builder_purchase():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Settler:
        unit_type = "UNIT_SETTLER"

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 2

    class Option:
        def __init__(self, item_name, gold_cost):
            self.category = "UNIT"
            self.item_name = item_name
            self.gold_cost = gold_cost

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def purchase_item(self, city_id, category, item_name, yield_type):
            if item_name == "UNIT_BUILDER":
                return "Error: STACKING_CONFLICT|Cannot purchase UNIT_BUILDER"
            raise AssertionError("blocked builder purchase must not fall back to basic military")

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            16,
            "state-0016",
            {
                "overview": {"turn": 16, "gold": 100, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Settler()],
                "cities": [City()],
                "production": {"1": [Option("UNIT_BUILDER", 100), Option("UNIT_WARRIOR", 80)]},
                "resources": ([], [], [NearHorse()], {}),
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["purchase_item"]
    assert recorder.calls[0][1]["item_name"] == "UNIT_BUILDER"
    assert recorder.decisions[0]["selected_action"] == "purchase UNIT_BUILDER with gold"


def test_maybe_spend_gold_holds_when_builder_not_purchasable_during_reserve():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Settler:
        unit_type = "UNIT_SETTLER"

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 2

    class Option:
        category = "UNIT"
        item_name = "UNIT_WARRIOR"
        gold_cost = 80

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def purchase_item(self, *args):
            raise AssertionError("reserve should not buy basic military when builder is absent")

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            17,
            "state-0017",
            {
                "overview": {"turn": 17, "gold": 105, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Settler()],
                "cities": [City()],
                "production": {"1": [Option()]},
                "resources": ([], [], [NearHorse()], {}),
            },
        )
    )

    assert recorder.calls == []
    assert recorder.decisions == []


def test_maybe_spend_gold_saves_for_builder_instead_of_basic_slinger():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Settler:
        unit_type = "UNIT_SETTLER"

    class NearHorse:
        name = "HORSES"
        resource_class = "strategic"
        x = 65
        y = 37
        distance = 2

    class Option:
        def __init__(self, item_name, gold_cost):
            self.category = "UNIT"
            self.item_name = item_name
            self.gold_cost = gold_cost

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def purchase_item(self, *args):
            raise AssertionError("gold should be held until the builder is affordable")

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            18,
            "state-0018",
            {
                "overview": {"turn": 18, "gold": 65, "era_score": 5, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "units": [Settler()],
                "cities": [City()],
                "production": {"1": [Option("UNIT_SLINGER", 65), Option("UNIT_BUILDER", 90)]},
                "resources": ([], [], [NearHorse()], {}),
            },
        )
    )

    assert recorder.calls == []
    assert recorder.decisions[0]["selected_action"] == "save gold for strategic-resource builder"


def test_maybe_set_city_production_overrides_builder_queue_for_horseman():
    module = load_runner_module()

    class City:
        def __init__(self, city_id, name, currently_building):
            self.city_id = city_id
            self.name = name
            self.currently_building = currently_building
            self.production_turns_left = 4

    class Option:
        def __init__(self, item_name, turns):
            self.category = "UNIT"
            self.item_name = item_name
            self.turns = turns
            self.gold_cost = -1
            self.is_repair = False

    class Stockpile:
        name = "HORSES"
        amount = 20
        cap = 25
        per_turn = 4
        demand = 0
        imported = 0

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def set_city_production(self, city_id, category, item_name, target_x, target_y):
            return f"PRODUCING|{item_name}|3 turns"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_set_city_production(
            recorder,
            FakeGameState(),
            27,
            "state-0027",
            {
                "overview": {"turn": 27, "era_score": 9, "era_golden_threshold": 19},
                "empire": {"players": [{"pid": 0, "era": "ERA_ANCIENT", "age": "NORMAL"}]},
                "cities": [
                    City(1, "Capital", "UNIT_BUILDER"),
                    City(2, "Second", "UNIT_BUILDER"),
                ],
                "units": [],
                "production": {
                    "1": [Option("UNIT_BUILDER", 3), Option("UNIT_HORSEMAN", 4)],
                    "2": [],
                },
                "resources": ([Stockpile()], [], [], {}),
            },
        )
    )

    assert recorder.calls[0][0] == "set_city_production"
    assert recorder.calls[0][1]["item_name"] == "UNIT_HORSEMAN"
    assert any(
        decision["selected_action"] == "UNIT UNIT_HORSEMAN"
        for decision in recorder.decisions
    )


def test_golden_age_gold_threshold_reverts_after_ancient_gate():
    module = load_runner_module()

    assert (
        module.golden_age_gold_spend_threshold(
            {
                "overview": {"gold": 90, "era_score": 3, "era_golden_threshold": 21},
                "empire": {"players": [{"pid": 0, "era": "ERA_CLASSICAL", "age": "NORMAL"}]},
            }
        )
        == module.GOLDEN_AGE_PUSH_MIN_GOLD_TO_SPEND
    )


def test_parse_unit_upgrade_check_result():
    module = load_runner_module()

    parsed = module.parse_unit_upgrade_check_result(
        "noise\nUPGRADE|UNIT_SLINGER|UNIT_ARCHER|Archer|60|220"
    )

    assert parsed["current_type"] == "UNIT_SLINGER"
    assert parsed["upgrade_type"] == "UNIT_ARCHER"
    assert parsed["gold_cost"] == 60
    assert parsed["available_gold"] == 220


def test_maybe_spend_gold_prefers_upgrade_before_unit_purchase():
    module = load_runner_module()

    class Unit:
        unit_id = 11
        unit_type = "UNIT_SLINGER"

    class City:
        city_id = 1
        name = "Capital"

    class Option:
        category = "UNIT"
        item_name = "UNIT_HORSEMAN"
        gold_cost = 160

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def check_unit_upgrade(self, unit_id):
            return "UPGRADE|UNIT_SLINGER|UNIT_ARCHER|Archer|60|220"

        async def upgrade_unit(self, unit_id):
            return "UPGRADED|UNIT_SLINGER -> UNIT_ARCHER"

        async def purchase_item(self, *args):
            raise AssertionError("unit purchase should not run before upgrade")

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            35,
            "state-0035",
            {
                "overview": {"gold": 220},
                "units": [Unit()],
                "cities": [City()],
                "production": {"1": [Option()]},
                "resources": ([], [], [], {}),
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["check_unit_upgrade", "upgrade_unit"]
    assert recorder.decisions[0]["selected_action"] == "upgrade UNIT_SLINGER to UNIT_ARCHER with gold"


def test_select_strategic_tile_purchase_prefers_horses():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Tile:
        def __init__(self, x, y, cost, resource):
            self.x = x
            self.y = y
            self.cost = cost
            self.terrain = "Plains"
            self.resource = resource
            self.resource_class = "strategic"

    selected = module.select_strategic_tile_purchase(
        {"overview": {"gold": 200}, "cities": [City()]},
        {"1": [Tile(3, 4, 90, "RESOURCE_IRON"), Tile(5, 6, 140, "Horses")]},
    )

    assert selected["resource_key"] == "HORSES"
    assert selected["x"] == 5
    assert selected["y"] == 6


def test_select_strategic_tile_purchase_skips_resource_with_income():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Stockpile:
        name = "HORSES"
        amount = 25
        cap = 25
        per_turn = 4
        demand = 0
        imported = 0

    class Tile:
        def __init__(self, x, y, cost, resource):
            self.x = x
            self.y = y
            self.cost = cost
            self.terrain = "Plains"
            self.resource = resource
            self.resource_class = "strategic"

    selected = module.select_strategic_tile_purchase(
        {
            "overview": {"gold": 200},
            "cities": [City()],
            "resources": ([Stockpile()], [], [], {}),
        },
        {"1": [Tile(3, 4, 90, "RESOURCE_HORSES"), Tile(5, 6, 140, "RESOURCE_IRON")]},
    )

    assert selected["resource_key"] == "IRON"
    assert selected["x"] == 5


def test_maybe_spend_gold_purchases_strategic_tile_when_no_military_buy():
    module = load_runner_module()

    class City:
        city_id = 1
        name = "Capital"

    class Tile:
        x = 5
        y = 6
        cost = 140
        terrain = "Plains"
        resource = "RESOURCE_HORSES"
        resource_class = "strategic"

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_purchasable_tiles(self, city_id):
            return [Tile()]

        async def purchase_tile(self, city_id, x, y):
            return "TILE_PURCHASED|(5,6)|cost:140"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_spend_gold_for_t50(
            recorder,
            FakeGameState(),
            35,
            "state-0035",
            {
                "overview": {"gold": 200},
                "units": [],
                "cities": [City()],
                "production": {"1": []},
                "resources": ([], [], [], {}),
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["get_purchasable_tiles", "purchase_tile"]
    assert recorder.decisions[0]["selected_action"] == "purchase HORSES tile (5,6) with gold"


def test_resource_trade_candidate_selects_surplus_horses_and_known_civ():
    module = load_runner_module()

    class Stockpile:
        name = "HORSES"
        amount = 31
        cap = 50
        per_turn = 3
        demand = 0
        imported = 0

    class Civ:
        player_id = 4
        civ_name = "Buyer"
        has_met = True
        is_at_war = False
        relationship_score = 1

    candidate = module.resource_trade_candidate(
        {"resources": ([Stockpile()], [], [], {}), "diplomacy": [Civ()]}
    )

    assert candidate["resource_type"] == "RESOURCE_HORSES"
    assert candidate["other_player_id"] == 4


def test_resource_trader_tests_and_proposes_surplus_horse_sale():
    module = load_runner_module()

    class Stockpile:
        name = "HORSES"
        amount = 31
        cap = 50
        per_turn = 3
        demand = 0
        imported = 0

    class Civ:
        player_id = 4
        civ_name = "Buyer"
        has_met = True
        is_at_war = False
        relationship_score = 1

    class DealOptions:
        their_gold = 120
        their_gpt = 0

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        async def get_deal_options(self, other_player_id):
            assert other_player_id == 4
            return DealOptions()

        async def test_trade(self, other_player_id, offer_items, request_items):
            assert other_player_id == 4
            assert offer_items == [
                {"type": "RESOURCE", "name": "RESOURCE_HORSES", "amount": 1, "duration": 30}
            ]
            assert request_items == [{"type": "GOLD", "amount": 90, "duration": 0}]
            return "ACCEPTABLE"

        async def propose_trade(self, other_player_id, offer_items, request_items):
            assert other_player_id == 4
            return "OK:DEAL_PROPOSED"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_trade_surplus_strategic_resources(
            recorder,
            FakeGameState(),
            36,
            "state-0036",
            {"resources": ([Stockpile()], [], [], {}), "diplomacy": [Civ()]},
        )
    )

    assert [call[0] for call in recorder.calls] == [
        "get_trade_options",
        "test_trade",
        "propose_trade",
    ]
    assert recorder.decisions[0]["selected_action"] == "sell surplus strategic resource"
    assert recorder.decisions[0]["execution"]["tool"] == "test_trade + propose_trade"
    assert recorder.gaps == []


def test_resource_trader_accepts_ai_counter_for_wasted_surplus():
    module = load_runner_module()

    class Stockpile:
        name = "HORSES"
        amount = 31
        cap = 50
        per_turn = 3
        demand = 0
        imported = 0

    class Civ:
        player_id = 4
        civ_name = "Buyer"
        has_met = True
        is_at_war = False
        relationship_score = 1

    class DealOptions:
        their_gold = 120
        their_gpt = 0

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []
            self.gaps = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

        def add_gap(self, field, reason, next_step):
            self.gaps.append((field, reason, next_step))

    class FakeGameState:
        def __init__(self):
            self.proposed_request_items = None

        async def get_deal_options(self, other_player_id):
            return DealOptions()

        async def test_trade(self, other_player_id, offer_items, request_items):
            assert request_items == [{"type": "GOLD", "amount": 90, "duration": 0}]
            return (
                "AI counter-offer (what they consider fair):\n"
                "  We give: Horses (30 turns)\n"
                "  They give: 4 gold"
            )

        async def propose_trade(self, other_player_id, offer_items, request_items):
            self.proposed_request_items = request_items
            return "OK:DEAL_PROPOSED_COUNTER"

    recorder = FakeRecorder()
    game_state = FakeGameState()
    asyncio.run(
        module.maybe_trade_surplus_strategic_resources(
            recorder,
            game_state,
            36,
            "state-0036",
            {"resources": ([Stockpile()], [], [], {}), "diplomacy": [Civ()]},
        )
    )

    assert [call[0] for call in recorder.calls] == [
        "get_trade_options",
        "test_trade",
        "propose_trade",
    ]
    assert game_state.proposed_request_items == [{"type": "GOLD", "amount": 4, "duration": 0}]
    assert recorder.decisions[0]["selected_action"] == "sell surplus strategic resource"
    assert recorder.decisions[0]["execution"]["counter_request_items"] == [
        {"type": "GOLD", "amount": 4, "duration": 0}
    ]


def test_opportunistic_war_candidate_requires_turn_force_and_declaration_action():
    module = load_runner_module()

    class Civ:
        player_id = 2
        civ_name = "Neighbor"
        leader_name = "Leader"
        has_met = True
        is_at_war = False
        military_strength = 60
        available_actions = ["DECLARE_SURPRISE_WAR"]
        visible_cities = []

    class Threat:
        unit_type = "UNIT_SCOUT"
        x = 7
        y = 8
        hp = 35
        max_hp = 100
        combat_strength = 10
        ranged_strength = 0
        owner_id = 2

    units = [
        {"unit_id": 1, "unit_type": "UNIT_WARRIOR", "combat_strength": 20, "targets": []},
        {
            "unit_id": 2,
            "unit_type": "UNIT_SLINGER",
            "combat_strength": 5,
            "ranged_strength": 15,
            "targets": ["Enemy SCOUT @7,8(35hp)"],
        },
        {"unit_id": 3, "unit_type": "UNIT_ARCHER", "ranged_strength": 25, "targets": []},
    ]
    snapshot = {"diplomacy": [Civ()], "units": units, "threats": [Threat()]}

    assert module.opportunistic_war_candidate(snapshot, 29) is None
    assert module.opportunistic_war_candidate({**snapshot, "threats": []}, 30) is None
    candidate = module.opportunistic_war_candidate(snapshot, 30)

    assert candidate["other_player_id"] == 2
    assert candidate["action"] == "DECLARE_SURPRISE_WAR"
    assert candidate["favorable_attack_count"] == 1


def test_opportunistic_war_gate_declares_only_after_tactical_window():
    module = load_runner_module()

    class Civ:
        player_id = 2
        civ_name = "Neighbor"
        leader_name = "Leader"
        has_met = True
        is_at_war = False
        military_strength = 60
        available_actions = ["DECLARE_SURPRISE_WAR"]
        visible_cities = []

    class Threat:
        unit_type = "UNIT_SCOUT"
        x = 7
        y = 8
        hp = 35
        max_hp = 100
        combat_strength = 10
        ranged_strength = 0
        owner_id = 2

    class FakeRecorder:
        strategy_profile = "golden_age_push"

        def __init__(self):
            self.calls = []
            self.decisions = []

        async def tool_call(self, name, params, fn, turn=None):
            result = await fn()
            self.calls.append((name, params, result, turn))
            return f"tool-{len(self.calls)}", result

        def record_decision(self, row):
            self.decisions.append(row)
            return f"decision-{len(self.decisions)}"

    class FakeGameState:
        async def send_diplomatic_action(self, other_player_id, action):
            assert other_player_id == 2
            assert action == "DECLARE_SURPRISE_WAR"
            return "OK:DECLARE_SURPRISE_WAR"

    recorder = FakeRecorder()
    asyncio.run(
        module.maybe_declare_opportunistic_war(
            recorder,
            FakeGameState(),
            30,
            "state-0030",
            {
                "diplomacy": [Civ()],
                "units": [
                    {"unit_id": 1, "unit_type": "UNIT_WARRIOR", "combat_strength": 20, "targets": []},
                    {
                        "unit_id": 2,
                        "unit_type": "UNIT_SLINGER",
                        "combat_strength": 5,
                        "ranged_strength": 15,
                        "targets": ["Enemy SCOUT @7,8(35hp)"],
                    },
                    {"unit_id": 3, "unit_type": "UNIT_ARCHER", "ranged_strength": 25, "targets": []},
                ],
                "threats": [Threat()],
            },
        )
    )

    assert [call[0] for call in recorder.calls] == ["send_diplomatic_action"]
    assert recorder.calls[0][1]["reason"] == "golden_age_push_opportunistic_war"
    assert recorder.decisions[0]["selected_action"] == "DECLARE_SURPRISE_WAR on Neighbor"


def test_ranked_attack_targets_allow_only_high_confidence_declared_war_targets():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class Civ:
        player_id = 2
        is_at_war = True

    class StrongThreat:
        unit_type = "UNIT_WARRIOR"
        x = 7
        y = 8
        hp = 100
        max_hp = 100
        combat_strength = 20
        ranged_strength = 0
        owner_id = 2
        owner_name = "Neighbor"
        is_city_state = False

    class WeakThreat:
        unit_type = "UNIT_SCOUT"
        x = 8
        y = 8
        hp = 35
        max_hp = 100
        combat_strength = 10
        ranged_strength = 0
        owner_id = 2
        owner_name = "Neighbor"
        is_city_state = False

    unit = {
        "unit_id": 12,
        "unit_type": "UNIT_SLINGER",
        "combat_strength": 5,
        "ranged_strength": 15,
        "targets": [
            "Neighbor WARRIOR @7,8(100hp)",
            "Neighbor SCOUT @8,8(35hp)",
        ],
    }

    ranked = module.ranked_attack_targets_for_unit(
        Recorder(),
        unit,
        [StrongThreat(), WeakThreat()],
        35,
        [Civ()],
    )

    assert len(ranked) == 1
    assert ranked[0]["x"] == 8
    assert ranked[0]["is_opportunistic_war"] is True
    assert ranked[0]["estimated_margin"] == 5


def test_nearest_war_threat_requires_declared_war_and_nearby_target():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "golden_age_push"

    class WarCiv:
        player_id = 2
        is_at_war = True

    class PeaceCiv:
        player_id = 2
        is_at_war = False

    class Threat:
        unit_type = "UNIT_WARRIOR"
        x = 6
        y = 7
        hp = 80
        combat_strength = 20
        ranged_strength = 0
        owner_id = 2
        owner_name = "Neighbor"
        is_city_state = False

    unit = {"unit_id": 1, "unit_type": "UNIT_WARRIOR", "x": 4, "y": 5}

    assert module.nearest_war_threat_for_unit(Recorder(), unit, [Threat()], [PeaceCiv()]) is None
    target = module.nearest_war_threat_for_unit(Recorder(), unit, [Threat()], [WarCiv()])

    assert target["x"] == 6
    assert target["distance"] == 2

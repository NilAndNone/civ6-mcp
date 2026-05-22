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


def test_warrior_auto_explore_stops_after_scout_exists():
    module = load_runner_module()

    class Recorder:
        strategy_profile = "explore_scout_first"

    assert not module.should_auto_explore_unit(
        Recorder(), "UNIT_WARRIOR", {"units": [{"unit_type": "UNIT_SCOUT"}]}
    )


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

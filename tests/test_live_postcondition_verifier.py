from __future__ import annotations

import pytest

from codex_hl.live.gateway import ActionRequest
from codex_hl.live.mutation_levels import MutationLevel
from codex_hl.live.verifier import PostconditionVerifier, VerifierStatus


def request(tool: str, args: dict) -> ActionRequest:
    return ActionRequest(
        source="mcp",
        tool_name=tool,
        args=args,
        mutation_level=MutationLevel.L3_HIGH_GAME_MUTATION,
        episode_id="ep_verify",
        plan_id="plan",
        step_id="s001",
        context_hash="sha256:ctx",
    )


@pytest.mark.parametrize(
    ("result", "post", "expected"),
    [
        ("Moved unit", {"units": [{"unit_id": 7, "x": 2, "y": 3}]}, VerifierStatus.PASS),
        (
            "Cannot move: blocked",
            {"units": [{"unit_id": 7, "x": 1, "y": 1}]},
            VerifierStatus.PASS,
        ),
        ("Moved unit", {"units": [{"unit_id": 7, "x": 1, "y": 1}]}, VerifierStatus.FAIL),
    ],
)
def test_unit_position_changed_or_blocked(result: str, post: dict, expected: VerifierStatus) -> None:
    verifier = PostconditionVerifier()
    verification = verifier.verify(
        request=request(
            "unit_action",
            {"unit_id": 7, "action": "move", "target_x": 2, "target_y": 3},
        ),
        result=result,
        pre_state={"units": [{"unit_id": 7, "x": 1, "y": 1}]},
        post_state=post,
    )

    assert verification.status == expected


def test_city_production_set_passes_when_post_state_matches() -> None:
    verification = PostconditionVerifier().verify(
        request=request(
            "set_city_production",
            {"city_id": 1, "item_type": "UNIT", "item_name": "UNIT_SCOUT"},
        ),
        result="Production set",
        pre_state={"cities": [{"city_id": 1, "production": {"item_name": "UNIT_WARRIOR"}}]},
        post_state={"cities": [{"city_id": 1, "production": {"item_name": "UNIT_SCOUT"}}]},
    )

    assert verification.status == VerifierStatus.PASS


def test_city_production_set_uses_currently_building_from_observation() -> None:
    verification = PostconditionVerifier().verify(
        request=request(
            "set_city_production",
            {"city_id": 1, "item_type": "UNIT", "item_name": "UNIT_SLINGER"},
        ),
        result="Production set",
        post_state={"cities": [{"city_id": 1, "currently_building": "UNIT_SLINGER"}]},
    )

    assert verification.status == VerifierStatus.PASS


def test_found_city_passes_when_city_count_increases() -> None:
    verification = PostconditionVerifier().verify(
        request=request("unit_action", {"unit_id": 65536, "action": "found_city"}),
        result="Founded city",
        pre_state={"cities": [[], []]},
        post_state={"cities": [[{"city_id": 1, "name": "Capital"}], []]},
    )

    assert verification.status == VerifierStatus.PASS


def test_found_city_uses_overview_city_count_when_city_rows_are_sparse() -> None:
    verification = PostconditionVerifier().verify(
        request=request("unit_action", {"unit_id": 65536, "action": "found_city"}),
        result="Founded city",
        pre_state={"overview": {"num_cities": 0}, "cities": []},
        post_state={"overview": {"num_cities": 1}, "cities": []},
    )

    assert verification.status == VerifierStatus.PASS


def test_skip_unit_passes_when_moves_are_spent() -> None:
    verification = PostconditionVerifier().verify(
        request=request("unit_action", {"unit_id": 7, "action": "skip"}),
        result="Skipped unit",
        pre_state={"units": [{"unit_id": 7, "moves_remaining": 2}]},
        post_state={"units": [{"unit_id": 7, "moves_remaining": 0}]},
    )

    assert verification.status == VerifierStatus.PASS


@pytest.mark.parametrize(
    ("category", "field", "value"),
    [
        ("tech", "current_research", "TECH_POTTERY"),
        ("civic", "current_civic", "CIVIC_CRAFTSMANSHIP"),
    ],
)
def test_research_and_civic_selected(category: str, field: str, value: str) -> None:
    verification = PostconditionVerifier().verify(
        request=request(
            "set_research",
            {"tech_or_civic": value, "category": category},
        ),
        result="Selected",
        post_state={"research_civic": {field: value}},
    )

    assert verification.status == VerifierStatus.PASS


def test_research_selected_matches_observed_localized_name_to_type() -> None:
    verification = PostconditionVerifier().verify(
        request=request(
            "set_research",
            {"tech_or_civic": "TECH_MINING", "category": "tech"},
        ),
        result="Selected",
        post_state={
            "research_civic": {
                "current_research": "\u91c7\u77ff\u4e1a",
                "available_techs": [
                    {"name": "\u91c7\u77ff\u4e1a", "tech_type": "TECH_MINING"}
                ],
            }
        },
    )

    assert verification.status == VerifierStatus.PASS


def test_turn_advanced_exactly_one() -> None:
    verification = PostconditionVerifier().verify(
        request=request("end_turn", {}),
        result="Turn 12 -> 13",
        pre_state={"overview": {"turn": 12}},
        post_state={"overview": {"turn": 13}},
    )

    assert verification.status == VerifierStatus.PASS
    assert verification.objective_delta["state_turn_delta"] == 1
    assert verification.objective_delta["result_turn_delta"] == 1


def test_turn_advance_accepts_tool_result_when_post_state_is_stale() -> None:
    verification = PostconditionVerifier().verify(
        request=request("end_turn", {}),
        result="Turn 12 -> 13",
        pre_state={"overview": {"turn": 12}},
        post_state={"overview": {"turn": 12}},
    )

    assert verification.status == VerifierStatus.PASS
    assert verification.objective_delta["turn_delta"] == 1
    assert verification.objective_delta["state_turn_delta"] == 0
    assert verification.objective_delta["result_turn_delta"] == 1
    assert verification.objective_delta["state_snapshot_unstable"] is True


def test_turn_advance_rejects_stale_tool_result_for_current_turn() -> None:
    verification = PostconditionVerifier().verify(
        request=request("end_turn", {}),
        result="Turn 15 -> 16",
        pre_state={"overview": {"turn": 16}},
        post_state={"overview": {"turn": 16}},
    )

    assert verification.status == VerifierStatus.FAIL
    assert verification.objective_delta["state_turn_delta"] == 0
    assert verification.objective_delta["result_turn_delta"] == 1
    assert verification.objective_delta["stale_tool_result"] is True


def test_turn_advance_fails_when_turn_jumps() -> None:
    verification = PostconditionVerifier().verify(
        request=request("end_turn", {}),
        result="Turn 12 -> 14",
        pre_state={"overview": {"turn": 12}},
        post_state={"overview": {"turn": 14}},
    )

    assert verification.status == VerifierStatus.FAIL


def test_turn_advance_marks_unresolved_state_result_conflict_inconclusive() -> None:
    verification = PostconditionVerifier().verify(
        request=request("end_turn", {}),
        result="Turn 12 -> 12",
        pre_state={"overview": {"turn": 12}},
        post_state={"overview": {"turn": 14}},
    )

    assert verification.status == VerifierStatus.INCONCLUSIVE
    assert verification.objective_delta["state_result_conflict"] is True
    assert "state/result" in verification.reason


def test_purchase_gold_delta_roughly_consistent() -> None:
    verification = PostconditionVerifier().verify(
        request=request(
            "purchase_item",
            {
                "city_id": 1,
                "item_type": "UNIT",
                "item_name": "UNIT_SCOUT",
                "yield_type": "YIELD_GOLD",
                "expected_cost": 65,
            },
        ),
        result="Purchased UNIT_SCOUT for 65 gold",
        pre_state={"overview": {"gold": 100}},
        post_state={"overview": {"gold": 36}},
    )

    assert verification.status == VerifierStatus.PASS
    assert verification.objective_delta["gold_delta"] == -64


def test_tool_result_ok_for_diplomacy_wrapper() -> None:
    verification = PostconditionVerifier().verify(
        request=request("respond_to_diplomacy", {"other_player_id": 3, "response": "POSITIVE"}),
        result="Responded to diplomacy request",
        postconditions=[{"type": "tool_result_ok"}],
    )

    assert verification.status == VerifierStatus.PASS


def test_tool_result_ok_rejects_blocked_wrapper_result() -> None:
    verification = PostconditionVerifier().verify(
        request=request("respond_to_diplomacy", {"other_player_id": 3, "response": "POSITIVE"}),
        result="Cannot respond: no pending diplomacy",
        postconditions=[{"type": "tool_result_ok"}],
    )

    assert verification.status == VerifierStatus.FAIL

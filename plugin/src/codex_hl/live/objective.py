"""Objective and turn-budget semantics for live strict runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ObjectiveName = Literal["t3", "t20", "t50"]

OBJECTIVE_TURN_BUDGETS: dict[ObjectiveName, int] = {
    "t3": 3,
    "t20": 20,
    "t50": 50,
}


@dataclass(frozen=True)
class LiveObjective:
    name: ObjectiveName
    start_turn: int
    turn_budget: int
    target_turn: int

    def as_header(self) -> dict[str, int | str]:
        return {
            "objective": self.name,
            "start_turn": self.start_turn,
            "turn_budget": self.turn_budget,
            "target_turn": self.target_turn,
        }


def objective_for_budget(turn_budget: int) -> ObjectiveName:
    for name, budget in OBJECTIVE_TURN_BUDGETS.items():
        if budget == turn_budget:
            return name
    raise ValueError("--turn-budget must be one of: 3, 20, 50")


def resolve_objective(
    *,
    start_turn: int,
    turn_budget: int,
    objective: str | None = None,
    target_turn: int | None = None,
) -> LiveObjective:
    if target_turn is not None:
        if target_turn <= start_turn:
            raise ValueError("--target-turn must be greater than the captured start turn")
        resolved_budget = target_turn - start_turn
        resolved_name = objective or objective_for_budget(resolved_budget)
        if resolved_name not in OBJECTIVE_TURN_BUDGETS:
            raise ValueError("--objective must be one of: t3, t20, t50")
        return LiveObjective(
            name=resolved_name,  # type: ignore[arg-type]
            start_turn=start_turn,
            turn_budget=resolved_budget,
            target_turn=target_turn,
        )

    resolved_name = objective or objective_for_budget(turn_budget)
    if resolved_name not in OBJECTIVE_TURN_BUDGETS:
        raise ValueError("--objective must be one of: t3, t20, t50")
    expected_budget = OBJECTIVE_TURN_BUDGETS[resolved_name]  # type: ignore[index]
    if expected_budget != turn_budget:
        raise ValueError("--objective must match --turn-budget")
    return LiveObjective(
        name=resolved_name,  # type: ignore[arg-type]
        start_turn=start_turn,
        turn_budget=turn_budget,
        target_turn=start_turn + turn_budget,
    )

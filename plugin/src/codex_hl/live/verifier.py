from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerifierStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class VerificationResult:
    status: VerifierStatus
    evidence_refs: list[str] = field(default_factory=list)
    objective_delta: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class PostconditionVerifier:
    """Deterministic verifier for the first JSON-plan live gate.

    It only evaluates observable pre/post state and tool arguments. It does not
    treat Codex rationale or raw prose as an outcome authority.
    """

    def verify(
        self,
        *,
        request: Any,
        result: Any,
        pre_state_hash: str | None = None,
        post_state_hash: str | None = None,
        pre_state: dict[str, Any] | None = None,
        post_state: dict[str, Any] | None = None,
        postconditions: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    ) -> VerificationResult:
        del pre_state_hash, post_state_hash
        checks = list(postconditions or [])
        if checks:
            return self._verify_declared(
                request=request,
                result=result,
                pre_state=pre_state or {},
                post_state=post_state or {},
                postconditions=checks,
            )
        return self._verify_inferred(
            request=request,
            result=result,
            pre_state=pre_state or {},
            post_state=post_state or {},
        )

    def _verify_declared(
        self,
        *,
        request: Any,
        result: Any,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
        postconditions: list[dict[str, Any]],
    ) -> VerificationResult:
        results: list[VerificationResult] = []
        for condition in postconditions:
            condition_type = str(condition.get("type") or "")
            if condition_type == "unit_position_changed_or_blocked":
                results.append(
                    self._verify_unit_position(
                        request=request,
                        result=result,
                        pre_state=pre_state,
                        post_state=post_state,
                        unit_id=condition.get("unit_id") or getattr(request, "args", {}).get("unit_id"),
                    )
                )
            elif condition_type == "unit_position_changed":
                results.append(
                    self._verify_unit_position_changed(
                        request=request,
                        result=result,
                        pre_state=pre_state,
                        post_state=post_state,
                        unit_id=condition.get("unit_id") or getattr(request, "args", {}).get("unit_id"),
                    )
                )
            elif condition_type == "city_production_set":
                results.append(
                    self._verify_city_production(
                        request=request,
                        post_state=post_state,
                        city_id=condition.get("city_id") or getattr(request, "args", {}).get("city_id"),
                        item_name=condition.get("item_name") or getattr(request, "args", {}).get("item_name"),
                    )
                )
            elif condition_type == "city_count_increased":
                results.append(
                    self._verify_city_count_increased(
                        pre_state=pre_state,
                        post_state=post_state,
                    )
                )
            elif condition_type == "research_or_civic_selected":
                results.append(
                    self._verify_research_civic(
                        request=request,
                        post_state=post_state,
                        category=str(condition.get("category") or getattr(request, "args", {}).get("category") or "tech"),
                        value=condition.get("value") or getattr(request, "args", {}).get("tech_or_civic"),
                    )
                )
            elif condition_type == "turn_advanced_exactly_one":
                results.append(
                    self._verify_turn_advanced(
                        request=request,
                        result=result,
                        pre_state=pre_state,
                        post_state=post_state,
                    )
                )
            elif condition_type == "unit_has_no_moves_or_blocked":
                results.append(
                    self._verify_unit_has_no_moves_or_blocked(
                        result=result,
                        post_state=post_state,
                        unit_id=condition.get("unit_id") or getattr(request, "args", {}).get("unit_id"),
                    )
                )
            elif condition_type == "purchase_gold_delta":
                results.append(
                    self._verify_purchase_delta(
                        request=request,
                        result=result,
                        pre_state=pre_state,
                        post_state=post_state,
                    )
                )
            elif condition_type == "tool_result_ok":
                results.append(self._verify_tool_result_ok(result=result))
            else:
                results.append(
                    VerificationResult(
                        status=VerifierStatus.INCONCLUSIVE,
                        reason=f"unsupported postcondition type: {condition_type}",
                    )
                )
        return self._combine(results)

    def _verify_inferred(
        self,
        *,
        request: Any,
        result: Any,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> VerificationResult:
        tool = str(getattr(request, "tool_name", "") or "")
        args = getattr(request, "args", {}) if isinstance(getattr(request, "args", {}), dict) else {}
        if tool == "unit_action" and str(args.get("action") or "").lower() == "found_city":
            return self._verify_city_count_increased(
                pre_state=pre_state,
                post_state=post_state,
            )
        if tool == "unit_action" and str(args.get("action") or "").lower() in {
            "move",
            "attack",
            "trade_route",
            "teleport",
        }:
            return self._verify_unit_position(
                request=request,
                result=result,
                pre_state=pre_state,
                post_state=post_state,
                unit_id=args.get("unit_id"),
            )
        if tool == "unit_action" and str(args.get("action") or "").lower() in {
            "skip",
            "fortify",
            "heal",
            "alert",
            "sleep",
            "automate",
        }:
            return self._verify_unit_has_no_moves_or_blocked(
                result=result,
                post_state=post_state,
                unit_id=args.get("unit_id"),
            )
        if tool == "set_city_production":
            return self._verify_city_production(
                request=request,
                post_state=post_state,
                city_id=args.get("city_id"),
                item_name=args.get("item_name"),
            )
        if tool == "set_research":
            return self._verify_research_civic(
                request=request,
                post_state=post_state,
                category=str(args.get("category") or "tech"),
                value=args.get("tech_or_civic"),
            )
        if tool == "end_turn":
            return self._verify_turn_advanced(
                request=request,
                result=result,
                pre_state=pre_state,
                post_state=post_state,
            )
        if tool == "purchase_item":
            return self._verify_purchase_delta(
                request=request,
                result=result,
                pre_state=pre_state,
                post_state=post_state,
            )
        if tool in {
            "respond_to_diplomacy",
            "respond_to_trade",
            "set_policies",
            "dismiss_popup",
        }:
            return self._verify_tool_result_ok(result=result)
        return VerificationResult(
            status=VerifierStatus.INCONCLUSIVE,
            reason="No deterministic postcondition available for this action.",
        )

    def _verify_unit_position(
        self,
        *,
        request: Any,
        result: Any,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
        unit_id: Any,
    ) -> VerificationResult:
        pre_unit = _find_by_id(pre_state.get("units"), unit_id)
        post_unit = _find_by_id(post_state.get("units"), unit_id)
        if pre_unit is None or post_unit is None:
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="unit position check needs pre and post unit state",
            )
        pre_pos = _xy(pre_unit)
        post_pos = _xy(post_unit)
        if pre_pos is None or post_pos is None:
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="unit position check needs x/y coordinates",
            )
        blocked = _result_indicates_blocked(result)
        if post_pos != pre_pos:
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={"from": pre_pos, "to": post_pos},
                reason="unit position changed",
            )
        if blocked:
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={"from": pre_pos, "to": post_pos, "blocked": True},
                reason="unit action was blocked and unit position did not change",
            )
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta={"from": pre_pos, "to": post_pos},
            reason="unit position did not change and action was not blocked",
        )

    def _verify_unit_position_changed(
        self,
        *,
        request: Any,
        result: Any,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
        unit_id: Any,
    ) -> VerificationResult:
        check = self._verify_unit_position(
            request=request,
            result=result,
            pre_state=pre_state,
            post_state=post_state,
            unit_id=unit_id,
        )
        if check.status is VerifierStatus.PASS and not check.objective_delta.get("blocked"):
            return check
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta=check.objective_delta,
            reason="unit position did not change",
        )

    def _verify_city_production(
        self,
        *,
        request: Any,
        post_state: dict[str, Any],
        city_id: Any,
        item_name: Any,
    ) -> VerificationResult:
        del request
        city = _find_by_id(post_state.get("cities"), city_id)
        if city is None:
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="city production check needs post city state",
            )
        current = _city_production_name(city)
        if current is None:
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="city production field not found",
            )
        if str(current).upper() == str(item_name).upper():
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={"production": current},
                reason="city production matches requested item",
            )
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta={"production": current, "expected": item_name},
            reason="city production does not match requested item",
        )

    def _verify_city_count_increased(
        self,
        *,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> VerificationResult:
        pre_count = _city_count(pre_state)
        post_count = _city_count(post_state)
        if post_count > pre_count:
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={"city_count_before": pre_count, "city_count_after": post_count},
                reason="city count increased",
            )
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta={"city_count_before": pre_count, "city_count_after": post_count},
            reason="city count did not increase",
        )

    def _verify_unit_has_no_moves_or_blocked(
        self,
        *,
        result: Any,
        post_state: dict[str, Any],
        unit_id: Any,
    ) -> VerificationResult:
        unit = _find_by_id(post_state.get("units"), unit_id)
        if unit is None:
            if _result_indicates_blocked(result):
                return VerificationResult(
                    status=VerifierStatus.PASS,
                    objective_delta={"blocked": True},
                    reason="unit action was blocked and unit is no longer present",
                )
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="unit move check needs post unit state",
            )
        moves = _number(unit.get("moves_remaining"))
        if moves is None:
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="unit move check needs moves_remaining",
            )
        if moves <= 0:
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={"moves_remaining": _clean_number(moves)},
                reason="unit has no moves remaining",
            )
        if _result_indicates_blocked(result):
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={"moves_remaining": _clean_number(moves), "blocked": True},
                reason="unit action was blocked",
            )
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta={"moves_remaining": _clean_number(moves)},
            reason="unit still has moves remaining",
        )

    def _verify_research_civic(
        self,
        *,
        request: Any,
        post_state: dict[str, Any],
        category: str,
        value: Any,
    ) -> VerificationResult:
        del request
        research = post_state.get("research_civic")
        if not isinstance(research, dict):
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="research/civic check needs post research_civic state",
            )
        key = "current_civic" if category.lower() == "civic" else "current_research"
        current = research.get(key)
        if _research_civic_matches(research, category=category, current=current, expected=value):
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta={key: current},
                reason=f"{key} matches requested selection",
            )
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta={key: current, "expected": value},
            reason=f"{key} does not match requested selection",
        )

    def _verify_turn_advanced(
        self,
        *,
        request: Any,
        result: Any,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> VerificationResult:
        del request
        pre_turn = _overview_number(pre_state, "turn")
        post_turn = _overview_number(post_state, "turn")
        result_delta = _turn_delta_from_result(result)
        if pre_turn is None or post_turn is None:
            if result_delta == 1:
                return VerificationResult(
                    status=VerifierStatus.PASS,
                    objective_delta={"turn_delta": 1, "result_turn_delta": 1},
                    reason="turn advanced according to tool result; state snapshot missing",
                )
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="turn check needs pre and post overview.turn",
            )
        delta = int(post_turn) - int(pre_turn)
        objective_delta: dict[str, Any] = {
            "turn_delta": delta,
            "state_turn_delta": delta,
        }
        if result_delta is not None:
            objective_delta["result_turn_delta"] = result_delta
        if delta == 1:
            if result_delta is not None and result_delta != 1:
                objective_delta["state_result_conflict"] = True
                return VerificationResult(
                    status=VerifierStatus.PASS,
                    objective_delta=objective_delta,
                    reason="turn advanced according to state snapshot; tool result conflicts",
                )
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta=objective_delta,
                reason="turn advanced exactly one",
            )
        if result_delta == 1:
            objective_delta["turn_delta"] = 1
            objective_delta["state_snapshot_unstable"] = True
            return VerificationResult(
                status=VerifierStatus.PASS,
                objective_delta=objective_delta,
                reason="turn advanced according to tool result; state snapshot unstable",
            )
        if result_delta is not None and result_delta != delta:
            objective_delta["state_result_conflict"] = True
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                objective_delta=objective_delta,
                reason="state/result turn delta conflict",
            )
        return VerificationResult(
            status=VerifierStatus.FAIL,
            objective_delta=objective_delta,
            reason="turn did not advance exactly one",
        )

    def _verify_purchase_delta(
        self,
        *,
        request: Any,
        result: Any,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> VerificationResult:
        args = getattr(request, "args", {}) if isinstance(getattr(request, "args", {}), dict) else {}
        if str(args.get("yield_type") or "YIELD_GOLD").upper() != "YIELD_GOLD":
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="only gold purchase deltas are supported",
            )
        pre_gold = _overview_number(pre_state, "gold")
        post_gold = _overview_number(post_state, "gold")
        if pre_gold is None or post_gold is None:
            return VerificationResult(
                status=VerifierStatus.INCONCLUSIVE,
                reason="purchase check needs pre and post overview.gold",
            )
        gold_delta = float(post_gold) - float(pre_gold)
        cost = _expected_cost(args, result)
        if gold_delta >= 0:
            return VerificationResult(
                status=VerifierStatus.FAIL,
                objective_delta={"gold_delta": _clean_number(gold_delta), "expected_cost": cost},
                reason="gold did not decrease after purchase",
            )
        if cost is not None and abs(abs(gold_delta) - cost) > max(5.0, cost * 0.15):
            return VerificationResult(
                status=VerifierStatus.FAIL,
                objective_delta={"gold_delta": _clean_number(gold_delta), "expected_cost": cost},
                reason="gold delta is not roughly consistent with purchase cost",
            )
        return VerificationResult(
            status=VerifierStatus.PASS,
            objective_delta={"gold_delta": _clean_number(gold_delta), "expected_cost": cost},
            reason="gold delta is roughly consistent with purchase",
        )

    def _verify_tool_result_ok(self, *, result: Any) -> VerificationResult:
        if _result_indicates_blocked(result):
            return VerificationResult(
                status=VerifierStatus.FAIL,
                objective_delta={"result": str(result)},
                reason="tool result indicates the action was blocked or failed",
            )
        return VerificationResult(
            status=VerifierStatus.PASS,
            objective_delta={"result": str(result)},
            reason="tool result does not indicate a blocked or failed action",
        )

    @staticmethod
    def _combine(results: list[VerificationResult]) -> VerificationResult:
        if any(result.status is VerifierStatus.FAIL for result in results):
            status = VerifierStatus.FAIL
        elif results and all(result.status is VerifierStatus.PASS for result in results):
            status = VerifierStatus.PASS
        else:
            status = VerifierStatus.INCONCLUSIVE
        return VerificationResult(
            status=status,
            evidence_refs=[
                ref for result in results for ref in result.evidence_refs
            ],
            objective_delta={
                key: value
                for result in results
                for key, value in result.objective_delta.items()
            },
            reason="; ".join(result.reason for result in results if result.reason),
        )


class StubVerifier(PostconditionVerifier):
    """Backward-compatible name for Phase 1 callers."""


def _find_by_id(rows: Any, value: Any) -> dict[str, Any] | None:
    for row in _entity_rows(rows):
        identifiers = [
            row.get("unit_id"),
            row.get("unit_index"),
            row.get("id"),
            row.get("city_id"),
            row.get("index"),
        ]
        if any(str(identifier) == str(value) for identifier in identifiers if identifier is not None):
            return row
    return None


def _entity_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
        elif isinstance(row, list):
            result.extend(item for item in row if isinstance(item, dict))
    return result


def _xy(row: dict[str, Any]) -> dict[str, int] | None:
    if isinstance(row.get("location"), dict):
        location = row["location"]
        if "x" in location and "y" in location:
            return {"x": int(location["x"]), "y": int(location["y"])}
    if "x" in row and "y" in row:
        return {"x": int(row["x"]), "y": int(row["y"])}
    if "plot_x" in row and "plot_y" in row:
        return {"x": int(row["plot_x"]), "y": int(row["plot_y"])}
    return None


def _result_indicates_blocked(result: Any) -> bool:
    text = str(result).lower()
    return any(
        marker in text
        for marker in [
            "blocked",
            "cannot",
            "can't",
            "invalid",
            "no path",
            "not enough",
            "error",
        ]
    )


def _city_production_name(city: dict[str, Any]) -> Any:
    for key in ("currently_building", "current_production", "production_item", "item_name"):
        if city.get(key):
            return city[key]
    production = city.get("production")
    if isinstance(production, dict):
        for key in ("item_name", "name", "type"):
            if production.get(key):
                return production[key]
    if isinstance(production, str):
        return production
    queue = city.get("build_queue")
    if isinstance(queue, list) and queue and isinstance(queue[0], dict):
        return queue[0].get("item_name") or queue[0].get("name")
    return None


def _same_symbol(a: Any, b: Any) -> bool:
    return str(a or "").strip().upper() == str(b or "").strip().upper()


def _research_civic_matches(
    research: dict[str, Any], *, category: str, current: Any, expected: Any
) -> bool:
    if _same_symbol(current, expected):
        return True
    option_key = "available_civics" if category.lower() == "civic" else "available_techs"
    type_key = "civic_type" if category.lower() == "civic" else "tech_type"
    for option in _entity_rows(research.get(option_key)):
        option_type = option.get(type_key)
        option_name = option.get("name")
        if _same_symbol(option_type, expected) and _same_symbol(option_name, current):
            return True
        if _same_symbol(option_name, expected) and _same_symbol(option_type, current):
            return True
    return False


def _city_count(state: dict[str, Any]) -> int:
    row_count = len(_entity_rows(state.get("cities")))
    overview_count = _overview_number(state, "num_cities")
    if overview_count is None:
        return row_count
    return max(row_count, int(overview_count))


def _overview_number(state: dict[str, Any], key: str) -> float | None:
    overview = state.get("overview")
    if not isinstance(overview, dict):
        return None
    return _number(overview.get(key))


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.replace(".", "", 1).isdigit():
            return float(text)
    return None


def _expected_cost(args: dict[str, Any], result: Any) -> float | None:
    for key in ("expected_cost", "cost", "gold_cost"):
        value = args.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:gold|金币)", str(result), re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _turn_delta_from_result(result: Any) -> int | None:
    text = str(result)
    patterns = [
        r"\bturn\s+(\d+)\s*(?:->|to)\s*(\d+)\b",
        r"\bT(\d+)\s*(?:->|to)\s*T?(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(2)) - int(match.group(1))
    return None


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value

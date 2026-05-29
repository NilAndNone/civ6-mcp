from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

from codex_hl.live.gateway import GatewayMode


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "plugin" / "src"


def load_observation_module():
    sys.path.insert(0, str(PLUGIN_SRC))
    try:
        return importlib.import_module("codex_hl.evidence.observation")
    finally:
        sys.path.remove(str(PLUGIN_SRC))


def test_legacy_recorder_routes_registered_mutation_through_shadow_gateway(
    monkeypatch, tmp_path
) -> None:
    module = load_observation_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("CODEX_HL_CIV6_LIVE_GATEWAY_MODE", "shadow")

    recorder = module.EpisodeRecorder("ep_legacy_shadow", "test 1")
    calls: list[str] = []

    async def run_action() -> str:
        calls.append("ran")
        return "OK"

    call_id, result = asyncio.run(
        recorder.tool_call(
            "unit_action",
            {"unit_id": 65536, "action": "skip"},
            run_action,
            turn=3,
        )
    )

    assert call_id == "tool-00001"
    assert result == "OK"
    assert calls == ["ran"]

    events_path = tmp_path / "episodes" / "ep_legacy_shadow" / "raw" / "live_events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event_type"] == "ACTION_FINISHED"
    assert events[-1]["source"] == "legacy_runner"
    assert events[-1]["tool"] == "unit_action"
    assert events[-1]["args"] == {"unit_id": 65536, "action": "skip"}
    assert events[-1]["level"] == "L2"
    assert events[-1]["plan_id"] is None
    assert events[-1]["step_id"] is None
    assert events[-1]["unplanned_mutation"] is True

    ledger_rows = recorder.store.read_jsonl("raw/live_events.jsonl")
    assert ledger_rows[-1]["source"] == "legacy_runner"


def test_legacy_recorder_ignores_global_live_strict_mode(
    monkeypatch, tmp_path
) -> None:
    module = load_observation_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("CODEX_HL_CIV6_LIVE_GATEWAY_MODE", "live_strict")

    recorder = module.EpisodeRecorder("ep_legacy_global_strict", "test 1")
    calls: list[str] = []

    async def run_action() -> str:
        calls.append("ran")
        return "OK"

    _call_id, result = asyncio.run(
        recorder.tool_call(
            "unit_action",
            {"unit_id": 65536, "action": "skip"},
            run_action,
            turn=3,
        )
    )

    assert result == "OK"
    assert calls == ["ran"]

    events_path = (
        tmp_path
        / "episodes"
        / "ep_legacy_global_strict"
        / "raw"
        / "live_events.jsonl"
    )
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event_type"] == "ACTION_FINISHED"
    assert events[-1]["source"] == "legacy_runner"
    assert events[-1]["tool"] == "unit_action"
    assert events[-1]["unplanned_mutation"] is True


@pytest.mark.parametrize(
    ("alias", "params", "canonical_tool", "expected_level"),
    [
        ("end_turn_retry", {}, "end_turn", "L4"),
        ("end_turn_after_diplomacy", {"attempt": 1}, "end_turn", "L4"),
        (
            "respond_to_trade_decline_for_end_turn",
            {"other_player_id": 3, "accept": False},
            "respond_to_trade",
            "L3",
        ),
        (
            "respond_to_diplomacy_for_end_turn",
            {"other_player_id": 3, "response": "POSITIVE"},
            "respond_to_diplomacy",
            "L3",
        ),
        (
            "respond_to_diplomacy_exit_for_end_turn",
            {"other_player_id": 3, "response": "EXIT"},
            "respond_to_diplomacy",
            "L3",
        ),
    ],
)
def test_legacy_alias_mutations_are_recorded_under_canonical_gateway_tool(
    monkeypatch,
    tmp_path,
    alias,
    params,
    canonical_tool,
    expected_level,
) -> None:
    module = load_observation_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("CODEX_HL_CIV6_LIVE_GATEWAY_MODE", "shadow")

    recorder = module.EpisodeRecorder(f"ep_alias_{alias}", "test 1")
    calls: list[str] = []

    async def run_action() -> str:
        calls.append(alias)
        return "OK"

    _call_id, result = asyncio.run(recorder.tool_call(alias, params, run_action, turn=4))

    assert result == "OK"
    assert calls == [alias]

    events_path = tmp_path / "episodes" / f"ep_alias_{alias}" / "raw" / "live_events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event_type"] == "ACTION_FINISHED"
    assert events[-1]["source"] == "legacy_runner"
    assert events[-1]["tool"] == canonical_tool
    assert events[-1]["level"] == expected_level
    assert events[-1]["payload"]["original_tool"] == alias
    assert events[-1]["unplanned_mutation"] is True


def test_legacy_recorder_marks_gateway_rejection_as_unsuccessful(
    monkeypatch, tmp_path
) -> None:
    module = load_observation_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    original_factory = module.action_gateway_for_episode

    def strict_gateway_for_episode(*args, **kwargs):
        kwargs["mode"] = GatewayMode.LIVE_STRICT
        return original_factory(*args, **kwargs)

    monkeypatch.setattr(module, "action_gateway_for_episode", strict_gateway_for_episode)

    recorder = module.EpisodeRecorder("ep_strict_rejection_contract", "test 1")
    calls: list[str] = []

    async def run_action() -> str:
        calls.append("ran")
        return "OK"

    _call_id, result = asyncio.run(
        recorder.tool_call(
            "unit_action",
            {"unit_id": 65536, "action": "skip"},
            run_action,
            turn=5,
        )
    )

    assert calls == []
    assert str(result).startswith("Error: LIVE_STRICT requires")

    rows = recorder.store.read_jsonl("raw/tool_calls.jsonl")
    assert rows[-1]["tool"] == "unit_action"
    assert rows[-1]["success"] is False
    assert rows[-1]["rejected"] is True
    assert rows[-1]["error"]["type"] == "GatewayRejected"

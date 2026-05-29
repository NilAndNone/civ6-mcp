from __future__ import annotations

import pytest

from codex_hl.live.fragment_sandbox import (
    FragmentSandboxError,
    analyze_fragment_source,
)


def test_fragment_ast_extracts_one_live_mutation_call() -> None:
    source = """
def run(live):
    ctx = live.read_context()
    live.assert_precondition("unit_exists", unit_id=65536)
    result = live.unit_action(unit_id=65536, action="move", target_x=4, target_y=7)
    live.assert_postcondition("unit_position_changed_or_blocked", unit_id=65536, target={"x": 4, "y": 7})
    return {"result": result, "ctx": ctx}
"""

    analysis = analyze_fragment_source(source)

    assert analysis["source_sha256"].startswith("sha256:")
    assert analysis["tool_name"] == "unit_action"
    assert analysis["args"] == {
        "unit_id": 65536,
        "action": "move",
        "target_x": 4,
        "target_y": 7,
    }
    assert analysis["preconditions"] == [{"type": "unit_exists", "unit_id": 65536}]
    assert analysis["postconditions"] == [
        {
            "type": "unit_position_changed_or_blocked",
            "unit_id": 65536,
            "target": {"x": 4, "y": 7},
        }
    ]


@pytest.mark.parametrize(
    "source, message",
    [
        ("import os\n\ndef run(live):\n    live.unit_action(unit_id=1, action='skip')\n", "Import"),
        ("def run(live):\n    for i in [1]:\n        live.unit_action(unit_id=1, action='skip')\n", "For"),
        (
            "def run(live):\n    live.unit_action(unit_id=1, action='skip')\n    live.unit_action(unit_id=2, action='skip')\n",
            "exactly one",
        ),
        ("def run(live):\n    live.raw_game_state()\n", "not allowed"),
        (
            "def run(live):\n    live.unit_action(unit_id=open('x'), action='skip')\n",
            "forbidden name",
        ),
        (
            "def run(live):\n    live.unit_action(unit_id=1, action='skip')\n    live.assert_precondition('unit_exists', unit_id=1)\n",
            "preconditions",
        ),
        (
            "def run(live):\n    live.assert_postcondition('unit_position_changed_or_blocked', unit_id=1)\n    live.unit_action(unit_id=1, action='skip')\n",
            "postconditions",
        ),
    ],
)
def test_fragment_ast_rejects_forbidden_shapes(source: str, message: str) -> None:
    with pytest.raises(FragmentSandboxError, match=message):
        analyze_fragment_source(source)

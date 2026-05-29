from __future__ import annotations

import json
from pathlib import Path

from codex_hl.runs import orchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_runner_arg_accepts_live_and_legacy_baseline() -> None:
    live = orchestrator.parse_args(["--execute", "--runner", "live"])
    legacy = orchestrator.parse_args(["--execute", "--runner", "legacy-baseline"])

    assert live.runner == "live"
    assert legacy.runner == "legacy-baseline"


def test_observe_command_documentation_marks_legacy_baseline() -> None:
    observe_doc = (ROOT / "plugin" / "commands" / "civ6-observe.md").read_text(encoding="utf-8")
    live_doc = (ROOT / "plugin" / "commands" / "civ6-observe-live.md").read_text(encoding="utf-8")
    baseline_doc = (ROOT / "docs" / "live_refactor" / "legacy_baseline.md").read_text(encoding="utf-8")

    assert "legacy-baseline" in observe_doc
    assert "deprecated" in observe_doc.lower()
    assert "JSON plan" in live_doc
    assert "--runner legacy-baseline" in baseline_doc


def test_plugin_manifest_points_to_mcp_config() -> None:
    manifest = json.loads(
        (ROOT / "plugin" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    mcp_config = json.loads(
        (ROOT / "plugin" / ".codex-plugin" / ".mcp.json").read_text(encoding="utf-8")
    )

    assert manifest["mcpServers"] == "./.mcp.json"
    assert "civ6_connector" in mcp_config["mcpServers"]

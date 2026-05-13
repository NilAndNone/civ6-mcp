import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"


def test_plugin_is_self_contained_codex_package():
    manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "codex-hl-civ6"
    assert manifest["skills"] == "./skills/"
    assert (PLUGIN / "AGENTS.md").exists()
    assert (PLUGIN / "skills" / "civ6-phase1-observation" / "SKILL.md").exists()

    for command in [
        "civ6-phase1-observe.md",
        "civ6-phase1-report.md",
        "civ6-debug.md",
    ]:
        assert (PLUGIN / "commands" / command).exists()


def test_plugin_runtime_modules_import_from_plugin_src():
    plugin_src = str(PLUGIN / "src")
    sys.path.insert(0, plugin_src)
    try:
        assert importlib.import_module("codex_hl.phase0")
        assert importlib.import_module("codex_hl.phase1.observer")
        assert importlib.import_module("civ6_connector.game_state")
    finally:
        sys.path.remove(plugin_src)

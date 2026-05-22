import importlib
import json
import sys
import tomllib
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
        "civ6-phase2-label.md",
        "civ6-phase3-assets.md",
        "civ6-phase4-candidates.md",
        "civ6-phase5-scenarios.md",
        "civ6-governance.md",
        "civ6-evolve.md",
        "civ6-debug.md",
    ]:
        assert (PLUGIN / "commands" / command).exists()

    assert (PLUGIN / "assets" / "codex_hl" / "phase3" / "catalog.json").exists()


def test_plugin_runtime_modules_import_from_plugin_src():
    plugin_src = str(PLUGIN / "src")
    sys.path.insert(0, plugin_src)
    try:
        assert importlib.import_module("codex_hl.phase0")
        assert importlib.import_module("codex_hl.phase1.observer")
        assert importlib.import_module("codex_hl.phase2.labeler")
        assert importlib.import_module("codex_hl.phase3.assets")
        assert importlib.import_module("codex_hl.phase4.improvements")
        assert importlib.import_module("codex_hl.phase5.scenarios")
        assert importlib.import_module("codex_hl.governance.automation")
        assert importlib.import_module("codex_hl.evolution.orchestrator")
        assert importlib.import_module("civ6_connector.game_state")
    finally:
        sys.path.remove(plugin_src)


def test_project_metadata_includes_phase3_asset_surface():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert "asset governance" in project["description"]
    assert {"phase3", "phase4", "phase5", "governance", "assets", "evolution"}.issubset(set(project["keywords"]))
    assert project["scripts"]["codex-hl-civ6-phase3-assets"] == "codex_hl.phase3.assets:main"
    assert project["scripts"]["codex-hl-civ6-phase4-candidates"] == "codex_hl.phase4.improvements:main"
    assert project["scripts"]["codex-hl-civ6-phase5-scenarios"] == "codex_hl.phase5.scenarios:main"
    assert project["scripts"]["codex-hl-civ6-governance"] == "codex_hl.governance.automation:main"
    assert project["scripts"]["codex-hl-civ6-evolve"] == "codex_hl.evolution.orchestrator:main"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"][
        "plugin/assets"
    ] == "assets"

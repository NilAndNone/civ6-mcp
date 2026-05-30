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
    assert (PLUGIN / "skills" / "civ6-observation" / "SKILL.md").exists()

    for command in [
        "civ6-observe.md",
        "civ6-observe-live.md",
        "civ6-load-test1.md",
        "civ6-review.md",
        "civ6-strategy-assets.md",
        "civ6-strategy-candidates.md",
        "civ6-validation-scenarios.md",
        "civ6-governance.md",
        "civ6-live-eval.md",
        "civ6-runs.md",
        "civ6-acceptance.md",
        "civ6-debug.md",
        "civ6-human-demo-record.md",
    ]:
        assert (PLUGIN / "commands" / command).exists()

    assert (PLUGIN / "assets" / "codex_hl" / "strategy" / "catalog.json").exists()


def test_plugin_runtime_modules_import_from_plugin_src():
    plugin_src = str(PLUGIN / "src")
    sys.path.insert(0, plugin_src)
    try:
        assert importlib.import_module("codex_hl.contracts")
        assert importlib.import_module("codex_hl.evidence.observation")
        assert importlib.import_module("codex_hl.review.failure_labeling")
        assert importlib.import_module("codex_hl.strategy.registry")
        assert importlib.import_module("codex_hl.strategy.candidates")
        assert importlib.import_module("codex_hl.validation.scenarios")
        assert importlib.import_module("codex_hl.governance.gates")
        assert importlib.import_module("codex_hl.live.evaluation")
        assert importlib.import_module("codex_hl.runs.orchestrator")
        assert importlib.import_module("codex_hl.reports.acceptance")
        assert importlib.import_module("civ6_connector.game_state")
    finally:
        sys.path.remove(plugin_src)


def test_project_metadata_includes_strategy_asset_surface():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert "asset governance" in project["description"]
    assert {"strategy", "governance", "assets", "observation", "review", "validation", "evolution"}.issubset(set(project["keywords"]))
    assert project["scripts"]["codex-hl-civ6-strategy-assets"] == "codex_hl.strategy.registry:main"
    assert project["scripts"]["codex-hl-civ6-strategy-candidates"] == "codex_hl.strategy.candidates:main"
    assert project["scripts"]["codex-hl-civ6-validation-scenarios"] == "codex_hl.validation.scenarios:main"
    assert project["scripts"]["codex-hl-civ6-governance"] == "codex_hl.governance.gates:main"
    assert project["scripts"]["codex-hl-civ6-live-eval"] == "codex_hl.live.evaluation:main"
    assert project["scripts"]["codex-hl-civ6-runs"] == "codex_hl.runs.orchestrator:main"
    assert project["scripts"]["codex-hl-civ6-acceptance"] == "codex_hl.reports.acceptance:main"
    assert project["scripts"]["codex-hl-civ6-load-test1"] == "codex_hl.diagnostics.load_test1:main"
    assert project["scripts"]["codex-hl-civ6-human-demo-record"] == "codex_hl.demos.cli:main"
    assert "Pillow>=10.0" in pyproject["project"]["optional-dependencies"]["launcher-windows"]
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"][
        "plugin/assets"
    ] == "assets"

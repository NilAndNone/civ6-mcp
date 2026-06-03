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
    mcp_config_path = PLUGIN / ".codex-plugin" / ".mcp.json"
    assert mcp_config_path.exists()
    mcp_config = json.loads(mcp_config_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "codex-hl-civ6"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert "automated live driver" not in manifest["interface"]["longDescription"].lower()
    assert (
        mcp_config["mcpServers"]["civ6_connector"]["env"][
            "CODEX_HL_CIV6_LIVE_GATEWAY_MODE"
        ]
        == "live_strict"
    )
    assert (PLUGIN / "AGENTS.md").exists()
    assert (PLUGIN / "skills" / "civ6-observation" / "SKILL.md").exists()

    for command in [
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
        "civ6-human-demo-contract.md",
        "civ6-wiki-build.md",
    ]:
        assert (PLUGIN / "commands" / command).exists()
    assert not (PLUGIN / "commands" / "civ6-live-driver.md").exists()

    assert (PLUGIN / "assets" / "codex_hl" / "strategy" / "catalog.json").exists()
    knowledge_root = PLUGIN / "assets" / "codex_hl" / "knowledge" / "civ6-wiki"
    assert (knowledge_root / "index.md").exists()
    assert (knowledge_root / "manifest.json").exists()
    assert (knowledge_root / "pages_index.json").exists()
    assert (knowledge_root / "rag_chunks.jsonl").exists()
    assert (knowledge_root / "validation_report.md").exists()


def test_plugin_runtime_modules_import_from_plugin_src():
    plugin_src = str(PLUGIN / "src")
    sys.path.insert(0, plugin_src)
    try:
        assert importlib.import_module("codex_hl.contracts")
        assert importlib.import_module("codex_hl.evidence.store")
        assert importlib.import_module("codex_hl.live.gateway")
        assert importlib.import_module("codex_hl.live.plan_store")
        assert importlib.import_module("codex_hl.review.failure_labeling")
        assert importlib.import_module("codex_hl.strategy.registry")
        assert importlib.import_module("codex_hl.strategy.candidates")
        assert importlib.import_module("codex_hl.validation.scenarios")
        assert importlib.import_module("codex_hl.governance.gates")
        assert importlib.import_module("codex_hl.live.evaluation")
        assert importlib.import_module("codex_hl.runs.orchestrator")
        assert importlib.import_module("codex_hl.reports.acceptance")
        assert importlib.import_module("codex_hl.wiki.build")
        assert importlib.import_module("civ6_connector.game_state")
    finally:
        sys.path.remove(plugin_src)


def test_project_metadata_includes_strategy_asset_surface():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert "live strict" in project["description"]
    assert {"strategy", "governance", "assets", "live-strict", "review", "validation", "evolution"}.issubset(set(project["keywords"]))
    assert project["scripts"]["codex-hl-civ6-strategy-assets"] == "codex_hl.strategy.registry:main"
    assert project["scripts"]["codex-hl-civ6-strategy-candidates"] == "codex_hl.strategy.candidates:main"
    assert project["scripts"]["codex-hl-civ6-validation-scenarios"] == "codex_hl.validation.scenarios:main"
    assert project["scripts"]["codex-hl-civ6-governance"] == "codex_hl.governance.gates:main"
    assert project["scripts"]["codex-hl-civ6-live-eval"] == "codex_hl.live.evaluation:main"
    assert project["scripts"]["codex-hl-civ6-wiki-build"] == "codex_hl.wiki.build:main"
    assert project["scripts"]["codex-hl-civ6-runs"] == "codex_hl.runs.orchestrator:main"
    assert project["scripts"]["codex-hl-civ6-acceptance"] == "codex_hl.reports.acceptance:main"
    assert project["scripts"]["codex-hl-civ6-load-test1"] == "codex_hl.diagnostics.load_test1:main"
    assert project["scripts"]["codex-hl-civ6-human-demo-record"] == "codex_hl.demos.cli:main"
    assert "codex-hl-civ6-live-driver" not in project["scripts"]
    assert "codex_hl.live.driver:main" not in project["scripts"].values()
    assert "Pillow>=10.0" in pyproject["project"]["optional-dependencies"]["launcher-windows"]
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"][
        "plugin/assets"
    ] == "assets"


def test_human_demo_runtime_docs_remove_automated_live_driver():
    observe_live_doc = (PLUGIN / "commands" / "civ6-observe-live.md").read_text(encoding="utf-8")
    runs_doc = (PLUGIN / "commands" / "civ6-runs.md").read_text(encoding="utf-8")
    architecture_doc = (ROOT / "docs" / "current-architecture.md").read_text(encoding="utf-8")

    assert "model authors" in observe_live_doc
    assert "Python/profile-generated live-driver plans" in observe_live_doc
    assert "`--execute`: removed" in runs_doc
    assert "--runner live" in runs_doc
    assert "Model-in-loop live strict" in architecture_doc
    assert "automated live driver has been removed" in architecture_doc


def test_public_commands_do_not_reintroduce_driver_surface():
    command_files = {path.name for path in (PLUGIN / "commands").glob("*.md")}
    assert "civ6-live-driver.md" not in command_files

    forbidden_command_terms = ("driver", "auto-run", "live-execute")
    threatening = [
        name
        for name in command_files
        if name != "civ6-observe-live.md"
        and any(term in name.lower() for term in forbidden_command_terms)
    ]
    assert threatening == []

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    threatening_scripts = [
        name
        for name in pyproject["project"]["scripts"]
        if "driver" in name.lower() or "live-execute" in name.lower()
    ]
    assert threatening_scripts == []

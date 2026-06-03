import json
from pathlib import Path

from codex_hl.wiki import build


def test_parse_template_fields_handles_nested_templates():
    template_name, fields, rest = build.parse_template_fields(build.SAMPLE_FIXTURES["Archery (Civ6)"])

    assert template_name == "Tech (Civ6)"
    assert fields["name"] == "Archery"
    assert fields["eureka"] == "Kill a unit with a Slinger."
    assert "Strategy" in rest


def test_build_page_excludes_strategy_text():
    page = build.build_page("Archery (Civ6)", "technologies", build.SAMPLE_FIXTURES["Archery (Civ6)"], [])

    assert page is not None
    assert page.category == "technologies"
    assert "subjective strategy" not in page.summary.lower()
    assert page.fields["reqs"] == "Animal Husbandry"


def test_scenario_filter_excludes_scenario_categories():
    page = build.build_page(
        "Aircraft (Civ6)",
        "technologies",
        "{{Tech (Civ6)\n|name = Aircraft\n}}\n'''Aircraft''' is a scenario technology.",
        ["War Machine (Civ6)", "Scenario-specific technologies"],
    )

    assert page is None


def test_no_network_sample_build_writes_required_outputs(tmp_path):
    out = tmp_path / "wiki"
    args = build.build_parser().parse_args(
        [
            "--out",
            str(out),
            "--plugin-kb",
            str(tmp_path / "plugin" / "assets" / "codex_hl" / "knowledge" / "civ6-wiki"),
            "--game-root",
            str(tmp_path / "missing-game"),
            "--sample-only",
            "--no-network",
        ]
    )

    manifest = build.build_knowledge_base(args)

    assert manifest["counts"]["pages"] == 7
    assert (out / "index.md").exists()
    assert (out / "manifest.json").exists()
    assert (out / "pages_index.json").exists()
    assert (out / "rag_chunks.jsonl").exists()
    assert (out / "validation_report.md").exists()

    index = json.loads((out / "pages_index.json").read_text(encoding="utf-8"))
    assert any(page["title"] == "Archery" and page["category"] == "technologies" for page in index)

    chunks = (out / "rag_chunks.jsonl").read_text(encoding="utf-8").splitlines()
    assert any("Babylon" in line and "Enuma Anu Enlil" in line for line in chunks)


def test_local_reference_validation_detects_cost_mismatch(tmp_path):
    game_root = tmp_path / "game"
    data_dir = game_root / "Base" / "Assets" / "Gameplay" / "Data"
    text_dir = game_root / "Base" / "Assets" / "Text" / "en_US"
    data_dir.mkdir(parents=True)
    text_dir.mkdir(parents=True)
    (data_dir / "Technologies.xml").write_text(
        """<GameInfo><Technologies>
        <Row TechnologyType="TECH_ARCHERY" Name="LOC_TECH_ARCHERY_NAME" Cost="60" EraType="ERA_ANCIENT"/>
        </Technologies></GameInfo>""",
        encoding="utf-8",
    )
    (text_dir / "Types_Text.xml").write_text(
        """<GameData><LocalizedText>
        <Row Tag="LOC_TECH_ARCHERY_NAME"><Text>Archery</Text></Row>
        </LocalizedText></GameData>""",
        encoding="utf-8",
    )
    page = build.build_page("Archery (Civ6)", "technologies", build.SAMPLE_FIXTURES["Archery (Civ6)"], [])
    assert page is not None

    ref = build.load_local_reference(game_root)
    findings = build.validate_pages([page], ref)

    assert findings == [
        {
            "page": "Archery",
            "field": "cost",
            "wiki_value": "50",
            "local_value": "60",
            "local_file": str(Path("Base") / "Assets" / "Gameplay" / "Data" / "Technologies.xml"),
        }
    ]

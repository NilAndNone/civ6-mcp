from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATTERNS = {
    "legacy slash observe": re.compile(r"(?<![\w/-])/civ6-observe(?!-live)(?![\w-])"),
    "legacy script observe": re.compile(r"\bcodex-hl-civ6-observe\b"),
    "legacy module": re.compile(r"\bcodex_hl\.evidence\.observation\b"),
    "legacy runner flag": re.compile(r"--runner\s+legacy-baseline\b"),
    "legacy t50 command": re.compile(r"\bcodex-hl-civ6-live-t50-driver\b"),
    "legacy t50 module": re.compile(r"\bcodex_hl\.live\.t50_driver\b"),
    "legacy t50 slash command": re.compile(r"(?<![\w/-])/civ6-live-t50-driver(?![\w-])"),
    "automated live driver slash command": re.compile(r"(?<![\w/-])/civ6-live-driver(?![\w-])"),
    "automated live driver script": re.compile(r"\bcodex-hl-civ6-live-driver\b"),
    "automated live driver module": re.compile(r"\bcodex_hl\.live\.driver\b"),
}

CURRENT_PATHS = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "pyproject.toml",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "current-architecture.md",
    ROOT / "docs" / "current-architecture.html",
    ROOT / "docs" / "codex-hl-observation.md",
    ROOT / "docs" / "plugin-architecture.md",
    ROOT / "plugin" / ".codex-plugin" / "plugin.json",
    ROOT / "plugin" / "README.md",
    ROOT / "plugin" / "AGENTS.md",
    ROOT / "plugin" / "commands",
    ROOT / "plugin" / "skills",
    ROOT / "plugin" / "assets" / "codex_hl" / "strategy",
    ROOT / "plugin" / "src" / "codex_hl" / "live",
    ROOT / "plugin" / "src" / "codex_hl" / "runs",
    ROOT / "plugin" / "src" / "codex_hl" / "demos",
]


def iter_text_files(path: Path):
    if path.is_file():
        yield path
        return
    for child in path.rglob("*"):
        if "__pycache__" in child.parts:
            continue
        if child.name == "change_ledger.jsonl":
            continue
        if child.is_file() and child.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".db", ".pyc"}:
            yield child


def test_removed_public_entrypoint_files_are_gone() -> None:
    assert not (ROOT / "plugin" / "commands" / "civ6-observe.md").exists()
    assert not (ROOT / "plugin" / "commands" / "civ6-live-driver.md").exists()
    assert not (ROOT / "plugin" / "commands" / "civ6-live-t50-driver.md").exists()
    assert not (ROOT / "plugin" / "src" / "codex_hl" / "evidence" / "observation.py").exists()
    assert not (ROOT / "plugin" / "src" / "codex_hl" / "live" / "driver.py").exists()
    assert not (ROOT / "plugin" / "src" / "codex_hl" / "live" / "planner.py").exists()
    assert not (ROOT / "plugin" / "src" / "codex_hl" / "live" / "policy_profiles.py").exists()
    assert not (ROOT / "plugin" / "src" / "codex_hl" / "live" / "t50_driver.py").exists()
    assert not (ROOT / "tests" / "test_live_t50_driver.py").exists()
    assert not (ROOT / "tests" / "test_live_driver.py").exists()


def test_current_mainline_files_do_not_reference_removed_public_entrypoints() -> None:
    failures: list[str] = []
    for root in CURRENT_PATHS:
        for path in iter_text_files(root):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT).as_posix()
            for label, pattern in FORBIDDEN_PATTERNS.items():
                if pattern.search(text):
                    failures.append(f"{rel}: {label}")
    assert failures == []


def test_pyproject_does_not_expose_automated_live_driver() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "codex-hl-civ6-live-driver" not in text
    assert "codex_hl.live.driver:main" not in text
    assert "codex-hl-civ6-live-t50-driver" not in text
    assert "codex-hl-civ6-observe" not in text


def test_demos_do_not_import_execution_policy() -> None:
    forbidden = [
        "codex_hl.evidence.observation",
        "legacy_baseline",
        "rules_runner",
        "t50_strategy_audit",
        "TECH_PRIORITY",
        "CIVIC_PRIORITY",
        "PRODUCTION_PRIORITY",
        "maybe_set_city_production",
        "maybe_expand_with_settler",
    ]
    for path in (ROOT / "plugin" / "src" / "codex_hl" / "demos").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.relative_to(ROOT)} contains forbidden execution token {token}"


def test_historical_t50_lessons_are_archived_and_not_active() -> None:
    sys.path.insert(0, str(ROOT / "plugin" / "src"))
    try:
        from codex_hl.strategy import registry

        asset_root = ROOT / "plugin" / "assets" / "codex_hl" / "strategy"
        catalog = registry.validate_catalog(asset_root)
        assets = {asset["asset_id"]: asset for asset in catalog["assets"]}
        archived = assets["strategy.playbook.historical_t50_lessons"]
        assert archived["status"] == "archived"
        snapshot = registry.active_asset_snapshot(asset_root)
        active_ids = {asset["asset_id"] for asset in snapshot["active_assets"]}
        assert "strategy.playbook.historical_t50_lessons" not in active_ids
        policy_path = asset_root / assets["strategy.tool_policy.observation_evidence"]["content_path"]
        policy = policy_path.read_text(encoding="utf-8")
        assert "strategy.playbook.historical_t50_lessons" not in policy
    finally:
        sys.path.remove(str(ROOT / "plugin" / "src"))

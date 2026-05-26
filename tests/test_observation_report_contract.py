from pathlib import Path
import importlib
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "plugin" / "src"
FIXTURE = ROOT / "plugin" / "fixtures" / "observation_report_contract" / "golden_skeleton.html"


def load_runner_module():
    sys.path.insert(0, str(PLUGIN_SRC))
    try:
        return importlib.import_module("codex_hl.evidence.observation")
    finally:
        sys.path.remove(str(PLUGIN_SRC))


def test_human_report_contract_accepts_golden_skeleton():
    module = load_runner_module()
    module.validate_human_report_text(FIXTURE.read_text(encoding="utf-8"))


def test_human_report_contract_rejects_raw_audit_markup():
    module = load_runner_module()
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "</body>",
        "<details><summary>raw</summary><pre>{&quot;turn&quot;: 1}</pre></details></body>",
    )
    with pytest.raises(RuntimeError):
        module.validate_human_report_text(text)

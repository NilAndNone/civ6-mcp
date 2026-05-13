from pathlib import Path
import importlib.util

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_phase1_observe.py"
FIXTURE = ROOT / "tests" / "fixtures" / "phase1_human_report_contract" / "golden_skeleton.html"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("codex_phase1_observe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

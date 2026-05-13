import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "plugin" / "src"


def load_runner_module():
    sys.path.insert(0, str(PLUGIN_SRC))
    try:
        return importlib.import_module("codex_hl.phase1.observer")
    finally:
        sys.path.remove(str(PLUGIN_SRC))


@pytest.mark.parametrize("turns", [3, 10, 50])
def test_phase1_observe_accepts_short_runs_and_t50(monkeypatch, turns):
    module = load_runner_module()
    monkeypatch.setattr(sys, "argv", ["codex-hl-civ6-phase1-observe", "--turns", str(turns)])

    args = module.parse_args()

    assert args.turns == turns


@pytest.mark.parametrize("turns", [1, 11, 49, 51])
def test_phase1_observe_rejects_unsupported_turn_counts(monkeypatch, turns):
    module = load_runner_module()
    monkeypatch.setattr(sys, "argv", ["codex-hl-civ6-phase1-observe", "--turns", str(turns)])

    with pytest.raises(SystemExit):
        module.parse_args()

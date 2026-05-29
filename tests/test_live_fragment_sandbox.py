from __future__ import annotations

import pytest

from codex_hl.live.fragment_sandbox import (
    FragmentSandboxError,
    MAX_SOURCE_BYTES,
    analyze_fragment_source,
    fragments_enabled,
)


def test_fragments_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", raising=False)

    assert fragments_enabled() is False


def test_fragment_feature_flag_accepts_explicit_enable(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HL_CIV6_ENABLE_LIVE_FRAGMENTS", "1")

    assert fragments_enabled() is True


@pytest.mark.parametrize(
    "source, message",
    [
        (
            "def run(live):\n    live.unit_action(unit_id=__import__('os'), action='skip')\n",
            "forbidden name",
        ),
        (
            "def run(live):\n    live.unit_action(unit_id=1, action='skip', note=compile('1', 'x', 'eval'))\n",
            "forbidden name",
        ),
        (
            "def run(live):\n    return subprocess.Popen(['cmd'])\n",
            "forbidden name",
        ),
    ],
)
def test_fragment_sandbox_rejects_import_shell_and_eval_surfaces(
    source: str, message: str
) -> None:
    with pytest.raises(FragmentSandboxError, match=message):
        analyze_fragment_source(source)


def test_fragment_sandbox_enforces_source_size_limit() -> None:
    oversized = "def run(live):\n    live.unit_action(unit_id=1, action='skip')\n" + (
        "# pad\n" * MAX_SOURCE_BYTES
    )

    with pytest.raises(FragmentSandboxError, match="exceeds"):
        analyze_fragment_source(oversized)

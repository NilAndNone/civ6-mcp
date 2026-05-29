from __future__ import annotations

from types import SimpleNamespace

from civ6_connector import game_launcher


def test_is_game_running_handles_missing_tasklist_stdout(monkeypatch) -> None:
    calls: list[tuple[list[str], dict]] = []

    monkeypatch.setattr(game_launcher.sys, "platform", "win32")
    monkeypatch.setattr(game_launcher, "_PROCESS_NAMES", ("CivilizationVI_DX12.exe",))

    def fake_run(args: list[str], **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=None, returncode=0)

    monkeypatch.setattr(game_launcher.subprocess, "run", fake_run)

    assert game_launcher.is_game_running() is False
    assert calls[0][1]["errors"] == "replace"


def test_is_game_running_matches_windows_process_name(monkeypatch) -> None:
    monkeypatch.setattr(game_launcher.sys, "platform", "win32")
    monkeypatch.setattr(game_launcher, "_PROCESS_NAMES", ("CivilizationVI_DX12.exe",))

    def fake_run(args: list[str], **kwargs):
        return SimpleNamespace(stdout="CivilizationVI_DX12.exe 123 Console", returncode=0)

    monkeypatch.setattr(game_launcher.subprocess, "run", fake_run)

    assert game_launcher.is_game_running() is True

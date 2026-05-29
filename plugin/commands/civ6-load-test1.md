# /civ6-load-test1

## Purpose

Load the standard real Civ6 `test 1` save and verify it with `get_game_overview`.
Use this before live Phase 3 gate runs when the current game may be on a stale
turn, closed, or at the main menu.

## Shell

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:UV_PROJECT_ENVIRONMENT=Join-Path $env:TEMP 'codex-hl-civ6-windows-venv'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-load-test1
```

For another save:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:UV_PROJECT_ENVIRONMENT=Join-Path $env:TEMP 'codex-hl-civ6-windows-venv'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-load-test1 --save-name "AutoSave_0013"
```

If the game is running but FireTuner is wedged, use the explicit recovery form:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:UV_PROJECT_ENVIRONMENT=Join-Path $env:TEMP 'codex-hl-civ6-windows-venv'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-load-test1 --force-restart
```

## Notes

- This is a boundary/recovery action: it launches Civ6 if needed, uses the
  existing FrontEnd Lua load path from the main menu, otherwise uses
  `load_game_save`, then verifies with overview.
- It only kills/relaunches Civ6 when `--force-restart` is passed.
- After a Lua load, it attempts to dismiss the Civ6 leader "continue game"
  screen before polling FireTuner; pass `--no-continue-screen` to disable this.
- It may use Lua load, menu OCR, or restart-and-load fallback depending on the
  current Civ6 state.
- It retries initial FireTuner connect and one load attempt because save loading
  often resets the socket once.
- It does not create an observation episode and does not count as T3/T20
  acceptance evidence by itself.

# Live Strict Evidence Runs

This document describes the current evidence/run surface. The executable
mainline is live strict.

## Supported Paths

- `/civ6-observe-live`: interactive MCP-driven operation.
- `/civ6-live-driver`: automated T3/T20/T50 live strict driver.
- `/civ6-runs --runner live`: orchestration wrapper around the live driver.

## Short Run

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver --load-test1 --objective t3 --turn-budget 3 --min-cities 1
```

## T50 Run

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver --load-test1 --objective t50 --turn-budget 50 --min-cities 2
```

## Evidence

- `episodes/<episode_id>/episode.db` is the durable episode database layer.
- `raw/live_plan_events.jsonl` records plan lifecycle.
- `raw/live_events.jsonl` records gateway and verifier events.
- `outputs/live_driver/<episode_id>_driver_summary.json` is a local run
  summary.

## Boundaries

- Every L2+ mutation must pass through a JSON plan, armed step, live gateway,
  and verifier-owned postcondition.
- Strategy assets and candidate packages are read-only runtime inputs unless
  governance explicitly merges them.
- Local run artifacts are not committed by default.
- Full Windows Civ6 `test 1` validation is required before claiming complete
  replacement proof.

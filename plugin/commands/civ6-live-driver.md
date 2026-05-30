# /civ6-live-driver

## Purpose

Run the automated live strict Civ6 driver for T3, T20, and T50 runs. The driver
captures the start turn, resolves an objective, records `start_turn`,
`turn_budget`, `target_turn`, and `objective` in the episode header, and routes
every L2+ mutation through JSON plan submission, armed steps, `ActionGateway`,
and verifier-owned postconditions.

## Shell

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:UV_PROJECT_ENVIRONMENT=Join-Path $env:TEMP 'codex-hl-civ6-windows-venv'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver `
  --load-test1 `
  --objective t50 `
  --turn-budget 50 `
  --min-cities 2
```

For short gates use `--objective t3 --turn-budget 3` or
`--objective t20 --turn-budget 20`.

## Boundaries

- `--turn-budget 3|20|50` is the normal external interface.
- `--target-turn` is only for recovery/debug and is mutually exclusive with
  `--turn-budget`.
- The driver owns execution lifecycle and evidence writing.
- Strategy preference constants live in planner/profile modules, not in the
  driver loop.
- Local artifacts under `episodes/` and `outputs/live_driver/` should not be
  committed.

## Outputs

- `episodes/<episode_id>/episode.db`
- `episodes/<episode_id>/raw/live_plan_events.jsonl`
- `episodes/<episode_id>/raw/live_events.jsonl`
- `outputs/live_driver/<episode_id>_driver_summary.json`

Full Windows Civ6 test 1 live strict validation must be run separately on a real
save before claiming complete replacement proof.

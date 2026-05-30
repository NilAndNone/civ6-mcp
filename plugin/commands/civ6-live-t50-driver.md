# /civ6-live-t50-driver

## Purpose

Run the tracked live strict T50 driver for the standard Civ6 `test 1` save.
Every L2+ game mutation is submitted as a JSON plan, armed, and executed through
`ActionGateway`.

## Shell

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:UV_PROJECT_ENVIRONMENT=Join-Path $env:TEMP 'codex-hl-civ6-windows-venv'
& 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-t50-driver `
  --load-test1 `
  --target-turn 51 `
  --min-cities 2
```

## Recovery

`end_turn` has a runner-level timeout. A timeout records a failed step and leaves
the episode in explicit recovery-needed evidence instead of a permanent
`EXECUTING` state. Save loading or restart must be requested through a recovery
plan; pass `--recovery-save-name <save>` to let the driver submit a
`metadata.plan_kind="recovery"` load/restart step with lineage back to the
failed step.

## Outputs

- `episodes/<episode_id>/episode.db`
- `episodes/<episode_id>/raw/live_plan_events.jsonl`
- `episodes/<episode_id>/raw/live_events.jsonl`
- `outputs/phase5/<episode_id>_driver_summary.json`

These are local runtime artifacts and should not be committed.

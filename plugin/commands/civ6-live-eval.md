# /civ6-live-eval

## Purpose

Build the Phase 5 live evaluation report from existing episode evidence.
This command is read-only: it does not start Civ6, replay saves, execute MCP
actions, run fragments, or merge strategy assets.

## Inputs

- `--target-turns 20|50`
- `--baseline-episode <episode_id>`: repeat or pass comma-separated ids.
- `--candidate-episode <episode_id>`: repeat or pass comma-separated ids.
- `--output <path>`: optional JSON report path; a Markdown report is written
  next to it.

## Outputs

- objective metrics for each baseline and candidate/live episode
- aggregate baseline vs candidate delta
- failure taxonomy summary
- audit-only strategy candidate gate

## Boundary

The gate uses objective ledger/state metrics only. Codex rationale and
self-evaluation text are not accepted as outcome authority. A PASS gate still
does not merge assets; use `/civ6-governance` for guarded audit/merge flow.

## Example

```powershell
$env:PYTHONPATH='O:\civ6\codex-hl-civ6\plugin\src'
python -m codex_hl.live.evaluation `
  --target-turns 20 `
  --baseline-episode legacy_t20_a,legacy_t20_b `
  --candidate-episode live_t20_a,live_t20_b `
  --output outputs\phase5\live_eval_t20.json
```

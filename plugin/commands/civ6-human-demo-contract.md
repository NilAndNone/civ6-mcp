# /civ6-human-demo-contract

## Purpose

Score Human Demo T50 reproduction attempts against the v2 contract. This command
checks final metric acceptance, causal-chain alignment, turn-node milestones,
and the three-valid-attempt stop rule. It is read-only: it consumes existing
episode evidence and does not start Civ6, replay saves, mutate live state, or
merge strategy assets.

## Shell

Single attempt:

```powershell
$env:PYTHONPATH='O:\civ6\codex-hl-civ6\plugin\src'
python -m codex_hl.live.human_demo_contract `
  --episode live_human_demo_t50_20260530_000002 `
  --output outputs\live_driver\live_human_demo_t50_20260530_000002_human_demo_contract_v2.json
```

Attempt window and stop rule:

```powershell
$env:PYTHONPATH='O:\civ6\codex-hl-civ6\plugin\src'
python -m codex_hl.live.human_demo_contract `
  --episode live_human_demo_t50_20260530_000002,live_human_demo_t50_20260530_000003,live_human_demo_t50_20260530_000004 `
  --output outputs\live_driver\human_demo_contract_v2_window.json
```

## Outputs

- JSON report with all strategy essentials, stage milestones, checkpoints,
  must-observe text, failure criteria, final targets, and stop-rule status.
- Markdown report beside the JSON output.
- Single-attempt Markdown includes acceptance rules, the nine strategy
  essentials, final turn plus final metrics, stage scores, and every
  checkpoint's must-observe/failure criteria.
- Window Markdown includes the same acceptance and strategy context, an attempt
  summary with final turn, and an episode-by-episode stage score matrix.
- Acceptance rules in both JSON and Markdown:
  - an attempt succeeds when it is valid and final metrics are greater than or
    equal to the reference T50 targets;
  - stage milestones and causal-chain checkpoints remain quality diagnostics
    and must still be reported, but they do not veto final metric success;
  - stage milestones can pass early when the observed metrics are greater than
    or equal to the milestone floor;
  - passed checkpoint rollback saves can be inherited only when the save is
    actually materialized and loadable, not when a stale artifact record remains;
  - after a major bug fix, the next full validation run starts again from
    `test 1`, with rollback saves used only for narrow technical confirmation.

## Boundary

Success cannot be claimed from reaching T50, selecting Religious Settlements, or
early city count alone. The v2 contract accepts final metric success when a
valid attempt reaches or exceeds: turn 50, 4 cities, population 20, science
20.8, culture 20.1, and era score 31. Key-node alignment remains part of the
quality report rather than a hard veto.

---
name: civ6-observation
description: Use the installed codex-hl-civ6 plugin for live strict Civ6 evidence runs, T3/T20/T50 execution, and read-only evidence handoff.
---

# Civ6 Live Strict Evidence

Read first:

- `../../assets/codex_hl/strategy/catalog.json`
- `strategy.prompt.default_boundary`
- `strategy.memory.low_trust`
- `strategy.playbook.observation`
- `strategy.tool_policy.observation_evidence`

## Purpose

Use live strict to record what happens in real Civ6 runs. Evidence capture does
not auto-merge strategy assets and does not bypass Review, Validation, or
Governance gates.

## Commands

Interactive MCP-driven operation:

```text
/civ6-observe-live --save-name "test 1" --turns 3 --strict-live
```

Automated short run:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver --load-test1 --objective t3 --turn-budget 3
```

Automated T50:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver --load-test1 --objective t50 --turn-budget 50 --min-cities 2
```

## Evidence

- `episodes/<episode_id>/episode.db`
- `raw/live_plan_events.jsonl`
- `raw/live_events.jsonl`
- `outputs/live_driver/<episode_id>_driver_summary.json`

`episodes/` and `outputs/` are local artifacts unless the user explicitly asks
to preserve or submit a specific artifact.

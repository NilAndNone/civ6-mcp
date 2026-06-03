---
name: civ6-observation
description: Use the installed codex-hl-civ6 plugin for model-in-loop live strict Civ6 operation and read-only evidence handoff.
---

# Civ6 Live Strict Evidence

Read first:

- `../../assets/codex_hl/strategy/catalog.json`
- `strategy.prompt.default_boundary`
- `strategy.memory.low_trust`
- `strategy.playbook.observation`
- `strategy.tool_policy.observation_evidence`

## Purpose

Use model-in-loop live strict to record what happens in real Civ6 runs.
Evidence capture does not auto-merge strategy assets and does not bypass
Review, Validation, or Governance gates.

## Commands

Interactive MCP-driven operation:

```text
/civ6-observe-live --save-name "test 1" --turns 3 --strict-live
```

Before every plan, capture the latest context and retrieve the relevant active
strategy assets and Civ6 wiki chunks. The model must author the next small JSON
plan from that fresh context; knowledge is guidance, not an executor.

## Evidence

- `episodes/<episode_id>/episode.db`
- `raw/live_plan_events.jsonl`
- `raw/live_events.jsonl`

`episodes/` and `outputs/` are local artifacts unless the user explicitly asks
to preserve or submit a specific artifact.

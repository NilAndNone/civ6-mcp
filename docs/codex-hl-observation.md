# Live Strict Evidence Runs

This document describes the current evidence/run surface. The executable
mainline is model-in-loop live strict.

## Supported Paths

- `/civ6-observe-live`: interactive MCP-driven operation.
- `/civ6-runs`: offline plan manifests and existing-evidence reports only.
- `/civ6-live-eval`: read-only evaluation of completed live evidence.

## Live Operation

For real Civ6 mutation, use `/civ6-observe-live`. Each plan must start from a
fresh `get_live_turn_context` snapshot, retrieve relevant active strategy
assets and Civ6 wiki chunks, submit a small JSON plan, arm one step, execute
the matching MCP action, and verify observable post-state.

## Evidence

- `episodes/<episode_id>/episode.db` is the durable episode database layer.
- `raw/live_plan_events.jsonl` records plan lifecycle.
- `raw/live_events.jsonl` records gateway and verifier events.
- completion or abort status is recorded through the live plan store.

## Boundaries

- Every L2+ mutation must pass through a JSON plan, armed step, live gateway,
  and verifier-owned postcondition.
- Knowledge base and strategy assets constrain model planning but do not
  replace a fresh model-authored plan.
- Strategy assets and candidate packages are read-only runtime inputs unless
  governance explicitly merges them.
- Driver, auto-run, and live-execute wrappers are not supported entrypoints.
- Local run artifacts are not committed by default.
- Full Windows Civ6 `test 1` validation is required before claiming complete
  replacement proof.

# Asset: strategy.tool_policy.observation_evidence

## Purpose

This tool policy defines how live strict run evidence is accepted.

## Run Policy

- Use `/civ6-observe-live` for interactive MCP-driven operation.
- Use `codex-hl-civ6-live-driver` for automated T3/T20/T50 runs.
- Use `/civ6-runs --runner live` for orchestration.
- Keep `episodes/` and `outputs/` as local run output unless the user names
  specific artifacts to preserve or submit.
- Do not start a separate connector service for the live strict flow unless the
  user is explicitly troubleshooting connector startup.

## Evidence Gate

A live strict run is reviewable only when these evidence classes exist:

- episode header with objective and turn-budget semantics;
- tool and connector calls with timing, parameters, raw result or raw error;
- per-turn context snapshots or explicit representation gaps;
- JSON plan submission and armed-step records;
- gateway mutation events and verifier results;
- save or load lineage when recovery is used;
- summary artifact with final turn, city count, action count, and failure
  taxonomy if the run did not complete.

## Boundary

Evidence capture records what happened. It does not mark strategy changes as
accepted, does not merge assets, and does not let archived historical lessons
override active runtime policy.

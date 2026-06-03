# Asset: strategy.tool_policy.observation_evidence

## Purpose

This tool policy defines how live strict run evidence is accepted.

## Run Policy

- Use `/civ6-observe-live` for interactive MCP-driven operation.
- Do not use driver, auto-run, or live-execute wrappers for real game mutation.
- `/civ6-runs` is offline-only; `--execute` and `--runner live` are removed.
- Before each live plan, retrieve relevant active strategy assets and Civ6 wiki
  chunks, but make the decision from the latest observed live context.
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
accepted, does not merge assets, and does not let archived historical lessons,
strategy assets, or wiki facts override a fresh model-authored live plan.

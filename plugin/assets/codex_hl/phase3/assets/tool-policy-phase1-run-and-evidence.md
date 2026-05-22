# Asset: tool_policy.phase1_run_and_evidence

## Purpose

This tool policy defines how Phase 1 runner results are accepted.

## Run Policy

- Use `codex-hl-civ6-phase1-observe` for short runs and T50.
- Use `--report-only <episode_id>` only to rebuild reports from existing
  evidence. Report-only mode must not start Civ6 or modify current gameplay.
- Keep `episodes/` as local run output unless the user explicitly names an
  episode to include.
- Do not start a separate `civ6-connector` service for the Phase 1 flow.
- Default preflight may stop stale repo-local connector processes and reset the
  Civ6 frontend before loading `test 1`; use bypass flags only for explicit
  troubleshooting.

## Evidence Gate

A short run or T50 run is reviewable only when these evidence classes exist:

- tool and connector calls with timing, parameters, raw result or raw error;
- per-turn state snapshots covering empire, cities, units, notifications,
  threats, tech/civic, and production, or explicit gaps;
- decision atoms with context, available actions, choice, rationale, rejected
  alternatives, execution, outcome, and evidence ids;
- save links connecting checkpoints to episode, turn, decision, or event;
- Chinese human HTML report;
- agent handoff report and full audit report.

## Human HTML Contract

- `phase1_short_run_report.html` is the human review entry.
- It must present natural-language Chinese review prose rather than raw JSON.
- Keep the accepted section order: title, verdict, observed game-state changes,
  turn narrative, decision flow, evidence boundary, save/decision links, gaps,
  and agent handoff.
- Do not put raw JSON blocks, `<details>`, `<pre>`, or encoded state dumps in
  the human report. Raw evidence belongs in audit artifacts and `raw/`.

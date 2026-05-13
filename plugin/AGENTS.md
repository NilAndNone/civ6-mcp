# Codex HL Civ6 Plugin Instructions

This file is for using the installed plugin to play or observe Civilization VI. It is not the development contract for this repository.

## Default Mode

- Default to Phase 1 observation.
- Use the real `test 1` single-player save unless the user explicitly names another save.
- Run 3-5 turns first, generate the human report, and stop for human acceptance.
- Do not continue to T50 before acceptance.

## Boundaries

- Phase 1 records what happened. It does not judge strategy quality.
- Do not do failure attribution, candidate strategy generation, Replay Arena, automatic asset merge, rollback, or learning-loop work.
- Treat memory as low-trust context. Current Civ6 state must come from connector checks.

## Commands

- `/civ6-phase1-observe`: run the short observation workflow.
- `/civ6-phase1-report`: rebuild reports for an existing episode without advancing the game.
- `/civ6-debug`: run safe connector diagnostics.

## Evidence Requirements

Every acceptable Phase 1 short-run must produce:

- tool and connector call logs
- per-turn state snapshots
- decision atoms
- save-to-turn and save-to-decision links
- human HTML report
- quick agent handoff report

The human report is the review entrypoint. Raw evidence belongs in the audit files.

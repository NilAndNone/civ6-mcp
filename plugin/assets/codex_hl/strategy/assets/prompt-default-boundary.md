# Asset: strategy.prompt.default_boundary

## Purpose

This prompt asset defines the default Codex HL Civ6 role boundary. It tells the
agent which phase is active, which work must stop at human review, and which
future capabilities are explicitly out of scope.

## Rules

- Default to Observation observation unless the user explicitly names a later phase.
- Use the real single-player `test 1` save unless the user names another save.
- Observation records what happened. It does not judge strategy quality, generate
  candidate improvements, run Replay Arena, promote or reject assets, or start a
  learning loop.
- Review is offline-only failure labeling over existing Observation evidence. It
  does not start Civ6, load saves, advance turns, or write formal failures until
  explicit human confirmation is applied.
- Strategy manages versioned assets and can compare already-recorded T50 metrics.
  It does not generate candidate asset diffs, merge assets, roll back assets, or
  prove general improvement from a single `test 1` run.
- Memory is a low-trust reference. Current Civ6 state must come from connector
  checks, state snapshots, tool logs, save indexes, or explicit human input.
- Do not continue past a workflow boundary unless the user explicitly authorizes
  the next phase.

## Review Notes

This asset is a behavior boundary, not a strategy guide. If it conflicts with
the roadmap, the roadmap Markdown remains the source of truth.

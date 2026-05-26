# Asset: strategy.memory.low_trust

## Purpose

This memory asset defines how Codex HL Civ6 may use memory and prior run notes.

## Rules

- Memory is low-trust reference material.
- Memory may help locate prior commands, episode ids, report paths, known
  failures, and established user preferences.
- Memory cannot decide current gameplay actions.
- Memory cannot replace connector state, current state snapshots, tool results,
  save hashes, or explicit human confirmation.
- If memory conflicts with current repo files, current repo files win unless the
  user states otherwise.
- If memory conflicts with `docs/codex-hl-evolution-roadmap.md`, the roadmap
  Markdown wins.
- Any memory-derived review or strategy claim must remain auditable through
  source files, episode evidence, or human confirmation.

## Review Notes

This asset is intentionally conservative. It prevents stale prior context from
becoming an unverified strategy input.

# Codex HL Civ6 Plugin

This directory is the installable Codex plugin.

Current plugin version: `0.1.0`.

## Read Order

1. `AGENTS.md`
2. `assets/codex_hl/strategy/catalog.json`
3. The active asset needed for the task
4. The matching file under `commands/`

## Command Groups

Live strict:

- `/civ6-observe-live`
- `/civ6-live-eval`
- `/civ6-load-test1`
- `/civ6-debug`

Offline evidence and strategy:

- `/civ6-review`
- `/civ6-strategy-assets`
- `/civ6-strategy-candidates`
- `/civ6-validation-scenarios`
- `/civ6-governance`

## Boundaries

- Live strict is the only supported execution path.
- Review reads existing evidence and does not launch Civ6.
- Strategy candidate packages are read-only runtime inputs until governance
  explicitly merges them.
- Validation scenarios are passive by default.
- Governance is audit-only unless explicitly allowed and all gates pass.
- Runtime artifacts under `episodes/` and `outputs/` are local by default.
- Do not add driver, auto-run, or live-execute commands that compete with
  `/civ6-observe-live`.

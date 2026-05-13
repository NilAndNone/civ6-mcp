# codex-hl-civ6 Development Instructions

This file is for developing the plugin in this repository. It is not the runtime playbook for an installed plugin.

## Source Of Truth

- `docs/codex-hl-evolution-roadmap.md` is the roadmap source of truth.
- `docs/codex-hl-evolution-roadmap.html` is only the human review companion.
- Do not edit either roadmap file without explicit user approval.
- If Markdown and HTML disagree, follow the Markdown and report the mismatch.

## Repository Shape

- `plugin/` is the self-contained Codex plugin. It contains runtime code, plugin metadata, commands, skills, agents, fixtures, and plugin usage instructions.
- `plugin/AGENTS.md` is for using the installed plugin to play or observe Civ6.
- Root `AGENTS.md`, `README.md`, and `docs/` are for developing and validating the plugin.
- `archive/legacy/` contains old CivBench, web, eval, devlog, publish, Hotseat, and generic MCP assets. Keep them isolated from the active plugin path.

## Current Scope

The active implementation scope is Phase 0/1 only.

- Phase 0: vocabulary, boundary, asset, and checklist alignment.
- Phase 1: real Civ6 observation, episode evidence, decision atoms, save links, and human review HTML.
- Do not implement Phase 2+ failure attribution, candidate strategy generation, Replay Arena, asset merge, rollback, or automatic learning unless the user explicitly asks.

## Development Routing

- For plugin architecture or packaging: inspect `plugin/.codex-plugin/plugin.json`, `plugin/AGENTS.md`, and `plugin/commands/`.
- For Phase 1 workflow changes: inspect `docs/codex-hl-phase1-observation.md`, then `plugin/src/codex_hl/phase1/observer.py`, then the relevant tests.
- For Civ6 connection changes: keep behavior inside `plugin/src/civ6_connector/` and avoid leaking connector details into root docs.
- For old CivBench/web/eval questions: read from `archive/legacy/`; do not move those assets back into the active path without approval.

## Ownership And Safety

- The user owns the roadmap and strategy direction.
- Codex owns implementation, tests, validation scripts, plugin packaging, and docs unless the user narrows scope.
- Do not use a worktree in this repository unless the user explicitly asks.
- Do not revert unrelated user changes.
- `episodes/` is local run output and should stay untracked unless the user asks for a specific artifact.

## Verification

Before reporting completion, run the local checks documented in `docs/codex-hl-phase1-observation.md`.

True end-to-end acceptance still requires a Windows Civ6 machine to run a real 3-turn `test 1` Phase 1 short-run through the plugin.

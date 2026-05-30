# codex-hl-civ6 Development Instructions

This file governs development work in this repository. Installed-plugin usage
instructions live in `plugin/AGENTS.md`.

## Source Of Truth

Current development source of truth:

1. `docs/current-architecture.md`
2. `plugin/AGENTS.md`
3. `plugin/commands/*.md`
4. Active strategy assets in `plugin/assets/codex_hl/strategy/catalog.json`
5. Tests as executable contracts

HTML files are generated human-readable views and are never authoritative.
Historical or reference docs cannot define runtime entrypoints.

## Repository Layout

- `plugin/` is the installable Codex plugin: runtime code, plugin metadata,
  commands, skills, agent instructions, fixtures, and plugin docs.
- `plugin/AGENTS.md` is the first installed-plugin instruction file.
- Root `AGENTS.md`, root `README.md`, and `docs/` serve development, design,
  and acceptance.
- `archive/legacy/` contains old CivBench, web, evaluation, development-log,
  Hotseat, and generic MCP assets. They are not current mainline inputs.

## Current Mainline

The current executable mainline is live strict:

- `/civ6-observe-live` for interactive MCP-driven live strict operation.
- `/civ6-live-driver` for automated T3/T20/T50 runs.
- `/civ6-runs --runner live` for orchestration around the live driver.

`codex_hl.evidence.store` remains the episode database layer. Legacy execution
runners and old report-only/rebuild command compatibility are removed.

## Development Routing

- For architecture or entrypoint work, read `docs/current-architecture.md`,
  `plugin/AGENTS.md`, and `plugin/commands/`.
- For live driver work, read `plugin/src/codex_hl/live/driver.py`,
  `objective.py`, `planner.py`, `policy_profiles.py`, `gateway.py`,
  `ledger.py`, `plan_store.py`, and their tests.
- For Review, Strategy, Validation, and Governance, read their corresponding
  docs and modules under `plugin/src/codex_hl/`.
- For Civ6 connector work, keep low-level behavior inside
  `plugin/src/civ6_connector/`; do not move connector details into root docs.
- Read old CivBench or research material only from `archive/legacy/` unless the
  user explicitly approves moving content back into the mainline.

## Ownership And Safety

- The user owns strategy direction.
- Codex owns implementation, tests, validation scripts, plugin packaging, and
  development docs unless the user narrows scope.
- Do not use worktrees unless explicitly requested.
- Do not revert changes you did not make.
- `episodes/`, `outputs/`, and live run artifacts are local by default and
  should not be committed unless the user names specific artifacts.

## Verification

Run the checks relevant to the touched modules before delivery. For the live
mainline cleanup, the baseline local set is:

```powershell
python -m pytest tests -q
codex-hl-civ6-strategy-assets --check
git diff --check
```

Full replacement proof still requires a real Windows Civ6 `test 1` live strict
run. Until that passes, claim only that the legacy executable path has been
removed and live strict is the only supported execution path.

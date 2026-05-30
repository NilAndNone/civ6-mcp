# codex-hl-civ6

`codex-hl-civ6` is a Codex plugin project for live strict Civilization VI
operation, evidence storage, offline review, versioned strategy assets,
candidate strategy packages, passive validation scenarios, governed asset
changes, and multi-run orchestration.

## Version

- Current version: `0.1.0`
- Architecture source: `docs/current-architecture.md`

This is a breaking cleanup release. The legacy executable path has been
removed. Live strict is the only supported execution path.

## Supported Entrypoints

- `/civ6-observe-live`: interactive MCP-driven live strict operation.
- `/civ6-live-driver`: automated T3/T20/T50 live strict driver.
- `/civ6-runs --runner live`: orchestration wrapper around the live driver.
- `/civ6-live-eval`: read-only live run evaluation.
- `/civ6-review`, `/civ6-strategy-assets`, `/civ6-strategy-candidates`,
  `/civ6-validation-scenarios`, and `/civ6-governance`: offline review,
  strategy, validation, and governance workflows.

Full Windows Civ6 live strict validation must be run separately on a real
`test 1` save before claiming complete replacement proof.

## Repository Layout

- `plugin/`: installable Codex plugin.
- `plugin/commands/`: installed slash-command docs.
- `plugin/src/codex_hl/live/`: live strict driver, objective, planner,
  gateway, ledger, plan store, and evaluation modules.
- `plugin/src/codex_hl/evidence/store.py`: episode database layer.
- `plugin/assets/codex_hl/strategy/`: versioned strategy assets.
- `docs/`: current architecture, module docs, historical/reference material.
- `tests/`: executable contracts and structural cleanup gates.
- `archive/legacy/`: old assets outside the current mainline.

## Local Checks

```powershell
python -m pytest tests -q
codex-hl-civ6-strategy-assets --check
git diff --check
```

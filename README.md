# codex-hl-civ6

`codex-hl-civ6` is a Codex plugin project for model-in-loop live strict
Civilization VI operation, Human Demo evidence capture, evidence storage,
offline review, versioned strategy assets, candidate strategy packages, passive
validation scenarios, and governed asset changes.

## Version

- Current version: `0.1.0`
- Architecture source: `docs/current-architecture.md`

This is a breaking cleanup release. The legacy executable path has been
removed. Model-in-loop live strict is the supported gameplay execution path.

## Supported Entrypoints

- `/civ6-observe-live`: interactive MCP-driven live strict operation with
  model-authored JSON plans from fresh turn context.
- `/civ6-human-demo-record`: read-only Human Demo capture into SQLite.
- `/civ6-human-demo-contract`: read-only Human Demo reproduction scoring.
- `/civ6-live-eval`: read-only live run evaluation.
- `/civ6-review`, `/civ6-strategy-assets`, `/civ6-strategy-candidates`,
  `/civ6-validation-scenarios`, and `/civ6-governance`: offline review,
  strategy, validation, and governance workflows.

The automated live driver and `/civ6-runs --runner live` execution path have
been removed. Do not add new driver, auto-run, or live-execute commands that
compete with `/civ6-observe-live`.

Full Windows Civ6 live strict validation must be run separately on a real
`test 1` save before claiming complete replacement proof.

## Repository Layout

- `plugin/`: installable Codex plugin.
- `plugin/commands/`: installed slash-command docs.
- `plugin/src/codex_hl/live/`: live strict gateway, ledger, plan store,
  evaluation, context, and evidence modules.
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

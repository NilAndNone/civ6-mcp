# codex-hl-civ6

This repository develops the `codex-hl-civ6` Codex plugin.

The plugin is an observation-first Civilization VI harness for Codex HL. Its current scope is Phase 0/1: align vocabulary, run real Civ6 short observations, record evidence, produce a human report, and stop before longer runs.

## Active Layout

- `plugin/` - the self-contained Codex plugin users install.
- `plugin/AGENTS.md` - runtime instructions for using the plugin.
- `plugin/src/codex_hl/` - Phase 0/1 plugin logic.
- `plugin/src/civ6_connector/` - lowest-level Civ6 connector.
- `docs/` - development roadmap and validation contracts.
- `tests/` - development tests for the plugin and connector.
- `archive/legacy/` - old CivBench, web, eval, devlog, publish, Hotseat, and generic MCP assets.

## Development Setup

```bash
uv sync
uv run pytest tests -q
```

The main local checks are:

```bash
uv run python -m py_compile plugin/src/codex_hl/phase1/observer.py
uv run pytest tests/test_plugin_structure.py tests/test_phase1_human_report_contract.py -q
uv run pytest tests -q
```

## Plugin Entry Points

The installed plugin exposes a small set of strong commands:

- `/civ6-phase1-observe`
- `/civ6-phase1-report`
- `/civ6-debug`

The matching command documents live in `plugin/commands/`.

## End-To-End Acceptance

Local tests prove the plugin package, imports, and report contract. Full acceptance still requires Windows Civ6 validation:

1. Install/use the plugin from the Civ6 machine.
2. Load the real `test 1` single-player save.
3. Run a 3-turn Phase 1 observation short-run.
4. Confirm the episode evidence and human HTML report are generated.
5. Stop before T50 until human acceptance.

# codex-hl-civ6 Plugin Architecture

This repository now separates development from usage.

## Development Layer

The repository root is for building and validating the plugin:

- `AGENTS.md` defines development routing and ownership.
- `docs/` contains the roadmap and validation contracts.
- `tests/` verifies plugin structure, connector behavior, and report contracts.
- `archive/legacy/` stores old assets outside the active path.

## Plugin Layer

`plugin/` is the self-contained installable plugin:

- `.codex-plugin/plugin.json` exposes plugin metadata.
- `AGENTS.md` tells Codex how to use the installed plugin.
- `commands/` exposes only the approved user-facing commands.
- `skills/` contains the Phase 1 observation workflow.
- `src/codex_hl/` contains Phase 0/1 logic.
- `src/civ6_connector/` contains the lowest-level Civ6 connection layer.
- `fixtures/` contains report contract fixtures needed by the plugin.

## Runtime Flow

Codex reads the installed plugin instructions, invokes a small command surface, runs Phase 1 through `codex_hl.phase1`, and reaches Civ6 only through `civ6_connector`.

The short-run produces an episode and then stops before T50.

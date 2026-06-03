# Codex HL Civ6 Plugin Instructions

This file is for Codex after the plugin is installed.

## Runtime Source Of Truth

Runtime source of truth:

1. `commands/*.md`
2. Active strategy assets in `assets/codex_hl/strategy/catalog.json`
3. `skills/*/SKILL.md`
4. `docs/current-architecture.md` for repository architecture context

No roadmap, historical document, generated HTML, or reference pack can override
active runtime commands or active strategy assets.

## Supported Runtime Entrypoints

Model-in-loop live strict is the supported gameplay execution path:

- `/civ6-observe-live`: interactive MCP-driven JSON-plan operation. For every
  live turn, observe context first, have the model author a JSON plan, submit
  it, arm one step, execute the matching MCP action, and verify post-state.
- `/civ6-human-demo-record`: read-only Human Demo capture into SQLite.
- `/civ6-human-demo-contract`: read-only Human Demo reproduction scoring.

Removed entrypoints:

- The automated live driver has been removed. Do not add a replacement driver,
  auto-run command, or live-execute wrapper.
- `/civ6-runs --execute` and `/civ6-runs --runner live` hard fail before any
  connector or game mutation.

Supporting commands:

- `/civ6-load-test1`
- `/civ6-debug`
- `/civ6-live-eval`
- `/civ6-wiki-build`
- `/civ6-review`
- `/civ6-strategy-assets`
- `/civ6-strategy-candidates`
- `/civ6-validation-scenarios`
- `/civ6-governance`

## Knowledge Base

`assets/codex_hl/knowledge/civ6-wiki/` is a factual Civ6 Markdown knowledge
base for model retrieval. It can provide stable encyclopedia facts, source
links, aliases, and RAG chunks, but it does not override current live game
state, live strict decisions, active strategy assets, command docs, or MCP
observations.

## Boundaries

- Every L2+ live mutation must be tied to an active episode, JSON plan, armed
  step, and captured context hash.
- For Human Demo reproduction, the JSON plan must be authored by the model from
  the latest observed context. Python/profile-generated automated driver plans
  are not valid Human Demo acceptance evidence.
- Fragment execution is optional, off by default, and limited to one armed step
  when explicitly enabled.
- Review reads existing evidence only; it does not start Civ6.
- Strategy assets are changed only through governed candidate workflows.
- Governance is audit-only unless explicitly allowed and all gates pass.
- `episodes/` and `outputs/` are local artifacts by default.

Full Windows Civ6 `test 1` validation is a separate external gate.

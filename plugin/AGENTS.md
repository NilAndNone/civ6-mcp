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

Live strict is the only supported execution path:

- `/civ6-observe-live`: interactive MCP-driven JSON-plan operation.
- `/civ6-live-driver`: automated T3/T20/T50 live strict driver.
- `/civ6-runs --runner live`: orchestration wrapper around the live driver.

Supporting commands:

- `/civ6-load-test1`
- `/civ6-debug`
- `/civ6-live-eval`
- `/civ6-review`
- `/civ6-strategy-assets`
- `/civ6-strategy-candidates`
- `/civ6-validation-scenarios`
- `/civ6-governance`

## Boundaries

- Every L2+ live mutation must be tied to an active episode, JSON plan, armed
  step, and captured context hash.
- Fragment execution is optional, off by default, and limited to one armed step
  when explicitly enabled.
- Review reads existing evidence only; it does not start Civ6.
- Strategy assets are changed only through governed candidate workflows.
- Governance is audit-only unless explicitly allowed and all gates pass.
- `episodes/` and `outputs/` are local artifacts by default.

Full Windows Civ6 `test 1` validation is a separate external gate.

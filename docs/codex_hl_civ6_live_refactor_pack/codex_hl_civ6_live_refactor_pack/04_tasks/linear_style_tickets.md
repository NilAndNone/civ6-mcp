# Linear-style Tickets

## LIVA-000 — Prepare branch and docs

- Create branch `codex/live-codex-mcp-agent` from `windows-test`.
- Add `docs/live_refactor/` with copied architecture summary.
- No behavior change.

## LIVA-010 — Mutation registry

- Add `codex_hl.live.mutation_levels`.
- Add `codex_hl.live.actions`.
- Register known MCP and runner actions.
- Tests for unclassified action failure.

## LIVA-020 — Direct mutation inventory

- Static scan `observation.py`, `runs/orchestrator.py`, `civ6_connector/server.py`.
- Produce `docs/live_refactor/phase_0_inventory.md`.

## LIVA-100 — ActionGateway skeleton

- Add request/result dataclasses.
- Add modes: legacy/shadow/live_strict.
- Add ledger event hook.

## LIVA-110 — Gateway partial migration

- Migrate `set_research`, `set_city_production`, selected `unit_action` paths.
- Preserve behavior in shadow mode.

## LIVA-200 — Live plan schema/store

- Add JSON schema validation.
- Add plan store.
- Add state machine.

## LIVA-210 — Live MCP lifecycle tools

- Add start/context/submit/arm/abort/finish tools.
- Add plugin `.mcp.json` and `/civ6-observe-live` docs.

## LIVA-220 — Strict step guard

- Enforce active plan step for L2+.
- stale context / args mismatch / duplicate rejection.

## LIVA-230 — Verifier v1

- Basic postcondition verification.
- Fail/inconclusive handling.

## LIVA-300 — Orchestrator runner split

- `--runner live|legacy-baseline`.
- `--execute` without runner rejected.

## LIVA-400 — Optional fragment sandbox

- Only after Phase 2/3 pass.
- Single step only.

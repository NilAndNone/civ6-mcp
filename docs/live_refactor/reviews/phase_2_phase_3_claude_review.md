# Phase 2 + Phase 3 — Claude Architecture Review

Reviewer: Claude Code (architecture review only; no implementation files modified).
Date: 2026-05-29
Branch: codex/live-codex-mcp-agent

## Verdict

- PHASE2_PASS: true
- PHASE3_PASS: true
- ARCHITECTURE_PASS: true

Verdicts are scoped to the static / unit-testable deliverables. They are gate
passes **with a MAJOR caveat**: the post-state verifier is not wired to any
pre/post state capture in the live execution path, so the documented end-to-end
T3 flow (`/civ6-observe-live ... --strict-live` → execute steps → `finish_live_episode`)
would currently be unable to finish. Real T3 acceptance was **not run** here
(requires Windows Civ6/FireTuner) and must be executed before the live pipeline
is claimed functional. See MAJOR-1.

## Scope Inspected (exact files)

Implementation:
- `plugin/src/codex_hl/live/schemas.py`
- `plugin/src/codex_hl/live/state_machine.py`
- `plugin/src/codex_hl/live/plan_store.py`
- `plugin/src/codex_hl/live/gateway.py`
- `plugin/src/codex_hl/live/verifier.py`
- `plugin/src/codex_hl/live/context.py`
- `plugin/src/codex_hl/live/ledger.py`
- `plugin/src/codex_hl/live/runner.py`
- `plugin/src/codex_hl/live/actions.py`
- `plugin/src/civ6_connector/server.py` (live lifecycle tools L605–844; gateway
  wiring `_gateway_tool_call`/`_logged_gateway` L536–588; mutating-tool call
  sites; strict-mode guards at L475, L2523, L2705, L3460)
- `plugin/src/codex_hl/runs/orchestrator.py` (runner selection: `RUNNER_LIVE`/
  `RUNNER_LEGACY_BASELINE` L35–37, `run_observation` L358, `run_live_observation`
  L403, `validate_args` L1905, runner dispatch L2254)

Config / docs:
- `plugin/.codex-plugin/plugin.json`, `plugin/.codex-plugin/.mcp.json`
- `plugin/commands/civ6-observe-live.md`, `civ6-observe.md`, `civ6-runs.md`
- `docs/live_refactor/legacy_baseline.md`

Tests:
- `tests/test_live_plan_schema.py`, `tests/test_live_state_machine.py`,
  `tests/test_live_mcp_guard.py`, `tests/test_live_postcondition_verifier.py`,
  `tests/test_live_action_gateway.py`, `tests/test_orchestrator_runner_selection.py`,
  `tests/test_legacy_baseline_deprecation.py`, `tests/test_runs_orchestrator.py`,
  `tests/test_plugin_structure.py`

Context artifacts: `/tmp/civ6_phase2_phase3_codex.jsonl`,
`/tmp/civ6_phase2_phase3_codex_report.md`, Phase 1 gateway/gate docs.

## Verification Run (lightweight; no real game)

- `py_compile` on server.py + all `live/*.py` + orchestrator.py → OK.
- `rg "register_live_fragment|execute_live_fragment|fragment_sandbox" plugin/src tests`
  → no matches.
- `pytest` (the nine files above) → **86 passed in 6.76s**.
- Confirmed all Phase 2/3 docs + config files exist with expected content.

## Phase 4 Fragment Boundary

**Respected.** No `register_live_fragment` / `execute_live_fragment` /
`fragment_sandbox` symbol or MCP tool exists anywhere in `plugin/src` or `tests`.
The only fragment reference is the inert string literal `"fragment"` in the
`ActionSource` type union in `gateway.py:17` — it is a typing placeholder with no
code path, no tool registration, and no execution route. No multi-step free
execution path was introduced.

## Phase 2 Assessment

Deliverables present and correct:
- Live lifecycle MCP tools all wired (`start_live_episode`,
  `get_live_turn_context`, `submit_turn_plan`, `arm_live_step`,
  `abort_live_episode`, `finish_live_episode`), returning api_contracts-shaped
  payloads (`server.py:676–844`).
- `.mcp.json` + `plugin.json: "mcpServers": "./.mcp.json"` present; default
  `CODEX_HL_CIV6_LIVE_GATEWAY_MODE=legacy_compat` (does not auto-arm strict).
- JSON plan schema validation (`schemas.normalize_turn_plan`): rejects non-object,
  empty steps, duplicate step_id, bad mutation level, bad args/postconditions.
- Append-only event-sourced state (`plan_store.py`) with deterministic replay;
  separate `raw/live_plan_events.jsonl` (lifecycle) vs `raw/live_events.jsonl`
  (gateway actions).
- LIVE_STRICT guard (`gateway._strict_validation`) enforces, in order: active
  non-terminal episode, plan exists, step exists, **step status == ARMED**,
  context_hash match, tool match, **args fingerprint match**, mutation-level ≤
  step allowance. Duplicate execution is blocked because a consumed step leaves
  `ARMED` (→ EXECUTING/EXECUTED) and re-execute fails the ARMED check
  (verified by `test_live_mcp_guard.test_live_strict_executes_once_then_rejects_duplicate_step`).
- `finish_episode` rejects unverified EXECUTED/EXECUTING steps and (defense-in-depth)
  allowed unplanned L2+ mutations, and refuses `NEED_RECOVERY_PLAN`.
- Verifier upgraded from Phase-1 stub to deterministic `PostconditionVerifier`
  (unit move/block, city production, research/civic, one-turn advance, gold
  purchase delta), with `StubVerifier` retained as an alias. It does not treat
  prose/rationale as outcome authority.

Acceptance-matrix Phase 2 items: all code-verifiable items pass; T3 real
acceptance NOT RUN (Windows-only); this review is the remaining gate.

## Phase 3 Assessment

- `--runner {live,legacy-baseline}` added; `--execute` without `--runner` is
  rejected (`validate_args` L1910–1911); invalid runner rejected (L1907–1909).
- `run_live_observation` (L403) invokes `python -m codex_hl.live.runner` with
  `CODEX_HL_CIV6_LIVE_GATEWAY_MODE=live_strict`; it does **not** call the legacy
  `codex_hl.evidence.observation` rules runner. Dispatch at L2254 selects by
  `runner_kind`.
- `run_observation` (legacy-baseline, L358) still calls `codex_hl.evidence.observation`
  and stamps `runner_kind=legacy-baseline` + `runner_deprecation`. Legacy runner
  is **not deleted/archived** (matrix: "不允许 删除 baseline" honored).
- Manifest stamps `runner_kind` and `runner_deprecation` (L1996–2007); per-episode
  payloads stamp `runner_kind` (L2273).
- Docs updated: `civ6-observe.md` marks legacy/deprecated/baseline; `civ6-runs.md`
  documents runner requirement; `legacy_baseline.md` present.

All Phase 3 acceptance-matrix items pass.

## BLOCKERS

None.

## MAJOR

- **MAJOR-1 — Verifier is not wired to pre/post state in the live path; finish
  becomes unreachable after any executed L2+ step.** `ActionGateway.execute`
  (`gateway.py:314–318`) calls `self.verifier.verify(request=..., result=...,
  postconditions=...)` with **no `pre_state`/`post_state`**, and the ledger event
  is written with `pre_state_hash=None`/`post_state_hash=None`. Every
  `PostconditionVerifier` rule that matters needs pre/post state, so the live
  path always yields `INCONCLUSIVE` (directly asserted by
  `tests/test_live_action_gateway.py:228`). `next_after_verifier("INCONCLUSIVE")`
  → step status `EXECUTED`, and `LivePlanStore.finish_episode`
  (`plan_store.py:392–402`) treats any `EXECUTED` step as "unverified executed
  step" and raises. Net effect: a real episode that executes even one gated step
  can never `finish_live_episode` successfully. The deterministic verifier is
  fully unit-tested in isolation but effectively dead in the live pipeline. This
  is a logic gap provable without the game; it is masked only because real T3 was
  not run. Fix direction: capture a post-state snapshot (e.g. reuse
  `get_live_turn_context` capture or an explicit post-state read) and thread
  `pre_state`/`post_state` (+ hashes) into `verify()` and the ledger so the
  verifier can reach PASS/FAIL, and persist pre/post per step as T3 requires.

## MINOR

- **MINOR-1 — Strict mode leaks into process-global env and is never reset.**
  `start_live_episode` sets `os.environ["CODEX_HL_CIV6_LIVE_GATEWAY_MODE"]
  = live_strict` (`server.py:718–719`) and `_set_live_env` persists
  episode/plan/step/context env, but neither `abort_live_episode` nor
  `finish_live_episode` clears them. In a long-lived MCP server process,
  subsequent non-live mutating calls then run under stale strict context. Tools
  take explicit params, but `_gateway_tool_call` falls back to env context
  (`server.py:550–555`). Recommend clearing live env on abort/finish.
- **MINOR-2 — Not all L2+ MCP tools expose the documented binding params.**
  api_contracts requires every L2+ tool to support `episode_id/plan_id/step_id/
  context_hash`. Only a subset (`set_research`, `set_city_production`,
  `purchase_item`, `unit_action`, `end_turn`, `purchase_tile`, `city_action`)
  expose them as explicit args; the rest (e.g. `set_policies`, `spy_action`,
  diplomacy/governor/religion/great-person/`change_government`/`queue_wc_votes`)
  route via `_logged_gateway` and bind only through env context set by
  `arm_live_step`/`get_live_turn_context`. Functionally bindable in strict, but
  the literal contract ("必须支持" explicit params) is only partially met.
- **MINOR-3 — `next_episode_after_plan` has a dead branch** (`state_machine.py:20–24`):
  both the `NEED_RECOVERY_PLAN` branch and the fallthrough return
  `PLAN_SUBMITTED`. Harmless, but the `if` is misleading.
- **MINOR-4 — `_result_indicates_blocked` is a broad substring heuristic**
  (`verifier.py:408–421`): any result text containing `error`/`cannot`/`invalid`
  classifies an unchanged-position unit action as PASS("blocked"). This can mask
  a genuine failed move as a pass. Acceptable for an initial verifier but should
  be tightened with structured tool results.

## Unrun / Out-of-scope Acceptance

- **T3 real-game acceptance NOT RUN.** `/civ6-observe-live --save-name "test 1"
  --turns 3 --strict-live` requires the Windows Civ6 + FireTuner runtime and the
  installed MCP plugin; not executable in this Linux repo. Codex report concurs
  ("NOT RUN here"). Per MAJOR-1, the current finish-gate logic would block this
  flow until pre/post state capture is added — T3 should be the explicit
  validation of that fix.
- Phase 5 eval/baseline-comparison metrics are out of scope for this review.

## Summary

Phase 2 and Phase 3 deliverables are present, internally consistent, well-tested
at the unit level (86 passing), and respect the Phase 4 fragment boundary and the
"don't delete baseline" constraint. The architecture (event-sourced plan store,
ordered strict guard, explicit runner split) is sound. The one substantive gap is
MAJOR-1: the deterministic verifier is not fed pre/post state in the live path,
which both renders verifier outcomes INCONCLUSIVE and makes `finish_live_episode`
unreachable after real step execution. This does not fail the static phase gate,
but it must be resolved (and validated by a real T3 run) before the live pipeline
is declared functional.

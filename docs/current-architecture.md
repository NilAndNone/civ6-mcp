# Codex HL Civ6 Current Architecture

Status: current development mainline for `0.1.0`.

## Source Of Truth

Current development source of truth:

1. `docs/current-architecture.md`
2. `plugin/AGENTS.md`
3. `plugin/commands/*.md`
4. Active strategy assets in `plugin/assets/codex_hl/strategy/catalog.json`
5. Tests as executable contracts

HTML files are derived human-readable views and are never authoritative.
Historical/reference docs cannot define runtime entrypoints.

## Runtime Mainline

Live strict is the only supported executable path:

- `/civ6-observe-live`: interactive MCP-driven JSON-plan operation.
- `/civ6-live-driver`: automated T3/T20/T50 live strict driver.
- `/civ6-runs --runner live`: orchestration wrapper around
  `codex_hl.live.driver`.

The legacy executable path has been removed. `codex_hl.evidence.store` remains
the episode database layer for evidence persistence.

## Live Module Boundaries

- `codex_hl.live.driver`: CLI parsing, objective resolution, episode lifecycle,
  turn loop, plan submission, armed-step execution, and evidence summary.
- `codex_hl.live.objective`: objective and turn semantics for T3/T20/T50.
- `codex_hl.live.planner`: plan-choice helpers that map context rows to
  intended actions.
- `codex_hl.live.policy_profiles`: strategy profile constants and priority
  lists.
- `codex_hl.live.gateway`: live strict mutation gate.
- `codex_hl.live.ledger`: append-only live evidence events.
- `codex_hl.live.plan_store`: JSON-plan and live state persistence.
- `codex_hl.live.evaluation`: read-only evaluation of completed run evidence.

The driver does not own strategy constants. Planner/profile modules own
preference choices; gateway/verifier modules own mutation and postcondition
safety.

## Turn Semantics

The public live driver interface uses:

- `--turn-budget 3|20|50`
- `--objective t3|t20|t50`

The driver captures `start_turn`, then records:

```json
{
  "start_turn": 1,
  "turn_budget": 50,
  "target_turn": 51,
  "objective": "t50"
}
```

`--target-turn` is reserved for recovery/debug and is mutually exclusive with
`--turn-budget`.

## Orchestration

`/civ6-runs --runner live` calls `codex_hl.live.driver` with the selected
turn budget. Removed runner values hard fail before any game mutation.

Runs still respect the Strategy/Validation/Governance gates:

- Review reads existing evidence only.
- Strategy candidate packages are read-only runtime inputs until governance
  explicitly merges them.
- Validation scenarios are passive unless a future command explicitly enables
  replay.
- Governance is audit-only unless an explicit merge flag and all gates pass.

## Human Demo Boundary

Human-demo helpers may capture read-only snapshots, log input/capture events,
write SQLite facts, and summarize factual snapshot counts. They must not carry
rules runners, action-selection policy, or executable heuristic strategy.

## Strategy Assets

Active strategy assets define runtime prompt/playbook/tool policy. Archived
historical lessons may preserve context, but archived assets do not enter the
active runtime snapshot and do not define tool policy.

## Evidence Boundary

`episodes/<episode_id>/episode.db` is the durable episode database layer. JSON,
JSONL, HTML, and save exports are compatibility or presentation artifacts unless
a module explicitly states otherwise.

## Validation Status

`0.1.0` removes the legacy executable path and makes live strict the only
supported execution path. Full Windows Civ6 `test 1` live strict validation must
be run separately before claiming complete replacement proof.

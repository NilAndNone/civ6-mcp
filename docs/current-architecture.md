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

Model-in-loop live strict is the supported executable path for gameplay:

- `/civ6-observe-live`: interactive MCP-driven JSON-plan operation. Each turn
  starts from a fresh context snapshot; the model authors the JSON plan; one
  step is armed; the matching MCP action is executed and verified.
- `/civ6-human-demo-record`: read-only Human Demo capture into SQLite.
- `/civ6-human-demo-contract`: read-only Human Demo reproduction scoring.

Removed runtime surfaces:

- The automated live driver has been removed as a public command, console
  script, and runtime module.
- `/civ6-runs --execute` and `/civ6-runs --runner live` hard fail before any
  connector or game mutation.
- New driver, auto-run, or live-execute commands that bypass
  `/civ6-observe-live` are not allowed.

`codex_hl.evidence.store` remains the episode database layer for evidence
persistence.

## Live Module Boundaries

- `codex_hl.live.gateway`: live strict mutation gate.
- `codex_hl.live.ledger`: append-only live evidence events.
- `codex_hl.live.plan_store`: JSON-plan and live state persistence.
- `codex_hl.live.context`: context helpers for model-in-loop operation.
- `codex_hl.live.human_demo_contract`: read-only Human Demo reproduction
  scoring.
- `codex_hl.live.evaluation`: read-only evaluation of completed run evidence.

Gateway/verifier modules own mutation and postcondition safety. Strategy
learning for Human Demo belongs in recorded demonstration evidence, review,
candidate assets, and model-authored `/civ6-observe-live` plans; not in
automated driver heuristics.

## Turn Semantics

The public model-in-loop execution interface is `/civ6-observe-live`:

- call `get_live_turn_context` for the current turn;
- author a JSON plan from that context;
- submit the plan, arm exactly one mutating step, execute the matching MCP
  action, and repeat until the turn boundary;
- after `end_turn`, capture the next turn context before planning again.

Legacy turn-budget fields may still appear in older evidence:

```json
{
  "start_turn": 1,
  "turn_budget": 50,
  "target_turn": 51,
  "objective": "t50"
}
```

Those fields describe old automated harness runs only. They do not prove Human
Demo strategy quality or model-in-loop correctness.

## Orchestration

`/civ6-runs` is offline-only. It may write plan manifests and read existing
evidence, but `--execute` and `--runner live` hard fail before any connector or
game mutation.

Runs still respect the Strategy/Validation/Governance gates:

- Review reads existing evidence only.
- Strategy candidate packages are read-only runtime inputs until governance
  explicitly merges them.
- Validation scenarios are passive unless a future command explicitly enables
  replay.
- Governance is audit-only unless an explicit merge flag and all gates pass.

## Human Demo Boundary

Human-demo helpers may capture read-only snapshots, log input/capture events,
write SQLite facts, summarize factual snapshot counts, and support contract
scoring. They must not carry rules runners, action-selection policy, or
executable heuristic strategy.

Human Demo strategy is learned through small-grained recorded evidence:

- record human turns with `/civ6-human-demo-record`;
- infer/correct action facts and preserve milestone evidence;
- distill strategy into candidate assets through governed workflows;
- reproduce with `/civ6-observe-live`, where every plan is model-authored from
  the current live context.

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

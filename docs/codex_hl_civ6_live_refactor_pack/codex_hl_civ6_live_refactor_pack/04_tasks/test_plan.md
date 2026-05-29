# Test Plan

## Unit Tests

### Inventory / Registry

```text
tests/test_live_mutation_inventory.py
tests/test_live_action_registry.py
```

- 所有 action tool 分类。
- `unit_action` 子 action 分类。
- L4 boundary actions 分类。
- 新增 mutating tool 未登记失败。

### Gateway

```text
tests/test_live_action_gateway.py
tests/test_live_gateway_shadow_mode.py
```

- shadow mode 允许但标红。
- live strict 无 plan 拒绝。
- L0/L1 不需要 plan。
- L2/L3/L4 policy 正确。

### Plan / State Machine

```text
tests/test_live_plan_schema.py
tests/test_live_state_machine.py
```

- invalid schema reject。
- context_hash mismatch reject。
- duplicate step reject。
- invalid transition reject。

### Verifier

```text
tests/test_live_postcondition_verifier.py
```

- unit moved。
- research/civic set。
- production set。
- purchase gold delta。
- end_turn exactly one turn。
- inconclusive 状态可追踪。

### Store / Ledger

```text
tests/test_live_ledger_store.py
```

- append-only seq。
- export raw live JSONL。
- restore branch lineage。
- crash partial event 可诊断。

### Fragment Phase 4

```text
tests/test_live_fragment_ast.py
tests/test_live_fragment_sandbox.py
tests/test_live_fragment_step_binding.py
```

## Integration Tests

- `/civ6-observe` legacy compatibility。
- `/civ6-observe-live` dry-run plan lifecycle。
- `codex-hl-civ6-runs --runner live` command construction。
- `finish_live_episode` DB export。

## Real Acceptance

### T3 Smoke

目标：证明管道。

PASS：

- strict live episode 跑 3 回合。
- unplanned L2+ mutation = 0。
- all steps verified or explicitly inconclusive。
- no unverified executed step at finish。

### T20 Stability

目标：证明不会频繁卡死。

PASS：

- 完成 T20。
- stuck/recovery 可解释。
- legacy baseline 可对照。

### T50 Quality

目标：证明策略质量趋势。

PASS：

- 至少 3 个 live T50。
- 与 legacy baseline 对照。
- 指标和失败归因完整。

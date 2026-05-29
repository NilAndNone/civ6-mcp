# Target File Map

## 新增目录

```text
plugin/src/codex_hl/live/
  __init__.py
  actions.py
  mutation_levels.py
  inventory.py
  gateway.py
  ledger.py
  state_machine.py
  plan_store.py
  schemas.py
  verifier.py
  exporter.py
  fragment_sandbox.py        # Phase 4 only
```

## 修改文件

### `plugin/src/civ6_connector/server.py`

目标：MCP tool 层变 thin wrapper，mutating action 通过 ActionGateway。

注意：

- `_logged` 不应在 LIVE_STRICT 下偷偷自动恢复。
- `end_turn` 的 hang recovery / WC auto-submit 要拆成 recovery event。
- read-only tool 的 runtime side effect 保留，但标 L1。

### `plugin/src/codex_hl/evidence/observation.py`

目标：旧 runner 变 legacy-baseline，逐步通过 gateway shadow 记录 provenance。

注意：

- Phase 0/1 不改变行为。
- Phase 3 后不再作为默认真实执行入口。
- 不要一开始 archive。

### `plugin/src/codex_hl/evidence/store.py`

目标：增加 live ledger tables 或 live artifact support。

注意：

- episode.db / ledger 是 source of truth。
- raw JSONL 是 export。

### `plugin/src/codex_hl/runs/orchestrator.py`

目标：显式 runner 选择。

```text
--runner live
--runner legacy-baseline
```

`--execute` 无 runner 应 fail。

### Plugin files

```text
plugin/.codex-plugin/plugin.json
plugin/.codex-plugin/.mcp.json
plugin/commands/civ6-observe-live.md
plugin/commands/civ6-observe.md
plugin/commands/civ6-runs.md
plugin/AGENTS.md
```

### Tests

```text
tests/test_live_mutation_inventory.py
tests/test_live_action_registry.py
tests/test_live_action_gateway.py
tests/test_live_gateway_shadow_mode.py
tests/test_live_plan_schema.py
tests/test_live_state_machine.py
tests/test_live_mcp_guard.py
tests/test_live_postcondition_verifier.py
tests/test_live_ledger_store.py
tests/test_orchestrator_runner_selection.py
tests/test_live_fragment_ast.py        # Phase 4
tests/test_live_fragment_sandbox.py    # Phase 4
```

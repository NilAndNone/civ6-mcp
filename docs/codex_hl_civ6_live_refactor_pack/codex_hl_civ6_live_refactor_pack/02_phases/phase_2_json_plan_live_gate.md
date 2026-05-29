# Phase 2 — JSON Plan + Live MCP Step Gate

## TL;DR

新增 live episode 生命周期和 JSON plan；mutating action 必须绑定 plan_id + step_id。仍不启用 Python fragment。


## 目标

- 新增 `/civ6-observe-live` 命令文档和 MCP config。
- 新增 live MCP lifecycle tools：
  - `start_live_episode`
  - `get_live_turn_context`
  - `submit_turn_plan`
  - `arm_live_step`
  - `abort_live_episode`
  - `finish_live_episode`
- mutating tools 支持可选/必选 `episode_id`, `plan_id`, `step_id`, `context_hash`。
- LIVE_STRICT 下 L2+ 必须绑定 active armed step。
- 引入 post-state verifier 初版。

## 禁止

- 不做 `register_live_fragment` / `execute_live_fragment` 主路径。
- 不直接 archive legacy runner。
- 不把 Codex 自评当 outcome。

## 任务

1. 插件入口：

```text
plugin/.codex-plugin/plugin.json  增加 mcpServers: "./.mcp.json"
plugin/.codex-plugin/.mcp.json    新增 civ6_connector server 配置
plugin/commands/civ6-observe-live.md
plugin/commands/civ6-observe.md   改为说明 legacy/deprecated/baseline 与 live 入口
```

2. Live state：

```text
plugin/src/codex_hl/live/state_machine.py
plugin/src/codex_hl/live/plan_store.py
plugin/src/codex_hl/live/schemas.py
```

3. DB schema：新增 live tables 或先以 artifacts + JSONL event 形式兼容，但必须保证 append-only source。
4. 让 `ActionGateway` 在 LIVE_STRICT 校验：
   - active episode
   - plan exists
   - step exists
   - step status == ARMED
   - context_hash match
   - args match
   - mutation level allowed
5. postcondition verifier：先支持基础规则：
   - unit position changed or blocked
   - city production set
   - research/civic selected
   - turn advanced exactly one
   - gold/purchase delta roughly consistent

## 测试

```text
tests/test_live_plan_schema.py
tests/test_live_state_machine.py
tests/test_live_mcp_guard.py
tests/test_live_postcondition_verifier.py
```

测试点：

- invalid plan schema 拒绝。
- stale context_hash 拒绝。
- step 未 armed 拒绝。
- step 重复执行拒绝。
- args mismatch 拒绝。
- postcondition fail 进入 `NEED_RECOVERY_PLAN`。
- `finish_live_episode` 拒绝未验证 executed steps。

## 真实验收

新线程安装插件后运行：

```text
/civ6-observe-live --save-name "test 1" --turns 3 --strict-live
```

T3 PASS 条件：

- 每个 L2+ action 都有关联 plan_id、step_id。
- 每个 step 有 pre-state、post-state、tool result、verifier status。
- 无 plan 的 mutating action 导致 episode FAIL。
- `episode.db` 或 ledger 能导出 live raw files。

T3 只证明管道，不证明策略变强。

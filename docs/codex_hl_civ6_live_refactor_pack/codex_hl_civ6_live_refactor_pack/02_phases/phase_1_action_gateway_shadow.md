# Phase 1 — ActionGateway Shadow Mode

## TL;DR

引入统一 gateway，但先以 shadow/compat 模式运行：记录所有 mutation provenance，不阻断旧流程。


## 目标

- 新增 `ActionGateway`。
- MCP tool 和 legacy runner 都能逐步接入 gateway。
- 默认 `LEGACY_COMPAT` 或 `SHADOW`，不改变旧行为。
- episode ledger 记录 unplanned mutation。

## 任务

1. 新增模块：

```text
plugin/src/codex_hl/live/gateway.py
plugin/src/codex_hl/live/context.py
plugin/src/codex_hl/live/ledger.py
plugin/src/codex_hl/live/verifier.py   # 先放 stub
```

2. 定义 `ActionRequest` / `ActionResult` / `GatewayMode`。
3. 在 `server.py` mutating tools 中选 2–3 个低风险工具先接入 gateway，例如：
   - `set_research`
   - `set_city_production`
   - `unit_action` 部分 action
4. 在 `observation.py` 的关键 mutating calls 外包一层 gateway shadow wrapper，但保持行为一致。
5. `EpisodeStore` 或 live ledger 先写 append-only artifact/event。

## 边界

- 不要求所有工具一次性迁完，但必须有迁移列表。
- live strict mode 可以存在，但不作为默认入口。
- 不新增 fragment executor。

## 测试

```text
tests/test_live_action_gateway.py
tests/test_live_gateway_shadow_mode.py
```

测试点：

- shadow mode 下无 plan 也允许执行，但记录 `unplanned_mutation=true`。
- live strict mode 下 L2+ 无 plan 拒绝。
- L0/L1 不要求 plan。
- gateway result 写 ledger。
- 旧 observation 测试不退化。

## 验收

PASS 条件：

- 至少 3 类 mutating action 通过 gateway。
- 旧 runner 行为不变。
- ledger 能看到 source=`legacy_runner|mcp`。
- 无 plan 的 L2+ action 在 shadow mode 被标红。

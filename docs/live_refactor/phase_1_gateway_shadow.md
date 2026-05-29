# Phase 1 ActionGateway Shadow Mode

Phase 1 只引入统一 mutation gateway 的 shadow/compat 执行层，不新增 live 主入口、不新增 fragment executor、不改变 `/civ6-observe` 和既有 MCP 工具默认行为。MCP 面默认模式来自 `CODEX_HL_CIV6_LIVE_GATEWAY_MODE`，未设置时为 `legacy_compat`；`live_strict` 可用于工程测试，但不是默认入口。

Claude Phase 1 review 后已做 gate hardening：legacy observation runner 不再继承 MCP/global live strict 开关，默认钉死为 shadow/compat；observation 中已知 mutating alias 会归一到 registry canonical tool 写入 ledger；strict 拒绝在 tool call raw evidence 中记为 `success=false` / `rejected=true`；ledger seq 使用进程内 cache + per-ledger lock，避免同进程多实例重复 seq 和每次构造全量回读 JSONL。

## 已新增模块

- `plugin/src/codex_hl/live/gateway.py`
  - 定义 `ActionRequest`、`ActionResult`、`GatewayMode` 和 `ActionGateway`。
  - `LEGACY_COMPAT` / `SHADOW` 下执行并记录；`LIVE_STRICT` 下 L2+ 无 `episode_id + plan_id + step_id` 拒绝。
- `plugin/src/codex_hl/live/context.py`
  - 从环境变量读取 gateway mode、live episode/plan/step/context hash。
  - 为 MCP shadow ledger 和 Observation episode ledger 创建 gateway。
- `plugin/src/codex_hl/live/ledger.py`
  - 写 append-only `raw/live_events.jsonl`。
  - Observation episode 中同步写入 `EpisodeStore` artifact。
- `plugin/src/codex_hl/live/verifier.py`
  - Phase 1 stub verifier，只返回 `INCONCLUSIVE`。
  - 不把 Codex rationale 或工具返回文本当作 outcome authority。

## 已接入执行路径

MCP 侧先接入 3 类清晰 mutating action，工具参数和返回值保持不变：

- `set_research`
  - `server.py` 中实际 `gs.set_research()` / `gs.set_civic()` callable 交给 `ActionGateway.execute()`。
  - 分类来自 `classify_action("set_research", args)`，level 为 L2。
- `set_city_production`
  - `server.py` 中实际 `gs.set_city_production()` callable 交给 gateway。
  - level 为 L3。
- `unit_action`
  - `server.py` 中 unit sub-action callable 交给 gateway。
  - `fortify` / `skip` / `heal` / `alert` / `sleep` 记录为 L2；移动、攻击、建城、改良等记录为 L3。

legacy runner 侧通过 `EpisodeRecorder.tool_call()` 接入 shadow wrapper：

- 对 `ACTION_REGISTRY` 中已登记的 tool name，构造 `source="legacy_runner"` 的 `ActionRequest`。
- 对 observation-only alias 先归一到 canonical tool 再进 gateway，例如：
  - `end_turn_retry` / `end_turn_after_diplomacy` -> `end_turn`
  - `respond_to_trade_decline_for_end_turn` -> `respond_to_trade`
  - `respond_to_diplomacy_for_end_turn` / `respond_to_diplomacy_exit_for_end_turn` -> `respond_to_diplomacy`
- 默认 `legacy_compat` / `shadow` 下无 plan 仍执行，但 L2+ ledger event 标记 `unplanned_mutation=true`。
- 未登记的 legacy calls 保持原行为，列入迁移清单。

Mode 分离：

- MCP gateway 继续读取 `CODEX_HL_CIV6_LIVE_GATEWAY_MODE`，因此 MCP strict 工程测试仍可独立进行。
- legacy observation runner 使用 `CODEX_HL_CIV6_LEGACY_RUNNER_GATEWAY_MODE`（仅 shadow/compat），不继承全局 `CODEX_HL_CIV6_LIVE_GATEWAY_MODE=live_strict`。这是 Phase 2 runner split 前保护 baseline 的临时硬化。
- 单元测试仍可通过显式 `mode=GatewayMode.LIVE_STRICT` 覆盖 legacy gateway factory，测试 strict 拒绝语义。

## Ledger 字段

每次 gateway action 至少写：

- `event_type`: `ACTION_STARTED`、`ACTION_FINISHED`、`ACTION_REJECTED` 或 `ACTION_FAILED`
- `source`: `mcp` / `legacy_runner`
- `tool`
- `args`
- `level` / `mutation_level`
- `plan_id` / `step_id`
- `context_hash`
- `unplanned_mutation`
- `verifier_status`
- `payload.request_id`
- `payload.original_tool`（仅 alias 归一化时写入）

MCP 无 active episode 时写到 `episodes/_live_shadow_mcp/raw/live_events.jsonl`，可用 `CODEX_HL_CIV6_LIVE_LEDGER_ROOT` 改写 episode root。Observation runner 写到当前 episode 的 `raw/live_events.jsonl` 并同步进 `episode.db` artifact。

## 未接入迁移列表

Phase 1 不要求一次迁完，下列仍是后续接管点：

- MCP tools：`purchase_item`、`purchase_tile`、`set_policies`、governor、religion、diplomacy、trade、World Congress、save/load/restart、`run_lua`。
- `server.py` 中 `_logged()` 的 connection-loss auto `restart_and_load` 仍是 legacy recovery 行为；strict live 主路径不得复用为透明恢复。
- `end_turn()` 内 hang recovery、World Congress repeated blocker auto-submit 仍是 legacy 行为；Phase 2/3 必须拆成 explicit recovery/turn-completion plan step。
- Observation runner 直接边界调用：load/reconnect/save/process lifecycle 和 raw Lua transport 仍需更细粒度 shadow event。

## 遗留风险

- Phase 1 strict 只验证 L2+ 是否有 `episode_id + plan_id + step_id`，尚未实现 step `ARMED`、args matcher、context hash stale check 或 duplicate step check。
- Verifier 是工程占位，所有执行结果为 `INCONCLUSIVE`；不能用于判定策略成功或高收益。
- MCP shadow ledger 默认写本地 `episodes/_live_shadow_mcp` 运行产物，提交时仍应排除 `episodes/`。
- legacy runner 中 registry 精确命名 action 和已知 mutating alias 已有 runtime shadow；load/reconnect/save/process lifecycle 和 raw Lua transport 仍依赖 Phase 2/3 接管。

## Phase 2 接管点

- 引入 JSON plan / plan store / step lifecycle。
- `LIVE_STRICT` 从“有 plan/step 即可”升级为校验 active episode、step status、args matcher、context hash 和 duplicate execution。
- L4 `end_turn`、save/load/restart、World Congress submit 进入 explicit turn/recovery plan。
- verifier 从 stub 升级为独立 postcondition/objective metric 验证。

## Phase 2-entry gate 状态

当前状态可以进入 Phase 2 设计/实现，但不能宣称 Phase 2 完成：

- 已处理 Phase 1 review 要求的 baseline 保护、alias ledger 覆盖、strict 拒绝 evidence 语义和 ledger seq 简单完整性。
- 未实现 Phase 2 正式 guard：step `ARMED`、args matcher、stale context、duplicate/cross-turn step 拒绝。
- 未落真实 `live_events/live_plans/live_steps/live_checkpoints/live_branches` DB 表；当前仍是 Phase 1 JSONL/export artifact 形态。
- 未新增 `/civ6-observe-live`、MCP live episode tools、完整 plan store/state machine，也未启用 fragment。
- 透明 L4 recovery 仍必须在 Phase 2/3 被拆成显式 recovery/turn-completion plan step 后，才能把 strict 当作真实 live 入口。

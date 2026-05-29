# Phase 1 to Phase 2 Gate

本文记录 Claude Phase 1 review 后的 gate-readiness 状态。它不是 Phase 2 设计文档，也不声明 Phase 2 已完成。

## 已处理的 required fixes

- Legacy observation runner 与 MCP gateway mode 已解耦。`CODEX_HL_CIV6_LIVE_GATEWAY_MODE=live_strict` 只影响 MCP/global live gateway，不会让 legacy baseline observation 因缺少 plan/step 而拒绝 L2+ action。
- Observation alias mutation 已进入 canonical gateway ledger 覆盖。`end_turn_retry`、`end_turn_after_diplomacy`、`respond_to_trade_decline_for_end_turn`、`respond_to_diplomacy_for_end_turn`、`respond_to_diplomacy_exit_for_end_turn` 会按 `end_turn` / `respond_to_trade` / `respond_to_diplomacy` 记录。
- Strict 拒绝时 raw tool call evidence 不再记 `success=true`。拒绝会返回 error text，同时在 `raw/tool_calls.jsonl` 记 `success=false`、`rejected=true`、`error.type=GatewayRejected`。
- Ledger seq 已加入进程内 cache 和 per-ledger lock。同一进程内反复创建 `EpisodeLedger` 不再每次全量回读 JSONL，也不会因两个实例先后 append 写出重复 `seq`。

## 仍属于 Phase 2 正式实现的项目

- 真正的 strict 状态机 guard：step `ARMED`、args matcher、context hash stale check、duplicate/cross-turn step 拒绝。
- 真实 source-of-truth DB schema：`live_events`、`live_plans`、`live_steps`、`live_checkpoints`、`live_branches`。当前 Phase 1 仍只提供轻量 append-only ledger/export artifact。
- 显式 L4 recovery / turn-completion plan step：`end_turn` hang recovery、World Congress submit、restart/load/save 等仍不能作为透明 strict live 主路径。
- Live episode API surface：不新增 `/civ6-observe-live`，不新增 MCP live episode tools，不新增完整 `plan_store/state_machine`，不启用 fragment。
- Verifier 独立结果判定：当前 stub 仍只写 `INCONCLUSIVE`，不能作为策略成功或高收益 authority。

## Gate 结论

仓库现在满足“进入 Phase 2”的前置条件：Phase 1 shadow gateway 不再误伤 legacy baseline，已知 observation mutating alias 不再静默绕过 gateway，strict 拒绝 evidence 语义一致，ledger seq 有基本同进程完整性。

这只表示可以开始 Phase 2 正式实现。Phase 2 完成仍必须交付计划提交、step lifecycle、strict guard、DB source of truth、显式 recovery plan 和对应测试，并再次通过 Claude gate review。

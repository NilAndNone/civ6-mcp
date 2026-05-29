# Target Architecture — Live Codex MCP Agent

## TL;DR

目标架构不是“Codex 写 Python 并让 Python 玩游戏”，而是：Codex 负责**生成结构化意图和选择理由**；工程系统负责**权限、执行、状态验证、证据、恢复边界**。

## 目标数据流

```text
Codex session
  |
  | read-only MCP tools
  v
Live Turn Context
  |
  | submit JSON plan
  v
LivePlanStore / EpisodeLedger
  |
  | execute one step at a time
  v
ActionGateway / MutationGateway
  |
  | call allowed GameState method
  v
Civ6 / FireTuner
  |
  | capture post-state + verifier result
  v
EpisodeLedger / episode.db / exported reports
```

## 分层职责

### 1. MCP Surface

- 暴露 read-only context tools。
- 暴露 live episode lifecycle tools。
- 暴露 mutating tools，但 mutating tools 只是 thin wrapper。
- 不允许 MCP tool 自己决定是否能改游戏；必须交给 ActionGateway。

### 2. ActionGateway

唯一允许改真实游戏状态的入口。

职责：

- 分类 action：L0/L1/L2/L3/L4/L5。
- 在 live strict mode 下校验 active episode、plan、step、context hash、args matcher、step status。
- 执行 pre-checkpoint policy。
- 调用底层 `GameState` 或 lifecycle function。
- 捕获 result/error。
- 触发 post-state capture 和 verifier。
- 追加 ledger event。

### 3. LivePlanStore

- 保存 JSON plan。
- 管理 plan version。
- 防止 stale context。
- 维护 step 状态。
- 拒绝重复执行、越权执行、跨回合执行。

### 4. EpisodeLedger

append-only source of truth。

必须记录：

- episode lifecycle event
- context snapshot hash
- plan submitted
- step armed/executed/verified
- tool call result
- pre/post state hash
- checkpoint/restore lineage
- abort/finish status

### 5. Verifier

工程层独立验证，不信任 Codex 自评。

Verifier 输入：

- step postconditions
- tool result
- pre-state snapshot
- post-state snapshot
- known game-state parser

Verifier 输出：

- `PASS`
- `FAIL`
- `INCONCLUSIVE`
- evidence refs
- objective delta

### 6. Exporter / Reporter

- `episode.db` / ledger 为源。
- raw JSONL、HTML、Markdown、report_pack 为导出视图。
- 兼容旧工具读取，但不要让导出文件反向成为权威。

## 非目标

Phase 0–3 不做：

- mutating Python fragment 主路径；
- 自动 strategy asset merge；
- 无人类 gate 的自学习；
- 直接删除 legacy runner；
- 用 3 回合结果证明策略提升；
- 让 Codex 自评高收益。

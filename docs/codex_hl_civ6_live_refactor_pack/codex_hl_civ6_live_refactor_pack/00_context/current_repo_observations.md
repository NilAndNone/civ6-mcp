# 当前仓库观察与重构动机

## 关键观察

1. `plugin/AGENTS.md` 当前把 `/civ6-observe` 作为基础观测入口，把 `/civ6-runs` 标为待验自动编排入口。插件说明层面仍是 observation/review/strategy/governance 的分层入口。
2. `plugin/.codex-plugin/plugin.json` 当前有 `skills: "./skills/"`，但未声明 `mcpServers`。Live MCP 作为插件正式入口，需要新增 `.mcp.json` 和 plugin.json 配置。
3. `plugin/src/civ6_connector/server.py` 是 FastMCP server，MCP tool 层有大量 read 和 action tools。
4. `server.py` 的 `_logged` 同时负责执行、日志、错误捕获、spatial、heartbeat，并包含连接失败后的自动 restart/load recovery。这会和 live strict plan provenance 冲突。
5. `end_turn` 内部有 hang recovery、World Congress auto-submit 等透明 mutating recovery。live strict mode 下不能继续透明执行。
6. `plugin/src/codex_hl/evidence/observation.py` 名义上是 observation-only，但内部有大量 hard-coded priority、profile 和直接 `GameState` 调用，实质是 rules-heavy autoplayer。
7. `plugin/src/codex_hl/runs/orchestrator.py` 通过 `codex_hl.evidence.observation` 启动旧 observation runner。不能第一步直接 archive，否则 runs/review/strategy/gov 闭环会被掀翻。
8. `plugin/src/codex_hl/evidence/store.py` 已经有 SQLite-backed `episode.db`，但 schema 目前没有 live plan / live step / postcondition / restore branch lineage 的一等结构。

## 重构动机

当前问题不是简单“缺少一个 live MCP 入口”，而是：

```text
策略选择逻辑、执行逻辑、证据记录、恢复逻辑、报告逻辑混在一起；
动作来源不统一；
MCP guard 无法覆盖 Python runner 直接 GameState 调用；
透明 recovery 会破坏 plan provenance；
Observation 名称与 autoplayer 行为不一致。
```

因此目标是分层重写：

```text
Decision/Plan 层：Codex 产生结构化 plan。
Execution 层：ActionGateway 严格校验并执行 step。
Verification 层：工程层独立验证 postcondition。
Evidence 层：append-only ledger + episode.db。
Review 层：Claude Code / offline review 检查架构遵循与策略质量。
```

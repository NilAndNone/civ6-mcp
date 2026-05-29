# Codex HL Civ6 Live Agent 重构执行包

## TL;DR

本包不是“写个新入口”的计划，而是一次分阶段架构重写：先建立统一 mutation gateway 和 episode ledger，再引入 JSON plan 与 step-level guard，最后才考虑 Python fragment。核心目标是：**所有真实游戏状态修改必须有可验证来源、可追踪 step、可复查状态 diff、可恢复 checkpoint lineage**。

## 适用仓库

- Repo: `https://github.com/NilAndNone/codex-hl-civ6/tree/windows-test`
- 建议工作分支: `codex/live-codex-mcp-agent`
- 编码执行: Codex
- 架构/代码审查: Claude Code
- 编排/分阶段推进: Hermes

## 必须遵守的总原则

1. **ActionGateway 是唯一 game-state mutation 入口。** 不能只在 MCP tool 层加 guard；legacy runner、MCP tool、未来 fragment executor 都必须通过同一层。
2. **先 JSON plan，后 Python fragment。** Phase 0–3 不允许把 mutating Python fragment 作为主路径。
3. **legacy rules runner 先保留为 baseline/deprecated，不要直接 archive。** 没有 baseline，就无法证明 live agent 更好。
4. **episode.db / live ledger 是 source of truth；raw 文件树是导出视图。** 不要让 raw JSONL 和 DB 双方争夺权威。
5. **Codex 自评不能作为 outcome authority。** Codex 可以写 rationale，成功/失败/高收益必须由 verifier、objective metrics 和 cross-episode review 判定。
6. **live strict mode 禁止透明自动恢复。** hang/restart/load/submit congress 等 mutating recovery 必须显式进入 recovery plan。
7. **rollback 叫 restore，不叫事务。** Civ6 不是数据库，restore 必须记录 branch lineage。

## 包结构

```text
00_context/                  当前仓库观察与重构动机
01_architecture/             目标架构、gateway、state machine、ledger、schema
02_phases/                   Phase 0–5 分阶段实施计划
03_agent_prompts/            Hermes/Codex/Claude Code 指令
04_tasks/                    任务清单、验收矩阵、测试计划、风险表
05_repo_change_plan/         目标文件图、API contract、迁移与弃用计划
06_templates/                plan/event/report/PR 模板
HERMES_START_HERE.md         Hermes 第一条指令
```

## 执行方式

1. Hermes 读取 `HERMES_START_HERE.md`。
2. Codex 每次只执行一个 phase，不允许跨 phase 偷跑。
3. 每个 phase 后 Claude Code 按 `03_agent_prompts/claude_arch_review_prompt.md` 做架构遵循度 review。
4. 未通过 review 不进入下一 phase。
5. 真实 Civ6 验收只在 Phase 2 之后开始；T3 只能证明管道，T20/T50 才能证明策略能力。

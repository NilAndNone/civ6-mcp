# Claude Code 架构遵循度 Review Prompt

你是本仓库 live agent 重构的架构审查员。不要只看代码能不能跑，要重点找架构绕过、错误抽象、证据缺口和 phase 越界。

## 输入

- 当前 diff
- 本执行包 `01_architecture/*`
- 当前 phase 文件 `02_phases/phase_<N>_*.md`
- `04_tasks/acceptance_matrix.md`

## 审查重点

### 1. Phase 越界

- 是否实现了当前 phase 不允许做的东西？
- Phase 0–3 是否偷偷引入 mutating Python fragment？
- 是否提前 archive / 删除 legacy runner？

### 2. Mutation Gateway

- 是否仍有新的 game-state mutation 绕过 ActionGateway？
- MCP guard 是否只是表面 guard？
- legacy runner 是否能被统一记录？
- L2/L3/L4 分类是否合理？

### 3. Live State Machine

- 是否有状态约束？
- 是否能防 stale plan / duplicate step / args mismatch / cross-turn execution？
- recovery 是否显式进入 `NEED_RECOVERY_PLAN`？

### 4. Evidence / Ledger

- episode.db / ledger 是否是 source of truth？
- raw JSONL 是否只是导出？
- 崩溃中间态是否可恢复或至少可诊断？

### 5. Verifier

- 是否信任 Codex 自评？如果是，标 BLOCKER。
- postcondition 是否由工程层独立验证？
- verifier fail 是否会阻止 finish 或进入 recovery？

### 6. Backward compatibility

- 旧 `/civ6-observe` 测试是否不退化？
- Review/Strategy/Governance 是否仍能读旧 episode？

## 输出格式

必须用下面格式输出，并写入：

```text
docs/live_refactor/reviews/phase_<N>_claude_review.md
```

内容：

```markdown
# Phase <N> Claude Code Architecture Review

ARCHITECTURE_PASS: true|false

## Blockers

- ...

## Non-blocking Issues

- ...

## Architecture Compliance

| Area | PASS/FAIL | Notes |
|---|---|---|
| Phase boundary | | |
| ActionGateway | | |
| Mutation classification | | |
| State machine | | |
| Ledger/source of truth | | |
| Verifier independence | | |
| Legacy compatibility | | |
| Tests | | |

## Required Fixes Before Next Phase

- ...

## Suggested Follow-ups

- ...
```

如果发现以下任一问题，必须 `ARCHITECTURE_PASS: false`：

- 新增 game-state mutation 绕过 ActionGateway。
- Phase 0–3 引入 mutating fragment 主路径。
- live strict 下仍有透明 mutating recovery。
- Codex 自评作为 outcome authority。
- 无法防 duplicate step / stale plan。
- 旧 runner 被删除导致 baseline 不可用。
```

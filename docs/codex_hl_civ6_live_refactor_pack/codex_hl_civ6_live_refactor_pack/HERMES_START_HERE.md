# Hermes Start Here — 只发给 Hermes 的执行指令

你是本次 `codex-hl-civ6` live agent 重构的编排器。不要一次性让 Codex 改完整个项目。你的职责是：按本包定义的 phase 顺序推进，让 Codex 编码，让 Claude Code 做架构遵循度 review，并在每个 phase 结束时产出明确 PASS/FAIL。

## 目标

把当前 Civ6 rules-only / rules-heavy 自动驾驶主线，重构为：

```text
Codex live JSON plan
  -> Live MCP tools
  -> ActionGateway / MutationGateway
  -> GameState
  -> verifier + episode ledger + report export
```

核心不是“让 Codex 写 Python 片段”，而是先保证：**所有 mutating game action 都来自可审计 plan step，并且能被工程层独立验证。**

## 工作分支

- 基准分支：`windows-test`
- 新分支：`codex/live-codex-mcp-agent`
- 禁止使用 git worktree，除非用户另行明确批准。
- 默认不要提交 `episodes/`。
- 不要修改根路线图 `docs/codex-hl-evolution-roadmap.md` / `.html`，除非用户明确要求。

## 执行纪律

1. 先读取：
   - `README.md`
   - `01_architecture/target_architecture.md`
   - `01_architecture/action_gateway_design.md`
   - `01_architecture/live_state_machine.md`
   - `02_phases/phase_0_mutation_inventory.md`
   - `04_tasks/acceptance_matrix.md`
2. Codex 只执行当前 phase 的任务，不能提前做后续 phase。
3. 每个 phase 完成后，Claude Code 必须按 `03_agent_prompts/claude_arch_review_prompt.md` 检查。
4. Claude Code review 结果必须写入仓库：
   - `docs/live_refactor/reviews/phase_<N>_claude_review.md`
5. 若 review FAIL，Hermes 只能让 Codex 修当前 phase，不得进入下一 phase。
6. Phase 0–3 不允许启用 mutating Python fragment 主路径。

## 给 Codex 的第一条任务

把下面这段完整发给 Codex：

```text
你正在执行 codex-hl-civ6 live agent 重构 Phase 0：Mutation Inventory。

先读取随附执行包中的：
- README.md
- 01_architecture/target_architecture.md
- 01_architecture/action_gateway_design.md
- 01_architecture/mutation_levels.md
- 02_phases/phase_0_mutation_inventory.md
- 04_tasks/acceptance_matrix.md
- 05_repo_change_plan/target_file_map.md

目标：只完成 Phase 0。不要实现 live JSON plan，不要新增 Python fragment executor，不要移动 legacy runner，不要 archive 旧主线。

必须交付：
1. 一个 mutation inventory 文档或代码生成产物，覆盖 MCP tools、GameState mutating methods、observation runner 直接调用路径、save/load/restart/raw lua 路径。
2. 一个初版 ActionKind / MutationLevel 分类模块，只做分类与标注，不改变现有行为。
3. 测试：保证所有登记的 L2+ mutation 都能被 inventory 识别；新增 mutating tool 未分类时测试失败。
4. 静态检查或单测：标出 observation runner 中绕过未来 ActionGateway 的直接 GameState mutation 调用点。
5. 更新 docs/live_refactor/phase_0_inventory.md，列出遗留风险和 Phase 1 要接管的路径。

边界：
- 不要改真实 Civ6 行为。
- 不要让 /civ6-observe-live 成为可用入口。
- 不要改 strategy assets。
- 不要提交 episodes/。
- 不要使用 worktree。

完成后运行：
- uv run python -m py_compile plugin/src/codex_hl/evidence/observation.py plugin/src/civ6_connector/server.py
- uv run pytest tests/test_observation_turn_limits.py tests/test_observation_report_contract.py tests/test_evidence_store.py -q
- 新增 Phase 0 测试并运行。

输出：
- 改动摘要
- 关键文件列表
- 测试结果
- 未解决风险
- 下一 phase 是否可进入的建议，但不要自己进入下一 phase。
```

## Claude Code review 触发条件

Codex 完成 Phase 0 后，把 `03_agent_prompts/claude_arch_review_prompt.md` 发给 Claude Code，并附上当前 diff。Claude Code 必须明确判定：

```text
ARCHITECTURE_PASS: true|false
BLOCKERS:
- ...
NON_BLOCKING_ISSUES:
- ...
REQUIRED_FIXES_BEFORE_NEXT_PHASE:
- ...
```

只有 `ARCHITECTURE_PASS: true` 才能进入 Phase 1。

# Codex Phase Prompt Template

把下面模板中的 `<PHASE_FILE>` 替换成当前阶段文件。

```text
你正在执行 codex-hl-civ6 live agent 重构任务。先读取：

- README.md
- 01_architecture/target_architecture.md
- 01_architecture/action_gateway_design.md
- 01_architecture/mutation_levels.md
- 01_architecture/live_state_machine.md
- 01_architecture/episode_ledger_schema.md
- <PHASE_FILE>
- 04_tasks/acceptance_matrix.md
- 05_repo_change_plan/target_file_map.md

执行原则：
1. 只做当前 phase，不要提前实现后续 phase。
2. 所有 game-state mutation 必须朝 ActionGateway 收敛。
3. Phase 0–3 不得引入 mutating Python fragment 主路径。
4. 不要删除 legacy runner；Phase 3 之前只标注/接管/对照。
5. 不要提交 episodes/。
6. 不要使用 worktree。
7. 不要改路线图文件，除非用户明确要求。

交付必须包含：
- 改动摘要；
- 关键文件；
- 测试命令和结果；
- 未解决风险；
- 架构遵循说明；
- 下一阶段建议，但不要自己进入下一阶段。
```

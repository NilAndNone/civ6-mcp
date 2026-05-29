请读取我发你的 zip 包，并按 `HERMES_START_HERE.md` 执行。你是本次 `codex-hl-civ6` live agent 重构的编排器：Codex 负责编码，Claude Code 负责架构遵循度 review，你负责按 phase gate 推进。

关键约束：

1. 从 `windows-test` 创建 `codex/live-codex-mcp-agent` 分支。
2. 禁止使用 worktree。
3. 不要一次性重写全项目；必须 Phase 0 → review → Phase 1 → review 逐步推进。
4. Phase 0–3 不允许引入 mutating Python fragment 主路径。
5. 不要直接 archive legacy runner；先保留为 baseline/deprecated。
6. 所有真实 game-state mutation 必须朝 ActionGateway 收敛，不能只在 MCP tool 层加 guard。
7. live strict mode 下透明 restart/load/submit congress 等 recovery 不能偷偷执行，必须进入 explicit recovery plan。
8. Codex 自评不能作为 outcome authority；必须由 verifier/objective metrics 判断。
9. 不提交 `episodes/`，不改路线图文件，除非我明确批准。

先只执行 Phase 0：Mutation Inventory。把 `HERMES_START_HERE.md` 里“给 Codex 的第一条任务”完整发给 Codex。Codex 完成后，用 `03_agent_prompts/claude_arch_review_prompt.md` 让 Claude Code 做 review。Claude Code 没有 `ARCHITECTURE_PASS: true` 前，不进入 Phase 1。

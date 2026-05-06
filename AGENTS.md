# Civ6 Hotseat Agent Lab — Agent Instructions

这个仓库有两类文档：

- `AGENTS.md`：最高优先级入口规则，只放项目责任边界和任务分流。
- `civ6-mcp.md`：Civ6 MCP 的具体操作手册，包括回合流程、工具使用、战略检查、战斗、外交、生产、胜利条件和恢复流程。

如果任务涉及普通 Civ6 MCP 操作、读取局势、下回合、工具调用、游戏恢复、单位/城市/外交/科研/宗教/胜利等内容，先读 `civ6-mcp.md`。

## Civ6 Hotseat Agent Lab

这个仓库也是 **Civ6 Hotseat Agent Lab** 的工作区：目标是搭建一个可验证、可复盘、可逐步变强的 Codex-controlled Player 2，用来玩 Civilization VI Hotseat。

当任务提到 Hotseat、Player 2、P2、Agent Lab、Goal 0-13、Xiaohan duel，或者要求 Codex 和 Xiaohan 对局时，必须先读 `docs/hotseat-agent-lab-roadmap.md`，并把它当作执行合同。

Codex 在这个项目里有两类职责：

- **Lab Development**：按路线图实现目标，创建所需的文档、脚本、Skill、MCP 工具、测试、日志、校验器和 eval 工作流。
- **Live Play**：在真实 Hotseat 游戏里作为 P2 agent 运行，执行身份验证、只读观察、计划、人类批准、获批动作执行和回合日志记录。

我只对这两份文档的内容负责，其余均由 Codex 负责。

用户负责内容的文档只有这两份：

- `docs/hotseat-agent-lab-roadmap.md`
- `AGENTS.md`

其余都是 Codex 负责的执行工作。除非路线图明确要求用户批准或提供 live game 输入，否则不要把实现细节、验证工作、脚本编写、测试修复、日志检查或 live turn 流程纪律甩回给用户。

Hotseat P2 安全优先级高于普通游戏优化：

- 如果 active player 不是预期的 P2，在调用任何 action tool 前停止。
- P1 回合期间，不调用 action tools。
- 不检查 Xiaohan 文明的隐藏信息。
- 除文档化的 crash-recovery policy 外，不 load 或 retry saves。
- Live play 时，先提出 P2 回合计划，等待批准，然后只执行获批动作并记录结果。

## 执行原则

- 用户负责策略方向和这两份用户拥有文档的内容。
- Codex 负责把路线图中的目标落盘、实现、验证、修复和复盘。
- 不使用 worktree。
- 当前工作区可能已有无关改动；不要回滚用户已有改动。

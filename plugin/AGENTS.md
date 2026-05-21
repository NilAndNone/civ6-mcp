# Codex HL Civ6 插件使用说明

这个文件给安装插件后的 Codex 使用。它不是本仓库的开发说明。

## 默认模式

- 默认执行 Phase 1 观测。
- 除非用户明确指定其他存档，否则使用真实 `test 1` 单人存档。
- 先跑 3-5 回合，生成中文人工报告，然后等待人工验收。
- 验收前不要继续到 T50；验收通过后，T50 仍然只做完整观测，不进入 Phase 2。
- 只有用户明确要求 Phase 2 时，才对已有 episode 执行离线标注；Phase 2 不启动 Civ6，也不推进回合。

## 边界

- Phase 1 只记录发生了什么，不评价策略好坏。
- 不做失败归因、候选策略生成、Replay Arena、自动资产合并、回滚或学习循环。
- 记忆只能当低可信背景。当前 Civ6 状态必须来自连接器检查。

## 命令

- `/civ6-phase1-observe`：跑 Phase 1 观测；默认短跑，验收后可跑单个 episode 的 T50 完整观测。
- `/civ6-phase1-report`：基于已有 episode 重新生成报告，不推进游戏。
- `/civ6-phase2-label`：对已有 Phase 1 episode 生成候选失败、人工确认后生成正式 failure 和被动 regression seed。
- `/civ6-debug`：做受控连接测试和排障。

## Phase 2 v1 离线标注

Phase 2 v1 只读已有 Phase 1 证据，所有输出都写在 `episodes/<episode_id>/phase2/`。

默认运行只生成 `candidates.jsonl` 和 `phase2_review.html`，不得写 `failures.jsonl` 或 `regression_seeds.jsonl`。正式写入必须经过人工 `confirmation.jsonl` 和显式 `--apply-confirmation`。

短跑 planning failure 必须标明只适用于 `T10/T20 local_episode_fragment`，不是长期战略结论，也不是资产修改证据。

## 证据要求

一次合格的 Phase 1 短跑或 T50 完整观测必须产出：

- 工具和连接器调用日志。
- 每回合状态快照。
- 决策记录。
- 存档到回合、存档到决策的关联。
- 中文人工 HTML 报告。
- 面向下一个 Agent 的快速接手报告。

中文人工报告是给人看的主入口。原始证据放在审计文件里。

## T50 完整观测

只有人工接受短跑报告后，才运行 T50。T50 必须从真实 `test 1` 起点推进 50 回合，保留同一套四类证据，并在 T50 结束后生成报告并停止。

不要把多个短跑 episode 拼接成 T50；如果 runner 暂时不能接受 `--turns 50`，先修 runner，再重新跑单个完整 episode。

# Observation 观测流程

Observation 负责记录真实 Civ6 对局发生了什么。它只做观测和报告，不做失败
归因，不生成策略改进，不进入自动学习。

## 输入

- 真实 Civilization VI 单人存档，默认是 `test 1`。
- 目标回合数，短跑默认 3 回合，T50 使用 50 回合。
- Strategy active assets，用于记录本次运行使用的规则版本。

## 处理过程

入口命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --save-name "test 1" --turns 3
```

处理流程：

1. 检查仓库、资产、连接和 Civ6 状态。
2. 加载真实存档。
3. 每回合采集游戏状态。
4. 记录工具调用、Lua/MCP 事件、关键决策和存档关联。
5. 生成面向人的中文报告和面向 Agent 的交接报告。
6. 到达目标回合后停止，等待人工审阅。

T50 仍然属于 Observation：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --save-name "test 1" --turns 50
```

T50 不是策略改进阶段，只是更长的观测 episode。

## 输出

一个 episode 写在：

```text
episodes/<episode_id>/
```

权威存储：

- `episode.db`

`episode.db` 是该局的本地 SQLite 结构化证据库。JSON、JSONL、HTML、MD
和 `.Civ6Save` 存档都会写入 DB；下面的文件树是从 DB 导出的兼容视图，
用于人工查看和旧脚本读取。

关键产物：

- `header.json`
- `raw/tool_calls.jsonl`
- `raw/mcp.jsonl`
- `raw/civ6_states/*.json`
- `raw/saves/save_index.jsonl`
- `derived/decision_atoms.jsonl`
- `derived/report_pack.json`
- `outcome/observation_report.html`
- `outcome/agent_report.md`
- `outcome/agent_audit_report.html`
- `assets_snapshot/active_assets.json`

文件名里可能仍带 `short_run`，验收时以 `report_pack.json` 里的实际回合数为准。

重建老 episode 的 DB：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --rebuild-db <episode_id>
```

这个命令只从已有文件树导入 `episode.db`，不启动 Civ6、不加载存档、不推进回合。

## 验收看什么

一次 observation episode 可验收，必须能回答：

- 实际跑了多少回合。
- 每回合看到了什么状态。
- 做了哪些关键决策。
- 每个决策依据是什么。
- 哪些工具调用成功或失败。
- 存档和 episode 如何关联。
- 中文报告是否能让人不用看原始 JSON 也理解这一局。

本地检查：

```bash
uv run pytest tests/test_observation_report_contract.py tests/test_observation_turn_limits.py -q
```

完整本地检查见 `docs/v0.0.1-release.md`。

## 最容易错的地方

- 把 Observation 报告写成策略好坏判断。Observation 只能记录事实。
- 短跑结束后自动进入 T50。短跑后必须停下来等人工审阅。
- T50 后继续进入 Review 或 T51+。T50 后同样必须停在报告。
- 用多个短跑拼成 T50。T50 必须是一个完整 episode。
- 把缺失证据藏起来。缺口必须写进报告。

## 提交边界

`episodes/` 是本地运行产物，默认不要提交。只有用户明确点名某个 episode
时才考虑纳入版本控制。

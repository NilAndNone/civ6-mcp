# Codex HL Phase 1 观测流程

这个文档是 `codex-hl-civ6` 插件内 Phase 1 流程的开发和验收契约。插件安装后的使用说明在 `plugin/AGENTS.md` 和 `plugin/skills/civ6-phase1-observation/SKILL.md`。

Phase 1 只做观测：记录一局真实 Civ6 发生了什么，产出可审阅证据。默认先跑短验收；短验收被人工接受后，同一套记录契约必须能够继续完整记录到 T50。

## 插件会产出什么

入口命令 `codex-hl-civ6-phase1-observe` 会加载真实 `test 1` 单人存档，并在 `episodes/<episode_id>/` 下写入一个 episode。默认流程先跑 3-5 回合短验收；人工接受短验收后，T50 完整观测必须从同一存档起点推进 50 回合，并保留每回合证据。

每个 episode 至少包含：

- `header.json`
- `raw/tool_calls.jsonl`
- `raw/mcp.jsonl`
- `raw/civ6_states/*.json`
- `raw/saves/save_index.jsonl` 和对应的 `.Civ6Save` 检查点存档
- `derived/decision_atoms.jsonl`
- `derived/report_pack.json`
- `outcome/phase1_short_run_report.draft.html`
- `outcome/phase1_short_run_report.html`
- `outcome/phase1_agent_report.md`
- `outcome/phase1_agent_audit_report.html`

中文人工报告必须用自然语言解释决策流程，不能变成 JSON 堆叠或审计表格。

## 中文人工 HTML 契约

人类审阅入口固定是：

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
```

报告必须保持这个章节顺序：

1. `Codex HL Phase 1 人类验收报告`
2. `验收结论`
3. `我实际观测到的局面变化`，其中包含 `起点 T...` 和 `终点 T...`
4. `回合叙事`
5. `重点：决策流程`
6. `证据边界和你需要判断的点`
7. `存档和决策关联`
8. `缺口清单`
9. `面向 Agent 的报告`，并链接到 `phase1_agent_report.md` 和 `phase1_agent_audit_report.html`

报告还必须满足当前可读性底线：包含 `先读这份报告的顺序`、`快速定位`、`关键数字变化`、卡片式回合叙事、结构化决策卡片、紧凑存档行，以及区分 `快速接手` 和 `完整审计` 的两个入口。

每条决策必须展示这些中文标签：

- `当时看到的问题：`
- `候选动作：`
- `我选择了：`
- `为什么这样选：`
- `为什么没选其他动作：`
- `执行后结果：`
- `对 review 的意义：`

原始证据放在 `phase1_agent_audit_report.html`、`derived/report_pack.json`、`raw/*.jsonl`、`raw/civ6_states/*.json` 和 `derived/decision_atoms.jsonl`。

报告契约夹具在 `plugin/fixtures/phase1_human_report_contract/`。

## 新会话执行流程

在 Windows 的插件开发目录开始：

```powershell
Set-Location O:\civ6\codex-hl-civ6
& 'C:\Program Files\Git\cmd\git.exe' status --short --branch --untracked-files=all
```

先读插件技能：

```text
plugin/skills/civ6-phase1-observation/SKILL.md
```

然后跑一次短验收：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
```

这个流程不要单独启动 `civ6-connector` 服务。运行器会直接连接 FireTuner，并默认停止本仓库残留的旧连接器进程。

命令会打印 `episode_id` 和报告路径。打开：

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
```

人工验收这份报告前，不要继续到 T50。

## T50 完整观测

只有人工明确接受短验收报告后，才进入 T50 完整观测。T50 不是新的策略阶段，仍然属于 Phase 1 Observation Only：继续记录事实，不做失败归因、Replay Arena、候选策略优化、自动学习、晋级或淘汰判断。

T50 运行必须满足这些约束：

- 从真实 `test 1` 单人存档起点开始，推进 50 个真实回合；报告中的 `actual_turns` 必须是 `50`，`final_turn` 必须等于 `start_turn + 50`。
- 生成一个完整 episode，不要把 T50 拆成多个互不关联的短跑 episode 充数。
- 每个回合都必须有状态快照；每个关键决策、阻塞处理、结束回合和检查点存档都必须有可追溯记录。
- 继续使用 `codex-hl-civ6-phase1-observe`，不要单独启动 `civ6-connector` 服务。
- 到 T50 后必须生成报告并停止；不要继续到 T51+，除非用户明确开启下一阶段。

人工接受短验收后，目标命令是：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 50
```

如果当前实现仍拒绝 `--turns 50`，这不是人工操作阻塞，而是 Phase 1 runner 的实现缺口。应先修改 runner，让 T50 使用同一套 episode、报告和证据 schema 完整落盘；不要用 5 个 10 回合 episode 或手工拼报告绕过。

T50 报告仍然使用同一套产物路径：

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
episodes/<episode_id>/outcome/phase1_agent_report.md
episodes/<episode_id>/outcome/phase1_agent_audit_report.html
```

即使文件名里仍有 `short_run`，验收时以 `derived/report_pack.json` 的 `run.actual_turns = 50` 和报告正文中的 T50 叙事为准。后续可以单独重命名产物，但不能因此打断本次 T50 记录。

## 只重建报告

已有 episode、且不应该推进 Civ6 时，使用报告重建模式：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

报告重建模式不能启动游戏、加载存档或推进回合。

## 验收标准

一次短跑或 T50 完整观测只有在四类证据都存在时才算可验收：

1. 工具和连接器调用记录包含时间、参数、原始返回内容，以及出错时的原始错误。
2. 每回合状态快照覆盖帝国、城市、单位、通知、威胁、科技/市政和生产；缺失项必须明确写出。
3. 决策记录包含触发原因、背景、当前目标、可选动作、最终选择、理由、为什么没选其他动作、执行过程、结果和相关证据 ID。
4. 存档记录能关联 episode、回合、决策或事件、路径、文件大小和 SHA256。

短跑结束后必须停在中文人工报告，不允许自动进入 T50。T50 结束后同样必须停在中文人工报告，不允许自动进入 T51+ 或 Phase 2。

## 本地验证

报告本地开发完成前，至少运行：

```bash
uv run python -m py_compile plugin/src/codex_hl/phase1/observer.py plugin/src/civ6_connector/server.py
uv run pytest tests/test_plugin_structure.py tests/test_phase1_human_report_contract.py -q
uv run pytest tests -q
```

在 Windows 上还要额外跑真实 3 回合短跑。短验收被接受后，T50 改动还必须在 Windows Civ6 真机上跑一次 50 回合观测，确认 `actual_turns = 50`、四类证据 PASS、报告可读。Mac 检查只能证明打包和报告契约，不能替代 Windows Civ6 真机运行。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 加载后 FireTuner 连不上 | 确认 `EnableTuner=1`，关闭残留 Civ6/连接器进程，重新跑短跑，并检查 `raw/tool_calls.jsonl`。 |
| 上一次验证留下连接器服务 | 不要加 `--keep-existing-mcp-server`，默认预检会停止本仓库的旧连接器服务。 |
| 上一次验证让 Civ6 停在游戏画面或主菜单 | 不要加 `--reuse-running-game`，默认预检会重置 Civ6 后重新加载 `test 1`。 |
| 中文人工报告像原始 JSON | 修报告渲染器，然后用报告重建模式重新生成。 |
| 中文 HTML 契约测试失败 | 对照 `plugin/fixtures/phase1_human_report_contract/contract.json` 和 `golden_skeleton.html`，修好后重建报告。 |

## 提交边界

- `episodes/` 默认不提交，除非用户点名要某个产物。
- 主线改动应集中在 `plugin/`、`docs/`、`tests/`、`pyproject.toml`、`.github/` 和根目录开发文档。
- 旧 CivBench、网页和评测资产继续留在 `archive/legacy/`。

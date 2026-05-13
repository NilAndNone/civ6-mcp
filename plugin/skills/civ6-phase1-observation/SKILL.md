---
name: civ6-phase1-observation
description: 在已安装的 codex-hl-civ6 插件中复现 Civilization VI 的 Codex HL Phase 1 观测短跑。用户要求 Codex HL Phase 1、Civ6 观测、test 1 短跑/T50 验证、可复用观测流程、人类报告或 Agent 审计报告时使用。
---

# Civ6 Phase 1 观测

使用已安装的 `codex-hl-civ6` 插件，在真实 `test 1` 单人存档上运行 Codex HL Phase 1 观测流程。目标是记录证据，不是提升策略。

## 硬边界

- 使用 `codex-hl-civ6` 工作区里的已安装插件，以及真实 `test 1` 单人存档。
- 不要切到 Hotseat、其他存档或产品化测试框架。
- 不做失败归因、Replay Arena、候选策略优化、自动学习、晋级或淘汰判断。
- 人工接受短跑报告前，不要继续到 T50。
- `episodes/` 视为本地运行产物；除非用户明确要求提交某个 episode，否则不要提交。

## 标准流程

1. 确认仓库根目录和当前分支。
   - 如果 `git` 不在 PATH，优先使用 `C:\Program Files\Git\cmd\git.exe`。
   - 检查 `git status --short --branch --untracked-files=all`。
   - 不要回滚无关脏文件。
2. 运行短跑。
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
   ```
   只有需要稳定验证名称时，才加 `--episode-id <id>`。
   - 不要为这个流程单独启动 `civ6-connector` 服务。运行器会直接连接 FireTuner。
   - 默认情况下，运行器会停止本仓库残留的 `civ6-connector` 服务进程，并把清理动作记录到 `raw/tool_calls.jsonl`。只有用户明确要求保留现有服务时，才使用 `--keep-existing-mcp-server`。
   - 默认情况下，运行器也会在加载 `test 1` 前重置正在运行的 Civ6，让流程从干净的前端加载路径开始。只有明确手动排障时，才使用 `--reuse-running-game`。
3. 确认生成的 episode 包含：
   - `header.json`
   - `raw/tool_calls.jsonl`
   - `raw/mcp.jsonl`
   - `raw/civ6_states/*.json`
   - `raw/saves/save_index.jsonl`
   - `derived/decision_atoms.jsonl`
   - `derived/report_pack.json`
   - `outcome/phase1_short_run_report.draft.html`
   - `outcome/phase1_short_run_report.html`
   - `outcome/phase1_agent_report.md`
   - `outcome/phase1_agent_audit_report.html`
4. 验证四类证据：
   - 工具/MCP 调用都有时间、参数、原始结果或错误。
   - 每回合都有状态快照，覆盖帝国、城市、单位、通知、威胁、科技/市政、生产，或明确写出缺口。
   - 决策记录包含 `available_actions`、理由、`why_not_alternatives`、执行、结果、`related_*_ids`，以及兼容字段 `alternatives` 和 `evidence_ids`。
   - 存档索引能把存档关联到 episode、回合、决策或事件。
5. 把报告分成两层看：
   - 证据层写入原始日志、`derived/report_pack.json` 和草稿 HTML。
   - 最终 `phase1_short_run_report.html` 是给人看的中文入口。它必须基于 `report_pack.json`，并通过下面的中文 HTML 契约。
6. 确认 `phase1_short_run_report.html` 满足下面的中文 HTML 契约。运行器会自动检查；如果失败，先修报告渲染器或用 `--report-only` 重建，不要直接请求人工验收。
7. 汇报中文人工报告路径，然后暂停等待人工验收。

## 报告分工

- `phase1_short_run_report.html` 是唯一的人类审阅入口。它必须保留 `phase1_test1_short_20260512_130155` 已接受的中文 HTML 形态，并提升可扫描性，不能退化成工程摘要。
- `phase1_short_run_report.draft.html` 是运行器生成的草稿材料，可用于调试渲染器；如果最终契约没过，它不是人工验收入口。
- `phase1_agent_report.md` 是下一个 Agent 或下一次会话的快速接手报告。恢复工作时先读它。
- `phase1_agent_audit_report.html` 是完整机器/Agent 审计报告，包含原始 JSON 证据和可展开细节。它不能替代中文人工 HTML。
- 如果人工报告像原始 JSON、字段堆叠或只有表格审计，必须先重新生成或改进报告，再请求验收。

## 中文 HTML 契约

中文人工报告必须是打磨过的 HTML 审阅文档，并保持这个章节顺序：

1. `Codex HL Phase 1 人类验收报告`
2. `验收结论`
3. `我实际观测到的局面变化`，其中包含 `起点 T...` 和 `终点 T...`
4. `回合叙事`
5. `重点：决策流程`
6. `证据边界和你需要判断的点`
7. `存档和决策关联`
8. `缺口清单`
9. `面向 Agent 的报告`，并链接到 `phase1_agent_report.md` 和 Agent 审计产物

可读性底线要高于已接受的基线 HTML。可复用报告必须包含：

- 顶部有简短的 `先读这份报告的顺序`，让审阅者知道先看哪里。
- 有 `快速定位` 导航，能跳到主要章节。
- 用 `关键数字变化` 指标块呈现变化，而不是只有密集文字或列表。
- 每回合叙事用 `turn-card` 卡片展示，不用宽审计表格。
- 决策记录用 `decision-header`、`decision-grid` 和 `review-note` 展示。
- 存档行要紧凑，先显示检查点文件名，再显示完整路径。
- 为两个 Agent 产物提供 `快速接手` 和 `完整审计` 两个入口。

每条决策必须用自然语言展示这些标签：

- `当时看到的问题：`
- `候选动作：`
- `我选择了：`
- `为什么这样选：`
- `为什么没选其他动作：`
- `执行后结果：`
- `对 review 的意义：`

不要在 `phase1_short_run_report.html` 里放原始 JSON 块、`<details>`、`<pre>`，或 `{&quot;turn&quot;` 这类编码后的状态 dump。原始证据放到 `phase1_agent_audit_report.html`、`derived/report_pack.json` 和 episode 的 `raw/` 文件。

契约来源是 `plugin/fixtures/phase1_human_report_contract/contract.json`；骨架夹具用于防止后续 Agent 发明另一种人工报告形态。

## 重建已有报告

episode 已存在且不能推进 Civ6 回合时，使用报告重建模式：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

报告重建模式不能启动 Civ6，也不能修改当前游戏。

## 新 Agent 验证提示词

用全新 Agent 验证技能时，使用这个提示词结构：

```text
使用 plugin/skills/civ6-phase1-observation/SKILL.md。
不要改代码，不要提交，不要推送。
在真实 test 1 单人存档上跑一次 3 回合 Phase 1 短跑。
不要单独启动 civ6-connector 服务；只使用 codex-hl-civ6-phase1-observe。
创建一个新的 episode id，命名为 phase1_subagent_validation_<timestamp>。
在 T50 前停止。
返回 episode_id、中文人工报告路径、Agent 接手报告路径、Agent 审计报告路径、四类证据的 PASS/FAIL 结果，以及阻塞项。
```

## 提交边界

- 可以提交插件运行器、这个技能和相关文档。
- 默认不要暂存 `episodes/`。
- 不要暂存无关脏文件，例如独立玩法修复或旧实验脚本，除非用户明确包含它们。

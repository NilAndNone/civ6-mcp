# codex-hl-civ6

`codex-hl-civ6` 是一个让 Codex 以“先观测、再验收”的方式玩
Civilization VI 的插件项目。

`v0.0.2` 是当前仓库的策略改进验收版本。它在 `v0.0.1` 冻结入口、边界、
证据产物和本地验收方式的基础上，证明候选 playbook 能进入 observation runner
决策路径，并在 Windows 真机 T50 对比中改善主指标。

## 一句话结论

这套系统现在已经具备从真实 Civ6 对局记录证据、离线标注失败、管理策略
资产、生成候选改进、沉淀回归场景、执行治理审计、编排多局运行，以及生成
`v0.0.2` 策略改进验收报告的正式入口。

`v0.0.2` 已通过 `5 baseline T50 + 5 candidate T50` 的本地 Windows 真机验收：
候选 playbook 来自正式 failure，runner 读取候选包并产生可审计行为差异，
T50 科技、科学和文化主指标改善，且没有明显主指标退化。

## 当前正式版本

- 当前版本：`0.0.2`
- 目标标签：`v0.0.2`
- `v0.0.1` 审批入口：`docs/v0.0.1-release.md`
- `v0.0.2` 验收目标：`docs/v0.0.2-strategy-improvement.md`
- 长期路线图：`docs/codex-hl-evolution-roadmap.md`

## v0.0.2 包含什么

### 1. 基础观测与报告

- `/civ6-observe`：运行真实 Civ6 observation episode。
- `/civ6-observe --report-only`：基于已有 episode 重建报告。
- `/civ6-debug`：检查 Civ6 连接、FireTuner 端口和存档目录。

这一级是当前最基础的能力：记录真实游戏发生了什么，并生成可审阅报告。

### 2. 离线资产与证据流程

- `/civ6-review`：从已有 episode 生成候选失败，人工确认后写正式失败。
- `/civ6-strategy-assets`：校验资产库，列出 active assets，只读比较 T50 指标。
- `/civ6-strategy-candidates`：从正式失败生成候选改进包。
- `/civ6-validation-scenarios`：把正式失败登记成被动回归场景。
- `/civ6-governance`：做候选合并审计；显式允许且 gate 全过才写资产。

这一级是正式入口，但核心边界是“证据、候选、审计、显式确认”，不是自动改策略。

### 3. 自动化编排待验入口

- `/civ6-runs`：编排多局 T20/T50、Review、Strategy Candidate、Validation 和 governance 审计。
- `/civ6-acceptance`：只读验证 `5 baseline T50 + 5 candidate T50`，
  生成 `v0.0.2` 策略改进验收报告。

`/civ6-runs` 现在可以把 strategy candidate package 作为只读运行时输入传给
observation runner。候选包不会自动合并资产；合并仍然必须走 governance gate。

## 仓库结构

- `plugin/`：可安装的 Codex 插件成品目录。
- `plugin/AGENTS.md`：插件安装后 Codex 先读的使用说明。
- `plugin/commands/`：安装后的命令入口说明。
- `plugin/assets/codex_hl/strategy/`：prompt、playbook、tool policy、memory 的版本化资产库。
- `plugin/src/codex_hl/`：observation、review、strategy、validation、governance 和 runs 的流程代码。
- `plugin/src/civ6_connector/`：连接 Civilization VI、FireTuner 和 Lua 查询的底层代码。
- `docs/`：开发说明、职责模块说明、版本审批和长期路线图。
- `tests/`：本地结构、报告、资产、治理和连接器测试。
- `validation/scenarios/`：Validation 生成的被动回归场景池。
- `archive/legacy/`：旧 CivBench、网页、评测、脚本和研究资料；不属于当前主线。

## 先看哪几份文档

如果你要审批第一个正式版本：

1. `docs/v0.0.1-release.md`
2. `docs/plugin-architecture.md`
3. `docs/codex-hl-observation.md`
4. `docs/v0.0.2-strategy-improvement.md`

如果你要运行插件：

1. `plugin/README.md`
2. `plugin/AGENTS.md`
3. `plugin/commands/`

如果你要改代码：

1. `docs/README.md`
2. 对应职责模块文档
3. `tests/`

## 本地验收

交付前使用本地检查：

```bash
uv run codex-hl-civ6-strategy-assets --check
uv run python -m py_compile plugin/src/codex_hl/evidence/observation.py plugin/src/civ6_connector/server.py
uv run python -m py_compile plugin/src/codex_hl/review/failure_labeling.py plugin/src/codex_hl/strategy/registry.py
uv run python -m py_compile plugin/src/codex_hl/strategy/candidates.py plugin/src/codex_hl/validation/scenarios.py plugin/src/codex_hl/governance/gates.py
uv run python -m py_compile plugin/src/codex_hl/runs/orchestrator.py plugin/src/codex_hl/reports/acceptance.py
uv run pytest tests -q
git diff --check
```

Windows 真实 Civ6 端到端验收仍然要用真实 `test 1` 存档运行，不能用模拟数据替代。

`v0.0.2` 策略改进验收使用：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-acceptance --candidate-package <candidate.json> --baseline-episodes <5 baseline ids> --candidate-episodes <5 candidate ids>
```

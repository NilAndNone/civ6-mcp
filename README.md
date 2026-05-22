# codex-hl-civ6

`codex-hl-civ6` 是一个让 Codex 以“先观测、再验收”的方式玩
Civilization VI 的插件项目。

`v0.0.1` 是当前仓库的第一个正式版本。它要冻结的是现有系统的入口、
边界、证据产物和本地验收方式，而不是承诺策略已经被自动优化。

## 一句话结论

这套系统现在已经具备从真实 Civ6 对局记录证据、离线标注失败、管理策略
资产、生成候选改进、沉淀回归场景、执行治理审计和编排多局运行的正式入口。

但 `v0.0.1` 只证明这些入口、边界和本地检查成立；“候选 playbook 真的让
策略变好”留给 `v0.0.2` 用 Windows 真机多局 T50 对比验证。

## 当前正式版本

- 当前版本：`0.0.1`
- 目标标签：`v0.0.1`
- 审批入口：`docs/v0.0.1-release.md`
- 下一版目标：`docs/v0.0.2-strategy-improvement.md`
- 长期路线图：`docs/codex-hl-evolution-roadmap.md`

## v0.0.1 包含什么

### 1. 基础观测与报告

- `/civ6-phase1-observe`：运行真实 Civ6 Phase 1 episode。
- `/civ6-phase1-report`：基于已有 episode 重建报告。
- `/civ6-debug`：检查 Civ6 连接、FireTuner 端口和存档目录。

这一级是当前最基础的能力：记录真实游戏发生了什么，并生成可审阅报告。

### 2. 离线资产与证据流程

- `/civ6-phase2-label`：从已有 episode 生成候选失败，人工确认后写正式失败。
- `/civ6-phase3-assets`：校验资产库，列出 active assets，只读比较 T50 指标。
- `/civ6-phase4-candidates`：从正式失败生成候选改进包。
- `/civ6-phase5-scenarios`：把正式失败登记成被动回归场景。
- `/civ6-governance`：做候选合并审计；显式允许且 gate 全过才写资产。

这一级是正式入口，但核心边界是“证据、候选、审计、显式确认”，不是自动改策略。

### 3. 自动化编排待验入口

- `/civ6-evolve`：编排多局 T20/T50、Phase 2、Phase 4/5 和 governance 审计。

这个入口纳入 `v0.0.1`，但策略改进效果不在 `v0.0.1` 承诺内。`v0.0.2`
会专门验证 playbook 候选是否真实影响 runner，并改善 T50 主指标。

## 仓库结构

- `plugin/`：可安装的 Codex 插件成品目录。
- `plugin/AGENTS.md`：插件安装后 Codex 先读的使用说明。
- `plugin/commands/`：安装后的命令入口说明。
- `plugin/assets/codex_hl/phase3/`：prompt、playbook、tool policy、memory 的版本化资产库。
- `plugin/src/codex_hl/`：Phase 1-5、governance 和 evolution 的流程代码。
- `plugin/src/civ6_connector/`：连接 Civilization VI、FireTuner 和 Lua 查询的底层代码。
- `docs/`：开发说明、阶段说明、版本审批和长期路线图。
- `tests/`：本地结构、报告、资产、治理和连接器测试。
- `validation/regression_scenarios/`：Phase 5 生成的被动回归场景池。
- `archive/legacy/`：旧 CivBench、网页、评测、脚本和研究资料；不属于当前主线。

## 先看哪几份文档

如果你要审批第一个正式版本：

1. `docs/v0.0.1-release.md`
2. `docs/plugin-architecture.md`
3. `docs/codex-hl-phase1-observation.md`
4. `docs/v0.0.2-strategy-improvement.md`

如果你要运行插件：

1. `plugin/README.md`
2. `plugin/AGENTS.md`
3. `plugin/commands/`

如果你要改代码：

1. `docs/README.md`
2. 对应阶段文档
3. `tests/`

## 本地验收

`v0.0.1` 打标前使用本地检查：

```bash
uv run codex-hl-civ6-phase3-assets --check
uv run python -m py_compile plugin/src/codex_hl/phase1/observer.py plugin/src/civ6_connector/server.py
uv run python -m py_compile plugin/src/codex_hl/phase2/labeler.py plugin/src/codex_hl/phase3/assets.py
uv run python -m py_compile plugin/src/codex_hl/phase4/improvements.py plugin/src/codex_hl/phase5/scenarios.py plugin/src/codex_hl/governance/automation.py
uv run python -m py_compile plugin/src/codex_hl/evolution/orchestrator.py
uv run pytest tests -q
git diff --check
```

Windows 真实 Civ6 短跑仍然是端到端验收要求，但不是 `v0.0.1` 打标前的硬门槛。

## 下一步

`v0.0.2` 的目标是策略改进验证：系统自动从正式 failure 生成候选 playbook，
让 playbook 直接驱动 Phase 1 runner，并在 Windows 真机上用
`5 baseline T50 + 5 candidate T50` 对比 T50 主指标。

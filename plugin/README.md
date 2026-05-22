# Codex HL Civ6 插件

这个目录是可安装的 Codex 插件成品。

当前插件版本：`0.0.1`

## 先读什么

安装后 Codex 应先读：

1. `AGENTS.md`
2. `assets/codex_hl/phase3/catalog.json`
3. 当前任务需要的 active asset
4. 对应的 `commands/*.md`

## 命令分级

### 1. 基础观测与报告

- `/civ6-phase1-observe`：运行真实 Civ6 Phase 1 观测。
- `/civ6-phase1-report`：基于已有 episode 重建报告。
- `/civ6-debug`：检查连接、FireTuner 和存档环境。

### 2. 离线资产与证据流程

- `/civ6-phase2-label`：离线标注候选失败，人工确认后写正式 failure。
- `/civ6-phase3-assets`：校验资产库，列 active assets，只读比较 T50。
- `/civ6-phase4-candidates`：从正式 failure 生成候选改进包。
- `/civ6-phase5-scenarios`：把正式 failure 登记为被动 regression scenario。
- `/civ6-governance`：审计候选资产，显式允许且 gate 通过才合并。

### 3. 自动化编排待验入口

- `/civ6-evolve`：编排多局 T20/T50 和后续阶段。

`/civ6-evolve` 是 `v0.0.1` 的正式入口，但策略改进效果不在 `v0.0.1`
承诺内。`v0.0.2` 会验证候选 playbook 是否真实驱动 runner 并改善 T50 主指标。

## 核心边界

- Phase 1 只记录事实，不判断策略好坏。
- Phase 2 只读已有 episode，不启动 Civ6。
- Phase 3 只管理和校验资产，不生成候选改动。
- Phase 4 只生成候选包，不直接改资产。
- Phase 5 只登记 passive scenario，不 replay。
- Governance 默认 audit-only。
- Evolution 可以编排流程，但不能替代策略改进验收。

## 运行产物

真实运行会写 `episodes/<episode_id>/`。这些是本地产物，默认不要提交。

回归场景池默认写到：

```text
validation/regression_scenarios/
```

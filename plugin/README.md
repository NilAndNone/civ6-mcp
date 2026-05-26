# Codex HL Civ6 插件

这个目录是可安装的 Codex 插件成品。

当前插件版本：`0.0.2`

## 先读什么

安装后 Codex 应先读：

1. `AGENTS.md`
2. `assets/codex_hl/strategy/catalog.json`
3. 当前任务需要的 active asset
4. 对应的 `commands/*.md`

## 命令分级

### 1. 基础观测与报告

- `/civ6-observe`：运行真实 Civ6 Observation 观测。
- `/civ6-observe --report-only`：基于已有 episode 重建报告。
- `/civ6-debug`：检查连接、FireTuner 和存档环境。

### 2. 离线资产与证据流程

- `/civ6-review`：离线标注候选失败，人工确认后写正式 failure。
- `/civ6-strategy-assets`：校验资产库，列 active assets，只读比较 T50。
- `/civ6-strategy-candidates`：从正式 failure 生成候选改进包。
- `/civ6-validation-scenarios`：把正式 failure 登记为被动 regression scenario。
- `/civ6-governance`：审计候选资产，显式允许且 gate 通过才合并。

### 3. 自动化编排和验收入口

- `/civ6-runs`：编排多局 T20/T50 和后续阶段。
- `/civ6-acceptance`：只读验证 `5 baseline T50 + 5 candidate T50` 的
  `v0.0.2` 策略改进验收。

`/civ6-runs` 可以把 strategy candidate package 作为只读运行时输入传给
observation runner；候选包不会自动合并资产，合并仍然必须走 governance gate。

## 核心边界

- Observation 只记录事实，不判断策略好坏。
- Review 只读已有 episode，不启动 Civ6。
- Strategy 负责管理资产和候选包，是系统的核心产物层。
- Validation 只登记 passive scenario，不 replay。
- Governance 默认 audit-only。
- Evolution 可以编排流程，但不能替代策略改进验收。

## 运行产物

真实运行会写 `episodes/<episode_id>/`。这些是本地产物，默认不要提交。

回归场景池默认写到：

```text
validation/scenarios/
```

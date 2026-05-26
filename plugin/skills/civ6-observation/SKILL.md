---
name: civ6-observation
description: 在已安装的 codex-hl-civ6 插件中运行 Civilization VI Observation 观测、短跑、T50、报告重建或审计报告时使用。
---

# Civ6 Observation 观测

执行前先读取：

- `../../assets/codex_hl/strategy/catalog.json`
- `strategy.prompt.default_boundary`
- `strategy.memory.low_trust`
- `strategy.playbook.observation`
- `strategy.tool_policy.observation_evidence`

## 用途

Observation 只记录真实 Civ6 发生了什么，并生成可审阅报告。它不判断策略好坏，
不生成候选改进，不进入自动学习。

## 命令

短跑：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --save-name "test 1" --turns 3
```

T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --save-name "test 1" --turns 50
```

重建已有报告：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --report-only <episode_id>
```

## 汇报内容

返回：

- episode id
- 中文人工报告路径
- Agent 接手报告路径
- Agent 审计报告路径
- 四类证据 PASS/FAIL
- 实际回合数
- 起点/终点回合
- 阻塞项或证据缺口

## 提交边界

`episodes/` 默认是本地运行产物。除非用户明确点名某个 episode，否则不要提交。

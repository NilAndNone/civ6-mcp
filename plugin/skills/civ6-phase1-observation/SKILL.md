---
name: civ6-phase1-observation
description: 在已安装的 codex-hl-civ6 插件中复现 Civilization VI 的 Codex HL Phase 1 观测。用户要求 Codex HL Phase 1、Civ6 观测、test 1 短跑/T50 验证、可复用观测流程、人类报告或 Agent 审计报告时使用。
---

# Civ6 Phase 1 观测

规则主体已经迁入 Phase 3 资产。执行本技能前先读取：

- `../../assets/codex_hl/phase3/catalog.json`
- asset `prompt.default_boundary`
- asset `memory.low_trust_policy`
- asset `playbook.phase1_observation`
- asset `tool_policy.phase1_run_and_evidence`

## 命令

短跑：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
```

T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 50
```

重建已有报告：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

## 汇报

返回 episode id、中文人工报告路径、Agent 接手报告路径、Agent 审计报告路径、四类证据 PASS/FAIL、实际回合数、起点/终点回合和阻塞项。

## 提交边界

`episodes/` 默认是本地运行产物；除非用户明确点名某个 episode，否则不要提交。

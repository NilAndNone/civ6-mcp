# /civ6-phase1-report

基于已有 episode 重新生成 Phase 1 报告，不推进 Civilization VI。

## 必读资产

- `prompt.default_boundary`
- `playbook.phase1_observation`
- `tool_policy.phase1_run_and_evidence`

## 参数

- `episode_id`：必填，目标 episode 名称。

## 调用

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

报告重建模式只读已有 episode 证据。旧 episode 如果没有 `assets_snapshot/active_assets.json`，只能报告资产快照缺口，不能伪造历史资产版本。

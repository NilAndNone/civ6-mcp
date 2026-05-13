# /civ6-phase1-report

基于已有 episode 重新生成 Phase 1 报告，不推进 Civilization VI。

## 参数

- `episode_id`：必填，目标 episode 名称。

## 使用方式

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

报告重建模式不能启动 Civ6，也不能推进当前游戏。

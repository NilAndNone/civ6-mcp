# /civ6-phase1-report

## 用途

基于已有 Phase 1 episode 重建报告，不推进 Civilization VI。

## 输入

- `episode_id`：目标 episode id。

## 输出

重新生成或更新：

- `outcome/phase1_short_run_report.html`
- `outcome/phase1_agent_report.md`
- `outcome/phase1_agent_audit_report.html`
- `derived/report_pack.json`

## 边界

- 只读已有 episode 证据。
- 不启动 Civ6。
- 不加载存档。
- 不推进回合。
- 旧 episode 如果没有资产快照，只能报告缺口，不能伪造历史资产版本。

## 示例

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

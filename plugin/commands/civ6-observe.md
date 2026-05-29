# /civ6-observe

## 用途

运行 legacy-baseline Observation 真实 Civ6 观测，生成 episode、证据和报告。

Phase 3 后这个入口是 deprecated baseline / compatibility path：用于旧报告
重建、baseline 对照和旧 episode 读取。新的真实主线入口是
`/civ6-observe-live`。

## 输入

- `--save-name`：存档名，默认 `test 1`。
- `--turns`：目标回合数，短跑默认 `3`，T50 使用 `50`。
- `--episode-id`：可选，指定稳定 episode id。
- `--strategy-profile`：可选运行策略 profile。

## 输出

写入：

```text
episodes/<episode_id>/
```

权威存储：

- `episode.db`

文件树仍会导出，作为人工查看和旧工具兼容入口。

关键产物：

- `header.json`
- `raw/tool_calls.jsonl`
- `raw/mcp.jsonl`
- `raw/civ6_states/*.json`
- `raw/saves/save_index.jsonl`
- `derived/decision_atoms.jsonl`
- `derived/report_pack.json`
- `outcome/observation_report.html`
- `outcome/agent_report.md`
- `outcome/agent_audit_report.html`
- `assets_snapshot/manifest.json`

## 边界

- Observation 只记录事实，不判断策略好坏。
- legacy-baseline 不是默认真实执行主线。
- 新 live strict 验收请使用 `/civ6-observe-live`。
- 短跑结束后停止，不自动进入 T50。
- T50 结束后停止，不自动进入 Review。
- 不提交 `episodes/`，除非用户明确要求。

## 示例

短跑：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --save-name "test 1" --turns 3
```

T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --save-name "test 1" --turns 50
```

从旧文件树重建 DB：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-observe --rebuild-db <episode_id>
```

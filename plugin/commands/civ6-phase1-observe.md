# /civ6-phase1-observe

## 用途

运行 Phase 1 真实 Civ6 观测，生成 episode、证据和报告。

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

关键产物：

- `header.json`
- `raw/tool_calls.jsonl`
- `raw/mcp.jsonl`
- `raw/civ6_states/*.json`
- `raw/saves/save_index.jsonl`
- `derived/decision_atoms.jsonl`
- `derived/report_pack.json`
- `outcome/phase1_short_run_report.html`
- `outcome/phase1_agent_report.md`
- `outcome/phase1_agent_audit_report.html`

## 边界

- Phase 1 只记录事实，不判断策略好坏。
- 短跑结束后停止，不自动进入 T50。
- T50 结束后停止，不自动进入 Phase 2。
- 不提交 `episodes/`，除非用户明确要求。

## 示例

短跑：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
```

T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 50
```

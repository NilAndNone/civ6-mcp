# Phase 2 v1 离线失败标注

Phase 2 读取已有 Phase 1 episode，从证据里标出候选失败。它不启动 Civ6，
不加载存档，不推进回合，也不直接修改资产。

## 输入

- `episodes/<episode_id>/` 下已有的 Phase 1 证据。
- `derived/report_pack.json`
- `derived/decision_atoms.jsonl`
- `raw/tool_calls.jsonl`
- `raw/mcp.jsonl`
- `raw/civ6_states/*.json`
- `raw/saves/save_index.jsonl`

正式 apply 还需要人工确认文件：

```text
episodes/<episode_id>/phase2/confirmation/confirmation.jsonl
```

## 处理过程

生成候选：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id>
```

Phase 2 会只读 Phase 1 证据，生成候选失败和审阅页面。候选只是候选，不能
当成正式 failure。

人工确认后 apply：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\phase2\confirmation\confirmation.jsonl
```

apply 会校验候选存在、证据引用能回到 Phase 1、输入 hash 没变化，并拒绝
任何暗示修复、重跑、replay 或资产修改的字段。

## 输出

候选阶段：

- `phase2/candidates.jsonl`
- `phase2/candidate_summary.json`
- `phase2/phase2_review.html`

确认 apply 后：

- `phase2/failures.jsonl`
- `phase2/regression_seeds.jsonl`
- `phase2/confirmation_audit.jsonl`
- `phase2/phase2_summary.md`
- `phase2/phase2_summary.json`

## 验收看什么

- 是否只读取目标 episode。
- 是否没有启动 Civ6。
- 候选 failure 是否能回到具体证据。
- 人工确认前是否没有正式 `failures.jsonl`。
- apply 后是否一条正式 failure 对应一个被动 seed。
- 是否没有生成策略补丁、资产 diff、重跑命令或 replay 目标。

本地检查：

```bash
uv run pytest tests/test_phase2_labeler.py -q
```

## 最容易错的地方

- 把候选失败当成正式失败。
- 把短跑里的 high confidence 当成长周期战略结论。
- 在 Phase 2 里写修复建议或资产变更。
- 用 Phase 2 启动 Civ6 或推进回合。

短跑或 T20 里的 high confidence 只能说明局部片段，不是长期策略结论。

# /civ6-v002-acceptance

## 用途

基于已经完成的真机 T50 episode，生成 `v0.0.2` 策略改进验收报告。这个入口只读
现有证据，不启动 Civ6，不 replay，不修改 Phase 3 资产。

## 输入

- `--candidate-package <candidate.json>`：Phase 4 生成的候选 playbook 包。
- `--baseline-episodes <5 个 episode id>`：5 个 baseline T50 episode。
- `--candidate-episodes <5 个 episode id>`：5 个 candidate T50 episode。
- `--output-dir <dir>`：验收报告输出目录。

## 输出

- `v0.0.2_acceptance_report.json`
- `v0.0.2_acceptance_report.html`

## 示例

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-v002-acceptance `
  --candidate-package episodes\<source_ep>\phase4\candidate_packages\<candidate_id>\candidate.json `
  --baseline-episodes <baseline_1> <baseline_2> <baseline_3> <baseline_4> <baseline_5> `
  --candidate-episodes <candidate_1> <candidate_2> <candidate_3> <candidate_4> <candidate_5>
```

## 验收项

- baseline 和 candidate 都必须是 `5` 个完整 T50 episode。
- 候选包必须能回指到 Phase 2 正式 `failures.jsonl`。
- candidate episode 的 `header.json` 和 `decision_atoms.jsonl` 必须证明 runner 读取并应用了候选包。
- candidate 相比 baseline 必须有可审计行为差异。
- 至少一个 T50 主指标改善，且没有明显主指标退化。

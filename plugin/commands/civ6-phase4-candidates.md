# /civ6-phase4-candidates

从已有 Phase 2 正式 failure 生成 Phase 4 候选改进包。

## 必读资产

- `prompt.default_boundary`
- `memory.low_trust_policy`
- `playbook.phase4_candidate_improvements`
- `tool_policy.phase4_candidate_gate`

## 调用

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase4-candidates --episode-id <episode_id>
```

产物位于 `episodes/<episode_id>/phase4/`：

- `candidate_improvements.jsonl`
- `candidate_packages/<candidate_id>/candidate.json`
- `candidate_packages/<candidate_id>/asset_diff.json`
- `candidate_packages/<candidate_id>/validation_plan.json`
- `candidate_packages/<candidate_id>/evidence_pack.json`
- `phase4_review.html`

Phase 4 只生成候选包，不改资产、不 merge、不 rollback、不启动 Civ6。候选进入 L4/L5 前必须有 Phase 5 scenario pool 和多场景 validation report。

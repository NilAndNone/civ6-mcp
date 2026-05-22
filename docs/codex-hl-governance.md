# Codex HL L4/L5 资产治理

L4/L5 治理负责在多场景验证通过后执行受控 asset merge，并在退化时回滚。

## 默认行为

默认只做 audit-only evaluation，不改资产。只有显式传入 `--allow-merge` 且所有 gate 通过，才写 asset file、catalog 和 ledger。

## Merge gate

- 至少两个 scenario。
- 所有 scenario pass。
- T50 主指标至少一个变好。
- T50 主指标无退化。
- 无 regression records。
- 目标资产当前 hash 匹配候选记录。
- 候选包含 source failure、rollback plan，且仍是 `candidate_only`。

## 命令

审计：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-governance --evaluate --candidate-package <candidate.json> --validation-report <validation_report.json>
```

显式合并：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-governance --evaluate --candidate-package <candidate.json> --validation-report <validation_report.json> --allow-merge
```

回滚：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-governance --rollback --audit-dir <automation/audits/decision_id> --reason "<reason>"
```

## 产物

- `automation/audits/<decision_id>/merge_decision.json`
- `automation/audits/<decision_id>/rollback_snapshot.json`
- `automation/audits/<decision_id>/merge_result.json`
- `automation/audits/<decision_id>/rollback_result.json`

## 验收

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m py_compile plugin/src/codex_hl/governance/automation.py
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run pytest tests/test_phase4_5_governance.py -q
```

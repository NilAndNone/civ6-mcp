# /civ6-governance

执行 L4/L5 资产治理：默认只做 merge gate 审计；显式 `--allow-merge` 且所有 gate 通过时才写资产。

## 必读资产

- `prompt.default_boundary`
- `memory.low_trust_policy`
- `tool_policy.governance_auto_merge`

## 审计候选

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-governance --evaluate --candidate-package <candidate.json> --validation-report <validation_report.json>
```

审计写入 `automation/audits/<decision_id>/merge_decision.json`。默认不会改资产。

## 显式自动合并

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-governance --evaluate --candidate-package <candidate.json> --validation-report <validation_report.json> --allow-merge
```

合并 gate：

- 至少两个 scenario。
- 所有 scenario pass。
- T50 主指标至少一个变好。
- T50 主指标无退化。
- 无 regression records。
- 目标资产 hash 匹配候选来源。
- 候选有 source failure 和 rollback plan。

## 回滚

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-governance --rollback --audit-dir <automation/audits/decision_id> --reason "<reason>"
```

回滚从 merge audit 的 `rollback_snapshot.json` 恢复资产正文和 catalog hash，并写入 rollback audit。

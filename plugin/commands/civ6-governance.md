# /civ6-governance

## 用途

审计 Phase 4 候选资产是否满足合并 gate。默认只写审计，不改资产。只有显式
传 `--allow-merge` 且所有 gate 通过时才写资产。

## 输入

- `--candidate-package <candidate.json>`
- `--validation-report <validation_report.json>`
- `--allow-merge`：可选，允许 gate 全过后写资产。
- `--rollback --audit-dir <dir> --reason <reason>`：回滚已合并资产。

## 输出

审计：

```text
automation/audits/<decision_id>/merge_decision.json
```

合并时还会写 rollback snapshot、更新 asset 正文、更新 catalog 和 ledger。

## 边界

- 默认 audit-only。
- 没有 `--allow-merge` 不写资产。
- gate 不全过不写资产。
- 回滚必须基于已有 merge audit。
- validation report 必须能支持候选有效性判断。

## 示例

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

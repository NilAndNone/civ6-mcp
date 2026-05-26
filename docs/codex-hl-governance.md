# L4/L5 资产治理

Governance 负责审计候选资产是否可以合并，并在显式允许且所有 gate 通过时
执行合并或回滚。

默认行为是 audit-only，不改资产。

## 输入

审计输入：

- strategy candidate package。
- validation report。
- strategy asset catalog。

回滚输入：

- 已存在的 merge audit 目录。
- 回滚原因。

## 处理过程

审计候选：

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

## 输出

审计输出：

```text
automation/audits/<decision_id>/merge_decision.json
```

合并时还会写：

- `rollback_snapshot.json`
- 更新后的 asset 正文。
- 更新后的 `catalog.json`。
- `change_ledger.jsonl` 新记录。

回滚时会恢复 asset 正文和 catalog hash，并追加 rollback ledger。

## 验收看什么

合并 gate：

- 至少两个 scenario。
- 所有 scenario pass。
- 至少一个 T50 主指标变好。
- 无 T50 主指标退化。
- 无 regression records。
- 目标资产 hash 和候选记录匹配。
- 候选有 source failure。
- 候选有 rollback plan。
- 候选不是 premerged 状态。

本地检查：

```bash
uv run pytest tests/test_strategy_validation_governance.py -q
```

## 最容易错的地方

- 忘记默认是 audit-only。
- 没有 `--allow-merge` 却以为会写资产。
- validation report 不是候选运行时产生的，却拿来合并候选。
- 合并前没有保存 rollback snapshot。
- 回滚只改正文，不恢复 catalog hash。

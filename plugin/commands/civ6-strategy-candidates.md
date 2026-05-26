# /civ6-strategy-candidates

## 用途

从 Review 正式 failure 生成候选改进包。候选包用于后续验证和 governance，
不会直接修改资产。

## 输入

- `--episode-id <episode_id>`：已有 Review 正式 failure 的 episode。

## 输出

写入：

```text
episodes/<episode_id>/strategy/candidates/
```

关键产物：

- `candidate_improvements.jsonl`
- `candidate_packages/<candidate_id>/candidate.json`
- `candidate_packages/<candidate_id>/asset_diff.json`
- `candidate_packages/<candidate_id>/validation_plan.json`
- `candidate_packages/<candidate_id>/evidence_pack.json`
- `strategy_candidate_review.html`

## 边界

- 只读正式 failure。
- 不直接改资产。
- 不写 catalog 或 ledger。
- 不启动 Civ6。
- 不 replay。
- 不宣称候选已经更好。

## 示例

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-strategy-candidates --episode-id <episode_id>
```

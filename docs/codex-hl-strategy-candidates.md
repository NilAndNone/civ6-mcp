# Strategy Candidate 候选改进包

Strategy Candidate 从 Review 的正式 failure 生成候选改进包。它可以提出资产修改候选，
但不能直接修改资产。

## 输入

- `episodes/<episode_id>/review/failures.jsonl`
- `episodes/<episode_id>/review/regression_seeds.jsonl`
- strategy asset catalog。

只有人工确认后的正式 failure 可以进入 Strategy Candidate。候选 failure 不可以。

## 处理过程

入口命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-strategy-candidates --episode-id <episode_id>
```

Strategy Candidate 会：

1. 读取正式 failure。
2. 按能力维度选择目标 active asset。
3. 生成候选内容、差异摘要、验证计划、证据包和回滚计划。
4. 把所有产物写在 episode 的 `strategy/candidates/` 下。

它不会修改 `plugin/assets/`。

## 输出

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

## 验收看什么

- 候选是否引用正式 failure。
- 目标资产版本和 hash 是否记录清楚。
- 是否包含验证计划和回滚计划。
- 是否明确 `candidate_only`。
- 是否没有直接改资产、catalog、ledger、save 或 Civ6 状态。

本地检查：

```bash
uv run pytest tests/test_strategy_validation_governance.py -q
```

## 最容易错的地方

- 把候选包当成已接受资产修改。
- 直接改 strategy asset 正文。
- 没有保留当前资产 hash，导致后续 governance 无法判断候选是否过期。
- 在 Strategy Candidate 里启动 Civ6 或 replay。

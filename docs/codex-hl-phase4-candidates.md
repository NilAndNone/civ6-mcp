# Codex HL Phase 4 候选改进包

Phase 4 把已确认的 Phase 2 failure 转成候选资产改进包，但不直接修改资产。

## 边界

- 只读 `episodes/<episode_id>/phase2/failures.jsonl` 和 `regression_seeds.jsonl`。
- 读取 Phase 3 asset catalog 来选择候选目标资产。
- 只写 `episodes/<episode_id>/phase4/`。
- 不启动 Civ6，不 replay，不改 asset catalog，不写资产正文，不 merge，不 rollback。

## 命令

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase4-candidates --episode-id <episode_id>
```

## 产物

- `MANIFEST.json`
- `candidate_improvements.jsonl`
- `candidate_packages/<candidate_id>/candidate.json`
- `candidate_packages/<candidate_id>/asset_diff.json`
- `candidate_packages/<candidate_id>/validation_plan.json`
- `candidate_packages/<candidate_id>/evidence_pack.json`
- `phase4_review.html`

候选必须包含 source failure、target asset、proposed content、asset diff、validation plan、risk assessment 和 rollback plan。

## 验收

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m py_compile plugin/src/codex_hl/phase4/improvements.py
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run pytest tests/test_phase4_5_governance.py -q
```

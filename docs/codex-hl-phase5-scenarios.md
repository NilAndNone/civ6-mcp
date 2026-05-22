# Codex HL Phase 5 Regression Scenario Pool

Phase 5 把真实 confirmed failure 沉淀成 regression scenario pool，让后续验证不依赖单个 `test 1` 跑分。

## 边界

- 只读已有 Phase 2 正式 failure 和被动 seed。
- 默认写 `validation/regression_scenarios/`，并在 episode 下写一份 `phase5/scenario_ingest.json`。
- 不启动 Civ6，不加载 save，不 replay。
- 新 scenario 默认 `runnable=false`，直到 replay harness 明确实现。

## 命令

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase5-scenarios --episode-id <episode_id>
```

可用 `--pool-root <path>` 指定 scenario pool。

## 产物

- `validation/regression_scenarios/regression_scenarios.jsonl`
- `validation/regression_scenarios/MANIFEST.json`
- `validation/regression_scenarios/scenario_pool.html`
- `episodes/<episode_id>/phase5/scenario_ingest.json`

## 验收

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m py_compile plugin/src/codex_hl/phase5/scenarios.py
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run pytest tests/test_phase4_5_governance.py -q
```

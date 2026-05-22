# Phase 5 Regression Scenario Pool

Phase 5 把真实 confirmed failure 沉淀成 regression scenario pool。当前 scenario
是被动登记，不 replay，不启动 Civ6。

## 输入

- `episodes/<episode_id>/phase2/failures.jsonl`
- `episodes/<episode_id>/phase2/regression_seeds.jsonl`

输入必须来自 Phase 2 apply 后的正式 failure。

## 处理过程

入口命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase5-scenarios --episode-id <episode_id>
```

Phase 5 会把 failure 转成 scenario，保留来源 episode、failure id、证据引用、
预期行为、失败行为和后续验收条件。

默认写入：

```text
validation/regression_scenarios/
```

## 输出

- `validation/regression_scenarios/regression_scenarios.jsonl`
- `validation/regression_scenarios/MANIFEST.json`
- `validation/regression_scenarios/scenario_pool.html`
- `episodes/<episode_id>/phase5/scenario_ingest.json`

## 验收看什么

- scenario 是否能回到正式 failure。
- 是否保留证据引用和 save refs。
- 是否标记为 passive / not runnable。
- 是否没有启动 Civ6、加载 save 或 replay。
- 是否能作为后续 governance 的多场景验证基础。

本地检查：

```bash
uv run pytest tests/test_phase4_5_governance.py -q
```

## 最容易错的地方

- 把 scenario 登记写成 replay 执行。
- 把没有正式确认的 candidate failure 纳入 scenario pool。
- 丢失 source episode 或 evidence refs，导致后续无法审计。

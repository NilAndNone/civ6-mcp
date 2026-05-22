# /civ6-phase5-scenarios

## 用途

把 Phase 2 正式 failure 登记到 regression scenario pool。

## 输入

- `--episode-id <episode_id>`：已有正式 failure 的 episode。
- `--pool-root <path>`：可选，指定 scenario pool 目录。

## 输出

默认写入：

```text
validation/regression_scenarios/
```

关键产物：

- `regression_scenarios.jsonl`
- `MANIFEST.json`
- `scenario_pool.html`
- `episodes/<episode_id>/phase5/scenario_ingest.json`

## 边界

- 只登记 scenario。
- scenario 默认 passive / not runnable。
- 不启动 Civ6。
- 不加载 save。
- 不 replay。
- 不生成资产 diff。

## 示例

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase5-scenarios --episode-id <episode_id>
```

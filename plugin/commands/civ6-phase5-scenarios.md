# /civ6-phase5-scenarios

把已有 Phase 2 正式 failure 沉淀到 Phase 5 regression scenario pool。

## 必读资产

- `prompt.default_boundary`
- `memory.low_trust_policy`
- `playbook.phase5_regression_scenarios`

## 调用

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase5-scenarios --episode-id <episode_id>
```

默认写入：

```text
validation/regression_scenarios/
```

可用 `--pool-root <path>` 指定 scenario pool。Phase 5 只登记 scenario，不 replay，不启动 Civ6；scenario 默认是 passive，直到后续 replay harness 明确实现后才可运行。

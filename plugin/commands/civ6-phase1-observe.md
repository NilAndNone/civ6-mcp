# /civ6-phase1-observe

运行 Codex HL Phase 1 观测。规则主体在 Phase 3 资产中。

## 必读资产

- `prompt.default_boundary`
- `memory.low_trust_policy`
- `playbook.phase1_observation`
- `tool_policy.phase1_run_and_evidence`

## 参数

- `save_name`：可选，默认 `test 1`。
- `turns`：可选，默认 `3`；短跑使用 `3` 到 `10`，已接受短跑后的 T50 使用 `50`。
- `episode_id`：可选，用于指定稳定 episode 名称。

## 调用

短跑：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
```

T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 50
```

交付时返回 episode id、中文人工报告、Agent 接手报告、Agent 审计报告、四类证据 PASS/FAIL 和阻塞项。

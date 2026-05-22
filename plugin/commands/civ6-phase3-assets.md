# /civ6-phase3-assets

校验 Phase 3 资产库、列出 active assets，或只读比较两个已记录 T50 episode 的主指标。

## 必读资产

- `prompt.default_boundary`
- `tool_policy.t50_metrics_review`
- `memory.low_trust_policy`

## 调用

校验资产库：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --check
```

列出 active assets：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --list
```

只读比较 T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --compare-t50 --baseline-episode <baseline_id> --candidate-episode <candidate_id>
```

比较结果只能作为候选证据，不会生成资产 diff、merge、rollback、replay 或 Civ6 运行。

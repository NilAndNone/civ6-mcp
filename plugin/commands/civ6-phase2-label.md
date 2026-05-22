# /civ6-phase2-label

对已有 Phase 1 episode 做 Phase 2 v1 离线失败标注。规则主体在 Phase 3 资产中。

## 必读资产

- `prompt.default_boundary`
- `memory.low_trust_policy`
- `playbook.phase2_offline_labeling`
- `tool_policy.phase2_confirmation_apply`

## 生成候选

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id>
```

产物位于 `episodes/<episode_id>/phase2/`，其中 `phase2_review.html` 是人工审阅入口，`candidates.jsonl` 只是候选。

## 人工确认和 apply

确认文件默认位于：

```text
episodes/<episode_id>/phase2/confirmation/confirmation.jsonl
```

显式 apply：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\phase2\confirmation\confirmation.jsonl
```

Phase 2 输出仍是失败证据和被动 seed，不是资产修改或重跑命令。

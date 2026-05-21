# /civ6-phase2-label

对已有 Phase 1 episode 做 Phase 2 v1 离线失败标注。

默认命令只生成候选失败和静态审计页，不启动 Civ6，不推进回合，不写正式 failure 或 regression seed。

## 生成候选

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id>
```

产物位于：

```text
episodes/<episode_id>/phase2/
```

其中 `phase2_review.html` 是人工审阅入口，`candidates.jsonl` 只是候选，不是正式失败。

## 人工确认

人工确认文件默认写在：

```text
episodes/<episode_id>/phase2/confirmation/confirmation.jsonl
```

每行格式：

```json
{"candidate_id":"cand_...","action":"accept","modified_fields":{},"reviewer":"human","reviewer_note":"...","reviewed_at":"..."}
```

`action` 只能是 `accept`、`reject` 或 `modify`。`modify` 必须把修改内容写进 `modified_fields`。

也可以显式启动受限本地标注器：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --label
```

标注器只绑定 `127.0.0.1`，只写 `phase2/confirmation/`，不会写正式 failure 或 seed。

## 显式 apply

只有人工确认后才运行：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\phase2\confirmation\confirmation.jsonl
```

apply 会校验 Phase 1 输入 hash 未变、candidate id 存在、证据引用可回到 Phase 1，并拒绝 replay、rerun、资产修改或策略修复字段。通过后生成：

- `failures.jsonl`
- `regression_seeds.jsonl`
- `phase2_summary.md`
- `phase2_summary.json`
- 更新后的 `phase2_review.html`

短跑 planning failure 会强制带 `local_episode_fragment` caveat。Phase 2 v1 的 seed 是被动回归输入，不是当前阶段的重跑命令。

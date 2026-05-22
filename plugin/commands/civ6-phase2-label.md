# /civ6-phase2-label

## 用途

对已有 Phase 1 episode 做离线失败标注。先生成候选 failure，人工确认后才
写正式 failure 和被动 regression seed。

## 输入

- `--episode-id <episode_id>`：已有 Phase 1 episode。
- `--apply-confirmation <path>`：可选，人工确认文件路径。

确认文件默认位置：

```text
episodes/<episode_id>/phase2/confirmation/confirmation.jsonl
```

## 输出

候选阶段：

- `phase2/candidates.jsonl`
- `phase2/candidate_summary.json`
- `phase2/phase2_review.html`

apply 后：

- `phase2/failures.jsonl`
- `phase2/regression_seeds.jsonl`
- `phase2/phase2_summary.md`
- `phase2/phase2_summary.json`
- `phase2/confirmation_audit.jsonl`

## 边界

- 不启动 Civ6。
- 不加载 save。
- 不推进 turn。
- 不写资产修改。
- 不生成 rerun、replay 或策略补丁。
- 人工确认前不写正式 failure。

## 示例

生成候选：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id>
```

显式 apply：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\phase2\confirmation\confirmation.jsonl
```

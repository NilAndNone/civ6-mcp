# /civ6-review

## 用途

对已有 observation episode 做离线失败标注。先生成候选 failure，人工确认后才
写正式 failure 和被动 regression seed。

## 输入

- `--episode-id <episode_id>`：已有 observation episode。
- `--apply-confirmation <path>`：可选，人工确认文件路径。

确认文件默认位置：

```text
episodes/<episode_id>/review/confirmation/confirmation.jsonl
```

## 输出

候选阶段：

- `review/candidates.jsonl`
- `review/candidate_summary.json`
- `review/review.html`

apply 后：

- `review/failures.jsonl`
- `review/regression_seeds.jsonl`
- `review/review_summary.md`
- `review/review_summary.json`
- `review/confirmation_audit.jsonl`

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
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-review --episode-id <episode_id>
```

显式 apply：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-review --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\review\confirmation\confirmation.jsonl
```

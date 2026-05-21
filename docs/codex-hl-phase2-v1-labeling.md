# Codex HL Phase 2 v1 离线失败标注

这个文档记录当前实现的 Phase 2 v1 开发契约。它不修改路线图；路线图仍以 `docs/codex-hl-evolution-roadmap.md` 为准。

Phase 2 v1 只做离线标注闭环：

```text
offline episode evidence
-> candidate failure
-> human confirmation
-> formal failure
-> passive regression seed
```

## 边界

- 只读取已有 Phase 1 episode，不启动 Civ6，不加载 save，不推进 turn。
- 只写 `episodes/<episode_id>/phase2/`。
- 候选失败只能来自 Phase 1 证据、短跑 evidence、report pack、decision atoms、工具日志、状态快照和存档索引。
- LLM 或启发式只能生成 candidate，不能直接写正式 failure。
- 正式 failure 和 regression seed 只能由显式 `--apply-confirmation <file>` 生成。
- v1 强制 `1 confirmed failure -> 1 passive regression seed`。

正式输出禁止包含：

```text
suggested_fix
asset_diff
prompt_update
playbook_change
tool_policy_change
memory_update
strategy_patch
replay_target
rerun_command
arena_run
replay_from_save
auto_rerun
```

## 命令

生成候选和审计页：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id>
```

启动受限 localhost 标注器：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --label
```

显式 apply：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\phase2\confirmation\confirmation.jsonl
```

## 产物

候选生成阶段：

- `phase2/MANIFEST.json`
- `phase2/phase2_review.html`
- `phase2/candidates.jsonl`
- `phase2/analyzer_runs/<run_id>/provenance.json`
- `phase2/analyzer_runs/<run_id>/input_manifest.json`
- `phase2/analyzer_runs/<run_id>/prompt.txt`
- `phase2/analyzer_runs/<run_id>/llm_request.json`
- `phase2/analyzer_runs/<run_id>/llm_response.raw.json`
- `phase2/analyzer_runs/<run_id>/candidate_failures.jsonl`
- `phase2/analyzer_runs/<run_id>/dedupe_manifest.json`

apply 阶段额外生成：

- `phase2/confirmation/confirmation.jsonl`
- `phase2/confirmation/confirmation_audit.jsonl`
- `phase2/failures.jsonl`
- `phase2/regression_seeds.jsonl`
- `phase2/phase2_summary.md`
- `phase2/phase2_summary.json`

没有人工 confirmation 时，不得有正式 `failures.jsonl` 或 `regression_seeds.jsonl`。

## 短跑 caveat

所有 `short_validation` 的 planning failure 都必须限制为 `local_episode_fragment`，并带：

```yaml
not_a_long_horizon_conclusion: true
not_evidence_for_asset_change: true
requires_t50_or_multi_episode_followup: true
```

如果 confidence 为 `high`，`phase2_review.html` 和 summary 必须红字显示：

```text
该 high confidence 只适用于 T10/T20 local_episode_fragment；不是长期战略结论，不是资产修改证据，需要 T50 或 multi-episode follow-up。
```

## 本地检查

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m py_compile plugin/src/codex_hl/phase2/labeler.py
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run pytest tests/test_phase2_labeler.py -q
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run pytest tests -q
```

真实试点应使用已有真实 Phase 1 episode。候选生成可以自动运行；正式 apply 必须等人工确认文件存在后再运行。

# Codex HL Phase 3 资产体系

这个文档记录当前 Phase 3 v1 的实现契约。它不修改路线图；路线图仍以
`docs/codex-hl-evolution-roadmap.md` 为准。

## 边界

Phase 3 v1 只建立资产体系：

- 管理 `prompt`、`playbook`、`tool_policy`、低信任 `memory` 的版本、来源、风险、适用范围和回滚路径。
- 记录首批资产迁移的来源和人工判断。
- 只读比较已有 T50 episode 的主指标，结果只能作为候选证据。

Phase 3 v1 不做这些事：

- 不生成候选资产改动。
- 不写 `asset_diff`。
- 不自动 merge 或 rollback。
- 不启动 Civ6、不加载 save、不 replay。
- 不从单个 `test 1` 结果宣称通用变强。

## 资产目录

资产库位于：

```text
plugin/assets/codex_hl/phase3/
```

核心文件：

- `catalog.json`：登记 active assets。
- `change_ledger.jsonl`：记录首批迁移来源和判断。
- `assets/*.md`：资产正文。

每个 catalog asset 必须包含固定字段：

```text
asset_id, asset_type, version, content_path, content_sha256,
source_refs, applicability, risk_level, rollback_path,
capability_dimensions, status
```

## 命令

校验资产库：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --check
```

列出 active assets：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --list
```

比较两个已记录 T50 episode：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --compare-t50 --baseline-episode <baseline_id> --candidate-episode <candidate_id>
```

## Phase 1 快照

新的 Phase 1 episode 会写：

```text
episodes/<episode_id>/assets_snapshot/active_assets.json
```

旧 episode 在 report-only 模式下不会被补写历史资产快照；缺失时只在报告/manifest
里记录 gap。

## 本地检查

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m py_compile plugin/src/codex_hl/phase3/assets.py
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase3-assets --check
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run pytest tests/test_phase3_assets.py -q
```

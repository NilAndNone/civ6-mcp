# Phase 3 资产体系

Phase 3 管理 prompt、playbook、tool policy 和低信任 memory 的版本化资产。
它还可以只读比较已有 T50 episode 的主指标。

Phase 3 不生成候选资产改动，不启动 Civ6，不 replay，不 merge，不 rollback。

## 输入

资产库：

```text
plugin/assets/codex_hl/phase3/
```

关键文件：

- `catalog.json`
- `change_ledger.jsonl`
- `assets/*.md`

只读比较 T50 时，还需要两个已有 episode。

## 处理过程

校验资产库：

```bash
uv run codex-hl-civ6-phase3-assets --check
```

列出 active assets：

```bash
uv run codex-hl-civ6-phase3-assets --list
```

比较两个 T50 episode：

```bash
uv run codex-hl-civ6-phase3-assets --compare-t50 --baseline-episode <baseline_id> --candidate-episode <candidate_id>
```

比较只读取已记录状态。它不会触发资产 diff、merge、rollback、replay 或 Civ6
运行。

## 输出

资产校验输出：

- 资产数量。
- active asset 数量。
- asset id 列表。
- hash 和字段校验结果。

T50 比较输出：

- baseline episode。
- candidate episode。
- final state 来源。
- 城市数、科技、市政、科学、文化等主指标 delta。

## 验收看什么

- `catalog.json` 字段是否完整。
- `content_sha256` 是否和正文一致。
- `change_ledger.jsonl` 是否存在并可解析。
- active assets 是否能被安装后的 Codex 找到。
- T50 比较是否只基于已有 evidence。

本地检查：

```bash
uv run codex-hl-civ6-phase3-assets --check
uv run pytest tests/test_phase3_assets.py -q
```

## 最容易错的地方

- 把单个 T50 变好写成通用策略改进。
- 在 Phase 3 生成资产 diff。
- 在 Phase 3 触发 Civ6 运行。
- 只改资产正文，不更新 catalog hash。

`v0.0.2` 才会验证 playbook 是否真正驱动 runner 并改善 T50 主指标。

# Phase 3 — Legacy Baseline Split + Orchestrator Migration

## TL;DR

把 legacy runner 明确降级为 baseline/deprecated，把 runs/orchestrator 改成显式 runner 选择，不能再默认裸跑旧规则主线。


## 目标

- `/civ6-observe` 保留为 legacy-baseline / report rebuild / compatibility。
- `/civ6-observe-live` 成为新主线入口。
- `codex-hl-civ6-runs --execute` 必须显式选择 `--runner live|legacy-baseline`。
- 默认不能绕过 live gate 进行真实游戏推进。

## 任务

1. CLI 新增 runner 参数：

```text
codex-hl-civ6-runs --runner live
codex-hl-civ6-runs --runner legacy-baseline
```

2. 修改 orchestrator：
   - 无 `--runner` 且 `--execute` 时拒绝。
   - `live` 调 live episode path。
   - `legacy-baseline` 只用于 baseline 对照。
3. 文档更新：
   - `plugin/AGENTS.md`
   - `plugin/commands/civ6-runs.md`
   - `docs/live_refactor/legacy_baseline.md`
4. 报告中明确标记 runner kind。

## 测试

```text
tests/test_orchestrator_runner_selection.py
tests/test_legacy_baseline_deprecation.py
```

测试点：

- `--execute` 无 runner fail。
- `--runner legacy-baseline` 能跑旧命令但报告标 baseline。
- `--runner live` 不调用 old rules runner。
- Review/Strategy/Governance 仍能读旧 episode。

## 验收

PASS 条件：

- 旧 runner 不再是默认真实执行入口。
- legacy baseline 可复现实验，用于对比。
- live runner 不依赖旧 rules priority。

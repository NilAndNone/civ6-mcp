# Codex HL Civ6 插件使用入口

这个文件给安装插件后的 Codex 使用。

## 启动顺序

1. 先读 `assets/codex_hl/strategy/catalog.json`。
2. 按当前任务读取需要的 active asset。
3. 再读对应的 `commands/*.md`。
4. 最后运行命令。

常用 active asset：

- `strategy.prompt.default_boundary`
- `strategy.memory.low_trust`
- `strategy.playbook.observation`
- `strategy.tool_policy.observation_evidence`
- `strategy.playbook.failure_review`
- `strategy.tool_policy.review_confirmation`
- `strategy.tool_policy.t50_metrics_review`
- `strategy.playbook.candidate_improvements`
- `strategy.tool_policy.candidate_gate`
- `strategy.playbook.validation_scenarios`
- `strategy.tool_policy.governance_merge`

## 命令入口

基础观测与报告：

- `/civ6-observe --report-only`
- `/civ6-observe-live`
- `/civ6-load-test1`
- `/civ6-observe`（legacy-baseline / deprecated compatibility）
- `/civ6-debug`

离线资产与证据流程：

- `/civ6-review`
- `/civ6-strategy-assets`
- `/civ6-strategy-candidates`
- `/civ6-validation-scenarios`
- `/civ6-governance`

自动化编排待验入口：

- `/civ6-runs`（真实执行必须显式 `--runner live|legacy-baseline`）

## 边界

- 默认不要越过当前命令对应的职责边界。
- live 主线使用 `/civ6-observe-live`；不要把 legacy-baseline 当默认真实执行入口。
- Phase 3 不启用 fragment；不要调用或暴露 `register_live_fragment` / `execute_live_fragment`。
- 候选不是正式资产修改。
- Governance 默认只审计。
- `episodes/` 默认是本地产物，不提交。
- 如果入口文件和 strategy asset 不一致，以 strategy asset 为准。
- 如果 strategy asset 和 `docs/codex-hl-evolution-roadmap.md` 不一致，以路线图 Markdown 为准。

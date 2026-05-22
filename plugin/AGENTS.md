# Codex HL Civ6 插件使用入口

这个文件给安装插件后的 Codex 使用。

## 启动顺序

1. 先读 `assets/codex_hl/phase3/catalog.json`。
2. 按当前任务读取需要的 active asset。
3. 再读对应的 `commands/*.md`。
4. 最后运行命令。

常用 active asset：

- `prompt.default_boundary`
- `memory.low_trust_policy`
- `playbook.phase1_observation`
- `tool_policy.phase1_run_and_evidence`
- `playbook.phase2_offline_labeling`
- `tool_policy.phase2_confirmation_apply`
- `tool_policy.t50_metrics_review`
- `playbook.phase4_candidate_improvements`
- `tool_policy.phase4_candidate_gate`
- `playbook.phase5_regression_scenarios`
- `tool_policy.governance_auto_merge`

## 命令入口

基础观测与报告：

- `/civ6-phase1-observe`
- `/civ6-phase1-report`
- `/civ6-debug`

离线资产与证据流程：

- `/civ6-phase2-label`
- `/civ6-phase3-assets`
- `/civ6-phase4-candidates`
- `/civ6-phase5-scenarios`
- `/civ6-governance`

自动化编排待验入口：

- `/civ6-evolve`

## 边界

- 默认不要越过当前命令对应的阶段边界。
- 候选不是正式资产修改。
- Governance 默认只审计。
- `episodes/` 默认是本地产物，不提交。
- 如果入口文件和 Phase 3 资产不一致，以 Phase 3 资产为准。
- 如果 Phase 3 资产和 `docs/codex-hl-evolution-roadmap.md` 不一致，以路线图 Markdown 为准。

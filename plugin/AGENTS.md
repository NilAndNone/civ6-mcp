# Codex HL Civ6 插件使用入口

这个文件给安装插件后的 Codex 使用。规则主体已经迁入 Phase 3 资产库。

## 启动顺序

1. 先读 `assets/codex_hl/phase3/catalog.json`。
2. 对照当前任务读取需要的 active asset：
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
3. 再按 `commands/` 里的薄入口运行对应命令。

## 命令入口

- `/civ6-phase1-observe`：Phase 1 短跑或已验收后的单 episode T50 观测。
- `/civ6-phase1-report`：基于已有 episode 重建报告，不推进游戏。
- `/civ6-phase2-label`：对已有 Phase 1 episode 做离线候选标注和显式 confirmation apply。
- `/civ6-phase3-assets`：校验资产库、列出 active assets、只读比较 T50 指标。
- `/civ6-phase4-candidates`：从正式 failure 生成候选改进包，不改资产。
- `/civ6-phase5-scenarios`：把正式 failure 登记到 regression scenario pool，不 replay。
- `/civ6-governance`：审计、显式合并或回滚资产，默认 audit-only。
- `/civ6-evolve`：多局 T20/T50 自进化编排；默认只写 plan，显式 `--execute` 才启动 Civ6。
- `/civ6-debug`：受控连接测试和排障。

## 边界

如果入口文件和 Phase 3 资产内容不一致，以 Phase 3 资产为准；如果资产和
`docs/codex-hl-evolution-roadmap.md` 不一致，以路线图 Markdown 为准。

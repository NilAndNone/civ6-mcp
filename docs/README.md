# 开发文档

这里的文档只服务 `codex-hl-civ6` 的开发、设计和验收，不是插件安装后的使用说明。

## 当前主线文档

- [Codex HL Evolution Roadmap](codex-hl-evolution-roadmap.md)：路线图唯一权威来源。
- [Codex HL Evolution Roadmap HTML](codex-hl-evolution-roadmap.html)：路线图的人类审阅对照版本。
- [插件架构说明](plugin-architecture.md)：当前开发侧和插件使用侧如何隔离。
- [Phase 1 观测流程](codex-hl-phase1-observation.md)：当前 Phase 1 的开发和验收契约。
- [Phase 2 v1 离线失败标注](codex-hl-phase2-v1-labeling.md)：用户显式开启 Phase 2 后的候选失败、人工确认和被动 seed 契约。
- [Phase 3 资产体系](codex-hl-phase3-assets.md)：首批 prompt、playbook、tool policy、低信任 memory 的版本化管理和 T50 只读指标比较。
- [Phase 4 候选改进包](codex-hl-phase4-candidates.md)：从正式 failure 生成候选资产改进包，但不直接 merge。
- [Phase 5 Regression Scenario Pool](codex-hl-phase5-scenarios.md)：把真实 failure 沉淀成 passive regression scenarios。
- [L4/L5 资产治理](codex-hl-governance.md)：多场景 gate、显式 merge、rollback 和审计契约。

## 插件使用说明

插件安装后的使用说明放在：

- `plugin/AGENTS.md`
- `plugin/commands/`
- `plugin/skills/`

## 旧文档

旧 CivBench、网页、评测、开发日志、通用 MCP、研究和 Hotseat 文档都已归档到 `archive/legacy/docs/`。

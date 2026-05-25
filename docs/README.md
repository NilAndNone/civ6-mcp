# 开发文档入口

这里的文档服务 `codex-hl-civ6` 的开发、审批和验收。插件安装后的使用说明在
`plugin/` 下。

## 先读什么

- `v0.0.1-release.md`：第一个正式版本的审批说明。
- `v0.0.2-strategy-improvement.md`：策略改进验证目标和验收标准。
- `plugin-architecture.md`：当前仓库和插件如何分层。
- `codex-hl-evolution-roadmap.md`：长期路线图的唯一权威 Markdown。
- `codex-hl-evolution-roadmap.html`：路线图的人类审阅版，内容应与 Markdown 同步。

## 阶段文档

每份阶段文档都按同一逻辑写：输入是什么、怎么处理、输出什么、验收看什么、
哪一步最容易错。

- `codex-hl-phase1-observation.md`：真实 Civ6 观测、episode 证据和报告。
- `codex-hl-phase2-v1-labeling.md`：离线失败标注和人工确认。
- `codex-hl-phase3-assets.md`：版本化资产库和 T50 只读比较。
- `codex-hl-phase4-candidates.md`：从正式 failure 生成候选改进包。
- `codex-hl-phase5-scenarios.md`：把 failure 沉淀成被动回归场景池。
- `codex-hl-governance.md`：候选资产的审计、显式合并和回滚。

## 插件说明

- `../plugin/README.md`：插件使用总览。
- `../plugin/AGENTS.md`：安装后 Codex 先读的说明。
- `../plugin/commands/`：每个命令的用途、输入、输出和边界。
- `../plugin/skills/`：插件技能入口。

## 旧资料

旧 CivBench、网页、评测、开发日志、通用 MCP、研究和 Hotseat 文档都在
`../archive/legacy/`。不要让当前主线从这里导入代码或默认读取资料。

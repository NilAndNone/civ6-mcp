# codex-hl-civ6 开发说明

这个文件只约束本仓库的开发工作。安装插件后的 Civ6 使用说明在 `plugin/AGENTS.md`。

## 唯一权威来源

- `docs/codex-hl-evolution-roadmap.md` 是路线图的唯一权威来源。
- `docs/codex-hl-evolution-roadmap.html` 只是给人看的对照版本。
- 没有用户明确同意，不要改这两个路线图文件。
- 如果 Markdown 和 HTML 内容不一致，以 Markdown 为准，并把差异说出来。

## 仓库结构

- `plugin/` 是可以安装的 Codex 插件成品目录，里面包含运行代码、插件信息、命令、技能、Agent 配置、测试夹具和使用说明。
- `plugin/AGENTS.md` 是插件安装后给 Codex 看的使用说明。
- 根目录 `AGENTS.md`、`README.md` 和 `docs/` 只服务开发、设计和验收。
- `archive/legacy/` 存放旧 CivBench、网页、评测、开发日志、发布脚本、Hotseat 和通用 MCP 资产。它们不属于当前主线。

## 当前范围

默认主线仍然先保证 Phase 0/1；Phase 2+ 只有在用户明确开启时才做。

- Phase 0：统一术语、边界、资产清单和人工检查清单。
- Phase 1：真实 Civ6 观测、episode 证据、决策记录、存档关联和中文人工验收报告。
- Phase 2 v1：只读已有 Phase 1 episode，做离线候选失败、人工确认后的正式 failure 和被动 regression seed；不启动 Civ6，不推进回合，不改资产。
- Phase 3 v1：登记和校验 prompt、playbook、tool policy、低信任 memory 的版本化资产；只读比较已有 T50 指标，不生成候选资产改动。
- Phase 4：从正式 failure 生成候选改进包；不直接改资产，不启动 Civ6。
- Phase 5：把真实 failure 转成 regression scenario pool；默认 passive，不 replay。
- L4/L5：只在显式治理命令和 gate 全通过时合并资产；必须写 audit 和 rollback snapshot。
- 不要提前实现 Replay Arena、无 gate 自动学习或无审计资产修改，除非用户明确要求。

## 开发路由

- 改插件结构或打包时，先看 `plugin/.codex-plugin/plugin.json`、`plugin/AGENTS.md` 和 `plugin/commands/`。
- 改 Phase 1 流程时，先看 `docs/codex-hl-phase1-observation.md`，再看 `plugin/src/codex_hl/phase1/observer.py` 和相关测试。
- 改 Phase 2 离线标注时，先看 `docs/codex-hl-phase2-v1-labeling.md`，再看 `plugin/src/codex_hl/phase2/labeler.py` 和相关测试。
- 改 Phase 3 资产体系时，先看 `docs/codex-hl-phase3-assets.md`，再看 `plugin/assets/codex_hl/phase3/`、`plugin/src/codex_hl/phase3/assets.py` 和相关测试。
- 改 Phase 4 候选改进时，先看 `docs/codex-hl-phase4-candidates.md`，再看 `plugin/src/codex_hl/phase4/improvements.py` 和相关测试。
- 改 Phase 5 scenario pool 时，先看 `docs/codex-hl-phase5-scenarios.md`，再看 `plugin/src/codex_hl/phase5/scenarios.py` 和相关测试。
- 改 L4/L5 治理时，先看 `docs/codex-hl-governance.md`，再看 `plugin/src/codex_hl/governance/automation.py` 和相关测试。
- 改 Civ6 连接能力时，把行为收在 `plugin/src/civ6_connector/` 里，不要把底层连接细节写进根目录文档。
- 查旧 CivBench、网页或评测内容时，只从 `archive/legacy/` 读取；没有批准不要搬回主线。

## 归属和安全边界

- 用户拥有路线图和策略方向。
- Codex 负责实现、测试、验证脚本、插件打包和开发文档，除非用户缩小范围。
- 本仓库禁止使用 worktree，除非用户明确要求。
- 不要回滚不是你改的内容。
- `episodes/` 是本地运行产物，默认不要提交；除非用户点名要某个产物。

## 验证要求

交付前按相关阶段文档跑本地检查。Phase 1 看 `docs/codex-hl-phase1-observation.md`；Phase 2 看 `docs/codex-hl-phase2-v1-labeling.md`；Phase 3 看 `docs/codex-hl-phase3-assets.md`；Phase 4/5/L4 看对应文档和 `tests/test_phase4_5_governance.py`。

真正端到端验收仍然需要在 Windows Civ6 机器上，用插件跑一次真实 `test 1` 的 3 回合 Phase 1 短跑。

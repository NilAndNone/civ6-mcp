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

默认主线以职责模块划分。Strategy 是核心产物层；自进化体系负责从 evidence 到 review、candidate、validation、governance 的闭环。

- Evidence：真实 Civ6 观测、episode 证据、决策记录、存档关联和中文人工验收报告。
- Review：只读已有 evidence episode，做离线候选失败、人工确认后的正式 failure 和被动 regression seed；不启动 Civ6，不推进回合，不改资产。
- Strategy：登记和校验 prompt、playbook、tool policy、低信任 memory 的版本化资产，并从正式 failure 生成候选策略包；候选不直接改资产。
- Validation：把真实 failure 转成 regression scenario pool；默认 passive，不 replay。
- Governance：只在显式治理命令和 gate 全通过时合并资产；必须写 audit 和 rollback snapshot。
- Runs：编排自进化和多局验证，但不能绕过 Strategy/Validation/Governance gate。
- 不要提前实现 Replay Arena、无 gate 自动学习或无审计资产修改，除非用户明确要求。

## 开发路由

- 改插件结构或打包时，先看 `plugin/.codex-plugin/plugin.json`、`plugin/AGENTS.md` 和 `plugin/commands/`。
- 改 Evidence 流程时，先看 `docs/codex-hl-observation.md`，再看 `plugin/src/codex_hl/evidence/observation.py` 和相关测试。
- 改 Review 离线标注时，先看 `docs/codex-hl-review.md`，再看 `plugin/src/codex_hl/review/failure_labeling.py` 和相关测试。
- 改 Strategy 资产体系时，先看 `docs/codex-hl-strategy-assets.md`，再看 `plugin/assets/codex_hl/strategy/`、`plugin/src/codex_hl/strategy/registry.py` 和相关测试。
- 改 Strategy 候选改进时，先看 `docs/codex-hl-strategy-candidates.md`，再看 `plugin/src/codex_hl/strategy/candidates.py` 和相关测试。
- 改 Validation scenario pool 时，先看 `docs/codex-hl-validation-scenarios.md`，再看 `plugin/src/codex_hl/validation/scenarios.py` 和相关测试。
- 改 Governance 治理时，先看 `docs/codex-hl-governance.md`，再看 `plugin/src/codex_hl/governance/gates.py` 和相关测试。
- 改 Civ6 连接能力时，把行为收在 `plugin/src/civ6_connector/` 里，不要把底层连接细节写进根目录文档。
- 查旧 CivBench、网页或评测内容时，只从 `archive/legacy/` 读取；没有批准不要搬回主线。

## 归属和安全边界

- 用户拥有路线图和策略方向。
- Codex 负责实现、测试、验证脚本、插件打包和开发文档，除非用户缩小范围。
- 本仓库禁止使用 worktree，除非用户明确要求。
- 不要回滚不是你改的内容。
- `episodes/` 是本地运行产物，默认不要提交；除非用户点名要某个产物。

## 验证要求

交付前按相关职责模块文档跑本地检查。Evidence 看 `docs/codex-hl-observation.md`；Review 看 `docs/codex-hl-review.md`；Strategy 看 `docs/codex-hl-strategy-assets.md` 和 `docs/codex-hl-strategy-candidates.md`；Validation/Governance 看对应文档和 `tests/test_strategy_validation_governance.py`。

真正端到端验收仍然需要在 Windows Civ6 机器上，用插件跑一次真实 `test 1` 的 3 回合 observation 短跑。

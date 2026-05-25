# codex-hl-civ6 架构说明

当前仓库分成两层：开发层和插件层。

## 开发层

开发层在仓库根目录，负责说明、测试和发布：

- `README.md`：项目总入口。
- `AGENTS.md`：本仓库开发约束和任务路由。
- `docs/`：路线图、阶段说明、版本审批和架构说明。
- `tests/`：本地验收测试。
- `validation/`：回归场景池等验证资产。
- `archive/legacy/`：旧资料归档，不参与当前主线。

开发层回答的是：这个项目要解决什么问题、当前版本承诺什么、怎么判断可以发布。

## 插件层

`plugin/` 是可安装的 Codex 插件成品目录：

- `.codex-plugin/plugin.json`：插件元信息和版本。
- `README.md`：插件使用总览。
- `AGENTS.md`：插件安装后 Codex 先读的说明。
- `commands/`：用户可见命令入口。
- `skills/`：技能入口，目前主要是 Phase 1 观测。
- `assets/codex_hl/phase3/`：版本化 prompt、playbook、tool policy 和 memory。
- `src/codex_hl/`：Phase 1-5、governance、evolution 的流程层。
- `src/civ6_connector/`：Civ6 底层连接层。
- `fixtures/`：测试夹具。

插件层回答的是：安装后 Codex 怎么使用这些能力。

## 运行链路

真实游戏只由 `civ6_connector` 接触。它负责连接 FireTuner、执行 Lua 查询、
读取游戏状态、发出动作、推进回合和做排障。

`codex_hl` 不直接碰底层连接细节。它负责把底层能力组织成阶段流程：

1. Phase 1 记录真实 episode 和报告。
2. Phase 2 只读已有 episode，生成候选失败，人工确认后写正式 failure。
3. Phase 3 校验资产库，只读比较已有 T50。
4. Phase 4 从正式 failure 生成候选改进包。
5. Phase 5 把正式 failure 登记成被动回归场景。
6. Governance 做候选合并审计、显式合并和回滚。
7. Evolution 编排多局运行和后续阶段，并可把候选 playbook 作为只读运行时输入验证。

## 产物链路

一条完整证据链大致是：

```text
真实 Civ6 对局
  -> episodes/<episode_id>/ Phase 1 证据和报告
  -> phase2/ candidates, failures, regression seeds
  -> phase4/ candidate packages
  -> validation/regression_scenarios/
  -> governance audits
```

每一步都要能回到前一步的证据，不能只留下结论。

## 边界

- `v0.0.2` 已证明候选 playbook 可以进入 Phase 1 runner 决策路径并改善 T50 主指标。
- `/civ6-evolve` 可以运行 baseline/candidate T50；`/civ6-v002-acceptance` 只读生成验收报告。
- `episodes/` 是本地运行产物，默认不提交。
- `archive/legacy/` 只能作为旧资料查看，不是当前运行路径。

# codex-hl-civ6 插件架构

本仓库现在分成两层：开发层和插件层。

## 开发层

仓库根目录用于开发和验证插件：

- `AGENTS.md` 定义开发时的职责边界和任务路由。
- `docs/` 保存路线图、架构说明和验收契约。
- `tests/` 验证插件结构、连接器行为、报告契约、Phase 2 离线标注、Phase 3 资产库、Phase 4/5 和 L4/L5 治理。
- `archive/legacy/` 保存旧资产，避免混入当前主线。

## 插件层

`plugin/` 是可安装、可复制的插件目录：

- `.codex-plugin/plugin.json` 暴露插件信息。
- `AGENTS.md` 告诉 Codex 安装插件后怎么使用。
- `commands/` 只保留批准过的用户入口：Phase 1 observe/report、Phase 2 label、Phase 3 assets、Phase 4 candidates、Phase 5 scenarios、governance、evolve 和 debug。
- `skills/` 保存 Phase 1 观测工作流的入口；规则主体逐步沉淀到 Phase 3 资产。
- `assets/codex_hl/phase3/` 保存 prompt、playbook、tool policy 和低信任 memory 的版本化 catalog、账本和正文。
- `src/codex_hl/` 保存 Phase 0/1 逻辑、显式启用的 Phase 2/3/4/5 和 L4/L5 治理逻辑。
- `src/civ6_connector/` 保存最底层 Civ6 连接层。
- `fixtures/` 保存报告契约测试需要的夹具。

## 运行链路

Codex 安装插件后，先读插件内的说明和 Phase 3 active asset，再通过少量命令进入对应流程。Phase 1 只通过 `civ6_connector` 接触 Civ6。

短跑结束后必须生成 episode 和报告，并在 T50 之前暂停，等待人工验收。

Phase 2 默认只生成候选和审计页；正式 failure/seed 必须由人工 confirmation 和显式 apply 生成。

Phase 3 只校验资产库、列出 active assets、只读比较已有 T50 指标。比较结果只能作为候选证据，不能触发 asset diff、merge、rollback、replay 或 Civ6 运行。

Phase 4 只生成候选改进包，不直接修改资产。Phase 5 只登记 regression scenarios，不 replay。L4/L5 governance 默认 audit-only；只有显式 `--allow-merge` 且多场景 gate 全部通过时才写资产，并必须保留 rollback snapshot。

`/civ6-evolve` 是多局 T20/T50 编排层。默认只写 plan manifest；显式 `--execute` 才启动 Civ6。它可以生成 validation report 和 governance 审计，但不会在缺少 `--candidate-runtime-applied` 的情况下自动合并，因为当前 Phase 1 runner 仍以静态 blocker-resolution 优先级为主，资产候选是否影响运行时策略必须单独证明。

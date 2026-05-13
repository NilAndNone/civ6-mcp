# codex-hl-civ6 插件架构

本仓库现在分成两层：开发层和插件层。

## 开发层

仓库根目录用于开发和验证插件：

- `AGENTS.md` 定义开发时的职责边界和任务路由。
- `docs/` 保存路线图、架构说明和验收契约。
- `tests/` 验证插件结构、连接器行为和报告契约。
- `archive/legacy/` 保存旧资产，避免混入当前主线。

## 插件层

`plugin/` 是可安装、可复制的插件目录：

- `.codex-plugin/plugin.json` 暴露插件信息。
- `AGENTS.md` 告诉 Codex 安装插件后怎么使用。
- `commands/` 只保留批准过的用户入口。
- `skills/` 保存 Phase 1 观测工作流。
- `src/codex_hl/` 保存 Phase 0/1 逻辑。
- `src/civ6_connector/` 保存最底层 Civ6 连接层。
- `fixtures/` 保存报告契约测试需要的夹具。

## 运行链路

Codex 安装插件后，先读插件内的说明，再通过少量命令进入 Phase 1 流程。Phase 1 只通过 `civ6_connector` 接触 Civ6。

短跑结束后必须生成 episode 和报告，并在 T50 之前暂停，等待人工验收。

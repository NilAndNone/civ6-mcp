# codex-hl-civ6

这个仓库用于开发 `codex-hl-civ6` Codex 插件。

插件的目标是让 Codex 以“先观测、再验收”的方式玩 Civilization VI。当前主线先保证 Phase 0/1：统一术语，跑真实 Civ6 短跑，记录证据，生成中文人工报告，然后在进入更长流程前停下来。用户明确要求 Phase 2 时，仓库也提供 v1 离线标注闭环：把已有 Phase 1 episode 转成候选失败、人工确认后的正式 failure，以及被动 regression seed。

## 当前主线目录

- `plugin/`：可安装的 Codex 插件成品目录。
- `plugin/AGENTS.md`：插件安装后给 Codex 看的 Civ6 使用说明。
- `plugin/src/codex_hl/`：Phase 0/1 主线逻辑，以及显式启用的 Phase 2 v1 离线标注逻辑。
- `plugin/src/civ6_connector/`：最底层 Civ6 连接器。
- `docs/`：开发路线图、架构说明和验收约束。
- `tests/`：插件结构、连接器和报告契约测试。
- `archive/legacy/`：旧 CivBench、网页、评测、开发日志、发布脚本、Hotseat 和通用 MCP 资产。

## 本地开发检查

首次进入仓库后：

```bash
uv sync
uv run pytest tests -q
```

常用检查命令：

```bash
uv run python -m py_compile plugin/src/codex_hl/phase1/observer.py plugin/src/civ6_connector/server.py
uv run python -m py_compile plugin/src/codex_hl/phase2/labeler.py
uv run pytest tests/test_plugin_structure.py tests/test_phase1_human_report_contract.py -q
uv run pytest tests -q
```

## 插件使用入口

安装后的插件只暴露少量强命令：

- `/civ6-phase1-observe`：跑 Phase 1 观测短跑。
- `/civ6-phase1-report`：基于已有 episode 重新生成报告。
- `/civ6-phase2-label`：对已有 episode 做 Phase 2 v1 离线候选标注和显式 confirmation apply。
- `/civ6-debug`：做受控连接测试和排障。

对应说明在 `plugin/commands/`。

## 完整验收

本地测试只能证明插件结构、导入和报告契约没坏。真正验收还需要在 Windows Civ6 机器上完成：

1. 在 Civ6 机器上安装或使用 `plugin/`。
2. 加载真实 `test 1` 单人存档。
3. 跑 3 回合 Phase 1 观测短跑。
4. 确认生成 episode、四类证据、中文人工 HTML 报告和 Agent 接手报告。
5. 在人工验收前停止，不能自动继续到 T50。

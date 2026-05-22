# codex-hl-civ6

这个仓库用于开发 `codex-hl-civ6` Codex 插件。

插件的目标是让 Codex 以“先观测、再验收”的方式玩 Civilization VI。当前主线先保证 Phase 0/1：统一术语，跑真实 Civ6 短跑，记录证据，生成中文人工报告，然后在进入更长流程前停下来。用户明确要求后，仓库还提供 Phase 2 离线标注、Phase 3 资产体系、Phase 4 候选改进包、Phase 5 regression scenario pool、L4/L5 受控资产治理，以及多局 T20/T50 自进化编排入口。

## 当前主线目录

- `plugin/`：可安装的 Codex 插件成品目录。
- `plugin/AGENTS.md`：插件安装后给 Codex 看的 Civ6 使用说明。
- `plugin/assets/codex_hl/phase3/`：Phase 3+ 资产 catalog、变更账本和资产正文。
- `plugin/src/codex_hl/`：Phase 0/1 主线逻辑，以及显式启用的 Phase 2/3/4/5、L4/L5 治理和自进化编排逻辑。
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
uv run python -m py_compile plugin/src/codex_hl/phase3/assets.py
uv run python -m py_compile plugin/src/codex_hl/phase4/improvements.py plugin/src/codex_hl/phase5/scenarios.py plugin/src/codex_hl/governance/automation.py
uv run python -m py_compile plugin/src/codex_hl/evolution/orchestrator.py
uv run codex-hl-civ6-phase3-assets --check
uv run pytest tests/test_plugin_structure.py tests/test_phase1_human_report_contract.py -q
uv run pytest tests -q
```

## 插件使用入口

安装后的插件只暴露少量强命令：

- `/civ6-phase1-observe`：跑 Phase 1 观测短跑。
- `/civ6-phase1-report`：基于已有 episode 重新生成报告。
- `/civ6-phase2-label`：对已有 episode 做 Phase 2 v1 离线候选标注和显式 confirmation apply。
- `/civ6-phase3-assets`：校验资产库、列出 active assets、只读比较 T50 指标。
- `/civ6-phase4-candidates`：从正式 failure 生成候选改进包。
- `/civ6-phase5-scenarios`：把正式 failure 登记到 regression scenario pool。
- `/civ6-governance`：执行 audit-only evaluation、显式合并和回滚。
- `/civ6-evolve`：多局 T20/T50 自进化编排，默认只写 plan；显式 `--execute` 才启动 Civ6。
- `/civ6-debug`：做受控连接测试和排障。

对应说明在 `plugin/commands/`。

## 完整验收

本地测试只能证明插件结构、导入和报告契约没坏。真正验收还需要在 Windows Civ6 机器上完成：

1. 在 Civ6 机器上安装或使用 `plugin/`。
2. 加载真实 `test 1` 单人存档。
3. 跑 3 回合 Phase 1 观测短跑。
4. 确认生成 episode、四类证据、中文人工 HTML 报告和 Agent 接手报告。
5. 在人工验收前停止，不能自动继续到 T50。

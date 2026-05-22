# Codex HL Civ6 插件

这个目录是可安装的 Codex 插件成品。

它默认服务 Phase 0/1 Civ6 观测工作；用户明确要求后，也提供 Phase 2+ 的离线失败标注、资产体系、候选改进、scenario pool、受控资产治理和多局 T20/T50 自进化编排入口：

- Phase 0：统一术语、边界和检查清单。
- Phase 1：加载真实 `test 1` 存档，跑短回合，记录证据，生成中文人工报告，并在 T50 前暂停。
- Phase 2 v1：只读已有 Phase 1 episode，生成候选失败；人工确认后生成正式 failure 和被动 regression seed。
- Phase 3 v1：管理 prompt、playbook、tool policy 和低信任 memory 的版本化资产，并只读比较已有 T50 指标。
- Phase 4：从正式 failure 生成候选改进包，不直接改资产。
- Phase 5：把真实 failure 登记到 regression scenario pool，默认 passive，不 replay。
- L4/L5：在多场景 gate 通过后显式合并资产，并保留 rollback audit。
- Evolution v1：编排多把 T20/T50、Phase 2 候选、可选自动 confirmation、Phase 4/5 产物、validation report 和 governance 审计；默认不自动合并。

仓库根目录用于开发这个插件。插件安装后的使用说明在本目录的 `AGENTS.md`。

## 资产入口

Phase 3 资产库位于：

```text
assets/codex_hl/phase3/
```

安装后的 Codex 先读 `AGENTS.md`，再按任务需要读取 active asset。Phase 3 只登记和校验资产，不生成候选资产改动，不 merge，不 rollback，也不启动 Civ6。

## 命令

- `/civ6-phase1-observe`：运行 Phase 1 短跑或已验收后的 T50 观测。
- `/civ6-phase1-report`：基于已有 episode 重新生成报告。
- `/civ6-phase2-label`：对已有 episode 做离线候选标注和显式 confirmation apply。
- `/civ6-phase3-assets`：校验资产库、列出 active assets、只读比较 T50 指标。
- `/civ6-phase4-candidates`：从正式 failure 生成候选改进包。
- `/civ6-phase5-scenarios`：把正式 failure 登记到 regression scenario pool。
- `/civ6-governance`：执行 audit-only evaluation、显式合并和回滚。
- `/civ6-evolve`：多局 T20/T50 自进化编排，默认 plan-only；显式 `--execute` 才启动 Civ6。
- `/civ6-debug`：做受控连接测试和排障。

默认不要运行带 `--allow-merge` 的治理命令；只有用户明确要求、validation report 满足 gate、并能接受自动写资产时才执行。
`/civ6-evolve --allow-merge` 还要求 `--candidate-runtime-applied`，避免把没有运行时策略生效证据的 T50 报告用于自动合并。

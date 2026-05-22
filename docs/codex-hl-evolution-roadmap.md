# Codex HL Evolution Roadmap

这份 Markdown 是长期路线图的唯一权威来源。HTML 文件只是人类审阅版，内容
应该与这里保持一致。

## 一句话结论

`codex-hl-civ6` 的长期目标，是让 Codex 在真实 Civilization VI 对局里形成
可审计的改进闭环：先完整记录，再标失败，再形成候选资产，再用多场景验证，
最后在 gate 通过时受控合并和回滚。

当前正式版本是 `v0.0.1`。它冻结入口、边界和本地验收。下一版
`v0.0.2` 才验证 playbook 驱动的策略改进。

## 不做什么

- 不把单个 `test 1` 结果当成通用策略结论。
- 不让 Phase 1 判断策略好坏。
- 不让候选 failure 直接变成资产改动。
- 不跳过人工确认和 governance gate。
- 不从 `archive/legacy/` 恢复旧主线，除非用户明确批准。

## 阶段总览

| 阶段 | 目标 | 当前版本含义 |
| --- | --- | --- |
| Phase 0 | 统一词汇和边界 | v0.0.1 文档冻结这些定义 |
| Phase 1 | 完整观测真实对局 | v0.0.1 正式入口 |
| Phase 2 | 从真实证据里标失败 | v0.0.1 正式入口，人工确认后才写正式 failure |
| Phase 3 | 建立版本化资产体系 | v0.0.1 正式入口，只读比较 T50 |
| Phase 4 | 形成候选改进包 | v0.0.1 正式入口，候选不直接改资产 |
| Phase 5 | 沉淀 regression scenario pool | v0.0.1 正式入口，默认 passive |
| Governance | 审计、显式合并和回滚 | v0.0.1 正式入口，默认 audit-only |
| Evolution | 多局编排 | v0.0.1 正式入口，策略改进留到 v0.0.2 验证 |

## 三条主线

### 记录系统

记录系统回答：发生了什么，证据在哪里，结论能不能回到原始事实。

- Phase 1 落盘工具调用、状态快照、决策记录和存档索引。
- Phase 2 的失败必须引用 Phase 1 证据。
- Phase 4 的候选必须引用正式 failure。
- Phase 5 的 scenario 必须能回到 source episode 和 source failure。
- Governance audit 必须记录 gate、结论和 rollback snapshot。

### 资产系统

资产系统回答：哪些 prompt、playbook、tool policy 和 memory 正在生效，它们
从哪里来，能不能回滚。

- Phase 3 catalog 记录资产 id、类型、版本、hash、来源、风险、适用范围和状态。
- Phase 4 只生成候选资产包。
- Governance 才能在 gate 全过且显式允许时写资产。
- `v0.0.2` 会让候选 playbook 直接进入 runner 决策路径。

### 验证系统

验证系统回答：改动是否真的更好，有没有退化。

第一版主指标使用 T50，因为 T50 足够快，适合早期比较：

- 城市数。
- 科技完成数和当前研究。
- 市政完成数和当前市政。
- 科学产出。
- 文化产出。

单个 episode 只能提供候选证据。正式策略改进验证至少需要多局对比。

## v0.0.1 和 v0.0.2 的关系

`v0.0.1` 是正式地基：

- 文档结构清楚。
- 入口和命令清楚。
- 每个阶段的输入、处理、输出和边界清楚。
- 本地检查能通过。

`v0.0.2` 是策略改进验证：

- 自动从正式 failure 生成候选 playbook。
- runner 直接读取候选 playbook。
- Windows 真机跑 `5 baseline T50 + 5 candidate T50`。
- 用 T50 主指标判断 candidate 是否改进。

详细目标见 `docs/v0.0.2-strategy-improvement.md`。

## 当前优先级

当前优先级是完成 `v0.0.1` 正式版本整理和审批。审批通过后再打
`v0.0.1` 标签。

之后进入 `v0.0.2`，重点不再是文档定版，而是证明 playbook 驱动的策略改进。

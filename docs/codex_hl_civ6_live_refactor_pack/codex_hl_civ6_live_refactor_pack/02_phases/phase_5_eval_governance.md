# Phase 5 — Evaluation / Governance / Strategy Feedback

## TL;DR

用 T20/T50、多 episode、legacy baseline 和 regression scenarios 证明 live agent 是否真的更强，而不是只看 T3 管道成功。


## 目标

- 建立 live vs legacy-baseline 对照。
- 建立 objective metrics。
- 建立 failure taxonomy。
- 建立 candidate strategy 回流 gate。

## 核心指标

| 指标 | 说明 |
|---|---|
| turn_reached | 是否稳定到目标回合 |
| unplanned_mutation_count | live strict 下必须为 0 |
| verifier_pass_rate | step verifier pass 比例 |
| recovery_count | 恢复次数，越少越好 |
| city_count_T50 | 扩张节奏 |
| science_yield_T50 / culture_yield_T50 | 基础发展 |
| completed_tech_count / civic_count | 路线推进 |
| era_score / golden_age_gap | 时代目标 |
| military_strength / barb_threats | 安全性 |
| stuck_turn_count | 卡 UI / blocker 次数 |
| invalid_plan_rate | plan schema/guard 拒绝率 |

## 对照设计

```text
same save: test 1
same turn budget: T20, T50
runners:
  - legacy-baseline
  - live-json-plan
  - live-json-plan+fragment(optional)
episodes per condition: >= 3 for smoke, >= 10 for meaningful trend
```

## 失败分类

- state representation gap
- invalid plan schema
- stale context
- args mismatch
- tool bug
- Civ6/FireTuner instability
- verifier too strict
- model strategic error
- recovery protocol failure
- evidence/export failure

## Governance gate

只有满足以下条件，才允许将高收益 plan 转成 strategy candidate：

- live strict unplanned mutation = 0；
- verifier evidence complete；
- 至少跨多个 episode 复现；
- 与 legacy baseline 有明确 objective delta；
- failure/reward attribution 不依赖 Codex 自评；
- Claude Code review 不标注架构绕过。

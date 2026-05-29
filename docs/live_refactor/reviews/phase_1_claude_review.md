# Phase 1 Claude Code Architecture Review

> 审查范围：仅 Phase 1 — ActionGateway Shadow Mode。
> 分支：`codex/live-codex-mcp-agent`。
> 审查输入：当前 `git diff HEAD` + 未跟踪新增文件；执行包 `01_architecture/*`、`02_phases/phase_1_action_gateway_shadow.md`、`04_tasks/acceptance_matrix.md`、`03_agent_prompts/claude_arch_review_prompt.md`；仓库 `docs/live_refactor/phase_1_gateway_shadow.md`。
> 本审查为独立复核：已自行读取规范、全部实现 diff，并实跑测试取证；只写本文件，未修改任何代码或资产。
> 未把无关未跟踪文件 `docs/strategy-core-architecture.{html,png}` 纳入 Phase 1 结论（仅在提交排除项中提醒）。

ARCHITECTURE_PASS: true

BLOCKERS:
- （无）逐条核对 review prompt 的“必须 false”红线，全部为反面，详见下方 `## Blockers`。

NON_BLOCKING_ISSUES:
- **单一 env 变量同时驱动两个执行面**：`gateway_mode_from_env()`（`context.py:31-40`，读 `CODEX_HL_CIV6_LIVE_GATEWAY_MODE` / 兼容别名）被 `action_gateway_for_mcp`（`context.py:78-85`）和 `action_gateway_for_episode`（`context.py:53-67`）共用。一旦全局设 `live_strict`，observation legacy runner 也会进入 strict，而它经 `EpisodeRecorder.tool_call` 构造的 `ActionRequest` 从不带 `plan_id/step_id`（`observation.py:1045-1054`），其全部 L2+ 将被拒，baseline 直接瘫痪。**strict 非默认 → 不违反 Phase 1 验收**，但这是易踩脚枪：legacy baseline runner 在 Phase 3 runner split 前架构上无法提供 plan，应被钉死为 compat/shadow，不应随全局 strict 漂移。
- **透明 mutating recovery 仍在且绕过 gateway**：`server.py:472` 连接丢失后 `_logged` 内 `game_launcher.restart_and_load(save)`；`end_turn()` 的 hang recovery 与 World Congress 重复 blocker auto-submit；以及 observation runner 中别名化的 `end_turn_retry`（`observation.py:7153-7155`）、`end_turn_after_diplomacy`（`observation.py:7344-7345`）等仍直呼 `gs.end_turn`，因名不在 `ACTION_REGISTRY` 而**跳过 gateway**。即便 shadow，ledger 也并非全量 mutation 记录。迁移清单已诚实列出 → **Phase 1 可接受**，但属 Phase 2 启用 strict 真入口前的硬前置（见 Required Fixes #1）。
- **Phase 1 strict 只校验 plan/step “是否存在”**：`_strict_rejection_reason`（`gateway.py:82-101`）仅检查 `episode_id+plan_id+step_id` 非空，**无** step `ARMED`、args matcher、context_hash stale、duplicate/cross-turn step 防护（文档诚实声明）。这是 Phase 2 必交付项；strict 现状是脚手架级守卫，不可误当真守卫。
- **ledger 每次调用重建 + 全量回读 seq**：`_gateway_tool_call`（`server.py:508-541`）与 `tool_call`（`observation.py:1040-1044`）每次新建 `EpisodeLedger`，`_read_last_seq()`（`ledger.py:76-91`）每次回读整份 JSONL/store → 长 episode O(n²)，shadow 文件无界增长；且无单写者锁，并发 gateway 调用可能写出重复 `seq`（`event_id` 因 uuid 后缀仍唯一）。shadow 阶段非致命，Phase 2 应集中为单例 ledger / DB `max(seq)` / 落实 schema 的 `UNIQUE(episode_id, seq)`。
- **崩溃一致性事件粒度最小**：只写 `ACTION_STARTED/FINISHED/FAILED/REJECTED`（`gateway.py:103-186`），缺 `PRE_STATE_CAPTURED/CHECKPOINT_CREATED/POST_STATE_CAPTURED/STEP_VERIFIED`，`pre/post_state_hash` 恒为 `None`。可诊断“started 无 finished”，但未达 `episode_ledger_schema.md` 的 per-step 事件序列；属 Phase 2。
- **source-of-truth 形态**：episode 路径下 ledger 经 `EpisodeStore.append_jsonl(..., kind="live_events")` + `export_artifact()`（`ledger.py:145-148`）——DB 优先、JSONL 为导出，方向正确；但 MCP 无 store 时仅写 JSONL、无 DB。Phase 1 shadow 可接受；Phase 2 需按 schema 落 `live_events/live_plans/live_steps/...` 真实表，且 finalization 不得反向从 raw “导入”事实。
- **observation strict 拒绝时 success 语义不一致**：strict 下 gateway 拒绝时 `result = "Error: ..."`，但 recorder 随后无条件 `row["success"] = True`（`observation.py:1056-1065`）。仅在 strict（非默认）下出现；strict 转正前应对齐为 `success=False` 或显式 `rejected`。
- **MCP 路径 `str(result)` 早强转**：`_gateway_tool_call` 末尾返回 `str(action_result.result)`（`server.py:508-541`）。当前 3 个被包工具均返回 `str`（与工具 `-> str` 契约一致），无害幂等；但相对“原样返回”是更激进的类型强转，后续迁入返回非 str 的工具需注意。
- **ledger 行同写 `level` 与 `mutation_level`**（`ledger.py:125-126`）：同值冗余、向前兼容用，无害。
- **无关未跟踪产物**：`docs/strategy-core-architecture.{html,png}` 应在 Phase 1 提交时排除。

REQUIRED_FIXES_BEFORE_NEXT_PHASE:
- **（Phase 2 红线）在 `LIVE_STRICT` 成为真入口前，把透明 mutating recovery 拆成显式 L4 recovery/turn-completion plan step 并经 gateway 路由**：`server.py:472` 连接丢失 `restart_and_load`、`end_turn()` hang recovery、WC 重复 blocker auto-submit、以及别名化 `end_turn_retry/end_turn_after_diplomacy`（`observation.py:7153-7155,7344-7345`）。否则 Phase 2 一旦让 strict 上线，就直接命中 prompt 明列的 `ARCHITECTURE_PASS:false` 红线“live strict 下仍有透明 mutating recovery”。
- **统一别名 mutation 的 ledger 覆盖**：把 `end_turn_retry`/`end_turn_after_diplomacy`/`respond_to_*_for_end_turn` 等别名归一到 registry 名（或显式登记），使 shadow ledger 成为全量 mutation 记录；建议加“别名化 mutating 调用绕过 gateway 即失败”的守卫测试。
- **解耦 legacy_runner 与 MCP 的 gateway mode**（或把 legacy_runner 钉死为 compat/shadow）：使“为 live MCP 开 strict”不会静默打断 legacy baseline runner（baseline 在 Phase 3 runner split 前无法提供 plan）。
- **在 strict 中实现真正的状态机守卫**：step `ARMED`、args matcher、context_hash stale、duplicate/cross-turn step 拒绝（acceptance matrix 的 Phase 2 项）。
- **落实真实 `live_events`（及 plans/steps/checkpoints/branches）DB 表为 source of truth**，JSONL 仅作导出；补单写者 / seq 完整性；finalization 不得从 raw 反向导入事实。
- **提交卫生**：排除无关的 `docs/strategy-core-architecture.{html,png}`；确认 `episodes/` shadow 产物不入提交（已核验 `git check-ignore` 命中 `episodes/...`）。

---

## Blockers

无。逐条核对 review prompt 的“必须 false”红线，全部为反面：

1. **新增 game-state mutation 绕过 ActionGateway**：未触发。Phase 1 **不新增任何 mutation**，只把已存在调用包进 gateway；新模块 `gateway/context/ledger/verifier` 自身不调用任何 `gs.*` mutation，只执行传入的 `fn`（`gateway.py:144-146`）。无新绕过点。
2. **Phase 0–3 引入 mutating fragment 主路径**：未触发。`live/` 目录无 `plan_store/state_machine/fragment/lifecycle` 文件；server.py diff 未新增任何 `@mcp.tool` 或 `start_live_*/submit_turn_*/arm_plan_*/execute_live_*` 入口（已 grep 核验 0 命中）。
3. **live strict 下仍有透明 mutating recovery**：**Phase 1 未触发**（详见末节独立判定）。gateway 自身零 recovery：异常仅记 `ACTION_FAILED` 并原样 `raise`（`gateway.py:147-160`）；既有透明 recovery 是 Phase 1 未触碰的 legacy 路径，且 strict 在 Phase 1 是非默认、最小、脚手架级检查，未声称“安全 live 入口”。**列为 Phase 2 硬前置**。
4. **Codex 自评作为 outcome authority**：未触发。`StubVerifier.verify()` 恒返回 `INCONCLUSIVE`（`verifier.py:22-40`），显式声明不把 Codex rationale / 工具文本提升为权威；gateway 只记录 `verifier_status`，从不据其判“成功/高收益”。
5. **无法防 duplicate step / stale plan**：非 Phase 1 红线。acceptance matrix 明确把 stale/duplicate/args mismatch 划归 Phase 2；Phase 1 strict 不声称防护这些（文档诚实声明）。
6. **旧 runner 被删除导致 baseline 不可用**：未触发。diff 仅新增 + 极小重排改动（server.py、observation.py 均无删除函数），**0 文件删除、未 archive legacy runner**。

## Non-blocking Issues

（完整清单见顶部 `NON_BLOCKING_ISSUES`；下面补关键证据。）

### 是否“只是表面 MCP guard”
不是。guard 已下沉为统一执行网关并双面接入：
- **MCP 面**（`server.py`）：`set_research`（L2，`server.py:1955-1965`）、`set_city_production`（L3，`server.py:1892-1901`）、`unit_action`（按子动作 L2/L3，`server.py:1838-1843`）三类真实 mutating callable 交给 `ActionGateway.execute()`（`_gateway_tool_call`，`server.py:508-541`）。
- **legacy_runner 面**（`observation.py:1038-1060`）：`EpisodeRecorder.tool_call` 对**所有** `name in ACTION_REGISTRY` 的调用构造 `source="legacy_runner"` 走 gateway——覆盖面实际比 MCP 面更广，正面回应 `action_gateway_design.md` 的“旧 runner 必须可被统一记录、不能只在 MCP 层加表面 guard”。主路径 `unit_action(move→L3)`、`end_turn(L4)` 已被该机制捕获（`observation.py:6044-6056,7129`）。

### mutation 分类合理性
`classify_action`（`actions.py:484-505`）arg 敏感：`unit_action` 的 `skip/fortify/heal/...`→L2、`move/attack/found_city/...`→L3（`actions.py:26-47`）；`is_game_mutation_or_higher()`（`mutation_levels.py:27-33`）正确把 L2-L5 视为 game mutation，L0/L1 免 plan。与 `mutation_levels.md` 一致。`run_lua` 经 `_classify_raw_lua` 动态升 L4/L5（`actions.py:465-481`）。

### 分类覆盖率有源码级护栏（正面）
Phase 0 inventory 测试把分类钉在真实源码上：`test_non_readonly_mcp_tools_are_registered`（从 `server.py` 发现所有非 readonly MCP 工具，未登记即失败）、`test_unit_and_city_action_cases_are_fully_classified`（未分类子动作即失败）、`test_observation_direct_mutations_are_flagged_for_future_gateway`（直呼 mutation 必须标记待接管）。新增未分类 mutating 工具会被 CI 拦下。

### 两个 ledger 不重复计账（正面）
observation runner 经 `recorder.tool_call(...)` 直呼**进程内** `gs.*`（如 `observation.py:6044-6056`），不走 server.py 的 MCP `_gateway_tool_call`；故 runner 面（`source=legacy_runner`，写 episode ledger）与 MCP 面（`source=mcp`，写 `_live_shadow_mcp` ledger）是按 source 区分的独立记录，正常 observation 跑不会重复计账。

## Architecture Compliance

| Area | PASS/FAIL | Notes |
|---|---|---|
| Phase boundary | PASS | 无 Phase 2 越界：`live/` 无 plan store / 状态机 / fragment executor / live 入口；server.py 未加 `@mcp.tool`；0 删除、未 archive legacy；`verifier.py` 为 stub；`LIVE_STRICT` 存在但非默认。 |
| ActionGateway | PASS | 唯一统一执行入口落地：MCP 3 类（set_research/set_city_production/unit_action）+ legacy_runner 全 registry 接入。非表面 guard；gateway 自身不引入新 mutation、不做 recovery。 |
| Mutation classification | PASS | L0–L5 与 `mutation_levels.md` 一致；arg 敏感子动作分级正确；`is_game_mutation_or_higher` 边界正确（L0/L1 免 plan）；分类覆盖率有 inventory 测试护栏。 |
| State machine | N/A (Phase 2) | Phase 1 strict 仅“plan/step 存在性”最小校验（`gateway.py:82-101`）；无 ARMED/dup/stale/args matcher（文档诚实声明）。无越界实现。 |
| Ledger/source of truth | PASS (Phase 1 范围) | append-only（`ledger.py:150-153` 以 `"a"` 追加、seq 单调）；记录 source/tool/args/level/plan_id/step_id/context_hash/unplanned_mutation/verifier_status；episode 路径 DB 优先 + JSONL 导出。完整 DB schema、别名/边界全量覆盖属 Phase 2。 |
| Verifier independence | PASS | stub 恒 `INCONCLUSIVE`（`verifier.py:22-40`），无 Codex 自评权威，无 outcome authority。 |
| Legacy compatibility | PASS | 默认 `LEGACY_COMPAT`（`context.py:31-40`），不阻断；shadow 无 plan 仍执行并标 `unplanned_mutation=true`；observation trio **112 passed**，`/civ6-observe` 行为不变。 |
| Tests | PASS | 实跑：gateway `test_live_action_gateway.py`(6) + `test_live_gateway_shadow_mode.py`(1) = **7 passed**；registry+inventory(`-k`) 合计 **16 passed**；legacy `test_observation_turn_limits/report_contract/evidence_store` **112 passed**；`py_compile` PASS。覆盖：compat/shadow 放行+记账、strict 拒 L2+ 无 plan 且不执行、strict 放行 L0/L1、strict 放行带 plan/step、legacy_runner 经 shadow gateway 且 `source=legacy_runner`。 |

## Required Fixes Before Next Phase

见顶部 `REQUIRED_FIXES_BEFORE_NEXT_PHASE`。要点：Phase 2 启用 strict 真入口前，必须先 (1) 拆透明 recovery 为显式 L4 plan step 并经 gateway；(2) 统一别名 mutation 的 ledger 覆盖；(3) 解耦 legacy/MCP gateway mode；(4) 补状态机守卫（ARMED/dup/stale/args matcher）；(5) 落 DB source-of-truth；(6) 提交排除无关产物。

## Suggested Follow-ups

- 加“已登记 mutating MCP 工具未接入 gateway 即失败”/“别名化 mutating 调用绕过 gateway 即失败”的守卫测试，防覆盖率与 ledger 全量性静默回退。
- 把 `_gateway_tool_call` 的 `str(result)` 改为原样透传或显式契约，避免未来迁入非 str 工具时行为漂移。
- 对齐 observation strict 拒绝时的 `success` 语义（拒绝记 `success=False` 或显式 `rejected`）。
- 扩大 MCP 面 gateway 覆盖到迁移清单其余 L2/L3，优先不可逆 L2（pantheon/dedication/envoy）与 L3 trade/diplomacy。
- 给 `phase_1_gateway_shadow.md` 迁移清单加 regen/钉死测试（类比 Phase 0 inventory 的 regen-diff），防 doc 与实现漂移。
- gateway enforce 阶段对不可逆 L2 与 L4 加 pre-checkpoint。

---

## “是否构成 Phase 1 blocker” —— 透明 recovery 与 strict 的独立判定

**结论：Phase 1 不构成 blocker；列为 Phase 2 启用 strict 真入口前的硬性 Required-Fix。**

### 证据
- gateway 自身**零 recovery**：`execute()` 捕获异常后只追加 `ACTION_FAILED` 并 `raise`（`gateway.py:147-160`），不做 restart/load/retry。Phase 1 因此既未新增、也未删除透明 recovery。
- 既有透明 recovery（`server.py:472` 连接丢失 `restart_and_load`、`end_turn` hang recovery、WC auto-submit）与别名化 `end_turn_retry/end_turn_after_diplomacy`（`observation.py:7153-7155,7344-7345`）是 Phase 1 **未触碰**的 legacy 路径，且未经 gateway——`phase_1_gateway_shadow.md` 已诚实列入迁移/遗留清单。
- `LIVE_STRICT` 在 Phase 1 被显式定义为“可用于工程测试，但不是默认入口”，且仅做最小 plan/step 存在性校验——它**没有**声称是完整/安全的 live 路径。

### 判定理由（对齐 acceptance + prompt 红线）
1. prompt 红线“live strict 下仍有透明 mutating recovery”的语义是“一个对外宣称 strict/安全的模式仍偷偷做透明 mutating recovery”。Phase 1 的 strict 是脚手架级、非默认、文档明确不完整，不构成这种“虚假安全保证”。
2. Phase 1 自身验收（`02_phases/phase_1_action_gateway_shadow.md` + acceptance matrix）只要求：≥3 类 mutating action 经 gateway、旧 runner 行为不变、ledger 可见 source、shadow 下无 plan 的 L2+ 被标红。recovery 拆分、状态机守卫明确划归 Phase 2/3。本 diff 全部满足前者，未越界做后者。
3. 真正危险出现在 **Phase 2 让 strict 成为真入口**之时——届时若 recovery 仍透明、ledger 仍漏别名 mutation，就直接命中红线。故在此**前置**给出强约束。

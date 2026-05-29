# Phase 0 Claude Code Architecture Review

> 审查范围：仅 Phase 0 — Mutation Inventory。
> 分支：`codex/live-codex-mcp-agent`。
> 审查输入：当前 diff、执行包 `01_architecture/*`、`02_phases/phase_0_mutation_inventory.md`、`04_tasks/acceptance_matrix.md`。
> 本审查只写本文件，未修改任何代码或资产。

ARCHITECTURE_PASS: true

BLOCKERS:
- （无）

NON_BLOCKING_ISSUES:
- 既有 strategy asset hash drift（`strategy.prompt.default_boundary`：catalog `c68b…a507` vs 源资产 `44fa…aafe`）导致 acceptance 通用检查里 1 个测试为红。**非 Phase 0 引入**，详见下文判定。
- `run_lua` 动态分级用 regex 探测“写类 API”+ `ingame→L4` 降级，是弱信号启发式；Phase 0 仅作元数据可接受，但未来 gateway 不能把它当成强制边界。
- `discover_game_state_methods` 对不在手工表 `GAME_STATE_METHOD_LEVELS` 中的方法一律记为 L0，没有“漏登记的 mutating 方法”守卫测试。
- observation.py 直接调用扫描器是前缀敏感的（`gs.` / `conn.` / `game_launcher.`），别名引用可能漏扫；完整性最终要靠 Phase 1 runtime shadow，而非静态扫描。
- `get_religion_beliefs` / `get_dedications` / `get_gp_advisor` 实为只读，仅因缺 `readOnlyHint` 被登记成 L1。是为不改 `server.py` 而做的取巧，doc 已诚实标注。
- 生成的 `phase_0_inventory.md` 未被任何测试钉死到 `render_markdown_inventory()` 输出，手改会漂移。
- 两个未跟踪、与 Phase 0 无关的产物（`docs/strategy-core-architecture.html/.png`）存在于工作区，不应混入 Phase 0 提交。

REQUIRED_FIXES_BEFORE_NEXT_PHASE:
- 在 Phase 1 依赖“绿色基线”证明 shadow mode 不改旧行为之前，修复 strategy asset hash drift：把 `catalog.json` 中 `strategy.prompt.default_boundary.content_sha256` 重新生成为与源资产一致（或回退源资产），并重新同步已安装的 `.venv` 副本。**此修复不属于 Phase 0 代码、不阻断 Phase 0 验收**，但必须在 Phase 1 之前完成，否则 acceptance 通用检查命令始终为红，会掩盖后续回归。

---

## Blockers

无。Phase 0 满足审查 prompt 中全部“必须 false”红线的反面：

- 未新增任何绕过未来 ActionGateway 的 game-state mutation（Phase 0 不引入任何新的 mutation 路径，纯元数据）。
- 未引入 mutating Python fragment 主路径。
- 未引入 live strict 下的透明 mutating recovery（Phase 0 根本无执行层）。
- 无 Codex 自评作为 outcome authority（无 verifier）。
- 不涉及 duplicate step / stale plan 防护（状态机属 Phase 2）。
- 未删除/归档 legacy runner（diff 0 删除）。

## Non-blocking Issues

### 1. 既有 strategy asset hash drift（独立判定见下节）
acceptance `04_tasks/acceptance_matrix.md` 的“通用检查”第二条命令当前为 `111 passed, 1 failed`。该红测试与 Phase 0 无关，但因为它正是被文档化的 gate 命令，留红会侵蚀 Phase 1 的基线。

### 2. `run_lua` 动态分级是启发式
`plugin/src/codex_hl/live/actions.py:458-505`：
- `_RAW_LUA_WRITE_RE` 用正则匹配 `SetResearchingTech`、`UnitManager` 等“写类”符号 → L5；否则 `context=="ingame"` → L4；否则默认 L5。
- 正则写探测极易被绕过（拼接字符串、未列出的 manager / 操作）。作为 Phase 0 的分类标签没问题，但 **Phase 4+ 的 gateway 绝不能用正则当强制边界**，应走运行时白名单 / 沙箱。
- 语义上略反直觉：`gamecore` 只读默认 L5，而 `ingame` 反而降到 L4。保守（偏高）方向无害，但建议在 gateway 真正 enforce 时复核。

### 3. GameState mutating 方法完整性没有漏登记守卫
`plugin/src/codex_hl/live/inventory.py:203-221` 对任何不在 `GAME_STATE_METHOD_LEVELS` 中的方法记为 `L0`。测试 `test_registered_l2_plus_game_state_methods_have_method_classification` 只校验“registry 引用到的方法被分级”，**不校验“所有 mutating GameState 方法都已登记”**。因此一个既未被任何 registered MCP tool 引用、又不在手工表里的 mutating 方法会被静默记为 L0。Phase 0 的目标之一是“证明团队知道所有能改游戏状态的路径”，这一条留了完整性缺口。实际暴露面较低（这类方法等于在两个主入口都不可达），故非阻断，建议 Phase 1 加守卫测试。

### 4. observation 直接调用扫描是前缀敏感的
`inventory.py:224-236` 的 `_classify_observation_path` 依赖 `gs.` / `gs.conn.` / `conn.` / `game_launcher.` 前缀来识别 GameState 方法。若 observation.py 用其他局部别名持有 `gs`（如 `state = self.gs; state.move_unit(...)`），GameState 方法分类会漏扫（boundary 符号有 bare-symbol 兜底，GameState 方法没有）。这与目标架构一致——真正的安全网是 Phase 1 的 runtime shadow recording，而非静态扫描；建议在文档里明确“静态清单是下限，不是完整保证”。

### 5. 三个只读工具被登记为 L1
`get_religion_beliefs` / `get_dedications` / `get_gp_advisor` 实为 read，仅因 `server.py` 未给它们 `readOnlyHint` 才被登记为 L1，用以让“新增非 readOnly 工具未登记即失败”的测试保持严格而不必改 `server.py`。`phase_0_inventory.md` 的 Legacy Risks 已诚实记录。建议后续 phase 给这三个工具补 `readOnlyHint` 后重分类为 L0。

### 6. 生成文档未被钉死
`render_markdown_inventory()`（`inventory.py:344-391`）能生成 `phase_0_inventory.md`，但没有测试断言“仓库里的 doc == 生成输出”。手工编辑会让 doc 与代码漂移。建议加一个 regen-diff 测试。

### 7. 部分 L2 其实不可逆/高杠杆
`choose_pantheon` / `choose_dedication` / `send_envoy` 被分为 L2（与 `01_architecture/mutation_levels.md` 的作者建议一致），但它们实际不可逆且影响深远。分级与执行包一致，不算错；提示 gateway 在 enforce 时可能想对这些 L2 也加 pre-checkpoint。

### 8. 无关未跟踪产物
`docs/strategy-core-architecture.html` 与 `docs/strategy-core-architecture.png` 为未跟踪文件，与 Phase 0 无关；提交 Phase 0 时应排除。

## Architecture Compliance

| Area | PASS/FAIL | Notes |
|---|---|---|
| Phase boundary | PASS | `git diff HEAD --stat`：7 个新文件，+1415，**0 删除，0 修改既有文件**。全仓库（排除 `docs/live_refactor/*` 设计文档）grep 无 `start_live_episode` / `submit_turn_plan` / `execute_live_fragment` / `execute_mutating_action` / `civ6-observe-live`，**未引入 live 入口、fragment executor、live lifecycle 工具**。未 archive/删除 legacy runner。符合 phase_0 “禁止”清单。 |
| ActionGateway | PASS (N/A 实现) | Phase 0 不实现 gateway（属 Phase 1）。关键：未引入任何**新**的 mutation 路径绕过未来 gateway。`codex_hl.live` 仅被自身与测试 import，**主路径（server.py / observation.py / orchestrator）无任何 import**，`classify_action` 纯返回元数据、不执行、不路由、不阻断。doc 显式声明“descriptive only”。 |
| Mutation classification | PASS | L0–L5 与 `mutation_levels.md` 一致；L2/L3/L4/L5 划分合理（end_turn/save/load/restart/dismiss_popup=L4，submit_congress=L4 而 queue_wc_votes=L3，run_lua=L5）。arg 敏感分类正确处理 `unit_action`/`city_action` 子动作、`propose_trade` test 预览(→L1)、`run_lua` context。MCP 工具覆盖由 `test_non_readonly_mcp_tools_are_registered` 强制。见 Non-blocking #2/#3/#7 的边角。 |
| State machine | N/A (Phase 2) | Phase 0 不交付状态机。`ActionSpec` 已预留 `checkpoint_policy` 字段供未来使用。无越界实现。 |
| Ledger/source of truth | N/A (Phase 1+) | Phase 0 不触碰 episode/ledger。inventory doc 是可由 `render_markdown_inventory()` 重生成的静态视图，未反向成为权威。见 Non-blocking #6。 |
| Verifier independence | N/A (Phase 1+) | 无 verifier、无 Codex 自评、无 outcome authority。无违规。 |
| Legacy compatibility | PASS | Phase 0 修改 0 个既有文件，`/civ6-observe` 行为逐字节不变。observation.py 仍保有 12 处直接 `gs.(move_unit|end_turn|found_city|set_research)` 调用（grep 确认），即“绕过点真实存在且未被改动”——正是 inventory 的前提。Review/Strategy/Governance 读旧 episode 的能力不受影响。 |
| Tests | PASS | py_compile PASS（Hermes 独立复跑）；新 9 个测试全绿（registry + inventory，纯静态 AST 分析，不连游戏、不 mutate）。observation trio `111 passed, 1 failed`，唯一红为既有 strategy asset hash drift，**与 Phase 0 无关**（见下节）。 |

## Required Fixes Before Next Phase

1. **恢复绿色基线（owner：strategy-asset 维护者，非 Phase 0 代码）**：在 Phase 1 ActionGateway shadow 工作开始前，修复 strategy asset hash drift——重生成 `plugin/assets/codex_hl/strategy/catalog.json` 中 `strategy.prompt.default_boundary.content_sha256`（或回退源资产 `assets/prompt-default-boundary.md`），并重新同步 `.venv` 安装副本。理由：Phase 1 验收要求“shadow mode 不改变旧行为”，其证明依赖 acceptance 通用检查命令为全绿；若该命令长期 1 红，将无法可靠区分“Phase 1 引入的回归”与“既有红”。

## Suggested Follow-ups

- 加“漏登记 mutating GameState 方法即失败”的守卫测试（堵 Non-blocking #3 的完整性缺口）。
- 加 regen-diff 测试，把 `phase_0_inventory.md` 钉死到 `render_markdown_inventory()` 输出（Non-blocking #6）。
- 后续 phase 给 `get_religion_beliefs`/`get_dedications`/`get_gp_advisor` 补 `readOnlyHint` 并重分类 L0（Non-blocking #5）。
- Phase 4+ gateway 对 `run_lua` 用运行时白名单/沙箱而非正则做强制边界；把 `_RAW_LUA_WRITE_RE` 与 `ingame→L4` 降级降级为“仅提示”（Non-blocking #2）。
- gateway enforce 时考虑对不可逆 L2（pantheon/dedication/envoy）也加 pre-checkpoint（Non-blocking #7）。
- 可将 `ACTION_REGISTRY` 暴露为只读映射（`MappingProxyType`），防止下游误改（次要）。
- Phase 0 提交排除无关未跟踪产物 `docs/strategy-core-architecture.{html,png}`（Non-blocking #8）。

---

## 既有 strategy asset hash mismatch 是否为 Phase 0 blocker —— 独立判定

**结论：不是 Phase 0 blocker；但列为 Required-Before-Next-Phase。**

### 证据（本人独立核验，非仅采信 Hermes 复跑）

- `git diff HEAD --stat`：本 diff 仅新增 7 个文件、+1415 行、**0 删除、0 处修改既有文件**。`plugin/assets/codex_hl/strategy/`（catalog.json 与资产）完全未被 Phase 0 触碰。
- 实测哈希：
  - catalog 记录 `strategy.prompt.default_boundary.content_sha256 = c68b…a507`（`plugin/assets/codex_hl/strategy/catalog.json:11`）。
  - `sha256sum` 源资产 `plugin/assets/codex_hl/strategy/assets/prompt-default-boundary.md` = `44fa…aafe`（≠ catalog）。
  - `sha256sum` 已安装副本 `.venv/.../assets/codex_hl/strategy/assets/prompt-default-boundary.md` = `c68b…a507`（= catalog）。
- 故根因为：**源资产被改过、但 catalog 哈希未重生成**（且 `.venv` 副本未重新同步，仍是旧内容）。这一漂移先于本分支的 Phase 0 工作即已存在。

### 依据 Phase 0 acceptance + legacy compatibility 的判定理由

1. **审查 prompt 的“必须 false”红线**全是架构性绕过（mutation 绕过 gateway、fragment 主路径、透明 recovery、Codex 自评权威、无法防 duplicate/stale、删除 legacy runner）。本失败一项都不属于。
2. **Phase 0 自身验收措辞是“旧测试不退化”**（regression）。退化 = Phase 0 让原本通过的测试变红。本失败发生在 Phase 0 从未触碰的资产/catalog 文件上，因此**不是 Phase 0 引入的退化**。
3. **legacy compatibility 维度**关注 `/civ6-observe` 不退化、Review/Strategy/Governance 仍能读旧 episode。本漂移是 strategy prompt 资产的打包完整性校验问题，既非 Phase 0 引入也未被其加重，且不影响读旧 episode。
4. **若因此判 Phase 0 false 反而是错误把关**：修复它需要改 strategy 资产 / catalog——这恰恰超出 “mutation inventory” 的 Phase 0 范围（Phase 0 明令“不改真实运行行为/不越界”）。Phase 0 的架构工作本身是干净、达标的。

### 为何仍要在下一阶段前修

被文档化的 acceptance 通用检查命令当前为红。Phase 1 的核心验收是“shadow mode 不改变旧行为”，其可信度建立在该命令全绿之上。留红会让 Phase 1 难以区分自身回归与既有红，故须在 Phase 1 之前由资产维护方修复，恢复绿色基线。

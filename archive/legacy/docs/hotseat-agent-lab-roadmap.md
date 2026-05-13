# Civ6 Hotseat Agent Lab Roadmap

这份文档是给 Codex 的执行策略合同。

目标不是“给 Codex 加攻略”，而是搭一个可验证、可复盘、可逐步变强的 **Civ6 Hotseat Agent Lab**。Codex 的职责有两层：

- **开发职责**：按本路线图落盘文档、脚本、Skill、MCP 工具、日志、测试和 eval。
- **执行职责**：在后续真实热座游戏中作为 Player 2 agent 运行，按身份验证、观察、计划、审批、执行、日志流程和用户对局。

用户负责这两份文档的内容：

- `docs/hotseat-agent-lab-roadmap.md`
- `AGENTS.md`

其余开发、运行、验证、修复、复盘都由 Codex 负责。Codex 不应把脚本、测试、工具实现、日志校验、运行验证等执行细节甩回给用户。

## TL;DR

- 真实目标是搭一个 **Civ6 Hotseat Agent Lab**：观察增强、知识检索、行动流程、评测闭环。
- 当前最小可验证流程：**现有 civ6-mcp → 热座 P2 身份验证 → 只读局势 → 输出计划 → 人类批准 → 执行一回合 → 记录日志**。
- 第一阶段先解决 **身份错乱、误操作 P1、没有日志、没有回归测试**。
- 后续增强顺序：**结构化日志 → Skill 流程 → MCP 信息补强 → 截图视觉 → 知识库 → 战报/攻略卡 → eval benchmark → 难度爬坡**。
- “击败 Xiaohan”不能直接工程化；必须先过 **中等 AI → 高难 AI → 神级 AI → 多局稳定性 → 受限公平热座**。
- 当前硬约束：Codex 最需要的不是更多文明百科，而是 **眼睛、纪律和复盘执行力**。策略知识必须在身份安全、日志和回归测试之后加入。

## 1. 需求重构

Codex 的任务描述应该包含 Goal、Context、Constraints、Done when。这里的 `/goal` 格式就是给 Codex 的执行合约，不允许自由发挥。

OpenAI 官方资料确认了 persisted `/goal` workflows、app-server API、model tools、runtime continuation、TUI create/pause/resume/clear 等能力。不要把中文营销帖里的“自动拆解直到完美”当规格文档。

这个项目拆成 6 层：

| 层 | 目标 | 解决的问题 | 优先级 |
| --- | --- | --- | ---: |
| Hotseat safety | Codex 只操作自己的 P2 | 防止它动 Xiaohan 的 P1 文明 | P0 |
| Observability | 全量记录每回合状态、工具调用、承诺、结果 | 失败后可以复盘，不靠猜 | P0 |
| Skill workflow | 固定开局、每回合、战时、结算流程 | 防止每回合像失忆一样重开脑子 | P1 |
| MCP info expansion | 提供更适合策略判断的 composite tools | 原始工具太碎，agent 会漏查 | P1 |
| Vision support | 截图/小地图/UI 状态补充 | 弥补 Sensorium Effect | P2 |
| KB + reports | 攻略、战报、用户偏好、失败案例可检索 | 让它有经验，不是每局从零发明轮子 | P2 |

`civ6-mcp` 已经有不错的底座：README 说明它能让 LLM agent 玩完整 Civ6，支持 Codex/Gemini/Claude 等 MCP client，并暴露 76 个覆盖单位、城市、地图、科研、市政、外交、贸易、政府、宗教、伟人、世界议会、胜利进度和生命周期的工具。`end_turn` 也会做 before/after snapshots。

但公开战报说明这个底座还没到强 AI 玩家。devlog 记录了多局失败，cross-game analysis 指出几个结构性弱点：信息不主动查就等于不存在、侦察不足、扩张失败、反思和行动断裂。

## 2. 总体项目形态

不要直接把所有增强糊进上游核心逻辑。优先用 repo 内新增目录和文档/脚本层逐步推进：

```text
civ6-mcp/
  src/civ_mcp/                    # 原 MCP server
  tests/                          # offline tests
  docs/

  .agents/skills/civ6-hotseat/
    SKILL.md
    references/
  docs/
    hotseat-agent-lab-roadmap.md
    hotseat-runbook.md
    tool-catalog.md
    benchmark-protocol.md
  knowledge/
    mechanics/
    strategy-cards/
    game-reports/
    xiaohan-notes/
  scripts/
    evals/
    kb/
    hotseat/
  logs/                           # gitignored
    runs/*.jsonl
```

Codex skills 是把 instructions、resources、optional scripts 打包成可复用能力。技能目录需要 `SKILL.md`，还可以带 `scripts/`、`references/`、`assets/`，Codex 会按需加载完整说明。

## 3. 阶段路线图

| 阶段 | 名称 | 目标 | 不做什么 | 验收 |
| ---: | --- | --- | --- | --- |
| 0 | Baseline | 不改代码，跑通 civ6-mcp + Codex + 单人局 | 不碰热座、不加功能 | `test_connection.py` 成功 |
| 1 | Hotseat MVP | Codex 在热座 P2 只读、验证身份、执行一回合 | 不加视觉/KB | 连续 5 个 P2 回合不误操作 |
| 2 | Logging | 结构化记录每回合状态、计划、动作、结果 | 不优化策略 | 生成可复盘 JSONL/Markdown |
| 3 | Skill v1 | 固化热座回合流程 | 不做复杂 planner | Codex 每回合按流程走 |
| 4 | MCP Info Pack | 增加 composite 状态工具 | 不改底层游戏规则 | 一次调用拿到策略仪表盘 |
| 5 | Vision v1 | 截图工具和视觉观察报告 | 不让 OCR 决策覆盖 API | 截图保存、可引用、可对比 |
| 6 | KB v1 | 本地知识库检索 | 不联网乱爬攻略 | `kb_search` 返回带来源的片段 |
| 7 | Strategy Cards | 攻略/战报结构化成策略卡 | 不塞长文进 prompt | 每回合可检索 3-5 张相关卡 |
| 8 | Eval Harness | 中等电脑 benchmark | 不以单局输赢为唯一指标 | 30/100 回合指标达标 |
| 9 | Difficulty Ramp | King/Emperor/Immortal/Deity | 不改公平约束 | 多 seed 统计 |
| 10 | Xiaohan Duel | 和 Xiaohan 热座对战 | 不读取隐藏信息、不读档重试 | 人类可接受的公平对手 |

## 4. 最小可验证流程

### MVP 行为闭环

```text
1. Xiaohan 手动完成 P1 回合
2. 游戏进入 Codex P2 回合
3. Codex 调用 identity check
4. Codex 只读 overview / cities / units / victory / diplomacy
5. Codex 输出本回合计划
6. Xiaohan 批准或修改
7. Codex 执行动作
8. Codex end_turn
9. 记录：
   - turn number
   - player id / civ / leader
   - observed state
   - plan
   - tool calls
   - actions
   - post-turn result
```

### MVP 必须守住的红线

| 红线 | 原因 |
| --- | --- |
| 每个 P2 回合开始必须 identity check | 热座下最怕操作到 P1 |
| P1 回合 Codex 不许调用 action tools | 否则不是对战，是共享账号事故 |
| 不许 load save retry | 否则评测污染 |
| 不许读 omniscient/all-player hidden state | 否则不公平 |
| 不许一次改太多功能 | 否则 debug 复杂度失控 |

## 5. 可直接投给 Codex 的 `/goal` 阶段任务

下面这些按依赖顺序排列。不要一次性全丢给 Codex。先做 `Goal 0 → Goal 1 → Goal 2`。能跑 5 个热座回合后，再做后面的。不能跳过身份安全、日志和回归测试去做知识库或视觉。

### Goal 0：仓库基线与环境记录

```text
/goal Establish a reproducible baseline for civ6-mcp before making any code changes.

Context:
- This repo is lmwilki/civ6-mcp or my fork of it.
- I want to use it with Codex to play Civilization VI Hotseat as Player 2.
- Start by reading README.md, AGENTS.md if present, pyproject.toml, and any existing test docs.
- Do not modify gameplay behavior.

Tasks:
1. Create docs/hotseat-baseline.md documenting:
   - exact repo commit
   - Python version
   - uv version
   - Codex MCP config example
   - Civ6 requirements
   - live connection test steps
   - known risks for Hotseat
2. Create scripts/hotseat/check_env.py that prints:
   - Python version
   - uv availability
   - repo root
   - whether pyproject.toml exists
   - whether scripts/test_connection.py exists
   - whether .codex/config.toml or ~/.codex/config.toml guidance is documented
3. Do not require Civilization VI to be running for check_env.py.

Constraints:
- Do not change public APIs.
- Do not change MCP tool behavior.
- Do not add external dependencies.
- Keep changes to docs/ and scripts/hotseat/ only.
- Write a concise progress log to .codex-goal-log.md.

Done when:
- `uv run python scripts/hotseat/check_env.py` succeeds.
- Existing tests are discovered and documented.
- `git diff --stat` shows only docs/hotseat-baseline.md, scripts/hotseat/check_env.py, and .codex-goal-log.md unless you find an unavoidable reason.

Stop if:
- You need network access.
- You need secrets.
- You need more than 5 files changed.
- You cannot determine the repo structure.
```

### Goal 1：热座身份验证，不允许 action

```text
/goal Add a Hotseat identity verification runbook and a read-only smoke script for Player 2.

Context:
- I will play Civilization VI Hotseat:
  - Player 1: Xiaohan, human/manual
  - Player 2: Codex, human slot controlled through civ6-mcp
  - Player 3: in-game AI
- The first live requirement is to verify that civ6-mcp reads Player 2 when the screen is on Player 2's turn.
- Do not implement new gameplay actions yet.

Tasks:
1. Add docs/hotseat-identity-test.md with a step-by-step manual protocol:
   - P1 manual turn
   - switch to P2
   - run Codex read-only checks
   - expected civ/leader/player_id verification
   - stop conditions
2. Add scripts/hotseat/identity_smoke.py:
   - It should be safe to run without Civ6.
   - It should support `--expected-civ`, `--expected-leader`, `--expected-player-id`.
   - If live MCP access is not available, it should print the exact manual tool calls/prompts to run in Codex and exit with a clear message.
3. Add a sample Codex prompt to docs/hotseat-identity-test.md that forbids all action tools.

Constraints:
- Do not call or implement action tools.
- Do not change civ_mcp runtime behavior.
- Do not use network access.
- Do not rely on OCR or screenshot.
- Keep changes under docs/ and scripts/hotseat/.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run python scripts/hotseat/identity_smoke.py --expected-civ Rome --expected-leader Trajan` runs and prints a clear protocol or performs read-only validation if live access exists.
- `uv run pytest` passes if tests are configured; otherwise document that no test suite exists.
- docs/hotseat-identity-test.md contains a copy-paste Codex prompt for read-only P2 verification.

Stop if:
- You need to modify MCP action tools.
- You need more than 8 files changed.
- You cannot keep the script safe when Civ6 is not running.
```

### Goal 2：结构化日志，先别优化策略

```text
/goal Add a minimal structured Hotseat turn log format and local validators.

Context:
- We need to evaluate Codex across Civilization VI Hotseat turns.
- The current failure mode to prevent is untraceable behavior: no one knows what it saw, planned, executed, or forgot.
- This goal is about observability only, not better strategy.

Tasks:
1. Define docs/hotseat-turn-log-schema.md.
2. Add scripts/hotseat/validate_turn_log.py that validates a JSONL log file.
3. Add examples/hotseat/sample_turn_log.jsonl with 2 fake turns:
   - one valid P2 read-only turn
   - one valid P2 action turn
4. The schema should include:
   - session_id
   - game_turn
   - active_player_id
   - expected_player_id
   - civ
   - leader
   - phase: observe | plan | execute | post_turn
   - observed_state_summary
   - plan
   - tool_calls
   - actions_taken
   - commitments_next_turn
   - violations
   - notes

Constraints:
- Do not connect to Civ6.
- Do not change MCP tools.
- Do not add heavyweight dependencies; standard library preferred.
- Keep changes to docs/, scripts/hotseat/, examples/hotseat/.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run python scripts/hotseat/validate_turn_log.py examples/hotseat/sample_turn_log.jsonl` passes.
- Invalid player identity or missing tool_calls is caught by the validator.
- The docs explain how I should manually append logs after each Codex turn.

Stop if:
- You need external packages.
- You need more than 8 files changed.
- You are tempted to implement strategy logic in this goal.
```

### Goal 3：创建 Civ6 Hotseat Skill v1

```text
/goal Create a repository-scoped Codex skill for Civilization VI Hotseat play.

Context:
- I want Codex to follow a fixed workflow when playing Civ6 Hotseat through civ6-mcp.
- The skill must reduce:
  - wrong-player actions
  - skipped scouting
  - unescorted civilian movement
  - forgotten commitments
  - gold/faith hoarding
  - victory progress blindness
- This goal creates instructions only; no gameplay code changes.

Tasks:
1. Create `.agents/skills/civ6-hotseat/SKILL.md`.
2. Create `.agents/skills/civ6-hotseat/references/hotseat-turn-checklist.md`.
3. The skill must define:
   - when it should trigger
   - Player 2 identity check
   - start-of-turn observation sweep
   - MUST / SHOULD / OPTIONAL planning format
   - human approval gates
   - civilian safety gate
   - every-10-turn strategic checkpoint
   - post-turn commitments log
4. Include a section called "Never do these without approval":
   - declare war
   - accept major deals
   - spend >200 gold or faith
   - change government
   - select religion beliefs
   - settle a city
   - load an old save
   - inspect hidden information about Xiaohan's civilization

Constraints:
- Do not change Python code.
- Do not edit upstream AGENTS.md unless necessary; if needed, only add a short pointer to the skill.
- Keep the skill focused on Hotseat play only.
- Write progress to .codex-goal-log.md.

Done when:
- `.agents/skills/civ6-hotseat/SKILL.md` has valid YAML front matter with name and description.
- The skill includes a copy-paste "start Codex turn" prompt.
- The checklist is short enough to use every turn.
- `git diff --stat` shows only skill files and .codex-goal-log.md unless you justify otherwise.

Stop if:
- You need to package a plugin.
- You need external dependencies.
- You need more than 6 files changed.
```

### Goal 4：工具目录与 MCP 信息增强

```text
/goal Generate a tool catalog and identify the smallest useful MCP composite tools for Hotseat play.

Context:
- civ6-mcp already exposes many tools, but raw tool lists are too fragmented for reliable strategic play.
- Before adding new tools, map the existing tool registry and document gaps.
- Focus on Hotseat Player 2 use.

Tasks:
1. Inspect the existing MCP tool registration mechanism.
2. Generate docs/tool-catalog.md listing:
   - tool name
   - purpose
   - read-only vs action
   - safe in Hotseat P2
   - requires human approval
   - potential fairness risk
3. Add scripts/hotseat/generate_tool_catalog.py if the registry can be introspected safely.
4. Propose no more than 5 composite tools in docs/hotseat-mcp-gap-analysis.md:
   - get_hotseat_turn_context
   - get_strategy_dashboard
   - get_civilian_risk_report
   - get_commitment_status
   - get_public_victory_and_scoreboard
5. Do not implement the composite tools yet unless the repo already has a trivial pattern for this.

Constraints:
- Prefer documentation and introspection over behavior changes.
- Do not alter existing tool schemas.
- Do not break current MCP clients.
- Keep changes to docs/ and scripts/hotseat/ unless absolutely necessary.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run python scripts/hotseat/generate_tool_catalog.py` works or cleanly explains why automatic generation is unavailable.
- docs/tool-catalog.md exists and classifies tools by safety.
- docs/hotseat-mcp-gap-analysis.md recommends the next single composite tool to implement.

Stop if:
- You need to modify more than 10 files.
- The tool registry is too dynamic to inspect safely.
- You cannot classify action vs read-only tools with confidence.
```

### Goal 5：实现第一个 composite tool：策略仪表盘

```text
/goal Implement a read-only Hotseat strategy dashboard tool for civ6-mcp.

Context:
- Raw tools make Codex forget periodic strategic checks.
- The dashboard should make the "Sensorium Effect" less severe by forcing a standard observation sweep.
- This tool must be read-only.

Target tool:
- `get_hotseat_strategy_dashboard`

It should return a compact structured text or JSON-like summary including:
- active player identity
- expected player identity if configured
- turn number
- cities count and basic outputs
- units needing orders
- civilian units and risk hints
- gold, faith, science, culture
- current research/civic
- visible military threats near owned cities/civilians if available
- victory progress if available through existing read-only APIs
- diplomacy/public scoreboard if available through existing read-only APIs
- warnings:
  - identity mismatch
  - city count behind benchmark
  - gold > 500
  - faith > 500
  - no scout/exploration issue if detectable
  - unescorted civilian risk if detectable

Constraints:
- Read-only only. No action tool calls.
- Use existing helper functions where possible.
- Do not expose hidden information about Xiaohan's Player 1 beyond normally visible/public info.
- Add targeted tests with mocked or fixture data.
- Keep public APIs backward compatible.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run pytest tests` passes, or at minimum `uv run pytest tests/test_hotseat_strategy_dashboard.py` passes if full tests are not configured.
- The new tool appears in tool catalog/docs.
- The tool returns an identity warning when expected player does not match active player.
- Existing tools remain unchanged.

Stop if:
- You need to rewrite the tool registry.
- You need more than 10 files changed.
- You cannot implement this without reading hidden opponent internals.
```

### Goal 6：视觉截图 v1，只做观察，不做自动决策

```text
/goal Add minimal screenshot capture support for Hotseat observation without making gameplay decisions from OCR.

Context:
- I want visual support because Civ6 agents miss passive signals such as minimap, unit health bars, UI notifications, and fog boundaries.
- civ6-mcp may already have GUI automation or screenshot-related code; inspect it first.
- The first version should capture and store screenshots, not interpret them aggressively.

Tasks:
1. Inspect existing screenshot, launcher, OCR, or GUI automation code.
2. Add or document a read-only tool/script:
   - `capture_hotseat_screenshot`
   - saves a timestamped PNG under logs/screenshots/
   - returns the file path and basic metadata
3. Add docs/vision-v1.md explaining:
   - what screenshots are used for
   - what they are not trusted for
   - how screenshots complement API state
   - failure modes: wrong window, minimized game, scaling, multi-monitor, stale frame
4. Add tests for path generation and metadata formatting without requiring Civ6 to run.

Constraints:
- Do not make action decisions based solely on screenshot/OCR.
- Do not add cloud vision dependencies.
- Do not require network access.
- Do not break headless/offline tests.
- logs/screenshots/ must be gitignored.
- Write progress to .codex-goal-log.md.

Done when:
- Offline tests pass.
- The tool or script fails gracefully when screenshot capture is unavailable.
- docs/vision-v1.md includes a manual live test procedure.
- No gameplay action tools are changed.

Stop if:
- You need OS-level permissions that cannot be checked locally.
- You need more than 10 files changed.
- You cannot support a no-Civ6 offline path.
```

### Goal 7：知识库 v1，本地 Markdown 检索

```text
/goal Add a local Markdown knowledge base and simple search script for Civ6 Hotseat strategy support.

Context:
- I want Codex to use strategy knowledge, my notes, and game reports without dumping huge text into every prompt.
- This version should be local-only and deterministic.
- Do not scrape the web.
- Do not ingest copyrighted long-form guides unless I provide summaries or permitted excerpts.

Tasks:
1. Create knowledge/ with subfolders:
   - mechanics/
   - strategy-cards/
   - game-reports/
   - xiaohan-notes/
2. Add knowledge/README.md explaining allowed source types and citation rules.
3. Add scripts/kb/kb_search.py:
   - searches Markdown files locally
   - supports query string
   - returns top N file paths, headings, and short snippets
   - standard library preferred
4. Add sample strategy cards:
   - early_expansion.md
   - civilian_safety.md
   - gold_faith_spending.md
   - victory_reassessment.md
5. Add docs/kb-workflow.md explaining how Codex should use KB during a turn:
   - query only after observing state
   - retrieve 3-5 relevant cards
   - cite card names in its plan
   - do not blindly follow generic advice over current state

Constraints:
- No network access.
- No external vector DB.
- No embeddings yet.
- No long copyrighted pasted guides.
- Keep changes under knowledge/, scripts/kb/, docs/.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run python scripts/kb/kb_search.py "settler civilian safety" --top 3` returns relevant local cards.
- knowledge/README.md has source hygiene rules.
- docs/kb-workflow.md includes a copy-paste Codex prompt snippet.

Stop if:
- You need internet access.
- You need external dependencies.
- You need to ingest materials not present in the repo.
```

### Goal 8：把战报转换成策略卡，不要全文塞 prompt

```text
/goal Add a battle-report-to-strategy-card workflow for Civ6 agent improvement.

Context:
- civ6-mcp has public devlogs showing recurring agent failures.
- I want to convert lessons into compact strategy cards that Codex can retrieve during Hotseat play.
- The goal is not to summarize everything; it is to create actionable triggers.

Tasks:
1. Add docs/report-to-card-method.md defining a card schema:
   - title
   - trigger
   - symptoms
   - recommended action
   - anti-pattern
   - relevant game phase
   - confidence
   - source
2. Add scripts/kb/make_strategy_card.py that can create a Markdown card from a small YAML or JSON input.
3. Add at least 5 cards under knowledge/strategy-cards/agent-failure-patterns/:
   - sensorium_effect.md
   - exploration_neglect.md
   - expansion_failure.md
   - reflection_action_gap.md
   - victory_path_tunnel_vision.md
4. Each card must include a trigger such as:
   - "If turn <= 70 and city_count < 3"
   - "If gold > 500"
   - "If no victory_progress check in last 10 turns"
   - "If moving civilian"
5. Do not paste long source text. Use short summaries and source pointers only.

Constraints:
- No network access.
- No copyrighted long excerpts.
- Cards must be actionable, not generic essay sludge.
- Keep changes under docs/, scripts/kb/, knowledge/.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run python scripts/kb/kb_search.py "gold hoarding trigger" --top 3` finds the relevant card.
- Each card has a concrete IF/THEN trigger.
- docs/report-to-card-method.md explains how to add future game reports.

Stop if:
- You need external source fetching.
- You need more than 10 files changed.
- The cards become vague advice instead of trigger-action rules.
```

### Goal 9：完整热座 Skill v2：观察 → 检索 → 计划 → 执行 → 复盘

```text
/goal Upgrade the civ6-hotseat skill into a full turn workflow that uses MCP state, screenshots, and the local KB.

Context:
- The first skill version defined basic rules.
- Now the skill should orchestrate the complete Hotseat turn:
  1. identity check
  2. strategy dashboard
  3. optional screenshot capture
  4. KB retrieval
  5. plan with MUST / SHOULD / OPTIONAL
  6. human approval gates
  7. action execution
  8. post-turn log
  9. next-turn commitments

Tasks:
1. Update `.agents/skills/civ6-hotseat/SKILL.md`.
2. Add references:
   - turn-flow.md
   - approval-gates.md
   - benchmark-targets.md
   - fairness-rules.md
3. Add benchmark targets:
   - T30: second city plan active or founded
   - T50: at least 2 cities and active scouting
   - T70: target 3 cities or explicit recovery plan
   - T100: target 4+ cities or pivot plan
4. Add "commitment carryover":
   - Every turn must check prior commitments before making new plans.
5. Add "anti-bullshit rule":
   - If the dashboard contradicts the narrative, trust the dashboard.

Constraints:
- Skill/docs only unless a tiny script update is necessary.
- Do not implement new MCP tools in this goal.
- Do not make the skill omniscient.
- Keep the workflow short enough to actually use every turn.
- Write progress to .codex-goal-log.md.

Done when:
- The skill has a single copy-paste "Start my Codex P2 turn" prompt.
- The skill explicitly calls out identity, observation, KB, approval, execution, post-turn log.
- The skill references local KB and screenshots without requiring them.
- No Python behavior changes unless justified.

Stop if:
- You need more than 8 files changed.
- The skill becomes longer than necessary and unusable in play.
```

### Goal 10：评测框架 v1：30 回合中等电脑

```text
/goal Add a lightweight evaluation protocol for measuring Codex Hotseat performance over 30 turns against a medium-difficulty AI.

Context:
- Stage objective: beat a medium-difficulty computer eventually.
- First we need measurable leading indicators before full-game win/loss.
- The evaluation should be usable with manual Hotseat play and structured turn logs.

Tasks:
1. Add docs/benchmark-protocol.md defining:
   - map settings
   - difficulty
   - allowed/disallowed tools
   - logging requirements
   - reset rules
   - fairness profile
2. Add scripts/evals/eval_hotseat_log.py that scores a turn log on:
   - identity violations
   - action without approval
   - turns with missing observation sweep
   - city count by T50/T70/T100
   - turns since last victory check
   - gold/faith hoarding triggers
   - civilian movement without risk check
   - unresolved commitments
3. Add examples/hotseat/sample_eval_log.jsonl.
4. Output a JSON summary and a Markdown summary.

Constraints:
- Offline log evaluation only.
- No live Civ6 required.
- No LLM judge yet.
- No external dependencies unless already present.
- Write progress to .codex-goal-log.md.

Done when:
- `uv run python scripts/evals/eval_hotseat_log.py examples/hotseat/sample_eval_log.jsonl --out-md /tmp/hotseat_eval.md` succeeds.
- The eval catches at least:
  - identity mismatch
  - missing victory check
  - gold > 500 without purchase proposal
  - civilian moved without risk check
- docs/benchmark-protocol.md defines pass/fail thresholds for a 30-turn run.

Stop if:
- You need to parse actual Civ6 save files.
- You need more than 10 files changed.
- You cannot keep the evaluator deterministic.
```

### Goal 11：中等难度达标循环

```text
/goal Run an eval-driven improvement loop toward beating a medium-difficulty AI in Civ6 Hotseat, using only logged evidence.

Context:
- This is not a code-only goal. It coordinates playtesting, logs, evals, and targeted improvements.
- Use the benchmark protocol and eval script already added.
- The stage objective is not necessarily a full victory yet; it is to meet early-game survival and growth thresholds.

Procedure:
1. Read docs/benchmark-protocol.md and the civ6-hotseat skill.
2. Review the latest logs under logs/runs/ if present.
3. Run `uv run python scripts/evals/eval_hotseat_log.py <latest-log>`.
4. Identify the top 1-2 failure modes.
5. Make one focused improvement:
   - skill wording
   - strategy card
   - dashboard warning
   - eval rule
   - logging field
6. Re-run relevant tests/evals.
7. Log changes and scores to .codex-goal-log.md.

Constraints:
- One focused improvement per iteration.
- Do not change more than 8 files per iteration.
- Do not weaken fairness rules to improve scores.
- Do not optimize for eval loopholes.
- Do not claim victory without logged evidence.
- Stop if live game logs are unavailable; instead produce the next live-play checklist.

Done when:
- The latest 30-turn log has:
  - 0 identity violations
  - 0 unauthorized action violations
  - observation sweep on every Codex turn
  - no civilian-risk violations
  - city-count plan meets benchmark or has explicit recovery plan
  - eval Markdown summary is saved under logs/evals/
- .codex-goal-log.md records before/after scores.

Stop if:
- No log file exists.
- The evaluator cannot run.
- You need to change more than 8 files.
- You need network access.
```

### Goal 12：神级路线，不许跳级吹牛

```text
/goal Design the staged difficulty ramp from medium AI to Deity for Civ6 Hotseat Codex play.

Context:
- Milestone objective: eventually beat Deity.
- Do not implement new gameplay code in this goal.
- The purpose is to define a serious benchmark ladder, not declare success after one lucky seed.

Tasks:
1. Add docs/difficulty-ramp.md with stages:
   - Prince smoke
   - King stability
   - Emperor adaptation
   - Immortal pressure
   - Deity milestone
2. For each stage define:
   - map settings
   - civ pool
   - seed policy
   - number of runs
   - early-game pass criteria
   - mid-game pass criteria
   - full-game success criteria
   - allowed tools
   - fairness profile
3. Define failure taxonomy:
   - identity/tooling failure
   - tactical failure
   - expansion failure
   - diplomacy failure
   - economy hoarding
   - victory-path failure
   - human-approval bottleneck
4. Define when to upgrade difficulty and when to stay.

Constraints:
- Documentation only.
- No code changes.
- Do not use single-game anecdotes as proof.
- Do not relax fairness rules for benchmark claims.
- Write progress to .codex-goal-log.md.

Done when:
- docs/difficulty-ramp.md contains a table with all difficulty stages.
- It defines "Deity milestone achieved" as a multi-run condition, not one lucky win.
- It includes a recommended first Deity civ/map setup.

Stop if:
- You need live game access.
- You need more than 4 files changed.
```

### Goal 13：对战 Xiaohan 的公平规则

```text
/goal Define the fair-play protocol for Codex playing Hotseat against Xiaohan.

Context:
- Final objective: Codex should eventually beat Xiaohan, who has over 10,000 hours of strategy game experience.
- This must be a fair Hotseat opponent, not a debug-console cheater.
- Xiaohan controls Player 1 manually.
- Codex controls Player 2 through civ6-mcp.
- One AI may also be present.

Tasks:
1. Add docs/xiaohan-duel-rules.md.
2. Define:
   - allowed information
   - disallowed information
   - allowed tools
   - tools requiring approval
   - banned actions
   - save/load policy
   - screenshot policy
   - human intervention policy
   - pause/resume policy
   - post-game review policy
3. Add a "fairness profile" table:
   - DEBUG
   - TRAINING
   - FAIR_HOTSEAT
   - TOURNAMENT
4. Define what counts as a legitimate Codex win:
   - no identity violations
   - no hidden-state reads
   - no save-scumming
   - all major irreversible actions logged
   - final victory condition achieved in game
5. Include a copy-paste starting prompt for the duel.

Constraints:
- Documentation only.
- Do not change MCP tools.
- Do not weaken prior safety constraints.
- Write progress to .codex-goal-log.md.

Done when:
- docs/xiaohan-duel-rules.md is complete enough to use before a real match.
- It distinguishes training mode from fair duel mode.
- It defines a clear dispute resolution process for accidental tool misuse.

Stop if:
- You need live game access.
- You need more than 5 files changed.
```

## 6. 推荐执行顺序

### 先跑这 3 个

```text
Goal 0: baseline
Goal 1: hotseat identity
Goal 2: structured logging
```

这三个完成之前，不要碰视觉、知识库、战报。原因：如果 Codex 现在连“我是 Player 2”都不能稳定确认，策略知识只会放大错误执行。

### 然后做这 3 个

```text
Goal 3: skill v1
Goal 4: tool catalog
Goal 5: strategy dashboard
```

这一步把“每回合该看什么”固化下来，正面处理 Sensorium Effect。公开复盘已经指出 agent 只处理被推到面前的信息，外交、胜利进度、地图探索、宗教传播这类需要主动轮询的信息会长期失明。

### 再做增强

```text
Goal 6: screenshot
Goal 7: KB
Goal 8: strategy cards
Goal 9: skill v2
```

这时才值得加视觉和知识库。否则只是把一个没流程的 agent 变成一个“懂很多但执行很烂”的 agent。cross-game analysis 里最关键的点是 Reflection-Action Gap：它能写出正确分析，但下一回合照样不执行。

### 最后做评测和目标推进

```text
Goal 10: eval harness
Goal 11: medium AI loop
Goal 12: Deity ramp
Goal 13: Xiaohan duel rules
```

## 7. 阶段性目标定义

| 目标层级 | 成功标准 | 不算成功的东西 |
| --- | --- | --- |
| 最小可验证流程 | 连续 5 个 P2 回合身份正确、只操作自己、日志完整 | “它能回答局势分析” |
| 中等电脑 | 30/100 回合指标达标，并最终多局能赢 Prince/King | 单局运气好赢 |
| 神级电脑 | 多 seed、多文明、无隐藏信息/读档重试下至少稳定有胜率 | 靠全图/重载/调参 seed |
| 击败 Xiaohan | FAIR_HOTSEAT 规则下真实取胜，日志可审计 | 用户让子、Codex 作弊、用户手把手帮复盘 |

## 8. 第一场测试建议

首局不要超过 30 回合。

```text
Map: Tiny Pangaea
Speed: Quick 或 Online
Difficulty: Prince 或 King
P1: Xiaohan
P2: Codex
P3: AI
Mods: Off
Auto End Turn: Off
Save reload: banned except crash recovery
```

每个 Codex 回合固定：

```text
1. identity check
2. strategy dashboard / overview
3. cities
4. units
5. victory/public score every 10 turns
6. plan: MUST / SHOULD / OPTIONAL
7. ask Xiaohan approval
8. execute approved actions
9. log commitments
10. end turn
```

## 9. 开始前 checklist

- [ ] `civ6-mcp` 原始连接测试通过
- [ ] Codex `/mcp` 能看到 civ6 server
- [ ] 热座 P2 身份验证通过
- [ ] `logs/` 已 gitignore
- [ ] `.codex-goal-log.md` 已开始记录
- [ ] `docs/hotseat-identity-test.md` 存在
- [ ] 每个 P2 回合先 identity check
- [ ] 每个 action 前确认 active player 是 P2
- [ ] P1 回合 Codex 不调用 action tools
- [ ] 不读隐藏信息，不读档重试

## 10. Live Play 执行规则

当 Codex 不是在开发 Agent Lab，而是在真实热座游戏中执行 P2 agent 时：

1. 先确认当前是 P2 回合。
2. 如果不是 P2 回合，只能说明等待或请求用户切换，不调用 action tools。
3. 先做只读观察，再输出计划。
4. 计划必须区分 MUST / SHOULD / OPTIONAL。
5. 涉及战争、定居、换政府、宗教信条、大额花费、重大交易、读档、隐藏信息风险的动作必须等待用户批准。
6. 执行后记录本回合看到了什么、做了什么、结果怎样、下回合承诺是什么。
7. 如果日志或身份验证缺失，优先补齐流程，不继续推进游戏。

## 11. 结论

正确路线：

```text
先让 Codex 稳定、安全、可复盘地玩热座 P2
→ 再给它更好的观察工具
→ 再给它可检索的策略知识
→ 再用 Skill 固化流程
→ 最后用 eval 和战报迭代策略
```

第一步执行 **Goal 0、Goal 1、Goal 2**。不能跳。跳过地基去做视觉、知识库或神级策略，会让后续问题更难定位。

## 12. Sources

- [Best practices - Codex | OpenAI Developers](https://developers.openai.com/codex/learn/best-practices)
- [Agent Skills - Codex | OpenAI Developers](https://developers.openai.com/codex/skills)
- [civ6-mcp README](https://github.com/lmwilki/civ6-mcp/blob/main/README.md)
- [civ6-mcp devlog README](https://github.com/lmwilki/civ6-mcp/blob/main/docs/devlog/README.md)
- [civ6-mcp cross-game analysis](https://github.com/lmwilki/civ6-mcp/blob/main/docs/cross-game-analysis.md)

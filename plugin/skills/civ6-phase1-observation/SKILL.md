---
name: civ6-phase1-observation
description: Reproduce Codex HL Phase 1 observation-only runs for Civilization VI in this repo. Use when the user asks for Codex HL Phase 1, Civ6 observation, test 1 short-run/T50 validation, reusable observation workflow, or human/agent audit reports for a real Civ6 single-player save.
---

# Civ6 Phase 1 Observation

Use this skill from the installed `codex-hl-civ6` plugin to run the Codex HL Phase 1 observation workflow on the real `test 1` single-player save. The purpose is evidence capture, not strategy improvement.

## Hard Boundaries

- Use the installed plugin from a `codex-hl-civ6` workspace and the real `test 1` single-player save.
- Do not switch to Hotseat, another save, or a productized test harness.
- Do not do failure attribution, Replay Arena, candidate strategy improvement, automatic learning, or promote/reject.
- Do not continue to T50 until a human accepts the short-run report.
- Treat `episodes/` as local run output unless the user explicitly asks to commit a specific episode.

## Standard Workflow

1. Confirm the repo root and current branch.
   - Prefer `C:\Program Files\Git\cmd\git.exe` if `git` is not on PATH.
   - Inspect `git status --short --branch --untracked-files=all`.
   - Do not revert unrelated dirty files.
2. Run the short-run.
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
   ```
   Use `--episode-id <id>` only when a stable validation name is needed.
   - Do not start a separate `civ6-connector` server for this workflow. The runner talks directly to FireTuner.
   - By default the runner stops stale repo-local `civ6-connector` server processes and records that cleanup in `raw/tool_calls.jsonl`. Use `--keep-existing-mcp-server` only when a human explicitly asks to preserve an existing server process.
   - By default the runner also resets any running Civ6 process before loading `test 1`, so the run starts from a clean front-end load path. Use `--reuse-running-game` only for explicit manual debugging.
3. Verify the generated episode contains:
   - `header.json`
   - `raw/tool_calls.jsonl`
   - `raw/mcp.jsonl`
   - `raw/civ6_states/*.json`
   - `raw/saves/save_index.jsonl`
   - `derived/decision_atoms.jsonl`
   - `derived/report_pack.json`
   - `outcome/phase1_short_run_report.draft.html`
   - `outcome/phase1_short_run_report.html`
   - `outcome/phase1_agent_report.md`
   - `outcome/phase1_agent_audit_report.html`
4. Validate the four evidence classes:
   - all tool/MCP calls include time, params, raw result or error
   - every turn has a state snapshot covering empire, cities, units, notifications, threats, research/civic, production, or explicit gaps
   - decision records include `available_actions`, rationale, `why_not_alternatives`, execution, outcome, `related_*_ids`, plus compatibility aliases `alternatives` and `evidence_ids`
   - save index links saves to episode, turn, decision or event
5. Treat reporting as two stages:
   - Evidence capture writes raw logs, `derived/report_pack.json`, and the draft human HTML.
   - The final `phase1_short_run_report.html` is the Codex-refined human entrypoint. It must stay grounded in `report_pack.json` and pass the Human HTML Contract below.
6. Confirm `phase1_short_run_report.html` satisfies the Human HTML Contract below. The runner performs this check automatically; if it fails, fix the report renderer or rerun `--report-only` after refining the human HTML before asking for human acceptance.
7. Present the human report path and pause for human acceptance.

## Report Roles

- `phase1_short_run_report.html` is the only human review entrypoint. It must preserve the accepted Chinese HTML shape from `phase1_test1_short_20260512_130155` while improving scanability, not collapse into a newly invented engineering summary.
- `phase1_short_run_report.draft.html` is runner-produced draft material. It is useful for renderer debugging, but it is not the human acceptance entrypoint if it fails the final contract.
- `phase1_agent_report.md` is the quick handoff for the next agent/session. Read this first when resuming.
- `phase1_agent_audit_report.html` is the complete machine/agent audit report with raw JSON evidence and expandable details. It is never a substitute for the human HTML.
- If the human report reads like raw JSON, field dumps, or a table-only audit, regenerate or improve the report before asking for acceptance.

## Human HTML Contract

The human report must be a polished Chinese HTML review document with this section flow:

1. `Codex HL Phase 1 人类验收报告`
2. `验收结论`
3. `我实际观测到的局面变化`, including `起点 T...` and `终点 T...`
4. `回合叙事`
5. `重点：决策流程`
6. `证据边界和你需要判断的点`
7. `存档和决策关联`
8. `缺口清单`
9. `面向 Agent 的报告`, linking to both `phase1_agent_report.md` and the agent audit artifact

The readability floor is higher than the accepted baseline HTML. A reusable report must include:

- a short `先读这份报告的顺序` block near the top, so a reviewer knows what to inspect first
- a `快速定位` nav with anchors to the major sections
- `关键数字变化` metric chips instead of only a dense prose/list comparison
- per-turn narrative rendered as `turn-card` cards, not a wide audit table
- decision records rendered as `decision-header` + `decision-grid` + `review-note`
- compact save rows that show the checkpoint filename first and the full path second
- `快速接手` and `完整审计` tiles for the two agent-facing artifacts

Each decision in the human report must be rendered as prose with these labels:

- `当时看到的问题：`
- `候选动作：`
- `我选择了：`
- `为什么这样选：`
- `为什么没选其他动作：`
- `执行后结果：`
- `对 review 的意义：`

Do not put raw JSON blocks, `<details>`, `<pre>`, or `{&quot;turn&quot;` style encoded state dumps in `phase1_short_run_report.html`. Raw evidence belongs in `phase1_agent_audit_report.html`, `derived/report_pack.json`, and the episode `raw/` files.

The contract source is `plugin/fixtures/phase1_human_report_contract/contract.json`; the skeleton fixture is there to prevent future agents from inventing a different human report shape.

## Rebuild Existing Reports

Use report-only mode when the episode already exists and no Civ6 turn should be advanced:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

Report-only mode must not launch Civ6 or modify the live game.

## Fresh Validation Prompt

When validating the skill with a fresh agent, use this prompt shape:

```text
Use plugin/skills/civ6-phase1-observation/SKILL.md.
Do not edit code, commit, or push.
Run a real 3-turn Phase 1 short-run on the test 1 single-player save.
Do not start a separate civ6-connector server; use only codex-hl-civ6-phase1-observe.
Create a new episode id named phase1_subagent_validation_<timestamp>.
Stop before T50.
Return the episode_id, human report path, agent handoff path, agent audit report path, four evidence-class PASS/FAIL results, and blockers.
```

## Commit Hygiene

- Commit the plugin runner, this skill, and docs.
- Do not stage `episodes/` by default.
- Do not stage unrelated dirty files such as independent gameplay fixes or old experiment scripts unless the user explicitly includes them.

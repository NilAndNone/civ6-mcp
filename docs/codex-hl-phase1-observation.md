# Codex HL Phase 1 Observation Workflow

This document makes the Phase 1 observation workflow reproducible from a fresh Codex session. Phase 1 means observation only: record a real Civ6 game, produce reviewable evidence, and stop before any T50 continuation.

## What This Workflow Produces

The runner `scripts/codex_phase1_observe.py` runs the real `test 1` single-player save for 3-5 turns and writes an episode under `episodes/<episode_id>/`.

Each episode contains:

- `header.json` for provenance and route metadata.
- `raw/tool_calls.jsonl` for every high-level tool call with time, params, result, and errors.
- `raw/mcp.jsonl` for every low-level FireTuner/Lua exchange with raw request and response.
- `raw/civ6_states/*.json` for per-turn snapshots.
- `raw/saves/save_index.jsonl` plus checkpoint `.Civ6Save` files.
- `derived/decision_atoms.jsonl` for decision records including `available_actions`.
- `derived/report_pack.json` for the compact evidence bundle that grounds human-report refinement.
- `outcome/phase1_short_run_report.draft.html` for the runner-generated draft human HTML.
- `outcome/phase1_short_run_report.html` for human review.
- `outcome/phase1_agent_report.md` for the next agent/session handoff.
- `outcome/phase1_agent_audit_report.html` for complete machine/agent audit evidence.

The human report is intentionally not a JSON dump. It should explain the decision flow in Chinese prose so a reviewer can understand what the agent saw, what it considered, what it chose, why alternatives were rejected, what happened after execution, and what that means for later review. The runner emits a draft and `report_pack.json`; Codex may refine the final HTML, but that refinement must stay inside the contract and must not alter raw evidence.

## Human HTML Contract

The human-facing artifact is always:

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
```

That file must preserve the accepted review shape from `phase1_test1_short_20260512_130155` while raising the scanability floor. The agent-facing artifacts can be large and audit-oriented, but the human HTML must remain a polished Chinese review document with this section flow:

1. `Codex HL Phase 1 人类验收报告`
2. `验收结论`
3. `我实际观测到的局面变化`, including `起点 T...` and `终点 T...`
4. `回合叙事`
5. `重点：决策流程`
6. `证据边界和你需要判断的点`
7. `存档和决策关联`
8. `缺口清单`
9. `面向 Agent 的报告`, linking to both `phase1_agent_report.md` and `phase1_agent_audit_report.html`

The current readability floor is higher than the accepted baseline HTML. A reusable report must include a top-level read path (`先读这份报告的顺序`), quick section anchors (`快速定位`), metric chips for `关键数字变化`, card-based `回合叙事`, structured decision cards (`decision-header`, `decision-grid`, `review-note`), compact save rows that show checkpoint filenames before full paths, and two agent-report tiles for `快速接手` and `完整审计`.

The decision-flow section is the most important part for human review. Each decision must be rendered as readable prose with these labels:

- `当时看到的问题：`
- `候选动作：`
- `我选择了：`
- `为什么这样选：`
- `为什么没选其他动作：`
- `执行后结果：`
- `对 review 的意义：`

Do not replace this report with an engineering assembly, raw JSON block, field dump, or audit table. The runner validates this contract after writing the human HTML and fails fast if the shape regresses. Raw evidence belongs in `phase1_agent_audit_report.html`, `derived/report_pack.json`, `raw/*.jsonl`, `raw/civ6_states/*.json`, and `derived/decision_atoms.jsonl`.

The contract fixture lives in `tests/fixtures/phase1_human_report_contract/`. It stores the current structure/style gold standard without committing episode raw logs or save files.

## Fresh Session Procedure

Start in the repo root on Windows:

```powershell
Set-Location O:\civ6\civ6-mcp
& 'C:\Program Files\Git\cmd\git.exe' status --short --branch --untracked-files=all
```

Read the repo-local skill before running the workflow:

```text
.codex/skills/civ6-phase1-observation/SKILL.md
```

Run a short validation episode:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python scripts\codex_phase1_observe.py --save-name "test 1" --turns 3
```

Do not start a separate `civ-mcp` MCP server for this flow. The runner talks directly to FireTuner and, by default, stops stale repo-local `civ-mcp` server processes before launching so another process cannot race the game lifecycle. It also resets any running Civ6 process before loading `test 1`, so the episode does not depend on the screen left open by a previous session. Both steps are logged as normal tool calls. Use `--keep-existing-mcp-server` or `--reuse-running-game` only for explicit manual debugging.

Reporting is a two-stage flow:

1. Evidence capture writes raw logs, `derived/report_pack.json`, `outcome/phase1_short_run_report.draft.html`, `outcome/phase1_agent_report.md`, and the full audit HTML.
2. The final `outcome/phase1_short_run_report.html` is the Codex-refined human review HTML. It is validated against the golden contract and must stay grounded in `report_pack.json`.

The script prints the `episode_id` and report path. Open:

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
```

Do not continue to T50 until a human accepts that report.

## Report-Only Regeneration

Use report-only mode to rebuild reports for an existing episode without advancing Civ6:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python scripts\codex_phase1_observe.py --report-only <episode_id>
```

This is useful after improving report rendering or the human HTML refinement. It must not launch the game, load a save, or run turns, and it must not change raw evidence.

## Acceptance Criteria

A short-run is acceptable only when all four evidence classes are present:

1. Tool/MCP calls: every call has timestamps, parameters, raw return content, and raw error content when errors occur.
2. Turn state: every turn start has a state snapshot covering empire, cities, units, notifications, threats, research/civic, and production, or an explicit gap with reason and next step.
3. Decisions: each important decision records trigger, background, current goal, `available_actions`, selected action, rationale, why alternatives were not chosen, execution, outcome, and related evidence IDs. The canonical fields are `why_not_alternatives`, `related_tool_call_ids`, `related_state_snapshot_ids`, and `related_save_ids`; `alternatives` and `evidence_ids` are also emitted as compatibility aliases for validators.
4. Saves: at least the starting save and key checkpoints are indexed with episode, turn, decision id or event, path, size, and SHA256.

The human report must prioritize decision readability and must satisfy the Human HTML Contract above. It should be easier to scan than the accepted baseline report: a reviewer should be able to follow the read path, compare the key numbers, skim each turn card, and inspect each decision card without opening raw evidence. It must link both the quick agent handoff and the full audit report. Raw JSON belongs in the Agent audit report and `report_pack.json`, not as the main human narrative.

## Validation

Before committing workflow changes, run:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m py_compile scripts\codex_phase1_observe.py
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python 'C:\Users\leftv0id\.codex\skills\.system\skill-creator\scripts\quick_validate.py' .codex\skills\civ6-phase1-observation
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python -m pytest tests/test_phase1_human_report_contract.py
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python scripts\codex_phase1_observe.py --report-only phase1_test1_short_20260512_130155
```

The final command is a regression check against the previously accepted human report shape. It should rebuild both reports and fail if `phase1_short_run_report.html` no longer matches the Human HTML Contract.

For fresh-session validation, use a separate agent with this prompt:

```text
Use .codex/skills/civ6-phase1-observation/SKILL.md.
Do not edit code, commit, or push.
Run a real 3-turn Phase 1 short-run on the test 1 single-player save.
Do not start a separate civ-mcp server; use only scripts/codex_phase1_observe.py.
Create a new episode id named phase1_subagent_validation_<timestamp>.
Stop before T50.
Return the episode_id, human report path, agent handoff path, agent audit report path, four evidence-class PASS/FAIL results, and blockers.
```

## Common Failures

| Symptom | Action |
| --- | --- |
| FireTuner cannot reconnect after loading | Confirm `EnableTuner=1`, close stale Civ6/civ-mcp processes, then rerun the short-run. The runner records failed reconnect attempts in `raw/tool_calls.jsonl`. |
| A previous validation left `civ-mcp` running | Rerun the normal command. The default preflight stops repo-local `civ-mcp` server processes and logs affected process ids. |
| A previous validation left Civ6 at the game screen or main menu | Rerun the normal command. The default preflight resets Civ6 before loading `test 1` from the front end. |
| Human report is raw JSON | Use `--report-only <episode_id>` after improving the report renderer or Codex refinement. Do not ask for acceptance from a field dump. |
| Next session gets stuck reading a huge audit HTML | Start from `outcome/phase1_agent_report.md`, then open `derived/report_pack.json`, and only use `phase1_agent_audit_report.html` for raw evidence drill-down. |
| Human HTML contract fails | Compare against `tests/fixtures/phase1_human_report_contract/contract.json` and `golden_skeleton.html`; fix the final human HTML shape, then rerun report-only. |

### Verified Runs

- `phase1_subagent_validation_20260512_165419` (fresh subagent validation, 2026-05-12): PASS. Default workflow reset a leftover Civ6 process, loaded the real single-player `test 1` save, advanced T1 -> T4 for a 3-turn short-run, generated both reports, and stopped before T50. Evidence counts: 83 tool calls, 174 MCP/Lua exchanges, 4 state snapshots, 15 decision atoms, 5 indexed saves. Four required evidence classes passed, and decision compatibility aliases `alternatives` / `evidence_ids` also passed.

## Commit Hygiene

`episodes/` is local run output and is ignored by default. Do not stage raw logs or `.Civ6Save` checkpoints unless the user explicitly asks for a specific episode artifact to be committed.

Recommended staged files for workflow changes:

- `scripts/codex_phase1_observe.py`
- `.codex/skills/civ6-phase1-observation/SKILL.md`
- `.codex/skills/civ6-phase1-observation/agents/openai.yaml`
- `docs/codex-hl-phase1-observation.md`
- `docs/README.md`
- `.gitignore`

Do not stage unrelated dirty files.

---
name: civ6-phase1-observation
description: Reproduce Codex HL Phase 1 observation-only runs for Civilization VI in this repo. Use when the user asks for Codex HL Phase 1, Civ6 observation, test 1 short-run/T50 validation, reusable observation workflow, or human/agent audit reports for a real Civ6 single-player save.
---

# Civ6 Phase 1 Observation

Use this skill to run the Codex HL Phase 1 observation workflow on the real `test 1` single-player save. The purpose is evidence capture, not strategy improvement.

## Hard Boundaries

- Use the existing local civ6-mcp repo and the real `test 1` single-player save.
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
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python scripts\codex_phase1_observe.py --save-name "test 1" --turns 3
   ```
   Use `--episode-id <id>` only when a stable validation name is needed.
   - Do not start a separate `civ-mcp` MCP server for this workflow. The runner talks directly to FireTuner.
   - By default the runner stops stale repo-local `civ-mcp` server processes and records that cleanup in `raw/tool_calls.jsonl`. Use `--keep-existing-mcp-server` only when a human explicitly asks to preserve an existing server process.
   - By default the runner also resets any running Civ6 process before loading `test 1`, so the run starts from a clean front-end load path. Use `--reuse-running-game` only for explicit manual debugging.
3. Verify the generated episode contains:
   - `header.json`
   - `raw/tool_calls.jsonl`
   - `raw/mcp.jsonl`
   - `raw/civ6_states/*.json`
   - `raw/saves/save_index.jsonl`
   - `derived/decision_atoms.jsonl`
   - `outcome/phase1_short_run_report.html`
   - `outcome/phase1_agent_audit_report.html`
4. Validate the four evidence classes:
   - all tool/MCP calls include time, params, raw result or error
   - every turn has a state snapshot covering empire, cities, units, notifications, threats, research/civic, production, or explicit gaps
   - decision records include `available_actions`, rationale, `why_not_alternatives`, execution, outcome, `related_*_ids`, plus compatibility aliases `alternatives` and `evidence_ids`
   - save index links saves to episode, turn, decision or event
5. Present the human report path and pause for human acceptance.

## Report Roles

- `phase1_short_run_report.html` is the human review report. It must be readable prose, especially the decision flow: observed situation, candidate actions, chosen action, why not alternatives, execution result, and review meaning.
- `phase1_agent_audit_report.html` is the machine/agent audit report. It may be large and table-heavy, but it must preserve raw JSON evidence and expandable details.
- If the human report reads like raw JSON or field dumps, regenerate or improve the report before asking for acceptance.

## Rebuild Existing Reports

Use report-only mode when the episode already exists and no Civ6 turn should be advanced:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run python scripts\codex_phase1_observe.py --report-only <episode_id>
```

Report-only mode must not launch Civ6 or modify the live game.

## Fresh Validation Prompt

When validating the skill with a fresh agent, use this prompt shape:

```text
Use .codex/skills/civ6-phase1-observation/SKILL.md.
Do not edit code, commit, or push.
Run a real 3-turn Phase 1 short-run on the test 1 single-player save.
Do not start a separate civ-mcp server; use only scripts/codex_phase1_observe.py.
Create a new episode id named phase1_subagent_validation_<timestamp>.
Stop before T50.
Return the episode_id, human report path, agent audit report path, four evidence-class PASS/FAIL results, and blockers.
```

## Commit Hygiene

- Commit the runner, this skill, and docs.
- Do not stage `episodes/` by default.
- Do not stage unrelated dirty files such as independent gameplay fixes or old experiment scripts unless the user explicitly includes them.

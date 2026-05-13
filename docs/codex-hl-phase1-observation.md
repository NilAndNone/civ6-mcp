# Codex HL Phase 1 Observation Workflow

This document is the development contract for the Phase 1 workflow inside the `codex-hl-civ6` plugin. Plugin usage instructions live in `plugin/AGENTS.md` and `plugin/skills/civ6-phase1-observation/SKILL.md`.

Phase 1 means observation only: record a real Civ6 game, produce reviewable evidence, and stop before any T50 continuation.

## What The Plugin Produces

The entrypoint `codex-hl-civ6-phase1-observe` runs the real `test 1` single-player save for 3-5 turns and writes an episode under `episodes/<episode_id>/`.

Each episode contains:

- `header.json`
- `raw/tool_calls.jsonl`
- `raw/mcp.jsonl`
- `raw/civ6_states/*.json`
- `raw/saves/save_index.jsonl` plus checkpoint `.Civ6Save` files
- `derived/decision_atoms.jsonl`
- `derived/report_pack.json`
- `outcome/phase1_short_run_report.draft.html`
- `outcome/phase1_short_run_report.html`
- `outcome/phase1_agent_report.md`
- `outcome/phase1_agent_audit_report.html`

The human report must explain the decision flow in Chinese prose. It must not become a JSON dump or audit table.

## Human HTML Contract

The human-facing artifact is always:

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
```

The report must keep this section flow:

1. `Codex HL Phase 1 人类验收报告`
2. `验收结论`
3. `我实际观测到的局面变化`, including `起点 T...` and `终点 T...`
4. `回合叙事`
5. `重点：决策流程`
6. `证据边界和你需要判断的点`
7. `存档和决策关联`
8. `缺口清单`
9. `面向 Agent 的报告`, linking to both `phase1_agent_report.md` and `phase1_agent_audit_report.html`

It must include the current readability floor: `先读这份报告的顺序`, `快速定位`, `关键数字变化`, card-based turn narrative, structured decision cards, compact save rows, and separate quick handoff / full audit tiles.

Each decision must render these labels:

- `当时看到的问题：`
- `候选动作：`
- `我选择了：`
- `为什么这样选：`
- `为什么没选其他动作：`
- `执行后结果：`
- `对 review 的意义：`

Raw evidence belongs in `phase1_agent_audit_report.html`, `derived/report_pack.json`, `raw/*.jsonl`, `raw/civ6_states/*.json`, and `derived/decision_atoms.jsonl`.

The contract fixture lives in `plugin/fixtures/phase1_human_report_contract/`.

## Fresh Session Procedure

Start in the plugin development checkout on Windows:

```powershell
Set-Location O:\civ6\codex-hl-civ6
& 'C:\Program Files\Git\cmd\git.exe' status --short --branch --untracked-files=all
```

Read the plugin skill:

```text
plugin/skills/civ6-phase1-observation/SKILL.md
```

Run a short validation episode:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
```

Do not start a separate `civ6-connector` server for this flow. The runner talks directly to FireTuner and stops stale repo-local connector processes by default.

The command prints the `episode_id` and report path. Open:

```text
episodes/<episode_id>/outcome/phase1_short_run_report.html
```

Do not continue to T50 until a human accepts that report.

## Report-Only Regeneration

Use report-only mode to rebuild reports for an existing episode without advancing Civ6:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

Report-only mode must not launch the game, load a save, or run turns.

## Acceptance Criteria

A short-run is acceptable only when all four evidence classes are present:

1. Tool and connector calls include timestamps, params, raw return content, and raw errors when errors occur.
2. Turn state snapshots cover empire, cities, units, notifications, threats, research/civic, and production, or include explicit gaps.
3. Decision records include trigger, background, current goal, `available_actions`, selected action, rationale, why alternatives were not chosen, execution, outcome, and related evidence IDs.
4. Saves link to episode, turn, decision id or event, path, size, and SHA256.

The short-run must stop after the human report. It must not proceed to T50 automatically.

## Local Validation

Before reporting local development complete, run:

```bash
uv run python -m py_compile plugin/src/codex_hl/phase1/observer.py plugin/src/civ6_connector/server.py
uv run pytest tests/test_plugin_structure.py tests/test_phase1_human_report_contract.py -q
uv run pytest tests -q
```

On Windows, additionally run the real 3-turn short-run command above. The Mac checkout can validate packaging and report contracts, but it cannot replace the Windows Civ6 run.

## Common Failures

| Symptom | Action |
| --- | --- |
| FireTuner cannot reconnect after loading | Confirm `EnableTuner=1`, close stale Civ6/connector processes, rerun the short-run, and inspect `raw/tool_calls.jsonl`. |
| A previous validation left a connector server running | Rerun without `--keep-existing-mcp-server`; default preflight stops repo-local connector server processes. |
| A previous validation left Civ6 at the game screen or main menu | Rerun without `--reuse-running-game`; default preflight resets Civ6 before loading `test 1`. |
| Human report is raw JSON | Fix the report renderer, then rerun report-only. |
| Human HTML contract fails | Compare against `plugin/fixtures/phase1_human_report_contract/contract.json` and `golden_skeleton.html`, then rerun report-only. |

## Commit Hygiene

- Keep `episodes/` untracked unless the user asks for a specific artifact.
- Keep active changes in `plugin/`, `docs/`, `tests/`, `pyproject.toml`, `.github/`, and root development docs.
- Keep old CivBench/web/eval assets in `archive/legacy/`.

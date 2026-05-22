# Asset: playbook.phase1_observation

## Purpose

This playbook defines the Phase 1 short-run and T50 observation workflow for the
installed plugin.

## Short-Run Flow

1. Confirm the repo root and branch. If `git` is not on PATH, use
   `C:\Program Files\Git\cmd\git.exe`.
2. Check `git status --short --branch --untracked-files=all` and do not revert
   unrelated dirty files.
3. Run a short observation on the real `test 1` single-player save:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
   ```

4. Use a stable `--episode-id <id>` only when the validation needs a stable name.
5. Do not start a separate `civ6-connector` service. The runner connects through
   the normal Phase 1 path.
6. Do not use `--keep-existing-mcp-server` or `--reuse-running-game` unless the
   user is explicitly doing manual troubleshooting.
7. After the report is generated, stop and return the episode id, Chinese human
   report path, agent handoff path, audit report path, and evidence PASS/FAIL
   status.

## T50 Flow

1. Run T50 only after the user explicitly accepts the short-run report or asks
   for T50 on that basis.
2. Use one complete episode from the real `test 1` start point:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 50
   ```

3. Do not stitch multiple short episodes into T50.
4. If the runner rejects `--turns 50`, fix the runner rather than faking T50.
5. T50 is still Phase 1 observation: it records evidence and stops at the
   report. It does not enter Phase 2, T51+, strategy optimization, Replay Arena,
   or asset promotion.

## Required Episode Artifacts

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
- `assets_snapshot/active_assets.json` for new Phase 3-aware runs

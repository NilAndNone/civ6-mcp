# /civ6-phase1-observe

Run a Codex HL Phase 1 observation short-run.

## Arguments

- `save_name`: optional, defaults to `test 1`
- `turns`: optional, defaults to `3`; must stay between 3 and 10 for short-run validation
- `episode_id`: optional stable episode id

## Workflow

1. Read `plugin/AGENTS.md`.
2. Use `plugin/skills/civ6-phase1-observation/SKILL.md`.
3. Run:
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
   ```
4. Open the generated `phase1_short_run_report.html` path for review.
5. Stop before T50.

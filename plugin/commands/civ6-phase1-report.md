# /civ6-phase1-report

Regenerate Phase 1 reports for an existing episode without advancing Civilization VI.

## Arguments

- `episode_id`: required

## Workflow

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --report-only <episode_id>
```

Report-only mode must not launch Civ6 or move the live game forward.

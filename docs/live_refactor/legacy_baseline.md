# Legacy Baseline Runner

Phase 3 keeps the old Observation rules runner as an explicit baseline only.

## Allowed Uses

- `codex-hl-civ6-runs --execute --runner legacy-baseline` for baseline comparison.
- `/civ6-observe` for compatibility, report rebuilds, and old episode inspection.
- Review/Strategy/Governance may continue reading old episodes.

## Not Allowed

- `--execute` without `--runner`.
- Treating `/civ6-observe` as the default real game path.
- Deleting or archiving the legacy runner during Phase 3.

## Live Main Path

Use `/civ6-observe-live` or:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-runs --execute --runner live --turns 20 --save-name "test 1"
```

The live path routes through JSON plan lifecycle artifacts and live strict MCP
guards. It does not call the old `codex_hl.evidence.observation` rules runner.

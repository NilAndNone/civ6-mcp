# /civ6-runs

## Purpose

Orchestrate offline Review candidates, Strategy Candidate artifacts,
validation reports, checkpoint reports, and guarded governance.

`/civ6-runs` is offline-only. The real-game execution route has been removed:
`--execute`, `--runner live`, and any runner-backed live mutation fail before
connector startup. Use `/civ6-observe-live` for real Civ6 gameplay.

## Inputs

- `--turns 3|20|50`
- `--cycles <n>`
- `--episodes-per-cycle <n>`
- `--save-name "test 1"`
- `--execute`: removed; hard error.
- `--runner live`: removed; hard error.
- `--allow-auto-confirmation`: enable restricted auto-confirmation.
- `--auto-iterate-strategy`: allow runtime strategy profile changes between
  episodes.
- `--candidate-package <candidate.json>`: pass a read-only candidate package
  into the runtime.
- `--candidate-runtime-applied`: assert that the validation report came from
  candidate runtime episodes.
- `--allow-merge`: enter governance merge only after gates pass.

## Runtime Routing

- `/civ6-runs` writes plan manifests and reads existing evidence.
- `--execute` has been removed and does not launch Civ6.
- `--runner live` has been removed and does not launch Civ6.
- Removed runner values fail explicitly before any connector or game mutation.
- Candidate packages are read-only runtime inputs; they do not directly mutate
  strategy assets.
- Governance merge remains gated and requires explicit `--allow-merge`.

## Examples

Plan only:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-runs --turns 20 --cycles 1 --episodes-per-cycle 3
```

Checkpoint from existing episodes:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-runs --checkpoint-only --checkpoint-episodes <episode_id> --turns 50
```

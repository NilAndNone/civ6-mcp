# /civ6-runs

## Purpose

Orchestrate multi-run T3/T20/T50 live strict episodes, offline Review
candidates, optional auto-confirmation, Strategy Candidate artifacts, validation
reports, and guarded governance.

## Inputs

- `--turns 3|20|50`
- `--cycles <n>`
- `--episodes-per-cycle <n>`
- `--save-name "test 1"`
- `--execute`: launch real Civ6 runs.
- `--runner live`: required with `--execute`.
- `--allow-auto-confirmation`: enable restricted auto-confirmation.
- `--auto-iterate-strategy`: allow runtime strategy profile changes between
  episodes.
- `--candidate-package <candidate.json>`: pass a read-only candidate package
  into the runtime.
- `--candidate-runtime-applied`: assert that the validation report came from
  candidate runtime episodes.
- `--allow-merge`: enter governance merge only after gates pass.

## Runtime Routing

- Without `--execute`, `/civ6-runs` writes a plan manifest only.
- With `--execute`, `/civ6-runs --runner live` shells into
  `codex_hl.live.driver`.
- Removed runner values fail explicitly and do not launch any game mutation.
- Candidate packages are read-only runtime inputs; they do not directly mutate
  strategy assets.
- Governance merge remains gated and requires explicit `--allow-merge`.

## Examples

Plan only:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-runs --turns 20 --cycles 1 --episodes-per-cycle 3
```

Execute T3 live strict:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-runs --execute --runner live --turns 3 --save-name "test 1" --cycles 1 --episodes-per-cycle 1
```

Execute T50 live strict with a candidate runtime package:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-runs --execute --runner live --turns 50 --save-name "test 1" --cycles 1 --episodes-per-cycle 5 --candidate-package <candidate.json> --candidate-runtime-applied
```

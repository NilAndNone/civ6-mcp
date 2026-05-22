# Asset: playbook.phase2_offline_labeling

## Purpose

This playbook defines the Phase 2 v1 offline labeling loop over an existing
Phase 1 episode.

## Flow

1. Read only `episodes/<episode_id>/`.
2. Generate candidate failures and the static review page:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id>
   ```

3. Treat `phase2/candidates.jsonl` as candidate-only output.
4. Use `phase2/phase2_review.html` as the human review entry.
5. Write confirmation rows only under `phase2/confirmation/confirmation.jsonl`.
6. Apply confirmation only when the human confirmation file exists:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase2-label --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\phase2\confirmation\confirmation.jsonl
   ```

## Boundaries

- Do not start Civ6.
- Do not load saves.
- Do not advance turns.
- Do not write formal `failures.jsonl` or `regression_seeds.jsonl` before
  explicit `--apply-confirmation`.
- Do not emit fixes, rerun commands, replay targets, strategy patches, or asset
  changes.
- Short-validation planning failures must remain scoped to
  `local_episode_fragment` and must not be used as long-horizon conclusions or
  asset-change evidence.

## Formal Outputs After Apply

- `phase2/failures.jsonl`
- `phase2/regression_seeds.jsonl`
- `phase2/phase2_summary.md`
- `phase2/phase2_summary.json`
- updated `phase2/phase2_review.html`

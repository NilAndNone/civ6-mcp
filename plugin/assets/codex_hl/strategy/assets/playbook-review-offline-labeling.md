# Asset: strategy.playbook.failure_review

## Purpose

This playbook defines the Review v1 offline labeling loop over an existing
observation episode.

## Flow

1. Read only `episodes/<episode_id>/`.
2. Generate candidate failures and the static review page:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-review --episode-id <episode_id>
   ```

3. Treat `review/candidates.jsonl` as candidate-only output.
4. Use `review/review.html` as the human review entry.
5. Write confirmation rows only under `review/confirmation/confirmation.jsonl`.
6. Apply confirmation only when the human confirmation file exists:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-review --episode-id <episode_id> --apply-confirmation episodes\<episode_id>\review\confirmation\confirmation.jsonl
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

- `review/failures.jsonl`
- `review/regression_seeds.jsonl`
- `review/review_summary.md`
- `review/review_summary.json`
- updated `review/review.html`

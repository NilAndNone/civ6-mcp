# Phase 4 Candidate Improvements Playbook

Phase 4 starts only after Phase 2 has produced formal failures through human confirmation.

Rules:

- Read confirmed failures from `episodes/<episode_id>/phase2/failures.jsonl`.
- Read passive seeds from `episodes/<episode_id>/phase2/regression_seeds.jsonl` when available.
- Select a target asset from the active Phase 3 catalog by capability dimension.
- Produce a candidate package with source failure, target asset, proposed content, asset diff, validation plan, risk assessment, and rollback plan.
- Write only under `episodes/<episode_id>/phase4/`.
- Do not edit asset files, catalog, ledger, saves, or Civ6 state.
- Do not claim a candidate is generally better before Phase 5/L4 validation.

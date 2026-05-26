# Strategy Candidate Improvements Playbook

Strategy Candidate starts only after Review has produced formal failures through human confirmation.

Rules:

- Read confirmed failures from `episodes/<episode_id>/review/failures.jsonl`.
- Read passive seeds from `episodes/<episode_id>/review/regression_seeds.jsonl` when available.
- Select a target asset from the active strategy catalog by capability dimension.
- Produce a candidate package with source failure, target asset, proposed content, asset diff, validation plan, risk assessment, and rollback plan.
- Write only under `episodes/<episode_id>/strategy/candidates/`.
- Do not edit asset files, catalog, ledger, saves, or Civ6 state.
- Do not claim a candidate is generally better before validation scenarios and governance gates pass.

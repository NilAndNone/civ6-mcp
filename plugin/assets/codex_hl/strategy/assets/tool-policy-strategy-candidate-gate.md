# Strategy Candidate Gate Tool Policy

Candidate generation is an offline packaging step.

Required gates:

- A candidate must reference at least one formal Review failure.
- A candidate must keep the target asset's current version and hash.
- A candidate must include a rollback plan before it can enter governance.
- A candidate must require at least two scenarios before merge.
- A candidate must not start Civ6, replay saves, or run a validation arena.
- A candidate must be `candidate_only` and `auto_merge_allowed=false`.

Any missing gate blocks L4/L5 merge.

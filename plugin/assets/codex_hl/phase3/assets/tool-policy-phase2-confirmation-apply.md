# Asset: tool_policy.phase2_confirmation_apply

## Purpose

This tool policy defines what Phase 2 confirmation and apply may write.

## Confirmation Policy

- The local labeler binds only to `127.0.0.1`.
- The labeler may write only under `episodes/<episode_id>/phase2/confirmation/`.
- Confirmation rows use `action` values `accept`, `reject`, or `modify`.
- `modify` may edit only the allowed failure-label fields in the Phase 2 tool.

## Apply Policy

- Apply validates that Phase 1 input hash is unchanged.
- Apply validates that every candidate id exists.
- Apply validates that evidence references resolve back to Phase 1 evidence.
- Apply enforces one confirmed failure to one passive regression seed.
- Apply must reject fields that imply asset edits, reruns, replays, or fixes.

## Forbidden Formal Fields

- `suggested_fix`
- `asset_diff`
- `prompt_update`
- `playbook_change`
- `tool_policy_change`
- `memory_update`
- `strategy_patch`
- `replay_target`
- `rerun_command`
- `arena_run`
- `replay_from_save`
- `auto_rerun`

## Phase Boundary

Formal Phase 2 outputs are evidence and passive seeds only. They are not
instructions to modify assets, rerun games, or promote a strategy.

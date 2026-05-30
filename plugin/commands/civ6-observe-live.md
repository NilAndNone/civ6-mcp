# /civ6-observe-live

## Purpose

Use the interactive MCP-driven live strict workflow. This is the manual/agent
operation path: every mutating L2+ action must be tied to an active
`episode_id`, submitted JSON plan, armed step, and captured `context_hash`.

## Flow

1. Call `start_live_episode`.
2. For each turn, call `get_live_turn_context` and keep the returned
   `context_hash`.
3. Submit a JSON plan with `submit_turn_plan`.
4. Arm each mutating step with `arm_live_step`.
5. Execute the matching MCP action with the live parameters from the armed step.
6. Repeat context/plan/arm/action until the objective is complete.
7. Call `finish_live_episode`; use `abort_live_episode` for explicit stop.

## Boundaries

- Default mode is live strict.
- Python fragments stay disabled unless explicitly enabled by environment.
- Verifier decisions must come from observable post-state, not Codex self-rating.
- `episodes/` contains local runtime artifacts and should not be committed by
  default.

## Example

```text
/civ6-observe-live --save-name "test 1" --turns 3 --strict-live
```

For automated T3/T20/T50 runs, use `/civ6-live-driver` or
`/civ6-runs --runner live`.

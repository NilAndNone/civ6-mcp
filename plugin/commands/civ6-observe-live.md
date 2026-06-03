# /civ6-observe-live

## Purpose

Use the interactive MCP-driven live strict workflow. This is the manual/agent
operation path: every mutating L2+ action must be tied to an active
`episode_id`, submitted JSON plan, armed step, and captured `context_hash`.

This is the gameplay path for Human Demo reproduction. Every plan must be
authored by the model from the latest observed context; do not substitute
Python/profile-generated live-driver plans for Human Demo acceptance.

## Flow

1. Call `start_live_episode`.
2. For each turn, call `get_live_turn_context` and keep the returned
   `context_hash`.
3. Retrieve the relevant active strategy assets and Civ6 wiki chunks for the
   current situation.
4. The model authors a small JSON plan for the immediate turn context.
5. Submit the JSON plan with `submit_turn_plan`.
6. Arm each mutating step with `arm_live_step`.
7. Execute the matching MCP action with the live parameters from the armed step.
8. Repeat context/plan/arm/action through the turn. After `end_turn`, capture a
   fresh context before planning the next turn.
9. Call `finish_live_episode`; use `abort_live_episode` for explicit stop.

## Boundaries

- Default mode is live strict.
- Python fragments stay disabled unless explicitly enabled by environment.
- Verifier decisions must come from observable post-state, not Codex self-rating.
- Human Demo reproduction must stay small-grained: no multi-turn automated
  scripts, no precomputed driver strategy, and no claiming success from an
  automated live-driver episode.
- Knowledge base and strategy assets constrain the plan, but they do not
  replace the model's decision from the latest observed live context.
- `episodes/` contains local runtime artifacts and should not be committed by
  default.

## Example

```text
/civ6-observe-live --save-name "test 1" --turns 3 --strict-live
```

For Human Demo learning, use `/civ6-human-demo-record` to capture the reference
demo and `/civ6-human-demo-contract` to score reproduction evidence.

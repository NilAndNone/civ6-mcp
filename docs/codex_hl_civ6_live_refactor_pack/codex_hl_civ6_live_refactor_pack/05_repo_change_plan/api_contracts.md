# Live API Contracts

## MCP lifecycle tools

### start_live_episode

Input:

```json
{
  "save_name": "test 1",
  "target_turns": 3,
  "mode": "live_strict",
  "runner": "live-json-plan"
}
```

Output:

```json
{
  "episode_id": "live_test1_short_20260529_120000",
  "branch_id": "b000",
  "status": "EPISODE_STARTED",
  "ledger_db": "episodes/.../episode.db"
}
```

### get_live_turn_context

Output:

```json
{
  "episode_id": "...",
  "turn": 12,
  "branch_id": "b000",
  "context_hash": "sha256:...",
  "overview": {},
  "cities": [],
  "units": [],
  "notifications": [],
  "available_action_summary": []
}
```

### submit_turn_plan

Input: `live_turn_plan.schema.json`。

Output:

```json
{
  "accepted": true,
  "plan_id": "plan_t0012_v01",
  "status": "PLAN_SUBMITTED",
  "step_count": 5
}
```

### arm_live_step

Input:

```json
{
  "episode_id": "...",
  "plan_id": "plan_t0012_v01",
  "step_id": "s001"
}
```

Output:

```json
{
  "armed": true,
  "status": "STEP_ARMED"
}
```

### finish_live_episode

Must fail if:

- unverified executed step exists；
- unplanned L2+ mutation exists in live strict；
- state machine not terminal-safe；
- target turn boundary violated。

## Mutating tool additional parameters

所有 L2+ MCP tools 在 live strict mode 下必须支持：

```json
{
  "episode_id": "...",
  "plan_id": "...",
  "step_id": "...",
  "context_hash": "sha256:..."
}
```

兼容模式下这些参数可选。

## Gateway rejection format

```json
{
  "allowed": false,
  "error_code": "LIVE_PLAN_STEP_REQUIRED",
  "message": "unit_action is L3 and requires active plan_id + step_id in LIVE_STRICT mode.",
  "episode_id": "...",
  "tool": "unit_action"
}
```

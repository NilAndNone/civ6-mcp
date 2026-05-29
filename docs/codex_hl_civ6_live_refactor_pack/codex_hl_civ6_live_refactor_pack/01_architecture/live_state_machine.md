# Live Episode State Machine

## 目标

所有 live operation 必须有状态约束。没有状态机，`start_live_episode`、`submit_turn_plan`、`execute_live_fragment` 只是松散 RPC，无法防 stale plan、重复执行、跨回合误执行和恢复串线。

## 状态

```text
IDLE
EPISODE_STARTED
TURN_CONTEXT_READY
PLAN_SUBMITTED
STEP_ARMED
STEP_EXECUTING
STEP_EXECUTED
STEP_VERIFIED
TURN_COMPLETED
NEED_RECOVERY_PLAN
RESTORED
EPISODE_FINISHED
ABORTED
```

## 主路径

```text
IDLE
  -> start_live_episode
EPISODE_STARTED
  -> get_live_turn_context
TURN_CONTEXT_READY
  -> submit_turn_plan
PLAN_SUBMITTED
  -> arm_plan_step
STEP_ARMED
  -> execute_mutating_action
STEP_EXECUTING
  -> action_result_captured
STEP_EXECUTED
  -> verify_step
STEP_VERIFIED
  -> next step or end_turn
TURN_COMPLETED
  -> next turn context or finish_live_episode
EPISODE_FINISHED
```

## 异常路径

```text
STEP_EXECUTED --postcondition_fail--> NEED_RECOVERY_PLAN
STEP_EXECUTING --tool_error--> NEED_RECOVERY_PLAN
TURN_COMPLETED --wrong_turn_delta--> NEED_RECOVERY_PLAN
NEED_RECOVERY_PLAN --submit_recovery_plan--> PLAN_SUBMITTED
NEED_RECOVERY_PLAN --restore_checkpoint--> RESTORED
RESTORED --get_live_turn_context--> TURN_CONTEXT_READY
ANY --abort_live_episode--> ABORTED
```

## Step 状态

```text
PENDING
ARMED
EXECUTING
EXECUTED
VERIFIED_PASS
VERIFIED_FAIL
SKIPPED
INVALIDATED_BY_RESTORE
```

## 强约束

1. L2+ action 只能在 `STEP_ARMED` 执行。
2. 同一 step 默认只能执行一次。
3. 如果 step 需要 retry，必须创建新 step version，例如 `s003_r01`。
4. `end_turn` 是 L4 action，必须绑定 turn completion step。
5. `restart/load/restore` 是 recovery action，必须处于 `NEED_RECOVERY_PLAN` 或 explicit recovery step。
6. restore 后必须创建新的 branch_id，并 invalidated 后续旧 steps。
7. `finish_live_episode` 必须验证没有 unverified executed steps。

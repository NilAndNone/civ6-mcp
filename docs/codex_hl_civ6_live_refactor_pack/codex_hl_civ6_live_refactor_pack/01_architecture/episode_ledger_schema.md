# Episode Ledger / DB Schema 设计

## 核心原则

`episode.db` / append-only ledger 是 source of truth。raw JSONL、HTML、Markdown、report pack 都是导出视图。不要再让 finalization 从 raw 文件“导入”来决定事实。

## 建议新增表

### live_events

```sql
CREATE TABLE IF NOT EXISTS live_events(
  event_id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  turn INTEGER,
  branch_id TEXT,
  event_type TEXT NOT NULL,
  plan_id TEXT,
  step_id TEXT,
  tool TEXT,
  mutation_level TEXT,
  source TEXT,
  context_hash TEXT,
  pre_state_hash TEXT,
  post_state_hash TEXT,
  payload_json TEXT NOT NULL,
  UNIQUE(episode_id, seq)
);
```

### live_plans

```sql
CREATE TABLE IF NOT EXISTS live_plans(
  episode_id TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  turn INTEGER NOT NULL,
  branch_id TEXT NOT NULL,
  context_hash TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  objective TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(episode_id, plan_id)
);
```

### live_steps

```sql
CREATE TABLE IF NOT EXISTS live_steps(
  episode_id TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  turn INTEGER NOT NULL,
  branch_id TEXT NOT NULL,
  status TEXT NOT NULL,
  tool TEXT NOT NULL,
  mutation_level TEXT NOT NULL,
  args_json TEXT NOT NULL,
  preconditions_json TEXT,
  postconditions_json TEXT,
  verifier_status TEXT,
  verifier_json TEXT,
  result_json TEXT,
  error_text TEXT,
  checkpoint_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(episode_id, plan_id, step_id)
);
```

### live_checkpoints

```sql
CREATE TABLE IF NOT EXISTS live_checkpoints(
  episode_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  branch_id TEXT NOT NULL,
  turn INTEGER,
  step_id TEXT,
  save_id TEXT,
  save_path TEXT,
  sha256 TEXT,
  reason TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY(episode_id, checkpoint_id)
);
```

### live_branches

```sql
CREATE TABLE IF NOT EXISTS live_branches(
  episode_id TEXT NOT NULL,
  branch_id TEXT NOT NULL,
  parent_branch_id TEXT,
  restored_from_checkpoint_id TEXT,
  restored_from_step_id TEXT,
  reason TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY(episode_id, branch_id)
);
```

## 必须导出的兼容路径

```text
raw/live_events.jsonl
raw/live_turn_contexts.jsonl
raw/live_turn_plans.jsonl
raw/live_step_runs.jsonl
raw/live_pre_step_saves.jsonl
raw/live_restores.jsonl
derived/live_plan_outcomes.jsonl
derived/decision_atoms.jsonl
```

## 崩溃一致性

每个 step 至少写这些 event：

```text
STEP_ARMED
PRE_STATE_CAPTURED
CHECKPOINT_CREATED?   # 按 mutation level
ACTION_STARTED
ACTION_FINISHED | ACTION_FAILED
POST_STATE_CAPTURED
STEP_VERIFIED
```

如果进程在中间崩溃，恢复时必须能根据最后 event 判断：

- action 未开始；
- action 可能已开始但无结果；
- action 已执行但未验证；
- action 已验证失败，需要 recovery plan；
- restore 后旧 branch steps invalidated。

# /civ6-observe-live

## 用途

运行 Phase 2 live 主线：JSON plan + armed step gate。所有 L2+ mutating
MCP action 必须绑定 `episode_id`、`plan_id`、`step_id` 和 `context_hash`。

## 流程

1. 调用 `start_live_episode`。
2. 每回合调用 `get_live_turn_context`，取得 `context_hash`。
3. 调用 `submit_turn_plan` 提交 JSON plan。
4. 每个 mutating step 执行前调用 `arm_live_step`。
5. 调用对应 MCP action，并传入 live 参数。
6. 回合结束后重复 context/plan/arm/action。
7. 调用 `finish_live_episode`；如果需要中止，调用 `abort_live_episode`。

## 边界

- 默认使用 live strict。
- 不启用 Python fragment。
- 不使用 `register_live_fragment` 或 `execute_live_fragment`。
- verifier 只接受可观测 post-state，不把 Codex 自评当 outcome。
- `episodes/` 是本地产物，默认不提交。

## 示例

```text
/civ6-observe-live --save-name "test 1" --turns 3 --strict-live
```

真实 T3 验收需要 Windows Civ6/FireTuner 运行时和安装后的 MCP tools。

# Phase 4 — Optional Safe Python Fragment

## TL;DR

只有在 JSON plan + step gate 稳定后，才引入 Python fragment；fragment 不能成为多步自由执行器，只能作为单 step helper。


## 目标

- 新增 `register_live_fragment` / `execute_live_fragment`，但默认关闭。
- fragment 必须绑定单个 plan step。
- fragment 只能调用 `live.*` 受控 API。
- fragment 不得获得 raw `GameState`、`GameConnection`、filesystem write、network、shell。

## 安全要求

仅 AST 白名单不够。必须加：

- out-of-process worker；
- hard timeout；
- output limit；
- restricted builtins；
- no repo write permission；
- no network；
- no arbitrary import；
- no `open/subprocess/eval/exec/compile/__import__`；
- no mutation loop beyond one armed step；
- fragment source hash + plan binding；
- execution trace in ledger。

## 允许形态

```python
def run(live):
    ctx = live.read_context()
    live.assert_precondition("unit_exists", unit_id=12345)
    result = live.unit_action(
        episode_id="...",
        plan_id="plan_t0012_v01",
        step_id="s003",
        unit_id=12345,
        action="move",
        target_x=17,
        target_y=23,
    )
    live.assert_postcondition("unit_at_or_blocked", unit_id=12345, x=17, y=23)
    return {"result": result}
```

## 禁止形态

- 一个 fragment 执行整回合。
- fragment 自己生成新 plan。
- fragment 自己调用 restore。
- fragment 循环调用多个 mutating tool。
- fragment 写 repo / episodes 外路径。
- fragment outcome 自评覆盖 verifier。

## 测试

```text
tests/test_live_fragment_ast.py
tests/test_live_fragment_sandbox.py
tests/test_live_fragment_step_binding.py
```

## 验收

PASS 条件：

- fragment 可执行只读 helper。
- fragment 执行单个 armed step。
- 违反 sandbox / 多步 mutation / args mismatch 均拒绝。
- 不启用 fragment 时 live JSON plan 主路径仍可运行。

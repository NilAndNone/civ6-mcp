# ActionGateway / MutationGateway 设计

## 问题

如果只在 MCP tool 层加 guard，旧 observation runner 仍然可以直接调用 `GameState` mutating methods，绕过所有 live plan 检查。因此 guard 必须下沉为统一执行网关。

## 目标接口草案

```python
@dataclass(frozen=True)
class ActionRequest:
    source: Literal["mcp", "legacy_runner", "live_plan", "fragment", "recovery"]
    tool_name: str
    args: dict[str, Any]
    mutation_level: MutationLevel
    episode_id: str | None = None
    turn: int | None = None
    plan_id: str | None = None
    step_id: str | None = None
    context_hash: str | None = None
    idempotency_key: str | None = None

@dataclass(frozen=True)
class ActionResult:
    request_id: str
    allowed: bool
    status: Literal["executed", "rejected", "failed", "verified", "inconclusive"]
    result: Any = None
    error: str | None = None
    pre_state_hash: str | None = None
    post_state_hash: str | None = None
    verifier_status: str | None = None
    ledger_event_ids: list[str] = field(default_factory=list)
```

## Gateway mode

```python
class GatewayMode(str, Enum):
    LEGACY_COMPAT = "legacy_compat"  # 记录但不阻断
    SHADOW = "shadow"                # 标红违规，但不改变旧行为
    LIVE_STRICT = "live_strict"      # 无 plan step 直接拒绝
```

## 执行规则

### LEGACY_COMPAT / SHADOW

- 允许旧 runner 继续运行。
- 所有 L2+ action 必须写 ledger/shadow provenance。
- 无 plan 的 action 标记为 `unplanned_mutation=true`。
- 不阻断旧测试。

### LIVE_STRICT

- L2+ 必须有 active episode。
- L2+ 必须绑定 plan_id + step_id。
- step 必须处于 `ARMED`。
- args 必须匹配 plan step。
- context_hash 必须匹配或被明确声明可过期。
- L4 recovery 必须来自 recovery plan。
- 透明 recovery 禁止直接执行。

## 执行入口统一

目标：所有真实游戏 mutation 最终都类似这样：

```python
return await gateway.execute(
    ActionRequest(
        source="mcp",
        tool_name="unit_action",
        args={"unit_id": unit_id, "action": action, ...},
        mutation_level=MutationLevel.L2,
        episode_id=episode_id,
        plan_id=plan_id,
        step_id=step_id,
    ),
    lambda: gs.move_unit(unit_index, target_x, target_y),
)
```

## 禁止事项

- 禁止 live mode 下绕过 gateway 直接调用 `gs.end_turn()`、`gs.move_unit()`、`gs.propose_trade()` 等。
- 禁止 `_logged` 自动执行 restart/load/submit congress 等 mutating recovery。
- 禁止 fragment 获得 raw `GameState` 或 `GameConnection`。

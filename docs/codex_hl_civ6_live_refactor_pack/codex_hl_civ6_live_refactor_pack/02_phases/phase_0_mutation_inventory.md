# Phase 0 — Mutation Inventory

## TL;DR

只做盘点、分类、测试和文档，不改变真实 Civ6 行为。目标是证明团队知道所有能改游戏状态的路径在哪里。


## 目标

- 建立 MutationLevel / ActionKind 分类。
- 盘点 MCP action tools、`GameState` mutating methods、observation runner 直接调用点、save/load/restart/raw Lua 路径。
- 新增测试：未分类 L2+ action 失败。
- 产出 `docs/live_refactor/phase_0_inventory.md`。

## 禁止

- 不新增 `/civ6-observe-live` 可用主路径。
- 不改变 `/civ6-observe` 行为。
- 不 archive legacy runner。
- 不实现 fragment executor。

## 任务

1. 新增模块建议：

```text
plugin/src/codex_hl/live/__init__.py
plugin/src/codex_hl/live/actions.py
plugin/src/codex_hl/live/inventory.py
plugin/src/codex_hl/live/mutation_levels.py
```

2. 在 `mutation_levels.py` 定义：

```python
class MutationLevel(str, Enum):
    L0_READ = "L0"
    L1_RUNTIME_SIDE_EFFECT = "L1"
    L2_LOW_GAME_MUTATION = "L2"
    L3_HIGH_GAME_MUTATION = "L3"
    L4_BOUNDARY_RECOVERY = "L4"
    L5_UNSAFE_ESCAPE = "L5"
```

3. 在 `actions.py` 定义 action registry：

```python
@dataclass(frozen=True)
class ActionSpec:
    tool_name: str
    mutation_level: MutationLevel
    game_state_methods: tuple[str, ...] = ()
    checkpoint_policy: str = "auto_by_level"
    description: str = ""
```

4. 用单测固定初始 registry。
5. 写静态检测脚本或测试，扫描 `observation.py` 中潜在 mutating `gs.*` 调用，输出待接管清单。

## 测试建议

```text
tests/test_live_mutation_inventory.py
tests/test_live_action_registry.py
```

测试点：

- 所有已知 MCP action tool 都在 registry。
- `unit_action` 子 action 有分级。
- `end_turn`、save/load/restart/raw Lua 是 L4。
- 新增 `@mcp.tool()` action 未登记时测试失败。
- inventory 发现 `observation.py` 仍有 direct GameState mutation，并以文档形式列出。

## 验收

PASS 条件：

- 旧测试不退化。
- 新 registry 单测通过。
- 盘点文档列出所有绕过点。
- 没有改真实运行行为。

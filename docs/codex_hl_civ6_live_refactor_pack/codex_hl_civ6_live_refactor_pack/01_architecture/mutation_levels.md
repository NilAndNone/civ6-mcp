# Mutation Levels

## 分类原则

不要用 read/write 二分。当前系统里很多 read-only tool 会写 logger、heartbeat、camera、spatial，这些是 runtime side effect，不等于 game-state mutation。

| Level | 类型 | 示例 | live strict 策略 |
|---|---|---|---|
| L0 | Pure read | get_units, get_cities, get_tech_civics | trace only |
| L1 | Runtime side effect | heartbeat, logger, camera.push, spatial.record | trace only, no plan required |
| L2 | Low-impact game mutation | set_research, set_civic, unit skip/fortify, policy set | plan step required; checkpoint optional |
| L3 | High-impact game mutation | purchase, found city, trade, declare war, governor, city production | plan step + pre-checkpoint + postcheck |
| L4 | Boundary/recovery mutation | end_turn, load/save/restart, raw run_lua ingame, submit congress | explicit turn/recovery plan + stricter gate |
| L5 | Escape hatch / unsafe | raw Lua write, shell, repo write, arbitrary fragment side effect | default disabled |

## 初始 action 分类建议

### L2

- `set_research`
- `set_policies`
- `unit_action` with `fortify`, `skip`, `heal`, `alert`, `sleep`
- `promote_unit`
- `send_envoy`
- `choose_pantheon`
- `choose_dedication`

### L3

- `unit_action` with `move`, `attack`, `found_city`, `improve`, `remove_feature`, `trade_route`, `activate`, `teleport`, `spread_religion`
- `city_action` with `attack`, `keep`, `reject`, `raze`, `liberate_*`
- `set_city_production`
- `purchase_item`
- `respond_to_trade`
- `propose_trade`
- `propose_peace`
- `send_diplomatic_action`
- `form_alliance`
- `appoint_governor`, `assign_governor`, `promote_governor`
- `found_religion`
- `upgrade_unit`
- `skip_remaining_units`

### L4

- `end_turn`
- `save_game`
- `load_game_save`
- `restart_and_load`
- `abort_live_episode` if it loads/restores/cleans state
- `rollback_live_step` / `restore_live_checkpoint`
- raw Lua ingame execution

## 测试要求

- 新增 action tool 未分类时测试失败。
- 修改 `unit_action` 的 action enum 时，分类测试必须更新。
- L2+ 在 LIVE_STRICT 无 plan step 必须拒绝。
- L1 不得触发 plan step requirement，但必须 trace。

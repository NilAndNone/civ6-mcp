# Phase 0 Mutation Inventory

Phase 0 只做盘点、分类、测试和文档，不改变真实 Civ6 行为。对应代码入口：

- `plugin/src/codex_hl/live/mutation_levels.py`
- `plugin/src/codex_hl/live/actions.py`
- `plugin/src/codex_hl/live/inventory.py`

`MutationLevel` 使用执行包定义的 L0-L5；`ActionKind` 只做初版标签。当前 registry 不接入 `server.py` 或 `observation.py`，因此不会改变 `/civ6-observe` 或 MCP tool 的实际执行路径。

## MCP Tool Surface

下表覆盖 `plugin/src/civ6_connector/server.py` 中所有 `@mcp.tool()`。`Registered=no` 是带 `readOnlyHint` 的只读工具；所有没有 `readOnlyHint` 的工具都必须在 `ACTION_REGISTRY` 中登记，否则 `tests/test_live_action_registry.py` 会失败。

| Tool | Level | Kind | Registered | Line | GameState methods |
|---|---|---|---|---:|---|
| `get_human_demo_snapshot` | `L0` | `pure_read` | no | 543 | - |
| `get_game_overview` | `L0` | `pure_read` | no | 631 | - |
| `get_units` | `L0` | `pure_read` | no | 698 | - |
| `get_spies` | `L0` | `pure_read` | no | 725 | - |
| `spy_action` | `L3` | `spy_action` | yes | 745 | spy_travel, spy_mission |
| `get_cities` | `L0` | `pure_read` | no | 794 | - |
| `get_city_production` | `L0` | `pure_read` | no | 810 | - |
| `get_map_area` | `L0` | `pure_read` | no | 829 | - |
| `get_settle_advisor` | `L0` | `pure_read` | no | 860 | - |
| `get_pathing_estimate` | `L0` | `pure_read` | no | 880 | - |
| `get_global_settle_advisor` | `L0` | `pure_read` | no | 908 | - |
| `get_builder_tasks` | `L0` | `pure_read` | no | 927 | - |
| `get_empire_resources` | `L0` | `pure_read` | no | 951 | - |
| `get_strategic_map` | `L0` | `pure_read` | no | 967 | - |
| `get_diplomacy` | `L0` | `pure_read` | no | 984 | - |
| `get_tech_civics` | `L0` | `pure_read` | no | 1002 | - |
| `get_pending_trades` | `L0` | `pure_read` | no | 1018 | - |
| `get_policies` | `L0` | `pure_read` | no | 1034 | - |
| `get_notifications` | `L0` | `pure_read` | no | 1048 | - |
| `get_historic_moments` | `L0` | `pure_read` | no | 1066 | - |
| `get_pending_diplomacy` | `L0` | `pure_read` | no | 1083 | - |
| `get_governors` | `L0` | `pure_read` | no | 1105 | - |
| `appoint_governor` | `L3` | `governance` | yes | 1121 | appoint_governor |
| `assign_governor` | `L3` | `governance` | yes | 1139 | assign_governor |
| `promote_governor` | `L3` | `governance` | yes | 1158 | promote_governor |
| `get_unit_promotions` | `L0` | `pure_read` | no | 1179 | - |
| `promote_unit` | `L2` | `unit_action` | yes | 1198 | promote_unit |
| `get_city_states` | `L0` | `pure_read` | no | 1217 | - |
| `send_envoy` | `L2` | `diplomacy` | yes | 1234 | send_envoy |
| `get_pantheon_beliefs` | `L0` | `pure_read` | no | 1249 | - |
| `choose_pantheon` | `L2` | `religion` | yes | 1265 | choose_pantheon |
| `get_religion_beliefs` | `L1` | `runtime_side_effect` | yes | 1284 | - |
| `found_religion` | `L3` | `religion` | yes | 1301 | found_religion |
| `upgrade_unit` | `L3` | `unit_action` | yes | 1329 | upgrade_unit |
| `get_dedications` | `L1` | `runtime_side_effect` | yes | 1345 | - |
| `choose_dedication` | `L2` | `governance` | yes | 1362 | choose_dedication |
| `get_trade_options` | `L0` | `pure_read` | no | 1380 | - |
| `respond_to_trade` | `L3` | `diplomacy` | yes | 1402 | respond_to_deal |
| `propose_trade` | `L3` | `diplomacy` | yes | 1421 | propose_trade |
| `propose_peace` | `L3` | `diplomacy` | yes | 1523 | propose_peace |
| `set_policies` | `L2` | `governance` | yes | 1542 | set_policies |
| `respond_to_diplomacy` | `L3` | `diplomacy` | yes | 1573 | diplomacy_respond |
| `send_diplomatic_action` | `L3` | `diplomacy` | yes | 1596 | send_diplomatic_action |
| `form_alliance` | `L3` | `diplomacy` | yes | 1625 | form_alliance |
| `city_action` | `L3` | `city_action` | yes | 1647 | city_attack, resolve_city_capture |
| `unit_action` | `L3` | `unit_action` | yes | 1697 | move_unit, attack_unit, fortify_unit, skip_unit, found_city, improve_tile, repair_improvement, remove_improvement, remove_feature, build_route, automate_explore, heal_unit, alert_unit, sleep_unit, delete_unit, make_trade_route, activate_great_person, sacrifice_builder_charges, spread_religion, teleport_to_city |
| `skip_remaining_units` | `L3` | `unit_action` | yes | 1808 | skip_remaining_units |
| `set_city_production` | `L3` | `production` | yes | 1821 | set_city_production |
| `purchase_item` | `L3` | `production` | yes | 1856 | purchase_item |
| `set_research` | `L2` | `research_civic` | yes | 1888 | set_research, set_civic |
| `end_turn` | `L4` | `turn_boundary` | yes | 1913 | end_turn |
| `get_diary` | `L0` | `pure_read` | no | 2355 | - |
| `get_trade_routes` | `L0` | `pure_read` | no | 2419 | - |
| `get_trade_destinations` | `L0` | `pure_read` | no | 2435 | - |
| `get_district_advisor` | `L0` | `pure_read` | no | 2460 | - |
| `get_wonder_advisor` | `L0` | `pure_read` | no | 2492 | - |
| `get_purchasable_tiles` | `L0` | `pure_read` | no | 2532 | - |
| `purchase_tile` | `L3` | `tile` | yes | 2551 | purchase_tile |
| `change_government` | `L3` | `governance` | yes | 2578 | change_government |
| `get_great_people` | `L0` | `pure_read` | no | 2602 | - |
| `get_gp_advisor` | `L1` | `runtime_side_effect` | yes | 2618 | - |
| `recruit_great_person` | `L3` | `great_person` | yes | 2640 | recruit_great_person |
| `patronize_great_person` | `L3` | `great_person` | yes | 2659 | patronize_great_person |
| `reject_great_person` | `L3` | `great_person` | yes | 2681 | reject_great_person |
| `get_world_congress` | `L0` | `pure_read` | no | 2705 | - |
| `queue_wc_votes` | `L3` | `world_congress` | yes | 2722 | queue_wc_votes |
| `get_victory_progress` | `L0` | `pure_read` | no | 2758 | - |
| `get_religion_spread` | `L0` | `pure_read` | no | 2781 | - |
| `set_city_focus` | `L2` | `production` | yes | 2802 | set_city_focus |
| `dismiss_popup` | `L4` | `ui_recovery` | yes | 2828 | dismiss_popup |
| `run_lua` | `L5` | `raw_lua` | yes | 2839 | execute_lua |
| `list_saves` | `L0` | `pure_read` | no | 2867 | - |
| `load_save` | `L4` | `save_load` | yes | 2878 | load_save |
| `load_game_save` | `L4` | `save_load` | yes | 2894 | load_game_save |
| `kill_game` | `L4` | `process_lifecycle` | yes | 2922 | - |
| `launch_game` | `L4` | `process_lifecycle` | yes | 2932 | - |
| `load_save_from_menu` | `L4` | `save_load` | yes | 2946 | - |
| `restart_and_load` | `L4` | `process_lifecycle` | yes | 2964 | - |

## Unit And City Sub-Actions

`unit_action` 和 `city_action` 是子动作 multiplexers。测试会从 `server.py` 的 `match action` 直接抽取 case，要求这里的子动作完整登记。

| Multiplexer | L2 | L3 |
|---|---|---|
| `unit_action` | `fortify`, `skip`, `heal`, `alert`, `sleep` | `move`, `attack`, `found_city`, `improve`, `repair`, `remove_improvement`, `remove_feature`, `build_route`, `automate`, `delete`, `trade_route`, `activate`, `sacrifice_charges`, `spread_religion`, `teleport` |
| `city_action` | - | `attack`, `keep`, `reject`, `raze`, `liberate_founder`, `liberate_previous` |

## GameState Mutating Methods

下表覆盖 `plugin/src/civ6_connector/game_state.py` 中初版识别为 L2+ 的方法。L0/L1 查询方法没有展开；Phase 1 可以继续把 logger、heartbeat、camera、spatial 这类 runtime side effect 纳入 shadow trace。

| Method | Level | Line |
|---|---|---:|
| `spy_travel` | `L3` | 159 |
| `spy_mission` | `L3` | 164 |
| `move_unit` | `L3` | 228 |
| `attack_unit` | `L3` | 314 |
| `city_attack` | `L3` | 398 |
| `resolve_city_capture` | `L3` | 428 |
| `found_city` | `L3` | 433 |
| `fortify_unit` | `L2` | 505 |
| `skip_unit` | `L2` | 513 |
| `skip_remaining_units` | `L3` | 518 |
| `automate_explore` | `L3` | 535 |
| `heal_unit` | `L2` | 540 |
| `alert_unit` | `L2` | 545 |
| `sleep_unit` | `L2` | 550 |
| `delete_unit` | `L3` | 555 |
| `improve_tile` | `L3` | 560 |
| `remove_feature` | `L3` | 565 |
| `repair_improvement` | `L3` | 570 |
| `remove_improvement` | `L3` | 575 |
| `sacrifice_builder_charges` | `L3` | 580 |
| `build_route` | `L3` | 585 |
| `set_city_production` | `L3` | 590 |
| `purchase_item` | `L3` | 684 |
| `set_research` | `L2` | 701 |
| `set_civic` | `L2` | 727 |
| `diplomacy_respond` | `L3` | 760 |
| `send_diplomatic_action` | `L3` | 822 |
| `respond_to_deal` | `L3` | 883 |
| `propose_trade` | `L3` | 888 |
| `propose_peace` | `L3` | 924 |
| `form_alliance` | `L3` | 941 |
| `set_policies` | `L2` | 955 |
| `appoint_governor` | `L3` | 987 |
| `assign_governor` | `L3` | 992 |
| `promote_governor` | `L3` | 997 |
| `promote_unit` | `L2` | 1034 |
| `send_envoy` | `L2` | 1114 |
| `choose_pantheon` | `L2` | 1143 |
| `found_religion` | `L3` | 1157 |
| `upgrade_unit` | `L3` | 1174 |
| `choose_dedication` | `L2` | 1189 |
| `purchase_tile` | `L3` | 1276 |
| `change_government` | `L3` | 1285 |
| `recruit_great_person` | `L3` | 1304 |
| `patronize_great_person` | `L3` | 1309 |
| `reject_great_person` | `L3` | 1320 |
| `make_trade_route` | `L3` | 1343 |
| `activate_great_person` | `L3` | 1354 |
| `spread_religion` | `L3` | 1359 |
| `teleport_to_city` | `L3` | 1368 |
| `vote_world_congress` | `L3` | 1384 |
| `submit_congress` | `L4` | 1391 |
| `queue_wc_votes` | `L3` | 1396 |
| `set_city_focus` | `L2` | 1406 |
| `end_turn` | `L4` | 1674 |
| `dismiss_popup` | `L4` | 1680 |
| `load_save` | `L4` | 1692 |
| `load_game_save` | `L4` | 1702 |
| `execute_lua` | `L5` | 1722 |

## Observation Runner Direct Calls

这些调用来自 `plugin/src/codex_hl/evidence/observation.py` 的 AST 扫描，是 Phase 1 shadow gateway 需要标红和接管的绕过点。它们现在保持原样，Phase 0 不改变 runner 行为。

| Symbol | Level | Line | Path |
|---|---|---:|---|
| `execute_read` | `L4` | 1239 | `execute_read` |
| `execute_write` | `L4` | 1247 | `execute_write` |
| `execute_in_state` | `L4` | 1257 | `execute_in_state` |
| `assign_governor` | `L3` | 2837 | `gs.assign_governor` |
| `execute_in_state` | `L4` | 3802 | `conn.execute_in_state` |
| `execute_in_state` | `L4` | 3814 | `conn.execute_in_state` |
| `connect` | `L4` | 3836 | `conn.connect` |
| `disconnect` | `L4` | 3842 | `conn.disconnect` |
| `disconnect` | `L4` | 3852 | `conn.disconnect` |
| `launch_game` | `L4` | 3868 | `game_launcher.launch_game` |
| `connect_with_retry` | `L4` | 3874 | `connect_with_retry` |
| `front_end_load_game_save` | `L4` | 3882 | `front_end_load_game_save` |
| `load_game_save` | `L4` | 3888 | `load_game_save` |
| `disconnect` | `L4` | 3898 | `gs.conn.disconnect` |
| `reconnect` | `L4` | 3908 | `gs.conn.reconnect` |
| `reconnect` | `L4` | 3956 | `gs.conn.reconnect` |
| `save_game` | `L4` | 3984 | `save_game` |
| `set_research` | `L2` | 4064 | `gs.set_research` |
| `set_civic` | `L2` | 4137 | `gs.set_civic` |
| `choose_pantheon` | `L2` | 4184 | `gs.choose_pantheon` |
| `recruit_great_person` | `L3` | 4247 | `gs.recruit_great_person` |
| `found_religion` | `L3` | 4335 | `gs.found_religion` |
| `set_city_production` | `L3` | 4561 | `gs.set_city_production` |
| `upgrade_unit` | `L3` | 4888 | `gs.upgrade_unit` |
| `purchase_item` | `L3` | 4944 | `gs.purchase_item` |
| `purchase_tile` | `L3` | 5018 | `gs.purchase_tile` |
| `propose_trade` | `L3` | 5393 | `gs.propose_trade` |
| `send_diplomatic_action` | `L3` | 5523 | `gs.send_diplomatic_action` |
| `set_policies` | `L2` | 5580 | `gs.set_policies` |
| `choose_dedication` | `L2` | 5629 | `gs.choose_dedication` |
| `send_envoy` | `L2` | 5686 | `gs.send_envoy` |
| `appoint_governor` | `L3` | 5750 | `gs.appoint_governor` |
| `promote_unit` | `L2` | 5833 | `gs.promote_unit` |
| `activate_great_person` | `L3` | 5963 | `gs.activate_great_person` |
| `move_unit` | `L3` | 6026 | `gs.move_unit` |
| `move_unit` | `L3` | 6112 | `gs.move_unit` |
| `found_city` | `L3` | 6160 | `gs.found_city` |
| `move_unit` | `L3` | 6241 | `gs.move_unit` |
| `found_city` | `L3` | 6316 | `gs.found_city` |
| `skip_unit` | `L2` | 6380 | `gs.skip_unit` |
| `move_unit` | `L3` | 6419 | `gs.move_unit` |
| `skip_unit` | `L2` | 6459 | `gs.skip_unit` |
| `improve_tile` | `L3` | 6540 | `gs.improve_tile` |
| `move_unit` | `L3` | 6600 | `gs.move_unit` |
| `make_trade_route` | `L3` | 6709 | `gs.make_trade_route` |
| `skip_unit` | `L2` | 6740 | `gs.skip_unit` |
| `heal_unit` | `L2` | 6844 | `gs.heal_unit` |
| `move_unit` | `L3` | 6868 | `gs.move_unit` |
| `attack_unit` | `L3` | 6887 | `gs.attack_unit` |
| `move_unit` | `L3` | 6910 | `gs.move_unit` |
| `move_unit` | `L3` | 6955 | `gs.move_unit` |
| `move_unit` | `L3` | 6981 | `gs.move_unit` |
| `automate_explore` | `L3` | 6995 | `gs.automate_explore` |
| `fortify_unit` | `L2` | 7014 | `gs.fortify_unit` |
| `skip_unit` | `L2` | 7023 | `gs.skip_unit` |
| `end_turn` | `L4` | 7102 | `gs.end_turn` |
| `end_turn` | `L4` | 7127 | `gs.end_turn` |
| `respond_to_deal` | `L3` | 7209 | `gs.respond_to_deal` |
| `diplomacy_respond` | `L3` | 7227 | `gs.diplomacy_respond` |
| `diplomacy_respond` | `L3` | 7247 | `gs.diplomacy_respond` |
| `end_turn` | `L4` | 7318 | `gs.end_turn` |
| `kill_game` | `L4` | 9804 | `game_launcher.kill_game` |
| `disconnect` | `L4` | 9894 | `conn.disconnect` |

## Save / Load / Restart / Raw Lua Paths

| Path | Level | Source | Phase 1 handling |
|---|---|---|---|
| `save_game` | `L4` | observation checkpoint save | shadow provenance, pre/post save lineage |
| `load_save` | `L4` | MCP tool | gateway boundary action |
| `load_game_save` | `L4` | MCP tool and observation startup | gateway boundary action |
| `front_end_load_game_save` | `L4` | observation startup FrontEnd Lua | gateway boundary action |
| `restart_and_load` | `L4` | MCP recovery tool | explicit recovery plan path |
| `load_save_from_menu` | `L4` | MCP menu automation | explicit recovery plan path |
| `kill_game` / `launch_game` | `L4` | MCP lifecycle tools and observation preflight | explicit lifecycle/recovery events |
| `run_lua` | default `L5`; ingame context classifier returns `L4` | MCP escape hatch | disabled or explicit recovery/debug action in strict mode |
| `GameConnection.execute_write` | `L4` | raw InGame Lua transport | no raw connection exposure to live planner |
| `GameConnection.execute_read` | `L4` | raw GameCore Lua transport | trace source and context |
| `GameConnection.execute_in_state` | `L4` | raw state-index Lua transport | trace source and context |

## Legacy Risks

- `observation.py` still directly calls many L2+ `GameState` methods. This is expected for Phase 0 and is now statically visible.
- `server.py` still lets MCP mutating tools call `GameState` directly through `_logged`; no ActionGateway is inserted yet.
- `end_turn` still includes transparent hang recovery and WC auto-submit behavior in `server.py`; Phase 0 only classifies it as L4.
- `run_lua` remains an exposed MCP tool. Registry marks it L5 by default, with arg-sensitive classification for ingame/raw-write paths, but no guard is active yet.
- `get_religion_beliefs`, `get_dedications`, and `get_gp_advisor` lack `readOnlyHint`; they are registered as L1 so the “new unclassified non-readOnly tool” test remains strict without changing current tool annotations.
- `GameConnection.execute_*` is the raw Lua transport under both reads and writes. Phase 0 records it as a boundary path, but cannot distinguish every Lua snippet’s semantic write/read behavior.

## Phase 1 Must Take Over

- Add ActionGateway shadow mode that records source, tool/action, level, args, and unplanned mutation status without blocking legacy behavior.
- Wrap MCP L2+ tools as thin wrappers through gateway shadow first.
- Add shadow provenance for observation direct calls listed above, especially `set_research`, `set_civic`, `set_city_production`, unit movement/combat/founding, `end_turn`, `save_game`, and load/reconnect paths.
- Split transparent recovery into explicit L4 shadow events before strict gating: hang restart/load, repeated WC blocker auto-submit, connection-loss restart, menu load, and popup dismissal.
- Keep `/civ6-observe` behavior unchanged until Phase 3 runner split; do not enable `/civ6-observe-live` in Phase 1.

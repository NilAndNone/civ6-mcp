# Claude Code Review Checklist

## 必查 grep / static checks

```bash
rg "gs\." plugin/src/codex_hl/evidence/observation.py plugin/src/codex_hl/runs plugin/src/civ6_connector -n
rg "restart_and_load|load_game_save|save_game|execute_write|run_lua|submit_congress" plugin/src -n
rg "eval\(|exec\(|subprocess|open\(" plugin/src/codex_hl/live plugin/src/civ6_connector -n
```

## 架构问题红线

- [ ] 新增 mutating call 是否经过 ActionGateway？
- [ ] `_logged` 是否仍会在 LIVE_STRICT 偷偷自动 restart/load？
- [ ] `end_turn` hang recovery 是否在 live strict 下变成 recovery event？
- [ ] `finish_live_episode` 是否检查 unverified steps？
- [ ] `plan outcome` 是否依赖 Codex 自评？
- [ ] `episode.db` 与 raw JSONL 是否权威混乱？
- [ ] legacy baseline 是否仍可运行？
- [ ] new live path 是否不调用旧 rules priority？

## 测试红线

- [ ] 新增 action 未分类时测试失败。
- [ ] L2+ 无 plan 在 LIVE_STRICT 拒绝。
- [ ] stale context 拒绝。
- [ ] args mismatch 拒绝。
- [ ] duplicate step 拒绝。
- [ ] postcondition fail 进入 recovery 状态。
- [ ] legacy tests 不退化。

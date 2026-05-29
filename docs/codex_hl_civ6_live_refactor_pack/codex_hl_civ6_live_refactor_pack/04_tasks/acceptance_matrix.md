# Acceptance Matrix

## 通用检查

```bash
uv run python -m py_compile plugin/src/codex_hl/evidence/observation.py plugin/src/civ6_connector/server.py
uv run pytest tests/test_observation_turn_limits.py tests/test_observation_report_contract.py tests/test_evidence_store.py -q
```

## Phase Gate

| Phase | 必须交付 | 必须测试 | 不允许 |
|---|---|---|---|
| 0 | mutation registry, inventory doc | registry/inventory tests | 行为改动、live入口、fragment |
| 1 | ActionGateway shadow, ledger event | gateway shadow tests | strict 默认阻断旧 runner |
| 2 | JSON plan, live lifecycle, strict guard | schema/state/gate/verifier tests | fragment 主路径、archive legacy |
| 3 | runner split, orchestrator explicit runner | runner selection tests | 删除 baseline |
| 4 | optional sandbox fragment | AST/sandbox/step binding tests | 多步自由执行 fragment |
| 5 | eval matrix, baseline comparison | metrics/regression tests | 单 episode 自评高收益 |

## Phase 0 PASS

- [ ] ActionSpec / MutationLevel 存在。
- [ ] 所有已知 MCP action tools 有分类。
- [ ] `observation.py` direct mutation 清单生成。
- [ ] 旧测试通过。
- [ ] Claude Code review PASS。

## Phase 1 PASS

- [ ] Gateway 能记录 source、tool、args、level、plan_id/step_id。
- [ ] Shadow mode 不改变旧行为。
- [ ] LIVE_STRICT 无 plan 可拒绝。
- [ ] 至少 3 个 mutating action 接入 gateway。
- [ ] Claude Code review PASS。

## Phase 2 PASS

- [ ] `/civ6-observe-live` 文档存在。
- [ ] plugin `.mcp.json` / `mcpServers` 配置存在。
- [ ] submit plan schema 校验。
- [ ] step armed 后才可执行。
- [ ] stale context / duplicate step / args mismatch 拒绝。
- [ ] verifier 写入结果。
- [ ] T3 real acceptance: 所有 L2+ action 有 plan_id + step_id。
- [ ] Claude Code review PASS。

## Phase 3 PASS

- [ ] `--execute` 无 runner 拒绝。
- [ ] `--runner live` 不调用旧 rules runner。
- [ ] `--runner legacy-baseline` 可用于 baseline。
- [ ] 报告标记 runner kind。
- [ ] Claude Code review PASS。

## Phase 4 PASS

- [ ] fragment 默认关闭。
- [ ] fragment 绑定单 step。
- [ ] 禁止 import/open/subprocess/eval/exec/network/repo write。
- [ ] out-of-process timeout。
- [ ] 多 mutating calls 拒绝。
- [ ] Claude Code review PASS。

## Phase 5 PASS

- [ ] legacy vs live T20/T50 对比报告。
- [ ] objective metrics 完整。
- [ ] failure taxonomy 完整。
- [ ] strategy candidate gate 不依赖 Codex 自评。

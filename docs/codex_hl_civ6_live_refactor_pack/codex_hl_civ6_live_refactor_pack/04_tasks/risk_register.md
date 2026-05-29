# Risk Register

| Risk | Severity | Why it matters | Mitigation |
|---|---:|---|---|
| MCP guard 不能覆盖 legacy runner | High | 直接绕过 plan provenance | ActionGateway 下沉为唯一 mutation 入口 |
| `_logged` 透明 recovery 改状态 | High | plan 之外出现 restart/load/submit | LIVE_STRICT 下 recovery event 化 |
| Python fragment 过早进入主线 | High | 调试/安全/证据复杂度爆炸 | Phase 4 才允许，且单 step |
| Codex 自评 outcome | High | 评价污染、自嗨闭环 | verifier + objective metrics |
| 每步 pre-save 太重 | Medium | I/O 爆炸、运行慢、不稳定 | 按 MutationLevel checkpoint |
| restore 被当事务 rollback | Medium | 时间线证据混乱 | branch lineage + invalidated steps |
| legacy 直接 archive | High | 失去 baseline 和旧闭环 | Phase 3 才 deprecated baseline |
| episode.db/raw 双权威 | High | 崩溃后证据不一致 | ledger/DB source, raw export |
| verifier 过严或过松 | Medium | 误判模型/工具质量 | PASS/FAIL/INCONCLUSIVE 三态 |
| plugin cache/new thread 问题 | Medium | Codex 没加载新 MCP tools | reinstall/cachebuster/new thread real acceptance |

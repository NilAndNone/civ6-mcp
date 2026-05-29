# Hermes Execution Protocol

## 角色分工

| 角色 | 职责 |
|---|---|
| Hermes | 阶段编排、任务拆分、把 zip 内指令喂给 Codex/Claude Code、决定是否进入下一阶段 |
| Codex | 主要编码、测试、文档落地、提交 phase diff |
| Claude Code | 架构遵循度 review、找绕过、找 phase 越界、写 review report |
| 用户 | 批准进入关键阶段、运行真实 Civ6 验收 |

## 节奏

```text
Phase N start
  -> Hermes sends phase prompt to Codex
  -> Codex implements only Phase N
  -> Codex runs tests and writes summary
  -> Hermes sends diff + review prompt to Claude Code
  -> Claude Code writes architecture review
  -> If FAIL: Codex fixes Phase N only
  -> If PASS: Hermes may start Phase N+1
```

## 停止条件

Hermes 必须在这些情况停止并回报用户：

- Codex 想一次性做多个 phase。
- Codex 修改路线图或 strategy assets。
- Codex 删除 legacy runner。
- Codex 引入 mutating fragment 主路径早于 Phase 4。
- Claude Code review FAIL。
- 测试失败。
- 真实 Civ6 环境不可用。
- 出现需要用户批准的高风险改动：load/restart 行为、插件安装结构、episode DB schema migration。

## 推荐提交粒度

- Phase 0: inventory + classification + tests。
- Phase 1: gateway + shadow ledger + partial migration。
- Phase 2: live plan lifecycle + strict gate + T3 acceptance。
- Phase 3: runner split + orchestrator migration。
- Phase 4: optional fragment sandbox。
- Phase 5: eval/governance。

# /civ6-phase1-observe

运行 Codex HL Phase 1 观测。默认用于短跑验收；短跑被人工接受后，也用于单个 episode 的 T50 完整观测。

## 参数

- `save_name`：可选，默认是 `test 1`。
- `turns`：可选，默认是 `3`；短跑验收时必须保持在 3 到 10 回合之间。人工接受短跑后，T50 完整观测使用 `50`。
- `episode_id`：可选，用于指定稳定的 episode 名称。

## 流程

1. 阅读 `plugin/AGENTS.md`。
2. 使用 `plugin/skills/civ6-phase1-observation/SKILL.md`。
3. 短跑验收时运行：
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
   ```
4. 打开生成的 `phase1_short_run_report.html` 做人工验收。
5. 在验收前停止，不要继续到 T50。

## T50 完整观测

人工明确接受短跑报告后，可以运行：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 50
```

T50 运行仍然只做 Phase 1 观测，不做失败归因、策略优化、Replay Arena、自动学习或资产晋级/淘汰。它必须生成一个完整 episode，包含 50 回合的工具/MCP 调用、每回合状态快照、决策记录和存档关联。

如果当前实现拒绝 `--turns 50`，不要把多个短跑 episode 拼成 T50。先修 runner，让单个 episode 能完整记录 50 回合，再重新执行。

T50 完成后必须停止，不要继续 T51+。

# /civ6-phase1-observe

运行 Codex HL Phase 1 观测短跑。

## 参数

- `save_name`：可选，默认是 `test 1`。
- `turns`：可选，默认是 `3`；短跑验收时必须保持在 3 到 10 回合之间。
- `episode_id`：可选，用于指定稳定的 episode 名称。

## 流程

1. 阅读 `plugin/AGENTS.md`。
2. 使用 `plugin/skills/civ6-phase1-observation/SKILL.md`。
3. 运行：
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-phase1-observe --save-name "test 1" --turns 3
   ```
4. 打开生成的 `phase1_short_run_report.html` 做人工验收。
5. 在验收前停止，不要继续到 T50。

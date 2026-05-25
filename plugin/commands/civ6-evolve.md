# /civ6-evolve

## 用途

编排多局 T20/T50、Phase 2 候选、可选自动确认、Phase 4/5 产物和 governance
审计。

`/civ6-evolve` 可以编排 baseline T50，也可以把 Phase 4 candidate package
作为只读运行时输入传给 Phase 1 runner，用于 `v0.0.2` 策略改进验收。

## 输入

常用参数：

- `--turns 20|50`
- `--cycles <n>`
- `--episodes-per-cycle <n>`
- `--save-name "test 1"`
- `--execute`：真实启动 Civ6 运行。
- `--allow-auto-confirmation`：允许自动确认候选。
- `--auto-iterate-strategy`：允许自动切换运行策略。
- `--allow-merge`：允许进入治理合并路径。
- `--candidate-package <candidate.json>`：把候选 playbook 包传入验证流程。
- `--candidate-runtime-applied`：声明 validation report 来自候选运行时。

## 输出

- plan manifest。
- command log。
- episode 列表。
- Phase 2/4/5 产物。
- validation report。
- governance 审计。

## 边界

- 默认 plan-only，不启动 Civ6。
- 没有 `--execute` 不跑真实游戏。
- 自动确认必须显式开启。
- 自动策略迭代必须显式开启。
- 自动合并必须显式开启。
- `--allow-merge` 还必须配合候选运行时证据。
- 候选包运行时只读，不直接修改 Phase 3 assets。

## 示例

只写计划：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --turns 20 --cycles 1 --episodes-per-cycle 3
```

真实执行 T20：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 20 --save-name "test 1" --cycles 1 --episodes-per-cycle 3
```

真实执行 T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 50 --save-name "test 1" --cycles 1 --episodes-per-cycle 3
```

候选运行时 T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 50 --save-name "test 1" --cycles 1 --episodes-per-cycle 5 --candidate-package <candidate.json> --candidate-runtime-applied
```

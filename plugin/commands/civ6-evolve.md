# /civ6-evolve

## 用途

编排多局 T20/T50、Phase 2 候选、可选自动确认、Phase 4/5 产物和 governance
审计。

`/civ6-evolve` 是 `v0.0.1` 的正式入口，但策略改进效果留到 `v0.0.2` 验证。

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
- `v0.0.1` 不承诺 evolve 已经证明策略变强。

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

下一版 `v0.0.2` 会围绕候选 playbook 运行 `5 baseline T50 + 5 candidate T50`
并验证 T50 主指标。

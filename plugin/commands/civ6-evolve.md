# /civ6-evolve

运行多局自进化编排：多次真实 `test 1` T20/T50、Phase 2 候选、可选自动 confirmation、Phase 4/5 产物、validation report 和 L4/L5 governance 审计。

默认不启动 Civ6，只写 plan manifest：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --turns 20 --cycles 1 --episodes-per-cycle 3
```

真实执行 3 把 T20 策略探索：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 20 --save-name "test 1" --cycles 1 --episodes-per-cycle 3
```

真实执行侦察优先 profile 的 T20 候选策略：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 20 --strategy-profile explore_scout_first --save-name "test 1" --cycles 1 --episodes-per-cycle 1
```

真实执行 3 把 T50 验证：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 50 --save-name "test 1" --cycles 1 --episodes-per-cycle 3
```

真实执行至少 20 把 T50，并让 Phase 2 自动确认中高置信候选、自动切换运行时策略 profile：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-evolve --execute --turns 50 --save-name "test 1" --target-completed-episodes 20 --episodes-per-cycle 20 --episode-retries 2 --extra-attempt-slots 5 --allow-auto-confirmation --auto-confirm-min-confidence medium --auto-iterate-strategy
```

自进化安全边界：

- 自动 confirmation 必须显式传 `--allow-auto-confirmation`。
- 自动运行时策略切换必须显式传 `--auto-iterate-strategy`。
- 资产合并必须显式传 `--allow-merge`。
- `--allow-merge` 还必须传 `--candidate-runtime-applied`，否则拒绝；不要把只观察当前运行时的 T50 报告冒充候选策略验证。
- T20 只算局部策略探索证据；T50 才能作为更长验证。
- 当前 Phase 1 runner 仍有静态 blocker-resolution 优先级；validation report 会写 `strategy_runtime_coupled=false`，直到运行时真正读取策略资产。

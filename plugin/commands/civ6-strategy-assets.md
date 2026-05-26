# /civ6-strategy-assets

## 用途

校验 strategy asset catalog、列出 active assets，或只读比较两个已有 T50 episode
的主指标。

## 输入

- `--check`：校验资产库。
- `--list`：列 active assets。
- `--compare-t50 --baseline-episode <id> --candidate-episode <id>`：只读比较 T50。

## 输出

- 资产校验结果。
- active asset 列表。
- T50 主指标对比结果。

## 边界

- 不启动 Civ6。
- 不生成资产 diff。
- 不 merge。
- 不 rollback。
- 不把单个 T50 结果写成通用策略结论。

## 示例

校验资产库：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-strategy-assets --check
```

列 active assets：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-strategy-assets --list
```

比较 T50：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-strategy-assets --compare-t50 --baseline-episode <baseline_id> --candidate-episode <candidate_id>
```

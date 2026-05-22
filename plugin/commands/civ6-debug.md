# /civ6-debug

## 用途

检查 Civ6 连接、FireTuner 端口、游戏进程和存档目录。这个命令用于安装检查
和排障，不是普通游玩入口。

## 输入

- 可选端口，默认 `4318`。

## 输出

- 插件根目录。
- Civ6 存档目录。
- 游戏是否运行。
- FireTuner 端口是否可达。

## 边界

- 不推进游戏。
- 不生成 episode。
- 不修改资产。
- 不替代 Phase 1 观测。

## 示例

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-debug
```

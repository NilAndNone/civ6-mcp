# /civ6-human-demo-record

把玩家自己的 Civ6 手动操作录成独立 SQLite 参考证据。默认由 Codex 对话驱动：
玩家只在 Codex 里说“开始录制”“好了”“结束录制”或一句纠正，终端命令只作为
后台非交互接口使用。这个入口只记录，不自动决策，不结束回合，不写 `episodes/`，
不生成候选 playbook，也不修改 strategy asset assets。

## 输入

- 已经运行并加载好的 Civ6 局面。
- `--save-name`：用于数据库元数据，默认 `test 1`。
- `--turns`：要录制的人工回合数，默认 20。
- `--demo-id`：可选，指定 demo id。
- `--db`：可选，指定 SQLite 路径，默认 `human_demos/<demo_id>/demo.sqlite`。
- `start`：创建/恢复 demo，抓第一份 before 快照。
- `advance`：玩家说“好了”后抓 after，计算 delta，并写入待 Codex 总结的推断动作。
- `record-inference`：把 Codex 在对话里生成的摘要、证据和置信度写回 SQLite。
- `correct`：把玩家一句纠正写回最近回合或指定回合。
- `note`：写入阶段策略备注，例如每 10 回合问题的回答。
- `finish`：结束录制并生成 HTML。
- `report-only` 或 `--report-only --db <path>`：只从 SQLite 重新生成 HTML 报告。
- `self-play`：Codex 使用单独游戏连接自己操作当前 session，并按 human demo
  evidence 形状记录指定回合数；用于录制框架验证，不伪装成人类操作。

## 输出

- `human_demos/<demo_id>/demo.sqlite`
- `human_demos/<demo_id>/report.html`
- SQLite `action_facts` 表：每回合多行结构化明细，可直接查询科技、市政、
  城市生产、单位移动、城市变化、资源和关键数值变化。

## 边界

- 不写 Observation JSONL episode。
- 不调用自动 Observation 决策函数。
- 不替玩家推进回合。
- 录制流程严格只读：拒绝 `end_turn`、单位移动、生产/科技/市政设置等写操作。
- 对话驱动的 `start` / `advance` 会优先读取城市、生产、单位、科技/市政等
  关键字段；关键字段失败时自动低并发补读，仍缺失则降级为待复核摘要。
- `self-play` 的写动作使用单独 Civ6 连接；SQLite recorder 仍只记录只读证据。
- SQLite 记录只能作为策略参考证据；如果要影响 runner，必须另走候选
  playbook、多局验证和 governance。

## 用法

Codex 对话驱动时后台调用：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record start --save-name "test 1" --turns 20
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record advance --db human_demos\<demo_id>\demo.sqlite
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record record-inference --db human_demos\<demo_id>\demo.sqlite --action-id human-action-0001 --summary "T1 侦察兵向西探索" --confidence high --evidence-json "[]"
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record correct --db human_demos\<demo_id>\demo.sqlite --text "T1 实际是勇士向西保护开拓者"
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record finish --db human_demos\<demo_id>\demo.sqlite
```

旧的终端交互模式仍保留，但不作为推荐路径：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record --save-name "test 1" --turns 20
```

只重新生成报告：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record report-only --db human_demos\<demo_id>\demo.sqlite
```

Codex 自操作 5 回合验证录制框架：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record self-play --save-name "test 1" --turns 5
```

Human watch mode: Codex only polls the current turn and records after the human advances.

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record watch --save-name "test 1" --demo-id <demo_id> --poll-seconds 3 --stable-seconds 4 --max-turns 0
```

`watch` is read-only until a turn transition is detected. It pauses by default on skipped turns, review-needed captures, and periodic strategy questions. Use `--no-pause-on-skip`, `--no-stop-on-review`, or `--no-stop-on-periodic-question` only for deliberate unattended runs.

# sci test 1 科技飞天基准

## 目的

`sci test 1` 是用于考察神级科技胜利/飞天能力的固定基准存档。目标是让后续策略、模型或人工操作从同一个 T1 初始局面出发，比较扩张、科技、学院、生产力、太空项目推进和最终科技胜利回合。

## 基准存档

- 存档文件：`.benchmarks/sci-test-1/sci-test-1-baseline.Civ6Save`
- 游戏内存档名：`sci test 1`
- 生成时间：2026-06-03 07:58:24 +08:00
- 版本：1.0.12.68 (1023995)
- 存档大小：867501 bytes
- 存档 SHA-256：`886B6992588B0548EBD84B0956F638140C4711AAEBEA3ABE9B744C28008CCA4A`
- 种子截图：`.benchmarks/sci-test-1/source-seeds.jpg`
- 种子截图 SHA-256：`E6104D321848C9E48046BC9D8F541D05475875AE87DDDA86BC9C732CD9D1EE1E`

## 初始设置

- 规则集：风云变幻，`RULESET_EXPANSION_2`
- 地图：千湖，`Lakes.lua`
- 地图大小：标准
- 游戏速度：标准
- 初始时代：远古
- 难度：神级，`DIFFICULTY_DEITY`
- 地图种子：`919971248`
- 游戏种子：`919971247`
- 主要文明数：8
- 城邦数：12
- 玩家：永乐皇帝/中国，`LEADER_YONGLE` / `CIVILIZATION_CHINA`
- 保存点：第 1 回合，未进行单位、城市、科技、市政或生产选择操作

## 电脑玩家

电脑为可复现的官方内容随机结果。第一次直接使用当前启用内容随机时命中了 Workshop-only `PHANTA` 文明，因此最终基准改为：用游戏种子 `919971247` 对官方 Base/DLC leader 池洗牌，取 7 个不同文明并显式写入 AI 槽，避免 benchmark 依赖本机 Workshop 状态。

| 槽位 | Leader | Civilization |
| --- | --- | --- |
| 1 | `LEADER_DIDO` | `CIVILIZATION_PHOENICIA` |
| 2 | `LEADER_HOJO` | `CIVILIZATION_JAPAN` |
| 3 | `LEADER_AMANITORE` | `CIVILIZATION_NUBIA` |
| 4 | `LEADER_LUDWIG` | `CIVILIZATION_GERMANY` |
| 5 | `LEADER_TRAJAN` | `CIVILIZATION_ROME` |
| 6 | `LEADER_SEONDEOK` | `CIVILIZATION_KOREA` |
| 7 | `LEADER_AMBIORIX` | `CIVILIZATION_GAUL` |

## 高级设置

- 高级设置保持标准：地质年龄、温度、降雨、海平面、资源、起始位置均为标准。
- 遗迹开启，蛮族开启。
- 全部标准胜利条件开启：分数、科技、文化、征服、宗教、外交。
- 全部游戏模式禁用：天启、秘密结社、科技和市政随机、戏剧时代、英雄与传奇、垄断与公司、蛮族氏族、僵尸、随机模式。

## benchmark 记录口径

每次从本存档开始的科技飞天测试，至少记录以下字段：

| 指标 | 说明 |
| --- | --- |
| `run_id` | 运行编号，例如 `sci-test-1-run-001` |
| `operator` | 人工、模型或策略名 |
| `victory_turn` | 科技胜利完成回合；未完成则记录停止回合和原因 |
| `t50_snapshot` | T50 城市数、人口、科技值、文化值、学院数、时代分、金币/回合 |
| `t100_snapshot` | T100 城市数、人口、科技值、文化值、学院数、工业区/工厂、关键伟人 |
| `spaceport_turn` | 首个宇航中心完成回合 |
| `moon_landing_turn` | 登月完成回合 |
| `mars_colony_turn` | 火星殖民完成回合 |
| `exoplanet_start_turn` | 系外行星项目启动回合 |
| `exoplanet_eta` | 系外行星推进速率与预计完成回合 |
| `policy_notes` | 关键政策卡、政体、总督、外交和战争事件 |
| `save_path` | 中间/最终存档路径 |
| `evidence_path` | 回合快照、日志或 episode/demo 数据路径 |

## 判分建议

核心排序指标是 `victory_turn`，越早越好。若未完成科技胜利，则按以下顺序比较：

1. 更早完成系外行星项目。
2. 更早完成火星殖民。
3. 更早完成登月。
4. T100 科技值和有效产能更高。
5. T50 城市数、学院铺设和黄金时代稳定性更好。

## 验证记录

创建后通过 FireTuner 回读确认：

- 当前回合：`1`
- 本地玩家：`0`
- 难度：`DIFFICULTY_DEITY`
- 地图脚本：`Lakes.lua`
- 地图种子：`919971248`
- 游戏种子：`919971247`
- 玩家槽：0 为永乐/中国，1-7 为上述官方 AI
- 城邦配置：12
- 参与槽读数：22，含 8 个主要文明、12 个城邦及游戏内部隐藏槽
- 胜利条件：全开
- 游戏模式：全关
- 保存前未执行单位、城市或回合推进动作

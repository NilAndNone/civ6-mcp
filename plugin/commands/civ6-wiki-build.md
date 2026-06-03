# /civ6-wiki-build

## 用途

生成 Civ6 英文事实知识库，用于模型检索。主来源是 Civilization
Wiki/Fandom，本机 Civ6 游戏文件只用于校验名称、编号、数值、资料片归属和明显冲突。

## 输入

- `--out outputs/civ6-wiki`：暂存输出目录。
- `--cache-dir outputs/civ6-wiki-cache`：Fandom 页面抓取缓存目录，用于断点补跑。
- `--plugin-kb plugin/assets/codex_hl/knowledge/civ6-wiki`：插件知识库目录。
- `--publish-plugin-kb`：验收通过后替换插件知识库目录。
- `--game-root <path>`：本机 Civilization VI 安装目录。
- `--rate-limit-seconds <seconds>`：Fandom API 请求间隔。
- `--max-retries <n>`：单次 Fandom API 请求失败后的重试次数。
- `--sample-only`：只构建验收抽样页。
- `--no-network`：使用内置 fixture，不访问 Fandom。

## 输出

- Markdown 页面和目录。
- `manifest.json`
- `pages_index.json`
- `rag_chunks.jsonl`
- `validation_report.md`

## 边界

- 不启动 Civ6。
- 不读取或修改 `episodes/`。
- 不生成策略建议、强弱评价或主观攻略。
- 不把知识库写入 strategy asset catalog，也不参与 strategy governance merge。
- 剧本和 scenario-specific 内容排除。

## 示例

抽样构建：

```powershell
$env:PYTHONIOENCODING='utf-8'; python -m codex_hl.wiki.build --sample-only
```

完整构建并发布到插件知识库：

```powershell
$env:PYTHONIOENCODING='utf-8'; python -m codex_hl.wiki.build --publish-plugin-kb
```

# Migration / Deprecation Plan

## `/civ6-observe`

Phase 0–2：保持旧行为。

Phase 3：明确标为 legacy-baseline：

- 可用于 baseline 对照；
- 可用于 report/db rebuild；
- 不再是默认真实执行主线；
- 报告必须标 `runner_kind=legacy-baseline`。

## `/civ6-observe-live`

Phase 2 引入：

- 仅 JSON plan + step gate；
- live strict 默认；
- 不使用 Python fragment；
- 真实验收必须新线程，确保 Codex 加载新 MCP tools。

## `/civ6-runs`

Phase 3：

- `--execute` 无 `--runner` 直接 fail；
- `--runner live` 使用 live path；
- `--runner legacy-baseline` 用旧 path 作为对照；
- `--runner legacy-baseline` 输出必须带 deprecation warning。

## Strategy assets

不直接修改。live plan 的好坏先沉淀到 episode 和 review，后续通过 Strategy Candidate / Governance gate。

## Episode schema

- 新 live tables 可增量添加，不破坏旧 episode 读取。
- 导出文件树兼容旧报告工具。
- 老 episode rebuild 不需要 live tables。

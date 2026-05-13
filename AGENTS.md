# Civ6 Codex HL Agent Instructions

This file is the repository-level entry point for Codex behavior in this checkout. Keep it focused on authority, task routing, ownership, and safety boundaries.

## Source Of Truth

- `docs/codex-hl-evolution-roadmap.md` is the only source of truth for the Codex HL Evolution Harness roadmap.
- `docs/codex-hl-evolution-roadmap.html` is the human review companion. Use it to visually compare the review version against the Markdown source; do not treat it as authoritative over the Markdown.
- Do not edit either of those two roadmap files without explicit user approval. If a change is needed, first present the intended change and wait for approval.
- If the Markdown and HTML disagree, follow the Markdown and report the mismatch.

## Repository Documents

- `AGENTS.md`: highest-priority repo entry rule, limited to responsibility boundaries and task routing.
- `docs/codex-hl-phase1-observation.md`: current Phase 1 observation workflow contract for this repo.
- `civ6-mcp.md`: concrete Civ6 MCP operation manual for normal gameplay, including turn flow, tools, strategic checks, combat, diplomacy, production, victory conditions, and recovery.
- `docs/hotseat-agent-lab-roadmap.md`: legacy/project-specific Hotseat roadmap context. Use it for Hotseat/P2/Xiaohan tasks only after reading the current HL roadmap Markdown above.

## Current Direction

The current priority is **Phase 1 observation** for Codex HL Evolution Harness.

Phase 1 means:

- Record a real Civ6 game completely enough to explain what happened.
- Preserve tool/MCP calls, turn state snapshots, decision atoms, and save links.
- Generate a human-reviewable HTML acceptance report.
- Stop after the 3-5 turn short run until human review accepts continuation.

Phase 1 does not mean:

- Automatic learning.
- Strategy improvement.
- Replay Arena.
- Candidate strategy generation.
- Asset merge, rollback, or audit automation.
- Treating a single save as proof of general improvement.

## Task Routing

- For Codex HL, Phase 1 observation, episodes, reports, validation, or evolution-harness work: read `docs/codex-hl-evolution-roadmap.md` first, then `docs/codex-hl-phase1-observation.md`, then inspect the relevant code and tests.
- For normal Civ6 MCP play or operations: read `civ6-mcp.md` before using gameplay tools.
- For Hotseat, Player 2, P2, Agent Lab, Goal 0-13, Xiaohan duel, or live Codex-vs-Xiaohan play: read the current HL roadmap Markdown first, then `docs/hotseat-agent-lab-roadmap.md`, and keep the live-play safety rules below.
- If repository docs conflict with the external roadmap Markdown, the external Markdown wins. Report the conflict instead of silently blending the rules.

## Ownership

- The user owns strategy direction and the user-owned roadmap/review pair:
  - `docs/codex-hl-evolution-roadmap.md`
  - `docs/codex-hl-evolution-roadmap.html`
- Codex owns repo implementation work: scripts, tests, workflow docs, validators, reports, logs, fixes, and retrospectives unless the user narrows scope.
- Do not send implementation details, validation work, script writing, test repair, log inspection, or report generation back to the user unless explicit approval or live-game input is required.
- Do not use a worktree for this repo unless the user explicitly asks.
- The working tree may already contain unrelated user changes. Do not revert changes you did not make.

## Live Hotseat Safety

Hotseat P2 safety has higher priority than normal gameplay optimization.

- If the active player is not the expected P2, stop before calling any action tool.
- During P1 turns, do not call action tools.
- Do not inspect hidden information about Xiaohan's civilization.
- Do not load or retry saves except under a documented crash-recovery policy.
- During live play, first propose a P2 turn plan, wait for approval, execute only approved actions, and record the result.

## Local Execution Notes

- On this Windows checkout, `git` may not resolve in the current PowerShell session. Use `C:\Program Files\Git\cmd\git.exe` when needed.
- Prefer the repo workflow documented in `docs/codex-hl-phase1-observation.md` for Phase 1 validation and report regeneration.

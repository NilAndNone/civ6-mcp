# Asset: strategy.playbook.observation

## Purpose

This playbook defines model-in-loop live strict evidence runs for the installed
plugin.

## Live Flow

1. Confirm the repo root and branch. Do not revert unrelated dirty files.
2. Use `/civ6-observe-live` for real Civ6 mutation.
3. Before each plan, capture the latest context and retrieve relevant active
   strategy assets and Civ6 wiki chunks.
4. The model authors a small JSON plan for the immediate context, then arms and
   executes one matching MCP action at a time.
5. Record the episode id, `episode.db` path, live plan events, live gateway
   events, and any explicit context gaps.
6. Stop after the requested objective unless the user explicitly asks for a
   longer run.

## T50 Flow

1. Run T50 only when the user explicitly asks for T50 or accepts the shorter
   gate as sufficient setup.
2. Use a single model-in-loop live strict episode from the real `test 1` start
   point.
3. Do not stitch multiple short episodes into T50.
4. Do not treat archived lessons, strategy assets, or wiki facts as executable
   policy; they are retrieval context for model-authored plans.
5. Full Windows Civ6 `test 1` validation is required before claiming complete
   replacement proof.

## Required Evidence Classes

- episode header with `start_turn`, `turn_budget`, `target_turn`, and
  `objective`;
- `episode.db`;
- live plan lifecycle events;
- gateway/verifier events for L2+ mutations;
- context hashes for planned turns;
- explicit gaps when connector state is unavailable;
- completion or abort status from the live plan store.

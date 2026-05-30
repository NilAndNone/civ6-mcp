# Asset: strategy.playbook.observation

## Purpose

This playbook defines live strict evidence runs for the installed plugin.

## Short-Run Flow

1. Confirm the repo root and branch. Do not revert unrelated dirty files.
2. Use `/civ6-observe-live` for interactive MCP-driven operation, or run the
   automated driver for a T3 gate:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver --load-test1 --objective t3 --turn-budget 3 --min-cities 1
   ```

3. Record the episode id, `episode.db` path, live plan events, live gateway
   events, and driver summary.
4. Stop after the requested objective unless the user explicitly asks for a
   longer run.

## T50 Flow

1. Run T50 only when the user explicitly asks for T50 or accepts the shorter
   gate as sufficient setup.
2. Use a single live strict episode from the real `test 1` start point:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run --extra launcher-windows codex-hl-civ6-live-driver --load-test1 --objective t50 --turn-budget 50 --min-cities 2
   ```

3. Do not stitch multiple short episodes into T50.
4. Do not treat archived lessons as executable policy.
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
- driver summary under `outputs/live_driver/`.

# CivBench Save Files

This directory holds Civilization VI save files (`.Civ6Save`) used as starting positions for benchmark scenarios. Benchmark save files in this directory are tracked with the repository.

## Required Saves

Naming convention: `0{LETTER}_{SCENARIO_NAME}.Civ6Save` — the `0` prefix ensures saves sort to the top of Civ 6's Load Game screen.

### A: Ground Control

| File | Settings |
|------|----------|
| `0A_GROUND_CONTROL.Civ6Save` | Babylon (Hammurabi), Pangaea Standard, Prince, Quick, 7 opponents |

**Victory:** All types enabled
**Opponents:** Korea (Seondeok), Scotland (Robert the Bruce), Australia (John Curtin), Japan (Hojo Tokimune), Rome (Trajan), Mapuche (Lautaro), Netherlands (Wilhelmina)

### B: Snowflake

| File | Settings |
|------|----------|
| `0B_SNOWFLAKE.Civ6Save` | Korea (Seondeok), Six-Armed Snowflake Small, King, Quick, 5 opponents |

**Victory:** Domination only (Science, Culture, Religious, Diplomatic disabled)
**Opponents:** Macedon (Alexander), Aztec (Montezuma), Scythia (Tomyris), Brazil (Pedro II), Kongo (Mvemba a Nzinga)

### C: Cry Havoc

| File | Settings |
|------|----------|
| `0C_CRY_HAVOC.Civ6Save` | Sumeria (Gilgamesh), Pangaea Tiny, Immortal, Quick, 3 opponents |

**Victory:** All types enabled
**Opponents:** Korea (Seondeok), Brazil (Pedro II), Canada (Wilfrid Laurier)

### D: Low-Random Hotseat Science

| File | Settings |
|------|----------|
| `0D_LOW_RANDOM_HOTSEAT_SCIENCE.Civ6Save` | Hotseat, Pangaea Standard, Online speed, 2 humans, 6 AI, blank civilizations, fixed seeds 11111111/11111111 |

**Victory:** Science only
**Players:** P1 Xiaohan (Human, Prince), P2 Codex (Human, Prince), P3 Warlord AI, P4 Prince AI, P5 King AI, P6 Emperor AI, P7 Immortal AI, P8 Deity AI
**Game Mode:** Monopolies and Corporations enabled; other optional modes disabled

## Common Settings (A-C)

| Parameter | Value |
|-----------|-------|
| Game Speed | Quick |
| Start Era | Ancient |
| Game Modes | None |
| DLC | Gathering Storm (no Leader Pass on Linux) |
| Barbarians | On |
| City-States | Default for map size |
| Duplicate Leaders | Off |

## Creating Save Files

### A: Ground Control

1. Create Game > Single Player
2. **Leader:** Babylon — Hammurabi
3. **Difficulty:** Prince
4. **Game Speed:** Quick
5. **Map Type:** Pangaea
6. **Map Size:** Standard (8 players)
7. **Add opponents** (7 total): Korea (Seondeok), Scotland (Robert the Bruce), Australia (John Curtin), Japan (Hojo Tokimune), Rome (Trajan), Mapuche (Lautaro), Netherlands (Wilhelmina)
8. **Victory Conditions:** All enabled (default)
9. Start game. **Save immediately on Turn 1** before any actions.
10. Copy save to this directory as `0A_GROUND_CONTROL.Civ6Save`

### B: Snowflake

1. Create Game > Single Player
2. **Leader:** Korea — Seondeok
3. **Difficulty:** King
4. **Game Speed:** Quick
5. **Map Type:** Six-Armed Snowflake
6. **Map Size:** Small (6 players)
7. **Add opponents** (5 total): Macedon (Alexander), Aztec (Montezuma), Scythia (Tomyris), Brazil (Pedro II), Kongo (Mvemba a Nzinga)
8. **Victory Conditions:** DOMINATION ONLY — disable Science, Culture, Religious, Diplomatic, Score
9. Start game. **Save immediately on Turn 1** before any actions.
10. Copy save to this directory as `0B_SNOWFLAKE.Civ6Save`

### C: Cry Havoc

1. Create Game > Single Player
2. **Leader:** Sumeria — Gilgamesh
3. **Difficulty:** Immortal
4. **Game Speed:** Quick
5. **Map Type:** Pangaea
6. **Map Size:** Tiny (4 players)
7. **Add opponents** (3 total): Korea (Seondeok), Brazil (Pedro II), Canada (Wilfrid Laurier)
8. **Victory Conditions:** All enabled (default)
9. Start game. **Save immediately on Turn 1** before any actions.
10. Copy save to this directory as `0C_CRY_HAVOC.Civ6Save`

### D: Low-Random Hotseat Science

See `docs/low-random-science-benchmark.md` for the full benchmark definition.

1. Create a Hotseat game with Gathering Storm rules.
2. **Players:** 8 total: P1 Xiaohan (human), P2 Codex (human), P3-P8 AI.
3. **Civilizations:** all players use distinct blank civilizations from the blank civilization mod.
4. **Difficulties:** P1/P2 Prince; AI difficulties Warlord, Prince, King, Emperor, Immortal, Deity.
5. **Game Speed:** Online.
6. **Map Type:** Pangaea.
7. **Map Size:** Standard.
8. **Seeds:** map seed `11111111`, game seed `11111111`.
9. **Victory Conditions:** Science only.
10. **Game Modes:** Monopolies and Corporations enabled; other optional modes disabled.
11. **City-States:** 18.
12. Start game. Save immediately on Turn 1 before any actions.
13. Copy save to this directory as `0D_LOW_RANDOM_HOTSEAT_SCIENCE.Civ6Save`.

### Save file location

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/Sid Meier's Civilization VI/Saves/Single/` |
| Windows | `%USERPROFILE%\Documents\My Games\Sid Meier's Civilization VI\Saves\Single\` |
| Linux | `~/.local/share/aspyr-media/Sid Meier's Civilization VI/Saves/Single/` |

### Verification checklist

For each save file:
- [ ] Correct civilisation and leader
- [ ] Correct opponents (check in-game diplomacy screen after loading)
- [ ] Correct difficulty
- [ ] Quick game speed
- [ ] Turn 1 (no actions taken)
- [ ] Gathering Storm rules active
- [ ] Victory conditions correct (Snowflake = domination only)

## Running an Eval

The game must be running with FireTuner enabled before starting an eval. The agent loads the correct save via `list_saves` / `load_save`.

```bash
# Single scenario
inspect eval evals/civbench.py@civbench_standard \
    --model anthropic/claude-sonnet-4-5-20250929 \
    -T scenarios=ground_control

# All scenarios
uv run python evals/runner.py --model anthropic/claude-sonnet-4-5-20250929

# Multiple models
uv run python evals/runner.py \
    --models anthropic/claude-sonnet-4-5-20250929,openai/gpt-4o,google/gemini-2.5-pro
```

The eval framework spawns the civ-mcp server as a subprocess, which connects to the running game on port 4318.

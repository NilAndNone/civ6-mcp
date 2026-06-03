# Asset: strategy.tool_policy.human_demo_repro_review_gate

## Purpose

This tool policy defines the stop-and-review gate for Human Demo T50
reproduction attempts under contract
`human_demo_t50_reproduction_v2`.

## Rules

- Count only valid strategy attempts. Load failures, restart failures, and
  environment-only failures do not count toward the three-attempt review window.
- Every attempt must be scored with `/civ6-human-demo-contract`, including
  stage scores, checkpoint `must_observe`, checkpoint `failure_criteria`, final
  metrics, assumptions, and stop-rule status.
- Earlier-than-demo milestones are acceptable only when the same causal target
  is satisfied. Early city founding can pass only if it claims the Human Demo
  expansion site or an explicitly justified strategic equivalent; high city
  count alone is not sufficient.
- Shanghai `(65,37)` is a resource-lock deadline, not a generic third-city
  preference. If the horse city is delayed until AI settlement makes the exact
  site illegal, the T25 node fails even when the settler and escort eventually
  reach the target tile.
- After three valid attempts, score the attempts against the key Human Demo v2
  nodes before starting another run.
- If T17, T25, or T29 diverges heavily in all three valid attempts, stop live
  searching and write the next reproduction failure review.
- Do not claim reproduction success from final-turn survival alone. Success
  requires key-node alignment and final target alignment: 4 cities, total
  population 20, science 20.8, culture 20.1, and era score 31.
- Do not claim success from getting Religious Settlements, from early expansion,
  or from reaching T50 unless the causal chain and final metrics both pass.
- Do not encode this gate as an automated live driver. Each key node is a
  planning and review constraint for `/civ6-observe-live`, not a multi-turn
  executor.

## Key Nodes

- T7: slinger complete, village builder present, era score about 4; the capital
  must not still be on an unprotected builder/settler rush line.
- T10: Holy Site in progress, Mining moving, era score about 7, and barbarians
  handled as camp-clear, escort, era-score, and upgrade value.
- T13: builder chops `(63,40)`, Holy Site completes or remains clearly
  advanced, and Holy Site project starts.
- T16-T17: Religious Settlements, free settler, bought forest tile, second
  chop, and purchased slinger escort all connect as one chain. If this chain
  reaches the free-settler state early, the next expansion action must still
  obey the Shanghai horse-lock priority instead of waiting for a literal T16.
- T20: first religion with Choral Music and Pilgrimage, era score about 13.
- T25: Yiyang `(59,36)` and Shanghai `(65,37)` both exist, three cities are
  established, era score is about 17, the expansion route had escort/clearance,
  and the Shanghai site locks horses before AI settlement pressure can invalidate
  the target.
- T29: Yiyang crisis/camp clear locks Golden Age, with era-score sources
  auditable rather than guessed.
- T31: Monumentality is selected and faith is converted into civilian units.
- T37: resources are monetized, Colonization is paid-switched, and double
  chops immediately produce or prepare the fourth-city settler.
- T41: Nanjing `(68,42)` establishes the fourth city and connects to cotton,
  industry, campus, and science/culture plans.
- T44: Classical Republic and the policy combination support expansion and
  production, with science around 17 and culture around 16.
- T50: 4 cities, population about 20, science 20.8, culture 20.1, and era score
  31 with the Golden Age and expansion chain intact.

## Review Output Naming

- First review: `human_demo_repro_failure_review_R01_YYYYMMDD.md`.
- Later reviews increment the review number: `R02`, `R03`, and so on.
- Each review must update the failure blacklist if it identifies a new failed
  strategy pattern.

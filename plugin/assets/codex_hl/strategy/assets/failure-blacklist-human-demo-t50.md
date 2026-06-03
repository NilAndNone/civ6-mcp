# Asset: strategy.memory.failure_blacklist_human_demo_t50

## Purpose

This memory asset records failed strategy patterns from the first Human Demo T50
reproduction review. These entries are blacklist constraints, not positive
strategy recommendations.

## Evidence

- `outputs/live_driver/human_demo_repro_failure_review_R01_20260530.md`
- `outputs/live_driver/human_demo_repro_failure_review_R02_20260530.md`
- `human_demos/human_demo_20260527_074225/demo.sqlite`
- `episodes/live_human_demo_t50_20260530_000002/`
- `episodes/live_human_demo_t50_20260530_000003/`
- `episodes/live_human_demo_t50_20260530_000004/`

## Blacklisted Patterns

- Do not treat any early second city as successful Human Demo imitation. The
  second city must be evaluated by source, escort, site, era-score value, and
  resource logic. The failed runs founded an early city at `(66,40)`, which did
  not reproduce the Human Demo's T25 Yiyang `(59,36)` safety-compromise city.
- Do not copy named choices such as Religious Settlements, Choral Music, and
  Pilgrimage without reproducing their timing chain. In the Human Demo, those
  choices depend on Holy Site production, Holy Site projects, chops, faith
  timing, first pantheon, and first religion.
- Do not classify barbarians only as threats to avoid. Barbarian pressure must
  also be evaluated as a source of camp clears, Archer eureka progress,
  escort requirements, gold, and era score.
- Do not replace the slinger-opening safety chain with a builder/settler rush.
  The Human Demo's slinger opening supports defense, escorting, upgrade timing,
  and barbarian conversion into era-score value.
- Do not hide Holy Site failure with a generic builder fallback. If Holy Site
  placement or production fails, the reproduction attempt has failed the T17
  religion chain until that chain is restored.
- Do not continue blind search after repeated key-node failure. Three valid
  attempts that diverge heavily at T17, T25, or T29 must trigger a review before
  further attempts.
- Do not downgrade the Human Demo v2 acceptance target to an old interim floor.
  T50 success requires the reference final shape: 4 cities, total population 20,
  science 20.8, culture 20.1, and era score 31, plus the causal chain that
  produced those metrics.
- Do not execute pantheon or religion choices before the Human Demo chain window
  just because the connector reports them as available. Under the v2 contract,
  Religious Settlements belongs to the T16 Holy Site/project/chop/free-settler
  window, and Choral Music plus Pilgrimage belong to the T20 first-religion
  window. Earlier execution is label-copying, not reproduction.
- Do not leave the T26 military chain as implicit context. If a slinger can
  upgrade to `UNIT_ARCHER` and sufficient gold exists, the Human Demo profile
  must spend the gold so escort, crisis clear, camp value, and era-score safety
  are executable rather than assumed.
- Do not treat a T31 Monumentality trader purchase as complete unless the trader
  starts a route. The trader must become growth, gold, faith, or route-pressure
  output that supports the T37-T50 population and science/culture finish.
- Do not let early military units fall through to generic skip behavior. The
  warrior and first slinger must either follow the Human Demo exploration/escort
  route or attack visible targets, because villages, natural-wonder/contact era
  score, escort safety, archer upgrade value, and T29 camp-clear value all depend
  on active unit movement.
- Do not accept loose second- or third-city positions as a default
  "equivalent" just because city count or era score is high enough. If the
  settler reaches the Human Demo target early, founding early is acceptable, but
  the target must still align to Yiyang `(59,36)` and Shanghai `(65,37)` or carry
  an explicit strategic-equivalence explanation. A generic nearby site is a
  failed expansion-chain reproduction.
- Do not keep the warrior on blind exploration after the Religious Settlements
  settler is ready. From the T17-T25 expansion window onward, the warrior must
  pivot into escort/clearance for the Yiyang and Shanghai corridors unless it is
  converting an immediate barbarian threat into safety or era-score value.
- Do not let Shanghai `(65,37)` remain a normal third-city priority after the
  Religious Settlements settler is ready. The Shanghai site is the three-horse
  resource lock for T32+ cash conversion; if the second settler is too slow and
  an AI city makes `(65,37)` illegal, the T25 chain has failed even if Yiyang,
  era score, or city count otherwise look close.
- Do not move the T16 second chop away from the Holy Site project chain. The
  post-T16 failure pattern is expansion assignment: once the Religious
  Settlements settler exists, an unclaimed Shanghai `(65,37)` under AI settlement
  pressure must receive the earliest viable settler/escort instead of remaining
  a normal third-city fallback. A T22 capital settler arriving after AI pressure
  has made `(65,37)` illegal is still a T25 failure.
- Do not treat the T16 wording as a literal gate for Shanghai priority. If
  Religious Settlements and the free settler appear early, the staged milestone
  is already satisfied; the horse-lock rule must trigger immediately instead of
  sending the free settler through the default Yiyang-first ordering.
- Do not reintroduce these lessons as an automated driver or multi-turn script.
  They are retrieval constraints for `/civ6-observe-live`: every action still
  requires a fresh context, model-authored JSON plan, armed step, and observable
  post-state verification.

## Required Review Questions

- By T17, did the run reproduce or closely approach Holy Site, Holy Site
  project, chop, Religious Settlements, and free-settler timing?
- By T25, where is the second city, what produced its settler, what escorted it,
  and why is the site strategically equivalent to the Human Demo's Yiyang
  `(59,36)` compromise?
- By T25, did Shanghai `(65,37)` actually lock the horse cluster before AI
  settlement pressure made the site illegal, and did the post-T16 settler
  assignment and escort plan support that race while preserving the Holy Site
  project chain?
- By T29, is Golden Age locked, and which events produced the era score?
- By T41, are four cities established with science and culture connected to the
  religion, faith, campus, monument, and population plan?
- By T50, did the run reach 4 cities, population about 20, science 20.8, culture
  20.1, and era score 31 without breaking the Golden Age, expansion, resource
  conversion, faith-purchase, campus-project, or population chain?

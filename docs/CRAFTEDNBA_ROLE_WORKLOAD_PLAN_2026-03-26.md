# CraftedNBA Role/Workload Plan

Date: 2026-03-26
Status: planning-ready, parser gap partially fixed

## Goal

Use CraftedNBA as a bounded upstream role/workload and stat-tendency signal for prop modeling.

Do not treat CraftedNBA as a generic player-quality feed.

## Why the first takeoff failed

The prior role-metrics branch leaned too hard on impact metrics like `CPM`, `VORP`, `DARKO`, and `DRIP` as a direct same-day prior. Those fields describe broad player value, not tonight's role, volume, or line-clearing shape.

For props, the best CraftedNBA information is the role/workload block and the stat-family tendency block:

- role/workload: minutes projection, usage projection, touches, load, box creation, passer rating, assist-to-usage, starter/rotation/depth
- scoring tendencies: TS%, SQ, 3PAr, R3PAr, FTr
- rebound tendencies: TRB%, ORB%, DRB%, RAORB, RADRB
- assist tendencies: AST%, touches, AstUsg, box creation, passer rating

## Atlas Current State

### Parser

Current parser file: [tools/fetch_role_metrics.py](tools/fetch_role_metrics.py)

The parser is HTML-driven. It now maps these important glossary headers explicitly:

- `Touches`
- `AstUsg`
- `CraftedOPM`
- `CraftedDPM`
- `CraftedWARP`

### Enrichment

Enrichment file: [src/Atlas/core/matchup_enricher.py](src/Atlas/core/matchup_enricher.py)

The matchup enricher already renames parsed fields into `role_metrics_*` columns and merges them by `player_key + game_date`.

### Runtime use

Runtime file: [src/Atlas/engine/new_probability.py](src/Atlas/engine/new_probability.py)

Current live seams:

- `role_metrics_minutes_projection` can influence projected minutes
- workload and tendency fields feed `_usage_dependence_proxy(...)`
- impact metrics feed `_role_metrics_adjustment(...)`

Current problem:

- the direct bounded prior still leans on `cpm`, `vorp`, `drip`, and `darko`
- those are the wrong first-order features for same-day prop probabilities

## Feature Matrix

### Tier 1: Use First

These are the best candidates for the next bounded feature branch.

| CraftedNBA field | Atlas meaning | Best markets | Use now | Reason |
| --- | --- | --- | --- | --- |
| `minutes_projection` | expected minutes tonight | all, especially overs | yes | strongest same-day workload signal |
| `usage_projection` | expected offensive burden tonight | PTS, PRA, PA, PR | yes | closer to slate role than season-long impact |
| `usg_pct` | on-court usage tendency | PTS, PRA, PA, PR | yes | scoring-volume driver |
| `touches` | ball access / initiation volume | AST, PA, PRA, PTS | yes | direct role-volume signal |
| `load` | offensive workload estimate | PTS, AST, PRA, PA | yes | good role burden proxy |
| `bc` | box creation | AST, PA, PRA | yes | creation signal |
| `pr` | passer rating | AST, PA, PRA | yes | assist-family role signal |
| `ast_usg` | assist vs usage balance | AST, PA, PRA | yes | separates scorers from initiators |
| `ast_pct` | assist tendency | AST, PA, PRA | yes | core assist-family tendency |
| `trb_pct` | rebound tendency | REB, RA, PRA, PR | yes | core rebound-family tendency |
| `orb_pct` | offensive rebound tendency | REB, RA, PRA, PR | yes | rebound subtype signal |
| `drb_pct` | defensive rebound tendency | REB, RA, PRA, PR | yes | rebound subtype signal |
| `ts_pct` | scoring efficiency | PTS, FG3M, scoring combos | yes | useful only when market-routed |
| `sq` | shooting quality | PTS, FG3M | yes | useful when kept market-specific |
| `three_par` | threes share | FG3M, PTS | yes | good threes specialization signal |
| `ftr` | foul-drawing tendency | PTS, PRA, PA | yes | scoring floor/ceiling helper |

### Tier 2: Use Later or Audit First

| CraftedNBA field | Atlas meaning | Best markets | Use now | Reason |
| --- | --- | --- | --- | --- |
| `starter_flag` | starter/bench role bucket | all | audit first | categorical, useful but easy to overfit |
| `rotation_tier` | rotation status | all | audit first | likely useful for minutes confidence |
| `depth_role` | bench hierarchy | all | audit first | useful for volatility, not first-order mean |
| `role_awareness` | role-shape label | all | audit first | useful as a bucket, not a raw scalar |
| `crafted_opm` | blended offensive impact | PTS, AST combos | later | too global for first branch |
| `crafted_dpm` | blended defensive impact | maybe rebounds/stocks | later | indirect to current markets |
| `crafted_warp` | broad total value | none | later | too global |

### Tier 3: Do Not Use As Primary Same-Day Drivers

| CraftedNBA field | Reason |
| --- | --- |
| `cpm` | broad player value, not tonight role |
| `vorp` | broad player value, not tonight role |
| `darko` | projection quality metric, too global |
| `drip_total` | impact metric, too global |
| `odarko`, `ddarko`, `odrip`, `ddrip`, `obpm`, `dbpm`, `bpm`, `ws` | all are better as weak background priors than as same-day prop drivers |

## Recommended First Implementation

Do not build another global role-metrics multiplier.

Build a bounded `crafted_role_workload` family inside the usage/role path with these rules:

1. Route by market family.
2. Use workload fields first.
3. Use stat-tendency fields only inside the matching family.
4. Keep global impact metrics out of the first branch.

### Market routing

- `PTS`, `PRA`, `PA`, `PR`, `RA`:
  - `minutes_projection`
  - `usage_projection`
  - `usg_pct`
  - `load`
  - `ts_pct`
  - `sq`
  - `ftr`
- `AST`, `PA`, `PRA`, `RA`:
  - `touches`
  - `ast_pct`
  - `ast_usg`
  - `bc`
  - `pr`
  - `load`
- `REB`, `RA`, `PRA`, `PR`:
  - `trb_pct`
  - `orb_pct`
  - `drb_pct`
- `FG3M`:
  - `three_par`
  - `sq`
  - `ts_pct`
  - `minutes_projection`

## Recommended First Branch

Branch objective:

- move away from impact-metric prioring
- make CraftedNBA a role/workload surface, not a value ranking surface

Implementation sketch:

1. keep `role_metrics.enabled` explicit opt-in
2. leave `_role_metrics_adjustment(...)` effectively neutral for the first branch or remove impact metrics from it
3. strengthen `_usage_dependence_proxy(...)` with the Tier 1 role/workload fields only
4. optionally add a bounded minutes override using `minutes_projection` and `usage_projection`
5. replay March 17 and March 18 truth-backed bundles before any broader corpus work

## Pass Criteria

The first CraftedNBA branch is worth continuing only if:

- it moves `p_adj` materially more than the recent micro-branches
- it improves aggregate truth-backed Brier on March 17 and does not regress March 18
- the changed rows line up with the intended market families rather than the whole board

## Immediate Next Task

Implement a `crafted_role_workload` takeoff that:

- uses Tier 1 fields only
- disables the current impact-style direct prior path
- replays on the settled March 17 and March 18 bundles first
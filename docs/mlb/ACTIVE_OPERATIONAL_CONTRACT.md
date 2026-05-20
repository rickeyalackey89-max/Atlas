# Active MLB Operational Contract

Last updated: 2026-05-19

This is the current working contract for Atlas MLB Dev. It is the source to check before running new replay corpuses, CAT training, or slip-builder sweeps.

## Repository Layout

The active Python package uses a normal `src/` layout. The old `src/Atlas/sports/mlb/` package chain has been removed.

- `src/mlb/` - active MLB package. Imports remain `mlb.*`.
- `src/core/` - shared helpers used by MLB, including `core.prizepicks_quote`. Imports remain `core.*`.
- `scripts/mlb/` - replay, trainer, and audit scripts.
- `tests/mlb/` - MLB test suite.
- `config/sports/mlb.yaml` - active operational config.
- `data/mlb/raw/` - immutable raw snapshots and manifests.
- `data/mlb/staged/` - normalized source tables.
- `data/mlb/features/` - feature artifacts with manifests.
- `data/mlb/test_runs/` - replay and corpus-member runs.
- `data/mlb/live_runs/` - live runs only.
- `data/mlb/eval/` - eval legs, eval slips, corpus summaries, audits.
- `data/mlb/model/` - active and candidate model artifacts.

Canonical commands:

```powershell
uv run atlas-mlb --help
uv run python -m mlb.cli --help
.\AtlasMLB.ps1 doctor
```

## Fidelity Rule

Replay fidelity is mandatory. A replay must call the same feature, market, calibration, scoring, quote, and slip-builder contracts that live uses.

Rules:

- No replay-only feature inputs.
- No post-date context for probability.
- Every feature used by live must write a manifest usable by replay.
- Live runs must refresh same-day context before scoring, then write the same
  source-selection manifests that replay consumes.
- Every run writes `source_selection_manifest.json`; the same payload is embedded
  in `run_manifest.json` as `source_selection`.
- Market context source dirs are explicit for both live and replay. Replay uses
  the selected primary BettingPros source plus selected enabled supplemental
  sources only; it must not silently scan all staged market folders for a date.
- A live-enabled source that replay cannot reproduce is a source contract failure
  (`contract_status: fail`) until that same-date source is backfilled or the
  feature is intentionally disabled in config.
- DraftKings supplemental sources use `draftkings_mlb_late_market_timing_v2_per_game`.
  Every game is evaluated independently with a one-hour-before-first-pitch
  target. Missing DK rows are `timing_pending` only when every unstarted game is
  still before its own target. Once any game is inside its ready window, missing
  DK context is a source contract failure for that ready portion of the slate.
- Single replay and corpus replay stay separate from live output roots.
- Replays write to `data/mlb/test_runs/`.
- Live writes to `data/mlb/live_runs/`.
- Evaluations write to `data/mlb/eval/`.

## Active Config

Active config file: `config/sports/mlb.yaml`

Current config version:

```text
mlb_dev_fidelity_bettingpros_dk_pick6_v6_tuned_slip_v18_market_source_context_20260519
```

Important config fields:

- `market_sources.primary: bettingpros_mlb_props`
- `market_sources.external_features.draftkings_pick6_alignment_enabled: true`
- `market_sources.external_features.draftkings_sportsbook_alignment_enabled: true`
- `features.replay_safe_context.bettingpros_market_context: true`
- `features.replay_safe_context.roster_identity_from_prior_history: true`
- `validation.require_slip_eval: true`
- `validation.require_eval_legs: true`
- `validation.require_eval_slips: true`

## Active Probability Stack

Base probability kernel:

```text
mlb_market_prior_sobol_qmc_v0
```

Active CAT residual:

```text
mlb_cat_over_residual_v6_23date_live_context_scale_tuned
```

Active CAT artifact:

```text
data/mlb/model/cat_probability_kernel_v6_23date_live_context/scale_tuning/tuned_best_config.json
```

Known challenger artifacts:

- `data/mlb/model/cat_probability_kernel_v5_reorg_bettingpros_on/best_config.json`
- `data/mlb/model/cat_probability_kernel_v6_23date_live_context/best_config.json`
- `data/mlb/model/cat_probability_kernel_v4_bettingpros_on/best_config.json`
- `data/mlb/model/cat_probability_kernel_v3_wide_market_v15/best_config.json`
- `data/mlb/model/cat_probability_kernel_v4_bettingpros_off/best_config.json`
- `data/mlb/model/cat_probability_stacker_v1_lodo_cat_v5/best_config.json`

Current CAT promotion basis:

- Source LODO trainer artifact: `data/mlb/model/cat_probability_kernel_v6_23date_live_context/best_config.json`
- Date-held-out residual scale tuner: `data/mlb/model/cat_probability_kernel_v6_23date_live_context/scale_tuning/tuned_best_config.json`
- 23-date tuned LODO brier: `0.17984945`
- 23-date tuned LODO logloss: `0.53872755`
- 23-date original v6 LODO brier: `0.18093639`
- 23-date original v6 LODO logloss: `0.54133007`
- Same-20-date tuned v6 brier: `0.17926806`
- Same-20-date v5 brier: `0.17963887`
- Candidate replay smoke date: `2026-05-18`
- Candidate replay v6 tuned brier/logloss: `0.165452` / `0.500917`
- Candidate replay v5 brier/logloss: `0.199632` / `0.587311`

The live-path smoke corpus uses the full trained CAT artifact and is not the fair estimate for future accuracy. Use LODO outputs for CAT and slip-builder decisions.

## Live Market Sources

Market source order for live runs:

- Primary: `bettingpros_mlb_props`.
- Supplemental: `draftkings_mlb_pick6` normalized into `oddsapi_props.jsonl`
  for Pick6 line coverage. DK usually exposes only a few hitter fantasy rows
  per game and does not currently expose a stable pitcher fantasy feed.
- Supplemental: `draftkings_mlb_sportsbook` normalized into `oddsapi_props.jsonl`
  for DraftKings Sportsbook milestone and O/U odds. Current supplemental
  gap-fill markets include batter walks, stolen bases, and hitter strikeouts
  when DK has posted them. BettingPros consensus wins when both sources match
  because it has broader book depth.
- Every live run writes a `draftkings_gap_fill_monitor` section inside
  `source_selection_manifest.json` so missing DK rows are classified as loaded,
  timing-pending, no-board-rows, or not-currently-expected rather than being
  inferred from broad market coverage.

Live pull cadence:

- Central time windows: `11:00`, `14:30`, `17:00`, `19:00`.
- Each live run fetches a fresh PrizePicks board and market context.
- The engine board excludes games that have already started, so the 14:30,
  17:00, and 19:00 runs are late-slate refreshes, not full-day repeats.
- DraftKings late pitcher/hitter props are evaluated per game. Later games may
  remain timing-pending even when earlier games are already inside the DK-ready
  window.

Latest live smoke with all three sources:

- Run: `data/mlb/live_runs/live_v18_dk_teamfix_market_context_20260519_181834`
- Publish allowed: `true`
- Operator severity: `warning`
- Market coverage: `78.3%`
- Lineup coverage: `83.9%`
- StatsAPI/roster/player-history/advanced/weather coverage: `99.9% / 99.9% / 97.2% / 98.7% / 99.9%`
- Payout quotes: `9/9 exact`
- Pitcher prop matrix: `mlb_matchup_matrix_v1` is now wired in code. Next live/replay smoke should verify the previous `pitcher_prop_matchup_neutral` warning clears or narrows to true source misses.

Current fair LODO challenger:

- Stacker artifact: `data/mlb/model/cat_probability_stacker_v1_lodo_cat_v5/best_config.json`
- Base model: `mlb_cat_over_residual_v5_reorg_bettingpros_on`
- Best blend: `0.5` logit-space CAT residual probability + `0.5` CatBoost classifier probability
- LODO brier: `0.17868454`
- LODO logloss: `0.53544371`
- Brier delta vs active v5: `-0.00095433`
- Runtime application smoke: passed on `stacker_smoke_20260515` (`4429` parameter rows)
- Promotion status: challenger only until replay smoke/corpus validation passes.

## Active Slip Builder

Active builder:

```text
atlas_mlb_public_slip_ranker_v18_market_source_context
```

Promotion basis:

- Live-fidelity replay corpus: `data/mlb/eval/corpus_replay_20260426_20260518_v6_tuned_live_fidelity_v1`
- Builder sweep: `data/mlb/model/slip_builder_policy_v5_v6_tuned_live_fidelity`
- Best held-out variant: `marketed_system_probability_plus`
- Objective score: `0.696264`
- Settled slip count: `258`
- Settled rate: `0.952030`
- Marketed settled win rate: `54/66 = 0.818182`
- System settled win rate: `54/67 = 0.805970`
- Windfall settled win rate: `41/61 = 0.672131`
- DemonHunter settled win rate: `31/64 = 0.484375`
- Policy change: Marketed and System now weight direct calibrated probability more heavily under the active tuned V6 CAT artifact.
- Market-source context: scored/eval/slip artifacts distinguish external sportsbook-confirmed props from PrizePicks line-only props using `market_context_source_type` and `prizepicks_line_only_market_context`.
- 23-date audit result: selected slip legs without external sportsbook context were mostly PP fantasy-score alternates and hit `368/380 = 96.84%`; this context is a tuning signal, not an automatic exclusion.

Family order:

1. Marketed
2. System
3. Windfall
4. DemonHunter

Full slate rule:

- No 2-leg slips on full slates.
- Full slate families produce 3-leg, 4-leg, and 5-leg slips only when eligible.

Tier side rule:

- Goblin: over only.
- Demon: over only.
- Standard: over or under.

Flex-style eval:

- Marketed 5-leg
- Windfall 5-leg
- DemonHunter 4-leg
- DemonHunter 5-leg

## Replay Readiness Gates

Before a new corpus replay or CAT training run, run a readiness audit. Do not use a corpus result for model decisions if the replay inputs are incomplete.

Minimum targets:

- Roster context: `>= 90%`
- Player history context: `>= 90%`
- Lineup context: `>= 70%`
- Market context: `>= 75%`
- Advanced context: `>= 90%`
- Eval settlement: `>= 95%`

Roster context may use prior-date season gamelog or prior boxscore identity when a date-safe roster snapshot is unavailable. It must not use same-day or post-date identity for probability.

Environment context must be date-safe:

- Weather and lineup context must come from the replay date and must exclude post-start/postgame rows.
- Ballpark profiles are loaded from an as-of-date `ballpark_profiles.json` only; replay must not load `data/mlb/staged/ballparks/latest.json` for earlier dates.
- Stadium wind factors from `mlb_wind_effect_data_with_ballpark_orientation.xlsx` are static park/orientation priors and are allowed when dated Savant park profiles are unavailable.
- Umpire profiles are loaded as-of-date only. Current April replay dates do not have true historical umpire profiles, so they remain a non-blocking warning until a historical source is added.

## Market Source Contract

BettingPros is the primary market source for MLB runs.

Live market behavior:

- Live runs refresh BettingPros before market-context construction unless
  explicitly disabled.
- `market_context` must select staged market rows by actual `game_date`, not by
  folder timestamp text.
- If a PrizePicks prop has no playable external market equivalent, the row stays
  playable but the manifest records `missing_market_context`.

Optional sources are present but not active primary sources:

- ODDSAPI
- ParlayAPI historical closing props
- DraftKings Sportsbook
- DraftKings Pick6

DraftKings feeds are alignment/coverage sources until explicitly promoted in config.

## Required Feature Manifests

Every run should emit these manifests or explain why the stage was skipped:

- board
- market_context
- injury_context
- statsapi_context
- roster_context
- player_history_context
- transaction_context
- matchup_context
- advanced_context
- feature_table
- parameter_table
- score
- slips
- replay_eval

## Current Next Work

After repository layout and docs are stable:

1. Run replay readiness audit.
2. Fix any missing replay source coverage.
3. Rerun only the affected replay/corpus outputs.
4. Compare kernels with the same feature contract.
5. Train the next CAT only after readiness passes.
6. Re-run builder trainer after the CAT decision.
7. Tune family builders without changing the public tier contract.

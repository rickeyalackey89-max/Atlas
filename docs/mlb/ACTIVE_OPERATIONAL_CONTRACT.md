# Active MLB Operational Contract

Last updated: 2026-05-22

This is the current working contract for Atlas MLB Dev. It is the source to check before running new replay corpuses, CAT training, or slip-builder sweeps.

Binding replay docs:

- `docs/mlb/BASEBALL_PHILOSOPHY.md`
- `docs/mlb/MLB_BASEBALL_CONTEXT_CODEX_BRIEF.md`
- `docs/mlb/STRICT_REPLAY_FIDELITY_CONTRACT.md`
- `docs/mlb/STRICT_REPLAY_WORKFLOW.md`
- `docs/mlb/REPLAY_FIDELITY.md`

## Baseball-First Rule

The MLB model is not allowed to optimize around numbers divorced from baseball
context. `docs/mlb/BASEBALL_PHILOSOPHY.md` is the baseball-first contract for
how Atlas should interpret MLB props.

Operational meaning:

- Opportunity comes first: confirmed lineup, batting order, plate appearances,
  confirmed starter, pitch count, and role.
- Matchup comes second: hitter skill versus pitcher handedness, pitch mix,
  contact shape, strikeout/walk profile, and bullpen continuation.
- Environment comes third: ballpark, weather, wind, roof, umpire, defense, and
  game run environment.
- Prop personality matters: hits are not total bases, RBI are not isolated
  hitter skill, home runs are high variance, and pitcher outs are workload plus
  efficiency plus manager leash.
- Slip fit matters: good legs can be bad pairings when they depend on the same
  game script, fight each other, or cluster the same weather/team risk.

CAT, replay, and builder work should be judged against those baseball paths, not
only against global brier, aggregate hit rate, or table-level feature coverage.

## Passive Baseball Context Layer

The MLB runtime now writes passive baseball-context artifacts whenever scored
legs are used to build slips. This layer is non-mutating: it does not change
`p_cal`, `model_probability`, CAT artifacts, or slip probabilities.

Run-level artifacts:

- `mlb_scored_legs_context.csv`
- `mlb_publication_gate_report.json`
- `mlb_pick_context_packets.json`

Latest mirrors:

- `data/mlb/output/context/latest_mlb_scored_legs_context.csv`
- `data/mlb/output/context/latest_mlb_publication_gate_report.json`
- `data/mlb/output/context/latest_mlb_pick_context_packets.json`

The artifacts tag each leg by opportunity, lineup status, batting-order bucket,
pitcher starter status, prop volatility, matchup availability, park/weather
availability, and publication gate level (`ok`, `caution`, `suppress`). These
fields are audit context first. They become CAT or builder features only after
strict replay fidelity confirms that live and replay can reproduce them.

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
- `data/mlb/replay_runs/` - single replay and corpus-member run outputs.
- `data/mlb/corpus_replays/` - corpus replay aggregate outputs, member run/eval logs, and trainer handoff summaries.
- `data/mlb/test_runs/` - legacy/read-only compatibility outputs only.
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
- Single replay/member run artifacts write to `data/mlb/replay_runs/`.
- Corpus aggregate artifacts write to `data/mlb/corpus_replays/`.
- Live writes to `data/mlb/live_runs/`.
- Evaluations write to `data/mlb/eval/`.

## Active Config

Active config file: `config/sports/mlb.yaml`

Current config version:

```text
mlb_dev_fidelity_projection_features_v9_slip_v20_empirical_reliability_matchup_matrix_v1_20260522
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
mlb_cat_over_residual_v9_projection_features_strict_fidelity
```

Active CAT artifact:

```text
data/mlb/model/cat_probability_kernel_v9_20260516_20260520_strict_fidelity_projection_features/best_config.json
```

Known challenger artifacts:

- `data/mlb/model/cat_probability_kernel_v8_20260516_20260520_strict_fidelity/best_config.json`
- `data/mlb/model/cat_probability_kernel_v6_23date_live_context/scale_tuning/tuned_best_config.json`
- `data/mlb/model/cat_probability_kernel_v5_reorg_bettingpros_on/best_config.json`
- `data/mlb/model/cat_probability_kernel_v6_23date_live_context/best_config.json`
- `data/mlb/model/cat_probability_kernel_v4_bettingpros_on/best_config.json`
- `data/mlb/model/cat_probability_kernel_v3_wide_market_v15/best_config.json`
- `data/mlb/model/cat_probability_kernel_v4_bettingpros_off/best_config.json`
- `data/mlb/model/cat_probability_stacker_v1_lodo_cat_v5/best_config.json`

Current CAT promotion basis:

- Strict corpus: `data/mlb/corpus_replays/corpus_replay_20260516_20260520_strict_fidelity_v2`
- Strict preflight report: `data/mlb/audits/strict_replay_preflight/strict_replay_preflight_20260522T162108Z.json`
- Date count / row count: `5` dates / `30337` rows.
- v9 projection-feature LODO brier/logloss: `0.18648419` / `0.55538485`.
- v8 strict-fidelity LODO brier/logloss: `0.18652262` / `0.55550450`.
- v9 best parameters: `iterations=400`, `learning_rate=0.03`, `depth=4`, `residual_scale=0.65`.
- Promotion reason: small but clean brier/logloss improvement on the same strict-fidelity corpus after adding projection-derived features.

Projection-derived CAT features:

- `projection_mean_from_base`
- `projection_delta_from_line`
- `projection_abs_delta_from_line`
- `projection_line_ratio`

These are generated from the same base probability/distribution contract used by live scoring. They must be present in replay feature rows before CAT training; missing projection features are a strict-fidelity failure for any projection-feature CAT candidate.

The live-path smoke corpus uses the full trained CAT artifact and is not the fair estimate for future accuracy. Use LODO outputs for CAT and slip-builder decisions.

Source-aware CAT upgrade path:

- The CAT training feature contract now carries `market_context_source_type`,
  `external_market_context_source`, `line_bucket`, and numeric source flags for
  BettingPros, DraftKings Pick6, DraftKings Sportsbook, external market context,
  and PrizePicks-line-only rows.
- Feature-table contract `baseline_player_prop_features_v2_matchup_source_context`
  carries live/replay matchup detail before CAT training: batting order slot,
  lineup probability/confirmation, top-order flag, hitter handedness versus
  starter handedness, park and umpire fields, and the dedicated pitcher-prop
  context layer (`workload_context_score`, opponent lineup/K/contact/power/walk
  scores, pitcher history scores, bullpen support, and pitcher prop confidence).
  These are normal runtime fields, not hidden trainer-only features.
- Runtime calibration applies residual scale maps against the same merged
  parameter+feature row used for CAT prediction, so replay/live stay aligned when
  a source-aware tuned artifact is promoted.
- Fast diagnostic: `uv run python scripts/mlb/audit_cat_lodo_residuals.py --artifact <artifact-json>`.
- Guarded scale tuner supports strategy subsets through `--strategies`; start
  with `artifact,global,tier,market,tier_market,source,line_bucket` and only run
  `market_source` or `tier_market_source` when there is enough time and row
  count to justify the heavier sweep.
- Current diagnostic on raw v6 LODO:
  - Overall raw v6 LODO brier/logloss: `0.18093639` / `0.54133007`.
  - Overall calibration gap: `-0.02312469` (average probability high by about
    2.3 points).
  - Line-bucket smoke tuning improved raw v6 to brier/logloss
    `0.18008696` / `0.53984947`, but does not beat the current tuned artifact.
  - Conclusion: the next real attempt should retrain CAT with source-aware
    features, then run guarded segment scaling and builder training.

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
atlas_mlb_public_slip_ranker_v27_marketed_prob_edge_cat_v11
```

Promotion basis:

- CAT active candidate is
  `mlb_cat_over_residual_v11_20260426_20260520_baseball_context_v12`
  from the strict-fidelity 2026-04-26..05-20 corpus. Best held-out sweep:
  `400` iterations, depth `4`, learning rate `0.03`, residual scale `0.80`.
  It improved held-out Brier from `0.191641` to `0.181960`.
- Builder policy trainer:
  `data/mlb/model/slip_builder_policy_v17_20260426_20260520_baseball_context_v12_cat_v11_overlay`.
  The selected variant is `marketed_prob_edge_plus`.
- Only the Marketed policy is promoted from v17. System, Windfall, and
  DemonHunter stay on their prior family contracts because the fresh strict
  trainer did not prove a clean family-level improvement for them.
- On the strict 25-date corpus with CAT LODO overlay:
  - Baseline Marketed: `22/52` settled slips (`42.3%`), selected legs `72.1%`.
  - Promoted Marketed: `21/38` settled slips (`55.3%`), selected legs `76.9%`.
  - Marketed 2-leg remained the strongest public shape: `17/25` (`68.0%`).
  - System/Windfall/DemonHunter were not loosened; their weaker long-slip hit
    rates remain evidence that more volume is not automatically better.
- Family builder contracts are split by family under
  `src/mlb/runtime/slip_builders/`:
  - `marketed.py`: premium public picks.
  - `system.py`: Atlas Value/EV.
  - `windfall.py`: flex/upside construction.
  - `demonhunter.py`: Demon-only high-variance construction.
- Market-source context is a small tiebreaker only. It is not allowed to become
  the primary reason a leg outranks stronger empirical family/segment evidence.
- Runtime ranker `v27_marketed_prob_edge_cat_v11` blocks public selected
  slips whose baseball-context packet is `suppress` (`unknown_hitter_lineup`,
  `unknown_pitcher_starter_status`, identity gaps, or weather-delay workload
  risk). It also applies family-specific hard blocks:
  - DemonHunter/Windfall block weak Demon pitcher/workload and hitter fantasy
    over segments exposed by replay.
  - Marketed blocks specific fragile Standard workload unders/variance props.
  - System does not inherit those hard blocks globally; it keeps them as
    ranking/composition signals unless replay evidence supports a family-level
    block.
- Marketed full-slate templates include a 2-leg Goblin fallback. This keeps the
  public premium family from starving on slates where baseball-context gates
  leave too few Standard legs, and it tested as the strongest Marketed shape in
  the strict corpus (`4/5` settled 2-leg slips).
- Runtime ranker `v20_empirical_reliability` adds a replay-derived segment
  reliability adjustment. Weak historical segments and high model-vs-prior gaps
  are penalized, especially for premium Marketed/System slips.
- Runtime ranker carries detailed lineup-volume fields from the run-scoped
  feature table into slip selection: batting order slot, lineup confirmation,
  top-order flag, projected plate appearances, opportunity confidence, park
  confidence, matchup confidence, and environment scores. Batting slots 1-4 are
  volume support only; they are not a blind boost. Unconfirmed high-variance
  hitter overs, especially low-line hitter fantasy score legs without matched
  external market context, receive a small ranking penalty.
- Pitcher workload props require stronger probability support before they can
  outrank safer alternatives.
- Portfolio exposure blocks exact repeats, player repeats, and repeated volatile
  risk segments across the main public families.
- DemonHunter is a family-independent builder. It ranks the best Demon overs
  from its own Demon-only pool instead of being starved by Marketed/System/
  Windfall exposure caps. It still avoids duplicate exact/player legs internally,
  but does not hard-cap Demon market segments.

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

Required preflight command:

```powershell
uv run python scripts\mlb\preflight_strict_replay_dates.py --start 2026-04-26 --end 2026-05-20
```

The replay sweep script also runs this preflight before scoring. If the
preflight verdict is not `PASS`, the replay corpus must not start.

Strict-fidelity blocker:

- `source_selection_manifest.json` is a hard replay contract, not advisory telemetry.
- Any replay with `contract_status: fail` must stop before parameter scoring, slip building, replay eval, corpus aggregation, or CAT training.
- Corpus aggregation and CAT trainers must reject any member run whose source contract failed.
- A missing source can only be downgraded from failure to warning by changing the shared source contract code and documenting why live has the same behavior.
- `mlb_pick_context_packets.json` and `selected_slip_context_audit.json` are part of the replay slip contract. A replay member with suppress-gated selected legs must stop before eval aggregation, CAT training, or builder training.
- `caution` context tags remain audit/ranking signals until replay evidence supports stricter gating. They are not a hard block by themselves.

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

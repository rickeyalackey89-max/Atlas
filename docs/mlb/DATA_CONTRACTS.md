# Atlas MLB Data Contracts

Status: draft  
Last updated: 2026-05-16

## Raw Snapshot Contract

Every source pull should write:

- raw payload
- source name
- pull timestamp UTC
- requested sport/league
- source URL or API route when safe
- request parameters
- response status
- checksum

Target:

```text
data/mlb/raw/<source>/<YYYY-MM-DD>/<timestamp>/
```

## Run Mode Contract

Every run manifest must declare one run surface:

- `live`
- `replay_single`
- `replay_corpus`

Rules:

- Live runs represent same-day scoring and do not settle outcomes.
- Single replays target one historical run or one raw snapshot set.
- Corpus replays target many single replay members through a corpus manifest.
- Replay artifacts must not overwrite live artifacts.
- Replay publishing is disabled by default.
- Replays are strict-fidelity by default: model inputs must match what the live
  model would have consumed and must not use post-date source context.

Recommended manifest fields:

- `run_id`
- `run_mode`
- `created_at_utc`
- `source_manifest_path`
- `output_root`
- `publishing_enabled`
- `fidelity_policy`
- `replay_corpus_id`
- `replay_member_count`
- `parent_live_run_id`

## Normalized Board Contract

One row per player-market-line candidate.

Required columns:

- `snapshot_id`
- `source`
- `source_projection_id`
- `event_id`
- `league`
- `game_date`
- `start_time_utc`
- `team`
- `opponent`
- `player_id`
- `player_name`
- `player_team`
- `player_position`
- `market`
- `source_market`
- `line`
- `side`
- `odds`
- `book`
- `platform`
- `is_live`
- `is_combo`
- `combo_player_ids`
- `status`
- `tier`
- `updated_at`
- `pulled_at_utc`

## Game Environment Feature Contract

One row per game.

Candidate columns:

- `event_id`
- `park_id`
- `home_team`
- `away_team`
- `probable_home_sp`
- `probable_away_sp`
- `home_bullpen_fatigue`
- `away_bullpen_fatigue`
- `weather_temp_f`
- `wind_speed_mph`
- `wind_direction`
- `roof_state`
- `market_total`
- `market_home_implied_runs`
- `market_away_implied_runs`
- `home_lineup_confirmed`
- `away_lineup_confirmed`
- `home_probable_pitcher_confirmed`
- `away_probable_pitcher_confirmed`

## Player Feature Contract

One row per player-market-line candidate.

Candidate columns:

- `run_id`
- `source_projection_id`
- `event_id`
- `player_id`
- `player_name`
- `player_team`
- `opponent`
- `player_position`
- `market`
- `line`
- `tier`
- `status`
- `is_live`
- `is_combo`
- `market_group`
- `batting_order_slot`
- `throws_or_bats_hand`
- `opposing_pitcher_hand`
- `season_rate`
- `recent_rate_7d`
- `recent_rate_14d`
- `platoon_split`
- `park_adjustment`
- `weather_adjustment`
- `role_stability`
- `line_movement`
- `injury_status`
- `lineup_probability`
- `plate_appearance_projection`
- `minor_league_prior_available`
- `opportunity_model_version`
- `opportunity_type`
- `projected_opportunity`
- `opportunity_floor`
- `opportunity_ceiling`
- `opportunity_confidence`
- `opportunity_fragility_score`
- `feature_model_version`
- `flags`

Current baseline artifact:

```text
data/mlb/features/player_props/<run_id>/feature_table.csv
data/mlb/features/player_props/<run_id>/feature_table.json
data/mlb/features/player_props/<run_id>/feature_manifest.json
```

## Advanced Player Profile Contract

One row per player profile from Baseball Savant, Rotowire, or another future
advanced-stat source. This is source-neutral by design: raw source fields can
change, but staged profiles must keep this shape before the probability layer
reads them.

Required identity columns:

- `statsapi_person_id`
- `player_id`
- `player_name`
- `player_name_key`
- `player_team`
- `bats`
- `throws`
- `profile_role`

Recommended signal columns:

- `sample_pa`
- `sample_bf`
- `xwoba`
- `xba`
- `xslg`
- `woba`
- `iso`
- `barrel_rate`
- `hard_hit_rate`
- `k_rate`
- `bb_rate`
- `whiff_rate`
- `chase_rate`
- `contact_rate`
- `avg_exit_velocity`
- `avg_launch_angle`
- `source`
- `flags`

Staged artifact:

```text
data/mlb/staged/advanced_profiles/<run_id>/advanced_profiles.csv
data/mlb/staged/advanced_profiles/<run_id>/advanced_profiles.json
data/mlb/staged/advanced_profiles/<run_id>/advanced_profiles_manifest.json
```

## Advanced Player Context Contract

One row per player-market-line candidate. This joins staged advanced player
profiles to the engine board and emits probability-ready context signals.
Missing profile data is neutral and explicit; it must not fail a run.

Required columns:

- `run_id`
- `source_projection_id`
- `event_id`
- `player_id`
- `player_name`
- `player_team`
- `opponent`
- `game_date`
- `market`
- `line`
- `tier`
- `advanced_context_available`
- `advanced_context_score`
- `advanced_hit_context_score`
- `advanced_power_context_score`
- `advanced_plate_discipline_score`
- `advanced_k_context_score`
- `advanced_contact_quality_score`
- `advanced_sample_confidence`
- `advanced_profile_source`
- `advanced_profile_match_type`
- `advanced_context_flags`

Runtime artifact:

```text
data/mlb/features/advanced_context/<run_id>/advanced_context.csv
data/mlb/features/advanced_context/<run_id>/advanced_context.json
data/mlb/features/advanced_context/<run_id>/advanced_context_manifest.json
```

Parameter behavior:

- Hitter props may receive a capped target shift from advanced context.
- Pitcher props remain neutral until dedicated pitcher-profile logic is added.
- Missing advanced context is reportable through manifests and context audits.

## Injury Contract

One row per injured or uncertain player.

Required columns:

- `source`
- `pull_timestamp_utc`
- `player_id`
- `player_name`
- `team`
- `position`
- `status`
- `estimated_return`
- `comment`
- `report_date`

## Minor League Player Contract

One row per player-season or player-level summary.

Required columns:

- `source`
- `player_id`
- `player_name`
- `milb_team`
- `mlb_org`
- `level`
- `position`
- `bats`
- `throws`
- `season`
- `games`
- `stat_scope`
- `stats_json`

## StatsAPI Team Contract

One row per MLB or MiLB team.

Required columns:

- `season`
- `sport_id`
- `level`
- `team_id`
- `team_name`
- `team_abbreviation`
- `team_short_name`
- `club_name`
- `league_id`
- `league_name`
- `division_id`
- `division_name`
- `parent_org_id`
- `parent_org_name`
- `venue_id`
- `venue_name`
- `active`

## StatsAPI Roster Contract

One row per player on a team roster snapshot.

Required columns:

- `season`
- `team_id`
- `team_name`
- `sport_id`
- `level`
- `parent_org_id`
- `parent_org_name`
- `person_id`
- `player_name`
- `first_name`
- `last_name`
- `primary_position`
- `jersey_number`
- `status`
- `roster_type`
- `bats`
- `throws`
- `birth_date`
- `height`
- `weight`

## StatsAPI Schedule Contract

One row per game.

Required columns:

- `sport_id`
- `level`
- `game_pk`
- `game_date`
- `official_date`
- `status`
- `away_team_id`
- `away_team_name`
- `home_team_id`
- `home_team_name`
- `venue_id`
- `venue_name`
- `double_header`
- `game_number`
- `series_description`

## StatsAPI Boxscore Contract

One row per player/team side in a game box score.

Required columns:

- `game_pk`
- `team_side`
- `team_id`
- `team_name`
- `opponent_id`
- `opponent_name`
- `person_id`
- `player_name`
- `position`
- `batting_order`
- `is_starter`
- `batting_stats`
- `pitching_stats`
- `fielding_stats`

## StatsAPI Player Game Log Contract

One row per player/game/stat-group split.

Required columns:

- `season`
- `person_id`
- `player_name`
- `group`
- `game_pk`
- `game_date`
- `team_id`
- `team_name`
- `opponent_id`
- `opponent_name`
- `is_home`
- `stat`

## Scored Output Contract

One row per scored candidate.

Required columns:

- `run_id`
- `source_run_id`
- `snapshot_id`
- `source_projection_id`
- `event_id`
- `game_date`
- `start_time_utc`
- `player_id`
- `player_name`
- `player_team`
- `opponent`
- `market`
- `source_market`
- `line`
- `side`
- `over_probability`
- `under_probability`
- `push_probability`
- `model_probability`
- `mean_projection`
- `median_projection`
- `p10`
- `p25`
- `p75`
- `p90`
- `volatility_score`
- `fragility_score`
- `stability_score`
- `opportunity_model_version`
- `opportunity_type`
- `projected_opportunity`
- `opportunity_confidence`
- `opportunity_fragility_score`
- `simulation_n`
- `simulation_seed`
- `simulation_kernel_version`
- `parameter_model_version`
- `calibration_version`
- `fair_price`
- `fair_decimal`
- `market_price`
- `edge`
- `confidence_tier`
- `kernel_version`
- `model_version`
- `method`
- `flags`
- `tier`
- `status`
- `is_live`
- `is_combo`
- `pulled_at_utc`

Current paths:

```text
data/mlb/test_runs/<run_id>/scored_legs.csv
data/mlb/live_runs/<run_id>/scored_legs.csv
data/mlb/<test_runs|live_runs>/<run_id>/scored_legs_deduped.csv
data/mlb/<test_runs|live_runs>/<run_id>/scored_legs.json
data/mlb/<test_runs|live_runs>/<run_id>/score_manifest.json
data/mlb/<test_runs|live_runs>/latest_scored_legs.csv
data/mlb/<test_runs|live_runs>/latest_scored_legs_deduped.csv
data/mlb/<test_runs|live_runs>/latest_scored_legs.json
data/mlb/<test_runs|live_runs>/latest_score_manifest.json
```

`score_manifest.json` must include:

- `parameter_table_path`
- `parameter_row_match_count`
- `parameter_row_missing_count`

Live and replay scoring should be considered invalid if a generated parameter
table exists but parameter-row matches are incomplete. Direct ad hoc scoring may
fall back to market priors, but full pipeline runs must score from the generated
parameter artifact.

Current scorer status:

- context-free market-prior baseline
- baseline opportunity parameter layer
- Sobol/QMC simulation shell
- parameter-table-driven scoring in full pipeline execution
- contract scaffolding only
- not a production calibrated model
- designed so later CAT/GBM kernels can preserve the same output shape

## Slip Output Contract

MLB run outputs follow the Atlas family surface:

```text
data/mlb/<test_runs|live_runs>/<run_id>/System/recommended_2leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/System/recommended_3leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/System/recommended_4leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/System/recommended_5leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/Windfall/recommended_2leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/Windfall/recommended_3leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/Windfall/recommended_4leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/Windfall/recommended_5leg.csv
data/mlb/<test_runs|live_runs>/<run_id>/demonhunter.csv
data/mlb/<test_runs|live_runs>/<run_id>/marketed_slips.csv
data/mlb/<test_runs|live_runs>/<run_id>/marketed_slips.json
data/mlb/<test_runs|live_runs>/<run_id>/slips/slips_manifest.json
data/mlb/<test_runs|live_runs>/<run_id>/slips/payout_quote_manifest.json
```

Tier labels are canonical PrizePicks/Atlas labels: `GOBLIN`, `STANDARD`, and
`DEMON`. The root `recommended_*leg.csv` files mirror the System family for
compatibility with Atlas consumers.

Public slips enforce the Atlas tier-mix contract:

- System: 2-leg `1 GOBLIN / 1 STANDARD`; 3-leg `1 / 2`; 4-leg `2 / 2`; 5-leg `3 / 2`.
- Windfall: 2-leg `1 GOBLIN / 1 DEMON`; 3-leg `1 GOBLIN / 1 STANDARD / 1 DEMON`; 4-leg `1 / 2 / 1`; 5-leg `2 / 2 / 1`.
- DemonHunter: every leg is `DEMON`.
- Marketed: normal slate templates are 3-leg `1 GOBLIN / 2 STANDARD`, 4-leg `2 / 2`, and 5-leg `2 GOBLIN / 2 STANDARD / 1 DEMON`; single-game slates use the Atlas 2-leg and 3-leg templates.

`GOBLIN` and `DEMON` are OVER-only in public slip output. Scored legs may still
retain invalid tier-direction rows for audit/evaluation, but the slip writer
filters them before producing website-facing artifacts.

Public output also enforces a portfolio exposure rule before writing slips:

- priority is `Marketed`, then `System`, then `Windfall`, then `DemonHunter`
- the same exact picked leg may appear at most once across all public slips
- exact picked leg identity is `player/event/market/line/side`

This rule is intentionally stricter than the current NBA production builder so
one failed MLB prop does not cascade across multiple website-facing families.

PrizePicks payout quoting is a replayable tool contract:

- live runs under `data/mlb/live_runs/<run_id>/` call `core.prizepicks_quote`.
- replay/test runs do not call the live PrizePicks quote API by default.
- every completed public slip writes a row in `slips/payout_quote_manifest.json`.
- exact quotes have `payout_is_exact=true`; fallback replay payouts are marked
  `payout_is_exact=false` with a `fallback_*` quote status.
- slip JSON and CSV outputs carry `payout_quote_status`, `payout_is_exact`, and
  `payout_quote_key` so website and model consumers can tell exact live quotes
  from fallback contract payouts.

## Operator AI Contract

Per-run operator artifacts:

```text
data/mlb/<test_runs|live_runs>/<run_id>/operator/
  operator_input.json
  anomalies.jsonl
  ai_evaluation.json
  publish_decision.json
  operator_report.md
```

`operator_input.json` is the read-only packet for deterministic and future
OpenAI review. It includes run counts, score summaries, simulation summaries,
parameter summaries, slip summaries, top legs, anomaly context, artifact paths,
and guardrails.

`publish_decision.json` required fields:

- `run_id`
- `run_mode`
- `publish_allowed`
- `severity`
- `summary`
- `anomalies`
- `operator_notes`
- `recommended_next_actions`
- `ai_status`
- `ai_model`

Rules:

- deterministic hard stops block publish
- AI decisions cannot override deterministic hard stops
- AI does not mutate model probabilities or slips
- replay publish decisions default to disabled

## Evaluation Contract

One row per settled candidate.

Replay evaluation writes both leg-level and slip-level artifacts:

```text
data/mlb/eval/<run_id>/eval_legs.csv
data/mlb/eval/<run_id>/eval_legs.json
data/mlb/eval/<run_id>/eval_slips.csv
data/mlb/eval/<run_id>/eval_slips.json
data/mlb/eval/<run_id>/slip_eval.json
data/mlb/eval/<run_id>/eval_manifest.json
```

`run board --run-mode replay*` writes these eval artifacts automatically.
`live` runs do not settle outcomes. The scheduled morning helper
`scripts/mlb/run_prior_day_eval.ps1` fetches prior-day StatsAPI boxscores and
runs `audit eval` so the prior day's live or replay output has both
`eval_legs` and `eval_slips`.

Required columns:

- `run_id`
- `event_id`
- `player_id`
- `market`
- `line`
- `side`
- `actual_value`
- `result`
- `model_probability`
- `brier`
- `settlement_status`
- `settlement_source`

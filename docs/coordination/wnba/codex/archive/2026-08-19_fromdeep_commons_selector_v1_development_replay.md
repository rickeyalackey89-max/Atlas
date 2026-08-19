# WNBA FromDeep Commons Selector V1 — Development Replay

Status: **USER/CHAT AUTHORIZED — ACTIVE CODEX EXECUTION MISSION**

Date: 2026-08-19

Mission ID: `WNBA_FROMDEEP_COMMONS_SELECTOR_V1_DEVELOPMENT_REPLAY`

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Starting pushed target SHA: `02f8b7143012c879df55078fb7017ed9635382ea`

## Accepted predecessor

Accept WIN-vs-LOSS Commons R0 at `02f8b7143012c879df55078fb7017ed9635382ea` as descriptive development discovery evidence.

Accepted result:

- 38 dates / 27 markets / 20,626 rows;
- 4,305 WIN / 15,127 LOSS binary evidence;
- 19 markets = `POSITIVE_COMMONS_PRESENT`;
- 8 markets = `INSUFFICIENT_EVIDENCE`;
- no selector was selected, fitted, frozen, promoted, validated or opened against lockbox/Live.

This mission converts that completed commons discovery packet into **one simple deterministic candidate selector** and replays it causally. It does not reopen commonality discovery and does not build a new research engine.

## Scientific honesty / evidence class

The feature identities and positive/veto directions below were discovered using the full development corpus. Therefore this replay is **development-consumed procedural/performance evidence**, not untouched OOS confirmation.

The replay must still be strict historical-as-of for every target date so the selector uses only pregame feature values and prior-history numeric thresholds available at `t < D`.

If the replay is promising, the selector may later be frozen for protected validation with the rest of the completed stack. Validation and lockbox remain sealed in this mission.

## Selector freeze rule

Do not cherry-pick only the prettiest of the 19 positive markets after seeing the Commons R0 rates.

Use **all 19 markets** that passed the same fixed Commons R0 screen. The eight `INSUFFICIENT_EVIDENCE` markets abstain.

For each positive market, use exactly the primary positive qualifier and primary veto stated in that market's Commons R0 plain-language selector sentence. Do not substitute second/third features or pairwise intersections in this mission.

The 19 frozen market rules are:

1. `3_pt_attempted`: positive `season_ftm_per_game >= q75`; veto `last_10_minutes_sd <= q25`.
2. `assists`: positive `projection_independent_disagreement == true`; veto `external_market_line_match_type == 'wide_nearest'`.
3. `blks_stls`: positive `opportunity_signal_pace >= q75`; veto `opponent_allowed_fg3m_per_game >= q75`.
4. `blocks`: positive `opponent_prior_def_rebound_pct <= q25`; veto `opponent_allowed_def_rebounds_per_game <= q25`.
5. `double_double`: positive `team_prior_fga_per_game <= q25`; veto `player_position == 'G'`.
6. `fantasy_score`: positive `last_20_stat_sd >= q90`; veto `bbref_ts_pct >= q90`.
7. `fg_attempted`: positive `team_prior_turnovers_per_game >= q75`; veto `opponent_allowed_fg2a_per_game <= q25`.
8. `free_throws_attempted`: positive `rotowire_usage_proxy >= q75`; veto `season_fga_per_minute <= q25`.
9. `free_throws_made`: positive `rotowire_usage_proxy >= q50`; veto `team_prior_def_rebounds_per_game <= q50`.
10. `offensive_rebounds`: positive `team_prior_off_rebounds_per_game <= q10`; veto `season_fga_per_minute <= q10`.
11. `points`: positive `score_recommended_side == 'over'`; veto `rotowire_projection_edge <= q10`.
12. `points_assists`: positive `bettingpros_projection_mean >= q50`; veto `projection_prior_edge <= q10`.
13. `points_rebounds`: positive `bettingpros_projection_target_line <= q50`; veto `projection_prior_edge <= q10`.
14. `points_rebounds_assists`: positive `bettingpros_projection_target_line >= q75`; veto `external_market_line_match_type == 'no_line_within_threshold'`.
15. `rebounds`: positive `bettingpros_projection_target_line <= q10`; veto `projection_prior_edge <= q10`.
16. `rebounds_assists`: positive `external_market_line_match_type == 'exact'`; veto `rotowire_projection_edge <= q10`.
17. `steals`: positive `opportunity_signal_pct_fta >= q75`; veto `team_prior_assists_per_game <= q25`.
18. `three_pointers_made`: positive `bettingpros_projection_edge >= q90`; veto `rotowire_projection_edge <= q10`.
19. `turnovers`: positive `projection_independent_agreement_count >= q90`; veto `public_role_current_minutes <= q25`.

The eight abstaining markets are:

- `defensive_rebounds`
- `fg_made`
- `quarters_with_3_points`
- `quarters_with_4_points`
- `quarters_with_5_points`
- `triple_double`
- `two_pointers_attempted`
- `two_pointers_made`

## Numeric threshold semantics

For numeric conditions, the frozen identity is `field + operator + quantile symbol`, **not** the full-corpus literal cutpoint printed in Commons R0.

For each target date `D` and market:

- compute the referenced q10/q25/q50/q75/q90 from that market's nonmissing **pregame candidate values on prior admitted dates `t < D` only**;
- use no target/future feature values to set the threshold;
- use no outcomes to compute the threshold;
- categorical/boolean conditions use the exact frozen value.

This removes future feature-distribution leakage while preserving the discovered feature/operator identity.

## Cold-start / application rule

Before a market may emit on target date `D`, prior binary development history for that market must include at least:

- 24 WIN/LOSS rows;
- 8 unique prior dates;
- 6 unique prior participants/combo identities.

If not, abstain for that market/date.

For each target candidate row after the prior-only thresholds are frozen:

`QUALIFIED = positive_condition_matches AND NOT veto_condition_matches`

Missing positive value -> not qualified.

Missing veto value -> veto does not match.

No additional GREEN/RED/Wilson/temporal-road gate is applied. This is intentionally the simple commons selector being tested.

## Output semantics

FromDeep is not a slip.

Preserve **all** qualified single-leg rows. Zero, one, or multiple qualified singles per slate are valid.

Do not rank or cap them for product output in this mission. Existing model probability may be reported as context only and may not create or remove qualification.

Core 2L/3L/4L slip attachment/routing is not part of this mission.

## Execution path

Prefer the simplest faithful replay from already-sealed development artifacts/checkpoints.

- Do not build a new engine.
- Do not rerun Commons R0.
- Do not rerun the exhaustive SAFE road registry.
- Do not generate Tier A/Tier B roads.
- Do not regenerate source boards if the sealed candidate rows already provide the required pregame fields.
- Reuse existing historical-as-of/checkpoint utilities only where they reduce work; a small direct selector adapter/reporting utility is allowed if needed.

One parent mission preamble. Subagents inherit it. No repeated governance cycle for ordinary inspection/testing.

## Required report

Per market and overall, report:

- target dates eligible after cold start;
- qualified single count;
- WIN / LOSS / nonbinary counts;
- strict binary WIN rate;
- date-balanced WIN rate;
- unique dates and participants;
- same-market baseline on the exact selected target dates;
- lift versus that baseline;
- qualified singles per target-date distribution;
- positive-condition match count;
- veto match/removal count;
- how many otherwise-positive rows the veto removed and their post-seal WIN rate;
- whether output is stable across early/later target dates;
- which markets produced no qualified singles.

Also report the existing 90/90 + 24 selections / 8 dates product target as a **diagnostic reference only**, not an automatic method rewrite trigger.

Return one machine-readable selection artifact containing every sealed qualified single and one concise human-readable market summary.

## Resource / workflow envelope

Target parent mission: <=45 minutes.

Hard workflow boundary: 75 minutes. If not complete, stop and report the blocker rather than building more infrastructure.

The actual selector replay should be lightweight relative to the completed R1 evaluator.

No checkpoint framework expansion, storage-cleanup ceremony, generalized engine abstraction, or unrelated governance work.

## Hard boundaries

Prohibited:

- changing any of the 19 frozen positive/veto identities;
- adding second/third commons or intersections;
- dropping one of the 19 markets because its replay looks weak;
- adding one of the 8 insufficient markets;
- fitting/tuning a model;
- threshold search beyond prior-only quantile realization;
- validation or lockbox access;
- Aug. 13 contribution;
- Live/model/publication/promotion mutation;
- core-family method changes;
- FromDeep slip construction or core-slip attachment rules.

## Completion

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_COMMONS_SELECTOR_V1_DEVELOPMENT_REPLAY_COMPLETE`

At that stop, Chat/user will decide whether this simple candidate method is strong enough to freeze for protected validation, needs one narrowly justified commons-method revision, or should be rejected without further open-ended research.

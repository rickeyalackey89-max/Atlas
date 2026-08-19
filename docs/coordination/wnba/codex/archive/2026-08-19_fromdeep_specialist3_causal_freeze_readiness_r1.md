# WNBA FromDeep Specialist-3 Causal Freeze Readiness R1

Status: **USER/CHAT AUTHORIZED — ACTIVE CODEX EXECUTION MISSION**

Date: 2026-08-19

Mission ID: `WNBA_FROMDEEP_SPECIALIST3_CAUSAL_FREEZE_READINESS_R1`

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Starting pushed target SHA: `bf7475530320f7f90eaf1604982f9df14bfeb7c6`

## Accepted predecessor

Accept Recent Precision Roads R0 at `bf7475530320f7f90eaf1604982f9df14bfeb7c6` as completed development-consumed road discovery.

Accepted census:

- 14,615 contradiction-valid roads graded;
- 3,665 screen-qualified;
- 220 Pareto-valid;
- 33 finalists;
- 8 `SPECIALIST_GRADE_CURRENT_CANDIDATE` roads across exactly three markets;
- 19 `SPARSE_HIGH_PRECISION_WATCHLIST` roads;
- 6 `DECAYING` evidence-class roads;
- the eight-road non-decaying diagnostic union was too broad for the FromDeep product;
- analyzer runtime about 29.6 seconds;
- protected/validation/lockbox/Aug.13/heldout/fitting/Live access all zero.

This mission does **not** reopen road discovery.

## Binding cross-sport product doctrine

Read and bind:

- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_DOCTRINE.md`
- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_NAMES.md`

WNBA FromDeep is the same shared Atlas Demon-specialist concept as MLB BigSwings and NFL HailMarys: sparse, precision-first, market-owned, abstention-friendly single-leg flex/add-on picks, normally about 0-3-ish fires per run/slate.

## User/Chat freeze-candidate decision

The next development candidate is the **top-ranked specialist-grade road from each of the only three markets that produced specialist-grade evidence in R0**.

Freeze these road identities for this mission:

1. `fg_attempted`
   - road ID: `ROAD:18640a5f6a16e42a154fa86447c2a441da42a0c0201e11dd82f4b2f0b4133ad1`
   - road identity: `season_total_def_rebounds >= q75 AND opponent_allowed_fg3m_per_game <= q25`
   - R0 active/current: 8-2 / 8-2; strict 80%; current date-balanced 83.33%.

2. `free_throws_attempted`
   - road ID: `ROAD:653545eeb14ceac07a037a21b4f741dd85ccefadc135552cdec4b872563525e0`
   - road identity: `opponent_prior_off_rebounds_per_game <= q25 AND rotowire_usage_proxy >= q75`
   - R0 active: 7-1; current: 5-1; current strict/date-balanced 83.33%.

3. `free_throws_made`
   - road ID: `ROAD:6e42214971a4b68b8a0448170d7d4df19234866611e120e66c7bff7705da4a07`
   - road identity: `hours_to_game_start >= q50 AND NOT(team_prior_def_rebounds_per_game <= q50) AND team_prior_possessions_per_game >= q50`
   - R0 active: 8-2; current: 6-2; current strict 75%, date-balanced 80%.

Do not substitute an alias road, second/third-ranked road, watchlist road, or newly generated road.

The R0 trajectory label `DECAYING` on FTA/FTM does not itself disqualify those specialist-grade roads. Their current-window precision still clears the frozen specialist screen. This causal replay determines freeze readiness.

All watchlist, decaying-evidence-class, and no-current-road markets remain preserved research evidence but are **inactive for this freeze candidate**.

## Scientific question

**When the three frozen specialist road identities are replayed causally with only prior current-regime pregame information, do they remain precise enough and naturally sparse enough to freeze as the WNBA FromDeep candidate for one later protected validation?**

## Active regime and time arrow

Primary product regime remains current-season July/August.

- target/evaluation regime: usable dates from `2026-07-01` through `2026-08-09`;
- latest-10 usable dates remain the current-traction window;
- June is background/stress reporting only and contributes zero road selection, pass/fail, threshold realization, or support authority.

For each target date `D`:

1. use only pregame candidate feature values from admitted current-regime dates `t < D`;
2. realize every numeric q50/q75/q25 landmark from prior values only within the same market/field context;
3. require at least 24 prior nonmissing pregame values for each numeric gate before that road may fire on `D`; otherwise abstain for that road/date;
4. freeze all three road thresholds for `D`;
5. expose `D` pregame Demon-OVER candidates;
6. emit every candidate matching every gate in its frozen market road;
7. seal selections;
8. reveal `D` settlement only after seal;
9. append `D` only after grading.

Categorical/boolean semantics remain exact if any are encountered. Outcomes never set a threshold, gate, rank, or cap.

## No new selection research

This is a causal replay/freeze-readiness mission, not another discovery mission.

Do not:

- enumerate new road combinations;
- add/remove gates;
- replace a frozen road with another finalist;
- use watchlist roads;
- search numerical thresholds;
- fit/train/tune/calibrate a model;
- apply a probability top-N cap;
- reopen Commons R0 or the full condition universe;
- build a generalized research engine.

A small direct adapter around existing R0/replay utilities is allowed. Reuse existing sealed artifacts.

## Predeclared per-market freeze-readiness screen

Evaluate each of the three roads independently under the causal replay.

A road is `MARKET_FREEZE_READY` only if:

- at least 5 binary causal selections;
- at least 4 selected dates;
- at least 4 unique participants/combo identities;
- July/August strict binary WIN rate >= `0.65`;
- July/August lift versus exact contemporaneous same-market/date Demon baseline >= `+0.20` absolute;
- and in the latest-10 current window, when at least 4 binary selections across at least 3 dates exist:
  - strict binary WIN rate >= `0.70`;
  - date-balanced WIN rate >= `0.70`.

If current-window support is below 4 binary selections or 3 dates, classify the road `MARKET_FREEZE_WATCHLIST_INSUFFICIENT_CURRENT_SUPPORT`, not pass and not fail.

If the precision/lift thresholds fail with sufficient support, classify `MARKET_NOT_FREEZE_READY`.

These thresholds are frozen before execution. Do not tune them from results.

## Final sparse union rule

Form a final diagnostic union using only roads classified `MARKET_FREEZE_READY`.

There is no artificial top-N cap. The roads themselves must create the sparse product.

The union is `FROMDEEP_FREEZE_READY_FOR_PROTECTED_VALIDATION` only if:

- at least one market is `MARKET_FREEZE_READY`;
- latest-10 union strict WIN rate >= `0.70` when at least 5 binary union selections exist;
- latest-10 union date-balanced WIN rate >= `0.70` when gradeable;
- latest-10 median fires per usable date <= `1.5`;
- latest-10 90th-percentile fires/date <= `3`;
- latest-10 maximum fires/date <= `3`;
- percentage of latest-10 dates with more than 3 fires = `0`.

If precision passes but the density screen fails, return `FROMDEEP_PRECISION_PASS_DENSITY_FAIL`; do not invent a ranking cap.

If no market passes, return `FROMDEEP_NO_MARKET_FREEZE_READY`.

## Required report

Per road and for the final pass-only union report:

- eligible dates after causal quantile cold start;
- every sealed selected single-leg row;
- W/L/nonbinary;
- strict and date-balanced rates;
- exact-date same-market Demon baseline and lift;
- unique dates and participants;
- latest-10 current-window performance;
- fires per usable date;
- early-current versus newest-current chronology for context;
- June background outcome only after road evaluation, clearly `BACKGROUND_ONLY`;
- exact freeze-readiness classification and failed criterion if any.

Also report mission wall-clock time separately from runner/analyzer time.

## Workflow / resource envelope

This is one bounded mission.

One full Builder preamble at activation. Subagents inherit it.

No repeated governance cycles for ordinary implementation, testing, audit, or reporting.

Execution tier: `R1_ACTIONABILITY_CANARY` / lightweight causal replay using existing sealed artifacts.

Target parent mission <=30 minutes. Hard workflow boundary 45 minutes. If the mission is not essentially complete by 45 minutes, return the concrete blocker rather than building infrastructure.

No checkpoint framework expansion. No storage cleanup unless an actual measured resource blocker appears.

## Hard boundaries

Validation reads: `0` permitted.

Lockbox reads: `0` permitted.

Aug.13 contribution: `0` permitted.

Heldout/protected evidence: prohibited.

Live/model/publication/promotion mutation: prohibited.

Core 2L/3L/4L changes: prohibited.

Do not open protected validation automatically even if freeze-readiness passes.

## Completion

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_SPECIALIST3_CAUSAL_FREEZE_READINESS_R1_COMPLETE`

Return the causal evidence and exact pass/watchlist/fail set to Chat/user. The next user/Chat decision is whether to freeze the passing road set and authorize one protected validation.

# Atlas Config Reference

> **Last updated:** 2026-05-10
> **Source file:** `config.yaml` at workspace root
> **Purpose:** One-stop reference for every config section — what it controls, valid ranges, and whether a change requires GBM retraining or takes effect immediately on the next live run.

---

## How Config Changes Work

| Change Type | GBM Retrain Needed? | Takes Effect |
|---|---|---|
| Telemetry calibration path/mode | No | Next run |
| `role_ctx` clamps and multipliers | No | Next run |
| `blowout` spread_sd, thresholds | No | Next run |
| `slip_build` beam_width, penalties, prob floors | No | Next run |
| `optimizer` external priors cap/scale | No | Next run |
| `marketed_slips` thresholds, windows | No | Next run |
| `demonhunter` prob floors, stats | No | Next run |
| Adding/removing a GBM feature | **Yes** | After `gbm_vN_train.py --promote` |
| Changing `posthoc_calibrator.ensemble_dir` | No (new models must exist) | Next run |
| Changing CatBoost v5cD features | **Yes** | Requires CatBoost retrain + replay validation |
| Changing `catboost_playoff_calibrator.model_path` | No (new model must exist) | Next run |
| `pp_kernel` coefficients | No | Next run |

---

## Section: `telemetry`

Controls the optional isotonic overlay after the active calibrated probability.
As of 2026-05-10 this layer is **configured but disabled** because CatBoost v5cD is the active playoff calibrator.

| Key | Current Value | What It Does |
|---|---|---|
| `active_calibration` | `playoff_isotonic` | Configured isotonic key. Not applied while `apply_active_calibration=false`. |
| `active_calibration_path` | `data/model/telemetry_calibration.playoff_isotonic.json` | Path to the configured isotonic calibration JSON. |
| `apply_active_calibration` | `false` | Master switch. Current production bypasses isotonic overlay. |
| `calibration_policy.allow_family_split` | `true` | Allows separate calibration curves per leg family (role_on vs role_off). |
| `calibration_policy.family_order` | `[role_off, role_on]` | Order in which family rules are matched. First match wins. |
| `calibration_policy.strict_source_gating` | `true` | Leg must match a calibration rule's source filters to receive adjustment. No match → identity (no change). |
| `post_calibration.*_blend_retain` | `1.0` | How much of the isotonic adjustment to retain for combo-under legs. `1.0` = full retention, `0.0` = revert to pre-isotonic. |

**Calibration JSON format:** See `data/model/telemetry_calibration.playoff_isotonic.json`. Keys are rule names; each rule has `x_points` and `y_points` forming an isotonic mapping.

**To retrain:** `python tools/train_playoff_isotonic.py` — run only as an experiment unless the current CatBoost stack is intentionally being bypassed.

---

## Section: `role_ctx`

Controls the share matrix role context layer — how production redistribution from out players nudges per-minute rates.

| Key | Current Value | What It Does | Valid Range |
|---|---|---|---|
| `enabled` | `true` | Master switch for role context. `false` = role ctx disabled entirely, all `p_role = p`. | `true/false` |
| `projection_clamp_lo` | `0.9` | Minimum rate multiplier from share matrix. Clamps downward adjustments. | 0.8–1.0 |
| `projection_clamp_hi` | `1.11` | Maximum rate multiplier. Clamps upward adjustments. | 1.0–1.25 |
| `projection_softcap_k` | `0.9` | Soft-cap sharpness for extreme multipliers. Higher = softer approach to hard clamp. | 0.5–1.5 |
| `variance_k` | `0.65` | Scales how much variance increases when role context fires (uncertainty injection). | 0.0–1.5 |
| `variance_clamp_lo/hi` | `1.0 / 1.1` | Min/max variance multiplier bounds. | 0.9–1.5 |
| `combo_shrink` | `0.5` | For combo stats (PRA, PR, PA, RA), multiplier is shrunk by this factor. Prevents double-counting correlated components. | 0.0–1.0 |
| `min_games` | `3` | Minimum games in share matrix to trust the weight. Below this → share matrix entry ignored. | 2–10 |
| `close_sens_mult` | `0.35` | Scales how aggressively close-game context (spread < 5) modifies role context. | 0.0–1.0 |
| `weight_scale` | `8.8` | Controls how sharply share matrix game counts translate to weight. Higher = faster saturation. | 3.0–15.0 |
| `weight_power` | `1.2` | Exponent on game count in weight formula. | 0.5–2.0 |
| `accumulation` | `additive` | How multiple out-player share matrix entries combine. `additive` = sum of contributions (clamped). | `additive` / `max` |
| `max_outs_used` | `5` | Maximum number of out players that can contribute role context for one leg. | 1–10 |
| `star_beneficiary_damp` | `0.4` | Dampens role ctx mult when the beneficiary is a star (high usage/minutes). Prevents star-on-star overcounting. | 0.0–1.0 |
| `core_beneficiary_damp` | `1.0` | Dampener for core players. `1.0` = no damping. | 0.0–1.0 |
| `demon_tier_damp` | `0.0` | Dampens role ctx for DEMON-tier legs. `0.0` = fully suppressed. | 0.0–1.0 |
| `over_direction_damp` | `1.0` | Dampener for OVER legs specifically. `1.0` = no damping. | 0.0–1.0 |
| `multi_injury_boost` | `1.3` | Boosts role ctx when 2+ starters are out on the same team simultaneously. | 1.0–2.0 |
| `under_relief_q_min` | `0.1` | Minimum blowout risk (`q_blowout`) before under-relief applies. Below this → no relief. | 0.0–0.5 |
| `under_relief_haircut_min` | `0.05` | Minimum haircut fraction applied under under-relief. | 0.0–0.3 |
| `under_relief_factor` | `0.0` | Scale of under-relief adjustment. `0.0` = under-relief is disabled. | 0.0–1.0 |
| `zero_dnp_enabled` | `true` | Enables the zero-DNP correction (star with no DNP history goes out → bigger boost for backup). | `true/false` |
| `zero_dnp_dnp_thresh` | `2` | Out player must have fewer than this many historical DNP games to trigger. | 1–5 |
| `zero_dnp_min_cap` | `2.5` | Max minutes ratio applied under zero-DNP correction. Prevents extreme outliers. | 1.5–4.0 |
| `zero_dnp_min_blend` | `0.80` | Blend toward zero-DNP correction (1.0 = full correction, 0.8 = 80% of gap). | 0.5–1.0 |
| `zero_dnp_postcal_blend_thresh` | `1.40` | Only applies post-GBM blend when `role_ctx_mult >= this`. | 1.1–2.0 |
| `zero_dnp_postcal_blend_weight` | `0.70` | Weight on MC `p_adj` (vs GBM `p_cal`) in post-cal blend. Higher = trust MC more. | 0.3–1.0 |
| `zero_dnp_games_missed_max` | `7` | Suppress zero-DNP correction once an out player has missed this many consecutive games (GBM has learned the pattern). | 3–15 |

---

## Section: `blowout`

Controls blowout risk computation and minute-drop adjustments when spread is large.

| Key | Current Value | What It Does | Valid Range |
|---|---|---|---|
| `spread_sd` | `11.0` | Standard deviation of game spread used in blowout probability Normal model. Higher = blowouts are less likely at any given spread. | 8–18 |
| `threshold_margin` | `13.0` | Score margin (points) that triggers "blowout" in post-sim adjustment. | 10–25 |
| `star_minute_drop` | `8.0` | Minutes lost by star players in simulated blowout scenarios. | 4–15 |
| `role_minute_drop` | `0.5` | Minutes lost by role players. | 0.0–3.0 |
| `post_sim_exponent` | `0.0` | Current May 10 tuned value. | 0.0–1.0 |
| `rate_std_multiplier` | `1.0` | Global scalar on rate standard deviation for blowout computation. | 0.5–2.0 |
| `blowout_curve.slope` | `-0.28` | Slope of the minute-projection adjustment curve inside blowout scenario. | negative |
| `blowout_curve.intercept` | `4.0` | Intercept of minute adjustment curve. | 0–8 |
| `blowout_curve.crossover` | `14.0` | Minutes at which curve crosses zero (no adjustment). Legs expecting <14 min get boosted for UNDER; >14 get penalized for OVER. | 10–20 |
| `blowout_curve.max_gain` | `5.0` | Maximum minute gain for short-minute players in blowout. | 2–10 |
| `blowout_curve.max_drop` | `12.0` | Maximum minute loss for high-minute players in blowout. | 5–20 |
| `thin_window_games` | `15` | Games threshold for thin-window shrinkage. Players with fewer games get shrunk toward league prior. | 8–25 |
| `thin_window_max_mult` | `1.6` | Maximum variance multiplier applied to thin-window players (more uncertainty). | 1.0–3.0 |
| `recency_halflife` | `4` | Half-life (in games) for exponential recency weighting of recent game log. | 2–10 |
| `recent_form_blend` | `0.0` | Blend weight on recent-form rate adjustment. `0.0` = disabled. | 0.0–1.0 |
| `opp_defense_strength` | `1.0` | Scale factor for opponent defense adjustment. `1.0` = full strength. | 0.0–2.0 |
| `rate_std_multiplier_by_stat` | PRA/PR/PA/PTS: 1.3, RA: 1.1, AST: 1.2 | Per-stat rate std multipliers. Combo stats get higher uncertainty. | 0.5–3.0 |
| `rate_std_under_mult` | `2.0` | Additional multiplier on UNDER legs' rate std. Increases UNDER uncertainty. | 1.0–4.0 |
| `adjustment_rules` | 4 named rules | Structural adjustments by stat family + direction + q_blowout threshold. See below. | — |
| `series_multiplier.enabled` | `true` | Amplifies opponent-defense signal as playoff series progresses. |
| `playoff_regime.enabled` | `false` | Experimental playoff rate/minutes block; currently off. |

### `adjustment_rules` Reference

Each rule has: `name`, `direction` (OVER/UNDER), `families` (stat family list), `min_q` (blowout threshold), optional `max_q`, `starter_like` flag, `minute_drop_mult`, `sensitivity_mult`.

| Rule | Families | Direction | min_q | Effect |
|---|---|---|---|---|
| `combo_scoring_over_high_q_structural_v1` | combo_scoring | OVER | 0.35 | Drops minutes 22%, sensitivity 8% for starter-like players |
| `assists_over_high_q_structural_v1` | assists | OVER | 0.35 | Drops minutes 24%, sensitivity 12% |
| `threes_over_high_q_structural_v1` | threes | OVER | 0.35 | Drops minutes 18%, sensitivity 10% |
| `rebounds_over_midq_structural_v1` | rebounds | OVER | 0.20–0.30 | Drops minutes 10%, sensitivity 6% |

---

## Section: May 10 Kernel Transforms

These sections shape `p_adj` before calibration handoff. They are active in the current CatBoost v5cD runtime.

| Section | Current Value | What It Does |
|---|---|---|
| `kernel_high_prob_shrink` | `enabled=true`, `p_thr=0.75`, `k=0.0501` | Shrinks probabilities above 0.75 in logit space before CatBoost. |
| `kernel_blowout_bypass` | `enabled=true`, `q_lo=0.15`, `q_hi=0.50` | Reverts to `p_role` outside the blowout band where blowout adjustment validated poorly. |
| `kernel_subset_shifts` | UNDER delta `-0.1651` | Applies an UNDER logit correction before CatBoost. |
| `kernel_prob_floors` | GOBLIN OVER floor `0.40` | Repairs low-quintile GOBLIN OVER underprediction. |
| `kernel_logit_shrinks` | combo stats `RA/PA/PRA/PR`, `k=0.90` | Shrinks combo-stat probabilities toward 0.5 to reflect missing covariance/variance. |

These are not model-training artifacts by themselves, but changing them changes the CatBoost input distribution. Any change should be replay-tested against the v5cD corpus.

---

## Section: `slip_build`

Controls the main slip builder (System and Windfall families).

| Key | Current Value | What It Does | Valid Range |
|---|---|---|---|
| `min_leg_prob` | `0.65` | Floor: only legs with `p_cal >= this` can enter main slips. | 0.50–0.80 |
| `max_leg_prob` | `0.0` | Ceiling. `0.0` = disabled (no cap). | 0.0–0.99 |
| `min_under_prob` | `0.0` | UNDER window disabled under v5cD. | 0.0–0.90 |
| `max_under_prob` | `0.0` | UNDER ceiling disabled under v5cD. | 0.0–0.99 |
| `beam_width` | `250` | Number of candidates retained per beam-search step. Higher = more exhaustive but slower. | 50–2000 |
| `phase1_frac` | `0.1` | Fraction of total candidate pool built in phase 1 (diversity-focused seed phase). | 0.05–0.5 |
| `target_pool_mult` | `200` | Multiplier on `n_legs` for total candidate pool size. `200 × n_legs` candidates explored. | 50–1000 |
| `max_players_per_team` | `2` | Max legs from same team in a single slip. | 1–5 |
| `max_slips_per_player` | `5` | Max times a player appears across all output slips. | 1–20 |
| `max_same_stat` | `2` | Max legs of the same stat type in one slip. | 1–5 |
| `single_game_caps_by_legs.3/4/5` | `2 / 3 / 3` | One-game slate team cap overrides so 4/5-leg slips can still build. | 1–5 |
| `penalty.team_w` | `0.15` | Penalty weight for team concentration. Higher = more team diversity. | 0.0–1.0 |
| `penalty.family_w` | `0.1` | Penalty weight for stat family concentration. | 0.0–1.0 |
| `penalty.frag_w` | `0.0` | Penalty weight for fragility-heavy slips. `0.0` = disabled. | 0.0–1.0 |
| `leg_quality_filters.min_standard_player_dir_te` | `0.02` | STANDARD legs below this `player_dir_te` are excluded (historically sub-coin-flip). | 0.0–0.10 |
| `leg_quality_filters.min_goblin_l20_edge` | `0.05` | GOBLIN legs below this `l20_edge` excluded (no recent-form confirmation). | 0.0–0.15 |

### `by_legs` Overrides

The top-level `slip_build` keys set defaults. `by_legs['3']`, `['4']`, `['5']` override per slip length. `by_sort_mode.ev` and `by_sort_mode.hit` add further overrides for Windfall (ev-sorted) and hit-rate-sorted variants. Most important per-length settings:

| Legs | max_direction_per_slip.under | min_edge | beam_width |
|---|---|---|---|
| 3 | 1 | 0.02 | 500 |
| 4 | 1 | 0.02 | 500 |
| 5 | 2 | 0.02 | default |

---

## Section: `optimizer`

| Key | Current Value | What It Does |
|---|---|---|
| `top_n_slips` | `1` | How many top slips to output per family/legs combination. |
| `emit_winprob_variants` | `false` | Whether to also emit `_winprob.csv` slips sorted by pure hit probability. |
| `seed` | `7` | Random seed for slip builder. |
| `external_priors.enabled` | `true` | Whether to apply BettingPros/OddsAPI nudge. |
| `external_priors.cap` | `0.05` | Max nudge in probability units (+/-). Higher = more influence from external. |
| `external_priors.scale` | `1.5` | Tanh scale for translating projection distance to nudge. |
| `external_priors.sources.*.weight` | `1.0` each | Weight per source (rotowire, bettingpros, oddsapi). |

---

## Section: `demonhunter`

| Key | Current Value (3-leg) | What It Does |
|---|---|---|
| `min_leg_prob` | `0.56` | Min `p_cal` for DEMON-tier legs in DemonHunter slips. |
| `allowed_stats` | `[PRA, PTS, FTA, RA, PR, PA]` | Only these stats allowed in DemonHunter slips. |
| `max_same_stat` | `0` (3-leg) | Max repeated stats per slip. `0` = no limit. |
| `max_players_per_team` | `2` | Team concentration cap. |
| `per_tier` | `800` (3-leg) | Pool size per DEMON tier before beam search. |
| `beam_width` | `600` (3-leg) | Beam search width. |

---

## Section: `marketed_slips`

Controls the subscriber-facing marketed slip builder and `p_cal_marketed` computation.

| Key | Current Value | What It Does |
|---|---|---|
| `enabled` | `true` | Master switch. |
| `calibration_path` | `data/model/marketed_calibration.json` | Stat×tier multiplier table used to compute `p_cal_marketed`. |
| `max_players_per_team` | `2` | Team concentration cap. |
| `single_game_caps_by_legs.3/4/5` | `2 / 3 / 3` | One-game slate caps. |
| `excluded_stats` | `[BLK, STL, TO, FTA]` | Stats never included in marketed slips. FTA remains excluded until a validated retrain says otherwise. |
| `min_thresholds.GOBLIN/STANDARD/DEMON` | `0.0 / 0.0 / 0.0` | Post-haircut floor disabled; builder gates on raw `p_cal`. |
| `min_raw_thresholds.*` | `0.68 / 0.55 / 0.50` | Pre-haircut `p_cal` floor per tier, recalibrated for v5cD. |
| `direction_filters` | GOBLIN/DEMON OVER-only; STANDARD OVER/UNDER | Defense-in-depth against invalid tier-direction combinations. |
| `min_under_prob` | `0.0` | UNDER floor disabled under v5cD. |
| `max_under_prob` | `0.0` | UNDER ceiling disabled under v5cD. |
| `hit_prob_calibration.3/4/5` | `1.37 / 1.33 / 1.34` | Recomputed 2026-05-10 against v5cD 10-date slip eval. |
| `high_confidence_thresholds.3/4/5` | `0.65 / 0.40 / 0.20` | `hit_prob` threshold for the `high_confidence` label. **Label only — not a filter.** |
| `correlation.same_team_penalty` | `0.03` | Penalty for correlated same-team legs in slip scoring. |
| `correlation.blowout_penalty` | `0.02` | Penalty for legs with high `q_blowout`. |

---

## Section: `posthoc_calibrator`

| Key | Current Value | What It Does |
|---|---|---|
| `enabled` | `false` | Historical GBM ensemble calibrator is currently disabled. |
| `ensemble_dir` | `data/model/ensemble` | Directory containing the historical 14 GBM `.txt` model files + `ensemble_meta.json`. |
| `mode` | `replace` | `replace` = GBM output replaces MC probability. `blend` = weighted blend. |
| `coefficients_path` | `data/model/posthoc_calibrator_coeffs_enriched.json` | Legacy path, used for fallback non-GBM calibration. Not active in current runtime. |

---

## Section: `catboost_playoff_calibrator`

This is the active May 10 playoff calibrator.

| Key | Current Value | What It Does |
|---|---|---|
| `enabled` | `true` | Enables runtime CatBoost calibration. |
| `kind` | `regressor` | Uses residual-regressor path, not legacy classifier path. |
| `model_path` | `data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm` | Active CatBoost model file. |
| `meta_path` | `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json` | Active feature/parameter contract. |
| `mode` | `replace` | Writes `p_catboost` into `p_cal`. |

Current v5cD is a 19-feature residual regressor trained on playoff dates 2026-04-30 through 2026-05-09.

---

## Section: `pp_kernel`

PrizePicks pricing model — translates `p_cal` to an expected payout multiplier. Not used in slip selection. Used for EV computation in slip ranking.

Coefficients are per-stat, per-tier. STANDARD and GOBLIN use linear models (`a*p + b`). DEMON uses a quadratic (`a*p^2 + b*p + c`). The `DEFAULT` entry applies to any stat not explicitly listed.

**Do not change these unless you have re-estimated them from PrizePicks actual payout data.**

---

## Quick Config Diagnostics

| Symptom | Likely Config Lever |
|---|---|
| Too many UNDER legs in slips | First verify v5cD calibration by direction; UNDER caps are currently disabled intentionally |
| Slips all from 2–3 teams | Raise `penalty.team_w` in relevant `by_legs` section |
| DEMON legs not appearing | Lower `demonhunter.min_leg_prob` or broaden `allowed_stats` |
| Marketed slips empty | Check `marketed_slips.min_raw_thresholds`, `direction_filters`, and one-game caps |
| Role ctx moving probabilities too aggressively | Lower `projection_clamp_hi` or reduce `multi_injury_boost` |
| Blowout adjustment too large for playoff games | Raise `spread_sd` (softer blowout curve) |
| External priors overpowering model | Lower `external_priors.cap` (e.g. 0.03) |
| CatBoost overriding kernel signal | Compare `p_for_cal`, `p_catboost_residual`, and `p_cal`; test `mode: blend` only in replay |

# Atlas Model Context

> **Last updated:** 2026-03-31 — reflects v9d baseline and post-cleanup workspace state.

---

## What Atlas Is

Atlas is an NBA player-prop probability engine and daily slip builder targeting PrizePicks.
It ingests the live PrizePicks board, injury data, game logs, spreads, and team-context
information, then produces calibrated over/under probabilities for every leg and assembles
optimized multi-leg slip candidates.

Atlas is **not** just a probability calculator. It is a full decision pipeline:

1. Fetch the current PrizePicks board and convert it to structured data.
2. Freeze the injury state and redistribute production from out players to teammates.
3. Score every leg through a Monte-Carlo probability kernel.
4. Post-process with a 7-seed LightGBM ensemble calibrator (v9d).
5. Apply telemetry-driven isotonic calibration.
6. Build slips across three output families (System, Windfall, DemonHunter).
7. Publish run artifacts and optional bundle zip.

---

## Current Baseline — v9d

| Metric | Value |
|---|---|
| **Ensemble LODO Brier** | 0.196266 |
| **Ensemble LODO Hit Rate** | 69.86% |
| **Reader Brier (p_adj)** | 0.20046 |
| **Reader Corpus** | 49,956 legs / 22 runs |
| **Features** | 33 (trimmed from 56 in v9c) |
| **Temperature** | 0.98 |
| **Seeds** | 65536, 9999, 137, 999, 98765, 54321, 12345 |
| **Architecture** | dn-d11nl50 (direction-split GBMs) |
| **Training legs** | 171,214 across 33 dates |
| **Previous version** | v9c (Brier 0.200908) |

Full metadata is stamped in `data/model/ensemble/ensemble_meta.json`.

### GBM Parameters

| Parameter | OVER | UNDER |
|---|---|---|
| max_depth | 11 | 15 |
| num_leaves | 50 | 90 |
| min_child_samples | 200 | 150 |
| lambda_l2 | 1.0 | 6.0 |
| learning_rate | 0.03 | 0.03 |
| n_rounds | 200 | 200 |

The ensemble produces 14 model files (7 OVER + 7 UNDER, one per seed) stored in
`data/model/ensemble/`.

### v9d Feature List (33 features)

```
z_line, min_cv, is_combo, bp_score_gated, bp_has, is_assists, is_threes,
games_norm, thin_flag, line_norm, is_home_feat, min_sensitivity,
game_total_norm, is_b2b, l20_edge, l10_has, margin, stat_cat, tier_cat,
l40_hr, logit_p_x_demon, player_te, player_stat_te, player_dir_te,
player_n_norm, line_dist, tail_risk, line_tightness, margin_x_under,
q_blowout, rate_cv, abs_logit_p, q_x_under
```

Categorical features: `stat_cat`, `tier_cat`.

---

## Core Model Goal

Maximize edge by keeping the math aligned with real basketball behavior:

- **Who benefits when someone is out?** → Share matrix + role context allocator.
- **How much do usage and minutes shift?** → Team share allocator v2.
- **Which stat lines are fragile in blowouts?** → Blowout / fragility layer.
- **Which overs or unders are structurally stronger?** → Structural blowout rules.
- **Which combinations build the best slip?** → Beam-search slip builder.

---

## Main Inputs

| Input | Source | Path |
|---|---|---|
| PrizePicks board | Live fetch or pinned raw JSON | `data/raw/prizepicks_*.json` → `data/board/today.csv` |
| Injury data | IAEL (Injury/Absence/Eligibility Layer) | `data/output/dashboard/injury_invalidations_latest.json` |
| Game logs | NBA API rolling refresh | `data/gamelogs/nba_gamelogs.csv` |
| Spreads & totals | Rotowire fetch | `data/input/rotowire_lines.json` |
| External priors | BettingPros props | `data/input/external_priors_today.csv` |
| Role metrics | External adapter snapshot | `data/output/dashboard/role_metrics_latest.json` |
| Share matrix | Prebuilt from game logs | `data/model/share_matrix.csv` |
| Roster map | Manual/semi-auto | `data/input/roster_map.csv` |
| Slate schedule | Derived from board | `data/input/slate.csv` |

---

## Processing Layers (in order)

### 1. Board Ingestion
Fetches the live PrizePicks board (or loads a pinned raw JSON in replay mode) and
converts it into `data/board/today.csv` — the canonical input for the scoring kernel.

### 2. Injury Filtering (IAEL)
Out and doubtful players are removed. Questionable players are tagged with `is_questionable`
and `q_out_frac` so the model can reason about them explicitly rather than silently treating
them as active.

### 3. Share Matrix & Role Allocation
`team_share_allocator_v2.py` computes a **share matrix** (`data/model/share_matrix.csv`)
that maps: "when player X is out, how much of their stat production flows to player Y?"

This is built from historical game logs by comparing a player's stats in games where a
teammate was absent vs. present. The matrix columns are:
`team, out_player, beneficiary_player, stat, games, weight`.

At scoring time, `new_probability.py` loads this matrix and uses it to compute `role_ctx_mult`
— a clamped multiplier that adjusts a player's expected rate when a teammate is out. The
multiplier is clamped between 0.9 and 1.2 (`projection_clamp_lo/hi` in config) and the
variance is conservatively inflated via `variance_k`.

### 4. Probability Kernel (Monte Carlo)
`new_probability.py` → `simulate_leg_probability_new()`:

1. Loads the player's recent game log window.
2. Computes per-minute rate mean and standard deviation.
3. Applies role context adjustment (if injuries are present).
4. Runs a Monte Carlo simulation of minutes × rate to estimate `p` (probability of hitting the line).
5. Adjusts for blowout risk → produces `p_adj`.
6. Applies under-relief (optional restoration of haircut for qualifying UNDER legs).

The probability chain for each leg:
```
p (raw MC) → p_role (role-adjusted) → p_adj (blowout-adjusted) → p_for_cal → p_cal (calibrated)
```

### 5. Post-hoc Calibration (v9d Ensemble)
`calibration.py` + `calibration_map.py`:

The 7-seed LightGBM ensemble takes `p_adj` plus 33 features and produces a calibrated
probability. The ensemble averages predictions across all 7 seeds with temperature scaling
(T=0.98). This is the primary probability used for slip building.

### 6. Telemetry Calibration (Isotonic)
A secondary isotonic calibration layer trained on replay corpus outcomes. Currently using
`isotonic_hybrid_protect_role_ctx_on` as the active calibration. Applied after the GBM
ensemble. Controlled by `telemetry.active_calibration` in `config.yaml`.

### 7. Blowout / Fragility Logic
Game spread drives `q_blowout` — the probability of a blowout scenario. The blowout layer:
- Reduces OVER probabilities when blowout risk is high (stars lose minutes).
- Can boost UNDER probabilities in the same scenario.
- Uses structural adjustment rules by stat family (e.g., combo scoring overs get different
  treatment than assists or rebounds).

Key config: `blowout.spread_sd`, `blowout.threshold_margin`, `blowout.adjustment_rules`.

### 8. Slip Building
Three slip families are built from the scored legs:

| Family | Description | Sort Basis |
|---|---|---|
| **System** | Main output — beam-search optimized slips | `score_adj` (edge × probability) |
| **Windfall** | Hybrid probability + edge | `score_adj` variant |
| **DemonHunter** | All-DEMON tier legs only, highest-multiplier | DEMON-only filter |

Each family produces 3-leg, 4-leg, and 5-leg slips. The slip builder uses:
- Beam search with configurable width (250 default, 400 for 4-leg, 500 for 5-leg).
- Diversity penalties for same-team, same-stat-family, and fragility concentration.
- Per-player caps (`max_slips_per_player: 5`).
- A `winprob` sort mode variant that ranks by pure hit probability.

### 9. Publishing
`publish_run_outputs.py` writes all artifacts to `data/output/runs/<timestamp>/` and
copies latest surfaces to `data/output/latest/`. A bundle zip is optionally created
in `data/bundles/`.

---

## Output CSV Reference

### `scored_legs_deduped.csv` — The Master Diagnostic File

This is the single most important file for understanding a run. Every leg the model scored
appears here with the full probability chain and all diagnostic columns.

**Column Groups:**

#### Identity & Market
`projection_id`, `player_key`, `player`, `team`, `home`, `opp`, `stat`, `line`,
`direction`, `tier`, `odds_type`, `game_id`, `game_date`, `start_time`

#### Probability Chain
| Column | Meaning |
|---|---|
| `p` | Raw Monte Carlo probability (no role adjustment) |
| `p_role` | After role context adjustment for injuries |
| `p_adj` | After blowout/fragility adjustment |
| `p_adj_pre_under_relief` | p_adj before under-relief restoration |
| `p_for_cal` | Probability sent to the GBM calibrator |
| `p_cal` | Final calibrated probability |
| `p_close` / `p_close_raw` | Close-line probability variants |

#### Role Context Diagnostics
`role_ctx_mult`, `role_ctx_mult_raw`, `role_ctx_sigma_mult`, `role_ctx_reason`,
`role_ctx_outs_used`, `role_ctx_components`, `role_ctx_component_mults`

#### Blowout & Fragility
`q_blowout`, `fragility`, `fragility_abs`, `usage_dep`, `usage_pressure_mult`,
`minutes_s`, `is_star`

#### Calibration & Telemetry
`p_cal_src`, `telemetry_cal_key`, `telemetry_k_shrink`, `telemetry_under_penalty`,
`telemetry_mult`, `telemetry_cal_applied`

#### External Priors
`external_prior_score`, `external_prior_n`, `external_prior_sources`

### `eval_legs.csv` — Truth-Backed Evaluation

Produced during replay evaluation. Contains the scored legs **plus** the actual outcome
(`actual_stat`, `hit`) so Brier scores can be computed. This is the file used for all
backtest and reader evaluations.

### Slip CSVs

| File | Contents |
|---|---|
| `System/system_3.csv` ... `system_5.csv` | System family slips (3/4/5-leg) |
| `Windfall/windfall_3.csv` ... `windfall_5.csv` | Windfall family slips |
| `demonhunter.csv` | Best all-DEMON slips at each leg count |
| `*_winprob.csv` variants | Same families sorted by pure hit probability |

---

## How To Debug A Bad Row

When a leg looks wrong, inspect in this order:

1. **Start with `p`** — is the raw Monte Carlo probability reasonable given the player's
   recent stats and the line?
2. **Compare `p_role` vs `p`** — did the role context move it? Check `role_ctx_reason`
   and `role_ctx_outs_used` to see which absences drove the adjustment.
3. **Check `q_blowout` and `fragility`** — did the blowout layer move the probability
   too aggressively?
4. **Compare `p_adj_pre_under_relief` vs `p_adj`** — did under-relief restore too much
   or too little?
5. **Check `p_cal`** — did the GBM calibrator push the probability in the wrong direction?
   Compare `p_for_cal` (input) vs `p_cal` (output).
6. **Check telemetry columns** — did the isotonic overlay apply and was it appropriate?

The problem almost always maps to one of:
- Base kernel (wrong rate/minutes estimate)
- Role allocator (wrong redistribution)
- Blowout layer (over/under-correction)
- Calibrator (GBM or isotonic distortion)

---

## Key Config Knobs (`config.yaml`)

| Section | Key Settings | What They Control |
|---|---|---|
| `pp_kernel` | `coeffs` per stat/tier | PrizePicks pricing model coefficients |
| `role_ctx` | `projection_clamp_lo/hi`, `variance_k`, `close_sens_mult` | Role context adjustment bounds |
| `role_ctx` | `under_relief_q_min/haircut_min/factor` | Under-relief gate and strength |
| `posthoc_calibrator` | `enabled`, `coefficients_path`, `ensemble_dir` | GBM ensemble calibrator |
| `telemetry` | `active_calibration`, `apply_active_calibration` | Isotonic calibration overlay |
| `blowout` | `spread_sd`, `threshold_margin`, `adjustment_rules` | Blowout sensitivity |
| `slip_build` | `beam_width`, `max_slips_per_player`, `penalty.*` | Slip builder behavior |
| `optimizer` | `top_n_slips`, `external_priors.*` | Final slip selection and priors |

---

## Design Philosophy

1. **Math over guesswork** — every adjustment should be traceable through the probability chain.
2. **Basketball grounding** — role allocation mirrors how NBA rotations actually behave when
   players are absent.
3. **Layer consistency** — the kernel, allocator, calibrator, and telemetry overlay should
   reinforce the same answer, not introduce contradictory assumptions.
4. **Replay reproducibility** — any live run can be replayed from pinned artifacts to verify
   that the model produces the same outputs.
5. **Narrow changes** — prefer config-only adjustments and bounded fixes over broad
   refactors. Get explicit approval before changing core model behavior.

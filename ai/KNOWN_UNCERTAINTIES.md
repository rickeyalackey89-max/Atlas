# Atlas Known Uncertainties

> **Last updated:** 2026-05-12
> **Purpose:** Honest catalog of the model's known blind spots, structural limitations, and unresolved questions. Read this before making any model or config change.

---

## 1 — UNDER Direction Has Near-Zero Discrimination

**Status:** Known structural limit, partially mitigated.

UNDER legs have an AUC of ~0.52 — close to a coin flip. The model predicts UNDER probabilities but has almost no ability to distinguish which UNDERs will actually hit.

- Root cause: UNDER hits are dominated by game-script randomness (blowouts, pace) rather than player skill, making them inherently harder to model.
- The May 10 runtime partially compensates via the UNDER logit shift, CatBoost v5cD features such as `margin_x_under` and `q_x_under`, and downstream replay validation.
- **Practical implication:** UNDER legs remain structurally noisy. The old UNDER probability window is currently disabled because v5cD is treated as the active calibrated surface; monitor direction-split Brier before reintroducing caps.

---

## 2 — Playoff Calibration Drift

**Status:** Known, currently managed via CatBoost playoff v5cD plus May 10 kernel transforms.

The model was trained almost entirely on regular-season data (Feb–Apr). In the playoffs:

- Slate sizes shrink dramatically (2–4 games vs 8–12 in regular season).
- Player roles shift — bench depth compresses, star usage increases.
- Historical per-minute rates are less predictive because matchup scripting dominates.

The `playoff_isotonic` calibration JSON remains available, but it is currently disabled (`telemetry.apply_active_calibration: false`). The active correction is CatBoost v5cD, trained on playoff dates 2026-04-30 through 2026-05-09. However:

- It was fit on only 10 playoff dates.
- It should be **retrained or revalidated after 5–10 additional playoff dates** as the sample grows.
- `player_dir_te` (player × stat × direction target encoding) is stale in playoffs — trained on regular-season hit rates.

---

## 3 — Share Matrix Coverage Gaps

**Status:** Structural, acceptable with monitoring.

The share matrix is built from gamelogs: "when player X is out, how does player Y's production change?" This requires:

- Sufficient games with the out player absent (typically ≥5 games).
- A stable team context (no mid-season trades mid-window).

Gaps:

- **Newly acquired players** have no share matrix entries until enough games accumulate.
- **Small-sample teams** (e.g. teams that rarely had key players out) have weak weights.
- **Back-to-back rest situations** are not explicitly distinguished in the share matrix from injury outs.

When no share matrix match is found: `role_ctx_outs_used = 0`, role context stays off, and the model uses the unadjusted base rate. This is conservative but may understate production boosts for clear depth-player beneficiaries.

---

## 4 — Late Injury State Has Two Different Risks

**Status:** Policy defined, still operationally fragile near tip.

Atlas now separates late injury handling into:

- **Direct-player risk:** the prop player's own availability is uncertain.
- **Beneficiary uncertainty:** a teammate's availability may change the prop player's role.

Current policy:

- Direct `OUT`/`DOUBTFUL` players are removed by IAEL hard filter.
- Direct `QUESTIONABLE` players are excluded from premium slips by default.
- Questionable-teammate beneficiary exposure is tagged with `is_questionable` / `q_out_frac`; on normal slates it is excluded, but on single-game slates it may remain as penalized soft exposure if `role_ctx_outs` is present.

Remaining uncertainty:

- A player can be ruled in/out minutes before tip. The model cannot correct a stale run unless IAEL is refreshed and Atlas is rerun.
- Beneficiary boosts from a questionable teammate are conditional. If the teammate plays, the boost may be wrong.
- Single-game slates intentionally accept some beneficiary uncertainty to avoid wiping the entire output pool.

Canonical policy: `docs/LATE_INJURY_HANDLING.md`.

---

## 5 — External Priors Are Direction-Gated but Not Always Aligned

**Status:** Known, managed via `cap` and `scale` config.

BettingPros and OddsAPI projections are single-value (a point projection, not a probability). Atlas translates them to a nudge via:

$$\Delta p = \text{clip}\!\left(\tanh\!\left(\frac{\mu - \text{line}}{\text{scale}}\right) \times \text{cap},\ -\text{cap},\ +\text{cap}\right)$$

Uncertainties:

- The external projection may itself be calibrated against a different market (DraftKings, FanDuel) rather than PrizePicks lines.
- Direction gating prevents applying a prior that conflicts with the leg direction, but a projection exactly at the line contributes a zero nudge — not always the right signal.
- Sources can disagree significantly. When multiple sources fire, they are blended by source weights. If a high-confidence source is wrong on a given date, the error amplifies.

---

## 6 — Gamelog Window Is Fixed, Not Dynamic

**Status:** Known design choice with known failure modes.

The gamelog window is a rolling fixed window (configurable, default ~20 games). This means:

- **Early-season data bleeds through** if the window extends back to October. The thin-window multiplier applies shrinkage but does not cleanly separate contexts.
- **Trades are not detected automatically.** A player traded mid-season carries their old-team stats in the window. The share matrix and role context still reference the old team.
- **Recent-form divergence** (a player hot or cold in the last 5 games) is partially captured by `l20_edge` and `recent_form_blend` but the full gamelog window can dilute it.

---

## 7 — Blowout Curve Is a Single-Parameter Family

**Status:** Known simplification.

The blowout adjustment uses a two-tailed Normal model:

$$q = 2 \cdot \Phi\!\left(-\frac{|\text{spread}|}{\sigma}\right)$$

Real game-script risk is not symmetric and not Gaussian:

- Home teams blow out less often at equivalent spread values.
- Playoff games have structurally lower blowout rates (better coaching, deeper rosters).
- The curve crossover (14 minutes) is hardcoded — it does not adapt to position or team.

The `blowout.spread_sd` parameter (currently 11.0) controls the sensitivity. The May 10 runtime also uses `kernel_blowout_bypass` to keep blowout adjustment only in the validated middle band (`0.15 <= q_blowout < 0.50`).

---

## 8 — Thin Window Shrinkage Is Coarse

**Status:** Known, low priority.

When a player has fewer than `thin_window_games` games in the window (default 15), a shrinkage multiplier pulls their rate toward a league prior. The prior is a global average, not position-stratified or role-stratified.

Consequence: A star player returning from injury with 5 games logged gets shrunk toward the same prior as a bench player with 5 games. This underestimates the star's true production level.

---

## 9 — Role Metrics Are a Weak Prior, Not a Strong Signal

**Status:** By design, but worth stating explicitly.

The CraftedNBA/DARKO role metrics (CPM, VORP, DRIP, usage projection, etc.) are applied as a bounded prior with very tight clamps (`role_ctx_rate_clamp_lo=0.94`, `role_ctx_rate_clamp_hi=1.08`). The multiplier is capped at ±1.6pp.

This is intentional: role metrics are noisy and the model should not over-rely on them. But it means:

- A player with an unusually high usage projection that day (e.g. a coach just announced they'll play 38 minutes) will only shift probability by ~1pp.
- The role metrics snapshot is taken at run time — if the snapshot is stale (>2 hours old), it may not reflect the latest lineup news.

---

## 10 — Combo Stats Are Structurally Overconfident

**Status:** Partially corrected by combo logit shrink and CatBoost v5cD, not fully resolved.

Combo stats (PRA, PR, PA, RA) have correlated components (points, rebounds, assists). The Monte Carlo simulation treats them as independently drawn from per-minute rates, which understates variance when a player has a bad shooting night that simultaneously kills all three components.

Empirically, combo legs are structurally overconfident because the covariance among points/rebounds/assists is not fully modeled. Current runtime applies `kernel_logit_shrinks` with `k=0.90` for `RA/PA/PRA/PR`; the root cause is still not modeled directly.

---

## 11 — `p_cal_marketed` Is Not a Probability Estimate

**Status:** Design note.

`p_cal_marketed` is a deterministic scaling of `p_cal` by stat × tier multipliers from `marketed_slip_builder.py` / `data/model/marketed_calibration.json`. It is used for slip selection within the marketed builder, not as a calibrated probability estimate.

- It should not be used as a ground truth label or a training signal.
- It will be NaN for all legs not processed by the marketed builder.
- The multipliers were set based on cache analysis and are not continuously re-estimated.

---

## 12 — Current CatBoost Replay Is Not True Out-of-Sample

**Status:** Methodological note.

The historical LODO Brier (0.201529 for v18) is an in-corpus estimate. The current CatBoost v5cD full-corpus model was trained on all 10 playoff dates available through 2026-05-09, and its in-sample Brier is not an out-of-sample guarantee.

True out-of-sample performance on future slates may differ, particularly:

- After rule changes that shift how lines are set.
- During playoffs when team composition changes dramatically.
- For stat families with very small samples in the corpus (e.g. FTA).

---

## 13 — Slip Win Rates Are Sensitive to Sample Size

**Status:** Statistical caution.

The historical marketed slip baseline (43 slates) and the current v5cD slip eval (10 slates) are both small samples. The current v5cD marketed 3-leg result is 70% over 10 trials; that is encouraging but very wide-confidence.

Do not over-optimize slip builder parameters on this sample — trainer sweeps need at least 30 dates to avoid overfitting, and the current corpus of 43 playoff-era slates is particularly noisy.

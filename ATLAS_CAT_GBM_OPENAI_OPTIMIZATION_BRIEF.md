# Atlas CatBoost / GBM / OpenAI Optimization Brief for Codex

**Date:** 2026-05-12
**Audience:** Codex working inside the Atlas repo
**Primary file under review:** `tools/catboost_playoff_v5cD_full_corpus.py`
**Context:** Atlas slips have degraded after the CatBoost LOSO / playoff residual retool, even though Brier improved across the board. The current cached playoff corpus is small: 10 playoff dates, with the option to expand to 12 by adding the last two days of runs. Some gate dates were intentionally omitted during testing. The old season GBM was reportedly much stronger, but some prior data was lost during migration to a new machine. There is a possible path to rebuild season data through ODDSAPI and compare or blend GBM against CatBoost.

---

## 1. Executive Summary

The current CatBoost trainer appears useful as a **final full-corpus model writer**, but it should not be the only promotion decision-maker.

The failure mode we need to investigate is:

```text
Full-board Brier improves
→ CatBoost looks better on aggregate calibration
→ Builder trusts p_cal more heavily
→ selected-tail ranking changes
→ slips get worse
```

This is not contradictory. Brier evaluates full-board probability quality. Slips depend on a tiny, high-confidence, high-EV selected subset. A model can improve global calibration while degrading top-tail ranking, direction mix, role-context selection, or same-game correlation exposure.

**Core recommendation:**

```text
Keep CatBoost as a calibration / residual signal.
Do not let the small playoff CatBoost model fully control slip selection.
Add validation gates, selected-tail metrics, and ideally a separate p_select surface.
```

---

## 2. Current Trainer Observations

From `tools/catboost_playoff_v5cD_full_corpus.py`:

```python
"""Train final v5cD full-corpus CatBoost residual regressor.

Trains a SINGLE model on all 10 playoff dates (no holdout) using the v5cD
config: 19 features, iter=600, depth=5, lr=0.075. Saves the model file used
by runtime inference.
"""
```

The trainer currently:

```text
1. Loads `_v1_playoff_resim_cache.pkl`.
2. Reads canonical v5b/v5cD features from `catboost_playoff_v5b_lodo.json`.
3. Builds `p_for_cal` from `p_adj`.
4. Builds target as `hit - p_for_cal`.
5. Trains one full-corpus CatBoostRegressor.
6. Applies residual as:
   p_after = clip(p_for_cal + RESIDUAL_SCALE * clip(residual, -RESIDUAL_CLIP, RESIDUAL_CLIP), P_LO, P_HI)
7. Saves `.cbm` and `.meta.json`.
```

Important constants:

```python
RESIDUAL_CLIP  = 0.20
RESIDUAL_SCALE = 0.50
P_LO, P_HI     = 0.03, 0.97

PARAMS = dict(
    iterations=600,
    depth=5,
    learning_rate=0.075,
    l2_leaf_reg=6.0,
    min_data_in_leaf=50,
    loss_function="RMSE",
    eval_metric="RMSE",
    random_seed=42,
    verbose=100,
)
```

Current limitations:

```text
- No holdout in this full-corpus script.
- In-sample Brier is printed, but that is only a fit check.
- No selected-slip metrics.
- No top-tail metrics.
- No last-two-day gate.
- No promotion blocker.
- No feature health / missingness contract beyond fillna.
- No scale/clip sweep.
- No conservative param sweep.
- No explicit comparison against previous champion config.
```

The script correctly says LODO is the real generalization metric, but it does not enforce LODO or any slip-tail gates before saving the runtime model.

---

## 3. The Main Diagnosis

The current trainer optimizes:

```text
full-board residual calibration
```

Atlas needs to optimize:

```text
selected-slip performance under real builder constraints
```

These differ because the builder selects a narrow tail:

```text
highest p_cal / highest p_eff
+ tier templates
+ direction filters
+ raw thresholds
+ team constraints
+ correlation penalties
+ stat exclusions
+ role-context behavior
```

If CatBoost improves calibration on low- and mid-confidence legs, Brier can improve even while the selected top-tail becomes worse.

Likely failure modes to test:

```text
1. Positive CatBoost residuals are over-boosting bad legs into the selected pool.
2. High-p_cal UNDERs are not actually hitting.
3. STANDARD legs got worse because selection moved from player_dir_te / historical signal to p_cal.
4. DEMON / GOBLIN raw floors are too low for the new p_cal distribution.
5. Same-team / same-game exposure is too weak in by_legs overrides.
6. Last two days represent a regime/gate failure that was hidden by omitted gate dates.
7. Small 10-date corpus is too small for the Cat model to own production selection.
```

---

## 4. Immediate Diagnostic Plan for Codex

Please run or implement a validation script that compares at least these configurations:

```text
A. Current CatBoost replace config
B. CatBoost blend_alpha = 0.35
C. CatBoost disabled or p_for_cal selection baseline
D. CatBoost blend + UNDER window + stricter quality filters
E. Season GBM if rebuild is ready
F. GBM + CatBoost blend if both are available
```

Use the last two bad dates as a **gate holdout**, not as training data at first.

Recommended first split:

```text
Train: original 10 playoff dates, or clean-10 minus intentionally omitted gates
Validate / gate: last 2 bad dates
Then, only after diagnostics: train final on all 12 if gates pass
```

Because the last two days were bad, they are highly valuable as a failure detector. Do not immediately absorb them into the full-corpus model and hide the failure.

---

## 5. Metrics That Must Be Added

Current Brier is not enough.

Add a report with:

```text
Full-board metrics:
- Brier
- log-loss
- AUC
- calibration by p bucket
- direction-split Brier
- tier-split Brier
- stat-split Brier
- date-level Brier

Selected-tail metrics:
- top_25_by_p_cal hit rate
- top_50_by_p_cal hit rate
- top_100_by_p_cal hit rate
- top decile p_cal hit rate
- selected System 3-leg hit rate
- selected System 4-leg hit rate
- selected System 5-leg hit rate
- marketed selected leg hit rate
- marketed slip win rate
- DemonHunter hit rate / slip win rate

Slice metrics:
- UNDER selected hit rate
- OVER selected hit rate
- GOBLIN selected hit rate
- STANDARD selected hit rate
- DEMON selected hit rate
- stat x direction selected hit rate
- role_ctx selected hit rate
- zero_dnp selected hit rate
- q_blowout bucket selected hit rate
- p_catboost_residual bucket hit rate
- same-team slip exposure
- same-game slip exposure
- same-stat slip exposure
```

The most important failure table:

```text
selected misses grouped by:
- date
- direction
- tier
- stat
- p_catboost_residual bucket
- p_for_cal bucket
- p_cal bucket
- role_ctx_reason
- q_blowout bucket
- team/game
```

If misses cluster around positive residuals, reduce residual scale/clip or add a residual cap for selected-tail rows.

If misses cluster around high-p UNDERs, re-enable the UNDER window.

If misses cluster around STANDARD legs, restore player_dir_te / historical selection contribution.

If misses cluster by team/game, increase correlation defense.

---

## 6. Promotion Gates

Do not promote a model merely because aggregate Brier improves.

Suggested promotion blockers:

```text
Block promotion if any of the following are true:

1. Any gate date regresses by > 1.5 mB Brier.
2. Last-two-day selected leg hit rate drops by > 3–5pp vs champion.
3. Last-two-day marketed slip win rate drops by > 5pp vs champion.
4. Top_50_by_p_cal hit rate drops below champion by > 3pp.
5. UNDER selected hit rate falls below 45%, unless sample is too small.
6. High-p UNDER bucket, especially p_cal > 0.70, underperforms materially.
7. Positive residual bucket, e.g. residual > +0.08, underperforms baseline.
8. Same-team exposure increases while slip win rate decreases.
9. Model improves in-sample but fails LODO / holdout / walk-forward.
10. The model passes full-board Brier but fails selected-tail metrics.
```

A challenger should be allowed to promote only if:

```text
aggregate quality improves
AND date-level regressions are controlled
AND selected-tail performance does not collapse
AND slip-level performance is stable or better
AND failure slices are acceptable
```

---

## 7. Trainer Improvements to Implement

### 7.1 Add CLI Modes

Suggested interface:

```bash
python tools/catboost_playoff_v5cD_full_corpus.py --mode validate --holdout-last 2
python tools/catboost_playoff_v5cD_full_corpus.py --mode lodo
python tools/catboost_playoff_v5cD_full_corpus.py --mode sweep
python tools/catboost_playoff_v5cD_full_corpus.py --mode train-final --allow-promote
```

Where:

```text
validate     = train on selected dates, evaluate on holdout/gate dates
lodo         = leave-one-date-out validation
sweep        = residual scale/clip + CatBoost param grid
train-final  = full-corpus writer only after external validation passes
```

### 7.2 Make Gate Dates Explicit

Add config or CLI support:

```bash
--include-dates 2026-05-01,2026-05-02,...
--exclude-dates 2026-05-04,2026-05-06
--gate-dates 2026-05-10,2026-05-11
--holdout-last 2
```

Save these into meta:

```json
{
  "train_dates": [],
  "gate_dates": [],
  "excluded_dates": [],
  "omitted_gate_dates_reason": "testing",
  "validation_policy": "train clean dates, gate last 2"
}
```

### 7.3 Tune Residual Scale and Clip

Current values:

```python
RESIDUAL_SCALE = 0.50
RESIDUAL_CLIP = 0.20
```

These are likely too strong for a small 10–12 date corpus if the selected tail is collapsing.

Suggested grid:

```python
SCALE_GRID = [0.15, 0.25, 0.35, 0.50, 0.65]
CLIP_GRID  = [0.05, 0.08, 0.10, 0.15, 0.20]
```

Expected safer range:

```text
residual_scale: 0.25–0.35
residual_clip:  0.08–0.12
```

Do not optimize these only by aggregate Brier. Select by a blended objective:

```text
objective =
  Brier improvement
  + selected-tail hit stability
  + last-two-day holdout stability
  + no major slice collapse
```

### 7.4 Conservative CatBoost Param Sweep

Current params:

```python
iterations=600
learning_rate=0.075
depth=5
l2_leaf_reg=6.0
min_data_in_leaf=50
```

Try more conservative options:

```python
PARAM_GRID = [
    {"iterations": 250, "depth": 3, "learning_rate": 0.04,  "l2_leaf_reg": 12, "min_data_in_leaf": 100},
    {"iterations": 350, "depth": 3, "learning_rate": 0.035, "l2_leaf_reg": 18, "min_data_in_leaf": 150},
    {"iterations": 400, "depth": 4, "learning_rate": 0.03,  "l2_leaf_reg": 20, "min_data_in_leaf": 100},
    {"iterations": 500, "depth": 4, "learning_rate": 0.025, "l2_leaf_reg": 25, "min_data_in_leaf": 150},
]
```

For a 10–12 date playoff corpus, conservative may beat aggressive if it protects selected-tail stability.

### 7.5 Feature Health / Missingness Contract

Current `prep_X()` fills numeric missing values with `0.0` and categorical missing values with `0`. That can hide broken features.

Improve `prep_X()`:

```text
1. Assert all required features exist.
2. Report missing rate per feature.
3. Fail if critical feature missingness exceeds threshold, e.g. 5%.
4. Use median imputation for numeric features instead of universal zero.
5. Save imputation values and missing rates in meta.
6. Save a feature contract hash.
```

Suggested meta additions:

```json
{
  "feature_missing_rates": {},
  "numeric_imputation_values": {},
  "cat_imputation_values": {},
  "feature_contract_hash": "...",
  "cache_hash": "...",
  "config_hash": "..."
}
```

### 7.6 Save OOF / Holdout Predictions

Write files like:

```text
data/model/catboost_playoff/catboost_v5cD_oof_predictions.csv
data/model/catboost_playoff/catboost_v5cD_holdout_predictions.csv
data/model/catboost_playoff/catboost_v5cD_validation_report.json
data/model/catboost_playoff/catboost_v5cD_selected_tail_report.json
```

Each prediction CSV should contain:

```text
game_date
player
team
opp
stat
direction
tier
line
hit
p_for_cal
p_catboost_residual
p_catboost_oof_or_holdout
p_after
selected_by_current_builder
selected_by_candidate_builder
role_ctx_reason
role_ctx_outs_used
q_blowout
l20_edge
player_dir_te
```

This allows direct inspection of which legs CatBoost is pushing into slips.

---

## 8. Immediate Safe-Mode Config Experiments

These should be tested, not blindly promoted.

### 8.1 CatBoost Blend Instead of Replace

```yaml
catboost_playoff_calibrator:
  enabled: true
  kind: regressor
  model_path: data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm
  meta_path: data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json
  mode: blend
  blend_alpha: 0.35
```

Rationale:

```text
Keep CatBoost signal, but stop it from fully controlling p_cal.
```

### 8.2 Re-enable UNDER Window

```yaml
slip_build:
  min_under_prob: 0.60
  max_under_prob: 0.70

marketed_slips:
  min_under_prob: 0.60
  max_under_prob: 0.70
```

Rationale:

```text
If high-p UNDERs are driving misses, prevent CatBoost from allowing UNDER@0.80+ into slips.
```

### 8.3 Tighten Leg Quality Filters

```yaml
slip_build:
  leg_quality_filters:
    min_standard_player_dir_te: 0.04
    min_goblin_l20_edge: 0.08
```

Rationale:

```text
Require historical player/stat/direction signal and recent-form confirmation.
```

### 8.4 Raise Marketed Raw Floors

```yaml
marketed_slips:
  min_raw_thresholds:
    GOBLIN: 0.70
    STANDARD: 0.62
    DEMON: 0.56
```

Rationale:

```text
DEMON at 0.50 is risky if p_cal ranking is unstable.
```

### 8.5 Increase by_legs Team/Family/Frag Penalties

```yaml
slip_build:
  by_legs:
    '3':
      penalty:
        team_w: 0.10
        family_w: 0.05
        frag_w: 0.05
    '4':
      penalty:
        team_w: 0.10
        family_w: 0.05
        frag_w: 0.05
    '5':
      penalty:
        team_w: 0.12
        family_w: 0.08
        frag_w: 0.08
```

Rationale:

```text
Avoid correlated slate collapse while diagnosing the new model.
```

---

## 9. Separate p_cal from p_select

This is probably the most important architecture improvement.

Current risk:

```text
p_cal = reporting probability
p_cal = calibration metric target
p_cal = builder selection score
```

Better:

```text
p_cal    = calibrated probability for reporting / Brier / diagnostics
p_select = conservative ranking score for slip selection
p_slip   = final joint slip probability after correlation / tier / template rules
```

Possible `p_select` design:

```python
p_select = (
    0.45 * p_cal
  + 0.20 * p_for_cal
  + 0.15 * p_gbm_season
  + 0.10 * recent_form_score
  + 0.10 * player_dir_score
  - under_tail_penalty
  - correlation_penalty
  - fragile_blowout_penalty
)
```

If season GBM is not available yet:

```python
p_select = (
    0.55 * p_cal
  + 0.20 * p_for_cal
  + 0.15 * recent_form_score
  + 0.10 * player_dir_score
  - under_tail_penalty
)
```

The builder should use `p_select` for ranking, while `p_cal` remains the calibrated probability for logs, reporting, and probability calculations.

---

## 10. Rebuilding the Season GBM Through ODDSAPI

Rebuilding the season GBM is strongly worth testing.

Reason:

```text
The old GBM likely had more volume, more market context, more player/stat examples,
more injury regimes, and broader slate diversity than the 10–12 date playoff CatBoost corpus.
```

Recommended model stack:

```text
season GBM       = broad, high-volume prior
playoff CatBoost = small-data playoff residual adapter
kernel / MC      = simulation and role-context engine
p_select         = conservative builder-facing ranking surface
```

Do not frame this as:

```text
GBM OR CatBoost
```

Prefer:

```text
GBM + CatBoost, with gates
```

Example calibration blend to test:

```python
p_cal_candidate = (
    0.55 * p_gbm_season
  + 0.25 * p_for_cal
  + 0.20 * p_cat_playoff
)
```

Alternative if CatBoost is useful but too aggressive:

```python
p_cal_candidate = (
    0.70 * p_gbm_season
  + 0.15 * p_for_cal
  + 0.15 * p_cat_playoff
)
```

ODDSAPI rebuild cautions:

```text
1. Keep timestamp discipline.
2. Train only on data that would have existed before the run if using it for live prediction.
3. Closing lines can be used for diagnostics, but not as live features unless available pre-run.
4. Store market source, timestamp, and line movement separately.
5. Avoid training leakage from settled outcomes or post-game line data.
```

Useful GBM features from ODDSAPI / market context:

```text
- market consensus probability
- line movement since open
- market disagreement between books
- PrizePicks vs market line delta
- no-vig implied edge
- book count / market availability
- late movement flag
- odds stability / volatility
- market confidence score
```

---

## 11. How OpenAI Could Help the Cat Trainer

OpenAI can help, but it should not be the numeric judge.

Correct role:

```text
OpenAI = experiment designer / failure analyst / candidate generator
Python = evaluator / replay runner / promotion gate
```

Incorrect role:

```text
OpenAI predicts which slips hit
OpenAI overrides eval metrics
OpenAI promotes models without replay evidence
```

### 11.1 Best OpenAI Loop

```text
1. Python runs current evals and creates `validation_summary.json`.
2. OpenAI reads compact summaries, not the full corpus.
3. OpenAI proposes 10–25 candidate configs in strict JSON.
4. Python validates every candidate using replay / OOF / holdout.
5. Promotion gate decides champion vs challenger.
```

### 11.2 Candidate Generator Schema

Use Structured Outputs so candidate configs are machine-readable.

Example schema:

```json
{
  "type": "object",
  "properties": {
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "candidate_id": {"type": "string"},
          "hypothesis": {"type": "string"},
          "trainer_patch": {"type": "object"},
          "config_patch": {"type": "object"},
          "expected_effect": {"type": "string"},
          "risk": {"type": "string"},
          "required_gates": {
            "type": "array",
            "items": {"type": "string"}
          },
          "priority": {"type": "integer"}
        },
        "required": [
          "candidate_id",
          "hypothesis",
          "trainer_patch",
          "config_patch",
          "expected_effect",
          "risk",
          "required_gates",
          "priority"
        ]
      }
    }
  },
  "required": ["candidates"]
}
```

### 11.3 Example Summary to Send to OpenAI

```json
{
  "corpus": {
    "dates": 12,
    "train_dates": 10,
    "gate_dates": 2,
    "notes": "Some gate dates were omitted during earlier testing."
  },
  "champion": {
    "name": "pre_cat_or_old_gbm",
    "brier": 0.214,
    "selected_hit_rate": 0.50,
    "marketed_slip_win_rate": 0.395
  },
  "challenger": {
    "name": "catboost_v5cD_replace",
    "brier": 0.207,
    "selected_hit_rate": 0.38,
    "marketed_slip_win_rate": 0.25
  },
  "failure_slices": [
    {
      "slice": "UNDER p_cal > 0.70",
      "hit_rate": 0.34,
      "n": 47
    },
    {
      "slice": "positive_cat_residual > 0.08",
      "hit_rate": 0.36,
      "n": 62
    }
  ]
}
```

### 11.4 Expected OpenAI Output

```json
{
  "candidates": [
    {
      "candidate_id": "cat_scale_clip_safe_001",
      "hypothesis": "Cat residual is over-boosting selected-tail legs.",
      "trainer_patch": {
        "residual_scale": 0.25,
        "residual_clip": 0.10,
        "depth": 3,
        "l2_leaf_reg": 18,
        "min_data_in_leaf": 150
      },
      "config_patch": {
        "catboost_playoff_calibrator": {
          "mode": "blend",
          "blend_alpha": 0.35
        }
      },
      "expected_effect": "Reduce top-tail overcorrection while preserving some Brier improvement.",
      "risk": "Aggregate Brier improvement may shrink.",
      "required_gates": [
        "last_2_selected_hit_rate >= champion - 0.03",
        "no gate date Brier regression > 1.5 mB",
        "positive residual bucket hit rate does not collapse"
      ],
      "priority": 1
    }
  ]
}
```

### 11.5 OpenAI Files to Add

Suggested files:

```text
tools/openai_optimizer/
  summarize_cat_failures.py
  propose_cat_candidates_openai.py
  candidate_schema.py
  run_candidate_batch.py
  parse_candidate_results.py

reports/catboost/
  validation_summary.json
  openai_candidate_configs.json
  candidate_results.json
  promotion_decision.json
```

### 11.6 OpenAI Should Save Time by Reducing the Search Space

OpenAI should not run tests. It should reduce blind sweeps.

Instead of:

```text
500 brute-force configs
```

Use:

```text
20 hypothesis-driven configs
→ proxy eval
→ top 5 full eval
→ top 1 champion/challenger gate
```

---

## 12. Global Optimizer / Meta-Trainer Direction

Long-term, Atlas should move from isolated trainers to a meta-trainer.

Current pattern:

```text
trainer → config.yaml
```

Better pattern:

```text
trainer → candidate_config.json → global replay → champion registry → config.yaml
```

Suggested files:

```text
tools/meta_optimizer/
  summarize_eval_corpus.py
  generate_candidate_configs.py
  proxy_eval_candidates.py
  full_replay_topk.py
  promotion_gate.py
  champion_registry.py

configs/champions/
  champion.json
  challengers/
  reports/
```

The meta-trainer should coordinate:

```text
- CatBoost trainer
- season GBM trainer
- leg trainer EV
- leg trainer hit-rate
- marketed slip trainer
- DemonHunter trainer
- kernel trainer
- matrix trainer
- slip/leg builder configs
```

Promotion should be decided globally, not by each trainer in isolation.

---

## 13. Concrete Implementation Request for Codex

Please inspect the live repo and give an opinion on this proposed path. Ideally implement or sketch the following:

### Phase 1 — No-risk diagnostics

```text
1. Add a validation/report script for CatBoost v5cD.
2. Support explicit gate dates and holdout-last-N dates.
3. Generate selected-tail metrics and failure slices.
4. Save OOF/holdout prediction CSVs.
5. Compare current CatBoost replace vs blend vs disabled.
```

### Phase 2 — Safer trainer

```text
1. Add residual scale/clip sweep.
2. Add conservative CatBoost parameter sweep.
3. Add feature missingness report and fail-fast feature contract.
4. Add promotion gates.
5. Save validation report into model meta.
```

### Phase 3 — Builder protection

```text
1. Add p_select separate from p_cal.
2. Test p_select blends using p_cal, p_for_cal, l20_edge, player_dir_te, and GBM if available.
3. Restore UNDER protection if last-two-day data supports it.
4. Harden team/game/family correlation penalties.
```

### Phase 4 — Rebuild season GBM

```text
1. Rebuild data through ODDSAPI with timestamp discipline.
2. Train a season GBM as broad prior.
3. Compare GBM-only, Cat-only, and GBM+Cat blends.
4. Use playoff CatBoost as a residual adapter, not a standalone replacement, unless it passes gates.
```

### Phase 5 — Optional OpenAI optimization layer

```text
1. Create compact eval summaries.
2. Ask OpenAI for candidate configs via Structured Outputs.
3. Python tests candidates.
4. Promotion gate decides.
```

---

## 14. Questions for Codex

1. Are the intentionally omitted gate dates still excluded from the current v5cD validation path?
2. Which dates were omitted, and were those dates representative of the last-two-day failure mode?
3. Does current runtime use CatBoost in `replace` mode or `blend` mode?
4. Is the selected slip collapse mostly:
   - UNDERs?
   - STANDARDs?
   - DEMONs?
   - role-context legs?
   - same-team / same-game correlation?
   - positive Cat residual buckets?
5. Does CatBoost improve top-tail hit rate, or only aggregate Brier?
6. What happens if `RESIDUAL_SCALE` is cut to 0.25 or 0.35?
7. What happens if `RESIDUAL_CLIP` is cut to 0.08 or 0.10?
8. What happens if CatBoost runtime mode changes from `replace` to `blend_alpha=0.35`?
9. Does re-enabling UNDER window 0.60–0.70 fix most of the recent slip damage?
10. Does restoring `player_dir_te` / historical signal for STANDARD selection improve slips?
11. Does a rebuilt ODDSAPI season GBM beat CatBoost on the last-two-day gate?
12. Does a GBM+Cat blend outperform either model alone?
13. Can we add a `p_select` surface without breaking current output contracts?
14. What is the fastest low-risk patch to stabilize today’s slips?

---

## 15. Recommended Near-Term Decision Tree

```text
Step 1: Expand corpus to 12, but keep last 2 as gate holdout first.

Step 2: Evaluate current CatBoost replace on:
        - full board
        - selected tail
        - last 2 dates
        - slips

Step 3: If full-board Brier improves but selected-tail fails:
        - switch runtime to CatBoost blend
        - reduce residual scale/clip
        - add p_select
        - restore UNDER guard

Step 4: If CatBoost fails last-two-day gate:
        - do not train final on all 12 yet
        - treat failure as a promotion blocker

Step 5: Rebuild season GBM through ODDSAPI.

Step 6: Compare:
        - p_for_cal baseline
        - GBM season
        - Cat playoff
        - GBM + Cat blend
        - p_select builder surface

Step 7: Promote only through champion/challenger gates.
```

---

## 16. Bottom Line

The CatBoost trainer should not be discarded yet. The likely issue is that a small playoff residual model is being allowed to dominate runtime selection.

Best path:

```text
1. Use CatBoost as a residual signal, not the whole decision engine.
2. Rebuild the season GBM as the broad-data prior.
3. Add last-two-day/gate-date holdout validation.
4. Add selected-tail and slip-level metrics.
5. Separate p_cal from p_select.
6. Use OpenAI only to propose candidate experiments and reduce brute-force search.
7. Let Python evals and promotion gates decide the winner.
```

The main rule:

```text
Do not promote a model because Brier improved if the selected slip tail got worse.
```

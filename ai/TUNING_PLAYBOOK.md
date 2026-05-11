# Atlas Tuning Playbook

> **Last updated:** 2026-05-10
> **Purpose:** Diagnostic decision tree for improving model metrics. For each symptom, this file tells you which lever to pull, what to change, and how to validate the result before promoting.
> **Current runtime:** CatBoost playoff v5cD active; v18 GBM and telemetry isotonic disabled.

---

## How to Use This File

1. Identify the symptom (metric that's wrong)
2. Follow the diagnostic chain — start from the top
3. Make the smallest change that addresses the root cause
4. Validate with a single-slate replay before a full backtest
5. Never change two levers simultaneously — you won't know which one worked

---

## Symptom 1 — Brier Score Is Rising

Brier = `mean((p_cal - hit)^2)`. Higher is worse.

### Diagnostic Chain

**Step 1: Is this isolated to one direction?**
Run `tools/diagnose_winprob.py` and compare OVER vs UNDER Brier. If UNDER Brier is the driver:
→ Go to Symptom 3 (UNDER calibration).

**Step 2: Is this a calibration drift (new dates, regime change)?**
Check if the dates where Brier jumped coincide with a new phase (playoff start, roster changes, rule changes).

- If yes under current runtime → run CatBoost replay diagnostics first (`python tools/replay_v5cD_corpus.py`). Isotonic is currently disabled and should not be the first lever.
- If no → continue

**Step 3: Is the CatBoost playoff calibrator stale?**
Count playoff eval dates since the v5cD training window (through 2026-05-09). If 5-10 new playoff dates have accumulated:
→ Rebuild the playoff cache and retrain/evaluate CatBoost before touching the historical GBM.

**Step 4: Is `p_adj` (pre-CatBoost) drifting?**
Check `data/output/latest/all/System/scored_legs_deduped.csv`. Look at `p_adj`, `p_for_cal`, `p_catboost_residual`, and `p_cal` by tier. If `p_adj` is already miscalibrated before CatBoost:
→ Check role context and blowout settings — something upstream is pushing probabilities in the wrong direction.

---

## Symptom 2 — Hit Rate Is Declining

Hit rate = fraction of selected legs that actually hit.

### Diagnostic Chain 2

**Step 1: Is this a sample size issue?**
Playoff slates are small (2–4 games). 3–5 bad dates can swing hit rate ±5pp. Check if Brier is also rising. If Brier is stable, hit rate swing is noise — don't tune yet.

**Step 2: Are the wrong legs being selected?**
Pull `scored_legs_deduped.csv` and filter to legs that appeared in the slip. Check:

- Is `l20_edge` positive for all selected legs? (Recent form confirmation)
- Is `player_dir_te` above 0.02 for STANDARD legs? (Leg quality filter)
- Is `q_blowout` high for legs that missed? (Blowout exposure)

If leg quality filters aren't catching bad legs:
→ Raise `slip_build.leg_quality_filters.min_goblin_l20_edge` (e.g. 0.05 → 0.08) or `min_standard_player_dir_te` (0.02 → 0.04)

**Step 3: Is the slip builder over-concentrating risk?**
Check if multiple legs from the same team are appearing in slips. A single bad game crushes all correlated legs.
→ Raise `slip_build.penalty.team_w` in `by_legs['3']` or `['4']`

**Step 4: Are UNDER legs dragging down results?**
Check hit rate split by direction. UNDER AUC is historically ~0.52, but v5cD currently disables the old UNDER window. If UNDER legs are frequently missing:
→ Compare `p_for_cal` vs `p_catboost` and direction-split Brier on replay before restoring any UNDER cap.

---

## Symptom 3 — UNDER Calibration Is Off

UNDER legs should have a calibrated probability that matches actual hit rate. Check `diagnose_winprob.py` UNDER tier table.

### Diagnostic Chain 3

**Step 1: Are UNDER legs overconfident (model > actual)?**
Model says 0.80 UNDER probability, actual hit rate is 0.55. This is the historical chronic problem.

- Check whether the error is already present in `p_for_cal` or introduced by CatBoost (`p_catboost_residual`).
- If the error is in `p_for_cal`, test kernel subset shift or under-fragility settings.
- If the error is introduced by CatBoost, retrain/evaluate v5cD on the expanded playoff cache.

**Step 2: Are UNDER legs being over-selected in slips?**
Current setting: `slip_build.min_under_prob = 0.0`, `max_under_prob = 0.0`, and same for `marketed_slips`. This is intentional under v5cD. Reintroduce an UNDER window only after replay evidence shows v5cD UNDERs are again overselected.

**Step 3: Is under-relief doing anything unexpected?**
Check `role_ctx.under_relief_factor`. If it's non-zero, it's actively adjusting UNDER probabilities upward when `q_blowout` is high. In playoffs, this may be miscalibrated.
→ Current setting: `0.0` (disabled). If recently changed, revert.

---

## Symptom 4 — Slips Are All From the Same Team

This means the diversity penalty is too weak relative to the edge signal for a particular team.

### Fix

In `config.yaml` → `slip_build.by_legs`:

```yaml
'3':
  penalty:
    team_w: 0.15   # raise from current 0.02 → 0.10 or 0.15
```

Or add a hard cap: `max_players_per_team: 1` for 3-leg slips if you want zero same-team exposure.

**Validate:** Run a single replay on a recent slate with the old and new config. Compare the `team` distribution in the output slip CSVs.

---

## Symptom 5 — Marketed Slips Are Empty or Thin

The marketed builder is producing fewer slips than expected (< 3 per leg count).

### Diagnostic Chain 4

**Step 1: Are thresholds too high for current p_cal range?**
Under v5cD, post-haircut floors are disabled and the builder gates on raw `p_cal`.
Current raw floors are `GOBLIN=0.68`, `STANDARD=0.55`, `DEMON=0.50`.
If marketed slips are thin, inspect raw `p_cal`, direction filters, and single-game caps before changing thresholds.

**Step 2: Are too many stats excluded?**
Check `marketed_slips.excluded_stats`. Currently: `[BLK, STL, TO, FTA]`. FTA remains excluded until a validated retrain says otherwise.

**Step 3: Is the UNDER window too narrow?**
The UNDER window is currently disabled. On one-game or two-game slates, thin output is more likely caused by direction filters, excluded stats, team caps, or too few unique players.

---

## Symptom 6 — Role Context Is Misfiring on Injury Nights

A key player is OUT but the role context isn't boosting backup players as expected.

### Diagnostic Chain 5

**Step 1: Is the share matrix populated for this player?**
Check `data/model/share_matrix.csv`. Filter for `out_player = <name>`. If no rows → no share matrix data exists for this player.

- Fix: Run `python tools/build_share_matrix.py` to rebuild from current gamelogs. If the player is new/traded, there won't be enough games yet (minimum `role_ctx.min_games = 3`).

**Step 2: Is role context enabled for this leg's tier?**
Check `demon_tier_damp`. If the backup player is in DEMON tier and `demon_tier_damp = 0.0`, role context is fully suppressed for their legs by design.

**Step 3: Is zero-DNP correction firing?**
If the out player has no historical DNP games and this is their first injury absence, zero-DNP should boost backup players. Check `scored_legs_deduped.csv`:

- `role_ctx_reason` should say `zero_dnp`
- `role_ctx_mult` should be > 1.0

If not firing, check `zero_dnp_enabled = true` and that `zero_dnp_dnp_thresh = 2` (out player must have < 2 historical DNPs).

**Step 4: Is the post-GBM blend overriding the MC boost?**
If `zero_dnp_postcal_blend_thresh` is high (e.g. 1.40), only very large role context adjustments trigger the post-cal protection. Lower to 1.25 to protect more zero-DNP boosts from being washed away by the GBM.

---

## Symptom 7 — Calibrator Is Promotable But Per-Slate Regression Exists

A new GBM, CatBoost model, or resim cache rebuild improves aggregate Brier but one or more specific dates regress.

### Rule

**Do not promote.** The constraint is: every individual slate must be non-regressive.

### Diagnostic

Pull LODO per-date Brier from the trainer output. Find the regressing dates. Check:

1. Was the regressing date a small-sample slate (< 30 legs)? Small-slate variance is expected — this may not be a real regression.
2. Is there a feature distribution shift on that date? (e.g. unusual number of injury outs → role context extremes that the calibrator has not seen)
3. Was that date used in calibration training? If yes, the calibrator may have overfit to it and then flipped when held out.

### Options

- Accept if regressing date had < 30 legs (noise) — document and proceed
- Add more training dates if the regressing date is representative of a regime the model hasn't learned
- Retrain calibration (isotonic) separately before promoting GBM

---

## Symptom 8 — External Priors Are Overriding Model

`p_for_cal` is very different from `p_adj`, and the external prior is the main driver.

### Fix 2

In `config.yaml` → `optimizer.external_priors`:

```yaml
cap: 0.03   # was 0.05 — tighter cap means max ±3pp nudge
scale: 2.0  # was 1.5 — higher scale = nudge grows slower from center
```

Or disable entirely for a test run: `enabled: false` in `external_priors`.

**Validate:** Compare `p_adj` vs `p_for_cal` in `scored_legs_deduped.csv` before and after.

---

## CatBoost v5cD Retrain / Validation Workflow

When to retrain: new playoff dates since 2026-05-09, persistent Brier drift, or a kernel transform change that changes the CatBoost input distribution.

```powershell
# Step 1: Rebuild or verify playoff cache
python tools/build_playoff_resim_cache.py

# Step 2: Run v5cD replay validation
python tools/replay_v5cD_corpus.py

# Step 3: Inspect summary
type logs\replay_v5cD_corpus_<tag>_summary.csv

# Step 4: Train full-corpus model only after validation
python tools/catboost_playoff_v5cD_full_corpus.py

# Step 5: Run runtime smoke
python scripts/validation/smoke_v5cD_runtime.py
```

Promotion requires updating `config.yaml -> catboost_playoff_calibrator.model_path/meta_path` if paths change, then updating `ai/CURRENT_STATE_2026-05-10.md` or a new current-state doc.

---

## Historical GBM Retrain Workflow

When to retrain: ≥15 new eval dates accumulated since last train, or Brier rising persistently.

```powershell
# Step 1: Check cache dates
python -c "import pickle; c=pickle.load(open('data/model/_v18_resim_cache.pkl','rb')); print(sorted(c['dates']))"

# Step 2: Backfill any missing dates from bundles
python tools/batch_replay_backfill.py

# Step 3: Rebuild cache (update version number)
python tools/build_resim_cache.py --version v19 --force

# Step 4: Train with LODO
python tools/gbm_v19_train.py --lodo

# Step 5: Inspect per-date results — confirm no slate regressions

# Step 6: Promote if improved
python tools/gbm_v19_train.py --promote
```

**After promotion:** Update `config.yaml` → `posthoc_calibrator.ensemble_dir` only if the GBM path is being re-enabled. Current production has `posthoc_calibrator.enabled: false`, so a GBM retrain alone does not affect production until config changes.

---

## Isotonic Calibration Retrain Workflow

When to retrain: only for controlled experiments while `telemetry.apply_active_calibration` remains `false`, or if the team decides to reintroduce isotonic after CatBoost.

```powershell
python tools/train_playoff_isotonic.py
```

After running, inspect the output JSON for the new `x_points`/`y_points` curves. Confirm:

- OVER curve is monotone and spans a reasonable range (0.50 → 0.85)
- UNDER curve is separate and shows the expected flatness (UNDER is near-efficient)

**Deploy:** The script writes to `data/model/telemetry_calibration.playoff_isotonic.json`, but deployment still requires flipping `telemetry.apply_active_calibration: true`. That is currently off.

---

## Leg Trainer Workflow

When to run: after a major config change (new blowout rules, new penalty weights) or quarterly for drift check.

```powershell
# EV-optimized sweep
python tools/leg_trainer_v5_ev.py

# Hit-rate-optimized sweep
python tools/leg_trainer_v5_hit.py
```

**Rules:**

1. Verify all `RUN_DATES` corpus dirs have `eval_legs.csv` with > 0 rows before launching
2. Trainer runs are multi-hour — set up and let run overnight
3. When trainer reports improvement, apply new params to `config.yaml` immediately — do not wait
4. Keep all three trainers (`ev`, `hit`, `demonhunter_trainer_v4`) on the same date list

---

## Daily Health Check

What to verify after each automated run:

1. `data/output/latest/all/System/recommended_3leg.csv` — exists and non-empty
2. `data/output/latest/all/System/marketed_slips_latest.json` — exists and non-empty
3. `data/output/dashboard/status_latest.json` — `run_ok: true`
4. No `IAEL` errors in the run log (injured player appeared in output slips)
5. Twitter/X post went out (check for 402 CreditsDepleted in logs — if seen, credits need replenishment)

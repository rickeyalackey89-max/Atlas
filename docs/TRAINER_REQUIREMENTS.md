# Atlas Trainer Requirements

> **Audit status:** intentionally not refreshed in this docs pass.
>
> This file still describes the historical GBM/isotonic trainer stack in several places. Current production is CatBoost playoff v5cD, and trainer compatibility with the May 10 CatBoost/runtime changes still needs a dedicated audit before these instructions are used for promotion.
>
> Current runtime reference: [CURRENT_STATE_2026-05-10.md](CURRENT_STATE_2026-05-10.md).

Reference for all model and slip-builder trainers — inputs, outputs, runtime, ordering.

---

## Execution Order

Trainers must run in this order (each depends on outputs from previous):

```text
1. GBM Trainer (gbm_v17_train.py)          → produces GBM ensemble models
2. Calibration Trainers                      → produces isotonic calibration JSONs
   a. calibration_trainer.py                 → compares 12 methods, picks best
   b. train_direction_calibrator.py          → OVER/UNDER split isotonic
3. Leg Trainers (can run in parallel)        → produces slip builder config
   a. leg_trainer_v5_system.py                → EV-optimized slip params (System builder)
   b. leg_trainer_v5_windfall.py              → HIT-optimized slip params (Windfall builder)
   c. demonhunter_trainer_v4.py              → DEMON-only slip params
   d. slip_builder_trainer.py                → 3-leg EV/HIT slip params (stat_family_mode, beam_window_growth)
   e. external_priors_trainer.py             → external prior cap/scale/floor/ceil
```

The leg trainers use scored_legs that include GBM-calibrated probabilities (`p_cal`), so they must run AFTER the GBM and calibration trainers produce updated model artifacts.

---

## 1. GBM Trainer (`tools/gbm_v17_train.py`)

**Purpose:** Train a 33-feature LightGBM ensemble (7 seeds × 2 directions = 14 models) via Leave-One-Date-Out (LODO) cross-validation. Primary metric: Brier score. Production: v18, T=1.04, LODO 0.201529.

> **Note:** The canonical 33-feature set is the production contract. Do not add features without updating `src/Atlas/contracts/model_contract.py`.

### GBM CLI

```powershell
# Baseline LODO on v18 cache
python tools/gbm_v17_train.py --cache v18

# Test candidate features
python tools/gbm_v17_train.py --cache v18 --extra-feats role_ctx_outs_n opp_defense_rel

# Train + deploy to production
python tools/gbm_v17_train.py --cache v18 --promote

# Promote already-trained staging ensemble without re-running LODO
python tools/gbm_v17_train.py --cache v18 --from-staging [--force-promote]
```

### GBM Arguments

| Arg             | Default | Description                                  |
| --------------- | ------- | -------------------------------------------- |
| `--cache`       | `v18`   | Cache version: `v18` or later                |
| `--promote`     | off     | Save trained models to `data/model/ensemble/`|
| `--from-staging`| off     | Promote staged ensemble without re-running LODO |
| `--force-promote`| off    | Override regression safety gate              |
| `--extra-feats` | none    | Candidate features to test (space-separated) |

### GBM Required Inputs

| File                | Path                                                    | Format                                                           |
| ------------------- | ------------------------------------------------------- | ---------------------------------------------------------------- |
| Resim cache         | `data/model/_v{N}_resim_cache.pkl`                      | Pickle: `{cv: DataFrame, dates: list, raw_brier: float}`        |
| Gamelogs            | `data/gamelogs/nba_gamelogs.csv`                        | CSV: player, game_date, pts, reb, ast, fg3m, fga, fta, tov, min |
| Rotowire (optional) | `data/archives/iael/2026/{date}/*/rotowire_lines.json` | JSON: game totals for normalization                              |

### Cache DataFrame Required Columns

`p_new` (or `p`), `hit`, `stat_u`, `game_date`, `direction`, `tier`, `line`, `player`, `team`, `opp`, `q_blowout`, `fragility`, `usage_dep`, `role_ctx_mult`, `role_ctx_outs_used`, `home` (or `is_home`)

Features like `min_cv`, `is_combo`, `z_line`, `bp_score_gated`, etc. are **computed internally** from raw columns — they don't need to exist in the cache.

### GBM Outputs

| Output               | Path                                     | When             |
| -------------------- | ---------------------------------------- | ---------------- |
| LODO Brier (console) | stdout                                   | Always           |
| Ensemble models      | `data/model/ensemble/*.txt`              | With `--promote` |
| Ensemble meta        | `data/model/ensemble/ensemble_meta.json` | With `--promote` |

### GBM Architecture

- **Seeds:** 65536, 9999, 137, 999, 98765, 54321, 12345
- **OVER:** depth=8, leaves=30, L2=1.0, min_child=200
- **UNDER:** depth=11, leaves=50, L2=6.0, min_child=150
- **Rounds:** 200, learning_rate=0.03
- **Temperature:** 1.04 (v18 production; trainer searches [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12])
- **Clip:** p ∈ [0.03, 0.97]

### Candidate Extra Features

| Name                 | Source Column          | Transform                |
| -------------------- | ---------------------- | ------------------------ |
| `opp_defense_rel`    | `form_opp_defense_rel` | Clip ±0.2                |
| `pace_factor`        | `form_pace_factor`     | Clip ±0.1                |
| `role_ctx_outs_n`    | `role_ctx_outs_used`   | Clip 0–5                 |
| `usage_dep_feat`     | `usage_dep`            | Center at 0 (subtract 1) |
| `fragility_feat`     | `fragility`            | Clip 0–0.3               |
| `role_ctx_mult_feat` | `role_ctx_mult`        | Delta from 1.0           |

### GBM Interpreting Results

- **Good:** LODO Brier ≤ 0.201529 (v18 production baseline: 0.201529)
- Per-date breakdown should be consistent (no single-date blowups)
- Feature importance shows which features drive predictions

### GBM Runtime

~15–25 minutes

---

## 2a. Calibration Trainer (`tools/calibration_trainer.py`)

**Purpose:** Compare 12 calibration methods via LODO. Finds best p_adj → p_cal transformation and saves deployable artifacts.

### Calibration CLI

```powershell
python tools/calibration_trainer.py
```

### Calibration Required Inputs

| File             | Path                                                                                               | Format                                      |
| ---------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Eval legs corpus | `data/telemetry/v9d_corpus/runs/*/runs/*/eval_legs.csv`                                            | CSV: hit, p_adj, game_date, direction, stat |
| Fallback corpus  | `data/telemetry/replay_runs/{.corpus_tag}_{date}/*/runs/*/eval_legs.csv`     | Same                                        |

### Eval Legs Required Columns

`hit`, `p_adj`, `game_date`, `direction`, `stat`

### Calibration Outputs

| Output          | Path                                                                         |
| --------------- | ---------------------------------------------------------------------------- |
| Results summary | `tools/calibration_trainer_results.yaml`                                     |
| Isotonic global | `data/model/calibration_candidates/calibration_isotonic_global.json`         |
| Direction split | `data/model/calibration_candidates/calibration_isotonic_direction_split.json` |
| Stat-direction  | `data/model/calibration_candidates/calibration_isotonic_stat_direction.json`  |

### Methods Tested (12)

Identity, global isotonic, direction-split isotonic, stat-family×direction isotonic, Platt scaling, direction-split Platt, histogram binning, temperature scaling, stat-family×direction Platt, per-stat×direction isotonic, isotonic blended, direction-split isotonic blended.

### Calibration Interpreting Results

- Ranked by Brier score (lower = better)
- Direction-split isotonic typically wins (corrects UNDER overconfidence)
- Improvement vs identity should be negative (e.g., -0.002)

### Calibration Runtime

~10–30 minutes

---

## 2b. Direction Calibrator (`tools/train_direction_calibrator.py`)

**Purpose:** Train separate isotonic curves for OVER vs UNDER legs. Fixes the UNDER overconfidence problem (model 0.918 vs actual 0.505 at 0.80+ tier).

### Direction Calibrator CLI

```powershell
python tools/train_direction_calibrator.py
```

### Direction Calibrator Required Inputs

| File        | Path                                                              | Format                                  |
| ----------- | ----------------------------------------------------------------- | --------------------------------------- |
| Scored legs | `data/telemetry/replay_runs/{.corpus_tag}_{date}/scored_legs_deduped.csv` | CSV: p_adj, direction                   |
| Eval legs   | Same dir `eval_legs.csv`                                          | CSV: hit, player, line, stat, direction |

**Dates (hardcoded):** 23 dates, 2026-03-15 through 2026-04-07.

### Direction Calibrator Outputs

| Output        | Path                                                             |
| ------------- | ---------------------------------------------------------------- |
| Isotonic JSON | `data/model/telemetry_calibration.isotonic_direction_split.json` |

### Direction Calibrator Interpreting Results

- UNDER high-prob tail gap improvement (from -40pp to -5pp)
- Overall Brier improvement ~0.001–0.002

### Direction Calibrator Runtime

~1–2 minutes

---

## 3a. Leg Trainer v5 System (`tools/leg_trainer_v5_system.py`)

**Purpose:** Grid-search slip builder parameters to maximize EV (expected value) of 3/4/5-leg parlays for the **System** (score_adj-sorted) builder.

### System Trainer CLI

```powershell
python tools/leg_trainer_v5_system.py
```

### System Trainer Required Inputs

| File        | Path                                                       | Format                     |
| ----------- | ---------------------------------------------------------- | -------------------------- |
| Scored legs | `data/telemetry/v18_corpus/{date}/scored_legs_deduped.csv` | Full scored legs with p_cal |
| Eval legs   | `data/telemetry/v18_corpus/{date}/eval_legs.csv`           | Truth labels (hit)         |

**Dates:** Defined in `RUN_DATES`. Corpus auto-discovered (v18_corpus → v18_corpus → D-drive fallback).

### System Scored Legs Required Columns

`player`, `stat`, `line`, `direction`, `tier`, `p_cal`, `score_adj`, `team`, `opp`, `fragility`

### System Eval Legs Required Columns

`player`, `stat`, `line`, `direction`, `hit`

### System Search Structure (4 stages per category)

| Stage | Focus                                                                           | Combos | Time       |
| ----- | ------------------------------------------------------------------------------- | ------ | ---------- |
| S1    | Structural: excludes, min_edge, penalties, stat_family_mode, beam_window_growth | ~1440  | ~30–60 min |
| S1b   | Refinement: min_leg_prob, max_players, leg_quality_filters                      | ~15–25 | ~10s       |
| S2    | Exploration: beam_width, phase1_frac, pool_mult                                 | ~80+   | ~100s      |
| S3    | Fine-tuning: ±small steps on best                                               | ~40–80 | ~100s      |

### System Key Parameters

- **Seeds:** [42, 137, 9999, 2026, 777]
- **TOP_K:** 5 slips evaluated per config
- **MAX_ATTEMPTS:** 30,000 per slip per seed
- **Categories:** 3-leg SYSTEM, 4-leg SYSTEM, 5-leg SYSTEM
- **Output YAML:** `tools/leg_trainer_results_v5_system.yaml`
- **Config target:** `slip_build.by_legs.{3|4|5}`

### System Runtime

~2–6 hours

---

## 3b. Leg Trainer v5 Windfall (`tools/leg_trainer_v5_windfall.py`)

**Purpose:** Same as System trainer but optimizes for HIT rate (raw probability selection) for the **Windfall** (hit-sorted) builder. Expanded beam/pool grids.

### Windfall Trainer CLI

```powershell
python tools/leg_trainer_v5_windfall.py
```

### Windfall Trainer Required Inputs

Same as v5 System: corpus auto-discovered with `scored_legs_deduped.csv` + `eval_legs.csv`.

### Windfall Differences from System

- Larger S2/S3 grids (~150+ and ~100+ combos vs ~80 and ~40)
- S1 grid: ~64 combos (no exclude/edge — Windfall strips them at runtime)
- Adds `phase1_pool_frac` parameter sweep
- Sort mode: `hit` (selects by pure probability rather than edge)
- **Output YAML:** `tools/leg_trainer_results_v5_windfall.yaml`
- **Config target:** `slip_build.by_sort_mode.hit.by_legs.{3|4|5}`

### Windfall Runtime

~4–8 hours

---

## 3c. DemonHunter Trainer v4 (`tools/demonhunter_trainer_v4.py`)

**Purpose:** Tune all-DEMON slip configurations (pure DEMON tier, highest multiplier parlays).

### DemonHunter CLI

```powershell
python tools/demonhunter_trainer_v4.py
```

### DemonHunter Required Inputs

Same as leg trainers: `data/telemetry/v13_corpus/{date}/` with both CSVs.

### DemonHunter Key Differences

- **Seeds:** [42, 137] (only 2 — DEMON pool is large, seeds barely differ)
- **TOP_K:** 3
- **MIN_DATES_BEFORE_PRUNE:** 4 (prevents premature pruning)
- 2-stage pipeline (S1 structural + S2 exploration)
- `per_tier` is primary lever (200–1000)

### DemonHunter Outputs

| Output       | Path                                        |
| ------------ | ------------------------------------------- |
| Results YAML | `tools/demonhunter_trainer_results_v4.yaml` |

### DemonHunter Runtime

~2–4 hours

---

## 3d. Slip Builder Trainer (`tools/slip_builder_trainer.py`)

**Purpose:** Grid-search slip builder params specific to 3-leg EV and 3-leg HIT — sweeps `stat_family_mode`, `beam_window_growth`, `max_leg_prob`, `min_leg_prob`, and `frag_w`. Uses multiprocessing for parallel combo evaluation.

### Slip Builder CLI

```powershell
python tools/slip_builder_trainer.py
```

### Slip Builder Required Inputs

| File        | Path                                                                                                 | Format            |
| ----------- | ---------------------------------------------------------------------------------------------------- | ----------------- |
| Scored legs | `data/telemetry/replay_runs/{.corpus_tag}_{date}/scored_legs_deduped.csv` | Full scored legs  |
| Eval legs   | Same dir `eval_legs.csv`                                                                             | Truth labels (hit) |

**Dates:** 44 dates hardcoded in `RUN_DATES` (2026-02-08 through 2026-04-07).

### Slip Builder Parameter Grid (144 combos)

| Parameter            | Values                             |
| -------------------- | ---------------------------------- |
| `max_leg_prob`       | 0.0, 0.65, 0.70, 0.75, 0.78, 0.80 |
| `min_leg_prob`       | 0.50, 0.52, 0.55                   |
| `frag_w`             | 0.0, 0.20                          |
| `stat_family_mode`   | coarse, fine                        |
| `beam_window_growth` | 1.5, 2.0                           |

### Slip Builder Key Parameters

- **Seeds:** [42, 137, 9999] (3 seeds × top-3 slips each for stability)
- **TOP_N_PER_SEED:** 3
- **Categories:** 3-leg EV, 3-leg HIT
- **Workers:** `cpu_count - 1` (parallel combo evaluation via ProcessPoolExecutor)

### Slip Builder Outputs

Console output with best configs per category. Apply winning params to `config.yaml` → `slip_build.by_legs."3"` and `slip_build.by_sort_mode.hit.by_legs."3"`.

### Slip Builder Runtime

~30–60 minutes

---

## 3e. External Priors Trainer (`tools/external_priors_trainer.py`)

**Purpose:** Sweep external prior parameters (cap, scale, p_floor, p_ceil) against truth-backed legs in the resim cache to minimize Brier score.

### External Priors CLI

```powershell
python tools/external_priors_trainer.py
```

### External Priors Required Inputs

| File        | Path                              | Format                                                                    |
| ----------- | --------------------------------- | ------------------------------------------------------------------------- |
| Resim cache | `data/model/_v14_resim_cache.pkl` | Pickle with `cv` DataFrame containing `external_prior_score`, `p`, `hit` |

### External Priors Parameter Grid (196 combos)

| Parameter | Values                                     |
| --------- | ------------------------------------------ |
| `cap`     | 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08 |
| `scale`   | 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0        |
| `p_floor` | 0.01, 0.02                                 |
| `p_ceil`  | 0.98, 0.99                                 |

### External Priors Outputs

| Output       | Path                                         |
| ------------ | -------------------------------------------- |
| Results YAML | `tools/external_priors_trainer_results.yaml` |

Apply winning params to `config.yaml` → `external_priors`.

### External Priors Runtime

~5–10 minutes

---

## Corpus Setup for Leg Trainers

All three leg trainers + slip builder trainer read from `data/telemetry/v13_corpus/{YYYYMMDD}/` with this structure:

```text
data/telemetry/v13_corpus/
  20260208/
    scored_legs_deduped.csv
    eval_legs.csv
  20260209/
    scored_legs_deduped.csv
    eval_legs.csv
  ...
  20260407/
    scored_legs_deduped.csv
    eval_legs.csv
```

The slip builder trainer (`tools/slip_builder_trainer.py`) reads from `data/telemetry/replay_runs/{.corpus_tag}_{YYYYMMDD}/`.
The active tag is read from `data/telemetry/replay_runs/.corpus_tag`. Each batch replay auto-generates a unique timestamped tag.

Each date dir must contain BOTH files with >0 rows. The trainers will skip or fail on dates missing either file.

### Building the Corpus

After running replays, consolidate from `data/telemetry/replay_runs/` using `tools/build_v12_corpus.py` or manually:

```powershell
# For each replay date, copy the latest scored_legs + eval_legs to flat v13_corpus dir
```

### Updating RUN_DATES

When the corpus expands, ALL trainers must have their `RUN_DATES` lists updated simultaneously. The lists must be identical across:

- `leg_trainer_v5_system.py`
- `leg_trainer_v5_windfall.py`
- `demonhunter_trainer_v4.py`
- `slip_builder_trainer.py`

---

## Working Directory Rule — CRITICAL

**ALL trainers and tools must be run from `C:\Users\13142\Atlas` (the workspace root), NOT from `C:\Users\13142\Atlas\Atlas` (the inner repo folder).**

```powershell
# CORRECT — workspace root
cd C:\Users\13142\Atlas
$env:PYTHONIOENCODING='utf-8'
py Atlas\tools\marketed_slip_trainer_v2.py

# WRONG — inner folder, calibration JSONs and relative paths will not resolve
cd C:\Users\13142\Atlas\Atlas
py tools\marketed_slip_trainer_v2.py   # <-- DO NOT RUN FROM HERE
```

**Why:** Multiple tools (including `marketed_slip_builder.py`) resolve calibration files and config paths relative to the working directory. When run from `Atlas\Atlas`, the path `data/model/marketed_calibration.json` resolves to `C:\Users\13142\Atlas\Atlas\data\model\...` which may or may not exist depending on what's installed. Running from `Atlas\` ensures all relative paths are consistent with how the live pipeline sees them.

**Symptom of wrong CWD:** `marketed_calibration.json` not found → builder falls back to hardcoded multipliers → baseline slip win rate reads ~26% instead of the correct ~39.5%.

---

## marketed_slip_trainer_v2 — Baseline Reference

**Verified correct baseline (May 6 2026, v18 cache, production config):****

| Metric | Value |
|---|---|
| Baseline win rate | **39.5%** (51/129 slips) |
| 3-leg | 60.5% |
| 4-leg | 37.2% |
| 5-leg | 20.9% |
| Cache | `data/model/_v17_resim_cache.pkl` (44 dates, 165,792 legs) |
| Thresholds | GOBLIN=0.57, STANDARD=0.30, DEMON=0.28 |
| Excluded stats | BLK, STL, TO |
| Direction filters | none |
| Cal file | `data/model/marketed_calibration.json` v1.2 |

The `BASE_CONFIG` inside `marketed_slip_trainer_v2.py` **must exactly match production `config.yaml` marketed_slips thresholds** before running. Verify before every sweep:

```powershell
# Check production thresholds
Select-String "GOBLIN|STANDARD|DEMON" Atlas\config.yaml | Select-Object -First 10
# Check trainer BASE_CONFIG matches
Select-String "GOBLIN|STANDARD|DEMON" Atlas\tools\marketed_slip_trainer_v2.py | Select-Object -First 10
```

---

## Pre-Flight Checklist

Before launching any trainer:

- [ ] **CWD is correct:** Running from `C:\Users\13142\Atlas` (workspace root), not `Atlas\Atlas`
- [ ] **BASE_CONFIG matches production:** Trainer thresholds match `config.yaml` marketed_slips section
- [ ] **Cache exists:** `data/model/_v{N}_resim_cache.pkl` with expected date count
- [ ] **Gamelogs current:** `data/gamelogs/nba_gamelogs.csv` covers all replay dates
- [ ] **Corpus complete:** Every date in `RUN_DATES` has both `scored_legs_deduped.csv` and `eval_legs.csv` with >0 rows
- [ ] **Feature columns present:** `p_cal` not NaN, `hit` not NaN, `game_date` correct
- [ ] **Config backed up:** Copy of current `config.yaml` saved before applying trainer results
- [ ] **No stale models:** If re-training GBM, old ensemble in `data/model/ensemble/` will be overwritten with `--promote`

---

## Quick Reference

| Trainer                 | Input                            | Output                       | Runtime   | Metric      |
| ----------------------- | -------------------------------- | ---------------------------- | --------- | ----------- |
| gbm_v17_train           | Resim cache + gamelogs           | LODO Brier + ensemble models | 15–25 min | Brier ↓     |
| calibration_trainer     | Eval legs corpus                 | 12-method comparison + JSONs | 10–30 min | Brier ↓     |
| train_direction_cal     | 23-date replay corpus            | Isotonic JSON                | 1–2 min   | Gap ↓       |
| leg_trainer_v5_system   | v18_corpus (auto-discovered)     | Best slip configs + YAML     | 4–12 hrs  | slip_wins ↑ |
| leg_trainer_v5_windfall | v18_corpus (auto-discovered)     | Best slip configs + YAML     | 6–16 hrs  | slip_wins ↑ |
| demonhunter_v4          | v13_corpus (44 dates)            | Results YAML                 | 2–4 hrs   | slip_wins ↑ |
| slip_builder_trainer    | D-drive replay corpus (44 dates) | Best 3-leg configs (console) | 30–60 min | slip_wins ↑ |
| external_priors_trainer | Resim cache (v18)                | Results YAML                 | 5–10 min  | Brier ↓     |

"""
GBM Hyperparameter Sweep — v17 cache, no promotion.

Tests multiple configurations via LODO and prints a comparison table.
Uses the pre-built features fast path (all 33 FEATS already in cache).

Usage:
    python scripts/experiments/gbm_hyperparam_sweep.py --cache v17
"""
import sys, pathlib, warnings, time, json, argparse, pickle

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit, expit as sp_expit
import lightgbm as lgb

parser = argparse.ArgumentParser()
parser.add_argument("--cache", choices=["v17"], default="v17")
args = parser.parse_args()

# ── Baseline (current production) ───────────────────────────────────
BASELINE_LODO = 0.201402   # v17, 47 dates, force-promoted May 3 2026

SEEDS = [65536, 9999, 137, 999, 98765, 54321, 12345]
FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]
CAT_FEATURES = ["stat_cat", "tier_cat"]
CAT_IDX = [FEATS.index(f) for f in CAT_FEATURES]
P_LO, P_HI = 0.03, 0.97
TEMP_CANDIDATES = [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12]

# ── Configurations to sweep ──────────────────────────────────────────
# Format: (label, params_over, params_under, n_rounds)
CONFIGS = [
    (
        "baseline (d8/nl30/l2=1.0/mc200 x d11/nl50/l2=6.0/mc150, r200)",
        {"objective":"binary","metric":"binary_logloss","max_depth":8,"num_leaves":30,"learning_rate":0.03,"min_child_samples":200,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"verbose":-1},
        {"objective":"binary","metric":"binary_logloss","max_depth":11,"num_leaves":50,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":6.0,"verbose":-1},
        200,
    ),
    (
        "rounds=300 (all else baseline)",
        {"objective":"binary","metric":"binary_logloss","max_depth":8,"num_leaves":30,"learning_rate":0.03,"min_child_samples":200,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"verbose":-1},
        {"objective":"binary","metric":"binary_logloss","max_depth":11,"num_leaves":50,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":6.0,"verbose":-1},
        300,
    ),
    (
        "OVER mc=150 (baseline mc=200)",
        {"objective":"binary","metric":"binary_logloss","max_depth":8,"num_leaves":30,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"verbose":-1},
        {"objective":"binary","metric":"binary_logloss","max_depth":11,"num_leaves":50,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":6.0,"verbose":-1},
        200,
    ),
    (
        "UNDER l2=3.0 (baseline l2=6.0)",
        {"objective":"binary","metric":"binary_logloss","max_depth":8,"num_leaves":30,"learning_rate":0.03,"min_child_samples":200,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"verbose":-1},
        {"objective":"binary","metric":"binary_logloss","max_depth":11,"num_leaves":50,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":3.0,"verbose":-1},
        200,
    ),
    (
        "OVER nl=40 (baseline nl=30)",
        {"objective":"binary","metric":"binary_logloss","max_depth":8,"num_leaves":40,"learning_rate":0.03,"min_child_samples":200,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"verbose":-1},
        {"objective":"binary","metric":"binary_logloss","max_depth":11,"num_leaves":50,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":6.0,"verbose":-1},
        200,
    ),
    (
        "rounds=300 + OVER mc=150 + UNDER l2=3.0 (combined)",
        {"objective":"binary","metric":"binary_logloss","max_depth":8,"num_leaves":30,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"verbose":-1},
        {"objective":"binary","metric":"binary_logloss","max_depth":11,"num_leaves":50,"learning_rate":0.03,"min_child_samples":150,"feature_fraction":0.8,"bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":3.0,"verbose":-1},
        300,
    ),
]

# ── Load cache ───────────────────────────────────────────────────────
cache_path = ROOT / "data" / "model" / "_v17_resim_cache.pkl"
print(f"Cache: {cache_path}")
with open(cache_path, "rb") as f:
    cache = pickle.load(f)

cv = cache["cv"].copy()
dates = cache["dates"]
print(f"  {len(cv)} legs, {len(dates)} dates")

# Drop legs without truth labels
cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
dates = sorted(cv["game_date"].astype(str).str[:10].unique())

# Verify all 33 features are present
missing = [f for f in FEATS if f not in cv.columns]
if missing:
    print(f"ABORT: Missing features in cache: {missing}")
    sys.exit(1)
print(f"All {len(FEATS)} features present in cache (pre-built fast path).")

# Prep arrays
X_all = np.nan_to_num(cv[FEATS].values.astype(float), nan=0.0)
hit_arr = cv["hit"].values.astype(float)
um = (cv["direction"].astype(str).str.upper() == "UNDER").values
date_arr = cv["game_date"].astype(str).str[:10].values
sorted_dates = sorted(dates)

# ── LODO runner ──────────────────────────────────────────────────────
def run_lodo_config(label, params_over, params_under, n_rounds):
    print(f"\n{'='*72}")
    print(f"CONFIG: {label}")
    print(f"  rounds={n_rounds}  OVER mc={params_over['min_child_samples']} nl={params_over['num_leaves']} l2={params_over['lambda_l2']}")
    print(f"         UNDER mc={params_under['min_child_samples']} nl={params_under['num_leaves']} l2={params_under['lambda_l2']}")
    print(f"{'='*72}")
    t0 = time.time()

    oof_preds = np.full(len(cv), np.nan)
    n_good = n_hurt = 0

    for fold_i, holdout_date in enumerate(sorted_dates):
        hd = str(holdout_date)[:10]
        test_mask = date_arr == hd
        train_mask = ~test_mask
        n_test = int(test_mask.sum())
        if n_test == 0:
            continue

        X_train, y_train = X_all[train_mask], hit_arr[train_mask]
        X_test = X_all[test_mask]
        over_tr = ~um[train_mask]; under_tr = um[train_mask]
        over_te = ~um[test_mask];  under_te = um[test_mask]

        fold_preds = np.zeros(n_test, dtype=float)
        for seed in SEEDS:
            po = {**params_over, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
            pu = {**params_under, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
            if over_tr.sum() > 0 and over_te.sum() > 0:
                ds = lgb.Dataset(X_train[over_tr], label=y_train[over_tr],
                                 feature_name=FEATS, categorical_feature=CAT_IDX, free_raw_data=False)
                fold_preds[over_te] += lgb.train(po, ds, num_boost_round=n_rounds).predict(X_test[over_te])
            if under_tr.sum() > 0 and under_te.sum() > 0:
                ds = lgb.Dataset(X_train[under_tr], label=y_train[under_tr],
                                 feature_name=FEATS, categorical_feature=CAT_IDX, free_raw_data=False)
                fold_preds[under_te] += lgb.train(pu, ds, num_boost_round=n_rounds).predict(X_test[under_te])
        fold_preds /= len(SEEDS)
        oof_preds[test_mask] = fold_preds

        fold_brier = float(np.mean((fold_preds - hit_arr[test_mask]) ** 2))
        valid_so_far = ~np.isnan(oof_preds)
        running = float(np.mean((oof_preds[valid_so_far] - hit_arr[valid_so_far]) ** 2))

        # Compare to baseline raw for delta
        raw_brier = 0.250
        delta = (fold_brier - raw_brier) * 1000
        if delta < -1.0: n_good += 1
        elif delta > 1.0: n_hurt += 1

        print(f"  Fold {fold_i+1:2d}/{len(sorted_dates)}: {hd}  N={n_test:5d}  fold={fold_brier:.6f}  running={running:.6f}")

    # Temperature sweep
    valid = ~np.isnan(oof_preds)
    oof_logit = sp_logit(np.clip(oof_preds[valid], 0.001, 0.999))
    y_v = hit_arr[valid]
    best_brier, best_temp = 999.0, 1.0
    for T in TEMP_CANDIDATES:
        b = float(np.mean((sp_expit(oof_logit / T) - y_v) ** 2))
        if b < best_brier:
            best_brier, best_temp = b, T

    elapsed = time.time() - t0
    delta_vs_baseline = (best_brier - BASELINE_LODO) * 1000
    marker = "✅ IMPROVEMENT" if best_brier < BASELINE_LODO else "❌ REGRESSION"
    print(f"\n  → LODO Brier: {best_brier:.6f}  T={best_temp}  ({delta_vs_baseline:+.3f} mB vs baseline)  {marker}")
    print(f"  → Elapsed: {elapsed:.0f}s  |  Folds helped={n_good}  hurt={n_hurt}")
    return best_brier, best_temp, elapsed


# ── Run all configs ──────────────────────────────────────────────────
results = []
for cfg in CONFIGS:
    label, po, pu, nr = cfg
    brier, temp, elapsed = run_lodo_config(label, po, pu, nr)
    results.append((label, brier, temp, elapsed))

# ── Summary table ────────────────────────────────────────────────────
print(f"\n\n{'='*80}")
print("HYPERPARAMETER SWEEP RESULTS")
print(f"Baseline (production v17): {BASELINE_LODO:.6f}")
print(f"{'='*80}")
print(f"{'Config':<60} {'LODO Brier':>12} {'vs Base':>10} {'T':>5} {'Time':>7}")
print(f"{'-'*80}")
for label, brier, temp, elapsed in sorted(results, key=lambda x: x[1]):
    delta = (brier - BASELINE_LODO) * 1000
    marker = "✅" if brier < BASELINE_LODO else "  "
    print(f"{marker} {label:<58} {brier:.6f}  {delta:>+8.3f}mB  {temp:.2f}  {elapsed:>5.0f}s")
print(f"{'='*80}")

best_label, best_brier, best_temp, _ = min(results, key=lambda x: x[1])
if best_brier < BASELINE_LODO:
    print(f"\n🏆 BEST CONFIG: {best_label}")
    print(f"   LODO: {best_brier:.6f}  (saves {(BASELINE_LODO - best_brier)*1000:.3f} mB)")
    print(f"   Rerun with --promote to deploy:")
    print(f"   py Atlas\\tools\\gbm_v17_train.py --cache v17 --promote  [then edit PARAMS/N_ROUNDS to match]")
else:
    print(f"\nNo config beat baseline ({BASELINE_LODO:.6f}). Hyperparameters are well-tuned.")

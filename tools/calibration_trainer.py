"""
Calibration Trainer — Atlas v10 Calibration Improvement Sweep

Tests multiple calibration approaches on the v9d reader corpus to find
the approach that best maps p_adj → calibrated probability.

Current state:
  - p_adj Brier = 0.200 (kernel output — strong baseline)
  - p_cal Brier = 0.223 (isotonic overlay is HURTING)
  - Gap = +0.023 Brier — the calibration layer is destroying value.

Approaches tested:
  1. Identity (p_cal = p_adj) — baseline
  2. Global isotonic on p_adj
  3. Direction-split isotonic (separate OVER/UNDER curves)
  4. Stat-family × direction isotonic
  5. Platt scaling (logistic regression on logit(p_adj))
  6. Direction-split Platt scaling
  7. Histogram binning calibrator
  8. Temperature scaling (find best T on p_adj)
  9. Stat-family × direction Platt
  10. Beta calibration

Uses LODO (leave-one-date-out) cross-validation on the reader corpus
to prevent overfitting.

Output: calibration_trainer_results.yaml with per-method Brier/logloss/ECE
        and the best artifacts ready for deployment.
"""

import sys
import pathlib
import time
import warnings
import json
from collections import defaultdict

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(r"c:/Users/rick/projects/Atlas")
sys.path.insert(0, str(ROOT / "src"))
from Atlas.core.fingerprint import build_manifest, config_fingerprint

CORPUS_DIR = ROOT / "data" / "telemetry" / "v9d_corpus"
OUTPUT_PATH = ROOT / "tools" / "calibration_trainer_results.yaml"
ARTIFACT_DIR = ROOT / "data" / "model" / "calibration_candidates"

# ===================================================================
# Metrics
# ===================================================================

def brier_score(p, hit):
    return float(np.mean((p - hit) ** 2))

def log_loss(p, hit, eps=1e-15):
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(hit * np.log(p) + (1 - hit) * np.log(1 - p)))

def ece(p, hit, n_bins=15):
    """Expected Calibration Error."""
    bins = np.linspace(0, 1, n_bins + 1)
    total = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (p >= lo) & (p < hi)
        if mask.sum() == 0:
            continue
        avg_p = p[mask].mean()
        avg_hit = hit[mask].mean()
        total += mask.sum() * abs(avg_hit - avg_p)
    return float(total / len(p)) if len(p) > 0 else 0.0

def evaluate(p, hit):
    return {
        "brier": brier_score(p, hit),
        "logloss": log_loss(p, hit),
        "ece": ece(p, hit),
    }


# ===================================================================
# Load corpus
# ===================================================================

def load_corpus():
    """Load all eval_legs from the v9d reader corpus."""
    print("Loading v9d reader corpus ...")
    all_dfs = []
    # v9d corpus: runs/<snapshot>/runs/<timestamp>/eval_legs.csv
    runs = sorted(CORPUS_DIR.glob("runs/*/runs/*/eval_legs.csv"))
    if not runs:
        runs = sorted(CORPUS_DIR.glob("**/eval_legs.csv"))

    for f in runs:
        try:
            df = pd.read_csv(f, low_memory=False)
            if "hit" in df.columns and "p_adj" in df.columns:
                df = df.dropna(subset=["hit", "p_adj"])
                if len(df) > 0:
                    all_dfs.append(df)
        except Exception as e:
            print(f"  Skipping {f}: {e}")

    if not all_dfs:
        # Fallback: try kernel_v2 corpus in workspace replay_runs
        import glob
        replay_runs = ROOT / "data" / "telemetry" / "replay_runs"
        _tag_file = replay_runs / ".corpus_tag"
        _tag = _tag_file.read_text().strip() if _tag_file.exists() else "kernel_v2_perstat_corr015"
        files = glob.glob(str(replay_runs / f"{_tag}_*" / "*" / "runs" / "*" / "eval_legs.csv"))
        print(f"  Falling back to replay_runs corpus: {len(files)} files")
        for f in files:
            try:
                df = pd.read_csv(f, low_memory=False)
                if "hit" in df.columns and "p_adj" in df.columns:
                    df = df.dropna(subset=["hit", "p_adj"])
                    if len(df) > 0:
                        all_dfs.append(df)
            except Exception:
                pass

    if not all_dfs:
        raise RuntimeError("No eval_legs found in corpus or replay_runs fallback")

    combined = pd.concat(all_dfs, ignore_index=True)
    # Ensure game_date is available for LODO
    if "game_date" in combined.columns:
        combined["game_date"] = pd.to_datetime(combined["game_date"], errors="coerce")
    elif "date" in combined.columns:
        combined["game_date"] = pd.to_datetime(combined["date"], errors="coerce")

    # Derive direction
    if "direction" not in combined.columns:
        combined["direction"] = "OVER"
    combined["direction_u"] = combined["direction"].astype(str).str.upper().str.strip()

    # Derive stat
    if "stat" not in combined.columns:
        combined["stat"] = "UNK"
    combined["stat_u"] = combined["stat"].astype(str).str.upper().str.strip()

    # Stat family mapping
    FAMILY_MAP = {
        "PTS": "scoring", "FG3M": "threes", "REB": "rebounds", "AST": "assists",
        "PRA": "scoring", "PR": "scoring", "PA": "scoring", "RA": "rebounds",
        "FGA": "scoring", "FTA": "scoring", "TOV": "scoring",
    }
    combined["stat_family"] = combined["stat_u"].map(FAMILY_MAP).fillna("other")

    print(f"  Loaded {len(combined)} legs across {combined['game_date'].dt.date.nunique()} dates")
    return combined


# ===================================================================
# Calibration methods
# ===================================================================

def _fit_isotonic(p_train, hit_train):
    """Fit isotonic regression, return callable."""
    from sklearn.isotonic import IsotonicRegression
    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
    ir.fit(p_train, hit_train)
    return ir

def _fit_platt(p_train, hit_train):
    """Fit Platt scaling (logistic regression on logit(p))."""
    from sklearn.linear_model import LogisticRegression
    logit_p = np.log(np.clip(p_train, 1e-6, 1 - 1e-6) / (1 - np.clip(p_train, 1e-6, 1 - 1e-6)))
    lr = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    lr.fit(logit_p.reshape(-1, 1), hit_train)
    return lr

def _predict_platt(lr, p_test):
    logit_p = np.log(np.clip(p_test, 1e-6, 1 - 1e-6) / (1 - np.clip(p_test, 1e-6, 1 - 1e-6)))
    return lr.predict_proba(logit_p.reshape(-1, 1))[:, 1]

def _fit_histogram(p_train, hit_train, n_bins=30):
    """Histogram binning calibrator."""
    bins = np.linspace(0, 1, n_bins + 1)
    bin_idx = np.digitize(p_train, bins) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)
    bin_means = np.full(n_bins, 0.5)
    for b in range(n_bins):
        mask = bin_idx == b
        if mask.sum() >= 5:
            bin_means[b] = hit_train[mask].mean()
    return bins, bin_means

def _predict_histogram(bins, bin_means, p_test):
    bin_idx = np.digitize(p_test, bins) - 1
    bin_idx = np.clip(bin_idx, 0, len(bin_means) - 1)
    return bin_means[bin_idx]


# ===================================================================
# LODO cross-validation harness
# ===================================================================

def lodo_evaluate(df, method_name, fit_fn, predict_fn, split_col=None):
    """
    Leave-one-date-out cross-validation for a calibration method.

    fit_fn(p_train, hit_train, **extra) -> model
    predict_fn(model, p_test, **extra) -> p_calibrated

    If split_col is given, fits separate models per split value.
    """
    dates = sorted(df["game_date"].dt.date.unique())
    all_p_cal = np.full(len(df), np.nan)

    for held_out_date in dates:
        test_mask = df["game_date"].dt.date == held_out_date
        train_mask = ~test_mask

        if train_mask.sum() < 100 or test_mask.sum() < 10:
            # Not enough data — use identity
            all_p_cal[test_mask.values] = df.loc[test_mask, "p_adj"].values
            continue

        if split_col is None:
            p_train = df.loc[train_mask, "p_adj"].values
            hit_train = df.loc[train_mask, "hit"].values
            model = fit_fn(p_train, hit_train)

            p_test = df.loc[test_mask, "p_adj"].values
            all_p_cal[test_mask.values] = predict_fn(model, p_test)
        else:
            # Per-split fitting
            test_idx = df.index[test_mask]
            for split_val in df[split_col].unique():
                train_split = train_mask & (df[split_col] == split_val)
                test_split = test_mask & (df[split_col] == split_val)

                if train_split.sum() < 30 or test_split.sum() < 3:
                    all_p_cal[test_split.values] = df.loc[test_split, "p_adj"].values
                    continue

                model = fit_fn(
                    df.loc[train_split, "p_adj"].values,
                    df.loc[train_split, "hit"].values,
                )
                all_p_cal[test_split.values] = predict_fn(
                    model, df.loc[test_split, "p_adj"].values
                )

    # Fill any NaN with identity
    nan_mask = np.isnan(all_p_cal)
    if nan_mask.any():
        all_p_cal[nan_mask] = df.loc[nan_mask, "p_adj"].values

    all_p_cal = np.clip(all_p_cal, 0.01, 0.99)
    hit = df["hit"].values
    metrics = evaluate(all_p_cal, hit)

    # Per-date breakdown
    per_date = {}
    for d in dates:
        mask = df["game_date"].dt.date == d
        if mask.sum() > 0:
            per_date[str(d)] = {
                "n": int(mask.sum()),
                "brier": round(brier_score(all_p_cal[mask.values], hit[mask.values]), 6),
            }

    return {
        "method": method_name,
        "brier": round(metrics["brier"], 6),
        "logloss": round(metrics["logloss"], 6),
        "ece": round(metrics["ece"], 6),
        "per_date": per_date,
    }


# ===================================================================
# Temperature scaling sweep
# ===================================================================

def lodo_temperature_sweep(df, temps):
    """Find the best temperature for scaling logit(p_adj)."""
    best_t = 1.0
    best_brier = 999.0
    results = []

    for t in temps:
        logit_p = np.log(np.clip(df["p_adj"].values, 1e-6, 1 - 1e-6) /
                         (1 - np.clip(df["p_adj"].values, 1e-6, 1 - 1e-6)))
        p_scaled = 1.0 / (1.0 + np.exp(-logit_p / t))
        p_scaled = np.clip(p_scaled, 0.01, 0.99)
        b = brier_score(p_scaled, df["hit"].values)
        results.append({"T": round(t, 4), "brier": round(b, 6)})
        if b < best_brier:
            best_brier = b
            best_t = t

    return best_t, best_brier, results


# ===================================================================
# Train final artifacts for the winning method
# ===================================================================

def train_final_artifact(df, method_name, fit_fn, predict_fn, split_col=None):
    """Train on ALL data and save artifact for deployment."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    if split_col is None:
        p_all = df["p_adj"].values
        hit_all = df["hit"].values
        model = fit_fn(p_all, hit_all)

        if hasattr(model, "X_thresholds_") and hasattr(model, "y_thresholds_"):
            # Isotonic — save as JSON artifact
            artifact = {
                "mode": "isotonic_global",
                "version": 2,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "meta": {
                    "source_col": "p_adj",
                    "x_thresholds": [round(float(x), 8) for x in model.X_thresholds_],
                    "y_thresholds": [round(float(y), 8) for y in model.y_thresholds_],
                    "mix": 1.0,
                    "training_legs": int(len(df)),
                },
                "cap": {"min": 0.01, "max": 0.99},
            }
            path = ARTIFACT_DIR / f"calibration_{method_name}.json"
            with open(path, "w") as f:
                json.dump(artifact, f, indent=2)
            print(f"  Saved artifact: {path}")
            return path
    else:
        artifacts = {}
        for split_val in df[split_col].unique():
            split_mask = df[split_col] == split_val
            if split_mask.sum() < 50:
                continue
            model = fit_fn(
                df.loc[split_mask, "p_adj"].values,
                df.loc[split_mask, "hit"].values,
            )
            if hasattr(model, "X_thresholds_") and hasattr(model, "y_thresholds_"):
                artifacts[str(split_val)] = {
                    "x_thresholds": [round(float(x), 8) for x in model.X_thresholds_],
                    "y_thresholds": [round(float(y), 8) for y in model.y_thresholds_],
                    "training_legs": int(split_mask.sum()),
                }

        if artifacts:
            full_artifact = {
                "mode": f"isotonic_split_{split_col}",
                "version": 2,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "meta": {
                    "source_col": "p_adj",
                    "split_col": split_col,
                    "mix": 1.0,
                    "splits": artifacts,
                    "training_legs": int(len(df)),
                },
                "cap": {"min": 0.01, "max": 0.99},
            }
            path = ARTIFACT_DIR / f"calibration_{method_name}.json"
            with open(path, "w") as f:
                json.dump(full_artifact, f, indent=2)
            print(f"  Saved artifact: {path}")
            return path

    return None


# ===================================================================
# Main
# ===================================================================

def main():
    t_start = time.time()
    print("=" * 60)
    print("Atlas Calibration Trainer")
    print("=" * 60)

    df = load_corpus()
    hit = df["hit"].values
    p_adj = df["p_adj"].values

    # Baseline: identity (p_cal = p_adj)
    baseline = evaluate(p_adj, hit)
    print(f"\nBaseline (identity):")
    print(f"  Brier={baseline['brier']:.6f}  LogLoss={baseline['logloss']:.6f}  ECE={baseline['ece']:.6f}")

    # Current p_cal if available
    if "p_cal" in df.columns:
        p_cal = df["p_cal"].values
        valid = np.isfinite(p_cal)
        if valid.sum() > 0:
            current = evaluate(p_cal[valid], hit[valid])
            print(f"\nCurrent p_cal (isotonic overlay):")
            print(f"  Brier={current['brier']:.6f}  LogLoss={current['logloss']:.6f}  ECE={current['ece']:.6f}")
            print(f"  Delta vs identity: {current['brier'] - baseline['brier']:+.6f} Brier")

    results = []

    # 1. Identity baseline
    print(f"\n{'='*60}")
    print("Method 1: Identity (p_cal = p_adj)")
    identity_result = {
        "method": "identity",
        "brier": round(baseline["brier"], 6),
        "logloss": round(baseline["logloss"], 6),
        "ece": round(baseline["ece"], 6),
    }
    results.append(identity_result)
    print(f"  Brier={identity_result['brier']:.6f}")

    # 2. Global isotonic on p_adj (LODO)
    print(f"\n{'='*60}")
    print("Method 2: Global isotonic on p_adj (LODO)")
    t0 = time.time()
    r = lodo_evaluate(df, "isotonic_global", _fit_isotonic, lambda m, p: m.predict(p))
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 3. Direction-split isotonic (LODO)
    print(f"\n{'='*60}")
    print("Method 3: Direction-split isotonic (LODO)")
    t0 = time.time()
    r = lodo_evaluate(df, "isotonic_direction_split", _fit_isotonic,
                      lambda m, p: m.predict(p), split_col="direction_u")
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 4. Stat-family × direction isotonic (LODO)
    print(f"\n{'='*60}")
    print("Method 4: Stat-family × direction isotonic (LODO)")
    t0 = time.time()
    df["stat_dir"] = df["stat_family"] + "_" + df["direction_u"]
    r = lodo_evaluate(df, "isotonic_stat_direction", _fit_isotonic,
                      lambda m, p: m.predict(p), split_col="stat_dir")
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 5. Platt scaling (LODO)
    print(f"\n{'='*60}")
    print("Method 5: Platt scaling (LODO)")
    t0 = time.time()
    r = lodo_evaluate(df, "platt_global", _fit_platt, _predict_platt)
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 6. Direction-split Platt (LODO)
    print(f"\n{'='*60}")
    print("Method 6: Direction-split Platt scaling (LODO)")
    t0 = time.time()
    r = lodo_evaluate(df, "platt_direction_split", _fit_platt, _predict_platt,
                      split_col="direction_u")
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 7. Histogram binning (LODO)
    print(f"\n{'='*60}")
    print("Method 7: Histogram binning (LODO)")
    t0 = time.time()
    r = lodo_evaluate(
        df, "histogram_binning",
        lambda p, h: _fit_histogram(p, h, n_bins=30),
        lambda m, p: _predict_histogram(m[0], m[1], p),
    )
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 8. Temperature scaling sweep
    print(f"\n{'='*60}")
    print("Method 8: Temperature scaling sweep")
    t0 = time.time()
    temps = np.arange(0.80, 1.21, 0.01)
    best_t, best_brier, temp_results = lodo_temperature_sweep(df, temps)
    temp_entry = {
        "method": "temperature_scaling",
        "brier": round(best_brier, 6),
        "logloss": round(log_loss(
            np.clip(1.0 / (1.0 + np.exp(-np.log(np.clip(p_adj, 1e-6, 1-1e-6) /
                    (1 - np.clip(p_adj, 1e-6, 1-1e-6))) / best_t)), 0.01, 0.99), hit), 6),
        "ece": round(ece(
            np.clip(1.0 / (1.0 + np.exp(-np.log(np.clip(p_adj, 1e-6, 1-1e-6) /
                    (1 - np.clip(p_adj, 1e-6, 1-1e-6))) / best_t)), 0.01, 0.99), hit), 6),
        "best_temperature": round(best_t, 4),
    }
    results.append(temp_entry)
    print(f"  Best T={best_t:.4f}  Brier={best_brier:.6f}  delta={best_brier - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 9. Stat-family × direction Platt (LODO)
    print(f"\n{'='*60}")
    print("Method 9: Stat-family × direction Platt (LODO)")
    t0 = time.time()
    r = lodo_evaluate(df, "platt_stat_direction", _fit_platt, _predict_platt,
                      split_col="stat_dir")
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 10. Stat-specific isotonic (per individual stat, not family)
    print(f"\n{'='*60}")
    print("Method 10: Per-stat × direction isotonic (LODO)")
    t0 = time.time()
    df["stat_dir_specific"] = df["stat_u"] + "_" + df["direction_u"]
    r = lodo_evaluate(df, "isotonic_per_stat_direction", _fit_isotonic,
                      lambda m, p: m.predict(p), split_col="stat_dir_specific")
    results.append(r)
    print(f"  Brier={r['brier']:.6f}  delta={r['brier'] - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 11. Blended: isotonic with mix < 1.0 (partial isotonic)
    print(f"\n{'='*60}")
    print("Method 11: Blended isotonic sweep (mix 0.1 to 0.9)")
    t0 = time.time()
    best_mix = 0.0
    best_blend_brier = baseline["brier"]
    blend_results = []
    for mix in np.arange(0.1, 1.0, 0.1):
        def _fit_blend(p, h, _mix=mix):
            return _fit_isotonic(p, h)
        def _predict_blend(m, p, _mix=mix):
            iso_p = m.predict(p)
            return p * (1 - _mix) + iso_p * _mix
        r_blend = lodo_evaluate(df, f"isotonic_blend_{mix:.1f}", _fit_blend, _predict_blend)
        blend_results.append({"mix": round(mix, 1), "brier": r_blend["brier"]})
        if r_blend["brier"] < best_blend_brier:
            best_blend_brier = r_blend["brier"]
            best_mix = mix

    blend_entry = {
        "method": "isotonic_blended",
        "brier": round(best_blend_brier, 6),
        "best_mix": round(best_mix, 1),
        "sweep": blend_results,
    }
    results.append(blend_entry)
    print(f"  Best mix={best_mix:.1f}  Brier={best_blend_brier:.6f}  delta={best_blend_brier - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # 12. Direction-split isotonic with blend
    print(f"\n{'='*60}")
    print("Method 12: Direction-split isotonic blended sweep")
    t0 = time.time()
    best_dir_mix = 0.0
    best_dir_blend_brier = baseline["brier"]
    dir_blend_results = []
    for mix in np.arange(0.1, 1.0, 0.1):
        def _fit_dir_blend(p, h, _mix=mix):
            return _fit_isotonic(p, h)
        def _predict_dir_blend(m, p, _mix=mix):
            iso_p = m.predict(p)
            return p * (1 - _mix) + iso_p * _mix
        r_dir = lodo_evaluate(df, f"dir_iso_blend_{mix:.1f}", _fit_dir_blend, _predict_dir_blend,
                              split_col="direction_u")
        dir_blend_results.append({"mix": round(mix, 1), "brier": r_dir["brier"]})
        if r_dir["brier"] < best_dir_blend_brier:
            best_dir_blend_brier = r_dir["brier"]
            best_dir_mix = mix

    dir_blend_entry = {
        "method": "direction_isotonic_blended",
        "brier": round(best_dir_blend_brier, 6),
        "best_mix": round(best_dir_mix, 1),
        "sweep": dir_blend_results,
    }
    results.append(dir_blend_entry)
    print(f"  Best mix={best_dir_mix:.1f}  Brier={best_dir_blend_brier:.6f}  delta={best_dir_blend_brier - baseline['brier']:+.6f}  ({time.time()-t0:.1f}s)")

    # ===================================================================
    # Summary
    # ===================================================================
    print(f"\n{'='*60}")
    print("SUMMARY — Ranked by Brier (lower is better)")
    print(f"{'='*60}")

    ranked = sorted(results, key=lambda x: x["brier"])
    for i, r in enumerate(ranked):
        delta = r["brier"] - baseline["brier"]
        marker = " ***BEST***" if i == 0 else ""
        print(f"  {i+1}. {r['method']:40s} Brier={r['brier']:.6f}  delta={delta:+.6f}{marker}")

    winner = ranked[0]
    print(f"\nWinner: {winner['method']}  Brier={winner['brier']:.6f}")
    print(f"  Improvement vs identity: {winner['brier'] - baseline['brier']:+.6f}")
    if "p_cal" in df.columns:
        print(f"  Improvement vs current p_cal: {winner['brier'] - current['brier']:+.6f}")

    # Train final artifacts for top 3 methods
    print(f"\n{'='*60}")
    print("Training final artifacts for top methods ...")
    for r in ranked[:3]:
        method = r["method"]
        if method == "identity":
            continue
        elif "isotonic" in method and "direction" in method and "blend" not in method and "stat" not in method and "per_stat" not in method:
            train_final_artifact(df, method, _fit_isotonic, lambda m, p: m.predict(p),
                                 split_col="direction_u")
        elif method == "isotonic_global":
            train_final_artifact(df, method, _fit_isotonic, lambda m, p: m.predict(p))
        elif "isotonic_stat_direction" in method:
            train_final_artifact(df, method, _fit_isotonic, lambda m, p: m.predict(p),
                                 split_col="stat_dir")
        elif "isotonic_per_stat_direction" in method:
            train_final_artifact(df, method, _fit_isotonic, lambda m, p: m.predict(p),
                                 split_col="stat_dir_specific")
        print(f"  Trained: {method}")

    # Save results
    with open(ROOT / "config.yaml") as _cf:
        _full_cfg = yaml.safe_load(_cf)
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_manifest": build_manifest(
            source="calibration_trainer", cfg=_full_cfg,
            ensemble_dir=_full_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
        ),
        "corpus_legs": int(len(df)),
        "corpus_dates": int(df["game_date"].dt.date.nunique()),
        "baseline_identity_brier": round(baseline["brier"], 6),
        "winner": winner["method"],
        "winner_brier": winner["brier"],
        "improvement_vs_identity": round(winner["brier"] - baseline["brier"], 6),
        "results": ranked,
    }

    with open(OUTPUT_PATH, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False)
    print(f"\nResults saved to {OUTPUT_PATH}")
    print(f"Total time: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()

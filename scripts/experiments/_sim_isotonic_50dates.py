"""
Simulate post-GBM isotonic overlay across all 50 v18 resim cache dates.
Applies telemetry_calibration.v18_post_gbm.json to p_cal in-memory.
Reports before/after Brier, calibration tiers, DEMON breakdown, per-date deltas.
"""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\13142\Atlas\Atlas")
CACHE_PATH = ROOT / "data/model/_v18_resim_cache.pkl"
CAL_PATH = ROOT / "data/model/telemetry_calibration.v18_post_gbm.json"

# ── Load ──────────────────────────────────────────────────────────────────────
with open(CACHE_PATH, "rb") as f:
    cache = pickle.load(f)
cv = cache["cv"].copy()

with open(CAL_PATH) as f:
    cal = json.load(f)

meta = cal["meta"]
main_x = np.array(meta["x_thresholds"])
main_y = np.array(meta["y_thresholds"])
demon_x = np.array(meta["protected_calibration"]["x_thresholds"])
demon_y = np.array(meta["protected_calibration"]["y_thresholds"])

print(f"Cache: {len(cv)} legs, {cv['game_date'].nunique()} dates")
print(f"Calibration: main curve={len(main_x)}pts, DEMON curve={len(demon_x)}pts")
print(f"p_cal non-null: {cv['p_cal'].notna().sum()}, hit non-null: {cv['hit'].notna().sum()}")

# ── Apply isotonic ────────────────────────────────────────────────────────────
def apply_isotonic(p_series: pd.Series, x_pts: np.ndarray, y_pts: np.ndarray) -> pd.Series:
    """Piecewise linear isotonic interpolation."""
    return pd.Series(np.interp(p_series.values, x_pts, y_pts), index=p_series.index)

valid = cv.dropna(subset=["p_cal", "hit"]).copy()
is_demon = valid["tier"].str.upper() == "DEMON" if "tier" in valid.columns else pd.Series(False, index=valid.index)

valid["p_iso"] = valid["p_cal"].copy()
valid.loc[is_demon, "p_iso"] = apply_isotonic(valid.loc[is_demon, "p_cal"], demon_x, demon_y)
valid.loc[~is_demon, "p_iso"] = apply_isotonic(valid.loc[~is_demon, "p_cal"], main_x, main_y)

# ── Overall metrics ───────────────────────────────────────────────────────────
brier_before = float(((valid["p_cal"] - valid["hit"]) ** 2).mean())
brier_after  = float(((valid["p_iso"] - valid["hit"]) ** 2).mean())

try:
    from sklearn.metrics import roc_auc_score
    auc_before = round(roc_auc_score(valid["hit"], valid["p_cal"]), 4)
    auc_after  = round(roc_auc_score(valid["hit"], valid["p_iso"]), 4)
except Exception:
    auc_before = auc_after = "N/A"

print(f"\n{'='*60}")
print(f"  ALL 50 DATES — N={len(valid)}")
print(f"{'='*60}")
print(f"  {'Metric':<20} {'Before (GBM)':>14}  {'After (iso)':>12}  {'Delta':>10}")
print(f"  {'-'*58}")
print(f"  {'Brier':<20} {brier_before:>14.6f}  {brier_after:>12.6f}  {brier_after-brier_before:>+10.6f}")
print(f"  {'AUC':<20} {str(auc_before):>14}  {str(auc_after):>12}")
print(f"  {'Mean p_cal':<20} {valid['p_cal'].mean():>14.4f}  {valid['p_iso'].mean():>12.4f}")
print(f"  {'Actual hit rate':<20} {valid['hit'].mean():>14.4f}")

# ── DEMON vs non-DEMON ────────────────────────────────────────────────────────
print(f"\n  {'Segment':<14} {'N':>7}  {'Brier Before':>13}  {'Brier After':>12}  {'Delta':>9}")
print(f"  {'-'*58}")
for name, mask in [("DEMON", is_demon), ("non-DEMON", ~is_demon)]:
    seg = valid[mask]
    if len(seg) == 0:
        continue
    bb = float(((seg["p_cal"] - seg["hit"]) ** 2).mean())
    ba = float(((seg["p_iso"] - seg["hit"]) ** 2).mean())
    print(f"  {name:<14} N={len(seg):>6}  {bb:>13.6f}  {ba:>12.6f}  {ba-bb:>+9.6f}")

# ── DEMON calibration buckets ─────────────────────────────────────────────────
demon_df = valid[is_demon].copy()
bins   = [0, 0.20, 0.30, 0.40, 0.50, 0.55, 0.60, 0.70, 1.0]
labels = ["0.00-0.20","0.20-0.30","0.30-0.40","0.40-0.50","0.50-0.55","0.55-0.60","0.60-0.70","0.70-1.00"]

demon_df["bucket_before"] = pd.cut(demon_df["p_cal"], bins=bins, labels=labels)
demon_df["bucket_after"]  = pd.cut(demon_df["p_iso"], bins=bins, labels=labels)

print(f"\n  DEMON calibration buckets — BEFORE isotonic (all 50 dates, N={len(demon_df)}):")
print(f"  {'Bucket':<12} {'N':>6}  {'Model':>7}  {'Actual':>7}  {'Gap':>8}")
grp = demon_df.groupby("bucket_before", observed=False).agg(
    N=("hit","count"), model_p=("p_cal","mean"), actual=("hit","mean")).reset_index()
grp["gap"] = grp["actual"] - grp["model_p"]
for _, r in grp.iterrows():
    if r["N"] > 0:
        mark = "  *** SEVERE" if abs(r["gap"]) > 0.15 else ""
        print(f"  {str(r['bucket_before']):<12}  N={r['N']:>6}  {r['model_p']:.3f}   {r['actual']:.3f}   {r['gap']:+.3f}{mark}")

print(f"\n  DEMON calibration buckets — AFTER isotonic:")
print(f"  {'Bucket':<12} {'N':>6}  {'Model':>7}  {'Actual':>7}  {'Gap':>8}")
grp2 = demon_df.groupby("bucket_after", observed=False).agg(
    N=("hit","count"), model_p=("p_iso","mean"), actual=("hit","mean")).reset_index()
grp2["gap"] = grp2["actual"] - grp2["model_p"]
for _, r in grp2.iterrows():
    if r["N"] > 0:
        mark = "  *** SEVERE" if abs(r["gap"]) > 0.15 else ""
        print(f"  {str(r['bucket_after']):<12}  N={r['N']:>6}  {r['model_p']:.3f}   {r['actual']:.3f}   {r['gap']:+.3f}{mark}")

# ── Per-date Brier delta ──────────────────────────────────────────────────────
print(f"\n  Per-date Brier delta (before → after → delta):")
print(f"  {'Date':<12} {'N':>5}  {'Before':>8}  {'After':>8}  {'Delta':>9}")
print(f"  {'-'*48}")
per_date = valid.groupby("game_date").apply(
    lambda x: pd.Series({
        "N": len(x),
        "before": float(((x["p_cal"] - x["hit"])**2).mean()),
        "after":  float(((x["p_iso"] - x["hit"])**2).mean()),
    })
).reset_index()
per_date["delta"] = per_date["after"] - per_date["before"]
per_date = per_date.sort_values("game_date")
for _, r in per_date.iterrows():
    mark = " <-- REGRESSION" if r["delta"] > 0.002 else ""
    print(f"  {r['game_date']:<12} N={r['N']:>4}  {r['before']:.6f}  {r['after']:.6f}  {r['delta']:>+9.6f}{mark}")

n_improve = (per_date["delta"] < 0).sum()
n_regress = (per_date["delta"] > 0.002).sum()
print(f"\n  Improved dates:   {n_improve} / {len(per_date)}")
print(f"  Regressed dates (>+0.002): {n_regress} / {len(per_date)}")
print(f"  Mean per-date delta: {per_date['delta'].mean():+.6f}")
print(f"  Worst regression:    {per_date['delta'].max():+.6f} ({per_date.loc[per_date['delta'].idxmax(),'game_date']})")
print(f"  Best improvement:    {per_date['delta'].min():+.6f} ({per_date.loc[per_date['delta'].idxmin(),'game_date']})")

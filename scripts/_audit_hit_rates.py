"""Audit hit rates from resim cache + live telemetry runs for slip builder analysis."""
import os, pickle, sys
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 1. Resim cache (training corpus) ────────────────────────────────────────
import glob as _glob
_candidates = sorted(_glob.glob(str(ROOT / "data/model/_v*resim_cache.pkl")), reverse=True)
cache_path = Path(_candidates[0]) if _candidates else ROOT / "data/model/_v12_resim_cache.pkl"
print(f"Using cache: {cache_path.name}")
if not cache_path.exists():
    print("ERROR: No resim cache")
    sys.exit(1)

with open(cache_path, "rb") as f:
    cache = pickle.load(f)

cv = cache["cv"]
dates = cache["dates"]
print(f"=== RESIM CACHE: {len(dates)} dates, {len(cv)} legs ===")

if "hit" not in cv.columns:
    print("No 'hit' column in resim cache")
    sys.exit(1)

print(f"\nOverall hit rate: {cv['hit'].mean():.4f}  (N={len(cv)})")

print("\nBy direction:")
print(cv.groupby("direction")["hit"].agg(["mean","count"]).rename(columns={"mean":"hit_rate","count":"n"}).to_string())

print("\nBy tier:")
print(cv.groupby("tier")["hit"].agg(["mean","count"]).rename(columns={"mean":"hit_rate","count":"n"}).sort_values("hit_rate", ascending=False).to_string())

print("\nBy stat:")
print(cv.groupby("stat")["hit"].agg(["mean","count"]).rename(columns={"mean":"hit_rate","count":"n"}).sort_values("hit_rate", ascending=False).to_string())

print("\nBy direction x tier:")
print(cv.groupby(["direction","tier"])["hit"].agg(["mean","count"]).rename(columns={"mean":"hit_rate","count":"n"}).sort_values("hit_rate", ascending=False).to_string())

# ── 2. Calibration vs actuals — p_cal buckets ───────────────────────────────
if "p_cal" in cv.columns:
    print("\n=== CALIBRATION CHECK: p_cal vs actual hit rate (deciles) ===")
    cv2 = cv.copy()
    cv2["p_cal_f"] = pd.to_numeric(cv2["p_cal"], errors="coerce")
    cv2 = cv2.dropna(subset=["p_cal_f"])
    cv2["p_bucket"] = pd.cut(cv2["p_cal_f"], bins=[0,.45,.50,.55,.60,.65,.70,.75,.80,.85,.90,1.0])
    cal = cv2.groupby("p_bucket")["hit"].agg(["mean","count"]).rename(columns={"mean":"actual_hr","count":"n"})
    cal["model_mid"] = [(b.left+b.right)/2 for b in cal.index]
    cal["gap"] = cal["actual_hr"] - cal["model_mid"]
    print(cal.to_string())

# ── 3. Live telemetry runs — slip win rates ──────────────────────────────────
telem_dir = ROOT / "data/telemetry/live_runs"
if telem_dir.exists():
    slip_records = []
    for run_dir in sorted(telem_dir.iterdir()):
        for fam in ["system_3leg", "system_4leg", "system_5leg", "windfall_3leg", "windfall_4leg", "windfall_5leg"]:
            p = run_dir / f"{fam}.csv"
            if not p.exists():
                continue
            df = pd.read_csv(p)
            if "hit_prob" in df.columns and len(df):
                top = df.sort_values("ev_mult", ascending=False).head(1)
                slip_records.append({
                    "run": run_dir.name,
                    "family": fam,
                    "top1_hit_prob": float(top["hit_prob"].iloc[0]),
                    "top1_ev": float(top["ev_mult"].iloc[0]) if "ev_mult" in top.columns else None,
                    "n_slips": len(df),
                })
    if slip_records:
        sdf = pd.DataFrame(slip_records)
        print("\n=== LIVE TELEMETRY: avg top-1 hit_prob by family (last 20 runs) ===")
        print(sdf.groupby("family")["top1_hit_prob"].agg(["mean","min","max","count"]).sort_values("mean", ascending=False).to_string())
    else:
        print("\nNo live telemetry slip CSVs found")
else:
    print("\nNo live telemetry dir")

# ── 4. Per-leg probability distribution for builder legs (today's run) ──────
runs_dir = ROOT / "data/output/runs"
if runs_dir.exists():
    run_dirs = sorted(runs_dir.iterdir(), reverse=True)
    for rd in run_dirs[:1]:
        sl_path = rd / "scored_legs_deduped.csv"
        if sl_path.exists():
            sl = pd.read_csv(sl_path)
            print(f"\n=== TODAY ({rd.name}): {len(sl)} scored legs ===")
            if "p_cal" in sl.columns and "tier" in sl.columns:
                print(sl.groupby("tier")["p_cal"].agg(["mean","median","count"]).rename(columns={"mean":"p_cal_mean","median":"p_cal_median","count":"n"}).to_string())
            if "p_cal" in sl.columns and "direction" in sl.columns:
                print(sl.groupby("direction")["p_cal"].agg(["mean","median","count"]).to_string())

print("\nDone.")

import pandas as pd, numpy as np

runs = {
    "5/7": "data/telemetry/replay_runs/series_mult_L10_20260507/20260509_223524/runs/20260509_173847/eval_legs.csv",
    "5/8": "data/telemetry/replay_runs/series_mult_L10_20260508/20260509_223932/runs/20260509_174304/eval_legs.csv",
}

for label, path in runs.items():
    df = pd.read_csv(path, low_memory=False)
    df = df[df["hit"].isin([0, 1])].copy()
    for col in ["p_adj", "p_for_cal", "p_cal", "hit"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["hit"])
    n = len(df)
    hr = float(df["hit"].mean())
    b_adj     = float(((df["p_adj"]     - df["hit"])**2).mean())
    b_for_cal = float(((df["p_for_cal"] - df["hit"])**2).mean())
    b_cal     = float(((df["p_cal"]     - df["hit"])**2).mean())
    print(f"=== {label} ===  {n} legs  actual_HR={hr:.3f}")
    print(f"  p_adj     (MC raw):  {b_adj:.6f}")
    print(f"  p_for_cal (priors):  {b_for_cal:.6f}")
    print(f"  p_cal     (isotonic):{b_cal:.6f}  delta_vs_adj={b_cal-b_adj:+.6f}")
    for d in ["OVER", "UNDER"]:
        sub = df[df["direction"].astype(str).str.upper() == d]
        if sub.empty:
            continue
        ba = float(((sub["p_adj"] - sub["hit"])**2).mean())
        bc = float(((sub["p_cal"] - sub["hit"])**2).mean())
        act = float(sub["hit"].mean())
        mavg = float(sub["p_cal"].mean())
        print(f"    {d} ({len(sub)} legs): p_adj={ba:.6f}  p_cal={bc:.6f}  actual_hr={act:.3f}  model_avg={mavg:.3f}")
    print()

import pandas as pd, numpy as np, sys
from pathlib import Path

base = Path(sys.argv[1])

def _find(name):
    hits = list(base.rglob(name))
    if not hits:
        raise FileNotFoundError(f"{name} not found under {base}")
    return sorted(hits)[-1]  # latest if multiple

el = pd.read_csv(_find("eval_legs.csv"))
sl = pd.read_csv(_find("scored_legs_deduped.csv"))

print(f"=== {base.name} ===")
n = len(el)
hr = float(el["hit"].mean())
b_base = float(np.mean((el["p_for_cal"] - el["hit"])**2))
b_cal  = float(np.mean((el["p_cal"]     - el["hit"])**2))
print(f"  n={n}, hit_rate={hr:.4f}")
print(f"  Brier(p_for_cal) = {b_base:.6f}")
print(f"  Brier(p_cal)     = {b_cal:.6f}  ({1000*(b_cal-b_base):+.2f} mB vs baseline)")

if "p_catboost" in sl.columns:
    cnt = int(sl["p_catboost"].notna().sum())
    mp = float(sl["p_catboost"].mean())
    mc = float(sl["p_cal"].mean())
    mf = float(sl["p_for_cal"].mean())
    print(f"  p_catboost: {cnt}/{len(sl)} rows, mean={mp:.4f}")
    print(f"  mean p_for_cal={mf:.4f} -> p_catboost={mp:.4f} -> p_cal={mc:.4f}")
else:
    print("  WARNING: p_catboost NOT in scored_legs_deduped")

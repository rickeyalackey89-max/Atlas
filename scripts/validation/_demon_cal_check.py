import pickle
import pandas as pd
import numpy as np

cache = pickle.load(open("data/model/_v17_resim_cache.pkl", "rb"))
df = cache["cv"]

demon = df[df["tier"] == "DEMON"].copy()
print(f"DEMON rows: {len(demon)}")
print(f"DEMON hit rate:  {demon['hit'].mean():.3f}")
print(f"DEMON p_cal mean: {demon['p_cal'].mean():.3f}")
print(f"DEMON p_adj mean: {demon['p_adj'].mean():.3f}")

over  = demon[demon["direction"] == "OVER"]
under = demon[demon["direction"] == "UNDER"]
print(f"\nOVER  n={len(over):5d}  hit={over['hit'].mean():.3f}  p_cal={over['p_cal'].mean():.3f}")
print(f"UNDER n={len(under):5d}  hit={under['hit'].mean():.3f}  p_cal={under['p_cal'].mean():.3f}")

# Calibration gap by bucket
print("\nCalibration gap by p_cal bucket (DEMON all):")
demon["bucket"] = pd.cut(demon["p_cal"], bins=[0,.35,.45,.55,.65,.75,.85,1.0])
summary = demon.groupby("bucket", observed=True).agg(
    n=("hit","count"), actual=("hit","mean"), model=("p_cal","mean")
)
summary["gap"] = summary["actual"] - summary["model"]
print(summary.to_string())

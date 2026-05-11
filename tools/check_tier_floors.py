"""One-off: compute per-tier top-N p_cal floors across the v18 resim cache."""
import pandas as pd
import pickle

with open("data/model/_v18_resim_cache.pkl", "rb") as f:
    cache = pickle.load(f)
cv = cache["cv"]

print(f"Dates: {len(cv['game_date'].unique())}  |  Legs: {len(cv)}")
print()

rows = []
for date, grp in cv.groupby("game_date"):
    row = {"date": date}
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        t = grp[grp["tier"] == tier].sort_values("p_cal", ascending=False).reset_index(drop=True)
        n = len(t)
        row[tier + "_n"] = n
        row[tier + "_top15"] = round(t["p_cal"].iloc[min(14, n - 1)], 3) if n > 0 else None
        row[tier + "_top10"] = round(t["p_cal"].iloc[min(9,  n - 1)], 3) if n > 0 else None
    rows.append(row)

df = pd.DataFrame(rows)

for label, suffix in [("top-15", "_top15"), ("top-10", "_top10")]:
    print(f"Per-tier {label} floor across {len(df)} dates:")
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        col = tier + suffix
        s = df[col].dropna()
        avg_n = int(df[tier + "_n"].mean())
        print(
            f"  {tier:8s}: min={s.min():.3f}  p10={s.quantile(0.10):.3f}"
            f"  median={s.median():.3f}  p90={s.quantile(0.90):.3f}"
            f"  max={s.max():.3f}  avg_n={avg_n}"
        )
    print()

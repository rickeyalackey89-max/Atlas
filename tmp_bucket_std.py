import pandas as pd
import numpy as np
from pathlib import Path

runs_dir = Path("data/output/runs")
runs = sorted([p for p in runs_dir.glob("*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
r = runs[0]
df = pd.read_csv(r / "scored_legs.csv")

print("run", r.name)
print("has_games_used_col", "games_used" in df.columns)

# show likely candidates
cands = [c for c in df.columns if "game" in c.lower()]
print("game-ish cols:", cands[:25])

if "games_used" not in df.columns:
    print("No 'games_used' column available; cannot bucket by games_used.")
    raise SystemExit(0)

g = pd.to_numeric(df["games_used"], errors="coerce")
ms = pd.to_numeric(df.get("min_std", np.nan), errors="coerce")
rs = pd.to_numeric(df.get("rate_std", np.nan), errors="coerce")

print("\nmin_std==0 by games_used bucket")
for a, b in [(0, 4), (5, 8), (9, 15), (16, 999)]:
    bucket = (g >= a) & (g <= b)
    denom = int(bucket.sum())
    cnt = int((bucket & (ms == 0)).sum())
    print(a, b, cnt, "of", denom)

print("\nrate_std<=0.01 by games_used bucket")
for a, b in [(0, 4), (5, 8), (9, 15), (16, 999)]:
    bucket = (g >= a) & (g <= b)
    denom = int(bucket.sum())
    cnt = int((bucket & (rs <= 0.01)).sum())
    print(a, b, cnt, "of", denom)
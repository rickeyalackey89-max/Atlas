import pandas as pd

p = r"data/output/runs/20260228_200900/scored_legs.csv"
df = pd.read_csv(p)

need = ["player", "stat", "direction", "tier", "line", "p_adj"]
miss = [c for c in need if c not in df.columns]
print("missing_cols:", miss)

df = df.dropna(subset=["player", "stat", "direction", "tier", "line"])

out = []
for (player, stat, direction), sub in df.groupby(["player", "stat", "direction"]):
    if sub["line"].nunique() < 2:
        continue
    if sub["p_adj"].nunique() != 1:
        continue

    val = float(sub["p_adj"].iloc[0])
    # ignore clamp collisions
    if val <= 0.031 or val >= 0.969:
        continue

    out.append((player, stat, direction, int(sub["tier"].nunique()), int(sub["line"].nunique()), val))

print("suspicious_groups:", len(out))
out = sorted(out, key=lambda x: (-x[4], x[0]))[:25]
for r in out:
    print(r)
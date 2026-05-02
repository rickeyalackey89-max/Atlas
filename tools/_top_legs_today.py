import pandas as pd

df = pd.read_csv(r"data/output/runs/20260501_080424/scored_legs_deduped.csv")
df = df[df["p_cal"].notna()]

# For each player keep only their single highest p_cal leg
df_best = (
    df.sort_values("p_cal", ascending=False)
    .drop_duplicates(subset=["player"], keep="first")
    .sort_values("p_cal", ascending=False)
    .head(25)
)

print(f"{'#':<3} {'PLAYER':<28} {'TIER':<8} {'STAT':<8} {'LINE':>6}  {'DIR':<6}  {'P_CAL':>7}  {'P_ADJ':>7}  {'BLOWOUT':>8}")
print("-" * 95)
for i, (_, r) in enumerate(df_best.iterrows(), 1):
    print(
        f"{i:<3} {r['player']:<28} {r['tier']:<8} {r['stat']:<8} {r['line']:>6}  "
        f"{r['direction']:<6}  {r['p_cal']*100:>6.1f}%  {r['p_adj']*100:>6.1f}%  {r['q_blowout']:>8.3f}"
    )

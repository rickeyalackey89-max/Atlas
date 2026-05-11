"""Item 4 — blowout curve diagnostic. Where in q_blowout does p_adj help/hurt?"""
import pickle
import numpy as np
import pandas as pd

cv = pickle.load(open("data/model/_v1_playoff_resim_cache.pkl", "rb"))["cv"]
cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
cv["hit_f"] = cv["hit"].astype(float)
cv["q"] = pd.to_numeric(cv["q_blowout"], errors="coerce")
cv["p_pre"] = pd.to_numeric(cv.get("p_role"), errors="coerce").fillna(cv["p_adj_f"])

bins = [(0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
        (0.20, 0.30), (0.30, 0.50), (0.50, 1.01)]
print(f"{'q_range':<14} {'n':>5} {'mean_p':>8} {'hit':>8} {'gap_pp':>8}  "
      f"{'B_pre':>8} {'B_post':>8} {'delta_mB':>9}")
for lo, hi in bins:
    m = (cv["q"] >= lo) & (cv["q"] < hi)
    if m.sum() < 30:
        continue
    mp = cv.loc[m, "p_adj_f"].mean()
    mh = cv.loc[m, "hit_f"].mean()
    gap = (mh - mp) * 100
    b_pre = ((cv.loc[m, "p_pre"] - cv.loc[m, "hit_f"]) ** 2).mean()
    b_post = ((cv.loc[m, "p_adj_f"] - cv.loc[m, "hit_f"]) ** 2).mean()
    print(f"[{lo:.2f},{hi:.2f})    {m.sum():>5} {mp:>8.3f} {mh:>8.3f} "
          f"{gap:>+7.2f}pp {b_pre:>8.4f} {b_post:>8.4f} {(b_post-b_pre)*1000:>+8.2f}mB")

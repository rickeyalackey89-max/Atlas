"""Compute Brier on the two v5cD smoke replays."""
import pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TAG = "atlas_replay_v5cD_smoke_20260510_144329"

cache = pickle.load(open(ROOT/"data/model/_v1_playoff_resim_cache.pkl", "rb"))
cv = cache["cv"]


def brier(y, p):
    return float(np.mean((p - y) ** 2))


hdr = (f"{'date':<10} {'n':>5} {'p_adj':>10} {'p_cal':>10} {'p_catbst':>10} "
       f"{'cal-adj_mB':>11} {'cache_padj':>11} {'cache_pcal':>11}")
print(hdr)
print("-" * len(hdr))

for date in ["20260505", "20260507"]:
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    base = ROOT / "data" / "telemetry" / "replay_runs" / f"{TAG}_{date}" / "runs"
    run = sorted(base.glob("*"))[-1]
    ev = pd.read_csv(run / "eval_legs.csv")
    m = ev.dropna(subset=["hit", "p_cal", "p_adj"])
    m = m[m["hit"].isin([0, 1, 0.0, 1.0])]
    y = m["hit"].astype(float)
    bp = brier(y, m["p_adj"].astype(float))
    bc = brier(y, m["p_cal"].astype(float))
    bcat = brier(y, m["p_catboost"].astype(float)) if "p_catboost" in m.columns else float("nan")
    sub = cv[cv["game_date"].astype(str).str[:10] == iso]
    cbp = brier(sub["hit"].astype(float), sub["p_adj"].astype(float)) if len(sub) else float("nan")
    cbc = brier(sub["hit"].astype(float), sub["p_cal"].astype(float)) if "p_cal" in sub.columns and len(sub) else float("nan")
    print(f"{date:<10} {len(m):>5} {bp:>10.6f} {bc:>10.6f} {bcat:>10.6f} "
          f"{(bc-bp)*1000:>+11.2f} {cbp:>11.6f} {cbc:>11.6f}")

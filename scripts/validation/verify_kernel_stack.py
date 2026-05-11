"""Verify full kernel stack composes correctly on cache."""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
cv = pickle.load(open(ROOT / "data/model/_v1_playoff_resim_cache.pkl", "rb"))["cv"].copy()
cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)

p_adj = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1).to_numpy().copy()
p_role = pd.to_numeric(cv["p_role"], errors="coerce").fillna(0.5).clip(0, 1).to_numpy()
h = cv["hit"].astype(float).to_numpy()
q = pd.to_numeric(cv["q_blowout"], errors="coerce").fillna(0.0).to_numpy()
tier = cv["tier"].astype(str).str.upper().str.strip().to_numpy()
direction = cv["direction"].astype(str).str.upper().str.strip().to_numpy()
stat = cv["stat"].astype(str).str.upper().str.strip().to_numpy()


def brier(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def per_slate_brier(p_arr):
    cv["_p"] = p_arr
    rows = []
    for d, sub in cv.groupby(cv["game_date"].astype(str).str[:10]):
        rows.append({"date": d, "n": len(sub),
                     "b": brier(sub["hit"].astype(float).to_numpy(),
                                sub["_p"].to_numpy())})
    return rows


b_baseline = brier(h, p_adj)
print(f"BASELINE B(p_adj): {b_baseline:.6f}")
print()

# 1. Blowout bypass
bp = cfg.get("kernel_blowout_bypass", {})
if bp.get("enabled"):
    bypass = (q < bp["q_lo"]) | (q >= bp["q_hi"])
    p_adj[bypass] = p_role[bypass]
    print(f"1. Blowout bypass [{bp['q_lo']}, {bp['q_hi']}): "
          f"applied to {int(bypass.sum())} legs  "
          f"B={brier(h, p_adj):.6f}  delta={(brier(h,p_adj)-b_baseline)*1000:+.2f}mB")

# 2. High-prob shrink
hps = cfg.get("kernel_high_prob_shrink", {})
if hps.get("enabled"):
    p_thr, k = hps["p_thr"], hps["k"]
    mask = p_adj > p_thr
    if mask.any():
        z_thr = np.log(p_thr / (1 - p_thr))
        z = np.log(np.clip(p_adj[mask], 1e-6, 1-1e-6) / np.clip(1-p_adj[mask], 1e-6, 1-1e-6))
        p_adj[mask] = 1.0 / (1.0 + np.exp(-(z_thr + k * (z - z_thr))))
    print(f"2. High-prob shrink p_thr={p_thr} k={k}: applied to {int(mask.sum())} legs  "
          f"B={brier(h, p_adj):.6f}")

# 3. Subset shifts
for entry in cfg.get("kernel_subset_shifts", []) or []:
    if not entry.get("enabled", True): continue
    f = entry["filter"]
    m = np.ones(len(p_adj), dtype=bool)
    if "direction" in f:
        want = f["direction"]
        if isinstance(want, list):
            m &= np.isin(direction, [str(w).upper() for w in want])
        else:
            m &= (direction == str(want).upper())
    delta = entry["delta"]
    z = np.log(np.clip(p_adj[m], 1e-6, 1-1e-6) / np.clip(1-p_adj[m], 1e-6, 1-1e-6))
    p_adj[m] = 1.0 / (1.0 + np.exp(-(z + delta)))
    print(f"3. Subset shift {entry['name']} delta={delta}: applied to {int(m.sum())} legs  "
          f"B={brier(h, p_adj):.6f}")

# 4. Prob floors
for entry in cfg.get("kernel_prob_floors", []) or []:
    if not entry.get("enabled", True): continue
    f = entry["filter"]
    m = np.ones(len(p_adj), dtype=bool)
    if "tier" in f: m &= (tier == str(f["tier"]).upper())
    if "direction" in f: m &= (direction == str(f["direction"]).upper())
    floor = entry["floor"]
    below = m & (p_adj < floor)
    p_adj[below] = floor
    print(f"4. Prob floor {entry['name']} floor={floor}: applied to {int(below.sum())} legs  "
          f"B={brier(h, p_adj):.6f}")

# 5. Logit shrinks
for entry in cfg.get("kernel_logit_shrinks", []) or []:
    if not entry.get("enabled", True): continue
    f = entry["filter"]
    m = np.ones(len(p_adj), dtype=bool)
    if "stat" in f:
        want = f["stat"]
        if isinstance(want, list):
            m &= np.isin(stat, [str(w).upper() for w in want])
        else:
            m &= (stat == str(want).upper())
    k = entry["k"]
    z = np.log(np.clip(p_adj[m], 1e-6, 1-1e-6) / np.clip(1-p_adj[m], 1e-6, 1-1e-6))
    p_adj[m] = 1.0 / (1.0 + np.exp(-k * z))
    print(f"5. Logit shrink {entry['name']} k={k}: applied to {int(m.sum())} legs  "
          f"B={brier(h, p_adj):.6f}")

print()
b_final = brier(h, p_adj)
print(f"FINAL B(p_adj): {b_final:.6f}")
print(f"TOTAL DELTA:    {(b_final - b_baseline) * 1000:+.3f} mB")
print()
print("PER-SLATE COMPARISON")
print(f"{'date':<12} {'n':>5} {'B_baseline':>10} {'B_final':>10} {'delta_mB':>9}")
cv["_p_final"] = p_adj
for d, sub in cv.groupby(cv["game_date"].astype(str).str[:10]):
    h_s = sub["hit"].astype(float).to_numpy()
    p_b = pd.to_numeric(sub["p_adj"], errors="coerce").fillna(0.5).to_numpy()
    p_f = sub["_p_final"].to_numpy()
    b_b = brier(h_s, p_b)
    b_f = brier(h_s, p_f)
    flag = " <-" if (b_f - b_b) * 1000 > 1.0 else ""
    print(f"{d:<12} {len(sub):>5} {b_b:>10.6f} {b_f:>10.6f} "
          f"{(b_f-b_b)*1000:>+8.2f}mB{flag}")

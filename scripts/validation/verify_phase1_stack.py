"""Verify Phase 1 kernel winner composes with the 5 promoted layers.

Compares 4 scenarios on the playoff cache:
  S0: baseline kernel (current config) p_adj
  S1: baseline kernel + 5 layers       (current production end state)
  S2: Phase1 kernel p_adj                (winner alone)
  S3: Phase1 kernel + 5 layers           (combined)

Per-slate breakdown so we can see if layers still add value or have been
subsumed by the kernel winner.
"""
from __future__ import annotations
import sys, pickle, time
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import kernel_trainer_v1 as kt1
import kernel_trainer_v2_loso as kt2

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RESULTS = yaml.safe_load((ROOT / "tools" / "kernel_trainer_v2_loso_results.yaml").read_text())
WINNER = RESULTS["phase1"]["combined_winners"]

print("Phase 1 winner overrides:")
for k, v in sorted(WINNER.items()):
    print(f"  {k}: {v}")
print()

cv = kt2.load_cache(kt2.DEFAULT_CACHE)
cv = cv[cv["hit"].notna()].reset_index(drop=True)
N = len(cv)
hit = cv["hit"].astype(float).to_numpy()
dates = cv["game_date"].astype(str).str[:10].to_numpy()
unique_dates = sorted(set(dates))


def brier(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def per_slate(p):
    rows = []
    for d in unique_dates:
        m = (dates == d)
        rows.append((d, int(m.sum()), brier(hit[m], p[m])))
    return rows


# -- Compute p_adj (and we need p_role too) for both kernel variants --
# The MC sim returns p (raw) and p_adj (post haircut). p_role is the
# pre-blowout-haircut probability — we approximate with raw p, since
# in this trainer flow there is no separate role layer (no share matrix).
# So p_role := p_raw for the bypass check.

base_params = kt1._read_current_defaults()
phase1_params = {**base_params, **{k: float(v) for k, v in WINNER.items()}}

print("Running baseline MC (current config) ...")
t0 = time.time()
res_base = kt1.run_simulation(cv, base_params, sims=2000, return_per_date=True)
print(f"  done in {time.time()-t0:.0f}s  brier_p={res_base['brier_p']*1000:.3f}  brier_adj={res_base['brier_adj']*1000:.3f}")

print("Running Phase 1 winner MC ...")
t0 = time.time()
res_win = kt1.run_simulation(cv, phase1_params, sims=2000, return_per_date=True)
print(f"  done in {time.time()-t0:.0f}s  brier_p={res_win['brier_p']*1000:.3f}  brier_adj={res_win['brier_adj']*1000:.3f}")

# Re-run to extract p arrays (run_simulation returns metrics, not arrays —
# we'll inline the math here for arrays).

def compute_p_adj(params, sims=2000, seed=42):
    """Replica of run_simulation but returns (p_raw, p_adj) arrays."""
    import numpy as np
    rng = np.random.default_rng(seed)
    rate_mean_base = cv["rate_mean"].values.astype(float)
    rate_std_base = cv["rate_std"].values.astype(float)
    min_mean = cv["min_mean"].values.astype(float)
    min_std = cv["min_std"].values.astype(float)
    line = cv["line"].values.astype(float)
    is_under = cv["is_under"].values.astype(bool)
    spread = cv["spread"].values.astype(float)
    minutes_s = cv["minutes_s"].values.astype(float)
    is_star = cv["is_star"].values.astype(bool)
    games_used = cv["games_used"].values.astype(float)
    stat_u = cv["stat_u"].values

    if "opp_defense_rel" in cv.columns and float(params.get("opp_defense_strength", 1.0)) > 0:
        odr = np.nan_to_num(cv["opp_defense_rel"].values.astype(float), 0.0)
        rate_mean = rate_mean_base * (1.0 + float(params["opp_defense_strength"]) * odr)
    else:
        rate_mean = rate_mean_base.copy()

    rate_std = rate_std_base.copy() * float(params.get("rate_std_multiplier", 1.0))
    for stat_key, stat_names in kt1.STAT_GROUPS.items():
        pn = f"rate_std_{stat_key}"
        if pn in params:
            rate_std[np.isin(stat_u, stat_names)] *= float(params[pn])
    um = float(params.get("rate_std_under_mult", 1.0))
    if um != 1.0:
        rate_std[is_under] *= um
    tg = int(params.get("thin_window_games", 15))
    tm = float(params.get("thin_window_max_mult", 1.6))
    if tg > 0 and tm > 1.0:
        thin_mask = (games_used > 0) & (games_used < tg)
        thin_frac = games_used / tg
        thin_mult = 1.0 + (tm - 1.0) * (1.0 - thin_frac)
        rate_std = np.where(thin_mask, rate_std * thin_mult, rate_std)
    rate_std = np.maximum(rate_std, 0.01)

    q = kt1.compute_blowout_q(spread, float(params.get("threshold_margin", 15.5)),
                              float(params.get("spread_sd", 10.0)))
    star_drop = float(params.get("star_minute_drop", 6.0))
    starter_drop = float(params.get("starter_minute_drop", 3.5))
    role_drop = float(params.get("role_minute_drop", 0.5))
    minute_drop = np.where(is_star, star_drop,
                           np.where(min_mean >= 25.0, starter_drop, role_drop))
    rmc = float(params.get("rate_min_correlation", 0.35))

    p_all = np.empty(N, dtype=float)
    BS = kt1.BATCH_SIZE
    for s in range(0, N, BS):
        e = min(s + BS, N)
        p_all[s:e] = kt1.simulate_batch(rate_mean[s:e], rate_std[s:e], min_mean[s:e],
                                        min_std[s:e], line[s:e], is_under[s:e],
                                        q[s:e], minute_drop[s:e], rmc, sims, rng)

    pse = float(params.get("post_sim_exponent", 0.3))
    p_adj = kt1.apply_post_sim_adjustment(p_all, q, minutes_s, is_under, pse)
    return p_all, p_adj, q


print("\nExtracting p arrays for stacking...")
p_raw_base, p_adj_base, q_base = compute_p_adj(base_params)
p_raw_win, p_adj_win, q_win = compute_p_adj(phase1_params)


def apply_layers(p_adj, p_role, q, label):
    """Apply 5 promoted layers in order from config."""
    p = p_adj.copy()
    direction = cv["direction_u"].values
    stat = cv["stat_u"].values
    tier = cv["tier"].astype(str).str.upper().str.strip().to_numpy() if "tier" in cv.columns else np.full(N, "STANDARD")

    # 1. blowout bypass
    bp = CFG.get("kernel_blowout_bypass", {})
    if bp.get("enabled"):
        bypass = (q < bp["q_lo"]) | (q >= bp["q_hi"])
        p[bypass] = p_role[bypass]
        n1 = int(bypass.sum())
    else:
        n1 = 0
    # 2. high-prob shrink
    hps = CFG.get("kernel_high_prob_shrink", {})
    if hps.get("enabled"):
        p_thr, k = hps["p_thr"], hps["k"]
        m = p > p_thr
        if m.any():
            z_thr = np.log(p_thr / (1 - p_thr))
            z = np.log(np.clip(p[m], 1e-6, 1-1e-6) / np.clip(1-p[m], 1e-6, 1-1e-6))
            p[m] = 1.0 / (1.0 + np.exp(-(z_thr + k * (z - z_thr))))
        n2 = int(m.sum())
    else:
        n2 = 0
    # 3. subset shifts
    n3 = 0
    for entry in CFG.get("kernel_subset_shifts", []) or []:
        if not entry.get("enabled", True): continue
        f = entry["filter"]
        m = np.ones(len(p), dtype=bool)
        if "direction" in f:
            want = f["direction"]
            want = [str(w).upper() for w in (want if isinstance(want, list) else [want])]
            m &= np.isin(direction, want)
        delta = entry["delta"]
        z = np.log(np.clip(p[m], 1e-6, 1-1e-6) / np.clip(1-p[m], 1e-6, 1-1e-6))
        p[m] = 1.0 / (1.0 + np.exp(-(z + delta)))
        n3 += int(m.sum())
    # 4. probability floors
    n4 = 0
    for entry in CFG.get("kernel_prob_floors", []) or []:
        if not entry.get("enabled", True): continue
        f = entry["filter"]
        m = np.ones(len(p), dtype=bool)
        if "tier" in f: m &= (tier == str(f["tier"]).upper())
        if "direction" in f:
            want = f["direction"]
            want = [str(w).upper() for w in (want if isinstance(want, list) else [want])]
            m &= np.isin(direction, want)
        floor = entry["floor"]
        p[m] = np.maximum(p[m], floor)
        n4 += int(m.sum())
    # 5. logit shrinks
    n5 = 0
    for entry in CFG.get("kernel_logit_shrinks", []) or []:
        if not entry.get("enabled", True): continue
        f = entry["filter"]
        m = np.ones(len(p), dtype=bool)
        if "stat" in f:
            want = f["stat"]
            want = [str(w).upper() for w in (want if isinstance(want, list) else [want])]
            m &= np.isin(stat, want)
        k = entry["k"]
        z = np.log(np.clip(p[m], 1e-6, 1-1e-6) / np.clip(1-p[m], 1e-6, 1-1e-6))
        p[m] = 1.0 / (1.0 + np.exp(-(z * k)))
        n5 += int(m.sum())
    print(f"  [{label}] layers applied: bypass={n1} hps={n2} shifts={n3} floors={n4} shrinks={n5}")
    return p


print("\nApplying 5 layers on top of base kernel...")
p_base_layered = apply_layers(p_adj_base, p_raw_base, q_base, "BASE+layers")

print("Applying 5 layers on top of Phase 1 winner kernel...")
p_win_layered = apply_layers(p_adj_win, p_raw_win, q_win, "WIN+layers")


print("\n" + "=" * 78)
print("RESULTS  (Brier in mB, lower = better)")
print("=" * 78)

scenarios = {
    "S0  base kernel (no layers)":      p_adj_base,
    "S1  base + 5 layers (production)": p_base_layered,
    "S2  Phase1 kernel (no layers)":    p_adj_win,
    "S3  Phase1 + 5 layers":            p_win_layered,
}

agg = {name: brier(hit, p) * 1000 for name, p in scenarios.items()}
print(f"\nAggregate (N={N:,} legs):")
for name, b in agg.items():
    print(f"  {name:40s}  {b:7.3f} mB")

print(f"\nDeltas vs S1 (current production end state):")
ref = agg["S1  base + 5 layers (production)"]
for name, b in agg.items():
    print(f"  {name:40s}  {b-ref:+7.3f} mB")

print("\nPer-slate (Brier mB):")
ps = {name: per_slate(p) for name, p in scenarios.items()}
print(f"  {'date':<12} {'N':>5}  " + "  ".join(f"{n[:38]:>9}" for n in scenarios))
for i, d in enumerate(unique_dates):
    line = f"  {d:<12} {ps['S0  base kernel (no layers)'][i][1]:>5}  "
    line += "  ".join(f"{ps[n][i][2]*1000:>9.3f}" for n in scenarios)
    print(line)

# Per-slate deltas vs S1
print("\nPer-slate delta (S3 - S1):")
for i, d in enumerate(unique_dates):
    s1 = ps["S1  base + 5 layers (production)"][i][2]
    s3 = ps["S3  Phase1 + 5 layers"][i][2]
    n = ps["S0  base kernel (no layers)"][i][1]
    delta = (s3 - s1) * 1000
    tag = "GOOD" if delta <= 0 else ("OK" if delta <= 1.0 else "HURT")
    print(f"  {d}  N={n:>5}  delta={delta:+7.3f} mB  {tag}")

# Per-slate deltas vs S0 (kernel-only comparison)
print("\nPer-slate delta (S2 - S0, kernel-only):")
for i, d in enumerate(unique_dates):
    s0 = ps["S0  base kernel (no layers)"][i][2]
    s2 = ps["S2  Phase1 kernel (no layers)"][i][2]
    n = ps["S0  base kernel (no layers)"][i][1]
    delta = (s2 - s0) * 1000
    tag = "GOOD" if delta <= 0 else ("OK" if delta <= 1.0 else "HURT")
    print(f"  {d}  N={n:>5}  delta={delta:+7.3f} mB  {tag}")

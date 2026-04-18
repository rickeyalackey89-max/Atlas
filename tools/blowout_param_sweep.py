"""
Blowout Parameter Sweep — finds optimal blowout config by grid search.

Samples ~10K legs (stratified by date) from the v9 resim cache,
re-simulates each config through the MC kernel, and measures raw Brier.

Parameter grid:
  - spread_sd: [8, 10, 12]
  - star_minute_drop: [0.12, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
  - role_ratio: starter = star * ratio, rotation from role_minute_drop
  - role_minute_drop: [0.18, 0.3, 0.5, 1.0]
  - bench_minute_drop: [0.0, 0.2, 0.5]
  - enriched_q: [True, False]  (team/matchup weights on/off)

Reports top-N configs ranked by raw Brier.
Expected runtime: ~2-4 min per config, ~100 configs → ~3-6 hours.
Use --fast for a smaller sample (~5K legs, ~1-2 min/config).
"""
import sys, pathlib, time, pickle, copy, warnings, argparse, itertools
sys.path.insert(0, str(pathlib.Path(r"c:/Users/rick/projects/Atlas/src")))
sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

ROOT = pathlib.Path(r"c:/Users/rick/projects/Atlas")
CACHE_SRC = pathlib.Path(r"D:/AtlasTestMarch26/model_backups/_v9_resim_cache_with_spreads.pkl")

from Atlas.core.fingerprint import build_manifest, config_fingerprint
from Atlas.engine.new_probability import simulate_leg_probability_new, _build_blowout_team_stats

parser = argparse.ArgumentParser()
parser.add_argument("--fast", action="store_true", help="Smaller sample (~5K legs)")
parser.add_argument("--top", type=int, default=15, help="Show top N configs")
parser.add_argument("--sample", type=int, default=10000, help="Sample size (legs)")
parser.add_argument("--sims", type=int, default=10000, help="MC sims per leg")
args = parser.parse_args()

SAMPLE_SIZE = 5000 if args.fast else args.sample
MC_SIMS = args.sims

# ===================================================================
# Load config (base — we'll override blowout section per grid point)
# ===================================================================
with open(ROOT / "config.yaml") as f:
    base_cfg = yaml.safe_load(f)
role_cfg = base_cfg.get("role_ctx", {})

# ===================================================================
# Parameter grid
# ===================================================================
GRID = {
    "spread_sd":        [10.0],
    "star_minute_drop": [6.0],           # locked at peak
    "starter_minute_drop": [3.5],           # locked at peak
    "role_minute_drop": [0.5],              # locked at peak
    "bench_minute_drop":[0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0],  # Phase 3: sweep bench
    "enriched_q":       [True],
}

# Starter is now swept independently — disable ratio
STARTER_RATIO = None

def _build_configs():
    """Generate all grid configs, pruning nonsensical combos."""
    configs = []
    star_vals = GRID["star_minute_drop"]
    starter_vals = GRID.get("starter_minute_drop", [None])
    role_vals = GRID["role_minute_drop"]
    bench_vals = GRID["bench_minute_drop"]
    enrich_vals = GRID["enriched_q"]
    sd_vals = GRID["spread_sd"]

    for sd, star, starter_v, role, bench, enrich in itertools.product(
        sd_vals, star_vals, starter_vals, role_vals, bench_vals, enrich_vals,
    ):
        # Compute starter from ratio if not swept independently
        if starter_v is None:
            starter = round(star * STARTER_RATIO, 2)
        else:
            starter = starter_v

        # Prune: star >= starter >= role >= bench
        if starter > star:
            continue
        if role > starter:
            continue
        if bench > role:
            continue

        configs.append({
            "spread_sd": sd,
            "star_minute_drop": star,
            "starter_minute_drop": starter,
            "role_minute_drop": role,
            "bench_minute_drop": bench,
            "enriched_q": enrich,
        })
    return configs

all_configs = _build_configs()
print(f"Parameter grid: {len(all_configs)} configs")
print(f"Sample size: {SAMPLE_SIZE} legs, {MC_SIMS} sims/leg")
est_per_config = SAMPLE_SIZE * 0.019 / 60  # ~0.019s per leg
print(f"Estimated time per config: ~{est_per_config:.1f} min")
print(f"Estimated total: ~{est_per_config * len(all_configs):.0f} min ({est_per_config * len(all_configs) / 60:.1f} hours)")

# ===================================================================
# Load cache & sample
# ===================================================================
print("\nLoading cache ...")
with open(CACHE_SRC, "rb") as f:
    cache = pickle.load(f)
cv_full = cache["cv"].copy()
dates = sorted(cache["dates"])
print(f"  Full corpus: {len(cv_full)} legs, {len(dates)} dates")

# Stratified sample: equal legs per date
np.random.seed(42)
legs_per_date = max(1, SAMPLE_SIZE // len(dates))
sampled_indices = []
for d in dates:
    mask = cv_full["game_date"].astype(str).str[:10] == str(d)[:10]
    date_indices = cv_full.index[mask].tolist()
    n = min(legs_per_date, len(date_indices))
    chosen = np.random.choice(date_indices, size=n, replace=False)
    sampled_indices.extend(chosen.tolist())

# Trim to exact sample size
if len(sampled_indices) > SAMPLE_SIZE:
    sampled_indices = sorted(np.random.choice(sampled_indices, size=SAMPLE_SIZE, replace=False))
else:
    sampled_indices = sorted(sampled_indices)

cv = cv_full.loc[sampled_indices].reset_index(drop=True)
print(f"  Sampled: {len(cv)} legs across {len(dates)} dates")

# ===================================================================
# Load gamelogs & pre-compute per-date logs
# ===================================================================
print("Loading gamelogs ...")
logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}
for col in ["team", "opp"]:
    logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)

print("Pre-computing date-specific gamelogs ...")
date_logs = {}
for d in dates:
    gd = str(d)[:10]
    game_date = pd.to_datetime(gd)
    dl = logs[logs["game_date"] < game_date].copy()
    if "_atlas_players_unique" in dl.attrs:
        del dl.attrs["_atlas_players_unique"]
    date_logs[gd] = dl

# Pre-build blowout team stats per date (for enriched q)
print("Building blowout team stats per date ...")
date_blowout_stats = {}
for d in dates:
    gd = str(d)[:10]
    stats = _build_blowout_team_stats(date_logs[gd], threshold=15.5)
    date_blowout_stats[gd] = stats

# Pre-build row Series for each sampled leg
print("Pre-building row data ...")
row_data = []
for i in range(len(cv)):
    row = cv.iloc[i]
    gd = str(row["game_date"])[:10]
    row_s = pd.Series({
        "player": str(row["player"]).strip(),
        "stat": str(row.get("stat_u", row.get("stat", ""))).upper().strip(),
        "line": float(row["line"]),
        "direction": str(row.get("direction", "OVER")).upper().strip(),
        "team": str(row.get("team", "")).upper().strip(),
        "opp": str(row.get("opp", "")).upper().strip(),
        "game_spread": float(row.get("game_spread", 0) or 0),
        "spread": float(row.get("game_spread", 0) or 0),
    })
    row_data.append((gd, row_s))

hit_arr = cv["hit"].values.astype(float)

# Baseline raw Brier from original v9 cache (these are the p_new from original config)
baseline_p = cv_full.loc[sampled_indices, "p_new"].values
baseline_valid = np.isfinite(baseline_p) & (baseline_p > 0.005) & (baseline_p < 0.995)
baseline_brier = float(np.mean((baseline_p[baseline_valid] - hit_arr[baseline_valid]) ** 2))
print(f"\nBaseline Brier (v9 cache, original config): {baseline_brier:.6f}")

# ===================================================================
# Sweep
# ===================================================================
print(f"\n{'='*70}")
print(f"Starting sweep: {len(all_configs)} configs × {len(cv)} legs")
print(f"{'='*70}\n")

results = []
t_total = time.time()

for ci, cfg_point in enumerate(all_configs):
    t0 = time.time()
    
    # Build blowout config for this grid point
    blow = copy.deepcopy(base_cfg.get("blowout", {}))
    blow["spread_sd"] = cfg_point["spread_sd"]
    blow["star_minute_drop"] = cfg_point["star_minute_drop"]
    blow["role_minute_drop"] = cfg_point["role_minute_drop"]
    blow["threshold_margin"] = 15.5
    
    # Rotation tiers
    blow["rotation_tiers"] = {
        "starter_minute_drop": cfg_point["starter_minute_drop"],
        "bench_minute_drop": cfg_point["bench_minute_drop"],
    }
    
    # Enriched q weights
    if cfg_point["enriched_q"]:
        blow["matchup_blowout_weight"] = 0.25
        blow["team_blowout_weight"] = 0.15
    else:
        blow["matchup_blowout_weight"] = 0.0
        blow["team_blowout_weight"] = 0.0
    
    # Run simulation for all sampled legs
    preds = np.full(len(cv), np.nan)
    errors = 0
    
    for i, (gd, row_s) in enumerate(row_data):
        # Attach blowout team stats if enriched
        blow_run = copy.copy(blow)
        if cfg_point["enriched_q"] and gd in date_blowout_stats:
            blow_run["_blowout_team_stats"] = date_blowout_stats[gd]
        
        try:
            info = simulate_leg_probability_new(
                gamelogs=date_logs[gd],
                row=row_s,
                lookback=50,
                sims=MC_SIMS,
                spread_sd=float(blow_run["spread_sd"]),
                blowout_threshold=float(blow_run["threshold_margin"]),
                star_minute_drop=float(blow_run["star_minute_drop"]),
                role_minute_drop=float(blow_run["role_minute_drop"]),
                blowout_cfg=blow_run,
                role_cfg=role_cfg,
            )
            p = info.get("p")
            if p is not None:
                preds[i] = float(p)
        except Exception:
            errors += 1
    
    # Compute Brier
    valid = np.isfinite(preds) & (preds > 0.005) & (preds < 0.995)
    n_valid = int(valid.sum())
    if n_valid > 0:
        brier = float(np.mean((preds[valid] - hit_arr[valid]) ** 2))
        mean_p = float(np.mean(preds[valid]))
    else:
        brier = 999.0
        mean_p = 0.0
    
    delta = (brier - baseline_brier) * 1000
    elapsed = time.time() - t0
    
    results.append({
        **cfg_point,
        "brier": brier,
        "delta_mB": delta,
        "n_valid": n_valid,
        "mean_p": mean_p,
        "errors": errors,
        "time_s": elapsed,
    })
    
    # Progress
    marker = " ***" if delta < -0.5 else (" !!!" if delta > 2.0 else "")
    enr = "enrich" if cfg_point["enriched_q"] else "plain "
    print(f"  [{ci+1:3d}/{len(all_configs)}]  "
          f"sd={cfg_point['spread_sd']:4.0f}  star={cfg_point['star_minute_drop']:5.2f}  "
          f"role={cfg_point['role_minute_drop']:4.2f}  bench={cfg_point['bench_minute_drop']:3.1f}  "
          f"{enr}  Brier={brier:.6f}  Δ={delta:+.2f}mB  ({elapsed:.0f}s){marker}")

total_time = time.time() - t_total

# ===================================================================
# Results
# ===================================================================
print(f"\n{'='*70}")
print(f"SWEEP COMPLETE: {len(results)} configs in {total_time/60:.1f} min")
print(f"{'='*70}")

# Sort by Brier
results.sort(key=lambda x: x["brier"])

print(f"\nBaseline Brier (original config): {baseline_brier:.6f}")
print(f"\n--- TOP {args.top} CONFIGS (by raw Brier) ---")
print(f"{'Rank':>4s}  {'sd':>4s}  {'star':>6s}  {'starter':>7s}  {'role':>5s}  {'bench':>5s}  "
      f"{'enrich':>6s}  {'Brier':>9s}  {'Δ mB':>7s}")
print("-" * 75)

for rank, r in enumerate(results[:args.top], 1):
    enr = "yes" if r["enriched_q"] else "no"
    print(f"{rank:4d}  {r['spread_sd']:4.0f}  {r['star_minute_drop']:6.2f}  "
          f"{r['starter_minute_drop']:7.2f}  {r['role_minute_drop']:5.2f}  "
          f"{r['bench_minute_drop']:5.2f}  {enr:>6s}  {r['brier']:.6f}  {r['delta_mB']:+7.2f}")

# Also show worst configs
print(f"\n--- WORST 5 CONFIGS ---")
for rank, r in enumerate(results[-5:], len(results)-4):
    enr = "yes" if r["enriched_q"] else "no"
    print(f"{rank:4d}  {r['spread_sd']:4.0f}  {r['star_minute_drop']:6.2f}  "
          f"{r['starter_minute_drop']:7.2f}  {r['role_minute_drop']:5.2f}  "
          f"{r['bench_minute_drop']:5.2f}  {enr:>6s}  {r['brier']:.6f}  {r['delta_mB']:+7.2f}")

# Best config summary
best = results[0]
print(f"\n{'='*70}")
print(f"BEST CONFIG:")
print(f"  spread_sd:          {best['spread_sd']}")
print(f"  star_minute_drop:   {best['star_minute_drop']}")
print(f"  starter_minute_drop:{best['starter_minute_drop']}")
print(f"  role_minute_drop:   {best['role_minute_drop']}")
print(f"  bench_minute_drop:  {best['bench_minute_drop']}")
print(f"  enriched_q:         {best['enriched_q']}")
print(f"  Brier:              {best['brier']:.6f}  (Δ={best['delta_mB']:+.2f} mB vs baseline)")
print(f"{'='*70}")

# Save full results with config fingerprint
import json
_manifest = build_manifest(
    source="blowout_param_sweep", cfg=base_cfg,
    ensemble_dir=base_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
)
print(f"  Config fingerprint: {_manifest['config_fingerprint']}")
wrapped_results = {"_manifest": _manifest, "configs": results}
out_path = ROOT / "data" / "model" / "blowout_sweep_results.json"
with open(out_path, "w") as f:
    json.dump(wrapped_results, f, indent=2, default=str)
print(f"\nFull results saved to {out_path}")

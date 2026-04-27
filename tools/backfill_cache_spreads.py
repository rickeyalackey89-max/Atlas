"""
Backfill game spreads into the v9 resim cache.

Computes actual game margins from gamelogs (team_pts - opp_pts),
then patches the cache so every leg has a realistic spread value.
This ensures the blowout channel (q_blowout) sees real data
matching what the live model gets from Rotowire.

Note: Using actual final margins as the spread is slightly optimistic
(a closing line has noise), but it's the ground truth for what actually
happened — and far better than 0.0 (no spread) which gives q=0.121 everywhere.

Saves patched cache alongside the original (does NOT overwrite).
"""
import sys, pathlib, pickle, warnings
sys.path.insert(0, str(pathlib.Path(r"c:/Users/rick/projects/Atlas/src")))
sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = pathlib.Path(r"c:/Users/rick/projects/Atlas")
CACHE_SRC = pathlib.Path(r"D:/AtlasTestMarch26/model_backups/_v9_resim_cache.pkl")
CACHE_OUT = pathlib.Path(r"D:/AtlasTestMarch26/model_backups/_v9_resim_cache_with_spreads.pkl")

# ===================================================================
# 1. Load gamelogs and compute game-level margins
# ===================================================================
print("Loading gamelogs ...")
logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
logs["pts"] = pd.to_numeric(logs["pts"], errors="coerce")
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}
for col in ["team", "opp"]:
    logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)

# Sum pts per team per game
game_scores = logs.groupby(["game_date", "team", "opp"])["pts"].sum().reset_index()
game_scores.columns = ["game_date", "team", "opp", "team_pts"]

# Merge to get opponent pts
game_opp = game_scores.rename(columns={"team": "opp", "opp": "team", "team_pts": "opp_pts"})
games = game_scores.merge(game_opp, on=["game_date", "team", "opp"], how="left")
games["margin"] = games["team_pts"] - games["opp_pts"]
games["abs_margin"] = games["margin"].abs()

# Use margin as the "spread" (negative = team is favored, like Vegas convention)
# margin > 0 means team won by that much → spread should be negative (team was favored)
# We'll store as the team's perspective: spread = -margin (team favored = negative spread)
games["backfill_spread"] = -games["margin"]

games["gd"] = games["game_date"].dt.strftime("%Y-%m-%d")
games_dedup = games.drop_duplicates(["gd", "team", "opp"])

print(f"  Computed margins for {len(games_dedup)} team-game rows")
print(f"  Margin abs: mean={games['abs_margin'].mean():.1f}, "
      f"median={games['abs_margin'].median():.1f}")
print(f"  Blowout rate (|margin| >= 15.5): {(games['abs_margin'] >= 15.5).mean():.3f}")

# ===================================================================
# 2. Load cache
# ===================================================================
print("\nLoading resim cache ...")
with open(CACHE_SRC, "rb") as f:
    cache = pickle.load(f)

cv = cache["cv"].copy()
n_total = len(cv)
print(f"  Cache: {n_total} legs, {len(cache['dates'])} dates")

# Check existing spread coverage
existing_spread = pd.to_numeric(cv.get("game_spread", pd.Series(dtype=float)), errors="coerce")
n_existing = (existing_spread.notna() & (existing_spread != 0)).sum()
print(f"  Existing spread coverage: {n_existing} / {n_total} ({n_existing/n_total:.1%})")

# ===================================================================
# 3. Match and backfill
# ===================================================================
print("\nBackfilling spreads ...")
cv["game_date"] = pd.to_datetime(cv["game_date"], errors="coerce")
cv["gd"] = cv["game_date"].dt.strftime("%Y-%m-%d")

# Normalize team/opp in cache
for col in ["team", "opp"]:
    cv[col] = cv[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)

# Merge margin data
spread_lookup = games_dedup[["gd", "team", "opp", "backfill_spread", "margin", "abs_margin"]].copy()
cv = cv.merge(spread_lookup, on=["gd", "team", "opp"], how="left", suffixes=("", "_backfill"))

# Apply backfill: only where spread is missing or 0
has_existing = (existing_spread.notna() & (existing_spread != 0)).values
has_backfill = cv["backfill_spread"].notna().values

# Patch spread columns
spread_col = pd.to_numeric(cv.get("spread", pd.Series(dtype=float)), errors="coerce").values.copy()
game_spread_col = pd.to_numeric(cv.get("game_spread", pd.Series(dtype=float)), errors="coerce").values.copy()
home_spread_col = pd.to_numeric(cv.get("home_spread", pd.Series(dtype=float)), errors="coerce").values.copy()
backfill_vals = cv["backfill_spread"].values

n_patched = 0
for i in range(n_total):
    if has_backfill[i] and not has_existing[i]:
        val = float(backfill_vals[i])
        spread_col[i] = val
        game_spread_col[i] = val
        home_spread_col[i] = val
        n_patched += 1

cv["spread"] = spread_col
cv["game_spread"] = game_spread_col
cv["home_spread"] = home_spread_col

# Also set spread_ok and spread_source
cv.loc[has_backfill & ~has_existing, "spread_ok"] = "True"
cv.loc[has_backfill & ~has_existing, "spread_source"] = "gamelog_margin_backfill"
cv.loc[has_backfill & ~has_existing, "spread_reason"] = "actual_final_margin"

# Clean up temp columns
cv.drop(columns=["gd", "backfill_spread", "margin", "abs_margin"], errors="ignore", inplace=True)

# Final coverage check
final_spread = pd.to_numeric(cv["game_spread"], errors="coerce")
n_final = (final_spread.notna() & (final_spread != 0)).sum()
n_still_missing = n_total - n_final

print(f"  Patched: {n_patched} legs")
print(f"  Final spread coverage: {n_final} / {n_total} ({n_final/n_total:.1%})")
print(f"  Still missing: {n_still_missing}")

# Show spread distribution
print(f"\n  Spread distribution (all legs):")
valid = final_spread[final_spread.notna() & (final_spread != 0)]
print(f"    mean={valid.mean():.1f}, std={valid.std():.1f}")
print(f"    min={valid.min():.1f}, max={valid.max():.1f}")
print(f"    |spread| mean={valid.abs().mean():.1f}, median={valid.abs().median():.1f}")

# q_blowout impact preview
from scipy.stats import norm
sd = 10.0
threshold = 15.5
q_new = np.zeros(n_total)
for i in range(n_total):
    sp = float(final_spread.iloc[i]) if pd.notna(final_spread.iloc[i]) else 0.0
    z_hi = (threshold - sp) / sd
    z_lo = (-threshold - sp) / sd
    q_new[i] = (1 - norm.cdf(z_hi)) + norm.cdf(z_lo)

print(f"\n  q_blowout with backfilled spreads:")
print(f"    mean={q_new.mean():.4f} (was 0.1293)")
print(f"    std={q_new.std():.4f} (was 0.0516)")
print(f"    pct > 0.15: {(q_new > 0.15).mean():.3f} (was ~0.03)")
print(f"    pct > 0.20: {(q_new > 0.20).mean():.3f} (was ~0.02)")
print(f"    pct > 0.40: {(q_new > 0.40).mean():.3f}")

# ===================================================================
# 4. Save patched cache
# ===================================================================
print(f"\nSaving patched cache to {CACHE_OUT} ...")
cache_out = {
    "cv": cv,
    "dates": cache["dates"],
}
# Preserve any other keys
for k in cache:
    if k not in cache_out:
        cache_out[k] = cache[k]

with open(CACHE_OUT, "wb") as f:
    pickle.dump(cache_out, f, protocol=pickle.HIGHEST_PROTOCOL)

size_mb = CACHE_OUT.stat().st_size / 1024 / 1024
print(f"  Saved: {size_mb:.1f} MB")
print(f"\nDONE. Original cache untouched at {CACHE_SRC}")
print(f"Use {CACHE_OUT} for sweeps and training.")

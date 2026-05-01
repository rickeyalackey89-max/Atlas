"""
Patch v16 resim cache to v17 compatibility by computing all GBM features.

This script transforms the raw v16 cache leg data into the 34 GBM features
required by the v17 model, using the exact same feature engineering logic
as tools/gbm_v12_train.py.

Usage:
    python tools/patch_v16_to_v17_cache.py
    python tools/patch_v16_to_v17_cache.py --dry-run
"""
import argparse
import json
import math
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit

# Add Atlas modules to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from Atlas.core.minutes import minutes_sensitivity

# Constants from gbm_v12_train.py
FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
    "sb_over_prob",
]

STAT_COLUMN_MAP = {
    "PTS": ["pts"], "POINTS": ["pts"], "REB": ["reb"], "REBS": ["reb"],
    "AST": ["ast"], "ASTS": ["ast"], "FG3M": ["fg3m"], "3PM": ["fg3m"],
    "FGA": ["fga"], "FTA": ["fta"], "TOV": ["tov"],
    "PA": ["pts", "ast"], "PR": ["pts", "reb"], "RA": ["reb", "ast"],
    "PRA": ["pts", "reb", "ast"],
}
STAT_CATS = {"PTS": 0, "REB": 1, "AST": 2, "FG3M": 3, "PRA": 4,
             "PR": 5, "PA": 6, "RA": 7, "FGA": 8, "FTA": 9, "TOV": 10}
TIER_CATS = {"STANDARD": 0, "GOBLIN": 1, "DEMON": 2}
COMBOS = {"PRA", "PR", "PA", "RA"}
P_LO, P_HI = 0.03, 0.97
SMOOTH_K = 20
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}

def load_ou_cache():
    """Load Rotowire O/U cache from IAEL archives."""
    iael_dir = ROOT / "data/archives/iael/2026"
    cache = {}
    if not iael_dir.exists():
        return cache
    
    print(f"Loading Rotowire O/U data from {iael_dir}")
    
    for dd in sorted(iael_dir.glob("2026-*")):
        rw_files = sorted(dd.glob("*/rotowire_lines.json"))
        if not rw_files:
            continue
            
        try:
            data = json.loads(rw_files[-1].read_text(encoding="utf-8"))
            lookup = {}
            for event in data.get("events", []):
                home = str(event.get("homeTeam", "")).upper()
                away = str(event.get("awayTeam", "")).upper()
                ou = float(event.get("ou", 0))
                if ou > 0:
                    lookup[home] = ou
                    lookup[away] = ou
            if lookup:
                cache[dd.name] = lookup
        except Exception:
            pass
    
    print(f"Loaded O/U data for {len(cache)} dates")
    return cache

def load_gamelogs():
    """Load and prepare gamelog data."""
    logs_path = ROOT / "data/gamelogs/nba_gamelogs.csv"
    print(f"Loading gamelogs from {logs_path}")
    
    logs = pd.read_csv(logs_path, low_memory=False)
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
    
    # Normalize team names
    for col in ["team", "opp"]:
        if col in logs.columns:
            logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)
    
    print(f"Loaded {len(logs)} gamelog rows, {logs['player'].nunique()} players")
    return logs

def build_player_history(logs):
    """Build per-player game history for window feature computation."""
    print("Building player history lookup...")
    
    _logs_sorted = logs.sort_values(["player", "game_date"]).reset_index(drop=True)
    player_history = {}
    
    stat_columns = ["pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]
    
    for _, row in _logs_sorted.iterrows():
        player = str(row.get("player", "")).strip()
        game_date = row["game_date"]
        
        if pd.isna(game_date) or not player:
            continue
            
        gd_str = game_date.strftime("%Y-%m-%d")
        stats = {}
        
        for col in stat_columns:
            val = row.get(col)
            if val is not None:
                try:
                    v = float(val)
                    if math.isfinite(v):
                        stats[col] = v
                except (ValueError, TypeError):
                    pass
        
        if stats:
            player_history.setdefault(player, []).append((gd_str, stats))
    
    # Sort by date for each player
    for player in player_history:
        player_history[player].sort(key=lambda x: x[0])
    
    print(f"Built history for {len(player_history)} players")
    return player_history

def build_b2b_set(logs):
    """Build set of (player, game_date) tuples for back-to-back games."""
    print("Building back-to-back game set...")
    _gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
    _gl = _gl.sort_values(["player", "game_date"])
    _gl["prev"] = _gl.groupby("player")["game_date"].shift(1)
    _gl["days"] = (_gl["game_date"] - _gl["prev"]).dt.days
    
    b2b = set()
    for _, r in _gl.iterrows():
        if pd.notna(r["days"]) and r["days"] == 1:
            b2b.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))
    
    print(f"Found {len(b2b)} back-to-back game instances")
    return b2b

def get_recent_stats(player_history, player, stat_u, game_date_str, n=50):
    """Get recent stat values for a player before a given date."""
    hist = player_history.get(player)
    if not hist:
        return []
    
    cols = STAT_COLUMN_MAP.get(stat_u)
    if not cols:
        return []
    
    recent = []
    for gd, stats in hist:
        if gd >= game_date_str:  # Only use games before target date
            break
        
        total = 0.0
        ok = False
        for col in cols:
            if col in stats:
                total += stats[col]
                ok = True
        
        if ok:
            recent.append(total)
    
    return recent[-n:]

def engineer_gbm_features(cv, ou_cache, player_history, b2b_set):
    """Transform v16 cache into v17 GBM features using exact gbm_v12_train.py logic."""
    print("\nEngineering GBM features...")
    print(f"Processing {len(cv)} legs...")
    
    t0 = time.time()
    
    # Direction under mask
    dir_u = cv["direction"].astype(str).str.upper()
    um = (dir_u == "UNDER").values
    
    # Ensure numeric columns
    _num_cols = ["p_new", "rate_mean", "rate_std", "min_mean", "min_std",
                 "games_used", "q_blowout", "form_z_line",
                 "external_prior_score", "external_prior_n"]
    for col in _num_cols:
        if col in cv.columns:
            cv[col] = pd.to_numeric(cv[col], errors="coerce")
    
    # Use p_new if available, otherwise p_adj
    if "p_new" not in cv.columns:
        cv["p_new"] = cv.get("p_adj", cv.get("p", 0.5))
    
    cv["logit_p"] = sp_logit(np.clip(cv["p_new"].values, P_LO, P_HI))
    
    # z_line computation
    if "form_z_line" in cv.columns and cv["form_z_line"].notna().sum() > len(cv) * 0.5:
        cv["z_line"] = cv["form_z_line"].fillna(0.0).clip(-5, 5)
    else:
        _rm = cv["rate_mean"].fillna(0)
        _mm = cv["min_mean"].fillna(0)
        _rs = cv["rate_std"].fillna(0.01).clip(lower=0.01)
        cv["z_line"] = np.where(
            (_rm > 0) & (_mm > 0),
            (_rm * _mm - cv["line"]) / np.maximum(_rs * _mm, 0.01),
            0.0
        ).clip(-5, 5)
    
    # Basic features
    _mm = cv["min_mean"].fillna(0.0)
    _ms = cv["min_std"].fillna(0.0)
    cv["min_cv"] = np.where(_mm > 1, np.clip(_ms / _mm, 0, 1), 0.3)
    
    cv["is_combo"] = cv["stat_u"].isin(COMBOS).astype(float)
    
    # External priors (BettingPros)
    cv["bp_has"] = 0.0
    cv["bp_score_gated"] = 0.0
    if "external_prior_n" in cv.columns:
        has_bp = cv["external_prior_n"].fillna(0) > 0
        cv.loc[has_bp, "bp_has"] = 1.0
        edge = cv["external_prior_score"].fillna(0.0) - cv["line"]
        dm = ((edge > 0) & (dir_u == "OVER")) | ((edge <= 0) & (dir_u == "UNDER"))
        cv.loc[has_bp & dm, "bp_score_gated"] = np.tanh(edge[has_bp & dm] / 3.0)
    
    # Stat type indicators
    cv["is_assists"] = (cv["stat_u"] == "AST").astype(float)
    cv["is_threes"] = (cv["stat_u"] == "FG3M").astype(float)
    
    # Normalized features
    cv["games_norm"] = np.clip(cv["games_used"].values / 50.0, 0.0, 1.0)
    cv["thin_flag"] = (cv["games_used"] < 15).astype(float)
    cv["line_norm"] = np.clip(cv["line"].values / 40.0, 0.0, 2.0)
    
    # Home team feature
    if "is_home" not in cv.columns or cv["is_home"].isna().mean() > 0.5:
        if "home_team" in cv.columns and "team" in cv.columns:
            cv["is_home"] = (cv["team"].astype(str).str.upper().str.strip() == 
                           cv["home_team"].astype(str).str.upper().str.strip()).astype(float)
        elif "home" in cv.columns:
            cv["is_home"] = pd.to_numeric(cv["home"], errors="coerce").fillna(0.0).astype(float)
        else:
            cv["is_home"] = 0.0
    cv["is_home_feat"] = cv["is_home"].fillna(0.0).values.astype(float)
    
    # Minutes sensitivity  
    cv["min_sensitivity"] = cv["stat_u"].apply(
        lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0
    ).values.astype(float)
    
    cv["is_under"] = um.astype(float)
    
    # Game total normalization
    _gd_strs = cv["game_date"].astype(str).str[:10].values
    _teams = cv["team"].astype(str).str.upper().str.strip().values
    _gt_vals = np.array([ou_cache.get(g, {}).get(t, 0.0) for g, t in zip(_gd_strs, _teams)])
    cv["game_total_norm"] = np.where(_gt_vals > 0, np.clip(_gt_vals / 230.0 - 1.0, -0.15, 0.15), 0.0)
    
    # Back-to-back games
    _players = cv["player"].astype(str).str.strip().values
    cv["is_b2b"] = np.array([1.0 if (p, g) in b2b_set else 0.0 for p, g in zip(_players, _gd_strs)])
    
    # Demon tier features
    cv["is_demon"] = (cv["tier"] == "DEMON").astype(float)
    cv["logit_p_x_demon"] = cv["logit_p"] * cv["is_demon"]
    
    # Categorical mappings
    cv["stat_cat"] = cv["stat_u"].map(STAT_CATS).fillna(11).astype(int)
    cv["tier_cat"] = cv["tier"].map(TIER_CATS).fillna(0).astype(int)
    
    # Blowout features (already computed in cache)
    cv["q_blowout"] = pd.to_numeric(cv.get("q_blowout", 0.0), errors="coerce").fillna(0.0)
    cv["q_x_under"] = cv["q_blowout"] * cv["is_under"]
    
    # Sportsbook feature (34th feature)
    cv["sb_over_prob"] = 0.5  # default when no sportsbook data available
    
    print("Computing window features from gamelogs...")
    return compute_window_features(cv, player_history, _players, _gd_strs)

def compute_window_features(cv, player_history, _players, _gd_strs):
    """Compute window-based features from player history."""
    n_legs = len(cv)
    hr20 = np.full(n_legs, np.nan)
    hr40 = np.full(n_legs, np.nan)
    margin_arr = np.full(n_legs, np.nan)
    line_dist = np.zeros(n_legs)
    tail_risk = np.zeros(n_legs)
    line_tightness = np.zeros(n_legs)
    rate_cv_arr = np.zeros(n_legs)
    l10_has = np.zeros(n_legs)
    
    _su_arr = cv["stat_u"].values
    _ln_arr = cv["line"].astype(float).values
    _dr_arr = cv["direction"].astype(str).str.upper().values
    
    for i in range(n_legs):
        if i % 10000 == 0:
            print(f"  Processing leg {i}/{n_legs} ({i/n_legs*100:.0f}%)")
        
        pl = _players[i]
        su = _su_arr[i]
        ln = _ln_arr[i]
        dr = _dr_arr[i]
        gd = _gd_strs[i]
        
        actuals = get_recent_stats(player_history, pl, su, gd, n=50)
        if not actuals:
            continue
        
        # 20-game window
        a20 = actuals[-20:]
        if len(a20) >= 5:
            if dr == "OVER":
                h = sum(1 for v in a20 if v >= ln - 1e-9)
            else:
                h = sum(1 for v in a20 if v <= ln + 1e-9)
            hr20[i] = h / len(a20)
            
            mu = np.mean(a20)
            std20 = np.std(a20)
            if mu > 0.1:
                rate_cv_arr[i] = np.clip(std20 / mu, 0, 2.0)
            if ln > 0.5:
                line_dist[i] = np.clip((mu - ln) / ln, -0.5, 0.5)
            if std20 > 0.1 and ln > 0.5:
                tail_risk[i] = np.clip((ln - mu) / std20, -3, 3)
            tight = sum(1 for v in a20 if abs(v - ln) <= 1.5)
            line_tightness[i] = tight / len(a20)
        
        # 10-game window
        a10 = actuals[-10:]
        if len(a10) >= 5:
            l10_has[i] = 1.0
            margins = np.array(a10) - ln
            if dr == "UNDER":
                margins = -margins
            margin_arr[i] = np.clip(np.mean(margins) / max(ln, 1.0), -0.5, 0.5)
        
        # 40-game window
        a40 = actuals[-40:]
        if len(a40) >= 5:
            if dr == "OVER":
                h = sum(1 for v in a40 if v >= ln - 1e-9)
            else:
                h = sum(1 for v in a40 if v <= ln + 1e-9)
            hr40[i] = h / len(a40)
    
    # Assign computed features
    cv["l20_edge"] = np.where(np.isfinite(hr20), hr20 - 0.5, 0.0)
    cv["l10_has"] = l10_has
    cv["l40_hr"] = np.where(np.isfinite(hr40), hr40, -1.0)
    cv["margin"] = np.where(np.isfinite(margin_arr), margin_arr, 0.0)
    cv["line_dist"] = line_dist
    cv["tail_risk"] = tail_risk
    cv["line_tightness"] = line_tightness
    cv["rate_cv"] = rate_cv_arr
    cv["margin_x_under"] = cv["margin"] * cv["is_under"]
    cv["abs_logit_p"] = np.abs(cv["logit_p"])
    
    return cv

def compute_player_te_features(cv):
    """Compute target encoding features."""
    print("Computing target encoding features...")
    
    if "hit" not in cv.columns:
        print("  WARNING: No 'hit' column found, using default values")
        cv["player_te"] = 0.0
        cv["player_stat_te"] = 0.0
        cv["player_dir_te"] = 0.0
        cv["player_n_norm"] = np.clip(
            cv["player"].value_counts().reindex(cv["player"]).fillna(0).values / 200.0, 0.0, 1.0
        )
        return cv
    
    hit_arr = cv["hit"].values.astype(float)
    player_col = cv["player"].astype(str).str.strip().values
    stat_col = cv["stat_u"].values
    dir_col = cv["direction"].astype(str).str.upper().values == "UNDER"
    global_hr = float(hit_arr.mean())
    
    # Build aggregation dictionaries
    pa_full, psa_full, pda_full = {}, {}, {}
    for j in range(len(cv)):
        p, h, s, u = player_col[j], hit_arr[j], stat_col[j], dir_col[j]
        
        # Player overall
        pa_full[p] = (pa_full[p][0] + h, pa_full[p][1] + 1) if p in pa_full else (h, 1)
        
        # Player-stat
        k = (p, s)
        psa_full[k] = (psa_full[k][0] + h, psa_full[k][1] + 1) if k in psa_full else (h, 1)
        
        # Player-direction
        k = (p, u)
        pda_full[k] = (pda_full[k][0] + h, pda_full[k][1] + 1) if k in pda_full else (h, 1)
    
    # Compute smoothed target encoding
    player_te = np.full(len(cv), 0.0)
    player_stat_te = np.full(len(cv), 0.0)
    player_dir_te = np.full(len(cv), 0.0)
    
    for j in range(len(cv)):
        p, s, u = player_col[j], stat_col[j], dir_col[j]
        
        if p in pa_full:
            sh, sc = pa_full[p]
            player_te[j] = (sh + SMOOTH_K * global_hr) / (sc + SMOOTH_K) - global_hr
        
        if (p, s) in psa_full:
            sh, sc = psa_full[(p, s)]
            player_stat_te[j] = (sh + SMOOTH_K * global_hr) / (sc + SMOOTH_K) - global_hr
        
        if (p, u) in pda_full:
            sh, sc = pda_full[(p, u)]
            player_dir_te[j] = (sh + SMOOTH_K * global_hr) / (sc + SMOOTH_K) - global_hr
    
    cv["player_te"] = player_te
    cv["player_stat_te"] = player_stat_te
    cv["player_dir_te"] = player_dir_te
    
    # Player frequency normalization
    pc = pd.Series(player_col).value_counts()
    cv["player_n_norm"] = np.clip(
        pd.Series(player_col).map(pc).fillna(0).values.astype(float) / 200.0, 0.0, 1.0
    )
    
    return cv

def main():
    parser = argparse.ArgumentParser(description="Patch v16 cache to v17 compatibility")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Show what would be done without saving")
    args = parser.parse_args()
    
    print("=== v16 → v17 Cache Patcher ===")
    print()
    
    # Load v16 cache
    v16_cache_path = ROOT / "data/model/_v16_resim_cache.pkl"
    print(f"Loading v16 cache: {v16_cache_path}")
    
    if not v16_cache_path.exists():
        print(f"ERROR: v16 cache not found at {v16_cache_path}")
        return 1
    
    with open(v16_cache_path, "rb") as f:
        v16_cache = pickle.load(f)
    
    cv = v16_cache["cv"].copy()
    print(f"Loaded: {len(cv)} legs, {len(cv.columns)} columns")
    print(f"Date range: {min(v16_cache.get('dates', []))} to {max(v16_cache.get('dates', []))}")
    
    # Check what features are missing  
    existing = set(cv.columns)
    missing = [f for f in FEATS if f not in existing]
    
    print(f"\nFeature analysis:")
    print(f"  v17 requires: {len(FEATS)} features")
    print(f"  v16 cache has: {len([f for f in FEATS if f in existing])} matching")
    print(f"  Missing: {len(missing)} features")
    if missing:
        print(f"  Missing features: {missing}")
    
    if not missing:
        print("\n✓ Cache is already v17-compatible!")
        return 0
    
    if args.dry_run:
        print("\n[DRY RUN] Would engineer all GBM features from raw cache data")
        return 0
    
    # Load supporting data
    print("\nLoading supporting data...")
    ou_cache = load_ou_cache()
    gamelogs = load_gamelogs() 
    player_history = build_player_history(gamelogs)
    b2b_set = build_b2b_set(gamelogs)
    
    # Engineer all GBM features
    cv = engineer_gbm_features(cv, ou_cache, player_history, b2b_set)
    cv = compute_player_te_features(cv)
    
    # Verify we have all required features
    final_missing = [f for f in FEATS if f not in cv.columns]
    if final_missing:
        print(f"\nERROR: Still missing features after engineering: {final_missing}")
        return 1
    
    # Keep only GBM features + essential metadata
    essential_cols = [
        "game_date", "player", "team", "stat", "stat_u", "line", "direction", "tier", "hit"
    ]
    keep_cols = essential_cols + FEATS
    keep_cols = [c for c in keep_cols if c in cv.columns]
    
    cv_gbm = cv[keep_cols].copy()
    print(f"\nRetaining {len(keep_cols)} columns for v17 cache")
    
    # Update cache metadata
    patched_cache = {
        "cv": cv_gbm,
        "dates": v16_cache.get("dates", []),
        "version": "v16_patched_to_v17", 
        "patch_timestamp": time.time(),
        "original_version": v16_cache.get("version", "v16"),
        "gbm_features": FEATS,
        "feature_count": len(FEATS)
    }
    
    # Save as v17-compatible cache
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    print(f"\nSaving v17-compatible cache: {v17_cache_path}")
    
    with open(v17_cache_path, "wb") as f:
        pickle.dump(patched_cache, f)
    
    # Verify the saved cache
    print("Verifying saved cache...")
    with open(v17_cache_path, "rb") as f:
        verify_cache = pickle.load(f)
    
    verify_cv = verify_cache["cv"]
    final_missing = [f for f in FEATS if f not in verify_cv.columns]
    
    print(f"✓ Cache saved: {len(verify_cv)} legs, {len(verify_cv.columns)} columns")
    print(f"✓ Version: {verify_cache.get('version')}")
    print(f"✓ Features: {len([f for f in FEATS if f in verify_cv.columns])}/{len(FEATS)} complete")
    
    if final_missing:
        print(f"ERROR: Still missing features: {final_missing}")
        return 1
    
    print(f"\n🎉 SUCCESS: v16 cache successfully patched to v17 compatibility!")
    print(f"Your v17 model can now use the cache at: {v17_cache_path}")
    print(f"Cache contains all {len(FEATS)} required GBM features")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""Expand v17 bak cache (44 dates, 68 cols) with new dates, preserving ALL enrichment columns.

Unlike expand_v17_cache.py which strips the cache to 42 cols, this script:
  - Starts from _v17_resim_cache.bak.pkl (44 dates, 68 cols — full probability chain)
  - Loads scored_legs_deduped.csv + eval_legs.csv for each new date
  - Engineers GBM features AND preserves all diagnostic enrichment columns
    (p, p_role, p_adj, p_cal, fragility, opp, spread, q_blowout, etc.)
  - Derives is_home from home_team/team, maps p_new=p_adj for new dates
  - Concatenates using union of all columns (NaN padding for any gaps)
  - Saves to _v17_enriched_resim_cache.pkl

Usage:
    python tools/expand_bak_to_enriched_cache.py --dry-run
    python tools/expand_bak_to_enriched_cache.py
    python tools/expand_bak_to_enriched_cache.py --out v17_enriched
"""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from Atlas.core.minutes import minutes_sensitivity

# ------------------------------------------------------------------
# GBM feature contract (exact v9d 33-feature list)
# ------------------------------------------------------------------
FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]
ESSENTIAL_COLS = [
    "game_date", "player", "team", "stat", "stat_u", "line",
    "direction", "tier", "hit",
]
# Diagnostic enrichment columns to preserve from bak and new scored_legs
ENRICH_COLS = [
    "p", "p_role", "p_adj", "p_cal", "p_for_cal", "p_new",
    "fragility", "usage_dep", "opp", "spread", "min_mean", "min_std",
    "minutes_s", "rate_mean", "rate_std", "games_used", "is_home",
    "is_star", "is_questionable", "opp_defense_strength", "thin_window_mult",
    "recent_form_blend", "rotowire_game_spread", "external_prior_score",
    "external_prior_sources", "sb_over_prob",
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

# New dates to add: (date_str, live_run_dir)
# 4-6pm windows chosen for accuracy (post-injury-report, pre-game)
NEW_RUNS: list[tuple[str, str]] = [
    ("2026-05-03", "20260503_143724"),  # 2:37pm — after 2:30pm scheduled
    ("2026-05-04", "20260504_170214"),  # 5:02pm
    ("2026-05-05", "20260505_171724"),  # 5:17pm
]

LIVE_RUNS_DIR = ROOT / "data" / "telemetry" / "live_runs"
BAK_CACHE_PATH = ROOT / "data" / "model" / "_v17_resim_cache.bak.pkl"


# ------------------------------------------------------------------
# Supporting data loaders
# ------------------------------------------------------------------

def load_ou_cache() -> dict:
    iael_dir = ROOT / "data/archives/iael/2026"
    cache: dict = {}
    if not iael_dir.exists():
        return cache
    for dd in sorted(iael_dir.glob("2026-*")):
        rw_files = sorted(dd.glob("*/rotowire_lines.json"))
        if not rw_files:
            continue
        try:
            data = json.loads(rw_files[-1].read_text(encoding="utf-8"))
            lookup: dict = {}
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


def load_gamelogs() -> pd.DataFrame:
    logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
    for col in ["team", "opp"]:
        if col in logs.columns:
            logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)
    print(f"Loaded {len(logs)} gamelog rows, {logs['player'].nunique()} players")
    return logs


def build_player_history(logs: pd.DataFrame) -> dict:
    _sorted = logs.sort_values(["player", "game_date"]).reset_index(drop=True)
    player_history: dict = {}
    stat_cols = ["pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]
    for _, row in _sorted.iterrows():
        player = str(row.get("player", "")).strip()
        gd = row["game_date"]
        if pd.isna(gd) or not player:
            continue
        gd_str = gd.strftime("%Y-%m-%d")
        stats: dict = {}
        for c in stat_cols:
            val = row.get(c)
            if val is not None:
                try:
                    v = float(val)
                    if math.isfinite(v):
                        stats[c] = v
                except (ValueError, TypeError):
                    pass
        if stats:
            player_history.setdefault(player, []).append((gd_str, stats))
    for pl in player_history:
        player_history[pl].sort(key=lambda x: x[0])
    print(f"Built history for {len(player_history)} players")
    return player_history


def build_b2b_set(logs: pd.DataFrame) -> set:
    _gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
    _gl = _gl.sort_values(["player", "game_date"])
    _gl["prev"] = _gl.groupby("player")["game_date"].shift(1)
    _gl["days"] = (_gl["game_date"] - _gl["prev"]).dt.days
    b2b: set = set()
    for _, r in _gl.iterrows():
        if pd.notna(r["days"]) and r["days"] == 1:
            b2b.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))
    print(f"Found {len(b2b)} back-to-back game instances")
    return b2b


def get_recent_stats(player_history: dict, player: str, stat_u: str,
                     game_date_str: str, n: int = 50) -> list:
    hist = player_history.get(player)
    if not hist:
        return []
    cols = STAT_COLUMN_MAP.get(stat_u)
    if not cols:
        return []
    recent = []
    for gd, stats in hist:
        if gd >= game_date_str:
            break
        total = 0.0
        ok = False
        for c in cols:
            if c in stats:
                total += stats[c]
                ok = True
        if ok:
            recent.append(total)
    return recent[-n:]


# ------------------------------------------------------------------
# Feature engineering
# ------------------------------------------------------------------

def engineer_gbm_features(cv: pd.DataFrame, ou_cache: dict,
                           player_history: dict, b2b_set: set) -> pd.DataFrame:
    """Compute all 33 GBM base features in-place. Returns defragmented copy."""
    dir_u = cv["direction"].astype(str).str.upper()
    um = (dir_u == "UNDER").values

    # --- Numeric coercions ---
    num_cols = ["p_new", "rate_mean", "rate_std", "min_mean", "min_std",
                "games_used", "q_blowout", "form_z_line",
                "external_prior_score", "external_prior_n"]
    for col in num_cols:
        if col in cv.columns:
            cv[col] = pd.to_numeric(cv[col], errors="coerce")

    if "p_new" not in cv.columns:
        for fallback in ("p_adj", "p"):
            if fallback in cv.columns and cv[fallback].notna().mean() > 0.5:
                cv["p_new"] = cv[fallback].astype(float)
                print(f"  p_new <- {fallback}")
                break
    cv["logit_p"] = sp_logit(np.clip(cv["p_new"].values, P_LO, P_HI))

    # z_line
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

    _mm = cv["min_mean"].fillna(0.0)
    _ms = cv["min_std"].fillna(0.0)
    cv["min_cv"] = np.where(_mm > 1, np.clip(_ms / _mm, 0, 1), 0.3)
    cv["is_combo"] = cv["stat_u"].isin(COMBOS).astype(float)

    cv["bp_has"] = 0.0
    cv["bp_score_gated"] = 0.0
    if "external_prior_n" in cv.columns:
        has_bp = cv["external_prior_n"].fillna(0) > 0
        cv.loc[has_bp, "bp_has"] = 1.0
        edge = cv["external_prior_score"].fillna(0.0) - cv["line"]
        dm = ((edge > 0) & (dir_u == "OVER")) | ((edge <= 0) & (dir_u == "UNDER"))
        cv.loc[has_bp & dm, "bp_score_gated"] = np.tanh(edge[has_bp & dm] / 3.0)

    cv["is_assists"] = (cv["stat_u"] == "AST").astype(float)
    cv["is_threes"] = (cv["stat_u"] == "FG3M").astype(float)
    cv["games_norm"] = np.clip(cv["games_used"].values / 50.0, 0.0, 1.0)
    cv["thin_flag"] = (cv["games_used"] < 15).astype(float)
    cv["line_norm"] = np.clip(cv["line"].values / 40.0, 0.0, 2.0)

    # is_home
    if "is_home" not in cv.columns or cv["is_home"].isna().mean() > 0.5:
        if "home_team" in cv.columns and "team" in cv.columns:
            cv["is_home"] = (
                cv["team"].astype(str).str.upper().str.strip() ==
                cv["home_team"].astype(str).str.upper().str.strip()
            ).astype(float)
        elif "home" in cv.columns:
            cv["is_home"] = pd.to_numeric(cv["home"], errors="coerce").fillna(0.0)
        else:
            cv["is_home"] = 0.0
    cv["is_home_feat"] = cv["is_home"].fillna(0.0).values.astype(float)

    cv["min_sensitivity"] = cv["stat_u"].apply(
        lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0
    ).values.astype(float)
    cv["is_under"] = um.astype(float)

    _gd_strs = cv["game_date"].astype(str).str[:10].values
    _teams = cv["team"].astype(str).str.upper().str.strip().values
    _gt_vals = np.array([ou_cache.get(g, {}).get(t, 0.0) for g, t in zip(_gd_strs, _teams)])
    cv["game_total_norm"] = np.where(_gt_vals > 0, np.clip(_gt_vals / 230.0 - 1.0, -0.15, 0.15), 0.0)

    _players = cv["player"].astype(str).str.strip().values
    cv["is_b2b"] = np.array([1.0 if (p, g) in b2b_set else 0.0 for p, g in zip(_players, _gd_strs)])

    cv["is_demon"] = (cv["tier"] == "DEMON").astype(float)
    cv["logit_p_x_demon"] = cv["logit_p"] * cv["is_demon"]
    cv["stat_cat"] = cv["stat_u"].map(STAT_CATS).fillna(11).astype(int)
    cv["tier_cat"] = cv["tier"].map(TIER_CATS).fillna(0).astype(int)
    cv["q_blowout"] = pd.to_numeric(cv.get("q_blowout", 0.0), errors="coerce").fillna(0.0)
    cv["q_x_under"] = cv["q_blowout"] * cv["is_under"]

    # Window features from gamelogs
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

    print(f"  Computing window features for {n_legs} legs...")
    for i in range(n_legs):
        if i % 500 == 0 and i > 0:
            print(f"    {i}/{n_legs} ({i/n_legs*100:.0f}%)")
        pl = _players[i]; su = _su_arr[i]; ln = _ln_arr[i]; dr = _dr_arr[i]; gd = _gd_strs[i]
        actuals = get_recent_stats(player_history, pl, su, gd, n=50)
        if not actuals:
            continue
        a20 = actuals[-20:]
        if len(a20) >= 5:
            h = sum(1 for v in a20 if (v >= ln - 1e-9 if dr == "OVER" else v <= ln + 1e-9))
            hr20[i] = h / len(a20)
            mu = np.mean(a20); std20 = np.std(a20)
            if mu > 0.1:
                rate_cv_arr[i] = np.clip(std20 / mu, 0, 2.0)
            if ln > 0.5:
                line_dist[i] = np.clip((mu - ln) / ln, -0.5, 0.5)
            if std20 > 0.1 and ln > 0.5:
                tail_risk[i] = np.clip((ln - mu) / std20, -3, 3)
            tight = sum(1 for v in a20 if abs(v - ln) <= 1.5)
            line_tightness[i] = tight / len(a20)
        a10 = actuals[-10:]
        if len(a10) >= 5:
            l10_has[i] = 1.0
            margins = np.array(a10) - ln
            if dr == "UNDER":
                margins = -margins
            margin_arr[i] = np.clip(np.mean(margins) / max(ln, 1.0), -0.5, 0.5)
        a40 = actuals[-40:]
        if len(a40) >= 5:
            h = sum(1 for v in a40 if (v >= ln - 1e-9 if dr == "OVER" else v <= ln + 1e-9))
            hr40[i] = h / len(a40)

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

    return cv.copy()


def compute_player_te_features(cv: pd.DataFrame) -> pd.DataFrame:
    if "hit" not in cv.columns:
        for f in ("player_te", "player_stat_te", "player_dir_te", "player_n_norm"):
            cv[f] = 0.0
        return cv

    hit_arr = cv["hit"].values.astype(float)
    player_col = cv["player"].astype(str).str.strip().values
    stat_col = cv["stat_u"].values
    dir_col = cv["direction"].astype(str).str.upper().values == "UNDER"
    global_hr = float(hit_arr.mean())

    pa_full: dict = {}; psa_full: dict = {}; pda_full: dict = {}
    for j in range(len(cv)):
        p, h, s, u = player_col[j], hit_arr[j], stat_col[j], dir_col[j]
        pa_full[p] = (pa_full[p][0] + h, pa_full[p][1] + 1) if p in pa_full else (h, 1)
        k = (p, s); psa_full[k] = (psa_full[k][0] + h, psa_full[k][1] + 1) if k in psa_full else (h, 1)
        k = (p, u); pda_full[k] = (pda_full[k][0] + h, pda_full[k][1] + 1) if k in pda_full else (h, 1)

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
    pc = pd.Series(player_col).value_counts()
    cv["player_n_norm"] = np.clip(
        pd.Series(player_col).map(pc).fillna(0).values.astype(float) / 200.0, 0.0, 1.0
    )
    return cv


# ------------------------------------------------------------------
# Per-date loader
# ------------------------------------------------------------------

def load_new_date(date_str: str, run_dir: str) -> pd.DataFrame | None:
    """Load scored_legs + merge hit from eval_legs for a single live-run dir."""
    run_path = LIVE_RUNS_DIR / run_dir
    scored_path = run_path / "scored_legs_deduped.csv"
    eval_path = run_path / "eval_legs.csv"

    if not scored_path.exists():
        print(f"  SKIP {run_dir}: missing scored_legs_deduped.csv")
        return None
    if not eval_path.exists():
        print(f"  SKIP {run_dir}: missing eval_legs.csv")
        return None

    scored = pd.read_csv(scored_path, low_memory=False).copy()
    evalf = pd.read_csv(eval_path, low_memory=False)
    print(f"  {run_dir}: scored={len(scored)} rows {len(scored.columns)} cols, eval={len(evalf)} rows")

    # Merge hit from eval_legs
    if "hit" not in scored.columns:
        key_cols = [c for c in ["player", "stat", "line", "direction"] if c in evalf.columns]
        if "hit" in evalf.columns and key_cols:
            evalf_hit = evalf[key_cols + ["hit"]].drop_duplicates(subset=key_cols)
            scored = scored.merge(evalf_hit, on=key_cols, how="left")
        else:
            print(f"  WARNING: cannot merge hit for {run_dir}")

    # Derive missing enrichment columns
    if "p_new" not in scored.columns:
        for fallback in ("p_adj", "p"):
            if fallback in scored.columns:
                scored["p_new"] = scored[fallback].astype(float)
                break
    if "is_home" not in scored.columns or scored["is_home"].isna().mean() > 0.5:
        if "home_team" in scored.columns and "team" in scored.columns:
            scored["is_home"] = (
                scored["team"].astype(str).str.upper().str.strip() ==
                scored["home_team"].astype(str).str.upper().str.strip()
            ).astype(float)
        elif "home" in scored.columns:
            scored["is_home"] = pd.to_numeric(scored["home"], errors="coerce").fillna(0.0)
        else:
            scored["is_home"] = np.nan
    if "sb_over_prob" not in scored.columns:
        scored["sb_over_prob"] = np.nan   # removed feature; NaN is correct

    # Normalise stat_u
    if "stat_u" not in scored.columns and "stat" in scored.columns:
        scored["stat_u"] = scored["stat"].astype(str).str.upper()
    if "games_used" not in scored.columns:
        scored["games_used"] = 20
    if "game_date" not in scored.columns or scored["game_date"].isna().all():
        scored["game_date"] = date_str

    # Drop rows without hit label
    before = len(scored)
    scored = scored.dropna(subset=["hit"]).reset_index(drop=True)
    if len(scored) < before:
        print(f"  Dropped {before - len(scored)} rows without hit label")
    if len(scored) == 0:
        print(f"  SKIP {run_dir}: 0 rows with hit label")
        return None

    hit_rate = float(scored["hit"].mean())
    print(f"  {run_dir}: {len(scored)} legs with hit labels, hit_rate={hit_rate:.3f}")
    return scored


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Expand bak cache to enriched 68-col cache")
    parser.add_argument("--dry-run", action="store_true", help="Check what would happen without writing")
    parser.add_argument("--out", default="v17_enriched",
                        help="Output cache name stem (default: v17_enriched)")
    args = parser.parse_args()

    out_path = ROOT / "data" / "model" / f"_{args.out}_resim_cache.pkl"

    print("=== Enriched Cache Expansion ===")
    print(f"Base:   {BAK_CACHE_PATH}")
    print(f"Output: {out_path}")
    print()

    # --- Load bak cache ---
    if not BAK_CACHE_PATH.exists():
        print(f"ERROR: bak cache not found: {BAK_CACHE_PATH}")
        return 1

    with open(BAK_CACHE_PATH, "rb") as f:
        bak = pickle.load(f)

    existing_cv = bak["cv"].copy()
    existing_dates = set(str(d)[:10] for d in bak.get("dates", []))
    print(f"Bak cache: {len(existing_cv)} legs, {len(existing_dates)} dates, {len(existing_cv.columns)} cols")
    print(f"Date range: {min(existing_dates)} - {max(existing_dates)}")

    # Verify bak has full enrichment columns
    present_enrich = [c for c in ENRICH_COLS if c in existing_cv.columns]
    missing_enrich = [c for c in ENRICH_COLS if c not in existing_cv.columns]
    print(f"Enrichment cols in bak: {len(present_enrich)}/{len(ENRICH_COLS)}")
    if missing_enrich:
        print(f"  Missing from bak: {missing_enrich}")

    # Verify bak has pre-built GBM features (fast path)
    prebuilt_feats = [f for f in FEATS if f in existing_cv.columns]
    print(f"GBM features pre-built in bak: {len(prebuilt_feats)}/{len(FEATS)}")

    # --- Check which new dates to add ---
    to_add = [(d, r) for d, r in NEW_RUNS if d not in existing_dates]
    skipped = [(d, r) for d, r in NEW_RUNS if d in existing_dates]
    if skipped:
        for d, _ in skipped:
            print(f"  SKIP {d}: already in bak cache")
    if not to_add:
        print("\nAll target dates already in bak cache. Nothing to do.")
        return 0

    print(f"\nDates to add: {[d for d, _ in to_add]}")

    if args.dry_run:
        print("\n[DRY RUN] Would add the above dates from:")
        for d, r in to_add:
            rp = LIVE_RUNS_DIR / r
            sl = (rp / "scored_legs_deduped.csv").exists()
            el = (rp / "eval_legs.csv").exists()
            print(f"  {d}  {r}  scored={sl}  eval={el}")
        print("Re-run without --dry-run to apply.")
        return 0

    # --- Load supporting data ---
    print("\nLoading supporting data for window feature computation...")
    ou_cache = load_ou_cache()
    gamelogs = load_gamelogs()
    player_history = build_player_history(gamelogs)
    b2b_set = build_b2b_set(gamelogs)

    # --- Process each new date ---
    new_frames: list[pd.DataFrame] = []
    added_dates: list[str] = []

    for date_str, run_dir in to_add:
        print(f"\nProcessing {date_str} from {run_dir}...")
        df = load_new_date(date_str, run_dir)
        if df is None:
            continue

        # Engineer GBM features
        df = engineer_gbm_features(df.copy(), ou_cache, player_history, b2b_set)
        df = compute_player_te_features(df)

        # Verify all 33 GBM features present
        missing_feats = [f for f in FEATS if f not in df.columns]
        if missing_feats:
            print(f"  ERROR: missing GBM features {missing_feats} for {date_str} — skipping")
            continue

        new_frames.append(df)
        added_dates.append(date_str)
        print(f"  OK: {len(df)} legs, {len(df.columns)} cols")

    if not new_frames:
        print("\nNo new dates successfully processed. Aborting.")
        return 1

    # --- Concat using UNION of all columns (preserves all 68 bak cols + any new cols) ---
    print(f"\nConcatenating {len(existing_cv)} bak rows + {sum(len(f) for f in new_frames)} new rows...")
    all_frames = [existing_cv] + new_frames
    combined = pd.concat(all_frames, ignore_index=True, sort=False)
    combined["game_date"] = combined["game_date"].astype(str).str[:10]

    all_dates = sorted(existing_dates | set(added_dates))

    # Stats
    n_enriched = 0
    for c in ENRICH_COLS:
        if c in combined.columns and combined[c].notna().mean() > 0.5:
            n_enriched += 1

    n_feats_ok = sum(1 for f in FEATS if f in combined.columns)
    hit_col = combined["hit"].astype(float) if "hit" in combined.columns else None
    p_col = next((combined[c].astype(float) for c in ["p_adj", "p_new", "p"]
                  if c in combined.columns), None)
    brier = float(((hit_col - p_col) ** 2).mean()) if hit_col is not None and p_col is not None else 0.0

    # --- Save ---
    updated_cache = {
        "cv": combined,
        "dates": all_dates,
        "version": f"{args.out}_enriched",
        "patch_timestamp": time.time(),
        "source": str(BAK_CACHE_PATH.name),
        "gbm_features": FEATS,
        "feature_count": len(FEATS),
        "raw_brier": brier,
        "enrichment_cols": ENRICH_COLS,
    }

    print(f"\nSaving to {out_path} ...")
    with open(out_path, "wb") as f:
        pickle.dump(updated_cache, f)

    # --- Verify ---
    with open(out_path, "rb") as f:
        verify = pickle.load(f)
    vcv = verify["cv"]

    print(f"\n=== DONE ===")
    print(f"  Legs:         {len(existing_cv)} + {len(combined) - len(existing_cv)} = {len(vcv)}")
    print(f"  Dates:        {len(all_dates)} total ({len(added_dates)} added: {added_dates})")
    print(f"  Columns:      {len(vcv.columns)} total")
    print(f"  GBM features: {n_feats_ok}/{len(FEATS)} present")
    print(f"  Enrich cols with >50% coverage: {n_enriched}/{len(ENRICH_COLS)}")
    print(f"  Raw Brier:    {brier:.6f}")
    print(f"  Hit rate:     {vcv['hit'].mean():.4f}" if "hit" in vcv.columns else "")

    # Column coverage report
    print(f"\nEnrichment column coverage in combined cache:")
    for c in ENRICH_COLS:
        if c in vcv.columns:
            cov = vcv[c].notna().mean() * 100
            print(f"  {c:30s}  {cov:5.1f}%")
        else:
            print(f"  {c:30s}  ABSENT")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Feature Discovery Automator — systematic GBM feature screening via 1-seed LODO.

Loads the resim cache, builds the base 33 features (v9d architecture), then
systematically screens candidate features by adding each one at a time and
measuring the LODO Brier delta.  After individual screening, runs a greedy
forward-selection pass to find the best multi-feature combination.

Usage:
    python scripts/experiments/feature_discovery.py                     # v14 cache (default)
    python scripts/experiments/feature_discovery.py --cache v12         # older cache
    python scripts/experiments/feature_discovery.py --top 10            # top-10 greedy pass
    python scripts/experiments/feature_discovery.py --seed 65536        # specific screening seed
    python scripts/experiments/feature_discovery.py --full-seeds        # all 7 seeds (slow but precise)
    python scripts/experiments/feature_discovery.py --skip-base         # skip baseline if already known
"""
import sys, pathlib, warnings, time, json, math, argparse, pickle

sys.path.insert(0, str(pathlib.Path(r"c:/Users/rick/projects/Atlas/src")))
sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit, expit as sp_expit
import lightgbm as lgb

from Atlas.core.fingerprint import build_manifest, config_fingerprint
from Atlas.core.minutes import minutes_sensitivity

ROOT = pathlib.Path(r"c:/Users/rick/projects/Atlas")

# ===================================================================
# CLI
# ===================================================================
parser = argparse.ArgumentParser(description="Feature Discovery Automator")
parser.add_argument("--cache", choices=["v12", "v13", "v14", "v15"], default="v15",
                    help="Which resim cache (default: v14)")
parser.add_argument("--top", type=int, default=5,
                    help="Greedy forward-selection depth (default: 5)")
parser.add_argument("--seed", type=int, default=65536,
                    help="Single LODO seed for screening (default: 65536)")
parser.add_argument("--full-seeds", action="store_true",
                    help="Use all 7 seeds instead of 1 (7x slower but precise)")
parser.add_argument("--skip-base", action="store_true",
                    help="Skip baseline LODO (use cached value)")
parser.add_argument("--temp", type=float, default=1.08,
                    help="Temperature for LODO evaluation (default: 1.08)")
args = parser.parse_args()

ALL_SEEDS = [65536, 9999, 137, 999, 98765, 54321, 12345]
SCREEN_SEEDS = ALL_SEEDS if args.full_seeds else [args.seed]

# ===================================================================
# GBM architecture (v9d contract)
# ===================================================================
PARAMS_OVER = {
    "objective": "binary", "metric": "binary_logloss",
    "max_depth": 8, "num_leaves": 30,
    "learning_rate": 0.03, "min_child_samples": 200,
    "feature_fraction": 0.8, "bagging_fraction": 0.8,
    "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1,
}
PARAMS_UNDER = {
    "objective": "binary", "metric": "binary_logloss",
    "max_depth": 11, "num_leaves": 50,
    "learning_rate": 0.03, "min_child_samples": 150,
    "feature_fraction": 0.8, "bagging_fraction": 0.8,
    "bagging_freq": 1, "lambda_l2": 6.0, "verbose": -1,
}
N_ROUNDS = 200
SMOOTH_K = 20
TEMPERATURE = args.temp
P_LO, P_HI = 0.03, 0.97

BASE_FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]
CAT_FEATURES = ["stat_cat", "tier_cat"]

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

# ===================================================================
# Load cache
# ===================================================================
CACHE_PATHS = {
    "v12": ROOT / "data" / "model" / "_v12_resim_cache.pkl",
    "v13": ROOT / "data" / "model" / "_v13_resim_cache.pkl",
    "v14": ROOT / "data" / "model" / "_v14_resim_cache.pkl",
    "v15": ROOT / "data" / "model" / "_v15_resim_cache.pkl",
}
CACHE_PATH = CACHE_PATHS[args.cache]
if not CACHE_PATH.exists():
    print(f"ERROR: Cache not found: {CACHE_PATH}")
    sys.exit(1)

print(f"Cache: {CACHE_PATH}")
with open(CACHE_PATH, "rb") as f:
    cache = pickle.load(f)
cv = cache["cv"].copy()
dates = cache["dates"]
print(f"  {len(cv)} legs, {len(dates)} dates")

# Drop legs without truth labels
if "hit" in cv.columns:
    n_before = len(cv)
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    if n_before - len(cv) > 0:
        dates = sorted(cv["game_date"].astype(str).str[:10].unique())
        print(f"  Dropped {n_before - len(cv)} legs without hit -> {len(cv)} legs, {len(dates)} dates")

if "p_new" in cv.columns and cv["p_new"].isna().mean() > 0.5:
    if "p" in cv.columns and cv["p"].notna().mean() > 0.5:
        cv["p_new"] = cv["p"].astype(float)

# ===================================================================
# Build base features (replicating gbm_v17_train.py exactly)
# ===================================================================
print("\nBuilding base features ...")
t0 = time.time()

dir_u = cv["direction"].astype(str).str.upper()
um = (dir_u == "UNDER").values

_num_cols = ["p_new", "rate_mean", "rate_std", "min_mean", "min_std",
             "games_used", "q_blowout", "form_z_line",
             "external_prior_score", "external_prior_n"]
for col in _num_cols:
    if col in cv.columns:
        cv[col] = pd.to_numeric(cv[col], errors="coerce")

cv["logit_p"] = sp_logit(np.clip(cv["p_new"].values, P_LO, P_HI))

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

cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
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
cv["is_under"] = um.astype(float)

if "is_home" in cv.columns and cv["is_home"].isna().mean() > 0.5:
    if "home" in cv.columns:
        cv["is_home"] = cv["home"].astype(float)
cv["is_home_feat"] = cv["is_home"].fillna(0.0).values.astype(float)
cv["min_sensitivity"] = cv["stat_u"].apply(
    lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0
).values.astype(float)

# game_total_norm (from rotowire archives)
def _load_rotowire_ou(gd_str):
    dd = ROOT / "data/archives/iael/2026" / gd_str
    if not dd.exists():
        return {}
    rw = sorted(dd.glob("*/rotowire_lines.json"))
    if not rw:
        return {}
    try:
        d = json.loads(rw[-1].read_text(encoding="utf-8"))
        lk = {}
        for ev in d.get("events", []):
            h = str(ev.get("homeTeam", "")).upper()
            a = str(ev.get("awayTeam", "")).upper()
            ou = float(ev.get("ou", 0))
            if ou > 0:
                lk[h] = ou; lk[a] = ou
        return lk
    except Exception:
        return {}

_ou_cache = {}
iael_dir = ROOT / "data/archives/iael/2026"
if iael_dir.exists():
    for dd in sorted(iael_dir.glob("2026-*")):
        ou = _load_rotowire_ou(dd.name)
        if ou:
            _ou_cache[dd.name] = ou

_gd_strs = cv["game_date"].astype(str).str[:10].values
_teams = cv["team"].astype(str).str.upper().str.strip().values
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}
_gt_vals = np.array([_ou_cache.get(g, {}).get(t, 0.0) for g, t in zip(_gd_strs, _teams)])
cv["game_total_norm"] = np.where(_gt_vals > 0, np.clip(_gt_vals / 230.0 - 1.0, -0.15, 0.15), 0.0)

# is_b2b
logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
logs = logs.sort_values(["player", "game_date"]).reset_index(drop=True)
for col in ["team", "opp"]:
    logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)
_gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
_gl = _gl.sort_values(["player", "game_date"])
_gl["prev"] = _gl.groupby("player")["game_date"].shift(1)
_gl["days"] = (_gl["game_date"] - _gl["prev"]).dt.days
b2b_set = set()
for _, r in _gl.iterrows():
    if pd.notna(r["days"]) and r["days"] == 1:
        b2b_set.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))
_players = cv["player"].astype(str).str.strip().values
cv["is_b2b"] = np.array([1.0 if (p, g) in b2b_set else 0.0 for p, g in zip(_players, _gd_strs)])

cv["is_demon"] = (cv["tier"] == "DEMON").astype(float)
cv["logit_p_x_demon"] = cv["logit_p"] * cv["is_demon"]
cv["stat_cat"] = cv["stat_u"].map(STAT_CATS).fillna(11).astype(int)
cv["tier_cat"] = cv["tier"].map(TIER_CATS).fillna(0).astype(int)
cv["q_blowout"] = pd.to_numeric(cv.get("q_blowout", 0.0), errors="coerce").fillna(0.0)
cv["q_x_under"] = cv["q_blowout"] * cv["is_under"]

# Window features from gamelogs
print("Computing window features ...")
_logs_sorted = logs.sort_values(["player", "game_date"]).reset_index(drop=True)
player_history = {}
for _, row in _logs_sorted.iterrows():
    pl = str(row.get("player", "")).strip()
    gd = row["game_date"]
    if pd.isna(gd):
        continue
    gd_str = gd.strftime("%Y-%m-%d")
    stats = {}
    for c in ["pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]:
        val = row.get(c)
        if val is not None:
            try:
                v = float(val)
                if math.isfinite(v):
                    stats[c] = v
            except (ValueError, TypeError):
                pass
    if pl and stats:
        player_history.setdefault(pl, []).append((gd_str, stats))
for p in player_history:
    player_history[p].sort(key=lambda x: x[0])

def _get_recent(player, stat_u, game_date_str, n=50):
    hist = player_history.get(player)
    if not hist:
        return []
    cols = STAT_COLUMN_MAP.get(stat_u)
    if not cols:
        return []
    recent = []
    for gd, st in hist:
        if gd >= game_date_str:
            break
        total = 0.0
        ok = False
        for c in cols:
            if c in st:
                total += st[c]; ok = True
        if ok:
            recent.append(total)
    return recent[-n:]

hr20 = np.full(len(cv), np.nan)
hr40 = np.full(len(cv), np.nan)
margin_arr = np.full(len(cv), np.nan)
line_dist = np.zeros(len(cv))
tail_risk = np.zeros(len(cv))
line_tightness = np.zeros(len(cv))
rate_cv_arr = np.zeros(len(cv))
l10_has = np.zeros(len(cv))

_su_arr = cv["stat_u"].values
_ln_arr = cv["line"].astype(float).values
_dr_arr = cv["direction"].astype(str).str.upper().values

for i in range(len(cv)):
    pl = _players[i]; su = _su_arr[i]; ln = _ln_arr[i]; dr = _dr_arr[i]; gd = _gd_strs[i]
    actuals = _get_recent(pl, su, gd, n=50)
    if not actuals:
        continue
    a20 = actuals[-20:]
    if len(a20) >= 5:
        if dr == "OVER":
            h = sum(1 for v in a20 if v >= ln - 1e-9)
        else:
            h = sum(1 for v in a20 if v <= ln + 1e-9)
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
        if dr == "OVER":
            h = sum(1 for v in a40 if v >= ln - 1e-9)
        else:
            h = sum(1 for v in a40 if v <= ln + 1e-9)
        hr40[i] = h / len(a40)
    if (i + 1) % 50000 == 0:
        print(f"  {i+1}/{len(cv)} ({(i+1)/len(cv)*100:.0f}%)")

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

# Player TE (full data — matches trainer)
print("Computing player TE ...")
hit_arr = cv["hit"].values.astype(float)
player_col = cv["player"].astype(str).str.strip().values
stat_col = cv["stat_u"].values
global_hr = float(hit_arr.mean())
pa_full, psa_full, pda_full = {}, {}, {}
for j in range(len(cv)):
    p, h, s, u = player_col[j], hit_arr[j], stat_col[j], um[j]
    pa_full[p] = (pa_full[p][0] + h, pa_full[p][1] + 1) if p in pa_full else (h, 1)
    k = (p, s)
    psa_full[k] = (psa_full[k][0] + h, psa_full[k][1] + 1) if k in psa_full else (h, 1)
    k = (p, u)
    pda_full[k] = (pda_full[k][0] + h, pda_full[k][1] + 1) if k in pda_full else (h, 1)

player_te = np.full(len(cv), 0.0)
player_stat_te = np.full(len(cv), 0.0)
player_dir_te = np.full(len(cv), 0.0)
for j in range(len(cv)):
    p, s, u = player_col[j], stat_col[j], um[j]
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

print(f"Base features built ({time.time() - t0:.1f}s)")

# ===================================================================
# Define candidate features
# ===================================================================
def _safe(col, fill=0.0, lo=None, hi=None):
    """Extract numeric column safely."""
    vals = pd.to_numeric(cv.get(col, fill), errors="coerce").fillna(fill).values.astype(float)
    if lo is not None or hi is not None:
        vals = np.clip(vals, lo, hi)
    return vals

CANDIDATES = {}

# --- Direct columns from the cache ---
CANDIDATES["opp_defense_rel"]   = lambda: _safe("form_opp_defense_rel", 0.0, -0.3, 0.3)
CANDIDATES["pace_factor"]       = lambda: _safe("form_pace_factor", 0.0, -0.15, 0.15)
CANDIDATES["fragility_feat"]    = lambda: _safe("fragility", 0.0, 0.0, 0.5)
CANDIDATES["usage_dep_feat"]    = lambda: _safe("usage_dep", 1.0, 0.5, 1.5) - 1.0
CANDIDATES["spread_norm"]       = lambda: _safe("spread", 0.0, -15, 15) / 15.0
CANDIDATES["under_frag_feat"]   = lambda: _safe("under_frag", 0.0, 0.0, 0.3)
CANDIDATES["role_ctx_outs_n"]   = lambda: np.clip(_safe("role_ctx_outs_used", 0), 0, 5)
CANDIDATES["role_ctx_mult_feat"]= lambda: _safe("role_ctx_mult", 1.0) - 1.0
CANDIDATES["min_s_close"]       = lambda: _safe("minutes_s_close", 0.0, 0.0, 1.0)
CANDIDATES["min_s_blowout"]     = lambda: _safe("minutes_s_blowout", 0.0, 0.0, 1.0)
CANDIDATES["usage_burden"]      = lambda: _safe("usage_burden_ratio", 1.0, 0.5, 2.0) - 1.0
CANDIDATES["form_opp_rate_shift"] = lambda: _safe("form_opp_rate_shift", 0.0, -0.1, 0.1)
CANDIDATES["blowout_drop"]     = lambda: _safe("blowout_minute_drop", 0.0, 0.0, 10.0) / 10.0
CANDIDATES["q_blowout_spread_only"] = lambda: _safe("q_blowout_spread_only", 0.0, 0.0, 1.0)
CANDIDATES["under_relief_haircut"] = lambda: _safe("under_relief_haircut", 0.0, 0.0, 0.15)
CANDIDATES["min_mean_norm"]     = lambda: _safe("min_mean", 25.0, 10, 40) / 40.0
CANDIDATES["rate_mean_raw"]     = lambda: _safe("rate_mean", 0.0, 0.0, 2.0)
CANDIDATES["fragility_gap_core"]= lambda: _safe("fragility_gap_core", 0.0, 0.0, 0.2)
CANDIDATES["under_frag_gap"]    = lambda: _safe("under_frag_gap", 0.0, 0.0, 0.2)

# --- Interactions ---
CANDIDATES["logit_p_x_combo"]   = lambda: cv["logit_p"].values * cv["is_combo"].values
CANDIDATES["z_line_x_under"]    = lambda: cv["z_line"].values * cv["is_under"].values
CANDIDATES["opp_def_x_under"]   = lambda: _safe("form_opp_defense_rel", 0.0, -0.3, 0.3) * cv["is_under"].values
CANDIDATES["frag_x_under"]      = lambda: _safe("fragility", 0.0, 0.0, 0.5) * cv["is_under"].values
CANDIDATES["spread_x_under"]    = lambda: (_safe("spread", 0.0, -15, 15) / 15.0) * cv["is_under"].values
CANDIDATES["pace_x_logit"]      = lambda: _safe("form_pace_factor", 0.0, -0.15, 0.15) * cv["logit_p"].values
CANDIDATES["margin_x_combo"]    = lambda: cv["margin"].values * cv["is_combo"].values
CANDIDATES["q_blowout_x_combo"] = lambda: cv["q_blowout"].values * cv["is_combo"].values
CANDIDATES["logit_p_x_under"]   = lambda: cv["logit_p"].values * cv["is_under"].values
CANDIDATES["z_line_x_combo"]    = lambda: cv["z_line"].values * cv["is_combo"].values
CANDIDATES["tail_risk_x_under"] = lambda: cv["tail_risk"].values * cv["is_under"].values
CANDIDATES["line_norm_x_minsens"] = lambda: cv["line_norm"].values * cv["min_sensitivity"].values
CANDIDATES["games_norm_x_under"]= lambda: cv["games_norm"].values * cv["is_under"].values
CANDIDATES["bp_has_x_under"]    = lambda: cv["bp_has"].values * cv["is_under"].values

# --- Transformations ---
CANDIDATES["logit_p_sq"]        = lambda: cv["logit_p"].values ** 2
CANDIDATES["z_line_abs"]        = lambda: np.abs(cv["z_line"].values)
CANDIDATES["z_line_sq"]         = lambda: cv["z_line"].values ** 2
CANDIDATES["spread_abs"]        = lambda: np.abs(_safe("spread", 0.0, -15, 15)) / 15.0
CANDIDATES["log_line"]          = lambda: np.log1p(np.clip(cv["line"].values, 0.5, 60))
CANDIDATES["rate_std_norm"]     = lambda: _safe("rate_std", 0.0, 0.0, 1.0)

print(f"\n{len(CANDIDATES)} candidate features defined")

# ===================================================================
# LODO engine (streamlined for screening)
# ===================================================================
sorted_dates = sorted(dates)
date_arr = cv["game_date"].astype(str).str[:10].values


def run_lodo(feat_list, seeds, label=""):
    """Run LODO with given features and seeds. Returns (brier, per_fold_briers)."""
    cat_idx = [feat_list.index(f) for f in CAT_FEATURES if f in feat_list]
    X = np.nan_to_num(cv[feat_list].values.astype(float), nan=0.0)
    y = hit_arr

    oof = np.full(len(cv), np.nan)
    fold_briers = []

    for holdout_date in sorted_dates:
        hd = str(holdout_date)[:10]
        test_mask = date_arr == hd
        train_mask = ~test_mask
        n_test = int(test_mask.sum())
        if n_test == 0:
            continue

        X_train, y_train = X[train_mask], y[train_mask]
        X_test = X[test_mask]
        over_train = ~um[train_mask]
        under_train = um[train_mask]
        over_test = ~um[test_mask]
        under_test = um[test_mask]

        fold_preds = np.zeros(n_test, dtype=float)
        for seed in seeds:
            po = {**PARAMS_OVER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
            pu = {**PARAMS_UNDER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}

            if over_train.sum() > 0 and over_test.sum() > 0:
                dtrain = lgb.Dataset(X_train[over_train], label=y_train[over_train],
                                     feature_name=feat_list, categorical_feature=cat_idx, free_raw_data=False)
                bst = lgb.train(po, dtrain, num_boost_round=N_ROUNDS)
                fold_preds[over_test] += bst.predict(X_test[over_test])

            if under_train.sum() > 0 and under_test.sum() > 0:
                dtrain = lgb.Dataset(X_train[under_train], label=y_train[under_train],
                                     feature_name=feat_list, categorical_feature=cat_idx, free_raw_data=False)
                bst = lgb.train(pu, dtrain, num_boost_round=N_ROUNDS)
                fold_preds[under_test] += bst.predict(X_test[under_test])

        fold_preds /= len(seeds)
        oof[test_mask] = fold_preds

        fb = float(np.mean((fold_preds - y[test_mask]) ** 2))
        fold_briers.append((hd, n_test, fb))

    valid = ~np.isnan(oof)
    oof_logit = sp_logit(np.clip(oof[valid], 0.001, 0.999))
    p_T = sp_expit(oof_logit / TEMPERATURE)
    brier = float(np.mean((p_T - y[valid]) ** 2))
    return brier, fold_briers


# ===================================================================
# Phase 1: Baseline
# ===================================================================
print(f"\n{'='*70}")
print(f"PHASE 1: Baseline LODO ({len(BASE_FEATS)} features, {len(SCREEN_SEEDS)} seed(s), T={TEMPERATURE})")
print(f"{'='*70}")

if args.skip_base:
    # Use known v14 baseline
    baseline_brier = 0.198097
    print(f"  Using cached baseline: {baseline_brier:.6f}")
else:
    t1 = time.time()
    baseline_brier, _ = run_lodo(BASE_FEATS, SCREEN_SEEDS, "baseline")
    print(f"  Baseline LODO Brier: {baseline_brier:.6f}  ({time.time()-t1:.1f}s)")

# ===================================================================
# Phase 2: Individual feature screening
# ===================================================================
print(f"\n{'='*70}")
print(f"PHASE 2: Individual screening ({len(CANDIDATES)} candidates)")
print(f"{'='*70}")

results = []
for idx, (name, builder) in enumerate(sorted(CANDIDATES.items())):
    t_start = time.time()
    try:
        cv[name] = builder()
        nan_frac = pd.to_numeric(cv[name], errors="coerce").isna().mean()
        if nan_frac > 0.5:
            print(f"  [{idx+1:2d}/{len(CANDIDATES)}] {name:30s}  SKIP — {nan_frac:.0%} NaN")
            cv.drop(columns=[name], inplace=True, errors="ignore")
            continue

        test_feats = BASE_FEATS + [name]
        brier, _ = run_lodo(test_feats, SCREEN_SEEDS, name)
        delta_mB = (brier - baseline_brier) * 1000
        elapsed = time.time() - t_start
        results.append((name, brier, delta_mB))
        marker = " ***" if delta_mB < -0.1 else (" BAD" if delta_mB > 0.5 else "")
        print(f"  [{idx+1:2d}/{len(CANDIDATES)}] {name:30s}  Brier={brier:.6f}  "
              f"delta={delta_mB:+.3f}mB  ({elapsed:.0f}s){marker}")
    except Exception as e:
        print(f"  [{idx+1:2d}/{len(CANDIDATES)}] {name:30s}  ERROR: {e}")

# Sort by delta
results.sort(key=lambda x: x[2])

print(f"\n{'='*70}")
print(f"INDIVIDUAL SCREENING RESULTS (baseline={baseline_brier:.6f})")
print(f"{'='*70}")
print(f"{'Feature':35s}  {'Brier':>10s}  {'Delta mB':>10s}  {'Verdict':>8s}")
print("-" * 70)
for name, brier, delta in results:
    verdict = "BETTER" if delta < -0.05 else ("WORSE" if delta > 0.05 else "FLAT")
    print(f"{name:35s}  {brier:10.6f}  {delta:+10.3f}  {verdict:>8s}")

# ===================================================================
# Phase 3: Greedy forward selection (top-K)
# ===================================================================
improving = [r for r in results if r[2] < -0.01]
if not improving:
    print(f"\nNo candidates improved baseline. Stopping.")
    sys.exit(0)

top_n = min(args.top, len(improving))
print(f"\n{'='*70}")
print(f"PHASE 3: Greedy forward selection (top {top_n} from {len(improving)} improvers)")
print(f"{'='*70}")

selected = []
current_feats = list(BASE_FEATS)
current_brier = baseline_brier

for step in range(top_n):
    best_name, best_brier, best_delta = None, current_brier, 0.0
    remaining = [r[0] for r in improving if r[0] not in selected]
    if not remaining:
        break

    for cand_name in remaining:
        if cand_name not in cv.columns:
            cv[cand_name] = CANDIDATES[cand_name]()
        test_feats = current_feats + [cand_name]
        brier, _ = run_lodo(test_feats, SCREEN_SEEDS, f"greedy+{cand_name}")
        delta = (brier - current_brier) * 1000
        if brier < best_brier:
            best_name, best_brier, best_delta = cand_name, brier, delta

    if best_name is None or best_brier >= current_brier:
        print(f"  Step {step+1}: No further improvement. Stopping greedy.")
        break

    selected.append(best_name)
    current_feats.append(best_name)
    print(f"  Step {step+1}: +{best_name:30s}  Brier={best_brier:.6f}  "
          f"cum_delta={(best_brier - baseline_brier)*1000:+.3f}mB  "
          f"step_delta={best_delta:+.3f}mB")
    current_brier = best_brier

# ===================================================================
# Final summary
# ===================================================================
print(f"\n{'='*70}")
print(f"FINAL SUMMARY")
print(f"{'='*70}")
print(f"Baseline ({len(BASE_FEATS)} features): {baseline_brier:.6f}")
if selected:
    print(f"Best combo ({len(BASE_FEATS)}+{len(selected)} features): {current_brier:.6f}  "
          f"({(current_brier - baseline_brier)*1000:+.3f} mB)")
    print(f"Selected features: {selected}")
    print(f"\nTo train with these features:")
    print(f"  python tools/gbm_v17_train.py --cache {args.cache} --extra-feats {' '.join(selected)}")
else:
    print("No features survived greedy selection.")

# Save results to YAML
out_path = ROOT / "tools" / "feature_discovery_results.yaml"
import yaml
with open(ROOT / "config.yaml") as _cf:
    _full_cfg = yaml.safe_load(_cf)
out = {
    "_manifest": build_manifest(
        source="feature_discovery", cfg=_full_cfg,
        ensemble_dir=_full_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    ),
    "cache": args.cache,
    "baseline_brier": float(baseline_brier),
    "temperature": TEMPERATURE,
    "seeds": SCREEN_SEEDS,
    "n_legs": len(cv),
    "n_dates": len(dates),
    "individual_results": [
        {"feature": name, "brier": float(brier), "delta_mB": float(delta)}
        for name, brier, delta in results
    ],
    "greedy_selected": selected,
    "greedy_final_brier": float(current_brier),
    "greedy_delta_mB": float((current_brier - baseline_brier) * 1000),
    "train_command": f"python tools/gbm_v17_train.py --cache {args.cache} --extra-feats {' '.join(selected)}" if selected else None,
}
with open(out_path, "w") as f:
    yaml.dump(out, f, default_flow_style=False, sort_keys=False)
print(f"\nResults saved to {out_path}")

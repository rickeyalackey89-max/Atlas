"""
GBM ensemble trainer -- LODO cross-validation, temperature calibration,
and safe promotion with regression guard.

Trains a 7-seed x 2-direction LightGBM ensemble on a resim cache,
evaluates via leave-one-date-out Brier, sweeps temperature, and
optionally promotes to production (data/model/ensemble/).

Promotion is BLOCKED if the new LODO Brier is worse than the current
production ensemble (read from ensemble_meta.json).  Use --force-promote
to override the guard.

Usage:
    python tools/gbm_v12_train.py --cache v17 --extra-feats opp_defense_rel z_line_abs fragility_feat bp_has_x_under
    python tools/gbm_v12_train.py --cache v17 --promote --extra-feats opp_defense_rel z_line_abs fragility_feat bp_has_x_under
    python tools/gbm_v12_train.py --cache v17 --force-promote --extra-feats ...
"""
import sys, pathlib, warnings, time, json, math, argparse, pickle

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit, expit as sp_expit
import lightgbm as lgb

from Atlas.core.fingerprint import build_manifest, config_fingerprint
from Atlas.core.minutes import minutes_sensitivity

# ROOT already defined above

# ===================================================================
# CLI
# ===================================================================
parser = argparse.ArgumentParser(description="GBM ensemble trainer with safe promotion")
parser.add_argument("--cache", choices=["v9", "v12", "v13", "v14", "v15", "v16", "v17"],
                    default="v12", help="Which resim cache to train on")
parser.add_argument("--promote", action="store_true",
                    help="Promote to data/model/ensemble/ after safety check")
parser.add_argument("--force-promote", action="store_true",
                    help="Promote even if LODO regresses vs current production")
parser.add_argument("--extra-feats", nargs="*", default=[],
                    help="Additional features beyond the 33 base")
args = parser.parse_args()

if args.force_promote:
    args.promote = True

# ===================================================================
# Architecture (exact v9d contract -- 34 features, 7 seeds)
# ===================================================================
SEEDS = [65536, 9999, 137, 999, 98765, 54321, 12345]
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
TEMP_CANDIDATES = [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12]

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
CAT_FEATURES = ["stat_cat", "tier_cat"]
CAT_IDX = [FEATS.index(f) for f in CAT_FEATURES]

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

CACHE_PATHS = {
    "v9":  pathlib.Path(r"D:/AtlasTestMarch26/model_backups/_v9_resim_cache.pkl"),
    "v12": ROOT / "data" / "model" / "_v12_resim_cache.pkl",
    "v13": ROOT / "data" / "model" / "_v13_resim_cache.pkl",
    "v14": ROOT / "data" / "model" / "_v14_resim_cache.pkl",
    "v15": ROOT / "data" / "model" / "_v15_resim_cache.pkl",
    "v16": ROOT / "data" / "model" / "_v16_resim_cache.pkl",
    "v17": ROOT / "data" / "model" / "_v17_resim_cache.pkl",
    "v17_34feat": ROOT / "data" / "model" / "_v17_34feat_resim_cache.pkl",
}
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}

PRODUCTION_ENS_DIR = ROOT / "data" / "model" / "ensemble"


# ===================================================================
# Promotion safety gate
# ===================================================================
def read_production_lodo():
    """Return (lodo_brier, version) from the current production ensemble, or (None, None)."""
    meta_path = PRODUCTION_ENS_DIR / "ensemble_meta.json"
    if not meta_path.exists():
        return None, None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        return meta.get("lodo_brier_ensemble"), meta.get("version", "unknown")
    except Exception:
        return None, None


def check_promotion_safety(new_brier, force):
    """Check whether promotion is safe.

    Returns (ok, reason, prod_brier).
    """
    prod_brier, prod_version = read_production_lodo()

    if prod_brier is None:
        return True, "No existing production ensemble found -- safe to promote.", None

    delta_mB = (new_brier - prod_brier) * 1000.0

    if new_brier < prod_brier:
        return (True,
                f"IMPROVED vs production ({prod_version}): "
                f"{new_brier:.6f} < {prod_brier:.6f} ({delta_mB:+.3f} mB)",
                prod_brier)

    if new_brier == prod_brier:
        return (True,
                f"EQUAL to production ({prod_version}): {new_brier:.6f}",
                prod_brier)

    # Regression detected
    if force:
        return (True,
                f"REGRESSION vs production ({prod_version}): "
                f"{new_brier:.6f} > {prod_brier:.6f} ({delta_mB:+.3f} mB) "
                f"-- overridden by --force-promote",
                prod_brier)

    return (False,
            f"BLOCKED: LODO {new_brier:.6f} > production {prod_brier:.6f} "
            f"({prod_version}, {delta_mB:+.3f} mB). "
            f"Use --force-promote to override.",
            prod_brier)


# ===================================================================
# Gamelog helpers
# ===================================================================
def load_gamelogs():
    logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
    for col in ["team", "opp"]:
        logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)
    return logs


def build_player_history(logs):
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
    return player_history


def build_b2b_set(logs):
    _gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
    _gl = _gl.sort_values(["player", "game_date"])
    _gl["prev"] = _gl.groupby("player")["game_date"].shift(1)
    _gl["days"] = (_gl["game_date"] - _gl["prev"]).dt.days
    b2b = set()
    for _, r in _gl.iterrows():
        if pd.notna(r["days"]) and r["days"] == 1:
            b2b.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))
    return b2b


def load_ou_cache():
    iael_dir = ROOT / "data/archives/iael/2026"
    cache = {}
    if not iael_dir.exists():
        return cache
    for dd in sorted(iael_dir.glob("2026-*")):
        rw = sorted(dd.glob("*/rotowire_lines.json"))
        if not rw:
            continue
        try:
            d = json.loads(rw[-1].read_text(encoding="utf-8"))
            lk = {}
            for ev in d.get("events", []):
                h = str(ev.get("homeTeam", "")).upper()
                a = str(ev.get("awayTeam", "")).upper()
                ou = float(ev.get("ou", 0))
                if ou > 0:
                    lk[h] = ou
                    lk[a] = ou
            if lk:
                cache[dd.name] = lk
        except Exception:
            pass
    return cache


def get_recent(player_history, player, stat_u, game_date_str, n=50):
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
                total += st[c]
                ok = True
        if ok:
            recent.append(total)
    return recent[-n:]


# ===================================================================
# Sportsbook enrichment (lazy)
# ===================================================================
_SB_ALIAS = {
    "A.J. Green": "AJ Green", "C.J. McCollum": "CJ McCollum",
    "Dennis Schroder": "Dennis Schr\u00f6der", "G.G. Jackson": "GG Jackson",
    "Gary Payton II": "Gary Payton", "Gary Trent Jr": "Gary Trent",
    "Herb Jones": "Herbert Jones", "Jabari Smith Jr": "Jabari Smith",
    "Jaime Jaquez Jr": "Jaime Jaquez", "Justin Champagnie": "Julian Champagnie",
    "Kelly Oubre Jr": "Kelly Oubre", "Kevin Porter Jr.": "Kevin Porter",
    "Kristaps Porzingis": "Kristaps Porzi\u0146\u0123is", "Luka Doncic": "Luka Don\u010di\u0107",
    "Marvin Bagley III": "Marvin Bagley", "Michael Porter Jr": "Michael Porter",
    "Moe Wagner": "Moritz Wagner", "Moussa Diabate": "Moussa Diabat\u00e9",
    "Nicolas Claxton": "Nic Claxton", "Nikola Jokic": "Nikola Joki\u0107",
    "Nikola Vucevic": "Nikola Vu\u010devi\u0107", "Paul Reed Jr": "Paul Reed",
    "R.J. Barrett": "RJ Barrett", "Ron Holland": "Ronald Holland",
    "Scotty Pippen Jr": "Scottie Pippen", "Tim Hardaway Jr": "Tim Hardaway",
    "Trey Murphy III": "Trey Murphy", "Walter Clayton Jr.": "Walter Clayton",
    "Wendell Carter Jr": "Wendell Carter", "Carlton Carrington": "Bub Carrington",
    "Isaiah Stewart II": "Isaiah Stewart",
}
_sb_enriched = False


def enrich_cv_with_sportsbook(cv):
    global _sb_enriched
    if _sb_enriched:
        return
    _sb_enriched = True
    sb_path = ROOT / "data" / "model" / "oddsapi_historical_props.csv"
    if not sb_path.exists():
        print("  WARNING: oddsapi_historical_props.csv not found -- sb features will be NaN")
        cv["sb_over_prob"] = np.nan
        cv["sb_line_diff"] = np.nan
        return
    oa = pd.read_csv(sb_path)
    if "n_books" in oa.columns:
        before = len(oa)
        oa = oa[oa["n_books"] >= 3].copy()
        print(f"  Sportsbook filter: {len(oa)}/{before} rows with n_books >= 3")
    oa["player_norm"] = oa["player"].apply(lambda n: _SB_ALIAS.get(n.strip(), n.strip()))
    cv["player_norm"] = cv["player"].apply(lambda n: _SB_ALIAS.get(n.strip(), n.strip()))
    oa["line"] = oa["line"].astype(float)
    oa["over_prob"] = oa["over_prob"].astype(float)
    oa_agg = oa.groupby(["game_date", "player_norm", "stat", "line"]).agg(
        over_prob=("over_prob", "median")).reset_index()
    cv["_stat_join"] = cv["stat_u"] if "stat_u" in cv.columns else cv["stat"]
    cv["_idx"] = np.arange(len(cv))
    merged = cv[["_idx", "game_date", "player_norm", "_stat_join", "line"]].merge(
        oa_agg.rename(columns={"line": "sb_line", "over_prob": "sb_over_prob_raw", "stat": "_stat_join"}),
        on=["game_date", "player_norm", "_stat_join"], how="left")
    merged["ld"] = abs(merged["line"] - merged["sb_line"])
    has_match = merged["ld"].notna()
    if has_match.any():
        matched = merged[has_match]
        closest_idx = matched.groupby("_idx")["ld"].idxmin()
        closest = matched.loc[closest_idx].set_index("_idx")
        cv["sb_over_prob"] = closest["sb_over_prob_raw"].reindex(cv["_idx"]).values
        cv["sb_line_diff"] = closest["ld"].reindex(cv["_idx"]).values
    else:
        cv["sb_over_prob"] = np.nan
        cv["sb_line_diff"] = np.nan
    cv.drop(columns=["_idx", "player_norm", "_stat_join"], inplace=True, errors="ignore")
    n_matched = cv["sb_over_prob"].notna().sum()
    print(f"  Sportsbook enrichment: {n_matched}/{len(cv)} legs matched "
          f"({100*n_matched/len(cv):.1f}%)")


# ===================================================================
# Feature engineering
# ===================================================================
def compute_features(cv, player_history, b2b_set, ou_cache):
    """Compute all 33 base features on cv. Modifies cv in-place. Returns um array."""
    print("Computing features ...")
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

    if "is_home" not in cv.columns or ("is_home" in cv.columns and cv["is_home"].isna().mean() > 0.5):
        if "home_team" in cv.columns and "team" in cv.columns:
            cv["is_home"] = (cv["team"].astype(str).str.upper().str.strip() == cv["home_team"].astype(str).str.upper().str.strip()).astype(float)
            print(f"  Computed is_home from team/home_team: {cv['is_home'].mean():.1%} home legs")
        elif "home" in cv.columns:
            cv["is_home"] = pd.to_numeric(cv["home"], errors="coerce").fillna(0.0).astype(float)
            print(f"  Computed is_home from home: {cv['is_home'].mean():.1%} home legs")
        else:
            cv["is_home"] = 0.0
            print("  WARN: No home data found, is_home set to 0")
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
    print("Computing window features ...")
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
        pl = _players[i]
        su = _su_arr[i]
        ln = _ln_arr[i]
        dr = _dr_arr[i]
        gd = _gd_strs[i]

        actuals = get_recent(player_history, pl, su, gd, n=50)
        if not actuals:
            continue

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

    print(f"Features done ({time.time() - t0:.1f}s)")
    return um


def compute_player_te(cv, um, dates):
    """Compute player target-encoding features. Returns (pa_full, psa_full, pda_full, global_hr)."""
    print("Computing player TE (full data) ...")
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

    return pa_full, psa_full, pda_full, global_hr


def apply_extra_features(cv, extra_feats):
    """Compute and append extra features to FEATS list."""
    global CAT_IDX
    feat_map = {
        "opp_defense_rel":    lambda: pd.to_numeric(cv.get("form_opp_defense_rel", 0.0), errors="coerce").fillna(0.0).clip(-0.2, 0.2),
        "pace_factor":        lambda: pd.to_numeric(cv.get("form_pace_factor", 0.0), errors="coerce").fillna(0.0).clip(-0.1, 0.1),
        "role_ctx_outs_n":    lambda: np.clip(pd.to_numeric(cv.get("role_ctx_outs_used", 0), errors="coerce").fillna(0).values, 0, 5).astype(float),
        "usage_dep_feat":     lambda: pd.to_numeric(cv.get("usage_dep", 1.0), errors="coerce").fillna(1.0).clip(0.5, 1.5) - 1.0,
        "fragility_feat":     lambda: pd.to_numeric(cv.get("fragility", 0.0), errors="coerce").fillna(0.0).clip(0, 0.3),
        "role_ctx_mult_feat": lambda: pd.to_numeric(cv.get("role_ctx_mult", 1.0), errors="coerce").fillna(1.0) - 1.0,
        "sb_over_prob":       lambda: (enrich_cv_with_sportsbook(cv), cv["sb_over_prob"])[1],
        "sb_line_diff":       lambda: (enrich_cv_with_sportsbook(cv), cv["sb_line_diff"])[1],
        "z_line_abs":         lambda: np.abs(pd.to_numeric(cv["z_line"], errors="coerce").fillna(0.0).values),
        "bp_has_x_under":     lambda: cv["bp_has"].values * cv["is_under"].values,
        "form_z_line":        lambda: pd.to_numeric(cv.get("form_z_line", 0.0), errors="coerce").fillna(0.0).clip(-5, 5),
    }

    if not extra_feats:
        return

    print(f"\nComputing {len(extra_feats)} extra features: {extra_feats}")
    for feat_name in extra_feats:
        if feat_name in feat_map:
            cv[feat_name] = feat_map[feat_name]()
            FEATS.append(feat_name)
            print(f"  Added: {feat_name}  mean={cv[feat_name].mean():+.4f}  std={cv[feat_name].std():.4f}")
        else:
            print(f"  UNKNOWN extra feature: {feat_name}  (available: {list(feat_map.keys())})")
            sys.exit(1)
    CAT_IDX = [FEATS.index(f) for f in CAT_FEATURES]


def print_feature_report(cv):
    print(f"\nFeature coverage ({len(FEATS)} features):")
    for f in FEATS:
        if f in cv.columns:
            vals = pd.to_numeric(cv[f], errors="coerce")
            cov = vals.notna().sum() / len(cv) * 100
            mn = vals.mean()
            print(f"  {f:25s}  cov={cov:5.1f}%  mean={mn:+.4f}")
        else:
            print(f"  {f:25s}  MISSING -- ABORTING")
            sys.exit(1)


# ===================================================================
# LODO evaluation
# ===================================================================
def run_lodo(cv, um, hit_arr, dates):
    """Run leave-one-date-out evaluation. Returns (oof_preds, fold_briers, sorted_dates)."""
    sorted_dates = sorted(dates)
    date_arr = cv["game_date"].astype(str).str[:10].values
    X_all = np.nan_to_num(cv[FEATS].values.astype(float), nan=0.0)
    y_all = hit_arr

    print(f"\n{'='*60}")
    print(f"LODO evaluation ({len(dates)} dates, {len(SEEDS)} seeds)")
    print(f"{'='*60}")

    oof_preds = np.full(len(cv), np.nan)
    fold_briers = []

    for fold_i, holdout_date in enumerate(sorted_dates):
        hd = str(holdout_date)[:10]
        test_mask = date_arr == hd
        train_mask = ~test_mask
        n_test = int(test_mask.sum())
        if n_test == 0:
            continue

        X_train, y_train = X_all[train_mask], y_all[train_mask]
        X_test = X_all[test_mask]

        over_train = ~um[train_mask]
        under_train = um[train_mask]
        over_test = ~um[test_mask]
        under_test = um[test_mask]

        fold_preds = np.zeros(n_test, dtype=float)

        for seed in SEEDS:
            po = {**PARAMS_OVER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
            pu = {**PARAMS_UNDER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}

            if over_train.sum() > 0 and over_test.sum() > 0:
                dtrain = lgb.Dataset(X_train[over_train], label=y_train[over_train],
                                     feature_name=FEATS, categorical_feature=CAT_IDX, free_raw_data=False)
                bst = lgb.train(po, dtrain, num_boost_round=N_ROUNDS)
                fold_preds[over_test] += bst.predict(X_test[over_test])

            if under_train.sum() > 0 and under_test.sum() > 0:
                dtrain = lgb.Dataset(X_train[under_train], label=y_train[under_train],
                                     feature_name=FEATS, categorical_feature=CAT_IDX, free_raw_data=False)
                bst = lgb.train(pu, dtrain, num_boost_round=N_ROUNDS)
                fold_preds[under_test] += bst.predict(X_test[under_test])

        fold_preds /= len(SEEDS)
        oof_preds[test_mask] = fold_preds

        fold_brier = float(np.mean((fold_preds - hit_arr[test_mask]) ** 2))
        raw_fold_brier = float(np.mean((cv.loc[test_mask, "p_new"].values - hit_arr[test_mask]) ** 2))
        delta = (fold_brier - raw_fold_brier) * 1000
        fold_briers.append((hd, n_test, fold_brier, raw_fold_brier, delta))

        if fold_i < 3:
            print(f"    DEBUG preds: min={fold_preds.min():.6f} max={fold_preds.max():.6f} "
                  f"mean={fold_preds.mean():.6f} std={fold_preds.std():.6f}")
            print(f"    DEBUG truth: mean={hit_arr[test_mask].mean():.3f}  "
                  f"sample preds={fold_preds[:5].round(4).tolist()}  "
                  f"sample truth={hit_arr[test_mask][:5].tolist()}")

        valid_so_far = ~np.isnan(oof_preds)
        brier_so_far = float(np.mean((oof_preds[valid_so_far] - hit_arr[valid_so_far]) ** 2))
        marker = " HURT" if delta > 1.0 else (" GOOD" if delta < -1.0 else "")
        print(f"  Fold {fold_i+1:2d}/{len(sorted_dates)}: {hd}  N={n_test:5d}  "
              f"fold={fold_brier:.6f}  raw={raw_fold_brier:.6f}  d={delta:+.1f}mB  "
              f"running={brier_so_far:.6f}{marker}")

    return oof_preds, fold_briers, sorted_dates


def sweep_temperature(oof_preds, hit_arr):
    """Sweep temperature on LODO predictions. Returns (best_temp, best_brier)."""
    print(f"\n{'='*60}")
    print("Temperature sweep on LODO predictions")
    print(f"{'='*60}")

    valid = ~np.isnan(oof_preds)
    oof_logit = sp_logit(np.clip(oof_preds[valid], 0.001, 0.999))
    y_valid = hit_arr[valid]

    best_brier = 999.0
    best_temp = 1.0
    for T in TEMP_CANDIDATES:
        p_T = sp_expit(oof_logit / T)
        brier = float(np.mean((p_T - y_valid) ** 2))
        hr = float(np.mean((p_T > 0.5) == y_valid))
        logloss = -float(np.mean(y_valid * np.log(np.clip(p_T, 1e-7, 1)) +
                                  (1 - y_valid) * np.log(np.clip(1 - p_T, 1e-7, 1))))
        marker = " *** BEST" if brier < best_brier else ""
        print(f"  T={T:.2f}  Brier={brier:.6f}  HR={hr*100:.2f}%  LogLoss={logloss:.6f}{marker}")
        if brier < best_brier:
            best_brier = brier
            best_temp = T

    print(f"\nBest temperature: {best_temp:.2f}  LODO Brier: {best_brier:.6f}")
    return best_temp, best_brier


# ===================================================================
# Production model training
# ===================================================================
def train_production_models(cv, um, hit_arr, temperature, ens_dir):
    """Train 7-seed x 2-direction ensemble and save to ens_dir."""
    print(f"\n{'='*60}")
    print(f"Training production models ({len(SEEDS)} seeds, T={temperature})")
    print(f"{'='*60}")

    X = np.nan_to_num(cv[FEATS].values.astype(float), nan=0.0)
    y = hit_arr
    ens_dir.mkdir(parents=True, exist_ok=True)

    for seed in SEEDS:
        t0 = time.time()
        po = {**PARAMS_OVER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
        pu = {**PARAMS_UNDER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}

        dtrain_o = lgb.Dataset(X[~um], label=y[~um], feature_name=FEATS,
                               categorical_feature=CAT_IDX, free_raw_data=False)
        bst_o = lgb.train(po, dtrain_o, num_boost_round=N_ROUNDS)
        bst_o.save_model(str(ens_dir / f"posthoc_calibrator_gbm_over_s{seed}.txt"))

        dtrain_u = lgb.Dataset(X[um], label=y[um], feature_name=FEATS,
                               categorical_feature=CAT_IDX, free_raw_data=False)
        bst_u = lgb.train(pu, dtrain_u, num_boost_round=N_ROUNDS)
        bst_u.save_model(str(ens_dir / f"posthoc_calibrator_gbm_under_s{seed}.txt"))
        print(f"  Saved seed {seed} ({time.time() - t0:.1f}s)")


def save_meta(cv, dates, sorted_dates, raw_brier, best_brier, temperature,
              fold_briers, global_hr, ens_dir, prod_brier):
    """Write ensemble_meta.json."""
    import yaml as _yaml
    with open(ROOT / "config.yaml") as _cf:
        _cfg = _yaml.safe_load(_cf)
    _blow = _cfg.get("blowout", {})
    _rot = _blow.get("rotation_tiers", {})

    n_help = sum(1 for _, _, _, _, d in fold_briers if d <= 0)
    n_hurt = sum(1 for _, _, _, _, d in fold_briers if d > 0)
    worst = max(fold_briers, key=lambda x: x[4])
    best_fold = min(fold_briers, key=lambda x: x[4])

    meta = {
        "version": args.cache,
        "config_fingerprint": config_fingerprint(_cfg),
        "architecture": f"dn-d11nl50-top7-{len(FEATS)}feat",
        "description": f"{args.cache} GBM ensemble -- {len(FEATS)} features, {len(dates)} dates, {len(cv)} legs",
        "ensemble_seeds": SEEDS,
        "temperature": temperature,
        "lodo_brier_ensemble": round(best_brier, 6),
        "previous_production_brier": round(prod_brier, 6) if prod_brier is not None else None,
        "raw_brier": round(raw_brier, 6),
        "training_legs": int(len(cv)),
        "training_dates": int(len(dates)),
        "training_cache": args.cache,
        "date_range": f"{sorted_dates[0]} to {sorted_dates[-1]}",
        "features": list(FEATS),
        "cat_features": CAT_FEATURES,
        "params_over": {k: v for k, v in PARAMS_OVER.items() if k != "verbose"},
        "params_under": {k: v for k, v in PARAMS_UNDER.items() if k != "verbose"},
        "n_rounds": N_ROUNDS,
        "player_te_smooth_k": SMOOTH_K,
        "global_hit_rate": round(global_hr, 6),
        "blowout_config": {
            "spread_sd": _blow.get("spread_sd"),
            "star_minute_drop": _blow.get("star_minute_drop"),
            "starter_minute_drop": _rot.get("starter_minute_drop"),
            "role_minute_drop": _blow.get("role_minute_drop"),
            "bench_minute_drop": _rot.get("bench_minute_drop"),
            "matchup_blowout_weight": _blow.get("matchup_blowout_weight"),
            "team_blowout_weight": _blow.get("team_blowout_weight"),
        },
        "per_fold_summary": {
            "n_help": n_help,
            "n_hurt": n_hurt,
            "worst_fold": worst[0],
            "worst_delta_mB": round(worst[4], 1),
            "best_fold": best_fold[0],
            "best_delta_mB": round(best_fold[4], 1),
        },
        "validated": time.strftime("%Y-%m-%d"),
        "_training_manifest": build_manifest(
            source="gbm_v12_train", cfg=_cfg,
            ensemble_dir=str(ens_dir),
        ),
    }
    print(f"  Config fingerprint: {meta['config_fingerprint']}")
    meta_path = ens_dir / "ensemble_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved meta -> {meta_path}")
    return meta


def save_player_te(pa_full, psa_full, pda_full, global_hr, ens_dir):
    """Write player_te_lookup.json."""
    te_lookup = {"global_hr": round(global_hr, 6), "smooth_k": SMOOTH_K,
                 "player": {}, "player_stat": {}, "player_dir": {}}
    for p, (sh, sc) in pa_full.items():
        te_lookup["player"][p] = [round(float(sh), 1), int(sc)]
    for (p, s), (sh, sc) in psa_full.items():
        te_lookup["player_stat"][f"{p}|{s}"] = [round(float(sh), 1), int(sc)]
    for (p, u), (sh, sc) in pda_full.items():
        te_lookup["player_dir"][f"{p}|{'U' if u else 'O'}"] = [round(float(sh), 1), int(sc)]
    te_path = ens_dir / "player_te_lookup.json"
    with open(te_path, "w") as f:
        json.dump(te_lookup, f, separators=(",", ":"))
    print(f"Saved TE -> {te_path}")


# ===================================================================
# Main
# ===================================================================
def main():
    # ------ Load cache ------
    cache_path = CACHE_PATHS[args.cache]
    if not cache_path.exists():
        alt = pathlib.Path(rf"D:/AtlasTestMarch26/model_backups/_{args.cache}_resim_cache.pkl")
        if alt.exists():
            cache_path = alt
        else:
            print(f"ERROR: Cache not found: {cache_path}")
            sys.exit(1)

    print(f"Cache: {cache_path}")
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"]
    raw_brier = cache["raw_brier"]
    dates = cache["dates"]
    print(f"  {len(cv)} legs, {len(dates)} dates, raw Brier={raw_brier:.6f}")
    if "config_snapshot" in cache:
        snap = cache["config_snapshot"]
        print(f"  Config: spread_sd={snap.get('spread_sd')}, star_drop={snap.get('star_minute_drop')}")

    # Drop legs without truth labels
    if "hit" in cv.columns:
        n_before = len(cv)
        cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
        n_dropped = n_before - len(cv)
        if n_dropped > 0:
            dates = sorted(cv["game_date"].astype(str).str[:10].unique())
            raw_valid = cv.dropna(subset=["p"])
            raw_brier = float(((raw_valid["p"] - raw_valid["hit"]) ** 2).mean())
            print(f"  Dropped {n_dropped} legs without hit labels -> {len(cv)} legs, {len(dates)} dates, raw Brier={raw_brier:.6f}")

    # Fix p_new
    if "p_new" not in cv.columns:
        if "p" in cv.columns and cv["p"].notna().mean() > 0.5:
            cv["p_new"] = cv["p"].astype(float)
            print(f"  Created p_new from p (p_new absent, p was {cv['p'].isna().mean()*100:.0f}% NaN)")
    elif cv["p_new"].isna().mean() > 0.5:
        if "p" in cv.columns and cv["p"].notna().mean() > 0.5:
            cv["p_new"] = cv["p"].astype(float)
            print(f"  Mapped p -> p_new (p_new was {cv['p_new'].isna().mean()*100:.0f}% NaN, p was {cv['p'].isna().mean()*100:.0f}% NaN)")

    # Fix stat_u
    if "stat_u" not in cv.columns and "stat" in cv.columns:
        cv["stat_u"] = cv["stat"]
        print(f"  Created stat_u from stat")

    hit_arr = cv["hit"].values.astype(float)

    # ------ Load gamelogs & build lookups ------
    logs = load_gamelogs()
    print("Building player history ...")
    player_history = build_player_history(logs)
    b2b_set = build_b2b_set(logs)
    ou_cache = load_ou_cache()

    # ------ Features ------
    um = compute_features(cv, player_history, b2b_set, ou_cache)
    pa_full, psa_full, pda_full, global_hr = compute_player_te(cv, um, dates)
    apply_extra_features(cv, args.extra_feats)
    print_feature_report(cv)

    # ------ LODO ------
    oof_preds, fold_briers, sorted_dates = run_lodo(cv, um, hit_arr, dates)
    best_temp, best_brier = sweep_temperature(oof_preds, hit_arr)

    # ------ Comparison vs production ------
    prod_brier, prod_version = read_production_lodo()
    print(f"\n--- Comparison ---")
    print(f"Raw Brier ({args.cache} kernel):     {raw_brier:.6f}")
    if prod_brier is not None:
        delta_vs_prod = (best_brier - prod_brier) * 1000
        print(f"Production ({prod_version}) LODO:     {prod_brier:.6f}")
        print(f"New {args.cache} LODO ({len(dates)}d):       {best_brier:.6f}")
        print(f"  vs production: {delta_vs_prod:+.3f} mB  ({'IMPROVED' if delta_vs_prod < 0 else 'SAME' if delta_vs_prod == 0 else 'REGRESSED'})")
    else:
        print(f"New {args.cache} LODO ({len(dates)}d):       {best_brier:.6f}")
        print(f"  No production ensemble to compare against.")

    # Per-fold summary
    n_hurt = sum(1 for _, _, _, _, d in fold_briers if d > 0)
    n_help = sum(1 for _, _, _, _, d in fold_briers if d <= 0)
    worst = max(fold_briers, key=lambda x: x[4])
    best_fold = min(fold_briers, key=lambda x: x[4])
    print(f"\n--- Per-fold Brier (GBM vs raw) ---")
    print(f"  Folds where GBM helps: {n_help}/{len(fold_briers)}")
    print(f"  Folds where GBM hurts: {n_hurt}/{len(fold_briers)}")
    print(f"  Worst fold: {worst[0]}  d={worst[4]:+.1f}mB")
    print(f"  Best fold:  {best_fold[0]}  d={best_fold[4]:+.1f}mB")

    # ------ Gate: LODO must beat raw kernel ------
    if best_brier >= raw_brier:
        print(f"\n*** LODO Brier ({best_brier:.6f}) >= raw ({raw_brier:.6f}). GBM is not helping. ***")
        print("*** Skipping production model training. ***")
        sys.exit(0)

    print(f"\nGBM saves {(raw_brier - best_brier)*1000:.1f} mB over raw -- proceeding to train production models.")

    # ------ Determine output directory ------
    if args.promote:
        ens_dir = PRODUCTION_ENS_DIR
    else:
        ens_dir = ROOT / f"data/model/ensemble_{args.cache}"

    # ------ Promotion safety check ------
    if args.promote:
        ok, reason, checked_prod_brier = check_promotion_safety(best_brier, args.force_promote)
        print(f"\n{'='*60}")
        print(f"PROMOTION SAFETY CHECK")
        print(f"{'='*60}")
        print(f"  {reason}")
        if not ok:
            # Still train to staging so the work isn't lost
            staging_dir = ROOT / f"data/model/ensemble_{args.cache}"
            print(f"\n  Training to staging instead: {staging_dir}")
            train_production_models(cv, um, hit_arr, best_temp, staging_dir)
            save_meta(cv, dates, sorted_dates, raw_brier, best_brier, best_temp,
                      fold_briers, global_hr, staging_dir, prod_brier)
            save_player_te(pa_full, psa_full, pda_full, global_hr, staging_dir)
            print(f"\n*** PROMOTION BLOCKED -- models saved to staging: {staging_dir} ***")
            print(f"*** Re-run with --force-promote to override. ***")
            sys.exit(1)

    # ------ Train + save ------
    train_production_models(cv, um, hit_arr, best_temp, ens_dir)
    save_meta(cv, dates, sorted_dates, raw_brier, best_brier, best_temp,
              fold_briers, global_hr, ens_dir, prod_brier)
    save_player_te(pa_full, psa_full, pda_full, global_hr, ens_dir)

    # ------ Summary ------
    print(f"\n{'='*60}")
    if args.promote:
        print(f"{args.cache} PROMOTED to production: {ens_dir}")
    else:
        print(f"{args.cache} saved to staging: {ens_dir}")
        print(f"To promote: python tools/gbm_v12_train.py --cache {args.cache} --promote"
              + (f" --extra-feats {' '.join(args.extra_feats)}" if args.extra_feats else ""))
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
"""
GBM v12 trainer — 33-feature v9d architecture on v12 resim cache
(sweep-optimized blowout: star=6.0, starter=3.5, role=0.5, bench=0.5, real spreads).

Usage:
    python tools/gbm_v12_train.py               # v12 cache (default)
    python tools/gbm_v12_train.py --cache v9     # v9 cache (baseline comparison)
    python tools/gbm_v12_train.py --promote      # save to data/model/ensemble/ (overwrite)
"""
import sys, pathlib, warnings, time, json, math, argparse, pickle

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit, expit as sp_expit
import lightgbm as lgb

from Atlas.core.fingerprint import build_manifest, config_fingerprint
from Atlas.core.minutes import minutes_sensitivity

# ROOT already defined above

# ===================================================================
# CLI
# ===================================================================
parser = argparse.ArgumentParser()
parser.add_argument("--cache", choices=["v9", "v12", "v13", "v14", "v15", "v16", "v17"], default="v12",
                    help="Which resim cache to train on (default: v12)")
parser.add_argument("--promote", action="store_true",
                    help="Save models to data/model/ensemble/ (overwrites current)")
parser.add_argument("--extra-feats", nargs="*", default=[],
                    help="Additional features to append to the 33-feature base "
                         "(e.g. --extra-feats opp_defense_rel pace_factor role_ctx_outs_n usage_dep_feat)")
args = parser.parse_args()

# ===================================================================
# Architecture (exact v9d contract — 33 features, 7 seeds)
# ===================================================================
SEEDS = [65536, 9999, 137, 999, 98765, 54321, 12345]
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
TEMP_CANDIDATES = [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12]

# 33 v9d features — exact order from ensemble_meta.json
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
CAT_FEATURES = ["stat_cat", "tier_cat"]
CAT_IDX = [FEATS.index(f) for f in CAT_FEATURES]

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

# ===================================================================
# Load cache
# ===================================================================
CACHE_PATHS = {
    "v9": pathlib.Path(r"D:/AtlasTestMarch26/model_backups/_v9_resim_cache.pkl"),
    "v12": ROOT / "data" / "model" / "_v12_resim_cache.pkl",
    "v13": ROOT / "data" / "model" / "_v13_resim_cache.pkl",
    "v14": ROOT / "data" / "model" / "_v14_resim_cache.pkl",
    "v15": ROOT / "data" / "model" / "_v15_resim_cache.pkl",
    "v16": ROOT / "data" / "model" / "_v16_resim_cache.pkl",
    "v17": ROOT / "data" / "model" / "_v17_resim_cache.pkl",
}
CACHE_PATH = CACHE_PATHS[args.cache]
if not CACHE_PATH.exists():
    alt = pathlib.Path(r"D:/AtlasTestMarch26/model_backups/_v12_resim_cache.pkl")
    if alt.exists():
        CACHE_PATH = alt
    else:
        print(f"ERROR: Cache not found: {CACHE_PATH}")
        sys.exit(1)

print(f"Cache: {CACHE_PATH}")
with open(CACHE_PATH, "rb") as f:
    cache = pickle.load(f)
cv = cache["cv"]
raw_brier = cache["raw_brier"]
dates = cache["dates"]
print(f"  {len(cv)} legs, {len(dates)} dates, raw Brier={raw_brier:.6f}")
if "config_snapshot" in cache:
    snap = cache["config_snapshot"]
    print(f"  Config: spread_sd={snap.get('spread_sd')}, star_drop={snap.get('star_minute_drop')}")

# Drop legs without truth labels (required for training + LODO)
if "hit" in cv.columns:
    n_before = len(cv)
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    n_dropped = n_before - len(cv)
    if n_dropped > 0:
        dates = sorted(cv["game_date"].astype(str).str[:10].unique())
        raw_valid = cv.dropna(subset=["p"])
        raw_brier = float(((raw_valid["p"] - raw_valid["hit"]) ** 2).mean())
        print(f"  Dropped {n_dropped} legs without hit labels -> {len(cv)} legs, {len(dates)} dates, raw Brier={raw_brier:.6f}")

# Fix p_new: if missing or mostly NaN but p is populated, use p as p_new
if "p_new" not in cv.columns:
    if "p" in cv.columns and cv["p"].notna().mean() > 0.5:
        cv["p_new"] = cv["p"].astype(float)
        print(f"  Created p_new from p (p_new absent, p was {cv['p'].isna().mean()*100:.0f}% NaN)")
elif cv["p_new"].isna().mean() > 0.5:
    if "p" in cv.columns and cv["p"].notna().mean() > 0.5:
        cv["p_new"] = cv["p"].astype(float)
        print(f"  Mapped p -> p_new (p_new was {cv['p_new'].isna().mean()*100:.0f}% NaN, p was {cv['p'].isna().mean()*100:.0f}% NaN)")

# Fix stat_u: D-drive corpus uses 'stat' instead of 'stat_u'
if "stat_u" not in cv.columns and "stat" in cv.columns:
    cv["stat_u"] = cv["stat"]
    print(f"  Created stat_u from stat")

# ===================================================================
# Load gamelogs
# ===================================================================
logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}
for col in ["team", "opp"]:
    logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)

# ===================================================================
# Build lookups
# ===================================================================
print("Building player history ...")
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

# B2B lookup
_gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
_gl = _gl.sort_values(["player", "game_date"])
_gl["prev"] = _gl.groupby("player")["game_date"].shift(1)
_gl["days"] = (_gl["game_date"] - _gl["prev"]).dt.days
b2b_set = set()
for _, r in _gl.iterrows():
    if pd.notna(r["days"]) and r["days"] == 1:
        b2b_set.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))

# Rotowire O/U for game_total_norm
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
                lk[h] = ou
                lk[a] = ou
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
                total += st[c]
                ok = True
        if ok:
            recent.append(total)
    return recent[-n:]


# ===================================================================
# Feature engineering
# ===================================================================
print("Computing features ...")
t_feat = time.time()

dir_u = cv["direction"].astype(str).str.upper()
um = (dir_u == "UNDER").values

# Ensure numeric columns
_num_cols = ["p_new", "rate_mean", "rate_std", "min_mean", "min_std",
             "games_used", "q_blowout", "form_z_line",
             "external_prior_score", "external_prior_n"]
for col in _num_cols:
    if col in cv.columns:
        cv[col] = pd.to_numeric(cv[col], errors="coerce")

# logit_p (from p_new = raw MC kernel)
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

# min_cv
_mm = cv["min_mean"].fillna(0.0)
_ms = cv["min_std"].fillna(0.0)
cv["min_cv"] = np.where(_mm > 1, np.clip(_ms / _mm, 0, 1), 0.3)

# is_combo
cv["is_combo"] = cv["stat_u"].isin(COMBOS).astype(float)

# BettingPros
cv["bp_has"] = 0.0
cv["bp_score_gated"] = 0.0
if "external_prior_n" in cv.columns:
    has_bp = cv["external_prior_n"].fillna(0) > 0
    cv.loc[has_bp, "bp_has"] = 1.0
    edge = cv["external_prior_score"].fillna(0.0) - cv["line"]
    dm = ((edge > 0) & (dir_u == "OVER")) | ((edge <= 0) & (dir_u == "UNDER"))
    cv.loc[has_bp & dm, "bp_score_gated"] = np.tanh(edge[has_bp & dm] / 3.0)

# Stat family flags
cv["is_assists"] = (cv["stat_u"] == "AST").astype(float)
cv["is_threes"] = (cv["stat_u"] == "FG3M").astype(float)

# Simple features
cv["games_norm"] = np.clip(cv["games_used"].values / 50.0, 0.0, 1.0)
cv["thin_flag"] = (cv["games_used"] < 15).astype(float)
cv["line_norm"] = np.clip(cv["line"].values / 40.0, 0.0, 2.0)
# Compute is_home from available columns if missing or mostly NaN
if "is_home" not in cv.columns or ("is_home" in cv.columns and cv["is_home"].isna().mean() > 0.5):
    if "home_team" in cv.columns and "team" in cv.columns:
        cv["is_home"] = (cv["team"].astype(str).str.upper().str.strip() == cv["home_team"].astype(str).str.upper().str.strip()).astype(float)
        print(f"  Computed is_home from team/home_team: {cv['is_home'].mean():.1%} home legs")
    elif "home" in cv.columns:
        cv["is_home"] = pd.to_numeric(cv["home"], errors="coerce").fillna(0.0).astype(float)
        print(f"  Computed is_home from home: {cv['is_home'].mean():.1%} home legs")
    else:
        cv["is_home"] = 0.0
        print("  WARN: No home data found, is_home set to 0")
cv["is_home_feat"] = cv["is_home"].fillna(0.0).values.astype(float)
cv["min_sensitivity"] = cv["stat_u"].apply(lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0).values.astype(float)
cv["is_under"] = um.astype(float)

# game_total_norm (vectorized)
_gd_strs = cv["game_date"].astype(str).str[:10].values
_teams = cv["team"].astype(str).str.upper().str.strip().values
_gt_vals = np.array([_ou_cache.get(g, {}).get(t, 0.0) for g, t in zip(_gd_strs, _teams)])
cv["game_total_norm"] = np.where(_gt_vals > 0, np.clip(_gt_vals / 230.0 - 1.0, -0.15, 0.15), 0.0)

# is_b2b (vectorized)
_players = cv["player"].astype(str).str.strip().values
cv["is_b2b"] = np.array([1.0 if (p, g) in b2b_set else 0.0 for p, g in zip(_players, _gd_strs)])

# Logit interactions
cv["is_demon"] = (cv["tier"] == "DEMON").astype(float)
cv["logit_p_x_demon"] = cv["logit_p"] * cv["is_demon"]

# Categorical
cv["stat_cat"] = cv["stat_u"].map(STAT_CATS).fillna(11).astype(int)
cv["tier_cat"] = cv["tier"].map(TIER_CATS).fillna(0).astype(int)

# q_blowout (now enriched with team/matchup data)
cv["q_blowout"] = pd.to_numeric(cv.get("q_blowout", 0.0), errors="coerce").fillna(0.0)
cv["q_x_under"] = cv["q_blowout"] * cv["is_under"]

# ===================================================================
# Window features from gamelogs
# ===================================================================
print("Computing window features ...")
hr20 = np.full(len(cv), np.nan)
hr40 = np.full(len(cv), np.nan)
margin_arr = np.full(len(cv), np.nan)
line_dist = np.zeros(len(cv))
tail_risk = np.zeros(len(cv))
line_tightness = np.zeros(len(cv))
rate_cv_arr = np.zeros(len(cv))
l10_has = np.zeros(len(cv))

# Pre-extract columns as numpy arrays to avoid per-row iloc
_su_arr = cv["stat_u"].values
_ln_arr = cv["line"].astype(float).values
_dr_arr = cv["direction"].astype(str).str.upper().values

for i in range(len(cv)):
    pl = _players[i]
    su = _su_arr[i]
    ln = _ln_arr[i]
    dr = _dr_arr[i]
    gd = _gd_strs[i]

    actuals = _get_recent(pl, su, gd, n=50)
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

    # 10-game margin
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

print(f"Features done ({time.time() - t_feat:.1f}s)")

# ===================================================================
# Player TE (full-data, matching v9d methodology)
# ===================================================================
print("Computing player TE (full data) ...")
sorted_dates = sorted(dates)
date_arr = cv["game_date"].astype(str).str[:10].values
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

# ===================================================================
# Extra candidate features (v13+) — only computed if --extra-feats
# ===================================================================
# ---------------------------------------------------------------------------
# Sportsbook data (OddsAPI historical) — lazy-loaded for sb_* features
# ---------------------------------------------------------------------------
_SB_ALIAS = {
    "A.J. Green": "AJ Green", "C.J. McCollum": "CJ McCollum",
    "Dennis Schroder": "Dennis Schröder", "G.G. Jackson": "GG Jackson",
    "Gary Payton II": "Gary Payton", "Gary Trent Jr": "Gary Trent",
    "Herb Jones": "Herbert Jones", "Jabari Smith Jr": "Jabari Smith",
    "Jaime Jaquez Jr": "Jaime Jaquez", "Justin Champagnie": "Julian Champagnie",
    "Kelly Oubre Jr": "Kelly Oubre", "Kevin Porter Jr.": "Kevin Porter",
    "Kristaps Porzingis": "Kristaps Porziņģis", "Luka Doncic": "Luka Dončić",
    "Marvin Bagley III": "Marvin Bagley", "Michael Porter Jr": "Michael Porter",
    "Moe Wagner": "Moritz Wagner", "Moussa Diabate": "Moussa Diabaté",
    "Nicolas Claxton": "Nic Claxton", "Nikola Jokic": "Nikola Jokić",
    "Nikola Vucevic": "Nikola Vučević", "Paul Reed Jr": "Paul Reed",
    "R.J. Barrett": "RJ Barrett", "Ron Holland": "Ronald Holland",
    "Scotty Pippen Jr": "Scottie Pippen", "Tim Hardaway Jr": "Tim Hardaway",
    "Trey Murphy III": "Trey Murphy", "Walter Clayton Jr.": "Walter Clayton",
    "Wendell Carter Jr": "Wendell Carter", "Carlton Carrington": "Bub Carrington",
    "Isaiah Stewart II": "Isaiah Stewart",
}
_sb_enriched = False

def _enrich_cv_with_sportsbook():
    """Join OddsAPI historical props onto cv by (date, player, stat) closest-line."""
    global _sb_enriched
    if _sb_enriched:
        return
    _sb_enriched = True
    sb_path = ROOT / "data" / "model" / "oddsapi_historical_props.csv"
    if not sb_path.exists():
        print("  WARNING: oddsapi_historical_props.csv not found — sb features will be NaN")
        cv["sb_over_prob"] = np.nan
        cv["sb_line_diff"] = np.nan
        return
    oa = pd.read_csv(sb_path)
    # Filter to rows with meaningful consensus (>= 3 sportsbooks)
    if "n_books" in oa.columns:
        before = len(oa)
        oa = oa[oa["n_books"] >= 3].copy()
        print(f"  Sportsbook filter: {len(oa)}/{before} rows with n_books >= 3")
    oa["player_norm"] = oa["player"].apply(lambda n: _SB_ALIAS.get(n.strip(), n.strip()))
    cv["player_norm"] = cv["player"].apply(lambda n: _SB_ALIAS.get(n.strip(), n.strip()))
    oa["line"] = oa["line"].astype(float)
    oa["over_prob"] = oa["over_prob"].astype(float)
    # Aggregate to median prob per (date, player, stat, line)
    oa_agg = oa.groupby(["game_date", "player_norm", "stat", "line"]).agg(
        over_prob=("over_prob", "median")).reset_index()
    # Use stat_u from cv for join key (resim cache uses stat_u, OddsAPI uses stat)
    cv["_stat_join"] = cv["stat_u"] if "stat_u" in cv.columns else cv["stat"]
    cv["_idx"] = np.arange(len(cv))
    merged = cv[["_idx", "game_date", "player_norm", "_stat_join", "line"]].merge(
        oa_agg.rename(columns={"line": "sb_line", "over_prob": "sb_over_prob_raw", "stat": "_stat_join"}),
        on=["game_date", "player_norm", "_stat_join"], how="left")
    # Pick closest sportsbook line per leg (drop unmatched first)
    merged["ld"] = abs(merged["line"] - merged["sb_line"])
    has_match = merged["ld"].notna()
    if has_match.any():
        matched = merged[has_match]
        closest_idx = matched.groupby("_idx")["ld"].idxmin()
        closest = matched.loc[closest_idx].set_index("_idx")
        cv["sb_over_prob"] = closest["sb_over_prob_raw"].reindex(cv["_idx"]).values
        cv["sb_line_diff"] = closest["ld"].reindex(cv["_idx"]).values
    else:
        cv["sb_over_prob"] = np.nan
        cv["sb_line_diff"] = np.nan
    cv.drop(columns=["_idx", "player_norm", "_stat_join"], inplace=True, errors="ignore")
    n_matched = cv["sb_over_prob"].notna().sum()
    print(f"  Sportsbook enrichment: {n_matched}/{len(cv)} legs matched "
          f"({100*n_matched/len(cv):.1f}%)")


EXTRA_FEAT_MAP = {
    "opp_defense_rel": lambda: pd.to_numeric(cv.get("form_opp_defense_rel", 0.0), errors="coerce").fillna(0.0).clip(-0.2, 0.2),
    "pace_factor": lambda: pd.to_numeric(cv.get("form_pace_factor", 0.0), errors="coerce").fillna(0.0).clip(-0.1, 0.1),
    "role_ctx_outs_n": lambda: np.clip(pd.to_numeric(cv.get("role_ctx_outs_used", 0), errors="coerce").fillna(0).values, 0, 5).astype(float),
    "usage_dep_feat": lambda: pd.to_numeric(cv.get("usage_dep", 1.0), errors="coerce").fillna(1.0).clip(0.5, 1.5) - 1.0,
    "fragility_feat": lambda: pd.to_numeric(cv.get("fragility", 0.0), errors="coerce").fillna(0.0).clip(0, 0.3),
    "role_ctx_mult_feat": lambda: pd.to_numeric(cv.get("role_ctx_mult", 1.0), errors="coerce").fillna(1.0) - 1.0,
    "sb_over_prob": lambda: (_enrich_cv_with_sportsbook(), cv["sb_over_prob"])[1],
    "sb_line_diff": lambda: (_enrich_cv_with_sportsbook(), cv["sb_line_diff"])[1],
    "z_line_abs": lambda: np.abs(pd.to_numeric(cv["z_line"], errors="coerce").fillna(0.0).values),
    "bp_has_x_under": lambda: cv["bp_has"].values * cv["is_under"].values,
    "form_z_line": lambda: pd.to_numeric(cv.get("form_z_line", 0.0), errors="coerce").fillna(0.0).clip(-5, 5),
}

if args.extra_feats:
    print(f"\nComputing {len(args.extra_feats)} extra features: {args.extra_feats}")
    for feat_name in args.extra_feats:
        if feat_name in EXTRA_FEAT_MAP:
            cv[feat_name] = EXTRA_FEAT_MAP[feat_name]()
            FEATS.append(feat_name)
            print(f"  Added: {feat_name}  mean={cv[feat_name].mean():+.4f}  std={cv[feat_name].std():.4f}")
        else:
            print(f"  UNKNOWN extra feature: {feat_name}  (available: {list(EXTRA_FEAT_MAP.keys())})")
            sys.exit(1)
    # Recompute categorical indices since FEATS changed
    CAT_IDX = [FEATS.index(f) for f in CAT_FEATURES]

# Feature report (after all features including TE are computed)
print(f"\nFeature coverage ({len(FEATS)} features):")
for f in FEATS:
    if f in cv.columns:
        vals = pd.to_numeric(cv[f], errors="coerce")
        cov = vals.notna().sum() / len(cv) * 100
        mn = vals.mean()
        print(f"  {f:25s}  cov={cov:5.1f}%  mean={mn:+.4f}")
    else:
        print(f"  {f:25s}  MISSING — ABORTING")
        sys.exit(1)

# ===================================================================
# LODO evaluation
# ===================================================================
print(f"\n{'='*60}")
print(f"LODO evaluation ({len(dates)} dates, {len(SEEDS)} seeds)")
print(f"{'='*60}")

X_all = np.nan_to_num(cv[FEATS].values.astype(float), nan=0.0)
y_all = hit_arr

oof_preds = np.full(len(cv), np.nan)
fold_briers = []

for fold_i, holdout_date in enumerate(sorted_dates):
    hd = str(holdout_date)[:10]
    test_mask = date_arr == hd
    train_mask = ~test_mask
    n_test = int(test_mask.sum())
    if n_test == 0:
        continue

    X_train, y_train = X_all[train_mask], y_all[train_mask]
    X_test = X_all[test_mask]

    over_train = ~um[train_mask]
    under_train = um[train_mask]
    over_test = ~um[test_mask]
    under_test = um[test_mask]

    fold_preds = np.zeros(n_test, dtype=float)

    for seed in SEEDS:
        po = {**PARAMS_OVER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
        pu = {**PARAMS_UNDER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}

        if over_train.sum() > 0 and over_test.sum() > 0:
            dtrain = lgb.Dataset(X_train[over_train], label=y_train[over_train],
                                 feature_name=FEATS, categorical_feature=CAT_IDX, free_raw_data=False)
            bst = lgb.train(po, dtrain, num_boost_round=N_ROUNDS)
            fold_preds[over_test] += bst.predict(X_test[over_test])

        if under_train.sum() > 0 and under_test.sum() > 0:
            dtrain = lgb.Dataset(X_train[under_train], label=y_train[under_train],
                                 feature_name=FEATS, categorical_feature=CAT_IDX, free_raw_data=False)
            bst = lgb.train(pu, dtrain, num_boost_round=N_ROUNDS)
            fold_preds[under_test] += bst.predict(X_test[under_test])

    fold_preds /= len(SEEDS)
    oof_preds[test_mask] = fold_preds

    fold_brier = float(np.mean((fold_preds - hit_arr[test_mask]) ** 2))
    raw_fold_brier = float(np.mean((cv.loc[test_mask, "p_new"].values - hit_arr[test_mask]) ** 2))
    delta = (fold_brier - raw_fold_brier) * 1000
    fold_briers.append((hd, n_test, fold_brier, raw_fold_brier, delta))

    # Debug: show prediction distribution for first 3 folds
    if fold_i < 3:
        print(f"    DEBUG preds: min={fold_preds.min():.6f} max={fold_preds.max():.6f} "
              f"mean={fold_preds.mean():.6f} std={fold_preds.std():.6f}")
        print(f"    DEBUG truth: mean={hit_arr[test_mask].mean():.3f}  "
              f"sample preds={fold_preds[:5].round(4).tolist()}  "
              f"sample truth={hit_arr[test_mask][:5].tolist()}")

    valid_so_far = ~np.isnan(oof_preds)
    brier_so_far = float(np.mean((oof_preds[valid_so_far] - hit_arr[valid_so_far]) ** 2))
    marker = " HURT" if delta > 1.0 else (" GOOD" if delta < -1.0 else "")
    print(f"  Fold {fold_i+1:2d}/{len(sorted_dates)}: {hd}  N={n_test:5d}  "
          f"fold={fold_brier:.6f}  raw={raw_fold_brier:.6f}  d={delta:+.1f}mB  "
          f"running={brier_so_far:.6f}{marker}")

# ===================================================================
# Temperature sweep
# ===================================================================
print(f"\n{'='*60}")
print("Temperature sweep on LODO predictions")
print(f"{'='*60}")
valid = ~np.isnan(oof_preds)
oof_logit = sp_logit(np.clip(oof_preds[valid], 0.001, 0.999))
y_valid = hit_arr[valid]

best_brier = 999.0
best_temp = 1.0
for T in TEMP_CANDIDATES:
    p_T = sp_expit(oof_logit / T)
    brier = float(np.mean((p_T - y_valid) ** 2))
    hr = float(np.mean((p_T > 0.5) == y_valid))
    logloss = -float(np.mean(y_valid * np.log(np.clip(p_T, 1e-7, 1)) +
                              (1 - y_valid) * np.log(np.clip(1 - p_T, 1e-7, 1))))
    marker = " *** BEST" if brier < best_brier else ""
    print(f"  T={T:.2f}  Brier={brier:.6f}  HR={hr*100:.2f}%  LogLoss={logloss:.6f}{marker}")
    if brier < best_brier:
        best_brier = brier
        best_temp = T

TEMPERATURE = best_temp
print(f"\nBest temperature: {TEMPERATURE:.2f}  LODO Brier: {best_brier:.6f}")

# Comparison
print(f"\n--- Comparison ---")
print(f"Raw Brier ({args.cache} kernel):   {raw_brier:.6f}")
print(f"v9d baseline (33d):       0.196266")
print(f"v10 LODO (v9 cache):      0.199598")
print(f"v14 LODO (production):    0.198097")
print(f"{args.cache} LODO ({len(dates)}d):      {best_brier:.6f}")
delta_vs_v10 = (best_brier - 0.199598) * 1000
delta_vs_v9d = (best_brier - 0.196266) * 1000
delta_vs_v14 = (best_brier - 0.198097) * 1000
print(f"{args.cache} vs v14: {delta_vs_v14:+.3f} mB  ({'IMPROVED' if delta_vs_v14 < 0 else 'REGRESSED'})")
print(f"{args.cache} vs v10: {delta_vs_v10:+.3f} mB  ({'IMPROVED' if delta_vs_v10 < 0 else 'REGRESSED'})")
print(f"{args.cache} vs v9d: {delta_vs_v9d:+.3f} mB  ({'IMPROVED' if delta_vs_v9d < 0 else 'REGRESSED'})")
delta_mB = delta_vs_v9d

# Per-fold summary
print(f"\n--- Per-fold Brier (GBM vs raw) ---")
n_hurt = sum(1 for _, _, _, _, d in fold_briers if d > 0)
n_help = sum(1 for _, _, _, _, d in fold_briers if d <= 0)
print(f"  Folds where GBM helps: {n_help}/{len(fold_briers)}")
print(f"  Folds where GBM hurts: {n_hurt}/{len(fold_briers)}")
worst = max(fold_briers, key=lambda x: x[4])
best_fold = min(fold_briers, key=lambda x: x[4])
print(f"  Worst fold: {worst[0]}  d={worst[4]:+.1f}mB")
print(f"  Best fold:  {best_fold[0]}  d={best_fold[4]:+.1f}mB")

# ===================================================================
# Gate: only train production models if LODO improves over raw
# ===================================================================
if best_brier >= raw_brier:
    print(f"\n*** LODO Brier ({best_brier:.6f}) >= raw ({raw_brier:.6f}). GBM is not helping. ***")
    print("*** Skipping production model training. Investigate per-fold results above. ***")
    sys.exit(0)

print(f"\nGBM saves {(raw_brier - best_brier)*1000:.1f} mB over raw -- proceeding to train production models.")

# ===================================================================
# Train production models (full data)
# ===================================================================
print(f"\n{'='*60}")
print(f"Training production models ({len(SEEDS)} seeds, T={TEMPERATURE})")
print(f"{'='*60}")

X = np.nan_to_num(cv[FEATS].values.astype(float), nan=0.0)
y = hit_arr

if args.promote:
    ens_dir = ROOT / "data/model/ensemble"
else:
    ens_dir = ROOT / f"data/model/ensemble_{args.cache}"
ens_dir.mkdir(parents=True, exist_ok=True)

for seed in SEEDS:
    t0 = time.time()
    po = {**PARAMS_OVER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}
    pu = {**PARAMS_UNDER, "seed": seed, "data_random_seed": seed, "feature_fraction_seed": seed}

    dtrain_o = lgb.Dataset(X[~um], label=y[~um], feature_name=FEATS,
                           categorical_feature=CAT_IDX, free_raw_data=False)
    bst_o = lgb.train(po, dtrain_o, num_boost_round=N_ROUNDS)
    bst_o.save_model(str(ens_dir / f"posthoc_calibrator_gbm_over_s{seed}.txt"))

    dtrain_u = lgb.Dataset(X[um], label=y[um], feature_name=FEATS,
                           categorical_feature=CAT_IDX, free_raw_data=False)
    bst_u = lgb.train(pu, dtrain_u, num_boost_round=N_ROUNDS)
    bst_u.save_model(str(ens_dir / f"posthoc_calibrator_gbm_under_s{seed}.txt"))
    print(f"  Saved seed {seed} ({time.time() - t0:.1f}s)")

# ===================================================================
# Save meta
# ===================================================================
# Read blowout config from actual config.yaml — never hardcode
import yaml as _yaml
with open(ROOT / "config.yaml") as _cf:
    _cfg = _yaml.safe_load(_cf)
_blow = _cfg.get("blowout", {})
_rot = _blow.get("rotation_tiers", {})

meta = {
    "version": args.cache,
    "config_fingerprint": config_fingerprint(_cfg),
    "architecture": f"dn-d11nl50-top7-{len(FEATS)}feat",
    "parent": "v14",
    "description": f"{args.cache} GBM ensemble — {len(FEATS)} features, {len(dates)} dates, {len(cv)} legs",
    "ensemble_seeds": SEEDS,
    "temperature": TEMPERATURE,
    "lodo_brier_ensemble": round(best_brier, 6),
    "lodo_brier_v10": 0.199598,
    "lodo_brier_v9d": 0.196266,
    "lodo_brier_v14": 0.198097,
    "lodo_brier_delta_vs_v14_mB": round(delta_vs_v14, 3),
    "lodo_brier_delta_vs_v10_mB": round(delta_vs_v10, 3),
    "lodo_brier_delta_vs_v9d_mB": round(delta_vs_v9d, 3),
    "raw_brier": round(raw_brier, 6),
    "training_legs": int(len(cv)),
    "training_dates": int(len(dates)),
    "training_cache": args.cache,
    "date_range": f"{sorted_dates[0]} to {sorted_dates[-1]}",
    "features": FEATS,
    "cat_features": CAT_FEATURES,
    "params_over": {k: v for k, v in PARAMS_OVER.items() if k != "verbose"},
    "params_under": {k: v for k, v in PARAMS_UNDER.items() if k != "verbose"},
    "n_rounds": N_ROUNDS,
    "player_te_smooth_k": SMOOTH_K,
    "global_hit_rate": round(global_hr, 6),
    "blowout_config": {
        "spread_sd": _blow.get("spread_sd"),
        "star_minute_drop": _blow.get("star_minute_drop"),
        "starter_minute_drop": _rot.get("starter_minute_drop"),
        "role_minute_drop": _blow.get("role_minute_drop"),
        "bench_minute_drop": _rot.get("bench_minute_drop"),
        "matchup_blowout_weight": _blow.get("matchup_blowout_weight"),
        "team_blowout_weight": _blow.get("team_blowout_weight"),
    },
    "per_fold_summary": {
        "n_help": n_help,
        "n_hurt": n_hurt,
        "worst_fold": worst[0],
        "worst_delta_mB": round(worst[4], 1),
        "best_fold": best_fold[0],
        "best_delta_mB": round(best_fold[4], 1),
    },
    "validated": time.strftime("%Y-%m-%d"),
    "_training_manifest": build_manifest(
        source="gbm_v12_train", cfg=_cfg,
        ensemble_dir=str(ens_dir),
    ),
}
print(f"  Config fingerprint: {meta['config_fingerprint']}")
meta_path = ens_dir / "ensemble_meta.json"
with open(meta_path, "w") as f:
    json.dump(meta, f, indent=2)
print(f"Saved meta -> {meta_path}")

# ===================================================================
# Save player TE lookup
# ===================================================================
te_lookup = {"global_hr": round(global_hr, 6), "smooth_k": SMOOTH_K,
             "player": {}, "player_stat": {}, "player_dir": {}}
for p, (sh, sc) in pa_full.items():
    te_lookup["player"][p] = [round(float(sh), 1), int(sc)]
for (p, s), (sh, sc) in psa_full.items():
    te_lookup["player_stat"][f"{p}|{s}"] = [round(float(sh), 1), int(sc)]
for (p, u), (sh, sc) in pda_full.items():
    te_lookup["player_dir"][f"{p}|{'U' if u else 'O'}"] = [round(float(sh), 1), int(sc)]
te_path = ens_dir / "player_te_lookup.json"
with open(te_path, "w") as f:
    json.dump(te_lookup, f, separators=(",", ":"))
print(f"Saved TE -> {te_path}")

print(f"\n{'='*60}")
if args.promote:
    print(f"{args.cache} PROMOTED to production: {ens_dir}")
else:
    print(f"{args.cache} saved to staging: {ens_dir}")
    print(f"To promote: python tools/gbm_v12_train.py --cache {args.cache} --promote")
print(f"{'='*60}")

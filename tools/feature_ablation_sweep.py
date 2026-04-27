"""
Feature ablation sweep — LOO (leave-one-out feature) + add-one analysis.

For each of 33 base features, drop it and measure LODO Brier with 1 seed.
Also tests extra candidate features one at a time.
Uses a single seed for speed; full 7-seed confirmation should follow
for any feature with |delta| > 0.1 mB.

Expected runtime: ~2-3 hours on v17 cache (167K legs, 46 dates).

Usage:
    python tools/feature_ablation_sweep.py --cache v17
    python tools/feature_ablation_sweep.py --cache v17 --seeds 3   # 3-seed for higher accuracy
"""
import sys, pathlib, warnings, time, json, math, argparse, pickle

sys.path.insert(0, str(pathlib.Path(r"c:/Users/rick/projects/Atlas/src")))
sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit, expit as sp_expit
import lightgbm as lgb

from Atlas.core.minutes import minutes_sensitivity

ROOT = pathlib.Path(r"c:/Users/rick/projects/Atlas")

parser = argparse.ArgumentParser(description="Feature ablation sweep")
parser.add_argument("--cache", choices=["v12", "v13", "v14", "v15", "v16", "v17"],
                    default="v17")
parser.add_argument("--seeds", type=int, default=1,
                    help="Number of seeds to use (1=fast scan, 7=full)")
args = parser.parse_args()

# ===================================================================
# Architecture constants (copied from gbm_v12_train.py)
# ===================================================================
ALL_SEEDS = [65536, 9999, 137, 999, 98765, 54321, 12345]
SEEDS = ALL_SEEDS[:args.seeds]

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
TEMP = 1.04  # v17 production temperature

FEATS_BASE = [
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
P_LO, P_HI = 0.03, 0.97
TEAM_NORM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
             "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN"}


# ===================================================================
# LODO with specified feature set (core loop)
# ===================================================================
def run_lodo_fast(cv, feats, um, hit_arr, date_arr, sorted_dates):
    """Run LODO with given feature list. Returns Brier at production temperature."""
    cat_idx = [feats.index(f) for f in CAT_FEATURES if f in feats]
    X_all = np.nan_to_num(cv[feats].values.astype(float), nan=0.0)
    y_all = hit_arr

    oof_preds = np.full(len(cv), np.nan)

    for holdout_date in sorted_dates:
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
            po = {**PARAMS_OVER, "seed": seed, "data_random_seed": seed,
                  "feature_fraction_seed": seed}
            pu = {**PARAMS_UNDER, "seed": seed, "data_random_seed": seed,
                  "feature_fraction_seed": seed}

            if over_train.sum() > 0 and over_test.sum() > 0:
                dtrain = lgb.Dataset(X_train[over_train], label=y_train[over_train],
                                     feature_name=feats, categorical_feature=cat_idx,
                                     free_raw_data=False)
                bst = lgb.train(po, dtrain, num_boost_round=N_ROUNDS)
                fold_preds[over_test] += bst.predict(X_test[over_test])

            if under_train.sum() > 0 and under_test.sum() > 0:
                dtrain = lgb.Dataset(X_train[under_train], label=y_train[under_train],
                                     feature_name=feats, categorical_feature=cat_idx,
                                     free_raw_data=False)
                bst = lgb.train(pu, dtrain, num_boost_round=N_ROUNDS)
                fold_preds[under_test] += bst.predict(X_test[under_test])

        fold_preds /= len(SEEDS)
        oof_preds[test_mask] = fold_preds

    # Apply temperature
    valid = ~np.isnan(oof_preds)
    oof_logit = sp_logit(np.clip(oof_preds[valid], 0.001, 0.999))
    p_cal = sp_expit(oof_logit / TEMP)
    brier = float(np.mean((p_cal - hit_arr[valid]) ** 2))
    return brier


# ===================================================================
# Feature engineering (same as gbm_v12_train.py)
# ===================================================================
def compute_all_features(cv, logs):
    """Compute all 33 base features + extra candidates. Returns (um, hit_arr, date_arr, sorted_dates)."""
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

    # B2B
    _gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
    _gl = _gl.sort_values(["player", "game_date"])
    _gl["prev"] = _gl.groupby("player")["game_date"].shift(1)
    _gl["days"] = (_gl["game_date"] - _gl["prev"]).dt.days
    b2b_set = set()
    for _, r in _gl.iterrows():
        if pd.notna(r["days"]) and r["days"] == 1:
            b2b_set.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))

    # O/U cache
    iael_dir = ROOT / "data/archives/iael/2026"
    ou_cache = {}
    if iael_dir.exists():
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
                    ou_cache[dd.name] = lk
            except Exception:
                pass

    # --- Feature computation ---
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

    if "is_home" not in cv.columns or cv["is_home"].isna().mean() > 0.5:
        if "home_team" in cv.columns and "team" in cv.columns:
            cv["is_home"] = (cv["team"].astype(str).str.upper().str.strip() ==
                             cv["home_team"].astype(str).str.upper().str.strip()).astype(float)
        elif "home" in cv.columns:
            cv["is_home"] = pd.to_numeric(cv["home"], errors="coerce").fillna(0.0).astype(float)
        else:
            cv["is_home"] = 0.0
    cv["is_home_feat"] = cv["is_home"].fillna(0.0).values.astype(float)
    cv["min_sensitivity"] = cv["stat_u"].apply(
        lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0).values.astype(float)
    cv["is_under"] = um.astype(float)

    _gd_strs = cv["game_date"].astype(str).str[:10].values
    _teams = cv["team"].astype(str).str.upper().str.strip().values
    _gt_vals = np.array([ou_cache.get(g, {}).get(t, 0.0) for g, t in zip(_gd_strs, _teams)])
    cv["game_total_norm"] = np.where(_gt_vals > 0, np.clip(_gt_vals / 230.0 - 1.0, -0.15, 0.15), 0.0)

    _players = cv["player"].astype(str).str.strip().values
    cv["is_b2b"] = np.array([1.0 if (p, g) in b2b_set else 0.0
                              for p, g in zip(_players, _gd_strs)])
    cv["is_demon"] = (cv["tier"] == "DEMON").astype(float)
    cv["logit_p_x_demon"] = cv["logit_p"] * cv["is_demon"]
    cv["stat_cat"] = cv["stat_u"].map(STAT_CATS).fillna(11).astype(int)
    cv["tier_cat"] = cv["tier"].map(TIER_CATS).fillna(0).astype(int)
    cv["q_blowout"] = pd.to_numeric(cv.get("q_blowout", 0.0), errors="coerce").fillna(0.0)
    cv["q_x_under"] = cv["q_blowout"] * cv["is_under"]

    # Window features
    print("Computing window features ...")
    t0 = time.time()

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
    print(f"  Window features done ({time.time() - t0:.1f}s)")

    # Player TE
    print("Computing player TE ...")
    dates = sorted(cv["game_date"].astype(str).str[:10].unique())
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
        pd.Series(player_col).map(pc).fillna(0).values.astype(float) / 200.0, 0.0, 1.0)

    # Extra candidate features (for add-one tests)
    cv["opp_defense_rel"] = pd.to_numeric(
        cv.get("form_opp_defense_rel", 0.0), errors="coerce").fillna(0.0).clip(-0.2, 0.2)
    cv["usage_dep_feat"] = pd.to_numeric(
        cv.get("usage_dep", 1.0), errors="coerce").fillna(1.0).clip(0.5, 1.5) - 1.0
    cv["fragility_feat"] = pd.to_numeric(
        cv.get("fragility", 0.0), errors="coerce").fillna(0.0).clip(0, 0.3)
    cv["role_ctx_mult_feat"] = pd.to_numeric(
        cv.get("role_ctx_mult", 1.0), errors="coerce").fillna(1.0) - 1.0
    cv["z_line_abs"] = np.abs(cv["z_line"].values)
    cv["bp_has_x_under"] = cv["bp_has"].values * cv["is_under"].values

    date_arr = cv["game_date"].astype(str).str[:10].values
    sorted_dates = sorted(dates)

    return um, hit_arr, date_arr, sorted_dates


# ===================================================================
# Main
# ===================================================================
def main():
    t_start = time.time()

    # Load cache
    cache_path = ROOT / "data" / "model" / f"_{args.cache}_resim_cache.pkl"
    if not cache_path.exists():
        print(f"ERROR: Cache not found: {cache_path}")
        sys.exit(1)

    print(f"Cache: {cache_path}")
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"]
    print(f"  {len(cv)} total legs")

    # Drop legs without truth labels
    if "hit" in cv.columns:
        cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    print(f"  {len(cv)} legs with truth labels")

    # Fix p_new
    if "p_new" not in cv.columns or cv["p_new"].isna().mean() > 0.5:
        if "p" in cv.columns:
            cv["p_new"] = cv["p"].astype(float)
    if "stat_u" not in cv.columns and "stat" in cv.columns:
        cv["stat_u"] = cv["stat"]

    # Load gamelogs
    logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
    for col in ["team", "opp"]:
        logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)

    # Compute all features
    um, hit_arr, date_arr, sorted_dates = compute_all_features(cv, logs)

    print(f"\n{'='*70}")
    print(f"FEATURE ABLATION SWEEP")
    print(f"  Seeds: {len(SEEDS)} ({SEEDS})")
    print(f"  Dates: {len(sorted_dates)}")
    print(f"  Legs:  {len(cv)}")
    print(f"  Temperature: {TEMP}")
    print(f"{'='*70}")

    # --- Baseline (all 33 features) ---
    print(f"\n[0/33+] BASELINE (all 33 features) ...")
    t0 = time.time()
    baseline_brier = run_lodo_fast(cv, list(FEATS_BASE), um, hit_arr, date_arr, sorted_dates)
    t_baseline = time.time() - t0
    print(f"  Baseline LODO Brier: {baseline_brier:.6f}  ({t_baseline:.0f}s)")

    results = []

    # --- LOO: drop each feature one at a time ---
    print(f"\n{'='*70}")
    print(f"PHASE 1: LEAVE-ONE-OUT (drop each of 33 features)")
    print(f"{'='*70}")

    for i, feat in enumerate(FEATS_BASE):
        feats_reduced = [f for f in FEATS_BASE if f != feat]
        print(f"\n[{i+1}/33] DROP '{feat}' ({len(feats_reduced)} features) ...", end=" ", flush=True)
        t0 = time.time()
        brier = run_lodo_fast(cv, feats_reduced, um, hit_arr, date_arr, sorted_dates)
        elapsed = time.time() - t0
        delta_mB = (brier - baseline_brier) * 1000
        verdict = "HELPS (keep)" if delta_mB > 0.05 else ("HURTS (drop)" if delta_mB < -0.05 else "NEUTRAL")
        print(f"Brier={brier:.6f}  delta={delta_mB:+.3f} mB  ({elapsed:.0f}s)  {verdict}")
        results.append({
            "test": f"DROP {feat}",
            "n_feats": len(feats_reduced),
            "brier": brier,
            "delta_mB": delta_mB,
            "verdict": verdict,
            "elapsed_s": elapsed,
        })

    # --- ADD-ONE: test extra candidate features ---
    EXTRA_CANDIDATES = ["opp_defense_rel", "usage_dep_feat", "fragility_feat",
                        "role_ctx_mult_feat", "z_line_abs", "bp_has_x_under"]
    if any(f in cv.columns for f in EXTRA_CANDIDATES):
        print(f"\n{'='*70}")
        print(f"PHASE 2: ADD-ONE (test extra candidate features)")
        print(f"{'='*70}")

        for feat in EXTRA_CANDIDATES:
            if feat not in cv.columns or cv[feat].isna().mean() > 0.95:
                print(f"\n  SKIP '{feat}' (not in cache or >95% NaN)")
                continue
            feats_extended = list(FEATS_BASE) + [feat]
            print(f"\n[+] ADD '{feat}' ({len(feats_extended)} features) ...", end=" ", flush=True)
            t0 = time.time()
            brier = run_lodo_fast(cv, feats_extended, um, hit_arr, date_arr, sorted_dates)
            elapsed = time.time() - t0
            delta_mB = (brier - baseline_brier) * 1000
            verdict = "HELPS (add)" if delta_mB < -0.05 else ("HURTS" if delta_mB > 0.05 else "NEUTRAL")
            print(f"Brier={brier:.6f}  delta={delta_mB:+.3f} mB  ({elapsed:.0f}s)  {verdict}")
            results.append({
                "test": f"ADD {feat}",
                "n_feats": len(feats_extended),
                "brier": brier,
                "delta_mB": delta_mB,
                "verdict": verdict,
                "elapsed_s": elapsed,
            })

    # --- Summary ---
    print(f"\n\n{'='*70}")
    print(f"ABLATION SWEEP RESULTS")
    print(f"  Baseline: {baseline_brier:.6f} ({len(FEATS_BASE)} features, {len(SEEDS)} seed(s))")
    print(f"{'='*70}\n")

    # Sort by delta (most positive = feature helps most when present = worst when dropped)
    results_sorted = sorted(results, key=lambda x: -x["delta_mB"])

    print(f"{'Test':<30} {'N':>4} {'Brier':>10} {'Delta mB':>10} {'Verdict'}")
    print("-" * 75)
    for r in results_sorted:
        print(f"{r['test']:<30} {r['n_feats']:>4} {r['brier']:>10.6f} {r['delta_mB']:>+10.3f} {r['verdict']}")

    # Feature value ranking
    print(f"\n\n{'='*70}")
    print(f"FEATURE VALUE RANKING (LOO impact: positive = feature is valuable)")
    print(f"{'='*70}\n")

    loo_results = [r for r in results if r["test"].startswith("DROP")]
    loo_sorted = sorted(loo_results, key=lambda x: -x["delta_mB"])

    print(f"{'Rank':>4} {'Feature':<25} {'LOO Delta mB':>12} {'Verdict'}")
    print("-" * 55)
    for rank, r in enumerate(loo_sorted, 1):
        feat_name = r["test"].replace("DROP ", "")
        print(f"{rank:>4} {feat_name:<25} {r['delta_mB']:>+12.3f} {r['verdict']}")

    total_elapsed = time.time() - t_start
    print(f"\nTotal time: {total_elapsed/60:.1f} min ({total_elapsed/3600:.1f} hrs)")

    # Save results JSON
    out = {
        "baseline_brier": baseline_brier,
        "n_features": len(FEATS_BASE),
        "n_seeds": len(SEEDS),
        "n_dates": len(sorted_dates),
        "n_legs": len(cv),
        "temperature": TEMP,
        "cache": args.cache,
        "results": results,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_path = ROOT / "data" / "model" / "feature_ablation_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

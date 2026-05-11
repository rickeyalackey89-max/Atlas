"""
Expand the bak resim cache (44 dates, 68 enrichment cols) with 6 new dates
by loading each date's eval_legs.csv, computing GBM features, and appending.

Player TE is recomputed globally so encoding reflects full 50-date dataset.

Usage:
    python tools/expand_resim_cache.py [--dry-run] [--out <cache_name>]

Default output: data/model/_v18_resim_cache.pkl
"""

import sys, pathlib, math, json, time, pickle, argparse
import warnings
warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit
from Atlas.core.minutes import minutes_sensitivity

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BAK_CACHE = ROOT / "data" / "model" / "_v17_resim_cache.bak.pkl"

# Best 4-6pm runs for each new date (eval=True)
NEW_DATE_RUNS = {
    "2026-04-30": ROOT / "data/output/runs/20260430_182420",
    "2026-05-01": ROOT / "data/output/runs/20260501_173306",
    "2026-05-02": ROOT / "data/output/runs/20260502_173644",
    "2026-05-03": ROOT / "data/output/runs/20260503_173637",
    "2026-05-04": ROOT / "data/output/runs/20260504_173457",
    "2026-05-05": ROOT / "data/output/runs/20260505_173532",
}

FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]

STAT_COLUMN_MAP = {
    "PTS": ["pts"], "POINTS": ["pts"], "REB": ["reb"], "REBS": ["reb"],
    "AST": ["ast"], "ASTS": ["ast"], "FG3M": ["fg3m"], "3PM": ["fg3m"],
    "FGA": ["fga"], "FTA": ["fta"], "TOV": ["tov"],
    "PA": ["pts", "ast"], "PR": ["pts", "reb"], "RA": ["reb", "ast"],
    "PRA": ["pts", "reb", "ast"],
}
STAT_CATS  = {"PTS":0,"REB":1,"AST":2,"FG3M":3,"PRA":4,"PR":5,"PA":6,"RA":7,"FGA":8,"FTA":9,"TOV":10}
TIER_CATS  = {"STANDARD":0,"GOBLIN":1,"DEMON":2}
COMBOS     = {"PRA","PR","PA","RA"}
TEAM_NORM  = {"GS":"GSW","NO":"NOP","NY":"NYK","SA":"SAS","UTAH":"UTA",
              "WSH":"WAS","PHO":"PHX","BRO":"BKN"}
P_LO, P_HI = 0.03, 0.97
SMOOTH_K    = 20


# ---------------------------------------------------------------------------
# Gamelog helpers (mirrors gbm_v17_train.py)
# ---------------------------------------------------------------------------
def load_gamelogs():
    logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.sort_values(["player","game_date"],ascending=[True,False]).reset_index(drop=True)
    for col in ["team","opp"]:
        logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)
    return logs


def build_player_history(logs):
    _logs = logs.sort_values(["player","game_date"]).reset_index(drop=True)
    ph = {}
    for _, row in _logs.iterrows():
        pl = str(row.get("player","")).strip()
        gd = row["game_date"]
        if pd.isna(gd):
            continue
        gd_str = gd.strftime("%Y-%m-%d")
        stats = {}
        for c in ["pts","reb","ast","fg3m","fga","fta","tov"]:
            val = row.get(c)
            if val is not None:
                try:
                    v = float(val)
                    if math.isfinite(v):
                        stats[c] = v
                except (ValueError, TypeError):
                    pass
        if pl and stats:
            ph.setdefault(pl,[]).append((gd_str,stats))
    for p in ph:
        ph[p].sort(key=lambda x: x[0])
    return ph


def build_b2b_set(logs):
    gl = logs[["player","game_date"]].dropna(subset=["game_date"]).copy()
    gl = gl.sort_values(["player","game_date"])
    gl["prev"] = gl.groupby("player")["game_date"].shift(1)
    gl["days"] = (gl["game_date"] - gl["prev"]).dt.days
    b2b = set()
    for _, r in gl.iterrows():
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
            for ev in d.get("events",[]):
                h = str(ev.get("homeTeam","")).upper()
                a = str(ev.get("awayTeam","")).upper()
                ou = float(ev.get("ou",0))
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


# ---------------------------------------------------------------------------
# Feature engineering (mirrors gbm_v17_train.py :: compute_features)
# ---------------------------------------------------------------------------
def compute_features(df, player_history, b2b_set, ou_cache):
    """Compute all 33 GBM FEATS on df in-place. Modifies df. Returns um (bool array)."""
    print(f"  Computing features for {len(df)} rows ...")
    t0 = time.time()

    dir_u = df["direction"].astype(str).str.upper()
    um = (dir_u == "UNDER").values

    for col in ["p_new","rate_mean","rate_std","min_mean","min_std",
                "games_used","q_blowout","form_z_line","external_prior_score","external_prior_n"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["logit_p"] = sp_logit(np.clip(df["p_new"].values, P_LO, P_HI))

    # z_line
    if "form_z_line" in df.columns and df["form_z_line"].notna().sum() > len(df)*0.5:
        df["z_line"] = df["form_z_line"].fillna(0.0).clip(-5,5)
    else:
        _rm = df["rate_mean"].fillna(0)
        _mm = df["min_mean"].fillna(0)
        _rs = df["rate_std"].fillna(0.01).clip(lower=0.01)
        df["z_line"] = np.where(
            (_rm > 0) & (_mm > 0),
            (_rm * _mm - df["line"]) / np.maximum(_rs * _mm, 0.01),
            0.0
        ).clip(-5, 5)

    _mm = df["min_mean"].fillna(0.0)
    _ms = df["min_std"].fillna(0.0)
    df["min_cv"] = np.where(_mm > 1, np.clip(_ms/_mm,0,1), 0.3)

    df["is_combo"] = df["stat_u"].isin(COMBOS).astype(float)

    df["bp_has"] = 0.0
    df["bp_score_gated"] = 0.0
    if "external_prior_n" in df.columns:
        has_bp = df["external_prior_n"].fillna(0) > 0
        edge = df["external_prior_score"].fillna(0.0) - df["line"]
        dm = ((edge > 0) & (dir_u == "OVER")) | ((edge <= 0) & (dir_u == "UNDER"))
        df.loc[has_bp, "bp_has"] = 1.0
        df.loc[has_bp & dm, "bp_score_gated"] = np.tanh(edge[has_bp & dm] / 3.0)

    df["is_assists"] = (df["stat_u"] == "AST").astype(float)
    df["is_threes"]  = (df["stat_u"] == "FG3M").astype(float)
    df["games_norm"] = np.clip(df["games_used"].values / 50.0, 0.0, 1.0)
    df["thin_flag"]  = (df["games_used"] < 15).astype(float)
    df["line_norm"]  = np.clip(df["line"].values / 40.0, 0.0, 2.0)

    # is_home
    if "is_home" not in df.columns or df["is_home"].isna().mean() > 0.5:
        if "home_team" in df.columns and "team" in df.columns:
            df["is_home"] = (df["team"].astype(str).str.upper().str.strip() ==
                             df["home_team"].astype(str).str.upper().str.strip()).astype(float)
        elif "home" in df.columns:
            df["is_home"] = pd.to_numeric(df["home"], errors="coerce").fillna(0.0)
        else:
            df["is_home"] = 0.0

    df["is_home_feat"]   = df["is_home"].fillna(0.0).values.astype(float)
    df["min_sensitivity"] = df["stat_u"].apply(
        lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0
    ).values.astype(float)
    df["is_under"] = um.astype(float)

    _gd_strs = df["game_date"].astype(str).str[:10].values
    _teams   = df["team"].astype(str).str.upper().str.strip().values
    _gt_vals = np.array([ou_cache.get(g,{}).get(t,0.0) for g,t in zip(_gd_strs,_teams)])
    df["game_total_norm"] = np.where(_gt_vals > 0, np.clip(_gt_vals/230.0-1.0,-0.15,0.15), 0.0)

    _players = df["player"].astype(str).str.strip().values
    df["is_b2b"] = np.array([1.0 if (p,g) in b2b_set else 0.0
                              for p,g in zip(_players,_gd_strs)])

    df["is_demon"]        = (df["tier"] == "DEMON").astype(float)
    df["logit_p_x_demon"] = df["logit_p"] * df["is_demon"]
    df["stat_cat"]        = df["stat_u"].map(STAT_CATS).fillna(11).astype(int)
    df["tier_cat"]        = df["tier"].map(TIER_CATS).fillna(0).astype(int)
    df["q_blowout"]       = pd.to_numeric(df.get("q_blowout",0.0),errors="coerce").fillna(0.0)
    df["q_x_under"]       = df["q_blowout"] * df["is_under"]

    # Window features from gamelogs
    hr20 = np.full(len(df), np.nan)
    hr40 = np.full(len(df), np.nan)
    margin_arr     = np.full(len(df), np.nan)
    line_dist      = np.zeros(len(df))
    tail_risk      = np.zeros(len(df))
    line_tightness = np.zeros(len(df))
    rate_cv_arr    = np.zeros(len(df))
    l10_has        = np.zeros(len(df))

    _su_arr = df["stat_u"].values
    _ln_arr = df["line"].astype(float).values
    _dr_arr = df["direction"].astype(str).str.upper().values

    for i in range(len(df)):
        pl = _players[i]; su = _su_arr[i]; ln = _ln_arr[i]; dr = _dr_arr[i]; gd = _gd_strs[i]
        actuals = get_recent(player_history, pl, su, gd, n=50)
        if not actuals:
            continue
        a20 = actuals[-20:]
        if len(a20) >= 5:
            h = sum(1 for v in a20 if v >= ln-1e-9) if dr=="OVER" else sum(1 for v in a20 if v <= ln+1e-9)
            hr20[i] = h / len(a20)
            mu = np.mean(a20); std20 = np.std(a20)
            if mu > 0.1:
                rate_cv_arr[i] = np.clip(std20/mu, 0, 2.0)
            if ln > 0.5:
                line_dist[i] = np.clip((mu-ln)/ln, -0.5, 0.5)
            if std20 > 0.1 and ln > 0.5:
                tail_risk[i] = np.clip((ln-mu)/std20, -3, 3)
            tight = sum(1 for v in a20 if abs(v-ln) <= 1.5)
            line_tightness[i] = tight / len(a20)
        a10 = actuals[-10:]
        if len(a10) >= 5:
            l10_has[i] = 1.0
            margins = np.array(a10) - ln
            if dr == "UNDER":
                margins = -margins
            margin_arr[i] = np.clip(np.mean(margins)/max(ln,1.0), -0.5, 0.5)
        a40 = actuals[-40:]
        if len(a40) >= 5:
            h = sum(1 for v in a40 if v >= ln-1e-9) if dr=="OVER" else sum(1 for v in a40 if v <= ln+1e-9)
            hr40[i] = h / len(a40)

    df["l20_edge"]      = np.where(np.isfinite(hr20), hr20-0.5, 0.0)
    df["l10_has"]       = l10_has
    df["l40_hr"]        = np.where(np.isfinite(hr40), hr40, -1.0)
    df["margin"]        = np.where(np.isfinite(margin_arr), margin_arr, 0.0)
    df["line_dist"]     = line_dist
    df["tail_risk"]     = tail_risk
    df["line_tightness"]= line_tightness
    df["rate_cv"]       = rate_cv_arr
    df["margin_x_under"]= df["margin"] * df["is_under"]
    df["abs_logit_p"]   = np.abs(df["logit_p"])

    print(f"  Features done ({time.time()-t0:.1f}s)")
    return um


# ---------------------------------------------------------------------------
# Player TE (global, must run on full combined dataset)
# ---------------------------------------------------------------------------
def compute_player_te(cv, um):
    print("Computing player TE on full dataset ...")
    hit_arr    = cv["hit"].values.astype(float)
    player_col = cv["player"].astype(str).str.strip().values
    stat_col   = cv["stat_u"].values
    global_hr  = float(hit_arr.mean())

    pa, psa, pda = {}, {}, {}
    for j in range(len(cv)):
        p, h, s, u = player_col[j], hit_arr[j], stat_col[j], um[j]
        pa[p]     = (pa[p][0]+h,  pa[p][1]+1)  if p in pa  else (h, 1)
        k = (p,s)
        psa[k]    = (psa[k][0]+h, psa[k][1]+1) if k in psa else (h, 1)
        k = (p,u)
        pda[k]    = (pda[k][0]+h, pda[k][1]+1) if k in pda else (h, 1)

    player_te  = np.full(len(cv), 0.0)
    player_ste = np.full(len(cv), 0.0)
    player_dte = np.full(len(cv), 0.0)
    for j in range(len(cv)):
        p, s, u = player_col[j], stat_col[j], um[j]
        if p in pa:
            sh,sc = pa[p]; player_te[j]  = (sh+SMOOTH_K*global_hr)/(sc+SMOOTH_K)-global_hr
        if (p,s) in psa:
            sh,sc = psa[(p,s)]; player_ste[j] = (sh+SMOOTH_K*global_hr)/(sc+SMOOTH_K)-global_hr
        if (p,u) in pda:
            sh,sc = pda[(p,u)]; player_dte[j] = (sh+SMOOTH_K*global_hr)/(sc+SMOOTH_K)-global_hr

    cv["player_te"]     = player_te
    cv["player_stat_te"]= player_ste
    cv["player_dir_te"] = player_dte
    pc = pd.Series(player_col).value_counts()
    cv["player_n_norm"] = np.clip(
        pd.Series(player_col).map(pc).fillna(0).values.astype(float)/200.0, 0.0, 1.0
    )
    return pa, psa, pda, global_hr


# ---------------------------------------------------------------------------
# Load one new date from eval_legs.csv
# ---------------------------------------------------------------------------
def load_new_date(date_str, run_dir):
    ev_path = run_dir / "eval_legs.csv"
    if not ev_path.exists():
        raise FileNotFoundError(f"eval_legs.csv missing: {ev_path}")
    df = pd.read_csv(ev_path, low_memory=False)
    print(f"  {date_str}: {len(df)} rows, {len(df.columns)} cols, "
          f"hit={df['hit'].notna().sum()}/{len(df)}")

    # Standardize stat_u
    if "stat_u" not in df.columns:
        if "stat" in df.columns:
            df["stat_u"] = df["stat"].astype(str).str.upper().str.strip()
        else:
            raise ValueError(f"No stat/stat_u in eval_legs for {date_str}")
    else:
        df["stat_u"] = df["stat_u"].astype(str).str.upper().str.strip()

    # p_new from p
    if "p_new" not in df.columns:
        if "p" in df.columns:
            df["p_new"] = df["p"].astype(float)
        else:
            raise ValueError(f"No p/p_new column for {date_str}")
    else:
        if df["p_new"].isna().mean() > 0.5 and "p" in df.columns:
            df["p_new"] = df["p"].astype(float)

    # Ensure games_used
    if "games_used" not in df.columns:
        df["games_used"] = df.get("games_norm", pd.Series(20, index=df.index))
        df["games_used"] = pd.to_numeric(df["games_used"], errors="coerce").fillna(20)

    # game_date
    df["game_date"] = df["game_date"].astype(str).str[:10]

    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Check inputs only, do not write output")
    parser.add_argument("--out", default="v18",
                        help="Output cache name, e.g. v18 -> _v18_resim_cache.pkl")
    args = parser.parse_args()

    out_path = ROOT / "data" / "model" / f"_{args.out}_resim_cache.pkl"

    # ------------------------------------------------------------------
    # 1. Load bak
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"Loading bak cache: {BAK_CACHE}")
    if not BAK_CACHE.exists():
        print("ERROR: bak cache not found"); sys.exit(1)
    with open(BAK_CACHE, "rb") as f:
        bak = pickle.load(f)
    cv_bak = bak["cv"].copy()
    bak_dates = set(bak["dates"])
    print(f"  Bak: {len(cv_bak)} rows, {len(bak_dates)} dates, {len(cv_bak.columns)} cols")

    # Verify bak has all 33 FEATS
    missing_feats = [f for f in FEATS if f not in cv_bak.columns]
    if missing_feats:
        print(f"ERROR: Bak missing GBM FEATS: {missing_feats}"); sys.exit(1)
    print(f"  All 33 GBM FEATS confirmed in bak")

    # Ensure stat_u in bak
    if "stat_u" not in cv_bak.columns and "stat" in cv_bak.columns:
        cv_bak["stat_u"] = cv_bak["stat"].astype(str).str.upper().str.strip()
    if "p_new" not in cv_bak.columns and "p" in cv_bak.columns:
        cv_bak["p_new"] = cv_bak["p"].astype(float)

    # ------------------------------------------------------------------
    # 2. Verify new date inputs
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Checking new date inputs ...")
    for date_str, run_dir in NEW_DATE_RUNS.items():
        ev_path = run_dir / "eval_legs.csv"
        if date_str in bak_dates:
            print(f"  SKIP {date_str} -- already in bak")
            continue
        if not ev_path.exists():
            print(f"  ERROR {date_str}: eval_legs.csv missing at {run_dir}"); sys.exit(1)
        ev = pd.read_csv(ev_path, nrows=2)
        n_full = len(pd.read_csv(ev_path))
        print(f"  OK   {date_str}: {n_full} rows, {len(ev.columns)} cols, hit={'hit' in ev.columns}")

    if args.dry_run:
        print("\nDRY RUN -- stopping before write"); sys.exit(0)

    # ------------------------------------------------------------------
    # 3. Load gamelogs for feature engineering
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Loading gamelogs ...")
    logs = load_gamelogs()
    print("Building player history ...")
    player_history = build_player_history(logs)
    b2b_set  = build_b2b_set(logs)
    ou_cache = load_ou_cache()

    # ------------------------------------------------------------------
    # 4. Load & engineer features for new dates
    # ------------------------------------------------------------------
    new_dfs = []
    for date_str, run_dir in sorted(NEW_DATE_RUNS.items()):
        if date_str in bak_dates:
            print(f"Skipping {date_str} (already in bak)")
            continue
        print(f"\nProcessing {date_str} ...")
        df = load_new_date(date_str, run_dir)
        compute_features(df, player_history, b2b_set, ou_cache)
        new_dfs.append(df)

    # ------------------------------------------------------------------
    # 5. Concatenate bak + new rows (keep all columns, fill NaN for missing)
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Concatenating ...")
    combined = pd.concat([cv_bak] + new_dfs, ignore_index=True, sort=False)
    combined["game_date"] = combined["game_date"].astype(str).str[:10]
    all_dates = sorted(combined["game_date"].unique().tolist())
    print(f"  Combined: {len(combined)} rows, {len(all_dates)} dates, {len(combined.columns)} cols")

    # Verify all 33 FEATS present
    missing = [f for f in FEATS if f not in combined.columns]
    if missing:
        print(f"ERROR after concat: missing FEATS: {missing}"); sys.exit(1)

    # ------------------------------------------------------------------
    # 6. Recompute player TE globally
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    if "hit" not in combined.columns or combined["hit"].isna().sum() > 0:
        n_missing_hit = combined["hit"].isna().sum() if "hit" in combined.columns else len(combined)
        print(f"WARNING: {n_missing_hit} rows missing hit label — dropping before TE")
        combined = combined.dropna(subset=["hit"]).reset_index(drop=True)
        all_dates = sorted(combined["game_date"].unique().tolist())

    um_full = (combined["direction"].astype(str).str.upper() == "UNDER").values
    pa, psa, pda, global_hr = compute_player_te(combined, um_full)

    # ------------------------------------------------------------------
    # 7. Compute raw Brier (using p column as raw kernel prob)
    # ------------------------------------------------------------------
    p_col = "p" if "p" in combined.columns else "p_new"
    valid_p = combined[p_col].notna() & combined["hit"].notna()
    raw_brier = float(((combined.loc[valid_p, p_col] - combined.loc[valid_p, "hit"]) ** 2).mean())
    hit_rate  = float(combined["hit"].mean())
    print(f"\nFinal dataset:")
    print(f"  Rows:      {len(combined)}")
    print(f"  Dates:     {len(all_dates)}  ({all_dates[0]} to {all_dates[-1]})")
    print(f"  Columns:   {len(combined.columns)}")
    print(f"  Hit rate:  {hit_rate:.4f}")
    print(f"  Raw Brier: {raw_brier:.6f}")
    print(f"  FEATS OK:  {all(f in combined.columns for f in FEATS)}")

    # Column breakdown
    diag_cols = ["p","p_role","p_adj","p_cal","p_for_cal","fragility","spread",
                 "opp","external_prior_score","sb_over_prob","usage_dep","min_mean",
                 "min_std","minutes_s","rate_mean","rate_std","is_home","is_star",
                 "games_used","opp_defense_strength","thin_window_mult","recent_form_blend",
                 "rotowire_game_spread","is_questionable","p_new","external_prior_sources"]
    n_diag = sum(1 for c in diag_cols if c in combined.columns)
    print(f"  Diag cols: {n_diag}/{len(diag_cols)} enrichment cols present")

    # ------------------------------------------------------------------
    # 8. Save
    # ------------------------------------------------------------------
    import yaml as _yaml
    with open(ROOT / "config.yaml") as f:
        cfg = _yaml.safe_load(f)

    cache_out = {
        "cv":     combined,
        "dates":  all_dates,
        "raw_brier": raw_brier,
        "version": args.out,
        "config_snapshot": {
            "spread_sd":         cfg.get("blowout",{}).get("spread_sd"),
            "star_minute_drop":  cfg.get("blowout",{}).get("star_minute_drop"),
        },
        "capture_keys": list(combined.columns),
        "um":     um_full,
    }

    # Backup existing target if it exists
    if out_path.exists():
        bak_out = out_path.with_suffix(".bak.pkl")
        out_path.rename(bak_out)
        print(f"Backed up existing {out_path.name} -> {bak_out.name}")

    with open(out_path, "wb") as f:
        pickle.dump(cache_out, f, protocol=4)
    print(f"\nSaved -> {out_path}")
    print(f"  Size: {out_path.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()

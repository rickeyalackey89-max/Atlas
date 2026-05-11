"""Build playoff resim cache from cat_corpus_* replay runs.

Mirrors build_resim_cache.py + gbm_v12_train.py feature engineering exactly.
Scans data/telemetry/replay_runs/cat_corpus_YYYYMMDD dirs, merges hit labels,
computes the full 33-feature GBM feature set, and saves a pickle cache that
catboost_playoff_lodo.py can read identically to how GBM reads its resim cache.

Output:
    data/model/_v1_playoff_resim_cache.pkl

Usage:
    python tools/build_playoff_resim_cache.py
    python tools/build_playoff_resim_cache.py --force     # overwrite existing
    python tools/build_playoff_resim_cache.py --dry-run   # plan only
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPLAY_RUNS = ROOT / "data" / "telemetry" / "replay_runs"
MODEL_OUT    = ROOT / "data" / "model"
CACHE_NAME   = "_v1_playoff_resim_cache.pkl"

# Scan prefix for playoff replay dirs (overridable via --prefix)
CORPUS_PREFIX = "cat_corpus_"

# ---------------------------------------------------------------------------
# Constants (must match gbm_v12_train.py exactly)
# ---------------------------------------------------------------------------
STAT_COLUMN_MAP = {
    "PTS":    ["pts"], "POINTS": ["pts"],
    "REB":    ["reb"], "REBS":   ["reb"],
    "AST":    ["ast"], "ASTS":   ["ast"],
    "FG3M":   ["fg3m"], "3PM":   ["fg3m"],
    "FGA":    ["fga"], "FTA":    ["fta"], "TOV": ["tov"],
    "PA":     ["pts", "ast"], "PR":  ["pts", "reb"],
    "RA":     ["reb", "ast"], "PRA": ["pts", "reb", "ast"],
}
STAT_CATS = {
    "PTS": 0, "REB": 1, "AST": 2, "FG3M": 3, "PRA": 4,
    "PR": 5, "PA": 6, "RA": 7, "FGA": 8, "FTA": 9, "TOV": 10,
}
TIER_CATS  = {"STANDARD": 0, "GOBLIN": 1, "DEMON": 2}
COMBOS     = {"PRA", "PR", "PA", "RA"}
TEAM_NORM  = {
    "GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
    "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRO": "BKN",
}
P_LO, P_HI = 0.03, 0.97
SMOOTH_K    = 20

# 33 base GBM features (v9d contract) — CatBoost cache adds p_for_cal on top
BASE_FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]
# Extra columns kept in cache for CatBoost (probability chain + identity)
EXTRA_COLS = [
    "player", "team", "opp", "stat", "stat_u", "line", "direction", "tier",
    "game_date", "hit", "p", "p_role", "p_adj", "p_for_cal", "p_cal",
    "is_home", "is_under",
]


# ---------------------------------------------------------------------------
# Gamelog helpers (identical to gbm_v12_train.py)
# ---------------------------------------------------------------------------

def load_gamelogs() -> pd.DataFrame:
    logs = pd.read_csv(ROOT / "data/gamelogs/nba_gamelogs.csv", low_memory=False)
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.sort_values(["player", "game_date"], ascending=[True, False]).reset_index(drop=True)
    for col in ["team", "opp"]:
        logs[col] = logs[col].astype(str).str.upper().str.strip().replace(TEAM_NORM)
    return logs


def build_player_history(logs: pd.DataFrame) -> dict:
    _sorted = logs.sort_values(["player", "game_date"]).reset_index(drop=True)
    history: dict = {}
    for _, row in _sorted.iterrows():
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
            history.setdefault(pl, []).append((gd_str, stats))
    for p in history:
        history[p].sort(key=lambda x: x[0])
    return history


def build_b2b_set(logs: pd.DataFrame) -> set:
    gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
    gl = gl.sort_values(["player", "game_date"])
    gl["prev"] = gl.groupby("player")["game_date"].shift(1)
    gl["days"] = (gl["game_date"] - gl["prev"]).dt.days
    b2b: set = set()
    for _, r in gl.iterrows():
        if pd.notna(r["days"]) and r["days"] == 1:
            b2b.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))
    return b2b


def load_ou_cache() -> dict:
    iael_dir = ROOT / "data/archives/iael/2026"
    cache: dict = {}
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


def get_recent(player_history: dict, player: str, stat_u: str,
               game_date_str: str, n: int = 50) -> list:
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
# Minutes sensitivity (matches kernel)
# ---------------------------------------------------------------------------

def minutes_sensitivity(stat_u: str) -> float:
    from Atlas.core.minutes import minutes_sensitivity as _ms
    return float(_ms(stat_u))


# ---------------------------------------------------------------------------
# Feature engineering (mirrors gbm_v12_train.py compute_features exactly)
# ---------------------------------------------------------------------------

def compute_features(cv: pd.DataFrame, player_history: dict,
                     b2b_set: set, ou_cache: dict) -> np.ndarray:
    """Compute all 33 base GBM features in-place. Returns um (is_under) array."""
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
            0.0,
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
    cv["is_threes"]  = (cv["stat_u"] == "FG3M").astype(float)
    cv["games_norm"] = np.clip(cv["games_used"].values / 50.0, 0.0, 1.0)
    cv["thin_flag"]  = (cv["games_used"] < 15).astype(float)
    cv["line_norm"]  = np.clip(cv["line"].values / 40.0, 0.0, 2.0)

    # is_home
    if "is_home" not in cv.columns or cv["is_home"].isna().mean() > 0.5:
        if "home_team" in cv.columns and "team" in cv.columns:
            cv["is_home"] = (
                cv["team"].astype(str).str.upper().str.strip()
                == cv["home_team"].astype(str).str.upper().str.strip()
            ).astype(float)
        elif "home" in cv.columns:
            cv["is_home"] = pd.to_numeric(cv["home"], errors="coerce").fillna(0.0)
        else:
            cv["is_home"] = 0.0
    cv["is_home_feat"] = cv["is_home"].fillna(0.0).astype(float)

    cv["min_sensitivity"] = cv["stat_u"].apply(
        lambda x: minutes_sensitivity(str(x)) if pd.notna(x) else 1.0
    ).astype(float)
    cv["is_under"] = um.astype(float)

    # game_total_norm from ou_cache
    _gd_strs = cv["game_date"].astype(str).str[:10].values
    _teams    = cv["team"].astype(str).str.upper().str.strip().values
    _gt_vals  = np.array([
        ou_cache.get(g, {}).get(t, 0.0) for g, t in zip(_gd_strs, _teams)
    ])
    cv["game_total_norm"] = np.where(
        _gt_vals > 0,
        np.clip(_gt_vals / 230.0 - 1.0, -0.15, 0.15),
        0.0,
    )

    # is_b2b
    _players = cv["player"].astype(str).str.strip().values
    cv["is_b2b"] = np.array([
        1.0 if (p, g) in b2b_set else 0.0
        for p, g in zip(_players, _gd_strs)
    ])

    # logit_p_x_demon
    cv["is_demon"]          = (cv["tier"] == "DEMON").astype(float)
    cv["logit_p_x_demon"]   = cv["logit_p"] * cv["is_demon"]

    # Categoricals
    cv["stat_cat"] = cv["stat_u"].map(STAT_CATS).fillna(11).astype(int)
    cv["tier_cat"] = cv["tier"].map(TIER_CATS).fillna(0).astype(int)

    # q_blowout
    cv["q_blowout"] = pd.to_numeric(cv.get("q_blowout", 0.0), errors="coerce").fillna(0.0)
    cv["q_x_under"] = cv["q_blowout"] * cv["is_under"]

    # Window features from gamelogs
    print("Computing window features ...")
    hr20         = np.full(len(cv), np.nan)
    hr40         = np.full(len(cv), np.nan)
    margin_arr   = np.full(len(cv), np.nan)
    line_dist    = np.zeros(len(cv))
    tail_risk    = np.zeros(len(cv))
    line_tight   = np.zeros(len(cv))
    rate_cv_arr  = np.zeros(len(cv))
    l10_has      = np.zeros(len(cv))

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
            h = sum(1 for v in a20 if v >= ln - 1e-9) if dr == "OVER" \
                else sum(1 for v in a20 if v <= ln + 1e-9)
            hr20[i] = h / len(a20)
            mu   = np.mean(a20)
            std20 = np.std(a20)
            if mu > 0.1:
                rate_cv_arr[i] = np.clip(std20 / mu, 0, 2.0)
            if ln > 0.5:
                line_dist[i] = np.clip((mu - ln) / ln, -0.5, 0.5)
            if std20 > 0.1 and ln > 0.5:
                tail_risk[i] = np.clip((ln - mu) / std20, -3, 3)
            tight = sum(1 for v in a20 if abs(v - ln) <= 1.5)
            line_tight[i] = tight / len(a20)

        a10 = actuals[-10:]
        if len(a10) >= 5:
            l10_has[i] = 1.0
            margins = np.array(a10) - ln
            if dr == "UNDER":
                margins = -margins
            margin_arr[i] = np.clip(np.mean(margins) / max(ln, 1.0), -0.5, 0.5)

        a40 = actuals[-40:]
        if len(a40) >= 5:
            h = sum(1 for v in a40 if v >= ln - 1e-9) if dr == "OVER" \
                else sum(1 for v in a40 if v <= ln + 1e-9)
            hr40[i] = h / len(a40)

        if (i + 1) % 5000 == 0:
            print(f"  {i+1}/{len(cv)} ({(i+1)/len(cv)*100:.0f}%)")

    cv["l20_edge"]      = np.where(np.isfinite(hr20), hr20 - 0.5, 0.0)
    cv["l10_has"]       = l10_has
    cv["l40_hr"]        = np.where(np.isfinite(hr40), hr40, -1.0)
    cv["margin"]        = np.where(np.isfinite(margin_arr), margin_arr, 0.0)
    cv["line_dist"]     = line_dist
    cv["tail_risk"]     = tail_risk
    cv["line_tightness"]= line_tight
    cv["rate_cv"]       = rate_cv_arr
    cv["margin_x_under"]= cv["margin"] * cv["is_under"]
    cv["abs_logit_p"]   = np.abs(cv["logit_p"])

    print(f"Features done ({time.time() - t0:.1f}s)")
    return um


def compute_player_te(cv: pd.DataFrame, um: np.ndarray,
                      ) -> tuple[dict, dict, dict, float]:
    """Populate player_te, player_stat_te, player_dir_te using the SAME path
    that runtime inference uses: read player_te_lookup.json via the engine's
    _enrich_te_columns() helper. This guarantees the training cache features
    match what CatBoost will see at inference.

    The previous implementation computed TE from the 9-date playoff corpus
    hits, which produced TE values that diverged from inference (in some cases
    even flipped sign), causing the trained CatBoost model to regress at
    deployment.

    Returns ({}, {}, {}, global_hr) — the dict returns are unused downstream
    but kept for API compatibility.
    """
    print("Enriching player TE from data/model/ensemble/player_te_lookup.json ...")
    from Atlas.engine.gbm_ensemble import _enrich_te_columns  # type: ignore[import]

    ensemble_dir = ROOT / "data" / "model" / "ensemble"
    lookup_path = ensemble_dir / "player_te_lookup.json"
    if not lookup_path.exists():
        raise FileNotFoundError(
            f"player_te_lookup.json not found at {lookup_path} — "
            "TE enrichment requires the same lookup that inference uses."
        )

    # _enrich_te_columns skips if columns are already populated; ensure they
    # are zeroed (or absent) so it always overwrites with lookup values.
    for col in ("player_te", "player_stat_te", "player_dir_te"):
        if col in cv.columns:
            cv.drop(columns=[col], inplace=True)

    # _enrich_te_columns returns a copy; we need to mutate cv in place to keep
    # the caller's reference valid.
    enriched = _enrich_te_columns(cv, ensemble_dir)
    cv["player_te"]      = enriched["player_te"].values
    cv["player_stat_te"] = enriched["player_stat_te"].values
    cv["player_dir_te"]  = enriched["player_dir_te"].values

    # player_n_norm is count-based, independent of TE source — keep using
    # the corpus-local count (it's a magnitude/dropout signal, not a hit-rate).
    player_col = cv["player"].astype(str).str.strip().values
    pc = pd.Series(player_col).value_counts()
    cv["player_n_norm"] = np.clip(
        pd.Series(player_col).map(pc).fillna(0).values.astype(float) / 200.0,
        0.0, 1.0,
    )

    # Read global_hr from the lookup so the cache record matches inference.
    with open(lookup_path, encoding="utf-8") as f:
        lkp = json.load(f)
    global_hr = float(lkp.get("global_hr", float(cv["hit"].mean())))

    # Diagnostic: how many legs got non-zero TE?
    pte_nz = float((np.abs(cv["player_te"]) > 1e-9).mean()) * 100
    pse_nz = float((np.abs(cv["player_stat_te"]) > 1e-9).mean()) * 100
    pde_nz = float((np.abs(cv["player_dir_te"]) > 1e-9).mean()) * 100
    print(f"  TE coverage from lookup: player_te={pte_nz:.1f}%  "
          f"player_stat_te={pse_nz:.1f}%  player_dir_te={pde_nz:.1f}%")
    print(f"  global_hr (from lookup) = {global_hr:.6f}")

    return {}, {}, {}, global_hr


# ---------------------------------------------------------------------------
# Corpus discovery
# ---------------------------------------------------------------------------

def find_playoff_dates(prefix: str = CORPUS_PREFIX) -> list[tuple[str, Path, Path]]:
    """Scan <prefix>YYYYMMDD dirs. Return (date, scored_path, eval_path)."""
    results = []
    seen: set = set()
    if not REPLAY_RUNS.exists():
        return results

    for d in sorted(REPLAY_RUNS.glob(f"{prefix}*")):
        m = re.search(r"(\d{8})$", d.name)
        if not m:
            continue
        date = m.group(1)
        if date in seen:
            continue

        scored_candidates = sorted(
            d.rglob("scored_legs_deduped.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not scored_candidates:
            continue

        best_scored = None
        best_eval   = None
        for sc in scored_candidates:
            co_eval = sc.parent / "eval_legs.csv"
            if co_eval.is_file() and co_eval.stat().st_size > 100:
                best_scored = sc
                best_eval   = co_eval
                break
        if not best_scored:
            best_scored = scored_candidates[0]
            evals = sorted(d.rglob("eval_legs.csv"), key=lambda p: p.stat().st_mtime)
            if evals:
                best_eval = evals[-1]

        if best_scored and best_eval:
            seen.add(date)
            results.append((date, best_scored, best_eval))

    results.sort(key=lambda x: x[0])
    return results


# ---------------------------------------------------------------------------
# Date loading + merge
# ---------------------------------------------------------------------------

def load_and_merge_date(date: str, scored_path: Path,
                        eval_path: Path) -> pd.DataFrame | None:
    try:
        scored  = pd.read_csv(scored_path, low_memory=False)
        eval_df = pd.read_csv(eval_path,   low_memory=False)
    except Exception as e:
        print(f"  [{date}] SKIP -- read error: {e}")
        return None

    if scored.empty:
        print(f"  [{date}] SKIP -- empty scored_legs")
        return None

    # Merge hit from eval_legs
    if "hit" in eval_df.columns and eval_df["hit"].notna().any():
        merge_cols = ["player", "stat", "line", "direction"]
        available  = [c for c in merge_cols if c in scored.columns and c in eval_df.columns]
        if available:
            eval_sub = eval_df[available + ["hit"]].copy()
            eval_sub = eval_sub.drop_duplicates(subset=available, keep="last")
            if "hit" in scored.columns:
                scored = scored.drop(columns=["hit"])
            scored = scored.merge(eval_sub, on=available, how="left")

    if "hit" not in scored.columns or scored["hit"].isna().all():
        print(f"  [{date}] SKIP -- no hit data after merge")
        return None

    hit_cov = scored["hit"].notna().mean()
    if hit_cov < 0.5:
        print(f"  [{date}] SKIP -- low hit coverage {hit_cov*100:.0f}%")
        return None

    # Column aliases expected by feature engine
    if "p" in scored.columns and "p_new" not in scored.columns:
        scored["p_new"] = scored["p"].values
    if "stat" in scored.columns and "stat_u" not in scored.columns:
        scored["stat_u"] = scored["stat"].astype(str).str.upper().str.strip()
    if "home" in scored.columns and "is_home" not in scored.columns:
        scored["is_home"] = pd.to_numeric(scored["home"], errors="coerce").fillna(0.0)

    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    scored["game_date"] = iso_date

    print(f"  [{date}] OK: {len(scored):>5,} legs, "
          f"{scored['hit'].notna().sum():>5,} hit ({hit_cov*100:.0f}%)")
    return scored


# ---------------------------------------------------------------------------
# Feature report
# ---------------------------------------------------------------------------

def print_feature_report(cv: pd.DataFrame) -> None:
    print(f"\nFeature coverage ({len(BASE_FEATS)} base features):")
    missing = []
    for f in BASE_FEATS:
        if f in cv.columns:
            vals = pd.to_numeric(cv[f], errors="coerce")
            cov  = vals.notna().sum() / len(cv) * 100
            mn   = vals.mean()
            print(f"  {f:25s}  cov={cov:5.1f}%  mean={mn:+.4f}")
        else:
            print(f"  {f:25s}  MISSING")
            missing.append(f)
    if missing:
        print(f"\nERROR: {len(missing)} features missing: {missing}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Build playoff v1 resim cache")
    ap.add_argument("--force",   action="store_true", help="Overwrite existing cache")
    ap.add_argument("--dry-run", action="store_true", help="Plan only, no output")
    ap.add_argument("--prefix",  default=CORPUS_PREFIX, help="Corpus dir name prefix (default: cat_corpus_)")
    args = ap.parse_args()
    prefix = args.prefix

    cache_path = MODEL_OUT / CACHE_NAME

    print("=" * 70)
    print(f"Playoff Resim Cache Builder -- v1")
    print("=" * 70)
    print(f"  Corpus prefix: {prefix}*")
    print(f"  Output:        {cache_path.name}")
    print()

    # Safety check
    if cache_path.exists() and not args.force:
        try:
            with open(cache_path, "rb") as f:
                old = pickle.load(f)
            print(f"  ERROR: Cache already exists: {cache_path.name}")
            print(f"    {len(old.get('dates', []))} dates, {len(old.get('cv', []))} legs, "
                  f"raw Brier={old.get('raw_brier', '?')}")
            print(f"    Use --force to overwrite.")
            return 1
        except Exception:
            pass

    # Discover dates
    print("Scanning playoff corpus dirs...")
    all_dates = find_playoff_dates(prefix=prefix)
    if not all_dates:
        print(f"ERROR: No {prefix}* dirs found in data/telemetry/replay_runs/")
        return 1
    print(f"  Found {len(all_dates)} dates: {[d for d, _, _ in all_dates]}\n")

    if args.dry_run:
        print("[DRY RUN] Plan:")
        for date, scored, ev in all_dates:
            print(f"  {date}: {scored.relative_to(ROOT)}")
        print("\n[DRY RUN] No files written.")
        return 0

    # Load and merge
    print(f"Loading {len(all_dates)} dates...")
    frames   = []
    skipped  = []
    for date, scored_path, eval_path in all_dates:
        df = load_and_merge_date(date, scored_path, eval_path)
        if df is not None:
            frames.append((date, df))
        else:
            skipped.append(date)

    if not frames:
        print("ERROR: No valid dates after loading!")
        return 1

    print(f"\nMerging {len(frames)} dates ({len(skipped)} skipped)...")
    if skipped:
        print(f"  Skipped: {skipped}")

    cv = pd.concat([df for _, df in frames], ignore_index=True)

    # Keep only rows with hit labels and valid p_new
    n_before = len(cv)
    cv = cv.dropna(subset=["hit", "p_new"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0.0, 1.0, 0, 1])].reset_index(drop=True)
    print(f"  After hit filter: {n_before:,} -> {len(cv):,} legs")

    # Ensure stat_u is uppercase
    cv["stat_u"] = cv["stat_u"].astype(str).str.upper().str.strip()
    cv["direction"] = cv["direction"].astype(str).str.upper()

    dates = sorted(cv["game_date"].astype(str).str[:10].unique().tolist())
    hit_arr   = cv["hit"].values.astype(float)
    raw_brier = float(np.mean((cv["p_new"].values - hit_arr) ** 2))
    print(f"\nCorpus: {len(cv):,} legs | {len(dates)} dates | "
          f"hit rate={hit_arr.mean():.3f} | raw Brier={raw_brier:.6f}")

    # Load gamelogs and build lookups
    print("\nLoading gamelogs...")
    logs = load_gamelogs()
    print(f"  {len(logs):,} gamelog rows")
    print("Building player history ...")
    player_history = build_player_history(logs)
    b2b_set = build_b2b_set(logs)
    ou_cache = load_ou_cache()
    print(f"  {len(player_history)} players, {len(b2b_set)} b2b pairs, "
          f"{len(ou_cache)} OU dates")

    # Compute features
    um = compute_features(cv, player_history, b2b_set, ou_cache)
    pa_full, psa_full, pda_full, global_hr = compute_player_te(cv, um)
    print_feature_report(cv)

    # Recompute raw Brier using p_new (after feature pass, should be same)
    raw_brier_final = float(np.mean((cv["p_new"].values - hit_arr) ** 2))

    # Feature coverage summary
    print(f"\nFeature summary:")
    for f in BASE_FEATS:
        vals = pd.to_numeric(cv[f], errors="coerce")
        nz   = (vals.fillna(0) != 0).mean()
        print(f"  {f:25s}  nonzero={nz:.1%}  mean={vals.mean():+.4f}")

    # Build cache dict (same structure as GBM resim cache)
    MODEL_OUT.mkdir(parents=True, exist_ok=True)
    cache = {
        "cv":           cv,
        "dates":        dates,
        "raw_brier":    raw_brier_final,
        "version":      "v1_playoff",
        "um":           um,
        "hit_arr":      hit_arr,
        "global_hr":    global_hr,
        "capture_keys": list(cv.columns),
        "base_feats":   BASE_FEATS,
        "corpus_source": {
            date: str(scored_path.relative_to(ROOT))
            for date, scored_path, _ in all_dates
            if date not in skipped
        },
    }

    with open(cache_path, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)

    size_mb = cache_path.stat().st_size / (1024 * 1024)
    print(f"\nSaved: {cache_path} ({size_mb:.1f} MB)")
    print(f"  {len(cv):,} legs | {len(dates)} dates | "
          f"Brier={raw_brier_final:.6f}")
    print(f"  Dates: {dates}")
    print("\nDone. Run catboost_playoff_lodo.py to train.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

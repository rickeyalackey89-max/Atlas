"""Runtime GBM ensemble calibrator.

Loads the v9d (or later) LightGBM ensemble from data/model/ensemble/,
computes a superset of features from the scored DataFrame + gamelogs,
and slices to the feature list specified in ensemble_meta.json before
producing a calibrated probability column.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit

from Atlas.core.minutes import minutes_sensitivity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
P_LO, P_HI = 0.03, 0.97
COMBOS = {"PRA", "PR", "PA", "RA"}
STAT_FAMILIES = {"PTS": "scoring", "AST": "assists", "REB": "rebounds", "FG3M": "threes"}
STAT_COLUMN_MAP = {
    "PTS": ["pts"], "POINTS": ["pts"], "REB": ["reb"], "REBS": ["reb"],
    "AST": ["ast"], "ASTS": ["ast"], "FG3M": ["fg3m"], "3PM": ["fg3m"],
    "FGA": ["fga"], "FTA": ["fta"], "TOV": ["tov"],
    "PA": ["pts", "ast"], "PR": ["pts", "reb"], "RA": ["reb", "ast"],
    "PRA": ["pts", "reb", "ast"],
}
STAT_CATS = {"PTS": 0, "REB": 1, "AST": 2, "FG3M": 3, "PRA": 4, "PR": 5, "PA": 6, "RA": 7, "FGA": 8, "FTA": 9, "TOV": 10}
TIER_CATS = {"STANDARD": 0, "GOBLIN": 1, "DEMON": 2}
SMOOTH_K = 20

# Ordered feature names matching column_stack order in compute_features().
# New features MUST be appended at the end to preserve index stability.
_ALL_FEATURE_NAMES = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
    "sb_over_prob", "sb_line_diff",
    # v16 discovery features
    "opp_defense_rel", "z_line_abs", "fragility_feat", "bp_has_x_under",
    # v17
    "form_z_line",
]

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------
_ensemble_cache: dict[str, Any] = {}


def _load_ensemble(ensemble_dir: Path) -> dict[str, Any]:
    """Load GBM ensemble models and metadata.  Cached after first load."""
    cache_key = str(ensemble_dir)
    if cache_key in _ensemble_cache:
        return _ensemble_cache[cache_key]

    meta_path = ensemble_dir / "ensemble_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"ensemble_meta.json not found in {ensemble_dir}")

    import lightgbm as lgb

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    seeds = meta["ensemble_seeds"]
    temperature = float(meta.get("temperature", 0.98))
    features = meta["features"]

    models_over, models_under = [], []
    for seed in seeds:
        p_over = ensemble_dir / f"posthoc_calibrator_gbm_over_s{seed}.txt"
        p_under = ensemble_dir / f"posthoc_calibrator_gbm_under_s{seed}.txt"
        if not p_over.exists() or not p_under.exists():
            raise FileNotFoundError(f"Missing model file for seed {seed} in {ensemble_dir}")
        models_over.append(lgb.Booster(model_file=str(p_over)))
        models_under.append(lgb.Booster(model_file=str(p_under)))

    result = {
        "meta": meta,
        "seeds": seeds,
        "temperature": temperature,
        "features": features,
        "models_over": models_over,
        "models_under": models_under,
    }
    _ensemble_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Feature engineering (mirrors trainer logic)
# ---------------------------------------------------------------------------

def _build_player_history(logs: pd.DataFrame) -> dict[str, list[tuple[str, dict[str, float]]]]:
    """Build player -> [(date, {stat: val})] lookup from gamelogs."""
    logs_sorted = logs.sort_values(["player", "game_date"]).reset_index(drop=True)
    history: dict[str, list[tuple[str, dict[str, float]]]] = {}
    stat_cols = ["pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]
    for _, row in logs_sorted.iterrows():
        pl = str(row.get("player", "")).strip()
        gd = row["game_date"]
        if pd.isna(gd):
            continue
        gd_str = gd.strftime("%Y-%m-%d") if hasattr(gd, "strftime") else str(gd)[:10]
        stats: dict[str, float] = {}
        for col in stat_cols:
            val = row.get(col)
            if val is not None:
                try:
                    v = float(val)
                    if math.isfinite(v):
                        stats[col] = v
                except (ValueError, TypeError):
                    pass
        if pl and stats:
            history.setdefault(pl, []).append((gd_str, stats))
    for p in history:
        history[p].sort(key=lambda x: x[0])
    return history


def _get_recent(history: dict, player: str, stat_u: str, game_date_str: str, n: int = 50) -> list[float]:
    """Get recent N game actuals for a player/stat before a date."""
    hist = history.get(player)
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


def _compute_b2b_lookup(logs: pd.DataFrame) -> set[tuple[str, str]]:
    """Return set of (player, date_str) for back-to-back games."""
    gl = logs[["player", "game_date"]].dropna(subset=["game_date"]).copy()
    gl["game_date"] = pd.to_datetime(gl["game_date"], errors="coerce")
    gl = gl.dropna(subset=["game_date"])
    gl = gl.sort_values(["player", "game_date"])
    gl["prev_game"] = gl.groupby("player")["game_date"].shift(1)
    gl["days_since"] = (gl["game_date"] - gl["prev_game"]).dt.days
    b2b = set()
    for _, r in gl.iterrows():
        if pd.notna(r["days_since"]) and r["days_since"] == 1:
            b2b.add((str(r["player"]).strip(), r["game_date"].strftime("%Y-%m-%d")))
    return b2b


def compute_features(scored: pd.DataFrame, logs: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Compute the 39 v16 features from a scored DataFrame + gamelogs.

    Returns (X, under_mask) where X is (n_legs, 39) float array and
    under_mask is boolean array of UNDER legs.
    """
    n = len(scored)
    player_history = _build_player_history(logs)
    b2b_set = _compute_b2b_lookup(logs)

    def _col(name: str, default: float = 0.0) -> np.ndarray:
        """Extract a numeric column as a concrete numpy float64 array."""
        if name in scored.columns:
            return np.asarray(pd.to_numeric(scored[name], errors="coerce").fillna(default), dtype=np.float64)
        return np.full(n, default, dtype=np.float64)

    # --- Extract base columns ---
    dir_u = scored["direction"].astype(str).str.upper()
    um: np.ndarray = np.asarray((dir_u == "UNDER").values, dtype=bool)
    stat_u = scored["stat"].astype(str).str.upper().str.strip()
    _stat_norm = {"POINTS": "PTS", "REBOUNDS": "REB", "ASSISTS": "AST", "REBS": "REB", "ASTS": "AST", "3PM": "FG3M"}
    stat_u = stat_u.replace(_stat_norm)

    p_new = _col("p_cal", 0.5)
    if "p_cal" not in scored.columns:
        p_new = _col("p_adj", 0.5) if "p_adj" in scored.columns else _col("p", 0.5)
    logit_p: np.ndarray = sp_logit(np.clip(p_new, P_LO, P_HI))

    line = _col("line", 0.0)
    rate_mean = _col("rate_mean", 0.0)
    rate_std = np.maximum(_col("rate_std", 0.01), 0.01)
    min_mean = _col("min_mean", 0.0)
    min_std = _col("min_std", 0.0)
    games_used = _col("games_used", 0.0)

    # --- z_line: prefer engine-computed form_z_line ---
    if "form_z_line" in scored.columns and scored["form_z_line"].notna().sum() > n * 0.5:
        z_line = np.clip(_col("form_z_line", 0.0), -5.0, 5.0)
    else:
        z_line = np.clip(np.where(
            (rate_mean > 0) & (min_mean > 0),
            (rate_mean * min_mean - line) / np.maximum(rate_std * min_mean, 0.01),
            0.0,
        ), -5.0, 5.0)

    # --- min_cv ---
    min_cv: np.ndarray = np.where(min_mean > 1, np.clip(min_std / np.maximum(min_mean, 1e-9), 0, 1), 0.3)

    # --- is_combo ---
    is_combo: np.ndarray = np.asarray(stat_u.isin(COMBOS), dtype=np.float64)

    # --- BettingPros features ---
    bp_has = np.zeros(n, dtype=np.float64)
    bp_score_gated = np.zeros(n, dtype=np.float64)
    if "external_prior_n" in scored.columns:
        _bp_n = _col("external_prior_n", 0.0)
        has_bp_mask = _bp_n > 0
        bp_has = has_bp_mask.astype(np.float64)
        _bp_score = _col("external_prior_score", 0.0)
        edge = _bp_score - line
        dm = ((edge > 0) & np.asarray(dir_u == "OVER")) | ((edge <= 0) & np.asarray(dir_u == "UNDER"))
        sel = has_bp_mask & dm
        bp_score_gated[sel] = np.tanh(edge[sel] / 3.0)

    # --- Stat family flags ---
    is_assists: np.ndarray = np.asarray(stat_u == "AST", dtype=np.float64)
    is_threes: np.ndarray = np.asarray(stat_u == "FG3M", dtype=np.float64)

    # --- games_norm, thin_flag, line_norm ---
    games_norm: np.ndarray = np.clip(games_used / 50.0, 0.0, 1.0)
    thin_flag: np.ndarray = (games_used < 15).astype(np.float64)
    line_norm: np.ndarray = np.clip(line / 40.0, 0.0, 2.0)

    # --- is_home ---
    is_home_feat = _col("is_home", 0.0)

    # --- min_sensitivity ---
    min_sensitivity: np.ndarray = np.asarray(stat_u.apply(minutes_sensitivity), dtype=np.float64)

    # --- game_total_norm ---
    game_total_norm: np.ndarray = np.clip(_col("game_total_norm", 0.0), -0.15, 0.15)

    # --- is_b2b ---
    is_b2b = np.zeros(n, dtype=np.float64)
    if "game_date" in scored.columns:
        for i in range(n):
            pl = str(scored.iloc[i].get("player", "")).strip()
            gd = str(scored.iloc[i].get("game_date", ""))[:10]
            if (pl, gd) in b2b_set:
                is_b2b[i] = 1.0

    # --- Logit interactions ---
    is_demon: np.ndarray = np.asarray(scored["tier"].astype(str).str.upper() == "DEMON", dtype=np.float64) if "tier" in scored.columns else np.zeros(n, dtype=np.float64)
    logit_p_x_demon: np.ndarray = logit_p * is_demon

    # --- Player TE ---
    player_col: np.ndarray = np.asarray(scored["player"].astype(str).str.strip())
    player_n = pd.Series(player_col).value_counts()
    player_n_norm: np.ndarray = np.clip(np.asarray(pd.Series(player_col).map(player_n), dtype=np.float64) / 200.0, 0.0, 1.0)

    player_te = _col("player_te", 0.0)
    player_stat_te = _col("player_stat_te", 0.0)
    player_dir_te = _col("player_dir_te", 0.0)

    # --- Window features (l20_edge, l10_has, l40_hr, margin, line_dist, tail_risk, line_tightness, rate_cv) ---
    l20_edge = np.zeros(n)
    l10_has = np.zeros(n)
    l40_hr = np.full(n, -1.0)
    margin_arr = np.zeros(n)
    line_dist = np.zeros(n)
    tail_risk = np.zeros(n)
    line_tightness_arr = np.zeros(n)
    rate_cv_arr = np.zeros(n)

    for i in range(n):
        pl = player_col[i]
        su = stat_u.iloc[i]
        ln = float(line[i])
        dr = dir_u.iloc[i]
        gd = str(scored.iloc[i].get("game_date", ""))[:10]
        actuals = _get_recent(player_history, pl, su, gd, n=50)

        if not actuals:
            continue

        # l20_edge
        a20 = actuals[-20:]
        if len(a20) >= 5:
            if dr == "OVER":
                h = sum(1 for v in a20 if v >= ln - 1e-9)
            else:
                h = sum(1 for v in a20 if v <= ln + 1e-9)
            l20_edge[i] = h / len(a20) - 0.5

            mu = np.mean(a20)
            std20 = np.std(a20)
            if mu > 0.1:
                rate_cv_arr[i] = np.clip(std20 / mu, 0, 2.0)
            if ln > 0.5:
                line_dist[i] = np.clip((mu - ln) / ln, -0.5, 0.5)
            if std20 > 0.1 and ln > 0.5:
                tail_risk[i] = np.clip((ln - mu) / std20, -3, 3)
            tight = sum(1 for v in a20 if abs(v - ln) <= 1.5)
            line_tightness_arr[i] = tight / len(a20)

        # l10_has
        a10 = actuals[-10:]
        if len(a10) >= 5:
            l10_has[i] = 1.0
            margins = np.array(a10) - ln
            if dr == "UNDER":
                margins = -margins
            margin_arr[i] = np.clip(np.mean(margins) / max(ln, 1.0), -0.5, 0.5)

        # l40_hr
        a40 = actuals[-40:]
        if len(a40) >= 5:
            if dr == "OVER":
                h = sum(1 for v in a40 if v >= ln - 1e-9)
            else:
                h = sum(1 for v in a40 if v <= ln + 1e-9)
            l40_hr[i] = h / len(a40)

    # --- Categorical features ---
    stat_cat: np.ndarray = np.asarray(stat_u.map(STAT_CATS).fillna(11), dtype=np.int32)
    tier_col = scored["tier"].astype(str).str.upper() if "tier" in scored.columns else pd.Series(["STANDARD"] * n)
    tier_cat: np.ndarray = np.asarray(tier_col.map(TIER_CATS).fillna(0), dtype=np.int32)

    # --- Derived ---
    um_f: np.ndarray = um.astype(np.float64)
    margin_x_under: np.ndarray = margin_arr * um_f
    q_blowout: np.ndarray = _col("q_blowout", 0.0)
    abs_logit_p: np.ndarray = np.abs(logit_p)
    q_x_under: np.ndarray = q_blowout * um_f

    # --- Sportsbook features (v13: sb_over_prob, sb_line_diff) ---
    # Only available at training time from OddsAPI historical props.
    # At runtime they are NaN -> 0.0; LightGBM handles the zero-fill gracefully.
    sb_over_prob: np.ndarray = np.full(n, np.nan)
    sb_line_diff: np.ndarray = np.full(n, np.nan)

    # --- v16 discovery features ---
    opp_defense_rel: np.ndarray = np.clip(_col("form_opp_defense_rel", 0.0), -0.2, 0.2)
    z_line_abs: np.ndarray = np.abs(z_line)
    fragility_feat: np.ndarray = np.clip(_col("fragility", 0.0), 0.0, 0.3)
    bp_has_x_under: np.ndarray = bp_has * um_f

    # --- v17: form_z_line as its own feature (also used as z_line source above) ---
    form_z_line_feat: np.ndarray = np.clip(_col("form_z_line", 0.0), -5.0, 5.0)

    # --- Assemble feature matrix (35 features in v13 order) ---
    X = np.column_stack([
        z_line,             # 0
        min_cv,             # 1
        is_combo,           # 2
        bp_score_gated,     # 3
        bp_has,             # 4
        is_assists,         # 5
        is_threes,          # 6
        games_norm,         # 7
        thin_flag,          # 8
        line_norm,          # 9
        is_home_feat,       # 10
        min_sensitivity,    # 11
        game_total_norm,    # 12
        is_b2b,             # 13
        l20_edge,           # 14
        l10_has,            # 15
        margin_arr,         # 16
        stat_cat,           # 17
        tier_cat,           # 18
        l40_hr,             # 19
        logit_p_x_demon,    # 20
        player_te,          # 21
        player_stat_te,     # 22
        player_dir_te,      # 23
        player_n_norm,      # 24
        line_dist,          # 25
        tail_risk,          # 26
        line_tightness_arr, # 27
        margin_x_under,     # 28
        q_blowout,          # 29
        rate_cv_arr,        # 30
        abs_logit_p,        # 31
        q_x_under,          # 32
        sb_over_prob,       # 33
        sb_line_diff,       # 34
        # v16 discovery features
        opp_defense_rel,    # 35
        z_line_abs,         # 36
        fragility_feat,     # 37
        bp_has_x_under,     # 38
        form_z_line_feat,   # 39
    ])

    return np.nan_to_num(X, nan=0.0), um


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def predict_ensemble(
    scored: pd.DataFrame,
    logs: pd.DataFrame,
    ensemble_dir: Path,
) -> np.ndarray:
    """Run the GBM ensemble on scored legs and return calibrated probabilities.

    Returns array of shape (n_legs,) with calibrated probabilities.
    """
    ens = _load_ensemble(ensemble_dir)
    X_full, um = compute_features(scored, logs)
    n = len(scored)
    temperature = ens["temperature"]

    # Slice X to only the features the model was trained on.
    # compute_features() always builds the full superset (_ALL_FEATURE_NAMES);
    # the meta's feature list is a subset in the same relative order.
    meta_feats = ens["features"]
    if len(meta_feats) != X_full.shape[1]:
        idx = [_ALL_FEATURE_NAMES.index(f) for f in meta_feats]
        X = X_full[:, idx]
    else:
        X = X_full

    preds = np.zeros(n, dtype=float)
    n_seeds = len(ens["seeds"])

    for j in range(n_seeds):
        over_preds = ens["models_over"][j].predict(X[~um])
        under_preds = ens["models_under"][j].predict(X[um])
        preds[~um] += over_preds
        preds[um] += under_preds

    preds /= n_seeds

    # Apply temperature scaling
    if temperature != 1.0:
        preds = np.clip(preds, 1e-6, 1 - 1e-6)
        logits = np.log(preds / (1 - preds))
        preds = 1.0 / (1.0 + np.exp(-logits / temperature))

    return np.clip(preds, P_LO, P_HI)


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def apply_gbm_ensemble(
    scored: pd.DataFrame,
    logs: pd.DataFrame,
    cfg: dict[str, Any],
    repo_root: Path,
) -> pd.DataFrame:
    """Apply GBM ensemble calibration to scored DataFrame.

    Reads config from cfg["posthoc_calibrator"]. If enabled, computes features,
    runs ensemble prediction, and writes p_gbm column. Optionally replaces p_cal.

    Config keys:
        posthoc_calibrator:
            enabled: true/false
            ensemble_dir: relative path to ensemble directory
            mode: "replace" (default) or "blend"
            blend_alpha: float 0-1 (weight on GBM when mode=blend)
    """
    def _col_safe(df: pd.DataFrame, name: str, default: float = 0.5) -> np.ndarray:
        if name in df.columns:
            return np.asarray(pd.to_numeric(df[name], errors="coerce").fillna(default), dtype=np.float64)
        return np.full(len(df), default, dtype=np.float64)

    pc_cfg = cfg.get("posthoc_calibrator", {}) or {}
    if not pc_cfg.get("enabled", False):
        return scored

    ensemble_dir_str = pc_cfg.get("ensemble_dir", "data/model/ensemble")
    ensemble_dir = Path(ensemble_dir_str)
    if not ensemble_dir.is_absolute():
        ensemble_dir = repo_root / ensemble_dir

    if not (ensemble_dir / "ensemble_meta.json").exists():
        print("[GBM_ENSEMBLE] WARNING: ensemble_meta.json not found, skipping GBM calibration")
        return scored

    try:
        p_gbm = predict_ensemble(scored, logs, ensemble_dir)
        scored["p_gbm"] = p_gbm

        mode = str(pc_cfg.get("mode", "replace")).strip().lower()
        if mode == "blend":
            alpha = float(pc_cfg.get("blend_alpha", 0.5))
            p_cal_arr = _col_safe(scored, "p_cal", 0.5)
            scored["p_cal"] = np.clip(alpha * p_gbm + (1 - alpha) * p_cal_arr, P_LO, P_HI)
        else:
            # Replace mode: GBM output becomes p_cal
            scored["p_cal"] = p_gbm

        print(f"[GBM_ENSEMBLE] Applied {mode} mode, mean p_gbm={p_gbm.mean():.4f}, mean p_cal={scored['p_cal'].mean():.4f}")

    except Exception as e:
        print(f"[GBM_ENSEMBLE] ERROR: {e!r} — falling back to existing p_cal")

    return scored

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Any
from typing import cast

import numpy as np
import pandas as pd

from Atlas.core.share_name_key import share_name_key


# ============================================================
# Normalization / small helpers
# ============================================================

import re
import unicodedata

_TEAM_NAME_TO_ABBR: Dict[str, str] = {
    # IAEL-style concatenated names -> 3-letter abbreviations
    "ATLANTAHAWKS": "ATL",
    "BOSTONCELTICS": "BOS",
    "BROOKLYNNETS": "BKN",
    "CHARLOTTEHORNETS": "CHA",
    "CHICAGOBULLS": "CHI",
    "CLEVELANDCAVALIERS": "CLE",
    "DALLASMAVERICKS": "DAL",
    "DENVERNUGGETS": "DEN",
    "DETROITPISTONS": "DET",
    "GOLDENSTATEWARRIORS": "GSW",
    "HOUSTONROCKETS": "HOU",
    "INDIANAPACERS": "IND",
    "LACLIPPERS": "LAC",
    "LALAKERS": "LAL",
    "MEMPHISGRIZZLIES": "MEM",
    "MIAMIHEAT": "MIA",
    "MILWAUKEEBUCKS": "MIL",
    "MINNESOTATIMBERWOLVES": "MIN",
    "NEWORLEANSPELICANS": "NOP",
    "NEWYORKKNICKS": "NYK",
    "OKLAHOMACITYTHUNDER": "OKC",
    "ORLANDOMAGIC": "ORL",
    "PHILADELPHIA76ERS": "PHI",
    "PHOENIXSUNS": "PHX",
    "PORTLANDTRAILBLAZERS": "POR",
    "SACRAMENTOKINGS": "SAC",
    "SANANTONIOSPURRS": "SAS",
    "TORONTORAPTORS": "TOR",
    "UTAHJAZZ": "UTA",
    "WASHINGTONWIZARDS": "WAS",
}

# prefer longer suffixes first (III before II)
_SUFFIX_RE = re.compile(r"^([a-z]+)(iii|ii|iv|v|jr|sr)$", re.I)
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _norm_team(x: str) -> str:
    """Return 3-letter team abbreviation when possible."""
    raw = str(x or "").strip()
    if not raw:
        return ""
    u = raw.upper().strip()
    # already abbr
    if len(u) == 3 and u.isalpha():
        return u
    key = re.sub(r"[^A-Z]", "", u)
    # IAEL often provides concatenated names like AtlantaHawks
    abbr = _TEAM_NAME_TO_ABBR.get(key)
    return abbr or u


def _player_key(x: str) -> str:
    """Canonical player key used for joins across IAEL / gamelogs / share_matrix."""
    return share_name_key(x)


def _norm_player(x: str) -> str:
    """Legacy wrapper; keep behavior stable but prefer _player_key for joins."""
    return str(x or "").strip()

def _safe_float(x, default: float = np.nan) -> float:
    """
    Robust float coercion:
      - treats None and empty strings as default
      - treats non-finite values as default
    """
    try:
        if x is None:
            return float(default)
        if isinstance(x, (str, bytes)):
            s = str(x).strip()
            if s == "":
                return float(default)
        v = float(x)
        if not np.isfinite(v):
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _safe_int(x, default: int = 0) -> int:
    """
    Robust int coercion:
      - accepts numeric strings and floats (e.g. "3.0" -> 3)
      - treats None/empty/non-coercible as default
    """
    try:
        if x is None:
            return int(default)
        if isinstance(x, (str, bytes)):
            s = str(x).strip()
            if s == "":
                return int(default)
        # use float->int to handle "3.0" etc.
        v = int(float(x))
        return int(v)
    except Exception:
        try:
            return int(default)
        except Exception:
            return 0


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """
    Safe division returning `default` if denominator is zero/NaN/invalid.
    """
    try:
        af = float(a)
    except Exception:
        return float(default)
    try:
        bf = float(b)
    except Exception:
        return float(default)
    if not np.isfinite(bf) or bf == 0.0:
        return float(default)
    return float(af) / bf

def _to_u_str_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def _to_str_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip()


def _normalize_weight_map(w: Dict[str, float], keys: Optional[List[str]] = None) -> Dict[str, float]:
    """
    Normalize weights to sum to 1 across provided keys (or across dict keys).
    Returns 0s if sum <= 0.
    """
    if w is None:
        return {}

    if keys is None:
        keys = list(w.keys())

    s = 0.0
    out: Dict[str, float] = {}
    for k in keys:
        v = float(w.get(k, 0.0))
        if np.isfinite(v) and v > 0:
            out[k] = v
            s += v
        else:
            out[k] = 0.0

    if s <= 0:
        return {k: 0.0 for k in keys}

    inv = 1.0 / s
    return {k: float(out[k] * inv) for k in keys}


def _apply_power_transform(scores: Dict[str, float], power: float) -> Dict[str, float]:
    """
    Sharpen a distribution while preserving rank:
      score' = score ** power

    power:
      - 1.0 -> no-op
      - >1.0 -> more concentrated (solves mid-tail leakage)
      - <1.0 -> flatter
    """
    try:
        p = float(power)
    except Exception:
        return scores

    if not np.isfinite(p) or p <= 0:
        return scores
    if abs(p - 1.0) < 1e-9:
        return scores

    out: Dict[str, float] = {}
    for k, v in (scores or {}).items():
        vv = float(v)
        if not np.isfinite(vv) or vv <= 0:
            out[k] = 0.0
        else:
            out[k] = float(vv ** p)
    return out


def _soft_cap_multiplier(mult: float, cap: float, softness: float = 0.35) -> float:
    """
    Soft-cap a multiplier above `cap`.

    - If mult <= cap: unchanged
    - If mult > cap: cap + softness*(mult-cap)

    softness:
      0.0 -> hard cap
      0.35 -> recommended (damps extremes, smooth)
      1.0 -> no cap
    """
    try:
        m = float(mult)
        c = float(cap)
        s = float(softness)
    except Exception:
        return mult

    if not np.isfinite(m) or not np.isfinite(c) or c <= 0:
        return mult
    if m <= c:
        return m

    s = float(np.clip(s, 0.0, 1.0))
    return float(c + s * (m - c))


# ============================================================
# Usage-weight utilities (Phase 2/3)
# ============================================================

def _recent_player_window(gamelogs: pd.DataFrame, player: str, lookback: int) -> pd.DataFrame:
    """
    Return last N rows for player from provided gamelogs (already team-scoped by caller).
    Uses game_date ordering if present.
    """
    if gamelogs is None or gamelogs.empty:
        return gamelogs.iloc[0:0].copy()

    p = _norm_player(player)
    g = gamelogs[gamelogs["player"].astype(str).str.strip() == p]
    if g.empty:
        return g.copy()

    if "game_date" in g.columns:
        gd = pd.to_datetime(g["game_date"], errors="coerce")
        g = g.assign(_gd=gd).sort_values("_gd", ascending=False).drop(columns=["_gd"])
    return g.head(int(lookback)).copy()


def _usage_score_for_stat(g: pd.DataFrame, stat_u: str) -> float:
    """
    Returns an 'ability to absorb' score for a player for a given stat.

    Primary signal:
      - PTS uses usg_proxy * avg_minutes when available

    Fallbacks:
      - If usg_proxy missing: uses mean of (pts/ast/reb) for corresponding stat if present.
      - Else: 0
    """
    if g is None or g.empty:
        return 0.0

    stat_u = (stat_u or "").upper().strip()

    # minutes column naming
    min_col = "minutes" if "minutes" in g.columns else ("min" if "min" in g.columns else None)
    mins = pd.to_numeric(g[min_col], errors="coerce").to_numpy(dtype=float) if min_col else None
    mins = np.clip(mins, 0.0, None) if mins is not None else None
    avg_mins = float(np.nanmean(mins)) if mins is not None and np.isfinite(mins).any() else 0.0

    # usage proxy (if present)
    if "usg_proxy" in g.columns:
        usg = pd.to_numeric(g["usg_proxy"], errors="coerce").to_numpy(dtype=float)
        usg = np.clip(usg, 0.0, None)
        avg_usg = float(np.nanmean(usg)) if np.isfinite(usg).any() else 0.0
    else:
        avg_usg = 0.0

    if stat_u == "PTS":
        if avg_usg > 0 and avg_mins > 0:
            return avg_usg * avg_mins
        if "pts" in g.columns:
            pts = pd.to_numeric(g["pts"], errors="coerce").to_numpy(dtype=float)
            pts = np.clip(pts, 0.0, None)
            return float(np.nanmean(pts)) if np.isfinite(pts).any() else 0.0
        return 0.0

    if stat_u == "AST":
        if "ast" in g.columns:
            ast = pd.to_numeric(g["ast"], errors="coerce").to_numpy(dtype=float)
            ast = np.clip(ast, 0.0, None)
            return float(np.nanmean(ast)) if np.isfinite(ast).any() else 0.0
        return avg_usg * avg_mins

    if stat_u == "REB":
        if "reb" in g.columns:
            reb = pd.to_numeric(g["reb"], errors="coerce").to_numpy(dtype=float)
            reb = np.clip(reb, 0.0, None)
            return float(np.nanmean(reb)) if np.isfinite(reb).any() else 0.0
        return avg_mins

    return avg_usg * avg_mins


def build_usage_weights(
    *,
    gamelogs: pd.DataFrame,
    candidates: List[str],
    stat: str,
    lookback: int,
    usage_power: float = 1.6,
) -> Dict[str, float]:
    """
    Phase 2 (simple): Build player->weight over candidates using recent usage/stat volume.
    Assumes gamelogs already team-scoped by caller responsibility.

    NEW:
      - usage_power applies a power transform to sharpen the distribution:
            score' = score ** usage_power
        This fixes mid-tail leakage when many rotation guys have similar raw scores.
    """
    scores: Dict[str, float] = {}
    for p in candidates:
        w = _recent_player_window(gamelogs, p, lookback=lookback)
        s = _usage_score_for_stat(w, stat_u=stat)
        scores[_norm_player(p)] = max(0.0, float(s))

    # NEW: sharpen before normalize
    scores = _apply_power_transform(scores, usage_power)

    total = float(sum(scores.values()))
    if total <= 0:
        n = max(1, len(candidates))
        return {(_norm_player(p)): 1.0 / n for p in candidates}

    return {p: (scores[p] / total) for p in scores}


# ---------------------------
# Phase 3: Trade-aware weights
# ---------------------------

def _prev_team_for_player(gl_all: pd.DataFrame, player_s: str, current_team_u: str) -> Optional[str]:
    """
    Previous team = most recent team (by game_date) different from current_team_u.
    Returns None if not found.
    """
    if gl_all is None or gl_all.empty:
        return None

    # gl_all expected normalized: team uppercase, player stripped, game_date normalized
    g = gl_all.loc[gl_all["player"] == player_s]
    if g.empty:
        return None

    if "game_date" in g.columns:
        g2 = g.sort_values("game_date", ascending=False)
        other = g2.loc[g2["team"] != current_team_u]
        if other.empty:
            return None
        return str(other["team"].iloc[0])

    counts = g["team"].value_counts().to_dict()
    counts.pop(current_team_u, None)
    if not counts:
        return None
    # use a lambda to avoid overload/type issues with counts.get
    if not counts:
        return None
    return cast(str, max(counts.keys(), key=lambda k: counts.get(k, 0)))


def _team_player_rows(gl: pd.DataFrame, team_u: str, player_s: str) -> pd.DataFrame:
    g = gl.loc[(gl["team"] == team_u) & (gl["player"] == player_s)]
    if g.empty:
        return g.copy()
    if "game_date" in g.columns:
        return g.sort_values("game_date", ascending=True).copy()
    return g.copy()


def build_trade_aware_usage_weights(
    *,
    gamelogs_all: pd.DataFrame,
    team_active: pd.DataFrame,
    candidates: List[str],
    team_u: str,
    stat: str,
    cfg: "ReallocConfig",
) -> Tuple[Dict[str, float], Dict[str, Dict[str, float]]]:
    """
    Trade-aware, season-heavy usage weights.

    Default per player:
      score = season_weight * score_season(current_team) + recent_weight * score_recent(current_team)

    Ramp case (new to team; games_on_current_team < min_games_new_team and has previous team):
      - season baseline uses PREVIOUS TEAM rows (body of work)
      - recent uses CURRENT TEAM recent rows
      - recent weight ramps upward as games accrue on new team:
            r = min(1, g_cur / min_games_new_team)
            w_recent = base_recent + ramp_extra_recent * r
            w_season = 1 - w_recent

    NEW:
      - usage_power in cfg applies power transform to sharpen distribution and reduce mid-tail leakage.
    """
    if team_active is None or team_active.empty or not candidates:
        n = max(1, len(candidates))
        return {(_norm_player(p)): 1.0 / n for p in candidates}, {}

    stat_u = (stat or "").upper().strip()

    base_w_season = float(getattr(cfg, "season_weight", 0.70) or 0.70)
    base_w_recent = float(getattr(cfg, "recent_weight", 0.30) or 0.30)
    recent_n = int(getattr(cfg, "recent_games", 10) or 10)
    min_new = int(getattr(cfg, "min_games_new_team", 10) or 10)
    ramp_extra = float(getattr(cfg, "ramp_extra_recent", 0.50) or 0.50)

    # NEW: usage sharpening
    usage_power = float(getattr(cfg, "usage_power", 1.6) or 1.6)

    # normalize season/recent weights
    s = max(0.0, base_w_season)
    r = max(0.0, base_w_recent)
    if s + r <= 0:
        s, r = 0.7, 0.3
    else:
        z = s + r
        s, r = s / z, r / z

    # normalize columns/types once
    gl_all = gamelogs_all.copy()
    gl_all["team"] = _to_u_str_series(gl_all["team"])
    gl_all["player"] = _to_str_series(gl_all["player"])
    if "game_date" in gl_all.columns:
        gl_all["game_date"] = pd.to_datetime(gl_all["game_date"], errors="coerce").dt.normalize()

    ta = team_active.copy()
    ta["team"] = _to_u_str_series(ta["team"])
    ta["player"] = _to_str_series(ta["player"])
    if "game_date" in ta.columns:
        ta["game_date"] = pd.to_datetime(ta["game_date"], errors="coerce").dt.normalize()

    scores: Dict[str, float] = {}
    dbg: Dict[str, Dict[str, float]] = {}

    for p in candidates:
        p_s = _norm_player(p)

        cur_rows = _team_player_rows(ta, team_u, p_s)
        g_cur = int(len(cur_rows))

        recent_rows = cur_rows.tail(int(recent_n)).copy() if g_cur > 0 else cur_rows.iloc[0:0].copy()

        score_season = _usage_score_for_stat(cur_rows, stat_u=stat_u)
        score_recent = _usage_score_for_stat(recent_rows, stat_u=stat_u)

        w_season = s
        w_recent = r
        mode = "normal"

        prev_team = None
        if g_cur > 0:
            prev_team = _prev_team_for_player(gl_all, p_s, current_team_u=team_u)

        if prev_team and g_cur < min_new:
            prev_rows = _team_player_rows(gl_all, prev_team, p_s)
            score_prev_season = _usage_score_for_stat(prev_rows, stat_u=stat_u)

            rr = float(min(1.0, g_cur / float(max(1, min_new))))
            w_recent = float(min(1.0, r + ramp_extra * rr))
            w_season = float(max(0.0, 1.0 - w_recent))

            score_season = score_prev_season
            mode = "ramp_prev_team"

        score_blend = float(max(0.0, w_season * score_season + w_recent * score_recent))
        scores[p_s] = score_blend

        dbg[p_s] = {
            "g_cur_team": float(g_cur),
            "w_season_used": float(w_season),
            "w_recent_used": float(w_recent),
            "score_season_used": float(score_season),
            "score_recent_used": float(score_recent),
            "score_blend": float(score_blend),
            "mode": 1.0 if mode == "ramp_prev_team" else 0.0,
        }

    # NEW: sharpen distribution before normalize (solves mid-tail leakage)
    scores_sharp = _apply_power_transform(scores, usage_power)

    total = float(sum(scores_sharp.values()))
    if total <= 0:
        n = max(1, len(candidates))
        return {(_norm_player(p)): 1.0 / n for p in candidates}, dbg

    weights = {p: (scores_sharp[p] / total) for p in scores_sharp}

    if bool(getattr(cfg, "debug_prints", False)):
        try:
            s_raw = float(sum(scores.values()))
            s_shp = float(sum(scores_sharp.values()))
            print(f"[USAGE SHARPEN] stat={stat_u} usage_power={usage_power:.3f} sum_raw={s_raw:.3f} sum_sharp={s_shp:.3f}")
        except Exception:
            pass

    return weights, dbg


# ============================================================
# Teamshare-weight utilities (normalized vector + outs blend)
# ============================================================

def build_teamshare_weights_for_outs(
    *,
    share_matrix: pd.DataFrame,
    team_u: str,
    stat_u: str,
    out_list: List[Tuple[str, float]],
    candidates: List[str],
    min_games_for_pattern: int,
) -> Tuple[Dict[str, float], int]:
    """
    Build a normalized teamshare weight vector over candidates using share_matrix patterns
    for the current out_list.

    IMPORTANT CHANGE:
      - Previously: hard-filtered outs when games_max < min_games_for_pattern.
      - Now: uses a smooth reliability factor rel in [0,1] where
            rel = min(1, games_max/min_games_for_pattern)
        This avoids "all-or-nothing" cliffs and works with Option C alpha scaling.

    Returns:
      (weights_map, outs_used_pattern_total)
    """
    if share_matrix is None or share_matrix.empty or not candidates:
        return {p: 0.0 for p in candidates}, 0

    sm = share_matrix.copy()
    sm["team"] = sm["team"].astype(str).str.upper().str.strip()
    sm["stat"] = sm["stat"].astype(str).str.upper().str.strip()
    sm["out_player"] = sm["out_player"].astype(str).str.strip()
    sm["beneficiary_player"] = sm["beneficiary_player"].astype(str).str.strip()
    sm["out_key"] = sm["out_player"].map(_player_key)
    sm["ben_key"] = sm["beneficiary_player"].map(_player_key)

    # robust: avoid DataFrame.get(...) returning a scalar
    if "games" in sm.columns:
        sm["games"] = pd.to_numeric(sm["games"], errors="coerce").fillna(0.0)
    else:
        sm["games"] = 0.0

    if "weight" in sm.columns:
        sm["weight"] = pd.to_numeric(sm["weight"], errors="coerce").fillna(0.0)
    else:
        sm["weight"] = 0.0

    cand_lut = {_player_key(p): p.strip() for p in candidates}
    scores = {p: 0.0 for p in candidates}

    outs_used = 0
    min_g = float(max(1, int(min_games_for_pattern)))

    for out_p, frac in out_list:
        out_key = _player_key(str(out_p))

        sub = sm[
            (sm["team"] == team_u)
            & (sm["stat"] == stat_u)
            & (sm["out_key"] == out_key)
        ]

        if sub.empty:
            continue

        outs_used += 1

        gmax = float(sub["games"].max() or 0.0)
        rel = float(min(1.0, gmax / min_g)) if np.isfinite(gmax) and gmax > 0 else 0.0

        eff_frac = float(frac) * rel
        if eff_frac <= 0:
            continue

        for _, r in sub.iterrows():
            ben = str(r.get("ben_key", ""))
            if ben in cand_lut:
                p = cand_lut[ben]
                scores[p] += eff_frac * float(r["weight"])

    total = float(sum(scores.values()))
    if total <= 0:
        return {p: 0.0 for p in candidates}, outs_used

    return {p: (scores[p] / total) for p in candidates}, outs_used


# ============================================================
# Teamshare support scaling (Option C)
# ============================================================


def _teamshare_alpha_multiplier(
    *,
    share_matrix: pd.DataFrame,
    team_u: str,
    stat_u: str,
    out_list: List[Tuple[str, float]],
    min_games_for_pattern: int,
) -> Tuple[float, float, float]:
    """
    Compute a scale factor alpha_mult in [0,1] based on sample support for the out patterns.

    support_score = frac-weighted mean of min(1, games_max/min_games_for_pattern)
    across outs that have any rows for (team, stat, out_player).

    Returns:
      (alpha_mult, supported_outs_count, support_score)
    """
    if share_matrix is None or share_matrix.empty or not out_list:
        return 0.0, 0.0, 0.0

    sm = share_matrix
    need_cols = {"team", "stat", "out_player", "games"}
    if not need_cols.issubset(sm.columns):
        return 0.0, 0.0, 0.0

    team_ser = _to_u_str_series(sm["team"])
    stat_ser = _to_u_str_series(sm["stat"])
    out_ser = _to_str_series(sm["out_player"]).map(_player_key)
    games_ser = pd.to_numeric(sm["games"], errors="coerce")

    base_mask = (team_ser == team_u) & (stat_ser == stat_u)
    if not bool(base_mask.any()):
        return 0.0, 0.0, 0.0

    min_games = float(max(1, int(min_games_for_pattern)))

    w_sum = 0.0
    s_sum = 0.0
    supported = 0.0

    for out_p, frac in out_list:
        op = _player_key(str(out_p))
        if not op:
            continue

        m = base_mask & (out_ser == op)
        if not bool(m.any()):
            continue

        gmax = float(np.nanmax(games_ser[m].to_numpy(dtype=float)))
        if not np.isfinite(gmax) or gmax <= 0:
            continue

        supported += 1.0
        rel = float(min(1.0, gmax / min_games))

        f = float(frac)
        w_sum += f
        s_sum += f * rel

    if w_sum <= 0:
        return 0.0, supported, 0.0

    support_score = float(s_sum / w_sum)
    alpha_mult = float(np.clip(support_score, 0.0, 1.0))
    return alpha_mult, supported, support_score


def _teamshare_support_stats(
    *,
    share_matrix: pd.DataFrame,
    team_u: str,
    stat_u: str,
    out_list: List[Tuple[str, float]],
    min_games_for_pattern: int,
    rel_effective_threshold: float,
) -> Dict[str, float]:
    if share_matrix is None or share_matrix.empty or not out_list:
        return {
            "supported_outs": 0.0,
            "effective_outs": 0.0,
            "rel_wmean": 0.0,
            "rel_min": float("nan"),
            "rel_max": float("nan"),
        }

    sm = share_matrix
    need = {"team", "stat", "out_player", "games"}
    if not need.issubset(sm.columns):
        return {
            "supported_outs": 0.0,
            "effective_outs": 0.0,
            "rel_wmean": 0.0,
            "rel_min": float("nan"),
            "rel_max": float("nan"),
        }

    team_ser = sm["team"].astype(str).str.upper().str.strip()
    stat_ser = sm["stat"].astype(str).str.upper().str.strip()
    out_ser = sm["out_player"].astype(str).str.strip().map(_player_key)
    games_ser = pd.to_numeric(sm["games"], errors="coerce")

    base = (team_ser == team_u) & (stat_ser == stat_u)
    if not bool(base.any()):
        return {
            "supported_outs": 0.0,
            "effective_outs": 0.0,
            "rel_wmean": 0.0,
            "rel_min": float("nan"),
            "rel_max": float("nan"),
        }

    min_g = float(max(1, int(min_games_for_pattern)))
    thr = float(np.clip(rel_effective_threshold, 0.0, 1.0))

    supported = 0.0
    effective = 0.0

    rels: List[float] = []
    w_sum = 0.0
    s_sum = 0.0

    for out_p, frac in out_list:
        op = _player_key(str(out_p))
        if not op:
            continue

        m = base & (out_ser == op)
        if not bool(m.any()):
            continue

        gmax = float(np.nanmax(games_ser[m].to_numpy(dtype=float)))
        if not np.isfinite(gmax) or gmax <= 0:
            continue

        rel = float(min(1.0, gmax / min_g))

        supported += 1.0
        rels.append(rel)

        if rel >= thr:
            effective += 1.0

        f = float(frac)
        w_sum += f
        s_sum += f * rel

    rel_wmean = float(s_sum / w_sum) if w_sum > 0 else 0.0
    rel_min = float(np.min(rels)) if rels else float("nan")
    rel_max = float(np.max(rels)) if rels else float("nan")

    return {
        "supported_outs": float(supported),
        "effective_outs": float(effective),
        "rel_wmean": float(rel_wmean),
        "rel_min": float(rel_min),
        "rel_max": float(rel_max),
    }


# ============================================================
# Rotation-likelihood utilities (prevents blowout guys soaking share)
# ============================================================

def _sigmoid(x: float) -> float:
    x = float(np.clip(x, -20.0, 20.0))
    return float(1.0 / (1.0 + np.exp(-x)))


def rotation_likelihood_map(
    *,
    team_active: pd.DataFrame,
    candidates: List[str],
    minutes_col: str,
    last_n_games: int,
    a0: float,
    sa: float,
    m0: float,
    sm: float,
    floor: float,
) -> Dict[str, float]:
    """
    Compute per-player rotation likelihood r_i in [floor,1].

    Inputs computed over last_n_games team dates:
      - appearances a_i = count of games with minutes > 0
      - avg minutes m_i = mean minutes across those games

    f_a = sigmoid((a_i - a0)/sa)
    f_m = sigmoid((m_i - m0)/sm)

    Combine with OR-like union:
      r = 1 - (1-f_a)(1-f_m)
    """
    if team_active is None or team_active.empty or not candidates:
        return {p: 1.0 for p in candidates}

    if "game_date" not in team_active.columns:
        return {p: 1.0 for p in candidates}

    last_n_games = int(max(1, last_n_games))
    floor = float(np.clip(floor, 0.0, 1.0))

    dates = (
        team_active[["game_date"]]
        .dropna()
        .drop_duplicates()
        .sort_values("game_date", ascending=False)
        .head(last_n_games)["game_date"]
        .tolist()
    )

    recent = team_active.loc[team_active["game_date"].isin(dates)].copy()
    if recent.empty:
        return {p: 1.0 for p in candidates}

    # normalize last_n_games without calling built-in max with mixed/unknown types
    try:
        last_n_games_i = int(last_n_games) if last_n_games is not None else 1
    except Exception:
        last_n_games_i = 1
    if last_n_games_i < 1:
        last_n_games_i = 1
    last_n_games = last_n_games_i

    floor = float(np.clip(float(floor or 0.0), 0.0, 1.0))

    dates = (
        team_active[["game_date"]]
        .dropna()
        .drop_duplicates()
        .sort_values("game_date", ascending=False)
        .head(last_n_games)["game_date"]
        .tolist()
    )

    recent = team_active.loc[team_active["game_date"].isin(dates)].copy()
    if recent.empty:
        return {p: 1.0 for p in candidates}

    # ensure we always pass a Series (not None) into pd.to_numeric
    if minutes_col in recent.columns:
        mins_raw = recent[minutes_col]
    else:
        mins_raw = pd.Series(np.nan, index=recent.index)
    mins = pd.to_numeric(mins_raw, errors="coerce").fillna(0.0)
    recent = recent.assign(_mins=mins)

    appeared = recent.groupby("player")["_mins"].apply(lambda s: int((s > 0).sum())).to_dict()
    avgmins = recent.groupby("player")["_mins"].mean().to_dict()

    appeared = recent.groupby("player")["_mins"].apply(lambda s: int((s > 0).sum())).to_dict()
    avgmins = recent.groupby("player")["_mins"].mean().to_dict()

    sa = float(max(1e-6, sa))
    sm = float(max(1e-6, sm))

    out: Dict[str, float] = {}
    for p in candidates:
        a = float(appeared.get(p, 0))
        m = float(avgmins.get(p, 0.0))

        fa = _sigmoid((a - float(a0)) / sa)
        fm = _sigmoid((m - float(m0)) / sm)

        r = 1.0 - (1.0 - fa) * (1.0 - fm)
        out[p] = float(max(floor, min(1.0, r)))

    return out


# ============================================================
# Replaceability-adjusted capture utilities
# ============================================================

def _adjust_capture_for_depth(
    *,
    base_cap: float,
    weight_map: Dict[str, float],
    cfg: "ReallocConfig",
) -> Tuple[float, float, float, float, float]:
    """
    Adjust capture rate based on:
      (A) Depth: effective number of engines (N_eff) computed from FINAL normalized weights (top-k)
      (B) Concentration: if redistribution becomes top-heavy (few guys absorb most share), reduce capture

    Returns:
      (cap_adj, n_eff, top_mass_n, conc_penalty, cap_adj_pre_clamp)

    Notes:
      - Uses Herfindahl: H = sum(w^2), N_eff = 1/H
      - Smooth adjustment around cfg.depth_ref_engines using log()
      - Optional concentration penalty uses top-N mass of the top-k normalized weights
      - Clamped to [depth_cap_min, depth_cap_max]
    """
    if not bool(getattr(cfg, "depth_capture_enabled", True)):
        return float(base_cap), float(np.nan), float("nan"), 0.0, float(base_cap)

    if not weight_map:
        return float(base_cap), float(np.nan), float("nan"), 0.0, float(base_cap)

    w = np.array(list(weight_map.values()), dtype=float)
    w = w[np.isfinite(w) & (w > 0)]
    if w.size == 0:
        return float(base_cap), float(np.nan), float("nan"), 0.0, float(base_cap)

    k = int(getattr(cfg, "depth_top_k", 8) or 8)
    k = max(1, min(k, int(w.size)))

    w = np.sort(w)[::-1][:k]
    s = float(w.sum())
    if s <= 0:
        return float(base_cap), float(np.nan), float("nan"), 0.0, float(base_cap)

    # top-k normalized weights
    w = w / s

    H = float(np.sum(w ** 2))
    if not np.isfinite(H) or H <= 0:
        return float(base_cap), float(np.nan), float("nan"), 0.0, float(base_cap)

    n_eff = float(1.0 / H)

    depth_ref = float(getattr(cfg, "depth_ref_engines", 3.0) or 3.0)
    depth_ref = max(1e-6, depth_ref)

    slope = float(getattr(cfg, "depth_slope", 0.04) or 0.04)

    adj_factor = 1.0 + slope * (float(np.log(n_eff)) - float(np.log(depth_ref)))
    cap_adj = float(base_cap) * float(adj_factor)

    # -----------------------------
    # NEW: Concentration penalty
    # If top-N mass is high, assume extra efficiency loss => lower capture.
    # -----------------------------
    top_mass_n = float("nan")
    conc_penalty = 0.0
    if bool(getattr(cfg, "depth_conc_enabled", True)):
        top_n = int(getattr(cfg, "depth_conc_top_n", 3) or 3)
        top_n = max(1, min(top_n, int(w.size)))

        top_mass_n = float(np.sum(w[:top_n]))

        floor = float(getattr(cfg, "depth_conc_floor", 0.45) or 0.45)
        span = float(getattr(cfg, "depth_conc_span", 0.25) or 0.25)
        span = max(1e-6, span)

        # pen01: 0 when <= floor, ramps to 1 by (floor+span)
        pen01 = float(np.clip((top_mass_n - floor) / span, 0.0, 1.0))

        max_pen = float(getattr(cfg, "depth_conc_max_penalty", 0.06) or 0.06)
        max_pen = float(np.clip(max_pen, 0.0, 0.50))

        conc_penalty = float(max_pen * pen01)
        cap_adj = float(cap_adj) * float(1.0 - conc_penalty)

    cap_adj_pre_clamp = float(cap_adj)

    cap_min = float(getattr(cfg, "depth_cap_min", 0.75) or 0.75)
    cap_max = float(getattr(cfg, "depth_cap_max", 0.95) or 0.95)

    cap_adj = float(max(cap_min, min(cap_max, cap_adj)))
    return cap_adj, n_eff, float(top_mass_n), float(conc_penalty), cap_adj_pre_clamp


# ============================================================
# Core stats supported by reallocation layer
# ============================================================

STAT_FAMILIES = ("PTS", "REB", "AST")


# ============================================================
# Config
# ============================================================

@dataclass(frozen=True)
class ReallocConfig:
    # How much of removed budget to redistribute (per stat)
    capture_rate: Optional[Dict[str, float]] = None

    # Share-matrix builder hyperparams
    dirichlet_alpha: float = 8.0
    min_games_for_pattern: int = 8
    min_minutes_clip: float = 8.0

    # IAEL semantics
    questionable_out_fraction: float = 0.5

    # Safety cap
    max_multiplier: float = 2.2

    # Choose weighting source
    weight_mode: str = "blend"   # "teamshare" | "usage" | "blend"
    blend_alpha: float = 0.2
    usage_lookback_games: int = 20  # legacy

    # Usage sharpening exponent (fixes mid-tail leakage)
    #  - 1.0 = no-op (flat)
    #  - 1.3–1.7 = concentrates mass toward top absorbers
    usage_power: float = 1.6

    # Phase 3: season-heavy + trade-aware ramp
    season_weight: float = 0.70
    recent_weight: float = 0.30
    recent_games: int = 10
    min_games_new_team: int = 10
    ramp_extra_recent: float = 0.50

    # Replaceability-adjusted capture (depth)
    depth_capture_enabled: bool = True
    depth_ref_engines: float = 3.0
    depth_slope: float = 0.04
    depth_cap_min: float = 0.75
    depth_cap_max: float = 0.95
    depth_top_k: int = 8

    # concentration penalty (adds separation for heliocentric/top-heavy offenses)
    depth_conc_enabled: bool = True
    depth_conc_top_n: int = 3
    depth_conc_floor: float = 0.45
    depth_conc_span: float = 0.25
    depth_conc_max_penalty: float = 0.06

    # Rotation-likelihood reweight
    rotation_reweight_enabled: bool = True
    rotation_last_n_games: int = 10
    rotation_a0: float = 3.0
    rotation_sa: float = 1.0
    rotation_m0: float = 10.0
    rotation_sm: float = 3.0
    rotation_floor: float = 0.05

    # Teamshare support debug/polish
    teamshare_rel_effective_threshold: float = 0.25
    teamshare_support_budget_floor: float = 0.75

    # --------------------------------------------------------
    # NEW: Role expansion guardrails (soft caps on multipliers)
    # This targets common "2 main guys sit" nights.
    # --------------------------------------------------------
    role_guardrails_enabled: bool = True
    role_guardrails_min_outs: int = 2

    # Apply if removed_budget for the stat exceeds threshold OR outs >= min_outs
    role_guardrails_removed_threshold: Optional[Dict[str, float]] = None

    # Caps by stat on the FINAL multiplier (after max_multiplier clamp still applies)
    role_guardrails_cap_mult: Optional[Dict[str, float]] = None

    # Softness for caps (0 hard cap, 1 none)
    role_guardrails_softness: float = 0.15

    # Debug printing (sandbox only)
    debug_prints: bool = False


def default_config() -> ReallocConfig:
    return ReallocConfig(
        capture_rate={"PTS": 0.90, "REB": 0.95, "AST": 0.85},

        dirichlet_alpha=8.0,
        min_games_for_pattern=8,
        min_minutes_clip=8.0,

        questionable_out_fraction=0.5,
        max_multiplier=2.2,

        weight_mode="blend",
        blend_alpha=0.2,
        usage_lookback_games=20,

        usage_power=1.6,

        season_weight=0.70,
        recent_weight=0.30,
        recent_games=10,
        min_games_new_team=3,
        ramp_extra_recent=0.50,

        depth_capture_enabled=True,
        depth_ref_engines=3.0,
        depth_slope=0.04,
        depth_cap_min=0.75,
        depth_cap_max=0.95,
        depth_top_k=8,

        depth_conc_enabled=True,
        depth_conc_top_n=3,
        depth_conc_floor=0.45,
        depth_conc_span=0.25,
        depth_conc_max_penalty=0.06,

        rotation_reweight_enabled=True,
        rotation_last_n_games=10,
        rotation_a0=3.0,
        rotation_sa=1.0,
        rotation_m0=10.0,
        rotation_sm=3.0,
        rotation_floor=0.05,

        teamshare_rel_effective_threshold=0.25,
        teamshare_support_budget_floor=0.75,

        # NEW guardrails defaults (tuned to your CHA double-out findings)
        role_guardrails_enabled=True,
        role_guardrails_min_outs=2,
        role_guardrails_removed_threshold={"PTS": 30.0, "AST": 7.0, "REB": 10.0},
        role_guardrails_cap_mult={"PTS": 1.35, "AST": 1.25, "REB": 1.20},
        role_guardrails_softness=0.15,

        debug_prints=False,
    )


# ============================================================
# Share-matrix builder
# ============================================================

def build_removed_share_matrix(
    gamelogs: pd.DataFrame,
    *,
    team_col: str = "team",
    player_col: str = "player",
    date_col: str = "game_date",
    minutes_col: str = "minutes",
    pts_col: str = "pts",
    reb_col: str = "reb",
    ast_col: str = "ast",
    # NEW: reflect current rosters/roles
    recent_days: int = 140,
    min_rotation_games: int = 6,
    min_rotation_avg_min: float = 8.0,
) -> pd.DataFrame:
    """
    FAST share-matrix builder.

    Learns: when player X is absent, which teammates gain share of PTS/REB/AST?

    Output columns:
      team, out_player, beneficiary_player, stat, weight, games
    """
    df = gamelogs.copy()

    needed = {team_col, player_col, date_col, minutes_col, pts_col, reb_col, ast_col}
    missing = [c for c in needed if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=[team_col, "out_player", "beneficiary_player", "stat", "weight", "games"])

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df.dropna(subset=[date_col]).copy()

    df[team_col] = _to_u_str_series(df[team_col])
    df[player_col] = _to_str_series(df[player_col])

    for c in (minutes_col, pts_col, reb_col, ast_col):
        # required columns were validated earlier; use direct access so to_numeric receives a Series, not Optional
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Focus on recent window (current roster reality)
    if int(recent_days) > 0 and not df.empty:
        cut = df[date_col].max()
        if pd.notna(cut):
            df = df[df[date_col] >= (cut - pd.Timedelta(days=int(recent_days)))].copy()

    if df.empty:
        return pd.DataFrame(columns=[team_col, "out_player", "beneficiary_player", "stat", "weight", "games"])

    df["active"] = df[minutes_col] > 0

    # Team totals per game
    team_date = df.groupby([team_col, date_col], as_index=False).agg(
        team_pts=(pts_col, "sum"),
        team_reb=(reb_col, "sum"),
        team_ast=(ast_col, "sum"),
        team_min=(minutes_col, "sum"),
    )
    df = df.merge(team_date, on=[team_col, date_col], how="left")

    df["pts_share"] = df[pts_col] / df["team_pts"].replace({0.0: np.nan})
    df["reb_share"] = df[reb_col] / df["team_reb"].replace({0.0: np.nan})
    df["ast_share"] = df[ast_col] / df["team_ast"].replace({0.0: np.nan})
    df["min_share"] = df[minutes_col] / df["team_min"].replace({0.0: np.nan})
    df[["pts_share", "reb_share", "ast_share", "min_share"]] = df[
        ["pts_share", "reb_share", "ast_share", "min_share"]
    ].fillna(0.0)

    # Baseline shares for active players
    base = df[df["active"]].groupby([team_col, player_col], as_index=False).agg(
        base_pts_share=("pts_share", "mean"),
        base_reb_share=("reb_share", "mean"),
        base_ast_share=("ast_share", "mean"),
        base_min_share=("min_share", "mean"),
        games=("active", "sum"),
        avg_min=(minutes_col, "mean"),
    )

    if base.empty:
        return pd.DataFrame(columns=[team_col, "out_player", "beneficiary_player", "stat", "weight", "games"])

    # NEW: define “rotation set” using role thresholds (reduces phantom outs)
    base_rot = base[
        (base["games"] >= int(min_rotation_games)) &
        (base["avg_min"] >= float(min_rotation_avg_min))
    ].copy()

    rotation_players = base_rot.groupby(team_col)[player_col].apply(set).to_dict()

    # Active players per team/date
    active_players = (
        df[df["active"]]
        .groupby([team_col, date_col])[player_col]
        .apply(list)
        .reset_index(name="active_players")
    )

    if active_players.empty:
        return pd.DataFrame(columns=[team_col, "out_player", "beneficiary_player", "stat", "weight", "games"])

    # Build outs rows: rotation_set - active_set
    outs_rows: List[Tuple[str, pd.Timestamp, str]] = []
    for _, r in active_players.iterrows():
        team = r[team_col]
        gdate = r[date_col]
        active_set = set(r["active_players"])
        rotation = rotation_players.get(team, set())
        missing_players = rotation - active_set
        for out_p in missing_players:
            outs_rows.append((team, gdate, out_p))

    if not outs_rows:
        return pd.DataFrame(columns=[team_col, "out_player", "beneficiary_player", "stat", "weight", "games"])

    outs_df = pd.DataFrame(outs_rows, columns=[team_col, date_col, "out_player"])

    # Observed shares for beneficiaries (active players) + baseline join
    obs = df[df["active"]][
        [team_col, date_col, player_col, "pts_share", "reb_share", "ast_share"]
    ].rename(columns={player_col: "beneficiary_player"})

    base_ben = base.rename(columns={player_col: "beneficiary_player"})
    obs = obs.merge(base_ben, on=[team_col, "beneficiary_player"], how="left")

    # Delta shares vs baseline
    obs["d_pts"] = obs["pts_share"] - obs["base_pts_share"]
    obs["d_reb"] = obs["reb_share"] - obs["base_reb_share"]
    obs["d_ast"] = obs["ast_share"] - obs["base_ast_share"]

    joined = outs_df.merge(
        obs[[team_col, date_col, "beneficiary_player", "d_pts", "d_reb", "d_ast"]],
        on=[team_col, date_col],
        how="left",
    )

    # Don’t allow self-out
    joined = joined[joined["out_player"].str.lower() != joined["beneficiary_player"].str.lower()].copy()

    long = pd.concat(
        [
            joined[[team_col, "out_player", "beneficiary_player"]].assign(stat="PTS", delta_share=joined["d_pts"]),
            joined[[team_col, "out_player", "beneficiary_player"]].assign(stat="REB", delta_share=joined["d_reb"]),
            joined[[team_col, "out_player", "beneficiary_player"]].assign(stat="AST", delta_share=joined["d_ast"]),
        ],
        ignore_index=True,
    )

    # Aggregate per out_player + beneficiary + stat.
    #
    # Pure signed-mean clipping makes a row disappear when a small number of
    # negative games outweigh several positive games. That is too brittle for
    # the reader-gate seam we are tuning, so keep a small blended floor for
    # rows that are only slightly negative but still have repeated positive
    # evidence.
    agg = long.groupby([team_col, "out_player", "beneficiary_player", "stat"], as_index=False).agg(
        delta_share=("delta_share", "mean"),
        pos_delta_sum=("delta_share", lambda s: float(np.clip(s.to_numpy(dtype=float), 0.0, None).sum())),
        pos_hits=("delta_share", lambda s: int((s.to_numpy(dtype=float) > 0.0).sum())),
        games=("delta_share", "size"),
    )

    agg["pos_delta_mean"] = np.where(
        agg["pos_hits"] > 0,
        agg["pos_delta_sum"] / agg["pos_hits"],
        0.0,
    )

    score = agg["delta_share"].clip(lower=0.0)
    mixed_mask = (
        (agg["delta_share"] <= 0.0)
        & (agg["delta_share"] > -0.01)
        & (agg["pos_delta_mean"] >= 0.04)
        & (agg["games"] >= 10)
    )
    score.loc[mixed_mask] = (
        agg.loc[mixed_mask, "delta_share"] + 0.2 * agg.loc[mixed_mask, "pos_delta_mean"]
    ).clip(lower=0.0)

    agg["score"] = score
    agg["sum_score"] = agg.groupby([team_col, "out_player", "stat"])["score"].transform("sum")
    agg["weight"] = np.where(agg["sum_score"] > 0, agg["score"] / agg["sum_score"], 0.0)

    out = agg.drop(columns=["delta_share", "pos_delta_sum", "pos_hits", "pos_delta_mean", "score", "sum_score"])
    out = out[out["stat"].isin(list(STAT_FAMILIES))].reset_index(drop=True)
    return out

# ============================================================
# Main multiplier
# ============================================================

def compute_role_multiplier(
    *,
    gamelogs: pd.DataFrame,
    share_matrix: pd.DataFrame,
    iael_df: pd.DataFrame,
    player: str,
    team: str,
    stat: str,
    cfg: Optional[ReallocConfig] = None,
    minutes_col: str = "minutes",
) -> Tuple[float, Dict[str, Any]]:
    """
    Returns (multiplier, debug_dict).
    Multiplier is applied to the simulated mean (rate_mu) in probability.py.
    """
    if cfg is None:
        cfg = default_config()

    stat_u = (stat or "").upper().strip()
    if stat_u not in STAT_FAMILIES:
        return 1.0, {"reason": "stat_not_core"}

    if iael_df is None or iael_df.empty:
        return 1.0, {"reason": "no_iael"}

    team_u = _norm_team(team)
    if not team_u:
        return 1.0, {"reason": "no_team"}

    player_s = _norm_player(player)
    player_k = _player_key(player_s)
    if not player_k:
        return 1.0, {"reason": "no_player"}

    ia = iael_df.copy()

    if "team_norm" in ia.columns:
        ia["team_u"] = _to_str_series(ia["team_norm"]).map(_norm_team)
    elif "team" in ia.columns:
        ia["team_u"] = _to_str_series(ia["team"]).map(_norm_team)

    if "player_norm" in ia.columns:
        ia["player_s"] = _to_str_series(ia["player_norm"])
    elif "player" in ia.columns:
        ia["player_s"] = _to_str_series(ia["player"])
    else:
        ia["player_s"] = ""

    ia["player_k"] = ia["player_s"].map(_player_key)

    if "status" in ia.columns:
        ia["status_u"] = _to_u_str_series(ia["status"])
    else:
        ia["status_u"] = "OUT"

    def out_frac(status: str) -> float:
        if status in ("OUT", "O", "DOUBTFUL", "D"):
            return 1.0
        if status in ("QUESTIONABLE", "Q"):
            return float(cfg.questionable_out_fraction)
        return 0.0
    ia["out_frac"] = ia["status_u"].map(out_frac)

    # Build outs: IAEL rows for this team with an out fraction > 0
    outs = ia.loc[(ia["team_u"].astype(str) == team_u) & (ia["out_frac"].fillna(0.0) > 0.0)].copy()
    if "player_k" not in outs.columns:
        outs["player_k"] = outs["player_s"].map(_player_key)

    if outs.empty:
        return 1.0, {
            "reason": "no_team_outs",
            "team_u": team_u,
            "player_k": player_k,
            "ia_team_u_sample": ia["team_u"].dropna().astype(str).unique()[:5].tolist() if "team_u" in ia.columns else [],
            "ia_status_u_counts": ia["status_u"].value_counts().head(10).to_dict() if "status_u" in ia.columns else {},
            "ia_out_frac_pos": int((ia["out_frac"].fillna(0.0) > 0.0).sum()) if "out_frac" in ia.columns else 0,
        }

    if (outs["player_k"] == player_k).any():
        return 1.0, {
            "reason": "player_is_out",
            "team_u": team_u,
            "player_k": player_k,
            "outs_n": int(len(outs)),
            "outs_players_sample": outs["player_s"].head(5).tolist() if "player_s" in outs.columns else [],
        }

    # Normalize gamelogs for lookups
    gl = gamelogs.copy()
    gl["game_date"] = pd.to_datetime(gl["game_date"], errors="coerce").dt.normalize()
    gl["team"] = _to_u_str_series(gl["team"])
    gl["player"] = _to_str_series(gl["player"])
    gl["player_k"] = gl["player"].map(_player_key)
    
    # ensure we always pass a Series (not None) into pd.to_numeric
    if minutes_col in gl.columns:
        mins_series = gl[minutes_col]
    else:
        mins_series = pd.Series(np.nan, index=gl.index)
    gl[minutes_col] = pd.to_numeric(mins_series, errors="coerce").fillna(0.0)

    stat_col = stat_u.lower()
    pl = gl[(gl["team"] == team_u) & (gl["player_k"] == player_k) & (gl[minutes_col] > 0)]
    if pl.empty or stat_col not in pl.columns:
        return 1.0, {
            "reason": "no_player_logs",
            "team_u": team_u,
            "player_k": player_k,
            "stat_col": stat_col,
            "pl_rows": int(len(pl)),
            "pl_has_stat_col": bool(stat_col in pl.columns),
            "gl_rows": int(len(gl)),
            "gl_team_rows": int((gl["team"] == team_u).sum()) if "team" in gl.columns else None,
            "gl_team_playerk_nunique": int(gl.loc[gl["team"] == team_u, "player_k"].nunique())
            if ("team" in gl.columns and "player_k" in gl.columns)
            else None,
            "gl_team_sample": sorted(gl["team"].dropna().unique().tolist())[:10]
            if "team" in gl.columns
            else None,
        }

    base_mean = _safe_float(
        pd.to_numeric(pl[stat_col], errors="coerce").dropna().tail(20).mean(),
        default=np.nan,
    )
    if not np.isfinite(base_mean) or base_mean <= 0:
        return 1.0, {"reason": "bad_base_mean"}

    removed = 0.0
    out_list: List[Tuple[str, float]] = []
    for _, r in outs.iterrows():
        out_p_raw = _norm_player(r["player_s"])
        out_k = _player_key(out_p_raw)
        frac = float(r["out_frac"])
        out_list.append((out_k, frac))

        out_logs = gl[(gl["team"] == team_u) & (gl["player_k"] == out_k) & (gl[minutes_col] > 0)]
        if out_logs.empty or stat_col not in out_logs.columns:
            continue

        out_mean = _safe_float(
            pd.to_numeric(out_logs[stat_col], errors="coerce").dropna().tail(20).mean(),
            default=np.nan,
        )
        if np.isfinite(out_mean) and out_mean > 0:
            removed += frac * out_mean

    if removed <= 0:
        return 1.0, {
            "reason": "no_removed_budget",
            "team_u": team_u,
            "player_k": player_k,
            "stat_col": stat_col,
            "outs_n": int(len(out_list)),
            "outs_k_sample": [o[0] for o in out_list[:8]],
            "outs_found_logs_n": int(
                sum(
                    1
                    for out_k, _ in out_list
                    if not gl[
                        (gl["team"] == team_u)
                        & (gl["player_k"] == out_k)
                        & (gl[minutes_col] > 0)
                    ].empty
                )
            )
            if ("team" in gl.columns and "player_k" in gl.columns and minutes_col in gl.columns)
            else None,
            "gl_team_rows": int((gl["team"] == team_u).sum()) if "team" in gl.columns else None,
            "gl_team_playerk_nunique": int(gl.loc[gl["team"] == team_u, "player_k"].nunique())
            if ("team" in gl.columns and "player_k" in gl.columns)
            else None,
        }
    # ------------------------------------------------------------
    # Candidate pool + weights
    # ------------------------------------------------------------
    mode = str(getattr(cfg, "weight_mode", "teamshare") or "teamshare").lower().strip()
    alpha_raw = float(getattr(cfg, "blend_alpha", 0.5) or 0.5)
    alpha_raw = float(np.clip(alpha_raw, 0.0, 1.0))
    usage_lb = int(getattr(cfg, "usage_lookback_games", 15) or 15)  # legacy

    team_active = gl[(gl["team"] == team_u) & (gl[minutes_col] > 0)].copy()

    candidates = sorted(
        team_active["player"].dropna().astype(str).str.strip().unique().tolist(),
        key=str.lower
    )

    out_lc = {p.strip().lower() for p, _ in out_list}
    # drop out players from candidate pool using canonical keys
    candidates = [p for p in candidates if _player_key(p) not in out_lc]
    if not candidates:
        return 1.0, {"reason": "no_candidates"}

    # ---- Usage weights (trade-aware) ----
    w_usage_dbg: Dict[str, float] = {}
    w_usage_map, usage_dbg_map = build_trade_aware_usage_weights(
        gamelogs_all=gl,            # multi-team (for prev-team inference)
        team_active=team_active,    # team-scoped (for current-team windows)
        candidates=candidates,
        team_u=team_u,
        stat=stat_u,
        cfg=cfg,
    )
    if player_s in usage_dbg_map:
        w_usage_dbg = usage_dbg_map[player_s]

    # ---- Teamshare weights ----
    w_teamshare_map, used_outs = build_teamshare_weights_for_outs(
        share_matrix=share_matrix if share_matrix is not None else pd.DataFrame(),
        team_u=team_u,
        stat_u=stat_u,
        out_list=out_list,
        candidates=candidates,
        min_games_for_pattern=int(cfg.min_games_for_pattern),
    )

    # ---- Support-scaled alpha (Option C) ----
    alpha_mult, supported_outs, support_score = _teamshare_alpha_multiplier(
        share_matrix=share_matrix if share_matrix is not None else pd.DataFrame(),
        team_u=team_u,
        stat_u=stat_u,
        out_list=out_list,
        min_games_for_pattern=int(cfg.min_games_for_pattern),
    )
    alpha_eff = float(alpha_raw) * float(alpha_mult)

    # Preserve the redistribution philosophy, but shrink the effect when the
    # share-matrix support for the current out pattern is weak.
    support_floor = float(getattr(cfg, "teamshare_support_budget_floor", 0.75) or 0.75)
    support_floor = float(np.clip(support_floor, 0.0, 1.0))
    # Support must be both present and consistent; weak out patterns should not
    # receive the same redistribution budget as fully-supported patterns.
    support_strength = float(alpha_mult) * float(support_score)
    support_curve = float(np.clip(support_strength ** 1.35, 0.0, 1.0))
    support_budget_mult = float(np.clip(support_floor + (1.0 - support_floor) * support_curve, 0.0, 1.0))

    # ---- Debug stats (effective outs, rel distribution) ----
    rel_thr = float(getattr(cfg, "teamshare_rel_effective_threshold", 0.25) or 0.25)
    ts_stats = _teamshare_support_stats(
        share_matrix=share_matrix if share_matrix is not None else pd.DataFrame(),
        team_u=team_u,
        stat_u=stat_u,
        out_list=out_list,
        min_games_for_pattern=int(cfg.min_games_for_pattern),
        rel_effective_threshold=rel_thr,
    )

    if bool(getattr(cfg, "debug_prints", False)):
        sm_rows = 0 if share_matrix is None else int(len(share_matrix))
        print(
            f"[TEAMSHARE DBG] team={team_u} stat={stat_u} share_matrix_rows={sm_rows} "
            f"used_outs={used_outs} supported_outs={supported_outs} support={support_score:.3f} "
            f"alpha_raw={alpha_raw:.3f} alpha_eff={alpha_eff:.3f} "
            f"effective_outs={ts_stats.get('effective_outs', 0.0)} rel_wmean={ts_stats.get('rel_wmean', 0.0):.3f}"
        )

    # ---- Choose final weights (VECTOR + RENORMALIZE) ----
    if mode == "usage":
        w_final_map = dict(w_usage_map)
        weight_reason = f"usage_tradeaware(power={float(getattr(cfg, 'usage_power', 1.0) or 1.0):.2f})"
    elif mode == "teamshare":
        w_final_map = dict(w_teamshare_map)
        weight_reason = "teamshare"
    else:
        w_final_map = {
            p: (alpha_eff * float(w_teamshare_map.get(p, 0.0)) + (1.0 - alpha_eff) * float(w_usage_map.get(p, 0.0)))
            for p in candidates
        }
        w_final_map = _normalize_weight_map(w_final_map, keys=candidates)
        weight_reason = (
            f"blend(alpha_eff={alpha_eff:.2f}, raw={alpha_raw:.2f}, support={support_score:.2f})"
            f"|usage_power={float(getattr(cfg, 'usage_power', 1.6) or 1.6):.2f}"
        )

    # ------------------------------------------------------------
    # Rotation-likelihood reweight (must happen BEFORE depth/capture)
    # ------------------------------------------------------------
    rot_factor = float(np.nan)
    rot_enabled = bool(getattr(cfg, "rotation_reweight_enabled", True))
    if rot_enabled:
        rot_map = rotation_likelihood_map(
            team_active=team_active,
            candidates=candidates,
            minutes_col=minutes_col,
            last_n_games=int(getattr(cfg, "rotation_last_n_games", 10) or 10),
            a0=float(getattr(cfg, "rotation_a0", 3.0) or 3.0),
            sa=float(getattr(cfg, "rotation_sa", 1.0) or 1.0),
            m0=float(getattr(cfg, "rotation_m0", 10.0) or 10.0),
            sm=float(getattr(cfg, "rotation_sm", 3.0) or 3.0),
            floor=float(getattr(cfg, "rotation_floor", 0.05) or 0.05),
        )

        rot_factor = float(rot_map.get(player_s, 1.0))
        w_final_map = {p: float(w_final_map.get(p, 0.0)) * float(rot_map.get(p, 1.0)) for p in candidates}
        w_final_map = _normalize_weight_map(w_final_map, keys=candidates)
        weight_reason = weight_reason + "|rotation_reweight"

    # ------------------------------------------------------------
    # Replaceability-adjusted capture (depth + concentration)
    # ------------------------------------------------------------
    cap_map = dict(cfg.capture_rate or {})

    def _cap_fix(key: str, default: float) -> None:
        v = cap_map.get(key, None)
        try:
            vf = float(v) if v is not None else float("nan")
        except Exception:
            vf = float("nan")
        if (not np.isfinite(vf)) or (vf <= 0.0):
            cap_map[key] = float(default)

    _cap_fix("PTS", 0.90)
    _cap_fix("REB", 0.95)
    _cap_fix("AST", 0.85)

    cap_base = float(cap_map.get(stat_u, 0.90))

    cap_adj, n_eff, top_mass_n, conc_penalty, cap_adj_pre_clamp = _adjust_capture_for_depth(
        base_cap=cap_base,
        weight_map=w_final_map,
        cfg=cfg,
    )
    redistributed = removed * cap_adj * support_budget_mult

    w_total = float(max(0.0, w_final_map.get(player_s, 0.0)))

    if w_total <= 0:
        mins = team_active.groupby("player")[minutes_col].mean().to_dict()
        denom = float(sum(max(cfg.min_minutes_clip, float(v)) for v in mins.values()))
        my_m = float(mins.get(player_s, 0.0))
        w_total = (max(cfg.min_minutes_clip, my_m) / denom) if denom > 0 else 0.0
        weight_reason = weight_reason + "|minutes_fallback"

    bump = redistributed * w_total
    new_mean = base_mean + bump

    mult = (new_mean / base_mean) if base_mean > 0 else 1.0
    mult = float(min(mult, cfg.max_multiplier))

    # ------------------------------------------------------------
    # NEW: Role expansion guardrails (soft caps on multiplier)
    # Triggered on common "2 stars sit" nights or big removed budgets.
    # Applied AFTER all allocation math so it can't break weight logic.
    # ------------------------------------------------------------
    mult_pre_guardrails = float(mult)
    guardrails_enabled = bool(getattr(cfg, "role_guardrails_enabled", True))
    guardrails_applied = False
    guardrail_cap_used = float("nan")
    guardrail_trigger = ""

    if guardrails_enabled:
        min_outs = int(getattr(cfg, "role_guardrails_min_outs", 2) or 2)
        thresholds = dict(getattr(cfg, "role_guardrails_removed_threshold", None) or {})
        caps = dict(getattr(cfg, "role_guardrails_cap_mult", None) or {})
        softness = float(getattr(cfg, "role_guardrails_softness", 0.15) or 0.15)

        # Defaults if user left dicts empty
        if not thresholds:
            thresholds = {"PTS": 30.0, "AST": 7.0, "REB": 10.0}
        if not caps:
            caps = {"PTS": 1.35, "AST": 1.25, "REB": 1.20}

        thr = float(thresholds.get(stat_u, float("inf")))
        capm = float(caps.get(stat_u, float("inf")))

        outs_n = int(len(out_list))
        big_vacuum = np.isfinite(thr) and (float(removed) >= thr)
        multi_out = outs_n >= min_outs

        if (big_vacuum or multi_out) and np.isfinite(capm) and capm > 0:
            # Soft cap the multiplier
            mult = _soft_cap_multiplier(mult, cap=capm, softness=softness)
            mult = float(min(mult, cfg.max_multiplier))  # keep global safety cap
            guardrails_applied = (abs(mult - mult_pre_guardrails) > 1e-12)
            guardrail_cap_used = float(capm)
            if big_vacuum and multi_out:
                guardrail_trigger = "outs_and_removed"
            elif big_vacuum:
                guardrail_trigger = "removed"
            else:
                guardrail_trigger = "outs"

    dbg_out: Dict[str, Any] = {
        "reason": "ok",
        "team": team_u,
        "stat": stat_u,
        "base_mean": float(base_mean),
        "removed_budget": float(removed),

        # capture
        "cap_base": float(cap_base),
        "cap_adj": float(cap_adj),
        "cap_adj_pre_clamp": float(cap_adj_pre_clamp),
        "n_eff": float(n_eff),
        "depth_top_mass_n": float(top_mass_n),
        "depth_conc_penalty": float(conc_penalty),
        "redistributed": float(redistributed),

        # capture cfg echoes (helps debug “did my changes apply?”)
        "cfg_depth_ref_engines": float(getattr(cfg, "depth_ref_engines", np.nan)),
        "cfg_depth_slope": float(getattr(cfg, "depth_slope", np.nan)),
        "cfg_depth_cap_min": float(getattr(cfg, "depth_cap_min", np.nan)),
        "cfg_depth_cap_max": float(getattr(cfg, "depth_cap_max", np.nan)),
        "cfg_depth_top_k": float(getattr(cfg, "depth_top_k", np.nan)),
        "cfg_depth_conc_enabled": 1.0 if bool(getattr(cfg, "depth_conc_enabled", True)) else 0.0,
        "cfg_depth_conc_top_n": float(getattr(cfg, "depth_conc_top_n", np.nan)),
        "cfg_depth_conc_floor": float(getattr(cfg, "depth_conc_floor", np.nan)),
        "cfg_depth_conc_span": float(getattr(cfg, "depth_conc_span", np.nan)),
        "cfg_depth_conc_max_penalty": float(getattr(cfg, "depth_conc_max_penalty", np.nan)),

        # weights + bump
        "weight": float(w_total),
        "bump": float(bump),
        "mult": float(mult),
        "outs": float(len(out_list)),

        # NEW guardrails debug
        "mult_pre_guardrails": float(mult_pre_guardrails),
        "guardrails_enabled": 1.0 if guardrails_enabled else 0.0,
        "guardrails_applied": 1.0 if guardrails_applied else 0.0,
        "guardrails_trigger": guardrail_trigger,
        "guardrails_cap_mult": float(guardrail_cap_used) if np.isfinite(guardrail_cap_used) else np.nan,
        "guardrails_softness": float(getattr(cfg, "role_guardrails_softness", np.nan)),

        # teamshare usage
        "outs_used_pattern": float(used_outs),
        "outs_used_pattern_effective": float(ts_stats.get("effective_outs", np.nan)),
        "teamshare_rel_threshold": float(rel_thr),
        "teamshare_rel_wmean": float(ts_stats.get("rel_wmean", np.nan)),
        "teamshare_rel_min": float(ts_stats.get("rel_min", np.nan)),
        "teamshare_rel_max": float(ts_stats.get("rel_max", np.nan)),

        "teamshare_supported_outs": float(supported_outs),
        "teamshare_support_score": float(support_score),
        "teamshare_support_budget_floor": float(support_floor),
        "teamshare_support_budget_mult": float(support_budget_mult),
        "teamshare_alpha_mult": float(alpha_mult),
        "teamshare_alpha_eff": float(alpha_eff),

        # weight debug (player-level)
        "weight_mode": mode,
        "weight_mode_str": weight_reason,
        "blend_alpha_raw": float(alpha_raw),
        "usage_power": float(getattr(cfg, "usage_power", 1.6) or 1.6),
        "weight_usage": float(w_usage_map.get(player_s, 0.0)),
        "weight_teamshare": float(w_teamshare_map.get(player_s, 0.0)),

        # rotation debug
        "rotation_enabled": 1.0 if rot_enabled else 0.0,
        "rot_factor": float(rot_factor) if np.isfinite(rot_factor) else np.nan,

        # sanity
        "weight_final_sum": float(sum(w_final_map.values())) if isinstance(w_final_map, dict) else np.nan,
        "candidate_count": float(len(candidates)),
    }

    for k, v in (w_usage_dbg or {}).items():
        try:
            dbg_out[f"usage_{k}"] = float(v)
        except Exception:
            pass

    dbg_out["usage_lb_legacy"] = float(usage_lb)

    return mult, dbg_out
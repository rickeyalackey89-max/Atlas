from __future__ import annotations

"""
src/Atlas/engine/new_probability.py

NewEngine probability kernel (Monte Carlo), with optional Role Context (team-share)
mean/variance adjustment driven by a precomputed share matrix.

Key points:
- Defaults preserve prior behavior when role context is not available:
  * If iael_df is None/empty OR share_matrix.csv missing -> role_ctx no-op.
- Role Context:
  * Adjusts per-minute mean rate by a tight-clamped multiplier.
  * Conservatively inflates per-minute rate sigma (tight clamp) as multiplier moves from 1.0.
- Designed to be auditable: returns role_ctx_* diagnostics in the output dict.

PATCH (2026-02-20):
- p_raw (no role), p_role (role ctx), and p_adj are separated.
- p_adj is ALWAYS computed by:
    p_adj = adjust_probability_for_blowout(p_raw=p_role, blowout_risk=q, sens=minutes_s)
- p_close is also adjusted the same way, so p_close can differ from p_close_raw.
- Spread extraction is robust (many possible input column names).
- Blowout probability uses a local two-tailed Normal tail calculation (no SciPy).
"""

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from Atlas.core.features import summarize_stat, get_player_window
from Atlas.core.minutes import adjust_probability_for_blowout, minutes_sensitivity

# -------------------------------------------------------------------
# Share matrix cache
# -------------------------------------------------------------------

_SHARE_MATRIX: pd.DataFrame | None = None
_SHARE_MATRIX_PREPARED: bool = False


def _repo_root_from_here() -> Path:
    # src/Atlas/engine/new_probability.py -> parents:
    # [0]=engine, [1]=Atlas, [2]=src, [3]=repo root
    return Path(__file__).resolve().parents[3]


def _canon_name(s: str) -> str:
    """
    Canonicalize player names for stable matching:
    - Handle "Last,First" by swapping to "First Last" first
    - NFKD deaccent
    - lowercase
    - strip punctuation
    - remove common suffixes (jr, sr, ii, iii, iv, v)
    - collapse whitespace
    """
    if s is None:
        return ""

    s = str(s).strip()

    # Normalize "Last,First Middle" -> "First Middle Last"
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            s = f"{parts[1]} {parts[0]}"

    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _load_share_matrix() -> pd.DataFrame:
    """
    Load share_matrix.csv once. If missing/unreadable, returns empty DataFrame.
    Expected columns:
      team, out_player, beneficiary_player, stat, games, weight
    """
    global _SHARE_MATRIX, _SHARE_MATRIX_PREPARED
    if _SHARE_MATRIX is None:
        try:
            root = _repo_root_from_here()
            path = root / "data" / "model" / "share_matrix.csv"
            if path.exists():
                _SHARE_MATRIX = pd.read_csv(path)
            else:
                _SHARE_MATRIX = pd.DataFrame()
        except Exception:
            _SHARE_MATRIX = pd.DataFrame()

    if (
        not _SHARE_MATRIX_PREPARED
        and isinstance(_SHARE_MATRIX, pd.DataFrame)
        and not _SHARE_MATRIX.empty
    ):
        # normalize expected cols to strings and add canonical helper cols
        for c in ["team", "out_player", "beneficiary_player", "stat"]:
            if c in _SHARE_MATRIX.columns:
                _SHARE_MATRIX[c] = _SHARE_MATRIX[c].astype(str)

        if "team" in _SHARE_MATRIX.columns:
            _SHARE_MATRIX["team_u"] = _SHARE_MATRIX["team"].astype(str).str.upper().str.strip()
        if "stat" in _SHARE_MATRIX.columns:
            _SHARE_MATRIX["stat_u"] = _SHARE_MATRIX["stat"].astype(str).str.upper().str.strip()
        if "out_player" in _SHARE_MATRIX.columns:
            _SHARE_MATRIX["out_canon"] = _SHARE_MATRIX["out_player"].map(_canon_name)
        if "beneficiary_player" in _SHARE_MATRIX.columns:
            _SHARE_MATRIX["ben_canon"] = _SHARE_MATRIX["beneficiary_player"].map(_canon_name)

        # coerce numeric fields
        if "games" in _SHARE_MATRIX.columns:
            _SHARE_MATRIX["games"] = pd.to_numeric(_SHARE_MATRIX["games"], errors="coerce").fillna(0).astype(int)
        if "weight" in _SHARE_MATRIX.columns:
            _SHARE_MATRIX["weight"] = pd.to_numeric(_SHARE_MATRIX["weight"], errors="coerce").fillna(0.0).astype(float)

        _SHARE_MATRIX_PREPARED = True

    return _SHARE_MATRIX


def _smoothed_prob(hits: np.ndarray) -> float:
    """
    Laplace smoothing to prevent exact 0/1 probabilities due to finite Monte Carlo:
        p = (sum(hits) + 0.5) / (N + 1.0)
    """
    n = int(hits.size)
    if n <= 0:
        return 0.0
    s = float(hits.sum())
    p = (s + 0.5) / (n + 1.0)
    eps = 1e-12
    if p <= 0.0:
        return eps
    if p >= 1.0:
        return 1.0 - eps
    return float(p)


# --- IAEL team normalization -------------------------------------------------
_TEAM_NAME_TO_ABBR = {
    "AtlantaHawks": "ATL",
    "BostonCeltics": "BOS",
    "BrooklynNets": "BKN",
    "CharlotteHornets": "CHA",
    "ChicagoBulls": "CHI",
    "ClevelandCavaliers": "CLE",
    "DallasMavericks": "DAL",
    "DenverNuggets": "DEN",
    "DetroitPistons": "DET",
    "GoldenStateWarriors": "GSW",
    "HoustonRockets": "HOU",
    "IndianaPacers": "IND",
    "LACLippers": "LAC",
    "LosAngelesClippers": "LAC",
    "LALakers": "LAL",
    "LosAngelesLakers": "LAL",
    "MemphisGrizzlies": "MEM",
    "MiamiHeat": "MIA",
    "MilwaukeeBucks": "MIL",
    "MinnesotaTimberwolves": "MIN",
    "NewOrleansPelicans": "NOP",
    "NewYorkKnicks": "NYK",
    "OklahomaCityThunder": "OKC",
    "OrlandoMagic": "ORL",
    "Philadelphia76ers": "PHI",
    "PhoenixSuns": "PHX",
    "PortlandTrailBlazers": "POR",
    "SacramentoKings": "SAC",
    "SanAntonioSpurs": "SAS",
    "TorontoRaptors": "TOR",
    "UtahJazz": "UTA",
    "WashingtonWizards": "WAS",
}


def _team_to_abbr(team: Any) -> str:
    s = str(team or "").strip()
    if not s:
        return ""
    if len(s) == 3 and s.isalpha():
        return s.upper()
    s2 = re.sub(r"[^A-Za-z0-9]", "", s)
    if s2 in _TEAM_NAME_TO_ABBR:
        return _TEAM_NAME_TO_ABBR[s2]
    return s2[:3].upper()


def _load_iael_status_latest() -> pd.DataFrame:
    """Load IAEL normalized status rows from data/output/dashboard/status_latest.json (if present)."""
    try:
        p = Path("data/output/dashboard/status_latest.json")
        if not p.exists():
            return pd.DataFrame()
        j = json.loads(p.read_text(encoding="utf-8"))
        rows = j.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _extract_team_outs(iael_df: pd.DataFrame, team_u: str) -> list[str]:
    """
    Best-effort extraction of OUT-ish players for a given team from IAEL dataframe.

    Supported patterns:
      - columns: team, player, status
      - columns: team, out_player
      - columns: team, name, iael_status
    """
    if iael_df is None or not isinstance(iael_df, pd.DataFrame) or iael_df.empty:
        return []

    cols = {c.lower(): c for c in iael_df.columns}
    team_col = cols.get("team")
    if not team_col:
        return []

    team_norm = iael_df[team_col].astype(str).map(_team_to_abbr)
    team_norm = team_norm.astype(str).str.upper().str.strip()
    tmask = (team_norm.ne("")) & team_norm.eq(team_u)
    if not bool(tmask.any()):
        return []

    df = iael_df.loc[tmask].copy()

    if "out_player" in cols:
        out_col = cols["out_player"]
        outs = df[out_col].dropna().astype(str).tolist()
        return [o for o in outs if str(o).strip()]

    status_col = cols.get("status") or cols.get("iael_status") or cols.get("injury_status")
    name_col = cols.get("player") or cols.get("name")
    if not name_col or not status_col:
        return []

    status_u = df[status_col].astype(str).str.upper().str.strip()
    out_mask = status_u.isin(["OUT", "O", "OUT.", "DNP", "INACTIVE", "DOUBTFUL", "D", "QUESTIONABLE", "Q"])
    if not bool(out_mask.any()):
        return []

    outs = df.loc[out_mask, name_col].dropna().astype(str).tolist()
    return [o for o in outs if str(o).strip()]


def compute_role_multiplier(
    share_matrix: pd.DataFrame,
    iael_df: pd.DataFrame,
    *,
    player: str,
    team: str,
    stat: str,
    min_games: int = 3,
    max_outs_used: int = 6,
) -> tuple[float, dict[str, Any]]:
    """
    Compute role multiplier for a (player, team, stat) given IAEL outs and share_matrix.

    share_matrix prepared schema: team_u, out_canon, ben_canon, stat_u, games, weight
    Interpretation:
      - For each OUT teammate, accumulate 'weight' where this player is beneficiary.
      - role_mult_raw = 1 + union(weight bumps)
    """
    team_u = str(team).upper().strip()
    stat_u = str(stat).upper().strip()
    stat_u = {
        "3PM": "FG3M",
        "3PTM": "FG3M",
        "3PT": "FG3M",
        "3P": "FG3M",
        "FG3": "FG3M",
    }.get(stat_u, stat_u)
    ben = _canon_name(player)

    outs = _extract_team_outs(iael_df, team_u)
    outs_canon = [canon for o in outs if (canon := _canon_name(o))]
    if not outs_canon:
        return 1.0, {
            "reason": "no_outs",
            "outs": [],
            "components": [stat_u],
            "component_mults": [1.0],
            "component_reasons": ["no_outs"],
        }

    outs_canon = list(dict.fromkeys(outs_canon))[:max_outs_used]

    if share_matrix is None or not isinstance(share_matrix, pd.DataFrame) or share_matrix.empty:
        return 1.0, {
            "reason": "no_share_matrix",
            "outs": outs[: len(outs_canon)],
            "components": [stat_u],
            "component_mults": [1.0],
            "component_reasons": ["no_share_matrix"],
        }

    required = {"team_u", "stat_u", "out_canon", "ben_canon", "games", "weight"}
    if not required.issubset(set(share_matrix.columns)):
        return 1.0, {
            "reason": "share_matrix_schema_missing",
            "outs": outs[: len(outs_canon)],
            "components": [stat_u],
            "component_mults": [1.0],
            "component_reasons": ["share_matrix_schema_missing"],
        }

    sub = share_matrix[
        (share_matrix["team_u"] == team_u)
        & (share_matrix["stat_u"] == stat_u)
        & (share_matrix["ben_canon"] == ben)
        & (share_matrix["out_canon"].isin(outs_canon))
        & (share_matrix["games"] >= int(min_games))
    ]

    # Drop zero-weight matches
    sub = sub[sub["weight"].abs() > 1e-12]
    if sub.empty:
        # Distinguish: no matches at all vs matches exist but not for this beneficiary
        try:
            sub_any = share_matrix[
                (share_matrix["team_u"] == team_u)
                & (share_matrix["stat_u"] == stat_u)
                & (share_matrix["out_canon"].isin(outs_canon))
                & (share_matrix["games"] >= int(min_games))
            ]
            sub_any = sub_any[sub_any["weight"].abs() > 1e-12]
            if not sub_any.empty:
                return 1.0, {
                    "reason": "no_beneficiary_match",
                    "team": team_u,
                    "stat": stat_u,
                    "outs": outs[: len(outs_canon)],
                    "components": [stat_u],
                    "component_mults": [1.0],
                    "component_reasons": ["no_beneficiary_match"],
                    "outs_used": 0,
                    "bump": 0.0,
                }
        except Exception:
            pass

    # ✅ Pylance-friendly aggregation
    by_out = (
        sub.groupby("out_canon", sort=False)["weight"]
        .sum()
        .sort_values(ascending=False)
        .reset_index(name="weight")
    )

    w = by_out["weight"].to_numpy(dtype=float)
    w = np.clip(w, 0.0, 0.95)  # safety clip

    total_bump = float(1.0 - np.prod(1.0 - w))
    role_mult_raw = 1.0 + total_bump

    return role_mult_raw, {
        "reason": "ok",
        "outs": outs[: len(outs_canon)],
        "outs_used": int(by_out.shape[0]),
        "bump": float(total_bump),
        "by_out": by_out.to_dict(orient="records")[:10],
        "stat": stat_u,
        "team": team_u,
        "min_games": int(min_games),
    }


# -------------------------------------------------------------------
# Spread extraction + blowout probability (local, robust)
# -------------------------------------------------------------------

def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _get_spread(row: pd.Series) -> float:
    """
    Your earlier telemetry showed 'spread' column missing.
    This tries multiple candidate columns so q_blowout isn't permanently 0.
    """
    candidates = [
        "spread",
        "closing_spread",
        "spread_close",
        "home_spread",
        "spread_home",
        "vegas_spread",
        "market_spread",
        "proj_spread",
        "spread_pts",
        # Sometimes people store it as 'line'
        "line_spread",
        "game_spread",
    ]
    for c in candidates:
        if c in row.index:
            v = _to_float(row.get(c), default=float("nan"))
            if math.isfinite(v):
                return v

    # Text fallback
    for c in ["odds", "market", "notes", "game_line"]:
        if c in row.index and row.get(c) is not None:
            s = str(row.get(c))
            m = re.search(r"([+-]?\d+(?:\.\d+)?)", s)
            if m:
                return _to_float(m.group(1), default=0.0)

    return 0.0


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def blowout_probability(*, spread_mean: float, threshold: float, sd: float) -> float:
    """
    Two-tailed probability that |margin| >= threshold when margin ~ Normal(mean=spread_mean, sd=sd).
    This returns > 0 even if spread_mean == 0 (unless threshold is enormous).
    """
    sd = max(1e-9, float(sd))
    t = float(threshold)
    mu = float(spread_mean)

    z_hi = (t - mu) / sd
    z_lo = (-t - mu) / sd

    p_hi = 1.0 - _norm_cdf(z_hi)
    p_lo = _norm_cdf(z_lo)

    p = p_hi + p_lo
    if not math.isfinite(p):
        return 0.0
    return float(max(0.0, min(1.0, p)))


# -------------------------------------------------------------------
# Kernel
# -------------------------------------------------------------------

def simulate_leg_probability_new(
    gamelogs: pd.DataFrame,
    row: pd.Series,
    lookback: int,
    sims: int,
    spread_sd: float,
    blowout_threshold: float,
    star_minute_drop: float,
    role_minute_drop: float,
    *,
    iael_df: pd.DataFrame | None = None,
    role_cfg: dict | None = None,
    rng: np.random.Generator | None = None,
) -> dict:
    """
    Monte Carlo probability for a single leg.

    Output contract:
      - p       := RAW/base probability (no role ctx)
      - p_role  := Role-context probability (ctx applied in simulation)
      - p_adj   := Blowout/minutes sensitivity adjustment applied to p_role:
                  p_adj = adjust_probability_for_blowout(p_raw=p_role, blowout_risk=q, sens=minutes_s)
      - p_close_raw := close-only probability for RAW channel
      - p_close      := close-only probability for ROLE channel, then adjusted same as p_adj
    """

    player = row["player"]
    stat = row["stat"]
    line = float(row["line"])
    direction = str(row["direction"]).upper()
    team = str(row.get("team", "")).upper().strip()

    # spread may not exist; extract robustly
    spread = _get_spread(row)

    g = get_player_window(gamelogs, player, lookback)
    s = summarize_stat(g, stat)

    is_star = float(s.get("min_mean", 0.0)) >= 33.0
    minute_drop = float(star_minute_drop if is_star else role_minute_drop)

    q = blowout_probability(spread_mean=spread, threshold=blowout_threshold, sd=spread_sd)

    mu_close = max(0.0, float(s.get("min_mean", 0.0)))
    sd_close = max(1.0, float(s.get("min_std", 1.0)))

    mu_blow = max(0.0, mu_close - minute_drop)
    sd_blow = max(1.0, sd_close)

    base_rate_mu = float(s.get("rate_mean", 0.0))
    rate_sd_base = max(0.01, float(s.get("rate_std", 0.01)))

    # ------------------------------------------------------------
    # Role context adjustment (mean + conservative variance)
    # ------------------------------------------------------------
    if role_cfg is None:
        cfg: dict[str, Any] = {}
        role_enabled = False
    else:
        cfg = role_cfg or {}
        role_enabled = bool(cfg.get("enabled", True))

    proj_lo = float(cfg.get("projection_clamp_lo", 0.90))
    proj_hi = float(cfg.get("projection_clamp_hi", 1.10))

    var_k = float(cfg.get("variance_k", 0.50))
    var_lo = float(cfg.get("variance_clamp_lo", 1.00))
    var_hi = float(cfg.get("variance_clamp_hi", 1.10))

    min_games = int(cfg.get("min_games", 3))

    role_mult_raw = 1.0
    role_mult = 1.0
    role_sigma_mult = 1.0
    role_reason = "not_applied"
    role_debug: dict[str, Any] | None = None

    stat_u = str(stat).upper().strip()
    STAT_COMPONENTS: dict[str, list[str]] = {
        "FG3M": ["PTS"],
        "3PM": ["PTS"],
        "FGM": ["PTS"],
        "FGA": ["PTS"],
        "PR": ["PTS", "REB"],
        "PA": ["PTS", "AST"],
        "RA": ["REB", "AST"],
        "PRA": ["PTS", "REB", "AST"],
    }

    iael_eff = iael_df
    cols_l = set(c.lower() for c in iael_eff.columns) if isinstance(iael_eff, pd.DataFrame) else set()
    need_fallback = (
        iael_eff is None
        or not isinstance(iael_eff, pd.DataFrame)
        or iael_eff.empty
        or ("team" not in cols_l)
        or (("status" not in cols_l) and ("out_player" not in cols_l))
    )
    if need_fallback:
        iael_eff = _load_iael_status_latest()

    if role_enabled and isinstance(iael_eff, pd.DataFrame) and not iael_eff.empty and team:
        share_matrix = _load_share_matrix()

        if stat_u in ("PTS", "REB", "AST"):
            comps = [stat_u]
        else:
            comps = STAT_COMPONENTS.get(stat_u)

        if comps:
            comp_mults: list[float] = []
            comp_debug: list[dict[str, Any]] = []

            for cstat in comps:
                m, dbg = compute_role_multiplier(
                    share_matrix,
                    iael_eff,
                    player=str(player),
                    team=team,
                    stat=str(cstat),
                    min_games=min_games,
                )
                m = float(m) if np.isfinite(m) and m > 0 else 1.0
                comp_mults.append(m)
                comp_debug.append(dbg)

            # Combine multipliers with diminishing returns (union)
            if len(comp_mults) == 1:
                m0 = float(comp_mults[0])
                b0 = float(np.clip(m0 - 1.0, 0.0, 0.95))
                role_mult_raw = 1.0 + b0
                role_debug = comp_debug[0]
                role_reason = str(role_debug.get("reason", "ok")) if isinstance(role_debug, dict) else "ok"
            else:
                comp = np.array(comp_mults, dtype=float)
                bumps = np.clip(comp - 1.0, 0.0, 0.95)
                total_bump = float(1.0 - np.prod(1.0 - bumps))
                role_mult_raw = 1.0 + total_bump
                
                # Prepare combo aggregation containers (populated in the loop below)
                combo_outs: list[str] = []
                combo_outs_set: set[str] = set()
                combo_outs_used_sum: int = 0
                combo_bump_sum: float = 0.0
                combo_by_out_rows: list[dict] = []

                # Derive per-component reasons and a quick outs_used summary (temporary)
                comp_reasons: list[str] = []
                outs_used_sum_tmp: int = 0
                try:
                    for d in comp_debug:
                        if not isinstance(d, dict):
                            continue
                        comp_reasons.append(str(d.get("reason", "")).strip())
                        try:
                            outs_used_sum_tmp += int(d.get("outs_used", 0) or 0)
                        except Exception:
                            pass
                except Exception:
                    comp_reasons = []
                    outs_used_sum_tmp = 0

                # Decide combo-level role_reason consistent with component outcomes
                if comp_reasons:
                    if all(r == "no_outs" for r in comp_reasons):
                        role_reason = "no_outs"
                    elif all(r == "no_matches" for r in comp_reasons):
                        role_reason = "no_matches"
                    elif any(r == "ok" for r in comp_reasons) and outs_used_sum_tmp > 0:
                        role_reason = "ok_combo"
                    else:
                        role_reason = "combo_no_effect"
                else:
                    role_reason = "combo_no_effect"

                for d in comp_debug:
                    if not isinstance(d, dict):
                        continue

                    # outs (union)
                    outs_d = d.get("outs", None)
                    if outs_d is None:
                        outs_d = []
                    if isinstance(outs_d, (list, tuple)):
                        for o in outs_d:
                            if o is None:
                                continue
                            os_ = str(o).strip()
                            if not os_:
                                continue
                            if os_ not in combo_outs_set:
                                combo_outs_set.add(os_)
                                combo_outs.append(os_)

                    # outs_used (sum, robust)
                    try:
                        combo_outs_used_sum += int(d.get("outs_used", 0) or 0)
                    except Exception:
                        pass

                    # bump (sum, telemetry only)
                    try:
                        combo_bump_sum += float(d.get("bump", 0.0) or 0.0)
                    except Exception:
                        pass

                    # by_out (optional, capped)
                    by_out_d = d.get("by_out", None)
                    if isinstance(by_out_d, list):
                        combo_by_out_rows.extend([r for r in by_out_d if isinstance(r, dict)])
                    elif isinstance(by_out_d, dict):
                        vals = list(by_out_d.values())
                        combo_by_out_rows.extend([r for r in vals if isinstance(r, dict)])

                role_debug = {
                    "reason": role_reason,

                    # component contract (existing)
                    "components": comps,
                    "component_mults": comp_mults,
                    "component_reasons": [str(d.get("reason", "")) for d in comp_debug if isinstance(d, dict)][:10],
                    "component_debug": comp_debug[:3],

                    # combo-level telemetry (NEW; fixes ok_combo outs_used==0 + outs NaN)
                    "outs": combo_outs,
                    "outs_used": int(combo_outs_used_sum),
                    "bump": float(combo_bump_sum),
                    "by_out": combo_by_out_rows[:10],
                }

            role_mult_raw = role_mult_raw if np.isfinite(role_mult_raw) and role_mult_raw > 0 else 1.0

            # Soft-cap to proj_hi
            k_soft = float(cfg.get("projection_softcap_k", 1.35))
            rm = float(role_mult_raw)
            if proj_hi <= 1.0 + 1e-12:
                role_mult = float(np.clip(rm, proj_lo, proj_hi))
            else:
                bump_raw = max(0.0, rm - 1.0)
                cap_bump = float(proj_hi - 1.0)
                bump_soft = cap_bump * (1.0 - float(np.exp(-k_soft * bump_raw / max(1e-12, cap_bump))))
                role_mult_soft = 1.0 + bump_soft
                role_mult = float(np.clip(role_mult_soft, proj_lo, proj_hi))

            role_sigma_mult = 1.0 + var_k * abs(role_mult - 1.0)
            role_sigma_mult = float(np.clip(role_sigma_mult, var_lo, var_hi))
        else:
            role_reason = "stat_unmapped"
            role_debug = {"reason": "stat_unmapped", "stat": stat_u}
    else:
        if not role_enabled:
            role_reason = "disabled"
        elif not isinstance(iael_eff, pd.DataFrame) or iael_eff.empty:
            role_reason = "no_iael"
        elif not team:
            role_reason = "no_team"

    # RAW channel parameters (no ctx)
    rate_mu_raw = base_rate_mu
    rate_sd_raw = rate_sd_base

    # Role-context channel parameters (ctx applied)
    rate_mu_role = base_rate_mu * role_mult
    rate_sd_role = rate_sd_base * role_sigma_mult

    if rng is None:
        rng = np.random.default_rng(42)

    # ------------------------------------------------------------
    # Shared random draws so RAW vs ROLE differ only by parameters
    # ------------------------------------------------------------
    u = rng.random(sims)

    z_min_blow = rng.standard_normal(sims)
    z_min_close = rng.standard_normal(sims)
    z_rate = rng.standard_normal(sims)

    blow_mask = u < q
    close_mask = ~blow_mask

    minutes = np.empty(sims, dtype=float)
    minutes[blow_mask] = mu_blow + sd_blow * z_min_blow[blow_mask]
    minutes[close_mask] = mu_close + sd_close * z_min_close[close_mask]
    minutes = np.clip(minutes, 0.0, 48.0)

    rate_raw = np.clip(rate_mu_raw + rate_sd_raw * z_rate, 0.0, None)
    rate_role = np.clip(rate_mu_role + rate_sd_role * z_rate, 0.0, None)

    stat_raw = rate_raw * minutes
    stat_role = rate_role * minutes

    if direction == "OVER":
        hits_raw = stat_raw > line
        hits_role = stat_role > line
    elif direction == "UNDER":
        hits_raw = stat_raw < line
        hits_role = stat_role < line
    else:
        raise ValueError(f"Unknown direction: {direction} (expected OVER or UNDER)")

    p_raw = _smoothed_prob(hits_raw)
    p_role = _smoothed_prob(hits_role)

    # Close-only channel for fragility (same idea)
    z_min_close_only = rng.standard_normal(sims)
    z_rate_close_only = rng.standard_normal(sims)

    minutes_close_only = np.clip(mu_close + sd_close * z_min_close_only, 0.0, 48.0)

    rate_raw_close = np.clip(rate_mu_raw + rate_sd_raw * z_rate_close_only, 0.0, None)
    rate_role_close = np.clip(rate_mu_role + rate_sd_role * z_rate_close_only, 0.0, None)

    stat_raw_close = rate_raw_close * minutes_close_only
    stat_role_close = rate_role_close * minutes_close_only

    if direction == "OVER":
        hits_close_raw = stat_raw_close > line
        hits_close_role = stat_role_close > line
    else:
        hits_close_raw = stat_raw_close < line
        hits_close_role = stat_role_close < line

    p_close_raw = _smoothed_prob(hits_close_raw)
    p_close_role = _smoothed_prob(hits_close_role)

    # ------------------------------------------------------------
    # ✅ PATCH: minutes_s + apply blowout adjuster (B, non-canceling)
    # ------------------------------------------------------------
    ms = row.get("minutes_s", None)
    try:
        minutes_s = float(ms) if ms is not None else float(minutes_sensitivity(stat_u))
    except Exception:
        minutes_s = float(minutes_sensitivity(stat_u))

    # Core leg probability gets full blowout sensitivity
    p_adj = float(
        adjust_probability_for_blowout(
            p_raw=float(p_role),
            blowout_risk=float(q),
            sens=float(minutes_s),
            direction=str(direction),
        )
    )

    # Key change for B: close channel is LESS blowout-sensitive to avoid cancellation
    # Knob carried via role_cfg; default matches legacy behavior.
    try:
        close_sens_mult = float((role_cfg or {}).get("close_sens_mult", 0.35))
    except Exception:
        close_sens_mult = 0.35

    minutes_s_close = float(minutes_s) * close_sens_mult

    p_close_adj = float(
        adjust_probability_for_blowout(
            p_raw=float(p_close_role),
            blowout_risk=float(q),
            sens=float(minutes_s_close),
            direction=str(direction),
        )
    )

    # Safety clamp
    p_adj = float(np.clip(p_adj, 0.0, 1.0))
    p_close_adj = float(np.clip(p_close_adj, 0.0, 1.0))

    # Experimental: directional UNDER support for fragile / blowout-sensitive legs
    frag_under_stats = {"PTS", "PRA", "PA", "PR", "RA", "REB"}
    frag_under_mult = 1.010
    frag_under_frag_min = 0.05
    frag_under_q_min = 0.10

    fragility_pre = float(max(0.0, p_close_adj - p_adj))
    frag_under_eligible = (
        str(direction).upper() == "UNDER"
        and str(stat_u).upper() in frag_under_stats
        and float(q) >= frag_under_q_min
        and fragility_pre >= frag_under_frag_min
    )
    p_adj_pre_frag_under = float(p_adj)

    if frag_under_eligible:
        p_adj = float(np.clip(p_adj * frag_under_mult, 0.0, 1.0))

    # Fragility (B): adjusted close vs adjusted p
    eps = 1e-9
    frag = 0.0 if p_close_adj <= eps else max(0.0, (p_close_adj - p_adj) / p_close_adj)
    frag_abs = max(0.0, p_close_adj - p_adj)

    out: dict[str, Any] = {
        # Core outputs
        "p": float(p_raw),
        "p_role": float(p_role),
        "p_adj": float(p_adj),

        # Close-only outputs (adjusted channel is what B uses)
        "p_close": float(p_close_adj),
        "p_close_raw": float(p_close_raw),
        "p_close_role": float(p_close_role),  # helpful for telemetry/debugging

        # Blowout + minutes diagnostics
        "spread": float(spread),
        "q_blowout": float(q),
        "minutes_s": float(minutes_s),
        "minutes_s_close": float(minutes_s_close),  # ✅ new: shows reduced close sensitivity
        "is_star": bool(is_star),

        # Fragility (aligned to adjusted channel)
        "fragility": float(frag),
        "fragility_abs": float(frag_abs),
        "p_adj_pre_frag_under": float(p_adj_pre_frag_under),
        "frag_under_mult": float(frag_under_mult if frag_under_eligible else 1.0),
        "frag_under_applied": bool(frag_under_eligible),

        # Stat summary diagnostics
        "min_mean": float(s.get("min_mean", 0.0)),
        "min_std": float(s.get("min_std", 0.0)),
        "rate_mean": float(base_rate_mu),
        "rate_std": float(s.get("rate_std", 0.0)),

        # Context diagnostics
        "rate_mean_ctx": float(rate_mu_role),
        "rate_std_ctx": float(rate_sd_role),
        "role_ctx_mult": float(role_mult),
        "role_ctx_mult_raw": float(role_mult_raw),
        "role_ctx_sigma_mult": float(role_sigma_mult),
        "role_ctx_reason": str(role_reason),

        "games_used": int(s.get("games", 0)),
    }

    if isinstance(role_debug, dict):
        import json

        # Always set outs_used from the dict if present; else infer from outs list
        if "outs_used" in role_debug:
            out["role_ctx_outs_used"] = int(role_debug.get("outs_used") or 0)
        elif "outs" in role_debug:
            v = role_debug.get("outs")
            out["role_ctx_outs_used"] = int(len(v)) if isinstance(v, (list, tuple)) else 0
        else:
            out["role_ctx_outs_used"] = 0

        for k in [
            "outs",
            "outs_used",
            "bump",
            "team",
            "stat",
            "min_games",
            "by_out",
            "components",
            "component_mults",
            "component_reasons",
        ]:
            if k not in role_debug:
                continue

            v = role_debug[k]

            # Serialize list/dict structures so CSV never gets NaN/object leakage
            if k in ("outs", "by_out", "components", "component_mults", "component_reasons"):
                # Normalize None -> empty list/dict for known structured fields
                if v is None:
                    v = [] if k in ("outs", "components", "component_mults", "component_reasons") else {}
                try:
                    out[f"role_ctx_{k}"] = json.dumps(v, ensure_ascii=False)
                except Exception:
                    out[f"role_ctx_{k}"] = "[]"
            else:
                out[f"role_ctx_{k}"] = v

    return out
from typing import Any, Iterable, Hashable

import re
import numpy as np
import pandas as pd

from Atlas.core.team_aliases import normalize_team_abbr

"""
Slip scoring helpers (extracted from LegacyEngine.optimize during Phase 7B).

Purpose
- Provide the exact legacy slip scoring behavior used by the slip builders.
- Keep pricing_engine behavior (atlas vs pp_kernel) unchanged.
"""

def _as_float(x: Any, default: float | None = None) -> float | None:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return default
        return float(x)
    except Exception:
        return default


# Helper: ensure an input is a Series (prevents float/None .fillna / .astype errors)
def _ensure_series(x: Any, index: pd.Index | None = None, default: Any = np.nan) -> pd.Series:
    if isinstance(x, pd.Series):
        return x
    if x is None:
        return pd.Series(default, index=index)
    # if scalar or array-like, create Series with given index if available
    try:
        return pd.Series(x, index=index)
    except Exception:
        return pd.Series([x] if index is None else [x] * len(index), index=index)


# Helper: convert dict keys to str to satisfy dict[str, Any] signatures
def _rec_keys_str(rec: dict[Hashable, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in rec.items()}

def _prod(xs: Iterable[float]) -> float:
    out = 1.0
    for v in xs:
        out *= float(v)
    return out


def _fmt_line(x: Any) -> str:
    v = _as_float(x, None)
    if v is None:
        return str(x).strip()
    return f"{v:g}"


def _is_over(r: pd.Series) -> bool:
    return str(r.get("direction", "")).strip().upper() == "OVER"


def _format_leg(r: pd.Series) -> str:
    player = str(r.get("player", "")).strip()
    direction = str(r.get("direction", "")).strip().upper()
    stat = str(r.get("stat", "")).strip().upper()
    line = _fmt_line(r.get("line", ""))
    tier = str(r.get("tier", "STANDARD")).strip().upper() or "STANDARD"
    pid = r.get("projection_id", "")
    try:
        pid_s = str(int(pid))
    except Exception:
        pid_s = str(pid).strip()
    return f"{player} {direction} {stat} {line} ({tier}) [id:{pid_s}]"


def _slip_key(rows: list[pd.Series]) -> str:
    parts = []
    for r in rows:
        pid = r.get("projection_id", "")
        if pd.isna(pid):
            pid = ""
        parts.append(str(pid))
    return "|".join(parts)


# -----------------------------
# Candidate builder
# -----------------------------

def _family(stat: Any) -> str:
    # Minimal safe implementation used by stat_family column.
    # Keeps behavior predictable for type-checkers (returns upper-stripped string).
    return str(stat).strip().upper()


def _pick_linear_prob_column(df: pd.DataFrame, *, prefer_calibrated: bool = True) -> str:
    """Return the probability column to use for candidate building.

    When ``prefer_calibrated`` is True, the current linear probability line is
    read from the upstream replay surface first so downstream selection stays
    aligned with the better-evaluated source when calibration lags.
    """
    if prefer_calibrated:
        order = ["p_cal", "p_for_cal", "p_role", "p", "p_eff", "p_combo", "p_adj", "p_close"]
    else:
        order = ["p_for_cal", "p_role", "p", "p_cal", "p_eff", "p_combo", "p_adj", "p_close"]

    for c in order:
        if c in df.columns:
            return c
    return ""


def build_candidates(scored: pd.DataFrame, pool_size: int = 250, *, prefer_calibrated_prob: bool = True) -> pd.DataFrame:
    if scored is None or len(scored) == 0:
        return pd.DataFrame()

    df = scored.copy()

    p_col = _pick_linear_prob_column(df, prefer_calibrated=prefer_calibrated_prob)

    if p_col is None:
        df["p_eff"] = 0.50
    else:
        df["p_eff"] = pd.to_numeric(df[p_col], errors="coerce").fillna(0.50).clip(0, 1)

    df["edge_score"] = df["p_eff"] - 0.5

    if "prop_key" not in df.columns:
        tier_series = _ensure_series(df.get("tier", "STANDARD"), index=df.index).astype(str).str.strip().str.upper()
        player_series = _ensure_series(df.get("player", ""), index=df.index).astype(str).str.strip()
        stat_series = _ensure_series(df.get("stat", ""), index=df.index).astype(str).str.strip().str.upper()
        line_num = pd.to_numeric(_ensure_series(df.get("line", pd.NA), index=df.index), errors="coerce")

        df["prop_key"] = (
            player_series
            + "|"
            + stat_series
            + "|"
            + line_num.astype(str)
            + "|"
            + tier_series.astype(str)
        )

    frag_col = None
    for c in ["fragility", "avg_fragility"]:
        if c in df.columns:
            frag_col = c
            break

    if frag_col is None:
        br = pd.to_numeric(_ensure_series(df.get("blowout_risk", 0.20), index=df.index), errors="coerce").fillna(0.20).clip(0, 1)
        ms = pd.to_numeric(_ensure_series(df.get("minutes_s", 0.60), index=df.index), errors="coerce").fillna(0.60).clip(0, 1)
        df["fragility"] = (0.60 * br + 0.40 * (1.0 - ms)).clip(0, 1)
    else:
        df["fragility"] = pd.to_numeric(_ensure_series(df[frag_col], index=df.index), errors="coerce").fillna(0.30).clip(0, 1)

    if "type" not in df.columns:
        df["type"] = _ensure_series(df.get("tier", "STANDARD"), index=df.index).astype(str).str.upper().str.strip()

    df["stat_family"] = _ensure_series(df.get("stat", ""), index=df.index).apply(_family)

    df = df.sort_values(["p_eff", "edge_score"], ascending=[False, False], na_position="last")
    pool_size = max(1, int(pool_size) if pool_size is not None else 250)
    return df.head(pool_size).reset_index(drop=True)


# -----------------------------
# Slip scoring (POWER ONLY)
# -----------------------------

def _score_slip(
    rows: list[pd.Series],
    n_legs: int,
    payout_power_mult: Any,
    *,
    pricing_engine: str = "atlas",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ps = [float(r.get("p_eff", 0.5)) for r in rows]
    # Use unclamped probability for hit_prob so winprob rankings differentiate slips
    ps_raw = [float(r.get("p_eff_raw", r.get("p_eff", 0.5))) for r in rows]
    hit_prob = _prod(ps_raw)

    # --- Same-game correlation adjustment (config-gated) ---
    corr_cfg = ((cfg or {}).get("slip_build", {}) or {}).get("correlation_adj", {}) if cfg else {}
    corr_enabled = bool(corr_cfg.get("enabled", False))
    if corr_enabled and len(rows) >= 2:
        same_team_pen = float(corr_cfg.get("same_team_penalty", 0.02) or 0.02)
        hedge_bonus = float(corr_cfg.get("hedge_bonus", 0.01) or 0.01)
        corr_mult = 1.0
        for i in range(len(rows)):
            ti = normalize_team_abbr(rows[i].get("team", rows[i].get("team_abbrev", "")))
            di = str(rows[i].get("direction", "")).strip().upper()
            for j in range(i + 1, len(rows)):
                tj = normalize_team_abbr(rows[j].get("team", rows[j].get("team_abbrev", "")))
                dj = str(rows[j].get("direction", "")).strip().upper()
                if not ti or not tj:
                    continue
                if ti == tj:
                    # Same team, same direction: positively correlated -> penalty
                    if di == dj:
                        corr_mult *= (1.0 - same_team_pen)
                    else:
                        # Same team, opposite direction: hedged -> slight bonus
                        corr_mult *= (1.0 + hedge_bonus)
        hit_prob = float(hit_prob * max(corr_mult, 0.5))

    atlas_power_mult = _as_float(payout_power_mult, None)
    pe = str(pricing_engine or "atlas").strip().lower()

    payout_mult = float(atlas_power_mult) if atlas_power_mult is not None else 0.0  # contract payout

    # Kernel pricing adjustment (separate from contract)
    kernel_mult = 1.0
    if atlas_power_mult is not None and pe == "pp_kernel":
        try:
            from .pp_pricing import load_kernel, power_multiplier
            kernel = load_kernel(cfg or {})
            legs = [_rec_keys_str(r.to_dict()) for r in rows]

            # IMPORTANT (Option A): kernel_mult must NOT include POWER_MULT
            kernel_mult = float(power_multiplier(base_mult=1.0, legs=legs, kernel=kernel))
        except Exception:
            kernel_mult = 1.0

    # Effective payout used for EV math
    payout_mult_eff = float(payout_mult) * float(kernel_mult)

    # EV uses the effective payout (same math as before, cleaner semantics)
    ev_mult = float(hit_prob * payout_mult_eff)

    avg_p = sum(ps) / len(ps) if ps else 0.0
    avg_frag = float(_ensure_series([r.get("fragility", 0.3) for r in rows]).astype(float).mean())
    min_p = min(ps) if ps else 0.0
    max_p = max(ps) if ps else 0.0
    min_p_raw = min(ps_raw) if ps_raw else min_p
    max_p_raw = max(ps_raw) if ps_raw else max_p

    return {
        "n_legs": int(n_legs),
        "legs": " | ".join([_format_leg(r) for r in rows]),
        "hit_prob": float(hit_prob),

        # ✅ shows the multiplier as a multiplier
        "payout_mult": float(payout_mult),
        "kernel_mult": float(kernel_mult),
        "payout_mult_eff": float(payout_mult_eff),

        # ✅ expected payout multiplier
        "ev_mult": float(ev_mult),

        # debug visibility
        "atlas_power_mult": float(atlas_power_mult) if atlas_power_mult is not None else None,
        "pricing_engine": pe,

        "avg_p": float(avg_p),
        "min_p": float(min_p),
        "max_p": float(max_p),
        "min_p_raw": float(min_p_raw),
        "max_p_raw": float(max_p_raw),
        "avg_fragility": float(avg_frag),
        "slip_key": _slip_key(rows),
    }


# -----------------------------
# Portfolio diversity (unchanged)
# -----------------------------

_ID_RE = re.compile(r"\[id:(\d+)\]")
_PLAYER_RE = re.compile(r"^(.*)\s+(OVER|UNDER)\s+", re.IGNORECASE)


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
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from Atlas.core.features import summarize_stat, get_player_window
from Atlas.core.minutes import adjust_probability_for_blowout, minutes_sensitivity
from Atlas.core.share_name_key import share_name_key

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
    Local alias for the shared canonical player join key.
    """
    return share_name_key(s)


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


def _market_usage_baseline(stat_u: str) -> float:
    """
    Atlas internal usage-dependence baseline.

    This is intentionally distinct from slip-builder family buckets. It is a
    basketball-facing proxy for how much a leg depends on sustained offensive
    burden if the game remains competitive.

    Notes:
    - This is a staging seam for fragility work. It does NOT yet change the
      default haircut math on its own.
    - Minutes sensitivity remains the hard base via Atlas.core.minutes.
    """
    stat = str(stat_u or '').upper().strip()
    if stat in {'PTS', 'PRA', 'PA', 'PR', 'RA'}:
        return 1.00
    if stat in {'AST'}:
        return 0.92
    if stat in {'FG3M', '3PM', 'THREES'}:
        return 0.88
    if stat in {'REB'}:
        return 0.78
    if stat in {'BLK', 'STL', 'STOCKS'}:
        return 0.70
    return 0.82


def _stat_specific_pressure_mult(stat_u: str, burden_ratio: float) -> float:
    """Conservative stat-specific pressure tier for usage-dependent fragility.

    The line-to-minutes burden should not mean the same thing for every market.
    High-usage scoring families should feel pressure sooner; rebounds/stocks
    should need more evidence before they are treated as usage-burden fragile.
    """
    stat = str(stat_u or '').upper().strip()

    if stat in {'PTS', 'PRA', 'PA', 'PR', 'RA'}:
        if burden_ratio >= 1.12:
            return 1.08
        if burden_ratio >= 0.98:
            return 1.04
        if burden_ratio >= 0.84:
            return 1.00
        return 0.97

    if stat in {'AST'}:
        if burden_ratio >= 1.10:
            return 1.07
        if burden_ratio >= 0.97:
            return 1.03
        if burden_ratio >= 0.84:
            return 1.00
        return 0.97

    if stat in {'FG3M', '3PM', 'THREES'}:
        if burden_ratio >= 1.15:
            return 1.06
        if burden_ratio >= 1.00:
            return 1.02
        if burden_ratio >= 0.86:
            return 1.00
        return 0.98

    if stat in {'REB'}:
        if burden_ratio >= 1.18:
            return 1.04
        if burden_ratio >= 1.02:
            return 1.01
        if burden_ratio >= 0.88:
            return 1.00
        return 0.99

    if stat in {'BLK', 'STL', 'STOCKS'}:
        if burden_ratio >= 1.20:
            return 1.03
        if burden_ratio >= 1.04:
            return 1.01
        if burden_ratio >= 0.90:
            return 1.00
        return 0.99

    if burden_ratio >= 1.15:
        return 1.05
    if burden_ratio >= 1.00:
        return 1.02
    if burden_ratio >= 0.86:
        return 1.00
    return 0.98



def _usage_dependence_proxy(
    stat_u: str,
    base_rate_mu: float,
    line: float,
    expected_minutes: float,
    usg_pct: float | None = None,
    ts_pct: float | None = None,
    sq: float | None = None,
    three_par: float | None = None,
    ftr: float | None = None,
    trb_pct: float | None = None,
    orb_pct: float | None = None,
    drb_pct: float | None = None,
    ast_pct: float | None = None,
    touches: float | None = None,
    ast_usg: float | None = None,
    box_creation: float | None = None,
    offensive_load: float | None = None,
    passer_rating: float | None = None,
) -> dict[str, float]:
    """
    Internal Atlas proxy for usage dependence.

    Atlas usage dependence is meant to capture offensive-burden reliance inside
    fragility, not generic player quality. The goal is conservative: strengthen
    fragility when a leg needs both a usage-heavy market family and a meaningful
    pace-to-line burden, without turning usage into a second global haircut.

    Inputs remain real-world-backed via the current stat window summary:
      - base_rate_mu: historical per-minute production for this market
      - expected_minutes: historical minutes expectation (competitive script)
      - line: the current prop line to clear

    Returns a compact debugable bundle so Atlas can inspect exactly how the
    usage proxy was formed without changing the stable probability corridor.
    """
    baseline = float(_market_usage_baseline(stat_u))

    try:
        mu = max(0.0, float(base_rate_mu))
    except Exception:
        mu = 0.0
    try:
        line_f = max(0.0, float(line))
    except Exception:
        line_f = 0.0
    try:
        exp_min = max(1.0, float(expected_minutes))
    except Exception:
        exp_min = 1.0

    # Producer tier: a light proxy for sustained offensive burden per minute.
    if mu >= 1.10:
        producer_mult = 1.03
    elif mu >= 0.85:
        producer_mult = 1.01
    elif mu >= 0.60:
        producer_mult = 1.00
    else:
        producer_mult = 0.99

    # Pace-to-line pressure: how much per-minute output the line implicitly asks
    # the player to sustain in a competitive game script.
    target_rate = line_f / exp_min
    burden_ratio = target_rate / max(mu, 1e-6) if mu > 0 else 1.0
    pressure_mult = _stat_specific_pressure_mult(stat_u, burden_ratio)

    def _to_float(value: float | None) -> float:
        try:
            return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])
        except Exception:
            return float("nan")

    def _bounded_mult(value: float, *, center: float, scale: float, weight: float, clamp: tuple[float, float] = (0.97, 1.03)) -> tuple[float, float]:
        if pd.isna(value):
            return 0.0, 1.0
        scaled = float(np.tanh((float(value) - center) / max(scale, 1e-6)))
        mult = float(np.clip(1.0 + (weight * scaled), clamp[0], clamp[1]))
        return scaled, mult

    usg = _to_float(usg_pct)
    ts = _to_float(ts_pct)
    sq_val = _to_float(sq)
    three_par_val = _to_float(three_par)
    ftr_val = _to_float(ftr)
    trb_val = _to_float(trb_pct)
    orb_val = _to_float(orb_pct)
    drb_val = _to_float(drb_pct)
    ast_val = _to_float(ast_pct)
    touches_val = _to_float(touches)
    ast_usg_val = _to_float(ast_usg)
    box_creation_val = _to_float(box_creation)
    offensive_load_val = _to_float(offensive_load)
    passer_rating_val = _to_float(passer_rating)

    stat_norm = str(stat_u or "").upper().strip()
    if stat_norm in {"PTS", "PRA", "PA", "PR", "RA"}:
        usg_weight = 0.018
    elif stat_norm in {"AST"}:
        usg_weight = 0.012
    elif stat_norm in {"FG3M", "3PM", "THREES"}:
        usg_weight = 0.008
    else:
        usg_weight = 0.010

    if pd.isna(usg):
        usg_scaled = 0.0
        usg_mult = 1.0
    else:
        usg_scaled = float(np.tanh((float(usg) - 26.5) / 12.0))
        usg_mult = float(np.clip(1.0 + (usg_weight * usg_scaled), 0.99, 1.01))

    scoring_ts_scaled, scoring_ts_mult = _bounded_mult(ts, center=58.0, scale=10.0, weight=0.006, clamp=(0.985, 1.015))
    scoring_sq_scaled, scoring_sq_mult = _bounded_mult(sq_val, center=50.0, scale=22.0, weight=0.006, clamp=(0.985, 1.015))
    scoring_ftr_scaled, scoring_ftr_mult = _bounded_mult(ftr_val, center=26.0, scale=18.0, weight=0.005, clamp=(0.985, 1.015))

    threes_three_par_scaled, threes_three_par_mult = _bounded_mult(three_par_val, center=40.0, scale=22.0, weight=0.014)
    threes_sq_scaled, threes_sq_mult = _bounded_mult(sq_val, center=55.0, scale=22.0, weight=0.010)
    threes_ts_scaled, threes_ts_mult = _bounded_mult(ts, center=58.0, scale=10.0, weight=0.008)

    rebound_trb_scaled, rebound_trb_mult = _bounded_mult(trb_val, center=13.0, scale=8.0, weight=0.014)
    rebound_orb_scaled, rebound_orb_mult = _bounded_mult(orb_val, center=4.0, scale=4.0, weight=0.010)
    rebound_drb_scaled, rebound_drb_mult = _bounded_mult(drb_val, center=10.0, scale=6.0, weight=0.010)

    assist_ast_scaled, assist_ast_mult = _bounded_mult(ast_val, center=18.0, scale=12.0, weight=0.012)
    assist_touches_scaled, assist_touches_mult = _bounded_mult(touches_val, center=55.0, scale=25.0, weight=0.010)
    assist_ast_usg_scaled, assist_ast_usg_mult = _bounded_mult(ast_usg_val, center=0.85, scale=0.35, weight=0.012)
    assist_bc_scaled, assist_bc_mult = _bounded_mult(box_creation_val, center=8.0, scale=4.0, weight=0.012)
    assist_load_scaled, assist_load_mult = _bounded_mult(offensive_load_val, center=20.0, scale=10.0, weight=0.008)
    assist_pr_scaled, assist_pr_mult = _bounded_mult(passer_rating_val, center=5.0, scale=2.0, weight=0.012)

    scoring_mult = 1.0
    if stat_norm == "PTS":
        scoring_mult *= usg_mult
        scoring_mult *= scoring_ts_mult
        scoring_mult *= scoring_sq_mult
        scoring_mult *= scoring_ftr_mult

    assist_mult = 1.0
    if stat_norm in {"AST", "PA", "PRA", "RA"}:
        assist_mult *= assist_ast_mult
        assist_mult *= assist_touches_mult
        assist_mult *= assist_ast_usg_mult
        assist_mult *= assist_bc_mult
        assist_mult *= assist_load_mult
        assist_mult *= assist_pr_mult

    rebound_mult = 1.0
    if stat_norm in {"REB", "PR", "PRA", "RA"}:
        rebound_mult *= rebound_trb_mult
        rebound_mult *= rebound_orb_mult
        rebound_mult *= rebound_drb_mult

    threes_mult = 1.0
    if stat_norm in {"FG3M", "3PM", "THREES"}:
        threes_mult *= threes_three_par_mult
        threes_mult *= threes_sq_mult
        threes_mult *= threes_ts_mult

    # Current payload coverage is reliable for scoring/rebound families but not
    # yet for the assist-family glossary fields. Keep assist/threes telemetry
    # visible while only letting scoring/rebound shape the live usage route.
    family_metric_mult = float(np.clip(scoring_mult * rebound_mult, 0.94, 1.06))

    usage_dep_raw = baseline * producer_mult * pressure_mult * family_metric_mult
    usage_dep = float(np.clip(usage_dep_raw, 0.75, 1.10))

    return {
        "usage_dep": usage_dep,
        "usage_baseline": float(baseline),
        "usage_producer_mult": float(producer_mult),
        "usage_pressure_mult": float(pressure_mult),
        "usage_usg_pct": None if pd.isna(usg) else float(usg),
        "usage_usg_scaled": float(usg_scaled),
        "usage_usg_mult": float(usg_mult),
        "usage_scoring_mult": float(scoring_mult),
        "usage_assist_mult": float(assist_mult),
        "usage_rebound_mult": float(rebound_mult),
        "usage_threes_mult": float(threes_mult),
        "usage_metric_mult": float(family_metric_mult),
        "usage_ts_scaled": float(scoring_ts_scaled),
        "usage_sq_scaled": float(scoring_sq_scaled),
        "usage_ftr_scaled": float(scoring_ftr_scaled),
        "usage_three_par_scaled": float(threes_three_par_scaled),
        "usage_trb_scaled": float(rebound_trb_scaled),
        "usage_ast_scaled": float(assist_ast_scaled),
        "usage_touches_scaled": float(assist_touches_scaled),
        "usage_ast_usg_scaled": float(assist_ast_usg_scaled),
        "usage_bc_scaled": float(assist_bc_scaled),
        "usage_load_scaled": float(assist_load_scaled),
        "usage_pr_scaled": float(assist_pr_scaled),
        "usage_target_rate": float(target_rate),
        "usage_burden_ratio": float(burden_ratio),
        "usage_dep_raw": float(usage_dep_raw),
    }


def _role_metrics_adjustment(row: Any, *, role_ctx_on_override: bool | None = None) -> tuple[float, dict[str, float]]:
    """Convert parsed role-metrics columns into a weak bounded prior."""
    weight_scale = 0.04
    role_ctx_on = False
    if role_ctx_on_override is None:
        try:
            if hasattr(row, "get"):
                role_ctx_on = float(pd.to_numeric(pd.Series([row.get("role_ctx_outs_used", 0)]), errors="coerce").iloc[0]) > 0.0
            elif isinstance(row, dict):
                role_ctx_on = float(pd.to_numeric(pd.Series([row.get("role_ctx_outs_used", 0)]), errors="coerce").iloc[0]) > 0.0
            else:
                role_ctx_on = float(pd.to_numeric(pd.Series([getattr(row, "role_ctx_outs_used", 0)]), errors="coerce").iloc[0]) > 0.0
        except Exception:
            role_ctx_on = False
    else:
        role_ctx_on = bool(role_ctx_on_override)

    if not role_ctx_on:
        return 1.0, {"score": 0.0, "mult": 1.0, "gated": 1.0}

    def _get(name: str) -> float:
        try:
            if hasattr(row, "get"):
                value = row.get(name, None)
            elif isinstance(row, dict):
                value = row.get(name, None)
            else:
                value = getattr(row, name, None)
            return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])
        except Exception:
            return float("nan")

    components: dict[str, float] = {}

    def _add(name: str, raw_value: float, scale: float, weight: float) -> None:
        if pd.isna(raw_value):
            return
        components[f"{name}_raw"] = float(raw_value)
        components[f"{name}_scaled"] = float(np.tanh(float(raw_value) / max(scale, 1e-6)))
        components[f"{name}_weighted"] = float(weight * components[f"{name}_scaled"])

    _add("cpm", _get("role_metrics_cpm"), 5.0, 0.010 * weight_scale)
    _add("vorp", _get("role_metrics_vorp"), 5.0, 0.008 * weight_scale)
    _add("drip", _get("role_metrics_drip_total"), 9.0, 0.006 * weight_scale)
    _add("darko", _get("role_metrics_darko"), 9.0, 0.003 * weight_scale)

    score = float(sum(v for k, v in components.items() if k.endswith("_weighted")))
    score = float(np.clip(score, -0.008, 0.008))
    mult = float(np.clip(1.0 + score, 0.992, 1.008))
    components["score"] = score
    components["mult"] = mult
    return mult, components



def _bounded_role_rate_multiplier(
    role_mult: float,
    role_metrics_mult: float,
    cfg: dict[str, Any] | None,
) -> tuple[float, float, float, float, float]:
    """Apply a conservative corridor to the combined role-rate uplift."""
    try:
        role_rate_clamp_lo = float((cfg or {}).get("role_rate_clamp_lo", 0.94))
    except Exception:
        role_rate_clamp_lo = 0.94
    try:
        role_rate_clamp_hi = float((cfg or {}).get("role_rate_clamp_hi", 1.08))
    except Exception:
        role_rate_clamp_hi = 1.08
    try:
        role_rate_softcap_k = float((cfg or {}).get("role_rate_softcap_k", 1.10))
    except Exception:
        role_rate_softcap_k = 1.10

    role_rate_clamp_lo = float(np.clip(role_rate_clamp_lo, 0.80, 1.0))
    role_rate_clamp_hi = float(np.clip(role_rate_clamp_hi, 1.0, 1.20))
    role_rate_softcap_k = float(max(0.01, role_rate_softcap_k))

    role_rate_mult_raw = float(max(0.0, float(role_mult)) * max(0.0, float(role_metrics_mult)))
    if role_rate_mult_raw >= 1.0 and role_rate_clamp_hi > 1.0:
        cap_bump = float(role_rate_clamp_hi - 1.0)
        bump_raw = float(max(0.0, role_rate_mult_raw - 1.0))
        bump_soft = float(
            cap_bump
            * (1.0 - float(np.exp(-role_rate_softcap_k * bump_raw / max(1e-12, cap_bump))))
        )
        role_rate_mult = 1.0 + bump_soft
    elif role_rate_mult_raw < 1.0 and role_rate_clamp_lo < 1.0:
        cap_drop = float(1.0 - role_rate_clamp_lo)
        drop_raw = float(max(0.0, 1.0 - role_rate_mult_raw))
        drop_soft = float(
            cap_drop
            * (1.0 - float(np.exp(-role_rate_softcap_k * drop_raw / max(1e-12, cap_drop))))
        )
        role_rate_mult = 1.0 - drop_soft
    else:
        role_rate_mult = role_rate_mult_raw

    role_rate_mult = float(np.clip(role_rate_mult, role_rate_clamp_lo, role_rate_clamp_hi))
    return (
        float(role_rate_mult_raw),
        float(role_rate_mult),
        float(role_rate_clamp_lo),
        float(role_rate_clamp_hi),
        float(role_rate_softcap_k),
    )




def _directional_fragility_gap(direction: str, frag_gap_usage: float) -> float:
    """Atlas fragility is currently an OVER-side vulnerability signal only.

    Conservative rule for this pass:
      - OVER rows retain the full usage-aware fragility gap
      - UNDER rows do not export directional fragility yet

    This keeps fragility from acting like a global symmetric anti-leg force
    while preserving the stable p_role -> p_adj corridor. Under-side liveliness
    can be surfaced later via a separate, explicitly-audited seam.
    """
    return float(frag_gap_usage) if str(direction).upper() == "OVER" else 0.0


def _usage_risk_gate(q_blowout: float) -> float:
    """Conservative competitive-risk gate for usage-driven fragility.

    Usage should matter most when real script danger is present. Tight or only
    mildly dangerous games should not materially inflate fragility for strong
    star overs.

    Gate shape:
    - q <= 0.14: no usage inflation
    - q >= 0.32: full usage effect available
      - in between: linear ramp
    """
    try:
        q = float(q_blowout)
    except Exception:
        q = 0.0
    if q <= 0.14:
        return 0.0
    if q >= 0.32:
        return 1.0
    return float((q - 0.14) / 0.18)


def _usage_effect_cap(stat_u: str) -> float:
    """Small stat-aware ceiling for effective usage-driven fragility.

    This keeps the seam conservative even when the raw usage proxy runs hot.
    """
    stat = str(stat_u or '').upper().strip()
    if stat in {'PTS', 'PRA', 'PA', 'PR', 'RA'}:
        return 1.06
    if stat in {'AST'}:
        return 1.04
    if stat in {'FG3M', '3PM', 'THREES'}:
        return 1.03
    if stat in {'REB'}:
        return 1.02
    if stat in {'BLK', 'STL', 'STOCKS'}:
        return 1.01
    return 1.03


def _soft_ramp(value: float | None, start: float, full: float) -> float:
    """Linear ramp that turns on at start and is full by full."""
    try:
        val = float(value)
    except Exception:
        return 0.0
    lo = float(start)
    hi = float(full)
    if hi <= lo:
        return 1.0 if val >= hi else 0.0
    if val <= lo:
        return 0.0
    if val >= hi:
        return 1.0
    return float((val - lo) / (hi - lo))


def _soft_ramp_inverse(value: float | None, zero_at: float, full_at: float) -> float:
    """Inverse linear ramp that is full at low values and zero at high values."""
    try:
        val = float(value)
    except Exception:
        return 0.0
    hi = float(zero_at)
    lo = float(full_at)
    if hi <= lo:
        return 1.0 if val <= lo else 0.0
    if val >= hi:
        return 0.0
    if val <= lo:
        return 1.0
    return float((hi - val) / (hi - lo))


def _competitive_usage_bonus(
    *,
    stat_u: str,
    direction: str,
    usg_pct: float | None,
    fragility: float,
    q_blowout: float,
    headroom: float,
    cfg: dict[str, Any] | None = None,
) -> tuple[float, dict[str, float]]:
    """Small bonus for high-usage competitive-script legs.

    This is the counterpart to usage-driven fragility:
    - high-usage overs in dangerous scripts can be more fragile
    - high-usage overs in tight, low-fragility scripts can earn a small bump

    The bump is deliberately conservative:
    - OVER only
    - scoring/creator families only
    - gated by real usage, low blowout risk, and low fragility
    - capped by available close-channel headroom
    """
    stat = str(stat_u or '').upper().strip()
    direction_u = str(direction or '').upper().strip()
    eligible_stats = {'PTS', 'PRA', 'PA', 'PR', 'AST'}

    try:
        headroom_f = max(0.0, float(headroom))
    except Exception:
        headroom_f = 0.0

    settings = cfg or {}
    usage_min = float(settings.get('competitive_usage_usg_min', 27.0))
    usage_full = float(settings.get('competitive_usage_usg_full', 33.0))
    frag_zero = float(settings.get('competitive_usage_frag_max', 0.12))
    frag_full = float(settings.get('competitive_usage_frag_full', 0.04))
    q_zero = float(settings.get('competitive_usage_q_max', 0.18))
    q_full = float(settings.get('competitive_usage_q_full', 0.08))
    max_bump = max(0.0, float(settings.get('competitive_usage_max_bump', 0.006)))

    usage_gate = _soft_ramp(usg_pct, usage_min, usage_full)
    frag_gate = _soft_ramp_inverse(fragility, frag_zero, frag_full)
    tight_gate = _soft_ramp_inverse(q_blowout, q_zero, q_full)
    total_gate = float(usage_gate * frag_gate * tight_gate)

    eligible = direction_u == 'OVER' and stat in eligible_stats and headroom_f > 0.0
    uncapped_bonus = float(max_bump * total_gate) if eligible else 0.0
    applied_bonus = float(min(headroom_f, uncapped_bonus)) if eligible else 0.0

    return applied_bonus, {
        'eligible': 1.0 if eligible else 0.0,
        'usage_gate': float(usage_gate),
        'frag_gate': float(frag_gate),
        'tight_gate': float(tight_gate),
        'total_gate': float(total_gate),
        'max_bump': float(max_bump),
        'headroom': float(headroom_f),
        'bonus_uncapped': float(uncapped_bonus),
        'bonus_applied': float(applied_bonus),
    }

def _fragility_root_inputs(row: pd.Series, stat_u: str, base_rate_mu: float, line: float, expected_minutes: float) -> tuple[float, dict[str, float]]:
    """
    Return Atlas fragility root inputs:
      - minutes_s: hard base from legacy minutes sensitivity seam
      - usage_debug: internal usage-dependence proxy bundle for fragility only

    This keeps the old minutes-first spirit explicit while giving the current
    kernel a dedicated seam for usage-dependent fragility.

    Role-context remains upstream in p_role and is intentionally not folded
    into this usage proxy.
    """
    ms = row.get('minutes_s', None)
    try:
        minutes_s = float(ms) if ms is not None else float(minutes_sensitivity(stat_u))
    except Exception:
        minutes_s = float(minutes_sensitivity(stat_u))

    def _row_metric(name: str) -> float | None:
        try:
            raw = row.get(name, None)
        except Exception:
            raw = None
        value = pd.to_numeric(pd.Series([raw]), errors='coerce').iloc[0]
        return None if pd.isna(value) else float(value)

    usage_debug = _usage_dependence_proxy(
        stat_u=stat_u,
        base_rate_mu=base_rate_mu,
        line=line,
        expected_minutes=expected_minutes,
        usg_pct=_row_metric('role_metrics_usg_pct'),
        ts_pct=_row_metric('role_metrics_ts_pct'),
        sq=_row_metric('role_metrics_sq'),
        three_par=_row_metric('role_metrics_three_par'),
        ftr=_row_metric('role_metrics_ftr'),
        trb_pct=_row_metric('role_metrics_trb_pct'),
        orb_pct=_row_metric('role_metrics_orb_pct'),
        drb_pct=_row_metric('role_metrics_drb_pct'),
        ast_pct=_row_metric('role_metrics_ast_pct'),
        touches=_row_metric('role_metrics_touches'),
        ast_usg=_row_metric('role_metrics_ast_usg'),
        box_creation=_row_metric('role_metrics_bc'),
        offensive_load=_row_metric('role_metrics_load'),
        passer_rating=_row_metric('role_metrics_pr'),
    )
    return float(minutes_s), usage_debug


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
        candidates: list[Path] = []

        strict_replay = (os.environ.get("ATLAS_STRICT_REPLAY") or "").strip() == "1"

        env_status = os.environ.get("ATLAS_IAEL_STATUS_PATH")
        if env_status:
            candidates.append(Path(env_status))

        if strict_replay and not candidates:
            raise RuntimeError("Strict replay requires ATLAS_IAEL_STATUS_PATH")

        env_out = os.environ.get("ATLAS_OUT_DIR")
        if env_out:
            candidates.append(Path(env_out) / "dashboard" / "status_latest.json")

        if not strict_replay:
            candidates.append(Path("data/output/dashboard/status_latest.json"))

        j = None
        for p in candidates:
            if not p.exists():
                continue
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                continue

        if not isinstance(j, dict):
            return pd.DataFrame()

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


def _apply_under_relief(
    *,
    p_role: float,
    p_adj: float,
    direction: str,
    stat_u: str,
    q: float,
    cfg: dict[str, Any] | None,
) -> tuple[float, bool, float, float, float, float]:
    under_relief_stats = {"PTS", "PRA", "PA", "PR", "RA", "REB", "AST", "FGM", "FG3M"}
    try:
        under_relief_factor = float((cfg or {}).get("under_relief_factor", 0.10))
    except Exception:
        under_relief_factor = 0.10
    under_relief_factor = float(np.clip(under_relief_factor, 0.0, 1.0))
    try:
        under_relief_haircut_min = float((cfg or {}).get("under_relief_haircut_min", 0.05))
    except Exception:
        under_relief_haircut_min = 0.05
    try:
        under_relief_q_min = float((cfg or {}).get("under_relief_q_min", 0.10))
    except Exception:
        under_relief_q_min = 0.10

    under_relief_haircut_min = float(max(0.0, under_relief_haircut_min))
    under_relief_q_min = float(max(0.0, under_relief_q_min))

    p_adj_pre_under_relief = float(p_adj)
    under_relief_haircut = max(0.0, float(p_role) - float(p_adj_pre_under_relief))

    under_relief_eligible = (
        str(direction).upper() == "UNDER"
        and str(stat_u).upper() in under_relief_stats
        and float(q) >= under_relief_q_min
        and float(under_relief_haircut) >= under_relief_haircut_min
    )

    if under_relief_eligible:
        # under_relief_factor is the retained share of the haircut.
        haircut_relief = float(under_relief_haircut) * under_relief_factor
        p_adj = float(np.clip(p_adj_pre_under_relief + haircut_relief, 0.0, 1.0))

    return (
        float(p_adj),
        bool(under_relief_eligible),
        float(under_relief_haircut),
        float(under_relief_factor),
        float(under_relief_haircut_min),
        float(under_relief_q_min),
    )


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

    projected_minutes_raw = row.get("role_metrics_minutes_projection", row.get("minutes_projection", None)) if hasattr(row, "get") else None
    projected_minutes = pd.to_numeric(pd.Series([projected_minutes_raw]), errors="coerce").iloc[0]
    projected_minutes_val = float(projected_minutes) if pd.notna(projected_minutes) else float("nan")

    role_metrics_mult = 1.0
    role_metrics_debug: dict[str, float] = {}

    is_star = float(projected_minutes_val if pd.notna(projected_minutes) else float(s.get("min_mean", 0.0))) >= 33.0
    minute_drop = float(star_minute_drop if is_star else role_minute_drop)

    q = blowout_probability(spread_mean=spread, threshold=blowout_threshold, sd=spread_sd)

    mu_close = max(0.0, float(projected_minutes_val if pd.notna(projected_minutes) else float(s.get("min_mean", 0.0))))
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
                total_bump = float(1.0 - float(np.prod(1.0 - bumps)))
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

    role_ctx_outs_used_for_metrics = 0
    if isinstance(role_debug, dict):
        try:
            role_ctx_outs_used_for_metrics = int(role_debug.get("outs_used") or 0)
        except Exception:
            role_ctx_outs_used_for_metrics = 0

    try:
        role_metrics_mult, role_metrics_debug = _role_metrics_adjustment(
            row,
            role_ctx_on_override=role_ctx_outs_used_for_metrics > 0,
        )
    except Exception:
        role_metrics_mult = 1.0
        role_metrics_debug = {}

    # RAW channel parameters (no ctx)
    rate_mu_raw = base_rate_mu
    rate_sd_raw = rate_sd_base

    # Role-context channel parameters (ctx applied)
    rate_mu_role_mult_raw, rate_mu_role_mult, rate_mu_role_clamp_lo, rate_mu_role_clamp_hi, rate_mu_role_softcap_k = _bounded_role_rate_multiplier(
        role_mult=role_mult,
        role_metrics_mult=role_metrics_mult,
        cfg=cfg,
    )
    rate_mu_role_raw = base_rate_mu * rate_mu_role_mult_raw
    rate_mu_role = base_rate_mu * rate_mu_role_mult
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
    # Atlas fragility roots: legacy minutes base + staged usage proxy
    # ------------------------------------------------------------
    minutes_s, usage_debug = _fragility_root_inputs(
        row=row,
        stat_u=stat_u,
        base_rate_mu=base_rate_mu,
        line=line,
        expected_minutes=mu_close,
    )
    usage_dep = float(usage_debug.get("usage_dep", 1.0))
    usage_dep_cap = _usage_effect_cap(stat_u)
    usage_dep_capped = float(np.clip(usage_dep, 0.60, usage_dep_cap))
    usage_risk_gate = _usage_risk_gate(q)
    usage_dep_eff = 1.0 + ((usage_dep_capped - 1.0) * usage_risk_gate)

    # Blowout sensitivity is direction-aware:
    # - starter-like rows (role-active or high-minute) get a softer UNDER haircut
    #   and a slightly harsher OVER haircut
    # - bench-like rows get the opposite small tilt
    # This keeps the blowout seam aligned with the basketball intuition: in a
    # blowout, starters are more likely to lose 4Q run, while bench overs can
    # benefit from garbage-time minutes.
    under_blowout_sens_stats = {"PTS", "PRA", "PA", "PR", "RA"}
    under_blowout_sens_q_min = 0.15
    try:
        blowout_role_step = float((role_cfg or {}).get("blowout_role_step", 0.01))
    except Exception:
        blowout_role_step = 0.01
    blowout_role_step = float(max(0.0, blowout_role_step))

    def _role_ctx_blowout_sens_mult(direction: str, outs_used: int, minutes_s_val: float) -> float:
        outs_i = max(0, int(outs_used))
        minutes_f = float(minutes_s_val)
        is_role_active = outs_i > 0
        is_starter_like = is_role_active or minutes_f >= 0.55
        is_bench_like = (not is_role_active) and minutes_f <= 0.45

        base = 0.75
        if str(direction).upper() == "UNDER":
            if is_starter_like:
                return float(np.clip(base - blowout_role_step, 0.55, 0.90))
            if is_bench_like:
                return float(np.clip(base + blowout_role_step, 0.55, 0.90))
        elif str(direction).upper() == "OVER":
            if is_starter_like:
                return float(np.clip(base + blowout_role_step, 0.55, 0.90))
            if is_bench_like:
                return float(np.clip(base - blowout_role_step, 0.55, 0.90))
        return base

    role_debug_obj = locals().get("role_debug")
    role_ctx_outs_used_early = 0
    if isinstance(role_debug_obj, dict):
        try:
            role_ctx_outs_used_early = int(role_debug_obj.get("outs_used") or 0)
        except Exception:
            role_ctx_outs_used_early = 0

    blowout_sens_mult = _role_ctx_blowout_sens_mult(str(direction), role_ctx_outs_used_early, float(minutes_s))

    under_blowout_sens_eligible = (
        str(direction).upper() == "UNDER"
        and str(stat_u).upper() in under_blowout_sens_stats
        and float(q) >= under_blowout_sens_q_min
    )
    minutes_s_blowout = (
        float(minutes_s) * float(blowout_sens_mult)
        if under_blowout_sens_eligible or str(direction).upper() == "OVER"
        else float(minutes_s)
    )
    under_blowout_sens_mult = float(blowout_sens_mult)

    p_adj = float(
        adjust_probability_for_blowout(
            p_raw=float(p_role),
            blowout_risk=float(q),
            sens=float(minutes_s_blowout),
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
        )
    )

    # Safety clamp
    p_adj = float(np.clip(p_adj, 0.0, 1.0))
    p_close_adj = float(np.clip(p_close_adj, 0.0, 1.0))
    # Experimental: reduced blowout haircut for tighter qualifying UNDER legs.
    # under_relief_factor is the retained share of the haircut, so 0.10 keeps
    # the adjustment tight while still allowing a small relief.
    p_adj_pre_under_relief = float(p_adj)
    (
        p_adj,
        under_relief_eligible,
        under_relief_haircut,
        under_relief_factor,
        under_relief_haircut_min,
        under_relief_q_min,
    ) = _apply_under_relief(
        p_role=float(p_role),
        p_adj=float(p_adj_pre_under_relief),
        direction=str(direction),
        stat_u=str(stat_u),
        q=float(q),
        cfg=cfg,
    )

    frag_gap_core_pre_bonus = max(0.0, p_close_adj - p_adj)
    frag_gap_usage_pre_bonus = float(frag_gap_core_pre_bonus) * float(usage_dep_eff)
    frag_gap_dir_pre_bonus = _directional_fragility_gap(
        direction=str(direction),
        frag_gap_usage=float(frag_gap_usage_pre_bonus),
    )
    eps = 1e-9
    frag_pre_bonus = 0.0 if p_close_adj <= eps else max(0.0, frag_gap_dir_pre_bonus / p_close_adj)

    competitive_usage_bonus, competitive_usage_debug = _competitive_usage_bonus(
        stat_u=str(stat_u),
        direction=str(direction),
        usg_pct=usage_debug.get('usage_usg_pct'),
        fragility=float(frag_pre_bonus),
        q_blowout=float(q),
        headroom=float(frag_gap_core_pre_bonus),
        cfg=role_cfg or {},
    )
    p_adj_pre_competitive_usage = float(p_adj)
    p_adj = float(np.clip(float(p_adj) + float(competitive_usage_bonus), 0.0, 1.0))

    # Fragility (Atlas): usage lives ONLY inside the fragility channel.
    # Keep the core p_role -> p_adj haircut unchanged; usage only scales how
    # breakable the OVER path is understood to be under game-script stress.
    frag_gap_core = max(0.0, p_close_adj - p_adj)
    frag_gap_usage = float(frag_gap_core) * float(usage_dep_eff)
    frag_gap_dir = _directional_fragility_gap(
        direction=str(direction),
        frag_gap_usage=float(frag_gap_usage),
    )

    frag = 0.0 if p_close_adj <= eps else max(0.0, frag_gap_dir / p_close_adj)
    frag_abs = max(0.0, frag_gap_dir)

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
        "minutes_s_blowout": float(minutes_s_blowout),
        "under_blowout_sens_mult": float(under_blowout_sens_mult),
        "under_blowout_sens_eligible": bool(under_blowout_sens_eligible),
        "minutes_s_close": float(minutes_s_close),  # ✅ new: shows reduced close sensitivity
        "is_star": bool(is_star),

        # Fragility (aligned to adjusted channel)
        "fragility": float(frag),
        "fragility_abs": float(frag_abs),
        "fragility_gap_core": float(frag_gap_core),
        "fragility_gap_usage": float(frag_gap_usage),
        "fragility_gap_dir": float(frag_gap_dir),
        "usage_dep": float(usage_dep),
        "usage_dep_capped": float(usage_dep_capped),
        "usage_dep_cap": float(usage_dep_cap),
        "usage_dep_eff": float(usage_dep_eff),
        "usage_risk_gate": float(usage_risk_gate),
        "usage_baseline": float(usage_debug.get("usage_baseline", 1.0)),
        "usage_producer_mult": float(usage_debug.get("usage_producer_mult", 1.0)),
        "usage_pressure_mult": float(usage_debug.get("usage_pressure_mult", 1.0)),
        "usage_usg_pct": float(usage_debug.get("usage_usg_pct", 0.0) or 0.0),
        "usage_usg_scaled": float(usage_debug.get("usage_usg_scaled", 0.0)),
        "usage_usg_mult": float(usage_debug.get("usage_usg_mult", 1.0)),
        "usage_scoring_mult": float(usage_debug.get("usage_scoring_mult", 1.0)),
        "usage_assist_mult": float(usage_debug.get("usage_assist_mult", 1.0)),
        "usage_rebound_mult": float(usage_debug.get("usage_rebound_mult", 1.0)),
        "usage_threes_mult": float(usage_debug.get("usage_threes_mult", 1.0)),
        "usage_metric_mult": float(usage_debug.get("usage_metric_mult", 1.0)),
        "usage_target_rate": float(usage_debug.get("usage_target_rate", 0.0)),
        "usage_burden_ratio": float(usage_debug.get("usage_burden_ratio", 1.0)),
        "usage_dep_raw": float(usage_debug.get("usage_dep_raw", usage_dep)),
        "p_adj_pre_under_relief": float(p_adj_pre_under_relief),
        "p_adj_pre_competitive_usage": float(p_adj_pre_competitive_usage),
        "competitive_usage_bonus": float(competitive_usage_bonus),
        "competitive_usage_eligible": bool(competitive_usage_debug.get("eligible", 0.0) >= 0.5),
        "competitive_usage_usage_gate": float(competitive_usage_debug.get("usage_gate", 0.0)),
        "competitive_usage_frag_gate": float(competitive_usage_debug.get("frag_gate", 0.0)),
        "competitive_usage_tight_gate": float(competitive_usage_debug.get("tight_gate", 0.0)),
        "competitive_usage_total_gate": float(competitive_usage_debug.get("total_gate", 0.0)),
        "competitive_usage_bonus_uncapped": float(competitive_usage_debug.get("bonus_uncapped", 0.0)),
        "competitive_usage_headroom": float(competitive_usage_debug.get("headroom", 0.0)),
        "under_relief_haircut": float(under_relief_haircut),
        "under_relief_haircut_min": float(under_relief_haircut_min),
        "under_relief_factor": float(under_relief_factor if under_relief_eligible else 1.0),
        "under_relief_applied": bool(under_relief_eligible),

        # Stat summary diagnostics
        "min_mean": float(s.get("min_mean", 0.0)),
        "min_std": float(s.get("min_std", 0.0)),
        "rate_mean": float(base_rate_mu),
        "rate_std": float(s.get("rate_std", 0.0)),

        # Context diagnostics
        "rate_mean_ctx": float(rate_mu_role),
        "rate_mean_ctx_raw": float(rate_mu_role_raw),
        "rate_std_ctx": float(rate_sd_role),
        "role_metrics_mult": float(role_metrics_mult),
        "role_ctx_mult": float(role_mult),
        "role_ctx_mult_raw": float(role_mult_raw),
        "role_ctx_rate_mult": float(rate_mu_role_mult),
        "role_ctx_rate_mult_raw": float(rate_mu_role_mult_raw),
        "role_ctx_rate_clamp_lo": float(rate_mu_role_clamp_lo),
        "role_ctx_rate_clamp_hi": float(rate_mu_role_clamp_hi),
        "role_ctx_rate_softcap_k": float(rate_mu_role_softcap_k),
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

    if role_metrics_debug:
        for k, v in role_metrics_debug.items():
            out[f"role_metrics_{k}"] = float(v)

    # Branch multiplier on role context activation (now after out dict is populated)
    role_ctx_outs_used = int(out.get("role_ctx_outs_used", 0)) if "role_ctx_outs_used" in out else 0
    under_blowout_sens_mult = _role_ctx_blowout_sens_mult(str(direction), role_ctx_outs_used, float(minutes_s))
    
    # Update p_adj if under blowout sensitivity was adjusted
    if under_blowout_sens_eligible and under_blowout_sens_mult != 0.75:
        # Recalculate with adjusted multiplier
        minutes_s_blowout_updated = float(minutes_s) * float(under_blowout_sens_mult)
        out["p_adj"] = float(
            adjust_probability_for_blowout(
                p_raw=float(p_role),
                blowout_risk=float(q),
                sens=float(minutes_s_blowout_updated),
            )
        )
        out["p_adj"] = float(np.clip(out["p_adj"], 0.0, 1.0))
        out["minutes_s_blowout"] = float(minutes_s_blowout_updated)
        out["under_blowout_sens_mult"] = float(under_blowout_sens_mult)

    return out
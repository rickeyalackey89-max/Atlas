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

from Atlas.core.features import summarize_stat, get_player_window, compute_recent_form, compute_opp_defense_factor, compute_pace_factor
from Atlas.core.minutes import adjust_probability_for_blowout, minutes_sensitivity
from Atlas.core.share_name_key import share_name_key
from Atlas.core.team_aliases import normalize_team_abbr

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
            _SHARE_MATRIX["team_u"] = _SHARE_MATRIX["team"].map(normalize_team_abbr)
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
    if stat in {'FTA'}:
        return 0.95  # FTA is strongly minutes-correlated but less volatile than scoring
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

    if stat in {'FTA'}:
        if burden_ratio >= 1.10:
            return 1.05
        if burden_ratio >= 0.96:
            return 1.02
        if burden_ratio >= 0.84:
            return 1.00
        return 0.98

    if burden_ratio >= 1.15:
        return 1.05
    if burden_ratio >= 1.00:
        return 1.02
    if burden_ratio >= 0.86:
        return 1.00
    return 0.98


def _role_metrics_role_ctx_active(row: Any, role_cfg: dict[str, Any] | None = None) -> bool:
    try:
        role_metrics_require_role_ctx = bool((role_cfg or {}).get('role_metrics_require_role_ctx', False))
    except Exception:
        role_metrics_require_role_ctx = False

    try:
        role_metrics_min_role_ctx_outs = int((role_cfg or {}).get('role_metrics_min_role_ctx_outs', 0) or 0)
    except Exception:
        role_metrics_min_role_ctx_outs = 0
    if role_metrics_require_role_ctx:
        role_metrics_min_role_ctx_outs = max(1, role_metrics_min_role_ctx_outs)

    try:
        if hasattr(row, 'get'):
            raw_outs = row.get('role_ctx_outs_used', 0)
        else:
            raw_outs = getattr(row, 'role_ctx_outs_used', 0)
        role_ctx_outs_used = float(pd.to_numeric(pd.Series([raw_outs]), errors='coerce').iloc[0])
    except Exception:
        role_ctx_outs_used = 0.0
    return role_ctx_outs_used >= float(role_metrics_min_role_ctx_outs)



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
        "usage_usg_pct": float("nan") if pd.isna(usg) else float(usg),
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


def _crafted_role_workload_adjustment(
    row: Any,
    stat_u: str,
    *,
    direction: str | None = None,
    role_cfg: dict[str, Any] | None = None,
    role_ctx_on_override: bool | None = None,
) -> tuple[float, dict[str, float]]:
    """Convert CraftedNBA role/workload fields into a bounded stat-family prior."""
    enabled = bool((role_cfg or {}).get("crafted_role_workload_enabled", False))
    if not enabled:
        return 1.0, {"score": 0.0, "mult": 1.0, "enabled": 0.0}

    if role_ctx_on_override is None:
        role_ctx_on = _role_metrics_role_ctx_active(row, role_cfg)
    else:
        role_ctx_on = bool(role_ctx_on_override)
    if not role_ctx_on:
        return 1.0, {"score": 0.0, "mult": 1.0, "enabled": 1.0, "gated": 1.0}

    if bool((role_cfg or {}).get("crafted_role_workload_over_only", False)) and str(direction or "").upper() != "OVER":
        return 1.0, {"score": 0.0, "mult": 1.0, "enabled": 1.0, "direction_gated": 1.0}

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

    def _scale(raw_value: float, center: float, scale: float) -> float | None:
        if pd.isna(raw_value):
            return None
        return float(np.tanh((float(raw_value) - float(center)) / max(float(scale), 1e-6)))

    def _add(components: dict[str, float], name: str, raw_value: float, center: float, scale: float, weight: float) -> None:
        scaled = _scale(raw_value, center, scale)
        if scaled is None:
            return
        components[f"{name}_raw"] = float(raw_value)
        components[f"{name}_scaled"] = float(scaled)
        components[f"{name}_weighted"] = float(weight * scaled)

    stat_norm = str(stat_u or "").upper().strip()
    components: dict[str, float] = {"enabled": 1.0}

    if stat_norm in {"PTS", "PRA", "PA", "PR", "RA"}:
        _add(components, "usage_projection", _get("role_metrics_usage_projection"), 24.0, 9.0, 0.007)
        _add(components, "usg_pct", _get("role_metrics_usg_pct"), 26.5, 12.0, 0.005)
        _add(components, "load", _get("role_metrics_load"), 20.0, 10.0, 0.005)
        _add(components, "touches", _get("role_metrics_touches"), 55.0, 25.0, 0.003)
        _add(components, "ts_pct", _get("role_metrics_ts_pct"), 58.0, 10.0, 0.004)
        _add(components, "sq", _get("role_metrics_sq"), 50.0, 22.0, 0.004)
        _add(components, "ftr", _get("role_metrics_ftr"), 26.0, 18.0, 0.003)

    if stat_norm in {"AST", "PA", "PRA", "RA"}:
        _add(components, "ast_pct", _get("role_metrics_ast_pct"), 18.0, 12.0, 0.006)
        _add(components, "touches", _get("role_metrics_touches"), 55.0, 25.0, 0.006)
        _add(components, "ast_usg", _get("role_metrics_ast_usg"), 0.85, 0.35, 0.007)
        _add(components, "bc", _get("role_metrics_bc"), 8.0, 4.0, 0.006)
        _add(components, "load", _get("role_metrics_load"), 20.0, 10.0, 0.004)
        _add(components, "pr", _get("role_metrics_pr"), 5.0, 2.0, 0.006)

    if stat_norm in {"REB", "PR", "PRA", "RA"}:
        _add(components, "trb_pct", _get("role_metrics_trb_pct"), 13.0, 8.0, 0.007)
        _add(components, "orb_pct", _get("role_metrics_orb_pct"), 4.0, 4.0, 0.004)
        _add(components, "drb_pct", _get("role_metrics_drb_pct"), 10.0, 6.0, 0.005)

    if stat_norm in {"FG3M", "3PM", "THREES"}:
        _add(components, "three_par", _get("role_metrics_three_par"), 40.0, 22.0, 0.008)
        _add(components, "sq", _get("role_metrics_sq"), 55.0, 22.0, 0.006)
        _add(components, "ts_pct", _get("role_metrics_ts_pct"), 58.0, 10.0, 0.004)
        _add(components, "usage_projection", _get("role_metrics_usage_projection"), 22.0, 10.0, 0.003)

    score = float(sum(v for k, v in components.items() if k.endswith("_weighted")))
    score = float(np.clip(score, -0.015, 0.020))
    mult = float(np.clip(1.0 + score, 0.985, 1.020))
    components["score"] = score
    components["mult"] = mult
    return mult, components


def _crafted_role_workload_minutes_projection(
    row: Any,
    *,
    role_cfg: dict[str, Any] | None = None,
    role_ctx_on_override: bool | None = None,
) -> float | None:
    enabled = bool((role_cfg or {}).get("crafted_role_workload_enabled", False))
    if not enabled:
        return None

    if role_ctx_on_override is None:
        role_ctx_on = _role_metrics_role_ctx_active(row, role_cfg)
    else:
        role_ctx_on = bool(role_ctx_on_override)
    if not role_ctx_on:
        return None

    try:
        base_minutes = float(pd.to_numeric(pd.Series([row.get("minutes_projection", None)]), errors="coerce").iloc[0])
    except Exception:
        base_minutes = float("nan")
    try:
        crafted_minutes = float(pd.to_numeric(pd.Series([row.get("role_metrics_minutes_projection", None)]), errors="coerce").iloc[0])
    except Exception:
        crafted_minutes = float("nan")

    if pd.isna(base_minutes) and pd.isna(crafted_minutes):
        return None
    if pd.isna(base_minutes):
        return float(crafted_minutes) if pd.notna(crafted_minutes) else None
    if pd.isna(crafted_minutes):
        return float(base_minutes)

    blend = float((role_cfg or {}).get("crafted_role_workload_minutes_blend", 0.35) or 0.35)
    ratio_lo = float((role_cfg or {}).get("crafted_role_workload_minutes_ratio_lo", 0.92) or 0.92)
    ratio_hi = float((role_cfg or {}).get("crafted_role_workload_minutes_ratio_hi", 1.08) or 1.08)
    blend = float(np.clip(blend, 0.0, 1.0))
    ratio_lo = float(np.clip(ratio_lo, 0.75, 1.0))
    ratio_hi = float(np.clip(ratio_hi, 1.0, 1.25))

    ratio = float(np.clip(float(crafted_minutes) / max(float(base_minutes), 1e-6), ratio_lo, ratio_hi))
    return float(base_minutes) * (1.0 + ((ratio - 1.0) * blend))



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


def _under_fragility(
    *,
    p_adj: float,
    p_close_adj: float,
    usage_dep_eff: float,
    direction: str,
    q_blowout: float = 0.0,
) -> tuple[float, float, float]:
    """Compute UNDER-side fragility: how overconfident the UNDER probability is.

    For UNDER legs the kernel systematically overshoots (mean p ~0.55 vs
    actual hit 0.51).  The overshoot worsens when the model sees "easy
    UNDER" conditions (high q_blowout, line well above expected).

    Fragility here is proportional to how far p_adj sits above 0.50,
    scaled by q_blowout (games with higher blowout risk show more
    overshoot in the empirical data).

    Returns (under_frag, under_frag_gap, under_frag_gap_usage).
    ``under_frag`` is in [0, 1] and measures the dampening need.
    """
    if str(direction).upper() != "UNDER":
        return 0.0, 0.0, 0.0
    # How far above 0.50 is the UNDER probability?
    overshoot = max(0.0, float(p_adj) - 0.50)
    # Scale by blowout risk: overshoot is most harmful when q is high
    q_scale = min(1.0, max(0.0, float(q_blowout)) / 0.20)   # ramps 0->1 over q 0->0.20
    gap = overshoot * (0.60 + 0.40 * q_scale)  # base 60% + up to 40% from q
    gap_usage = gap * float(usage_dep_eff)
    # Normalise to [0, 1]
    frag = min(1.0, gap_usage * 2.0)  # 0.50 overshoot * 2 -> frag=1.0
    return float(frag), float(gap), float(gap_usage)


def _apply_under_fragility_dampener(
    *,
    p_adj: float,
    p_close_adj: float,
    under_frag: float,
    cfg: dict | None,
) -> tuple[float, float]:
    """Compress overconfident UNDER probabilities toward 0.50.

    The UNDER kernel systematically overshoots: empirical hit rates
    cluster near 50 % regardless of predicted p.  When *under_frag*
    is high, pull ``p_adj`` back toward 0.50 by a fraction controlled
    by ``under_frag_dampen_strength`` (default 0.40).

    Returns (p_adj_dampened, dampen_amount).
    """
    try:
        strength = float((cfg or {}).get("under_frag_dampen_strength", 0.70))
    except Exception:
        strength = 0.70
    strength = float(max(0.0, min(1.0, strength)))

    # Blend p_adj toward 0.50 proportional to under_frag * strength
    blend = float(min(float(under_frag), 1.0)) * strength
    p_dampened = float(p_adj) * (1.0 - blend) + 0.50 * blend
    dampen_amount = float(p_adj) - float(p_dampened)
    return float(p_dampened), float(dampen_amount)


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
    if value is None:
        return 0.0
    try:
        val = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(val):
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
    if value is None:
        return 0.0
    try:
        val = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(val):
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

def _fragility_root_inputs(
    row: pd.Series,
    stat_u: str,
    base_rate_mu: float,
    line: float,
    expected_minutes: float,
    role_cfg: dict[str, Any] | None = None,
) -> tuple[float, dict[str, float]]:
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

    role_ctx_on = _role_metrics_role_ctx_active(row, role_cfg)

    def _row_metric(name: str) -> float | None:
        if not role_ctx_on:
            return None
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


def _team_to_abbr(team: Any) -> str:
    return normalize_team_abbr(team)


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


def _zero_dnp_minutes_mult(
    outs: list[str],
    player_min_mean: float,
    gamelogs: pd.DataFrame,
    *,
    cfg: dict,
) -> tuple[float, str]:
    """
    When a star player with 0 DNP games in the gamelog is OUT, their backup will
    play significantly more minutes than their historical average.

    Returns (mult, debug_str) where mult scales mu_close for the beneficiary.
    mult=1.0 means no adjustment (disabled or no qualifying out player found).
    """
    enabled = bool(cfg.get("zero_dnp_enabled", True))
    if not enabled:
        return 1.0, "disabled"
    if not outs or not isinstance(gamelogs, pd.DataFrame) or gamelogs.empty:
        return 1.0, "no_outs_or_gl"

    dnp_thresh = int(cfg.get("zero_dnp_dnp_thresh", 2))
    min_cap = float(cfg.get("zero_dnp_min_cap", 2.5))
    min_blend = float(cfg.get("zero_dnp_min_blend", 0.80))
    games_missed_max = int(cfg.get("zero_dnp_games_missed_max", 7))

    best_mult = 1.0
    best_reason = "no_zero_dnp_out"

    for out_player in outs:
        last_name = str(out_player).split()[-1] if out_player else ""
        if not last_name:
            continue
        out_gl = gamelogs[gamelogs["player"].str.contains(last_name, case=False, na=False)]
        if out_gl.empty:
            continue
        dnp_count = int((out_gl["minutes"].fillna(0) == 0).sum())
        if dnp_count >= dnp_thresh:
            continue  # Player has DNP history — share matrix is valid
        # Staleness gate: if the out player has missed > games_missed_max consecutive
        # games, the GBM and share matrix have already adapted — don't override.
        if games_missed_max > 0 and "game_date" in out_gl.columns:
            _sorted_gl = out_gl.sort_values("game_date", ascending=False)
            _recent_mins = _sorted_gl["minutes"].fillna(0).to_numpy()
            if len(_recent_mins) > 0 and np.any(_recent_mins > 0):
                _consecutive_missed = int(np.argmax(_recent_mins > 0))
            else:
                _consecutive_missed = len(_recent_mins)
            if _consecutive_missed > games_missed_max:
                continue  # Out too long — GBM and share matrix have already learned
        # Zero-DNP case: compute expected starter-load multiplier
        playing_gl = out_gl[out_gl["minutes"].fillna(0) > 0]
        if playing_gl.empty:
            continue
        out_avg_min = float(playing_gl["minutes"].mean())
        if not np.isfinite(out_avg_min) or out_avg_min <= 0:
            continue
        player_min = max(float(player_min_mean), 3.0)
        ratio = float(np.clip(out_avg_min / player_min, 1.0, min_cap))
        mult = 1.0 + (ratio - 1.0) * min_blend
        if mult > best_mult:
            best_mult = float(mult)
            best_reason = (
                f"zero_dnp:{out_player}(dnp={dnp_count}"
                f",out_min={out_avg_min:.0f},pl_min={player_min:.0f},x{mult:.3f}"
                f",missed={_consecutive_missed if 'game_date' in out_gl.columns else '?'})"
            )

    return best_mult, best_reason


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
    team_u = normalize_team_abbr(team)
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


# -------------------------------------------------------------------
# Rotation tier classification for blowout minute adjustments
# -------------------------------------------------------------------

def _classify_rotation_tier(
    row: pd.Series,
    projected_minutes: float,
    *,
    blowout_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify a player into a rotation tier using CraftedNBA signals and
    projected minutes.  Returns a dict with 'tier' (star/starter/rotation/bench)
    and 'minute_drop_key' for config lookup.

    Empirical blowout minute deltas follow a continuous curve
    (delta = slope × base_min + intercept), but this function still provides
    a tier label for diagnostic purposes.

    Starters/stars lose minutes in blowouts; bench players on the losing team
    GAIN garbage-time minutes (crossover at ~14 min baseline).
    """
    cfg = blowout_cfg or {}
    rot_cfg = cfg.get("rotation_tiers", {}) or {}

    # Thresholds (configurable, with sane defaults)
    star_min_thresh = float(rot_cfg.get("star_minutes", 33.0))
    starter_min_thresh = float(rot_cfg.get("starter_minutes", 26.0))
    rotation_min_thresh = float(rot_cfg.get("rotation_minutes", 16.0))
    bench_min_thresh = float(rot_cfg.get("bench_minutes", 10.0))

    # CraftedNBA usage as a secondary signal
    usg = _safe_float_np(row.get("role_metrics_usg_pct", None))
    load = _safe_float_np(row.get("role_metrics_load", None))

    pm = projected_minutes if math.isfinite(projected_minutes) else 0.0

    # Star: high-minute starters who get pulled first in blowouts
    if pm >= star_min_thresh or (pm >= 30.0 and usg >= 0.25):
        return {"tier": "star", "minute_drop_key": "star_minute_drop",
                "blowout_minute_sign": -1, "minutes": pm, "usg": usg}

    # Starter: regular starters, also lose minutes in blowouts
    if pm >= starter_min_thresh or (pm >= 22.0 and usg >= 0.18):
        return {"tier": "starter", "minute_drop_key": "starter_minute_drop",
                "blowout_minute_sign": -1, "minutes": pm, "usg": usg}

    # Rotation: mid-rotation players, slight minute loss
    if pm >= rotation_min_thresh or (pm >= 12.0 and load >= 0.10):
        return {"tier": "rotation", "minute_drop_key": "role_minute_drop",
                "blowout_minute_sign": -1, "minutes": pm, "usg": usg}

    # Bench: data shows they also lose minutes (or break even) in blowouts
    return {"tier": "bench", "minute_drop_key": "bench_minute_drop",
            "blowout_minute_sign": -1, "minutes": pm, "usg": usg}


def _safe_float_np(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


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
# Enriched blowout probability: spread + team/matchup history
# -------------------------------------------------------------------

_BLOWOUT_TEAM_CACHE: dict[str, Any] | None = None


def _build_blowout_team_stats(gamelogs: pd.DataFrame, threshold: float = 15.5, lookback_days: int = 120) -> dict[str, Any]:
    """
    Build per-team and per-matchup blowout propensity stats from gamelogs.

    Returns a dict with:
      team_blowout_rate[team] -> float  (how often this team is in blowouts)
      team_margin_sd[team] -> float     (this team's game-to-game margin volatility)
      matchup_blowout_rate[(team,opp)] -> float  (H2H blowout rate, min 2 games)
    """
    if gamelogs is None or gamelogs.empty:
        return {}

    gl = gamelogs.copy()
    gl["game_date"] = pd.to_datetime(gl["game_date"], errors="coerce")
    gl = gl[gl["game_date"].notna()].copy()

    if lookback_days > 0:
        cutoff = gl["game_date"].max() - pd.Timedelta(days=lookback_days)
        gl = gl[gl["game_date"] >= cutoff].copy()

    if gl.empty:
        return {}

    # Aggregate to game-team level
    gl["team"] = gl["team"].map(normalize_team_abbr)
    gl["opp"] = gl["opp"].map(normalize_team_abbr)

    game_team = gl.groupby(["game_date", "team", "opp"]).agg(
        team_pts=("pts", "sum"),
    ).reset_index()

    # Self-join to get opponent points
    merged = game_team.merge(
        game_team[["game_date", "team", "team_pts"]].rename(
            columns={"team": "opp", "team_pts": "opp_pts"}
        ),
        on=["game_date", "opp"],
        how="inner",
    )
    if merged.empty:
        return {}

    merged["margin"] = merged["team_pts"] - merged["opp_pts"]
    merged["abs_margin"] = merged["margin"].abs()
    merged["is_blowout"] = merged["abs_margin"] >= threshold

    # Per-team blowout rate and margin volatility
    team_stats = merged.groupby("team").agg(
        games=("is_blowout", "count"),
        blowout_rate=("is_blowout", "mean"),
        margin_sd=("abs_margin", "std"),
    ).to_dict("index")

    team_blowout_rate = {t: v["blowout_rate"] for t, v in team_stats.items() if v["games"] >= 5}
    team_margin_sd = {t: v["margin_sd"] for t, v in team_stats.items()
                      if v["games"] >= 5 and math.isfinite(v.get("margin_sd", 0.0))}

    # Per-matchup blowout rate (min 2 games for signal)
    matchup = merged.groupby(["team", "opp"]).agg(
        games=("is_blowout", "count"),
        blowout_rate=("is_blowout", "mean"),
    )
    matchup_blowout_rate = {
        (t, o): row["blowout_rate"]
        for (t, o), row in matchup.iterrows()
        if row["games"] >= 2
    }

    # League-average blowout rate as baseline
    league_blowout_rate = float(merged["is_blowout"].mean())

    return {
        "team_blowout_rate": team_blowout_rate,
        "team_margin_sd": team_margin_sd,
        "matchup_blowout_rate": matchup_blowout_rate,
        "league_blowout_rate": league_blowout_rate,
        "league_margin_sd": float(merged["margin"].std()) if len(merged) > 10 else 16.0,
    }


def compute_enriched_blowout_q(
    *,
    spread_mean: float,
    threshold: float,
    sd: float,
    team: str,
    opp: str,
    blowout_team_stats: dict[str, Any] | None = None,
    matchup_weight: float = 0.25,
    team_weight: float = 0.15,
) -> tuple[float, dict[str, Any]]:
    """
    Enriched blowout probability that blends:
      1. Spread-based Normal CDF (primary signal)
      2. Team historical blowout propensity (secondary)
      3. Head-to-head matchup blowout rate (tertiary, strongest when available)

    Returns (q_enriched, debug_dict).
    """
    # Base spread model
    q_spread = blowout_probability(spread_mean=spread_mean, threshold=threshold, sd=sd)

    debug = {
        "q_spread": float(q_spread),
        "q_team_adj": 0.0,
        "q_matchup_adj": 0.0,
        "team_blowout_rate": None,
        "opp_blowout_rate": None,
        "matchup_blowout_rate": None,
    }

    if not blowout_team_stats:
        return q_spread, debug

    league_rate = float(blowout_team_stats.get("league_blowout_rate", 0.33))
    team_rates = blowout_team_stats.get("team_blowout_rate", {})
    matchup_rates = blowout_team_stats.get("matchup_blowout_rate", {})

    team_u = normalize_team_abbr(team)
    opp_u = normalize_team_abbr(opp)

    # Team-level adjustment: average both teams' blowout propensity relative to league
    team_rate = team_rates.get(team_u)
    opp_rate = team_rates.get(opp_u)
    debug["team_blowout_rate"] = team_rate
    debug["opp_blowout_rate"] = opp_rate

    team_adj = 0.0
    if team_rate is not None and opp_rate is not None and league_rate > 0:
        # Both teams' propensity averaged, expressed as deviation from league mean
        pair_rate = (team_rate + opp_rate) / 2.0
        team_adj = (pair_rate - league_rate) * team_weight
    elif team_rate is not None and league_rate > 0:
        team_adj = (team_rate - league_rate) * team_weight * 0.5
    elif opp_rate is not None and league_rate > 0:
        team_adj = (opp_rate - league_rate) * team_weight * 0.5

    debug["q_team_adj"] = float(team_adj)

    # Matchup-level adjustment: H2H blowout history
    matchup_rate = matchup_rates.get((team_u, opp_u))
    debug["matchup_blowout_rate"] = matchup_rate

    matchup_adj = 0.0
    if matchup_rate is not None and league_rate > 0:
        matchup_adj = (matchup_rate - league_rate) * matchup_weight

    debug["q_matchup_adj"] = float(matchup_adj)

    # Blend: spread is primary, team/matchup add bounded adjustments
    q_enriched = q_spread + team_adj + matchup_adj
    q_enriched = float(max(0.02, min(0.85, q_enriched)))

    debug["q_enriched"] = float(q_enriched)
    return q_enriched, debug


def _blowout_stat_families(stat_u: str) -> set[str]:
    stat = str(stat_u or "").upper().strip()
    families = {"all"}
    if stat in {"PTS", "PRA", "PA", "PR", "RA"}:
        families.add("combo_scoring")
    elif stat == "REB":
        families.add("rebounds")
    elif stat == "AST":
        families.add("assists")
    elif stat in {"FG3M", "3PM", "THREES"}:
        families.add("threes")
    elif stat in {"BLK", "STL", "STOCKS"}:
        families.add("stocks")
    else:
        families.add("other")
    return families


def _resolve_blowout_rule_adjustments(
    *,
    blowout_cfg: dict[str, Any] | None,
    stat_u: str,
    direction: str,
    q_blowout: float,
    role_ctx_outs_used: int,
    minutes_s: float,
    is_star: bool,
) -> dict[str, Any]:
    rules = (blowout_cfg or {}).get("adjustment_rules", [])
    if not isinstance(rules, list) or not rules:
        return {
            "minute_drop_mult": 1.0,
            "sensitivity_mult": 1.0,
            "applied_rules": [],
        }

    stat_norm = str(stat_u or "").upper().strip()
    direction_norm = str(direction or "").upper().strip()
    families = _blowout_stat_families(stat_norm)
    role_on = int(role_ctx_outs_used or 0) > 0
    starter_like = bool(is_star) or role_on or float(minutes_s) >= 0.55
    q_val = float(q_blowout)

    minute_drop_mult = 1.0
    sensitivity_mult = 1.0
    applied_rules: list[str] = []

    for idx, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            continue

        rule_name = str(raw_rule.get("name", f"rule_{idx + 1}")).strip() or f"rule_{idx + 1}"
        rule_direction = str(raw_rule.get("direction", "")).strip().upper()
        if rule_direction and rule_direction != direction_norm:
            continue

        raw_stats = raw_rule.get("stats")
        if isinstance(raw_stats, list) and raw_stats:
            allowed_stats = {str(item).upper().strip() for item in raw_stats if str(item).strip()}
            if stat_norm not in allowed_stats:
                continue

        raw_families = raw_rule.get("families")
        if isinstance(raw_families, list) and raw_families:
            allowed_families = {str(item).lower().strip() for item in raw_families if str(item).strip()}
            if not families.intersection(allowed_families):
                continue

        role_ctx_mode = str(raw_rule.get("role_ctx", "any")).strip().lower()
        if role_ctx_mode == "on" and not role_on:
            continue
        if role_ctx_mode == "off" and role_on:
            continue

        starter_like_req = raw_rule.get("starter_like")
        if isinstance(starter_like_req, bool) and starter_like_req != starter_like:
            continue

        try:
            min_q = float(raw_rule.get("min_q", 0.0))
        except Exception:
            min_q = 0.0
        try:
            max_q = float(raw_rule.get("max_q", 1.0))
        except Exception:
            max_q = 1.0
        if q_val < min_q or q_val > max_q:
            continue

        try:
            rule_minute_mult = float(raw_rule.get("minute_drop_mult", 1.0))
        except Exception:
            rule_minute_mult = 1.0
        try:
            rule_sens_mult = float(raw_rule.get("sensitivity_mult", 1.0))
        except Exception:
            rule_sens_mult = 1.0

        if not math.isfinite(rule_minute_mult) or rule_minute_mult <= 0.0:
            rule_minute_mult = 1.0
        if not math.isfinite(rule_sens_mult) or rule_sens_mult <= 0.0:
            rule_sens_mult = 1.0

        minute_drop_mult *= rule_minute_mult
        sensitivity_mult *= rule_sens_mult
        applied_rules.append(rule_name)

    return {
        "minute_drop_mult": float(np.clip(minute_drop_mult, 0.25, 1.50)),
        "sensitivity_mult": float(np.clip(sensitivity_mult, 0.25, 1.50)),
        "applied_rules": applied_rules,
    }


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
    blowout_cfg: dict[str, Any] | None = None,
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
    _hl_by_stat = (blowout_cfg or {}).get("recency_halflife_by_stat", {})
    _hl_val = float(_hl_by_stat.get(stat.upper(), (blowout_cfg or {}).get("recency_halflife", 0)) or 0) or None
    s = summarize_stat(g, stat, recency_halflife=_hl_val)

    role_ctx_on_for_external_metrics = _role_metrics_role_ctx_active(row, role_cfg)
    crafted_minutes_projection = _crafted_role_workload_minutes_projection(
        row,
        role_cfg=role_cfg,
        role_ctx_on_override=role_ctx_on_for_external_metrics,
    )

    if hasattr(row, "get"):
        if crafted_minutes_projection is not None:
            projected_minutes_raw = crafted_minutes_projection
        elif not role_ctx_on_for_external_metrics:
            projected_minutes_raw = row.get("minutes_projection", None)
        else:
            projected_minutes_raw = row.get("role_metrics_minutes_projection", row.get("minutes_projection", None))
    else:
        projected_minutes_raw = None
    projected_minutes = pd.to_numeric(pd.Series([projected_minutes_raw]), errors="coerce").iloc[0]
    projected_minutes_val = float(projected_minutes) if pd.notna(projected_minutes) else float("nan")

    role_metrics_mult = 1.0
    role_metrics_debug: dict[str, float] = {}

    _pm_for_tier = float(projected_minutes_val if pd.notna(projected_minutes) else float(s.get("min_mean", 0.0)))
    is_star = _pm_for_tier >= 33.0

    # Rotation-tier-aware blowout minute adjustment
    _rot = _classify_rotation_tier(row, _pm_for_tier, blowout_cfg=blowout_cfg)
    _rot_tier = str(_rot.get("tier", "rotation"))

    # Continuous blowout minute-delta curve replaces discrete tier drops.
    # delta = slope × base_min + intercept; positive = player GAINS minutes.
    # Empirical fits:  win: -0.2446×base+2.41 (crossover 9.9 min)
    #                  loss: -0.3206×base+5.54 (crossover 17.3 min)
    # Averaged single curve: -0.28×base+4.0 (crossover ~14 min)
    _bcfg_rot = blowout_cfg or {}
    _curve_cfg = _bcfg_rot.get("blowout_curve", {}) or {}
    _curve_slope = float(_curve_cfg.get("slope", -0.28))
    _curve_intercept = float(_curve_cfg.get("intercept", 4.0))
    _curve_max_gain = float(_curve_cfg.get("max_gain", 5.0))
    _curve_max_drop = float(_curve_cfg.get("max_drop", 12.0))

    # minute_delta: positive = gain minutes, negative = lose minutes
    _base_min_for_curve = float(_pm_for_tier) if _pm_for_tier > 0 else 0.0
    minute_delta_raw = _curve_slope * _base_min_for_curve + _curve_intercept
    minute_delta = max(-_curve_max_drop, min(_curve_max_gain, minute_delta_raw))

    # Convert to drop convention: positive minute_drop = fewer minutes in blowout
    minute_drop_base = -minute_delta

    # Enriched blowout probability: spread + team/matchup history
    _blowout_team_stats = (blowout_cfg or {}).get("_blowout_team_stats")
    _opp_team_for_blow = str(row.get("opp", "")).upper().strip()
    _matchup_w = float((blowout_cfg or {}).get("matchup_blowout_weight", 0.25))
    _team_w = float((blowout_cfg or {}).get("team_blowout_weight", 0.15))

    if _blowout_team_stats:
        q, _blowout_enrich_debug = compute_enriched_blowout_q(
            spread_mean=spread,
            threshold=blowout_threshold,
            sd=spread_sd,
            team=team,
            opp=_opp_team_for_blow,
            blowout_team_stats=_blowout_team_stats,
            matchup_weight=_matchup_w,
            team_weight=_team_w,
        )
    else:
        q = blowout_probability(spread_mean=spread, threshold=blowout_threshold, sd=spread_sd)
        _blowout_enrich_debug = {}

    mu_close = max(0.0, float(projected_minutes_val if pd.notna(projected_minutes) else float(s.get("min_mean", 0.0))))
    sd_close = max(1.0, float(s.get("min_std", 1.0)))

    base_rate_mu = float(s.get("rate_mean", 0.0))
    rate_sd_base = max(0.01, float(s.get("rate_std", 0.01)))

    # Resolve blowout config and stat early — needed by playoff block and rate-std block below.
    _bcfg = blowout_cfg or {}
    stat_u = str(stat).upper().strip()

    # ── Playoff regime adjustment ─────────────────────────────────────────────
    # Regular-season rate_mean overstates per-minute production in playoffs
    # (lower pace, tighter defense, targeted schemes).  Empirical deltas from
    # 9 playoff dates vs full regular season:
    #   PTS -11%, AST -16%, FG3M -20%, REB -5.5%
    # Starters play significantly more minutes in playoffs (+5–9 min for top tier).
    # Both corrections are applied here before any further adjustments.
    # Config key: blowout.playoff_rate_penalty  (dict per stat, default: enabled=false)
    _playoff_cfg = (_bcfg if hasattr(_bcfg, 'get') else {}).get("playoff_regime", {}) or {}  # type: ignore[union-attr]
    _playoff_enabled = bool(_playoff_cfg.get("enabled", False))
    _is_playoff = False
    _playoff_rate_applied = "off"
    _playoff_min_applied = "off"
    if _playoff_enabled:
        _playoff_start_str = str(_playoff_cfg.get("start_date", "2026-04-30"))
        try:
            _row_game_date = row.get("game_date") if hasattr(row, "get") else getattr(row, "game_date", None)
            if _row_game_date is not None:
                _gd_str = str(_row_game_date)[:10]
                _is_playoff = _gd_str >= _playoff_start_str
        except Exception:
            _is_playoff = False

    if _playoff_enabled and _is_playoff and base_rate_mu > 0:
        # Per-stat rate penalty multipliers (data-backed, conservative)
        _default_rate_penalties: dict[str, float] = {
            "PTS": 0.89, "PA": 0.89, "PR": 0.89, "PRA": 0.89,
            "AST": 0.84, "RA": 0.84,
            "FG3M": 0.80, "3PM": 0.80,
            "REB": 0.945,
            "FTA": 0.91,
            "BLK": 0.95, "STL": 0.95, "STOCKS": 0.95,
        }
        _rate_penalties = _playoff_cfg.get("rate_penalties", _default_rate_penalties)
        _penalty = float(_rate_penalties.get(stat_u, _playoff_cfg.get("default_rate_penalty", 0.93)))
        _old_rate_for_po = base_rate_mu
        base_rate_mu = base_rate_mu * _penalty
        _playoff_rate_applied = f"x{_penalty:.3f}_({_old_rate_for_po:.4f}->{base_rate_mu:.4f})"

    # Playoff starter minutes boost: elite starters play +5-9 min more in playoffs
    # vs their L20 window mean (which is still ~35% regular-season games).
    if _playoff_enabled and _is_playoff and mu_close >= 30.0:
        _min_boost_cfg = _playoff_cfg.get("starter_minutes_boost", {})
        _elite_floor = float(_min_boost_cfg.get("elite_floor", 33.0))
        _core_floor  = float(_min_boost_cfg.get("core_floor",  30.0))
        _elite_boost = float(_min_boost_cfg.get("elite_boost",  6.0))
        _core_boost  = float(_min_boost_cfg.get("core_boost",   3.5))
        _boost_cap   = float(_min_boost_cfg.get("boost_cap",   47.0))
        _old_mu = mu_close
        if mu_close >= _elite_floor:
            mu_close = min(_boost_cap, mu_close + _elite_boost)
            _playoff_min_applied = f"elite+{_elite_boost:.1f}({_old_mu:.1f}->{mu_close:.1f})"
        elif mu_close >= _core_floor:
            mu_close = min(_boost_cap, mu_close + _core_boost)
            _playoff_min_applied = f"core+{_core_boost:.1f}({_old_mu:.1f}->{mu_close:.1f})"
    # ─────────────────────────────────────────────────────────────────────────

    # Rate std inflation — compensate for observed underestimation of outcome variance.
    # Per-stat-type multipliers: combo stats need more inflation because the sim
    # draws a single rate and misses the positive covariance between component
    # stats that thickens the tails in real game outcomes.
    _per_stat_mult = _bcfg.get("rate_std_multiplier_by_stat", {})
    _rate_std_mult = float(_per_stat_mult.get(stat_u, _bcfg.get("rate_std_multiplier", 1.0)))
    rate_sd_base = rate_sd_base * _rate_std_mult

    # Direction-aware inflation: UNDER legs are near-coin-flip (AUC ~0.52);
    # inflating their rate_std pushes p toward 0.50, reducing overconfidence.
    if direction == "UNDER":
        _under_mult = float(_bcfg.get("rate_std_under_mult", 1.0))
        rate_sd_base = rate_sd_base * _under_mult

    # Small-sample variance inflation: inflate rate_std for players with few
    # games so that their probabilities are pushed toward 0.50 instead of
    # being overconfident.  The multiplier decays to 1.0 at `thin_window_games`
    # and has no effect above that threshold.
    _games_used = int(s.get("games", 0))
    _thin_window_games = int(_bcfg.get("thin_window_games", 15))
    _thin_window_max_mult = float(_bcfg.get("thin_window_max_mult", 1.6))
    if 0 < _games_used < _thin_window_games:
        _thin_frac = _games_used / _thin_window_games  # 0→1 as games approach threshold
        _thin_mult = 1.0 + (_thin_window_max_mult - 1.0) * (1.0 - _thin_frac)
        rate_sd_base = rate_sd_base * _thin_mult

    # ------------------------------------------------------------
    # Recent form + opponent defense adjustment (pre-sim rate shift)
    # ------------------------------------------------------------
    _recent_form_blend = float(_bcfg.get("recent_form_blend", 0.0))
    _opp_defense_strength = float(_bcfg.get("opp_defense_strength", 0.0))
    _form_debug: dict[str, Any] = {}

    # Always compute z_line and opp_defense_rel for post-hoc calibrator
    _min_mean_for_z = float(s.get("min_mean", 0.0))
    _rate_std_raw = max(0.01, float(s.get("rate_std", 0.01)))
    if base_rate_mu > 0 and _min_mean_for_z > 0:
        _expected_stat = base_rate_mu * _min_mean_for_z
        _z_line = (_expected_stat - line) / max(0.01, _rate_std_raw * _min_mean_for_z)
    else:
        _z_line = 0.0
    _form_debug["z_line"] = float(np.clip(_z_line, -5.0, 5.0))

    _opp_team = str(row.get("opp", "")).upper().strip()
    if _opp_team and base_rate_mu > 0:
        # Prefer NBA.com team defense CSV when available
        _nba_def_rel = _bcfg.get("_nba_defense_lookup", {}).get((_opp_team, stat.upper()), None)
        if _nba_def_rel is not None:
            _opp_factor = 1.0 + float(_nba_def_rel)
        else:
            _opp_factor = compute_opp_defense_factor(gamelogs, _opp_team, stat, lookback=10)

        # Series multiplier: amplify opponent defense signal as series progresses.
        # Teams increasingly know each other's schemes → defense impact grows.
        _ser_cfg = _bcfg.get("series_multiplier", {}) or {}
        _ser_lookup = _bcfg.get("_series_game_lookup", {}) or {}
        if _ser_cfg.get("enabled", False) and _ser_lookup:
            _gd_str = str(row.get("game_date", ""))[:10]
            _team_str = str(row.get("team", "")).upper().strip()
            _pair_key = (tuple(sorted([_team_str, _opp_team])), _gd_str)
            _ser_game = _ser_lookup.get(_pair_key, 1)
            _ser_table = _ser_cfg.get("multipliers", [1.01, 1.08, 1.10, 1.12])
            _ser_mult = float(_ser_table[min(_ser_game - 1, len(_ser_table) - 1)])
            # Scale the deviation from neutral (1.0); neutral defenses unaffected
            _opp_factor = 1.0 + _ser_mult * (_opp_factor - 1.0)
            _form_debug["series_game"] = int(_ser_game)
            _form_debug["series_mult"] = float(_ser_mult)

        _form_debug["opp_defense_factor"] = float(_opp_factor)
        _form_debug["opp_defense_rel"] = float(np.clip(_opp_factor - 1.0, -0.5, 0.5))
    else:
        _opp_factor = 1.0
        _form_debug["opp_defense_factor"] = 1.0
        _form_debug["opp_defense_rel"] = 0.0

    # Pace factor: game speed relative to league average
    _pace_strength = float(_bcfg.get("pace_strength", 0.0))
    if _opp_team and team:
        _pace_factor = compute_pace_factor(gamelogs, team, _opp_team, lookback=10)
        _form_debug["pace_factor"] = float(np.clip(_pace_factor, -0.15, 0.15))
    else:
        _pace_factor = 0.0
        _form_debug["pace_factor"] = 0.0

    # Apply pace as pre-sim rate adjustment (if enabled)
    if _pace_strength > 0 and _pace_factor != 0.0 and base_rate_mu > 0:
        _pace_adj = 1.0 + _pace_strength * _pace_factor
        _old_rate_pace = base_rate_mu
        base_rate_mu = base_rate_mu * _pace_adj
        _form_debug["pace_rate_shift"] = float(base_rate_mu - _old_rate_pace)

    if _recent_form_blend > 0 and base_rate_mu > 0:
        _rf = compute_recent_form(g, stat, recent_n=10)
        _recent_rate = _rf.get("recent_rate_mean")
        if _recent_rate is not None and _rf.get("recent_games", 0) >= 3:
            # Blend: rate_mean = (1 - w) * full_window + w * L10
            _old_rate = base_rate_mu
            base_rate_mu = (1.0 - _recent_form_blend) * base_rate_mu + _recent_form_blend * _recent_rate
            _form_debug["recent_rate_L10"] = float(_recent_rate)
            _form_debug["recent_form_shift"] = float(base_rate_mu - _old_rate)
            _form_debug["recent_games"] = int(_rf["recent_games"])

    if _opp_defense_strength > 0 and base_rate_mu > 0 and _opp_team:
            # Apply as a dampened adjustment: rate *= 1 + strength * (factor - 1)
            _opp_adj = 1.0 + _opp_defense_strength * (_opp_factor - 1.0)
            _old_rate2 = base_rate_mu
            base_rate_mu = base_rate_mu * _opp_adj
            _form_debug["opp_defense_adj"] = float(_opp_adj)
            _form_debug["opp_rate_shift"] = float(base_rate_mu - _old_rate2)

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
    _damp_applied: list[str] = []

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
                combo_outs_used_sum = int(
                    role_debug.get("outs_used", 0) or 0
                ) if isinstance(role_debug, dict) else 0
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

            # ── Pre-softcap dampening ──────────────────────────────
            _bump_pre = max(0.0, role_mult_raw - 1.0)
            _damp_applied: list[str] = []

            # (A) Star-beneficiary dampening: high-minute players are at
            #     capacity and do not meaningfully absorb extra production.
            _ben_min_mean = float(s.get("min_mean", 0.0) or 0.0)
            _star_ben_damp = float(cfg.get("star_beneficiary_damp", 0.25))
            _core_ben_damp = float(cfg.get("core_beneficiary_damp", 0.60))
            if _ben_min_mean >= 33.0:
                _bump_pre *= _star_ben_damp
                _damp_applied.append(f"star_ben({_ben_min_mean:.0f}m,x{_star_ben_damp})")
            elif _ben_min_mean >= 28.0:
                _bump_pre *= _core_ben_damp
                _damp_applied.append(f"core_ben({_ben_min_mean:.0f}m,x{_core_ben_damp})")

            # (B) DEMON tier gating: market-efficient legs don't benefit
            _pp_tier = str(row.get("tier", "")).upper().strip()
            _demon_damp = float(cfg.get("demon_tier_damp", 0.0))
            if _pp_tier == "DEMON":
                _bump_pre *= _demon_damp
                _damp_applied.append(f"demon(x{_demon_damp})")

            # (C) Direction-aware scaling: OVER benefits much less than UNDER
            _over_damp = float(cfg.get("over_direction_damp", 0.50))
            if direction == "OVER" and _over_damp < 1.0:
                _bump_pre *= _over_damp
                _damp_applied.append(f"over(x{_over_damp})")

            # (D) Multi-injury boost: when 3+ players are out, redistribution
            #     signal is stronger — amplify the bump.
            _multi_inj_boost = float(cfg.get("multi_injury_boost", 1.0))
            if _multi_inj_boost > 1.0 and combo_outs_used_sum >= 3:
                _bump_pre *= _multi_inj_boost
                _damp_applied.append(f"multi_inj({combo_outs_used_sum}out,x{_multi_inj_boost})")

            role_mult_raw = 1.0 + _bump_pre

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

    role_ctx_outs_used_early = 0
    if isinstance(role_debug, dict):
        try:
            role_ctx_outs_used_early = int(role_debug.get("outs_used") or 0)
        except Exception:
            role_ctx_outs_used_early = 0

    minutes_s_seed = row.get("minutes_s", None)
    try:
        minutes_s_for_rules = float(minutes_s_seed) if minutes_s_seed is not None else float(minutes_sensitivity(stat_u))
    except Exception:
        minutes_s_for_rules = float(minutes_sensitivity(stat_u))

    blowout_rule_debug = _resolve_blowout_rule_adjustments(
        blowout_cfg=blowout_cfg,
        stat_u=str(stat_u),
        direction=str(direction),
        q_blowout=float(q),
        role_ctx_outs_used=role_ctx_outs_used_early,
        minutes_s=float(minutes_s_for_rules),
        is_star=bool(is_star),
    )

    minute_drop = float(
        max(0.0, float(minute_drop_base) * float(blowout_rule_debug.get("minute_drop_mult", 1.0)))
    )

    # ------------------------------------------------------------
    # Asymmetric blowout: favored team gets less minute drop + rate boost,
    # underdog team gets more minute drop + rate penalty.
    # Data shows: winning rotation players GAIN +0.8 PRA in blowouts;
    # losing stars lose -6.4 PRA.  The current symmetric penalty is wrong.
    # spread < 0 means team is favored (likely winning the blowout).
    # ------------------------------------------------------------
    _asym_cfg = _bcfg.get("asymmetric_blowout", {}) or {}
    _asym_enabled = bool(_asym_cfg.get("enabled", False))
    _favored_minute_scale = float(_asym_cfg.get("favored_minute_scale", 0.55))
    _underdog_minute_scale = float(_asym_cfg.get("underdog_minute_scale", 1.35))
    _favored_rate_boost = float(_asym_cfg.get("favored_rate_boost", 0.10))
    _underdog_rate_penalty = float(_asym_cfg.get("underdog_rate_penalty", 0.08))

    _blow_rate_mult = 1.0  # multiplier for per-minute rate in blowout draws

    if _asym_enabled and abs(spread) > 1.0:
        _team_favored = spread < 0  # negative spread = team is favored
        if _team_favored:
            # Favored team: less minute drop, higher per-min rate
            minute_drop = minute_drop * _favored_minute_scale
            _blow_rate_mult = 1.0 + _favored_rate_boost
        else:
            # Underdog team: more minute drop, lower per-min rate
            minute_drop = minute_drop * _underdog_minute_scale
            _blow_rate_mult = 1.0 - _underdog_rate_penalty

    # ── Zero-DNP minutes correction ──────────────────────────────────────
    # When a star player with no DNP history is OUT, their backup plays
    # far more minutes than their historical average. Scale mu_close up
    # so the MC sim reflects starter-load expectations.
    _zero_dnp_mult = 1.0
    _zero_dnp_debug = "not_triggered"
    if role_enabled and isinstance(iael_eff, pd.DataFrame) and not iael_eff.empty and team:
        _outs_for_dnp = _extract_team_outs(iael_eff, normalize_team_abbr(team))
        _player_min_mean_for_dnp = float(s.get("min_mean", 0.0) or 0.0)
        _zero_dnp_mult, _zero_dnp_debug = _zero_dnp_minutes_mult(
            _outs_for_dnp, _player_min_mean_for_dnp, gamelogs, cfg=cfg
        )
        if _zero_dnp_mult > 1.0:
            mu_close = float(np.clip(mu_close * _zero_dnp_mult, 0.0, 47.0))

    # Continuous curve: starters lose minutes, bench gains garbage time.
    # minute_drop can be negative (= minute gain) for low-baseline players.
    mu_blow = max(0.0, min(48.0, mu_close - minute_drop))
    sd_blow = max(1.0, sd_close)

    role_ctx_on_for_metrics = _role_metrics_role_ctx_active(
        {"role_ctx_outs_used": role_ctx_outs_used_for_metrics},
        role_cfg,
    )
    crafted_role_workload_enabled = bool((role_cfg or {}).get("crafted_role_workload_enabled", False))
    crafted_use_impact_prior = bool((role_cfg or {}).get("crafted_role_workload_use_impact_prior", False))

    try:
        if crafted_role_workload_enabled:
            role_metrics_mult, role_metrics_debug = _crafted_role_workload_adjustment(
                row,
                stat_u=str(stat_u),
                direction=str(direction),
                role_cfg=role_cfg,
                role_ctx_on_override=role_ctx_on_for_metrics,
            )
            if crafted_use_impact_prior:
                impact_mult, impact_debug = _role_metrics_adjustment(
                    row,
                    role_ctx_on_override=role_ctx_on_for_metrics,
                )
                role_metrics_mult = float(np.clip(float(role_metrics_mult) * float(impact_mult), 0.98, 1.03))
                role_metrics_debug.update({f"impact_{k}": v for k, v in impact_debug.items()})
        else:
            role_metrics_mult, role_metrics_debug = _role_metrics_adjustment(
                row,
                role_ctx_on_override=role_ctx_on_for_metrics,
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
    # Rate-minutes correlation: in reality, players who get more minutes
    # tend to produce at a higher per-minute rate (they stay in because
    # they're playing well).  ρ > 0 thickens the right tail of stat
    # outcomes, which is exactly the bias direction the data shows.
    _rate_min_corr = float(_bcfg.get("rate_min_correlation", 0.0))

    u = rng.random(sims)

    z_min_blow = rng.standard_normal(sims)
    z_min_close = rng.standard_normal(sims)
    z_rate_indep = rng.standard_normal(sims)

    blow_mask = u < q
    close_mask = ~blow_mask

    minutes = np.empty(sims, dtype=float)
    minutes[blow_mask] = mu_blow + sd_blow * z_min_blow[blow_mask]
    minutes[close_mask] = mu_close + sd_close * z_min_close[close_mask]
    minutes = np.clip(minutes, 0.0, 48.0)

    # z_min shared across components (used for rate-minutes correlation)
    z_min_used = np.where(blow_mask, z_min_blow, z_min_close) if _rate_min_corr != 0.0 else None

    # ----------------------------------------------------------------
    # Component-based combo simulation: decompose PRA/PR/PA/RA into
    # individual stat draws with shared minutes.  Each component has its
    # own rate distribution, providing correct variance structure
    # without the inflated rate_std_multiplier needed by the single-rate
    # approach.  Components are correlated through shared minutes draws.
    # ----------------------------------------------------------------
    _COMBO_COMPONENTS: dict[str, list[str]] = {
        "PRA": ["PTS", "REB", "AST"],
        "PR": ["PTS", "REB"],
        "PA": ["PTS", "AST"],
        "RA": ["REB", "AST"],
    }
    _combo_enabled = bool(_bcfg.get("combo_component_sim", False))
    _is_combo = _combo_enabled and stat_u in _COMBO_COMPONENTS

    if _is_combo:
        # ----- COMBO: simulate with shared z_rate, per-component rates -----
        _components = _COMBO_COMPONENTS[stat_u]
        _hl_by_stat_combo = _bcfg.get("recency_halflife_by_stat", {})
        _recency_hl_default = float(_bcfg.get("recency_halflife", 0) or 0) or None
        stat_raw = np.zeros(sims, dtype=float)
        stat_role = np.zeros(sims, dtype=float)
        stat_raw_close_arr = np.zeros(sims, dtype=float)
        stat_role_close_arr = np.zeros(sims, dtype=float)

        # Close-only channel draws (shared minutes for all components)
        z_min_close_only = rng.standard_normal(sims)
        minutes_close_only = np.clip(mu_close + sd_close * z_min_close_only, 0.0, 48.0)

        # Single shared z_rate for main channel (preserves single-factor
        # correlation structure — all components move together on "good"
        # vs "bad" game factor, differentiated only by per-component
        # rate mean/std scaling).
        _z_shared = rng.standard_normal(sims)
        if _rate_min_corr != 0.0 and z_min_used is not None:
            _z_shared = _rate_min_corr * z_min_used + np.sqrt(max(0.0, 1.0 - _rate_min_corr ** 2)) * _z_shared

        _z_shared_close = rng.standard_normal(sims)
        if _rate_min_corr != 0.0:
            _z_shared_close = _rate_min_corr * z_min_close_only + np.sqrt(max(0.0, 1.0 - _rate_min_corr ** 2)) * _z_shared_close

        for _comp in _components:
            _recency_hl = float(_hl_by_stat_combo.get(_comp.upper(), 0) or 0) or _recency_hl_default
            _s_comp = summarize_stat(g, _comp, recency_halflife=_recency_hl)
            _comp_rate_mu = float(_s_comp.get("rate_mean", 0.0))
            _comp_rate_sd = max(0.01, float(_s_comp.get("rate_std", 0.01)))

            _comp_rate_raw = np.clip(_comp_rate_mu + _comp_rate_sd * _z_shared, 0.0, None)
            _comp_rate_role = np.clip(_comp_rate_mu * rate_mu_role_mult + _comp_rate_sd * role_sigma_mult * _z_shared, 0.0, None)

            stat_raw += _comp_rate_raw * minutes
            stat_role += _comp_rate_role * minutes

            # Close-only channel
            _comp_raw_close = np.clip(_comp_rate_mu + _comp_rate_sd * _z_shared_close, 0.0, None)
            _comp_role_close = np.clip(_comp_rate_mu * rate_mu_role_mult + _comp_rate_sd * role_sigma_mult * _z_shared_close, 0.0, None)

            stat_raw_close_arr += _comp_raw_close * minutes_close_only
            stat_role_close_arr += _comp_role_close * minutes_close_only

        # Use combo stat for hit comparison (same as single-stat path)
        if direction == "OVER":
            hits_raw = stat_raw > line
            hits_role = stat_role > line
        elif direction == "UNDER":
            hits_raw = stat_raw < line
            hits_role = stat_role < line
        else:
            raise ValueError(f"Unknown direction: {direction}")

        p_raw = _smoothed_prob(hits_raw)
        p_role = _smoothed_prob(hits_role)

        if direction == "OVER":
            hits_close_raw = stat_raw_close_arr > line
            hits_close_role = stat_role_close_arr > line
        else:
            hits_close_raw = stat_raw_close_arr < line
            hits_close_role = stat_role_close_arr < line

        p_close_raw = _smoothed_prob(hits_close_raw)
        p_close_role = _smoothed_prob(hits_close_role)

    else:
        # ----- SINGLE STAT: existing logic -----
        # Build correlated z_rate from z_minutes and an independent component
        if _rate_min_corr != 0.0 and z_min_used is not None:
            z_rate = _rate_min_corr * z_min_used + np.sqrt(max(0.0, 1.0 - _rate_min_corr ** 2)) * z_rate_indep
        else:
            z_rate = z_rate_indep

        # ----------------------------------------------------------------
        # Rate draws: log-normal for right-skew (fixes UNDER bias from
        # symmetric Normal overestimating left-tail / low-stat outcomes).
        # E[rate] = rate_mu, Var[rate] ≈ rate_sd² (same moments as Normal).
        # ----------------------------------------------------------------
        _use_lognormal = bool(_bcfg.get("lognormal_rate", False))
        _POISSON_STATS = frozenset({"FG3M", "3PM", "THREES", "BLK", "STL", "TOV", "AST", "REB"})
        _use_poisson = bool(_bcfg.get("poisson_count", False)) and stat_u in _POISSON_STATS

        if _use_lognormal and rate_mu_raw > 0 and rate_sd_raw > 0:
            _cv2_raw = (rate_sd_raw / rate_mu_raw) ** 2
            _sig_ln_raw = float(np.sqrt(np.log1p(_cv2_raw)))
            _mu_ln_raw = float(np.log(rate_mu_raw)) - 0.5 * _sig_ln_raw ** 2
            rate_raw = np.exp(_mu_ln_raw + _sig_ln_raw * z_rate)
        else:
            rate_raw = np.clip(rate_mu_raw + rate_sd_raw * z_rate, 0.0, None)

        if _use_lognormal and rate_mu_role > 0 and rate_sd_role > 0:
            _cv2_role = (rate_sd_role / rate_mu_role) ** 2
            _sig_ln_role = float(np.sqrt(np.log1p(_cv2_role)))
            _mu_ln_role = float(np.log(rate_mu_role)) - 0.5 * _sig_ln_role ** 2
            rate_role = np.exp(_mu_ln_role + _sig_ln_role * z_rate)
        else:
            rate_role = np.clip(rate_mu_role + rate_sd_role * z_rate, 0.0, None)

        # Asymmetric blowout rate adjustment: boost/penalise per-min rate
        # in blowout draws only (close draws are untouched).
        if _asym_enabled and _blow_rate_mult != 1.0:
            rate_raw[blow_mask] *= _blow_rate_mult
            rate_role[blow_mask] *= _blow_rate_mult

        # Stat outcome: Poisson for count stats (discrete, non-negative),
        # continuous product for PTS / combo stats.
        if _use_poisson:
            stat_raw = rng.poisson(np.maximum(0.0, rate_raw * minutes)).astype(float)
            stat_role = rng.poisson(np.maximum(0.0, rate_role * minutes)).astype(float)
        else:
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
        z_rate_close_indep = rng.standard_normal(sims)

        if _rate_min_corr != 0.0:
            z_rate_close_only = _rate_min_corr * z_min_close_only + np.sqrt(max(0.0, 1.0 - _rate_min_corr ** 2)) * z_rate_close_indep
        else:
            z_rate_close_only = z_rate_close_indep

        minutes_close_only = np.clip(mu_close + sd_close * z_min_close_only, 0.0, 48.0)

        # Close-only rate draws: same log-normal / Poisson logic as main channel
        if _use_lognormal and rate_mu_raw > 0 and rate_sd_raw > 0:
            rate_raw_close = np.exp(_mu_ln_raw + _sig_ln_raw * z_rate_close_only)
        else:
            rate_raw_close = np.clip(rate_mu_raw + rate_sd_raw * z_rate_close_only, 0.0, None)

        if _use_lognormal and rate_mu_role > 0 and rate_sd_role > 0:
            rate_role_close = np.exp(_mu_ln_role + _sig_ln_role * z_rate_close_only)
        else:
            rate_role_close = np.clip(rate_mu_role + rate_sd_role * z_rate_close_only, 0.0, None)

        if _use_poisson:
            stat_raw_close = rng.poisson(np.maximum(0.0, rate_raw_close * minutes_close_only)).astype(float)
            stat_role_close = rng.poisson(np.maximum(0.0, rate_role_close * minutes_close_only)).astype(float)
        else:
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
        role_cfg=role_cfg,
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
    combo_over_relief_stats = {"PTS", "PRA", "PA", "PR", "RA"}
    under_blowout_sens_q_min = 0.15
    try:
        blowout_role_step = float((role_cfg or {}).get("blowout_role_step", 0.01))
    except Exception:
        blowout_role_step = 0.01
    blowout_role_step = float(max(0.0, blowout_role_step))
    try:
        combo_over_high_q_relief_min_q = float((role_cfg or {}).get("combo_over_high_q_relief_min_q", 0.30))
    except Exception:
        combo_over_high_q_relief_min_q = 0.30
    try:
        combo_over_high_q_relief_step = float((role_cfg or {}).get("combo_over_high_q_relief_step", 0.12))
    except Exception:
        combo_over_high_q_relief_step = 0.12
    combo_over_high_q_relief_step = float(max(0.0, combo_over_high_q_relief_step))

    def _role_ctx_blowout_sens_mult(direction: str, stat_name: str, outs_used: int, minutes_s_val: float, q_blowout: float) -> float:
        outs_i = max(0, int(outs_used))
        minutes_f = float(minutes_s_val)
        q_f = float(q_blowout)
        stat_norm = str(stat_name).upper().strip()
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
                over_mult = float(np.clip(base + blowout_role_step, 0.55, 0.90))
                if stat_norm in combo_over_relief_stats and q_f >= combo_over_high_q_relief_min_q:
                    over_mult = float(np.clip(over_mult - combo_over_high_q_relief_step, 0.55, 0.90))
                return over_mult
            if is_bench_like:
                return float(np.clip(base - blowout_role_step, 0.55, 0.90))
        return base

    blowout_sens_mult = _role_ctx_blowout_sens_mult(
        str(direction),
        str(stat_u),
        role_ctx_outs_used_early,
        float(minutes_s),
        float(q),
    )
    blowout_sens_mult = float(
        float(blowout_sens_mult) * float(blowout_rule_debug.get("sensitivity_mult", 1.0))
    )

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

    _post_sim_exp = float((blowout_cfg or {}).get("post_sim_exponent", 1.35))
    _post_sim_crossover = float(_curve_cfg.get("crossover", 14.0))

    p_adj = float(
        adjust_probability_for_blowout(
            p_raw=float(p_role),
            blowout_risk=float(q),
            sens=float(minutes_s_blowout),
            direction=str(direction),
            post_sim_exponent=_post_sim_exp,
            base_minutes=float(mu_close),
            curve_crossover=_post_sim_crossover,
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
            post_sim_exponent=_post_sim_exp,
            base_minutes=float(mu_close),
            curve_crossover=_post_sim_crossover,
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

    # UNDER-side fragility: measures overshoot above 0.50 scaled by q_blowout
    # and dampens overconfident UNDER probabilities toward 0.50.
    under_frag, under_frag_gap, under_frag_gap_usage = _under_fragility(
        p_adj=float(p_adj),
        p_close_adj=float(p_close_adj),
        usage_dep_eff=float(usage_dep_eff),
        direction=str(direction),
        q_blowout=float(q),
    )
    p_adj_pre_under_frag_dampen = float(p_adj)
    if under_frag > 0.0:
        p_adj, under_frag_dampen_amount = _apply_under_fragility_dampener(
            p_adj=float(p_adj),
            p_close_adj=float(p_close_adj),
            under_frag=float(under_frag),
            cfg=cfg,
        )
        # Also update fragility to reflect the UNDER-side value
        frag = float(under_frag)
        frag_abs = float(under_frag_gap_usage)
    else:
        under_frag_dampen_amount = 0.0

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
        "q_blowout_spread_only": float(_blowout_enrich_debug.get("q_spread", q)),
        "q_blowout_team_adj": float(_blowout_enrich_debug.get("q_team_adj", 0.0)),
        "q_blowout_matchup_adj": float(_blowout_enrich_debug.get("q_matchup_adj", 0.0)),
        "minutes_s": float(minutes_s),
        "blowout_minute_drop_base": float(minute_drop_base),
        "blowout_minute_drop": float(minute_drop),
        "blowout_rule_minute_drop_mult": float(blowout_rule_debug.get("minute_drop_mult", 1.0)),
        "blowout_rule_sensitivity_mult": float(blowout_rule_debug.get("sensitivity_mult", 1.0)),
        "blowout_rule_count": int(len(blowout_rule_debug.get("applied_rules", []))),
        "blowout_rules_applied": "|".join(str(x) for x in blowout_rule_debug.get("applied_rules", [])),
        "minutes_s_blowout": float(minutes_s_blowout),
        "under_blowout_sens_mult": float(under_blowout_sens_mult),
        "under_blowout_sens_eligible": bool(under_blowout_sens_eligible),
        "minutes_s_close": float(minutes_s_close),  # ✅ new: shows reduced close sensitivity
        "is_star": bool(is_star),
        "rotation_tier": str(_rot_tier),
        "blowout_minute_delta": float(minute_delta),
        "blowout_base_min_for_curve": float(_base_min_for_curve),

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

        # UNDER-side fragility (blowout-dependence dampener)
        "under_frag": float(under_frag),
        "under_frag_gap": float(under_frag_gap),
        "under_frag_gap_usage": float(under_frag_gap_usage),
        "under_frag_dampen_amount": float(under_frag_dampen_amount),
        "p_adj_pre_under_frag_dampen": float(p_adj_pre_under_frag_dampen),

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
        "crafted_role_workload_enabled": bool(crafted_role_workload_enabled),
        "role_ctx_mult": float(role_mult),
        "role_ctx_mult_raw": float(role_mult_raw),
        "role_ctx_rate_mult": float(rate_mu_role_mult),
        "role_ctx_rate_mult_raw": float(rate_mu_role_mult_raw),
        "role_ctx_rate_clamp_lo": float(rate_mu_role_clamp_lo),
        "role_ctx_rate_clamp_hi": float(rate_mu_role_clamp_hi),
        "role_ctx_rate_softcap_k": float(rate_mu_role_softcap_k),
        "role_ctx_sigma_mult": float(role_sigma_mult),
        "role_ctx_reason": str(role_reason),
        "role_ctx_damp_applied": ",".join(_damp_applied) if _damp_applied else "",
        "zero_dnp_mult": float(_zero_dnp_mult),
        "zero_dnp_debug": str(_zero_dnp_debug),

        # Recent form + opponent defense diagnostics
        "recent_form_blend": float(_recent_form_blend),
        "opp_defense_strength": float(_opp_defense_strength),
        **{f"form_{k}": v for k, v in _form_debug.items()},

        "games_used": int(s.get("games", 0)),
        "thin_window_mult": float(_thin_mult if 0 < _games_used < _thin_window_games else 1.0),

        # Playoff regime diagnostics
        "is_playoff": bool(_is_playoff),
        "playoff_rate_applied": str(_playoff_rate_applied),
        "playoff_min_applied": str(_playoff_min_applied),
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

    return out

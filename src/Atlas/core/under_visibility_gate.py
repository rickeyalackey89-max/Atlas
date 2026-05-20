"""Selection-only gate for playable STANDARD unders.

This does not rewrite model probability. It only decides whether an UNDER leg is
eligible for slip builders. The goal is to avoid treating every modeled under as
builder-playable when the market and injury/minute context do not support it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _section_cfg(cfg: dict[str, Any] | None, section: str) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    raw = cfg.get(section, {})
    return raw if isinstance(raw, dict) else {}


def _num(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float(default), index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.astype("float64")


def _str(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=object)
    return df[col].map(lambda value: default if value is None else str(value))


def _probability_surface(df: pd.DataFrame, preferred: str | None = None) -> pd.Series:
    for col in [preferred, "p_eff", "p_cal_marketed", "p_cal", "p_for_cal", "p_adj", "p"]:
        if col and col in df.columns:
            return _num(df, col, default=np.nan)
    return pd.Series(0.5, index=df.index, dtype="float64")


def _exact_market_probability(df: pd.DataFrame) -> pd.Series:
    direct = _num(df, "external_prior_market_prob", default=np.nan)
    if direct.notna().any():
        return direct

    sources = _str(df, "external_prior_sources").str.lower()
    exact_market = sources.str.contains("bettingpros_market", regex=False, na=False)
    delta = _num(df, "external_prior_delta_p", default=np.nan)
    cap = _num(df, "external_prior_cap_applied", default=np.nan)
    p_adj = _num(df, "p_adj", default=np.nan)

    # external_prior_delta_p = cap * ((market_prob - p_adj) / 0.5)
    inferred = p_adj + ((delta / cap.replace(0.0, np.nan)) * 0.5)
    inferred = inferred.where(exact_market).clip(lower=0.0, upper=1.0)
    return inferred


def under_visibility_mask(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None,
    *,
    section: str,
    probability_col: str | None = None,
) -> pd.Series:
    """Return True for rows visible to the builder under the section's policy."""

    if df.empty:
        return pd.Series(True, index=df.index, dtype=bool)

    section_cfg = _section_cfg(cfg, section)
    gate = section_cfg.get("under_visibility", {})
    if not isinstance(gate, dict) or not bool(gate.get("enabled", False)):
        return pd.Series(True, index=df.index, dtype=bool)

    direction = _str(df, "direction").str.strip().str.upper()
    tier = _str(df, "tier").str.strip().str.upper()
    stat = _str(df, "stat").str.strip().str.upper()
    under = direction == "UNDER"

    allowed = under.copy()
    if bool(gate.get("standard_only", True)):
        allowed &= tier == "STANDARD"

    excluded_stats = {
        str(item).strip().upper()
        for item in gate.get("excluded_stats", [])
        if str(item).strip()
    }
    if excluded_stats:
        allowed &= ~stat.isin(excluded_stats)

    p_model = _probability_surface(df, probability_col)
    min_model_prob = gate.get("min_model_prob", None)
    max_model_prob = gate.get("max_model_prob", None)
    if min_model_prob not in (None, ""):
        allowed &= p_model >= float(min_model_prob)
    if max_model_prob not in (None, "") and float(max_model_prob) > 0.0:
        allowed &= p_model <= float(max_model_prob)

    sources = _str(df, "external_prior_sources").str.lower()
    exact_market = sources.str.contains("bettingpros_market", regex=False, na=False)
    if bool(gate.get("require_exact_market", False)):
        allowed &= exact_market

    market_prob = _exact_market_probability(df)
    min_market_prob = gate.get("min_market_prob", None)
    if min_market_prob not in (None, ""):
        allowed &= market_prob >= float(min_market_prob)

    max_q_out_frac = gate.get("max_q_out_frac", None)
    if max_q_out_frac not in (None, ""):
        allowed &= _num(df, "q_out_frac", default=0.0).fillna(0.0) <= float(max_q_out_frac)

    max_minute_risk_score = gate.get("max_minute_risk_score", None)
    if max_minute_risk_score not in (None, ""):
        allowed &= _num(df, "minute_risk_score", default=0.0).fillna(0.0) <= float(max_minute_risk_score)

    require_main_line = bool(gate.get("require_main_line", False))
    if require_main_line and "is_main" in df.columns:
        is_main = _str(df, "is_main").str.strip().str.lower().isin({"1", "true", "yes", "y"})
        allowed &= is_main

    return (~under) | allowed


def apply_under_visibility_gate(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None,
    *,
    section: str,
    probability_col: str | None = None,
) -> pd.DataFrame:
    """Drop UNDER rows that are not builder-playable under the configured gate."""

    mask = under_visibility_mask(df, cfg, section=section, probability_col=probability_col)
    return df.loc[mask].reset_index(drop=True)


from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


_MODELED_MINUTE_COLUMNS = (
    "minutes_projection",
    "projected_minutes",
    "role_metrics_minutes_projection",
    "min_mean",
)


def _merge_guard_config(config: dict[str, Any] | None, *, section: str | None = None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}

    direct_keys = {
        "enabled",
        "min_modeled_minutes",
        "bench_minutes_threshold",
        "max_minutes_cv",
        "low_modeled_minutes_penalty",
        "bench_under_18_min_penalty",
        "minutes_cv_penalty",
        "injury_uncertainty_penalty",
        "max_total_penalty",
    }

    merged: dict[str, Any] = {}
    if any(k in config for k in direct_keys):
        merged.update(config)

    global_cfg = config.get("minute_risk_guard")
    if isinstance(global_cfg, dict):
        merged.update(global_cfg)

    if section:
        section_cfg = config.get(section)
        if isinstance(section_cfg, dict):
            section_guard = section_cfg.get("minute_risk_guard")
            if isinstance(section_guard, dict):
                merged.update(section_guard)

    return merged


def _numeric_col(df: pd.DataFrame, col: str, default: float = np.nan) -> np.ndarray:
    if col not in df.columns:
        return np.full(len(df.index), float(default), dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    arr = np.asarray(values.to_numpy(copy=True), dtype="float64")
    if default == default:
        arr[np.isnan(arr)] = float(default)
    return arr


def _first_available_modeled_minutes(df: pd.DataFrame) -> np.ndarray:
    modeled = np.full(len(df.index), np.nan, dtype="float64")
    for col in _MODELED_MINUTE_COLUMNS:
        if col not in df.columns:
            continue
        vals = _numeric_col(df, col, default=np.nan)
        mask = np.isnan(modeled) & np.isfinite(vals) & (vals > 0.0)
        modeled[mask] = vals[mask]
    return modeled


def compute_minute_risk_guard(
    df: pd.DataFrame,
    config: dict[str, Any] | None,
    *,
    section: str | None = None,
) -> pd.DataFrame:
    """Return minute-risk guard telemetry for each leg.

    The guard is intentionally selection-layer only. It does not rewrite calibrated
    model probability; callers decide whether to subtract the penalty from a
    ranking column.
    """

    guard = _merge_guard_config(config, section=section)
    if not bool(guard.get("enabled", False)):
        return pd.DataFrame(index=df.index)

    modeled = _first_available_modeled_minutes(df)
    min_mean = _numeric_col(df, "min_mean", default=np.nan)
    min_std = _numeric_col(df, "min_std", default=0.0)

    denom = np.where(np.isfinite(min_mean) & (min_mean > 0.0), min_mean, modeled)
    minutes_cv = np.full(len(df.index), np.nan, dtype="float64")
    valid_cv = np.isfinite(denom) & (denom > 0.0)
    minutes_cv[valid_cv] = np.clip(min_std[valid_cv] / denom[valid_cv], 0.0, 5.0)

    min_modeled = float(guard.get("min_modeled_minutes", 16.0) or 16.0)
    bench_threshold = float(guard.get("bench_minutes_threshold", 18.0) or 18.0)
    max_cv = float(guard.get("max_minutes_cv", 0.35) or 0.35)

    bench_penalty = float(guard.get("bench_under_18_min_penalty", 0.10) or 0.10)
    low_min_penalty = float(guard.get("low_modeled_minutes_penalty", bench_penalty) or bench_penalty)
    cv_penalty = float(guard.get("minutes_cv_penalty", 0.08) or 0.08)
    injury_penalty = float(guard.get("injury_uncertainty_penalty", 0.12) or 0.12)
    max_total = float(guard.get("max_total_penalty", 0.25) or 0.25)

    valid_min = np.isfinite(modeled) & (modeled > 0.0)
    low_min_mask = valid_min & (modeled < min_modeled)
    bench_mask = valid_min & (modeled >= min_modeled) & (modeled < bench_threshold)
    cv_mask = np.isfinite(minutes_cv) & (minutes_cv > max_cv)

    injury_mask = np.zeros(len(df.index), dtype=bool)
    if "is_questionable" in df.columns:
        injury_mask |= _numeric_col(df, "is_questionable", default=0.0) > 0.0
    if "q_out_frac" in df.columns:
        injury_mask |= _numeric_col(df, "q_out_frac", default=0.0) > 0.0

    penalty = np.zeros(len(df.index), dtype="float64")
    penalty += np.where(low_min_mask, low_min_penalty, 0.0)
    penalty += np.where(bench_mask, bench_penalty, 0.0)
    penalty += np.where(cv_mask, cv_penalty, 0.0)
    penalty += np.where(injury_mask, injury_penalty, 0.0)
    np.clip(penalty, 0.0, max_total, out=penalty)

    flags: list[str] = []
    for i in range(len(df.index)):
        parts: list[str] = []
        if low_min_mask[i]:
            parts.append("low_modeled_minutes")
        if bench_mask[i]:
            parts.append("bench_under_18_minutes")
        if cv_mask[i]:
            parts.append("high_minutes_cv")
        if injury_mask[i]:
            parts.append("injury_uncertainty")
        flags.append(",".join(parts))

    score = np.zeros(len(df.index), dtype="float64")
    if max_total > 0.0:
        score = np.clip(penalty / max_total, 0.0, 1.0)

    return pd.DataFrame(
        {
            "modeled_minutes": modeled,
            "minutes_cv": minutes_cv,
            "minute_risk_penalty": penalty,
            "minute_risk_score": score,
            "minute_risk_flags": flags,
        },
        index=df.index,
    )


def apply_minute_risk_guard(
    df: pd.DataFrame,
    config: dict[str, Any] | None,
    *,
    section: str | None = None,
    score_col: str | None = None,
) -> pd.DataFrame:
    out = df.copy()
    guard = compute_minute_risk_guard(out, config, section=section)
    if guard.empty:
        return out

    for col in guard.columns:
        out[col] = guard[col]

    if score_col and score_col in out.columns:
        score = pd.to_numeric(out[score_col], errors="coerce")
        if not isinstance(score, pd.Series):
            score = pd.Series(score, index=out.index)
        score_arr = np.asarray(score.to_numpy(copy=True), dtype="float64")
        score_arr[np.isnan(score_arr)] = 0.0
        penalty_arr = np.asarray(out["minute_risk_penalty"].to_numpy(copy=False), dtype="float64")
        out[f"{score_col}_before_minute_guard"] = score_arr
        out[score_col] = np.clip(score_arr - penalty_arr, 0.0, 1.0)
        if score_col == "p_eff":
            out["p_select"] = out[score_col]

    return out

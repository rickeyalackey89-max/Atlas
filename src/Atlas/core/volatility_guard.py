from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_LOW_LINE_THRESHOLDS = {
    "FG3M": 1.5,
    "PTS": 5.5,
    "REB": 2.5,
    "AST": 2.5,
    "PR": 7.5,
    "PA": 7.5,
    "RA": 7.5,
    "PRA": 9.5,
}


def _section(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    cfg = config.get("volatility_guard")
    return cfg if isinstance(cfg, dict) else {}


def _num(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.full(len(df), default, dtype="float64"), index=df.index)
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    if default == default:
        values = values.fillna(default)
    return values


def _line_bucket(stat: str, line: float, thresholds: dict[str, float]) -> str:
    if not np.isfinite(line):
        return "unknown"
    threshold = thresholds.get(stat)
    if threshold is None:
        return "other"
    return f"low_{stat}" if line <= threshold else f"normal_{stat}"


def apply_volatility_telemetry(df: pd.DataFrame, config: dict[str, Any] | None) -> pd.DataFrame:
    """Attach report-only volatility telemetry.

    This helper intentionally does not mutate probability columns. It exists so
    live and replay outputs expose the same fragility signals that the audit uses.
    Any p_select penalty must be promoted separately by audit evidence.
    """

    cfg = _section(config)
    if not (bool(cfg.get("report_only", False)) or bool(cfg.get("enabled", False))):
        return df

    out = df.copy()
    thresholds_cfg = cfg.get("low_line_thresholds")
    thresholds = DEFAULT_LOW_LINE_THRESHOLDS.copy()
    if isinstance(thresholds_cfg, dict):
        for key, value in thresholds_cfg.items():
            try:
                thresholds[str(key).upper()] = float(value)
            except Exception:
                continue

    stat = out.get("stat", pd.Series("", index=out.index)).astype(str).str.upper().str.strip()
    direction = out.get("direction", pd.Series("", index=out.index)).astype(str).str.upper().str.strip()
    line = _num(out, "line", default=np.nan)

    buckets = [_line_bucket(s, float(v), thresholds) for s, v in zip(stat, line)]
    out["volatility_line_bucket"] = buckets
    out["volatility_low_line"] = pd.Series(buckets, index=out.index).str.startswith("low_")

    min_mean = _num(out, "min_mean", default=np.nan)
    min_std = _num(out, "min_std", default=np.nan)
    rate_mean = _num(out, "rate_mean", default=np.nan)
    rate_std = _num(out, "rate_std", default=np.nan)

    minutes_cv = np.where(min_mean > 0.0, (min_std / min_mean).clip(0.0, 5.0), np.nan)
    rate_cv = np.where(rate_mean.abs() > 1e-9, (rate_std / rate_mean.abs()).clip(0.0, 10.0), np.nan)

    max_minutes_cv = float(cfg.get("max_minutes_cv", 0.35) or 0.35)
    max_rate_cv = float(cfg.get("max_rate_cv", 0.95) or 0.95)
    fg3m_low_line_threshold = float(cfg.get("low_line_fg3m_threshold", 1.5) or 1.5)

    out["volatility_minutes_cv"] = minutes_cv
    out["volatility_rate_cv"] = rate_cv
    out["volatility_low_line_minutes_cv"] = out["volatility_low_line"] & (pd.Series(minutes_cv, index=out.index) > max_minutes_cv)
    out["volatility_low_line_rate_cv"] = out["volatility_low_line"] & (pd.Series(rate_cv, index=out.index) > max_rate_cv)
    out["volatility_fg3m_low_line"] = (stat == "FG3M") & (direction == "OVER") & (line <= fg3m_low_line_threshold)

    flags: list[str] = []
    for i in range(len(out)):
        parts: list[str] = []
        if bool(out["volatility_low_line_minutes_cv"].iloc[i]):
            parts.append("low_line_minutes_cv")
        if bool(out["volatility_low_line_rate_cv"].iloc[i]):
            parts.append("low_line_rate_cv")
        if bool(out["volatility_fg3m_low_line"].iloc[i]):
            parts.append("fg3m_low_line_over")
        flags.append(",".join(parts))
    out["volatility_report_flags"] = flags
    out["volatility_report_flagged"] = [bool(x) for x in flags]
    return out

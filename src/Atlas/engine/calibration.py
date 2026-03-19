from __future__ import annotations

"""
src/Atlas/engine/calibration.py

Phase 7A-2 — Calibration Layer Injection (BONUS-ONLY)

User intent (locked):
- Last-10 signal provides a BOOST only when player is "hot" (8/10 to 10/10).
- No penalty / no docking when last10 is mediocre or below the threshold.
- This is not regression-to-mean; it's a one-sided bonus.

Implementation:
- If last10 is missing/NaN -> no-op
- If last10 < threshold -> no-op
- If last10 <= p -> no-op (never dock, never shrink downward)
- Otherwise apply logit-space shrink toward last10:
    p_bonus = sigmoid( (1-k)*logit(p) + k*logit(last10) )

Defaults aligned to telemetry baseline:
- clamp p and last10 into [0.03, 0.97] before logit
"""

from typing import Optional
import numpy as np

_P_MIN = 0.03
_P_MAX = 0.97


def _clamp(p: np.ndarray) -> np.ndarray:
    return np.clip(p, _P_MIN, _P_MAX)


def logit(p: np.ndarray) -> np.ndarray:
    p = _clamp(p)
    return np.log(p / (1.0 - p))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def apply_last10_bonus_logit(
    p: np.ndarray,
    last10: np.ndarray,
    k: float,
    threshold: float = 0.80,
) -> np.ndarray:
    """
    One-sided last10 bonus.

    Applies only when:
      - last10 is finite
      - last10 >= threshold
      - last10 > p  (so we never decrease p)

    Otherwise returns original p.
    """
    k = float(np.clip(k, 0.0, 1.0))
    thr = float(threshold)

    p = p.astype(float, copy=False)
    last10 = last10.astype(float, copy=False)

    out = p.copy()

    if k <= 0.0:
        return out

    m = np.isfinite(last10) & (last10 >= thr) & np.isfinite(p) & (last10 > p)
    if not np.any(m):
        return out

    lp = logit(p[m])
    ll = logit(last10[m])
    out[m] = sigmoid((1.0 - k) * lp + k * ll)
    return out


def apply_last10_bonus_logit_scalar(
    p: float,
    last10: Optional[float],
    k: float,
    threshold: float = 0.80,
) -> float:
    if last10 is None:
        return float(p)
    try:
        last10_f = float(last10)
    except Exception:
        return float(p)
    if not np.isfinite(last10_f):
        return float(p)
    p_f = float(p)
    if not np.isfinite(p_f):
        return float(p_f)
    if last10_f < float(threshold) or last10_f <= p_f:
        return float(p_f)
    p_arr = np.array([p_f], dtype=float)
    l_arr = np.array([last10_f], dtype=float)
    return float(apply_last10_bonus_logit(p_arr, l_arr, k, threshold=float(threshold))[0])

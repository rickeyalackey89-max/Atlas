# src/blowout.py
from __future__ import annotations
import math
from dataclasses import dataclass

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

@dataclass(frozen=True)
class BlowoutInputs:
    spread_abs: float | None = None
    rating_diff: float | None = None
    rest_diff: int | None = None
    pace_diff: float | None = None

def blowout_risk(inp: BlowoutInputs) -> float:
    score = 0.0
    weight_sum = 0.0

    if inp.spread_abs is not None:
        s = _sigmoid((inp.spread_abs - 6.0) / 3.0)
        score += 0.60 * s
        weight_sum += 0.60

    if inp.rating_diff is not None:
        r = _sigmoid((abs(inp.rating_diff) - 5.0) / 3.0)
        score += 0.25 * r
        weight_sum += 0.25

    if inp.rest_diff is not None:
        rd = abs(inp.rest_diff)
        rr = _clamp01(rd / 2.0)
        score += 0.10 * rr
        weight_sum += 0.10

    if inp.pace_diff is not None:
        pd = abs(inp.pace_diff)
        pr = _clamp01(pd / 8.0)
        score += 0.05 * pr
        weight_sum += 0.05

    if weight_sum == 0.0:
        return 0.20

    return _clamp01(score / weight_sum)

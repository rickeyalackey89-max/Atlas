from __future__ import annotations

"""src/Atlas/legacy/pp_pricing.py

PrizePicks pricing kernel (tier modifiers) expressed in probability space.

We model a per-leg factor f such that:

    M_pp = M_base * Π f_i

where M_base is the standard POWER_MULT (e.g., 20x for 5-leg Power), and each
leg factor f_i depends on (tier, stat, p_adj).

Model forms (config-driven):
    STANDARD: f = 1
    GOBLIN:   log f = a + b * logit(p)
    DEMON:    log f = a + b * logit(p) + c * logit(p)^2

All coefficients live in config.yaml under pp_kernel.coeffs.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _norm_stat(stat: Any) -> str:
    s = str(stat or "").strip().upper()
    # legacy aliases
    if s == "3PM":
        return "FG3M"
    return s


@dataclass(frozen=True)
class Kernel:
    p_min: float
    p_max: float
    coeffs: Dict[str, Dict[str, Dict[str, float]]]

    def coef_for(self, stat: str, tier: str) -> Dict[str, float] | None:
        stat = _norm_stat(stat)
        # prefer an explicit presence check so an empty per-stat dict is honored
        if stat in self.coeffs:
            by_stat = self.coeffs[stat]
        else:
            by_stat = self.coeffs.get("DEFAULT", {})

        tier_u = str(tier or "STANDARD").strip().upper() or "STANDARD"
        return by_stat.get(tier_u)


def load_kernel(cfg: dict[str, Any] | None) -> Kernel:
    cfg = cfg or {}
    pk = cfg.get("pp_kernel", {}) or {}
    p_min = float(pk.get("p_min", 0.01))
    p_max = float(pk.get("p_max", 0.99))
    coeffs = pk.get("coeffs", {}) or {}
    return Kernel(p_min=p_min, p_max=p_max, coeffs=coeffs)


def leg_factor(*, p_adj: float, tier: str, stat: str, kernel: Kernel) -> float:
    tier_u = str(tier or "STANDARD").strip().upper() or "STANDARD"

    c = kernel.coef_for(stat, tier_u)
    if not c:
        # unknown tier/stat -> neutral
        return 1.0

    p = _clamp(float(p_adj), kernel.p_min, kernel.p_max)
    x = _logit(p)
    a = float(c.get("a", 0.0))
    b = float(c.get("b", 0.0))
    if tier_u == "GOBLIN":
        y = a + b * x
    else:
        cc = float(c.get("c", 0.0))
        y = a + b * x + cc * (x * x)

    # exp(log f)
    try:
        f = math.exp(y)
    except OverflowError:
        f = 1.0

    # Safety clamp – prevents extreme factors from exploding EV.
    # You can widen/tighten via calibration later.
    if not math.isfinite(f):
        return 1.0
    return float(_clamp(f, 0.05, 20.0))


def power_multiplier(*, base_mult: float, legs: list[dict[str, Any]], kernel: Kernel) -> float:
    """Compute a PP-kernel-adjusted Power multiplier."""
    mult = float(base_mult)
    for leg in legs:
        p = 0.5
        for key in ("p_cal", "p_for_cal", "p_close_role", "p_close_adj", "p_role", "p_adj", "p_eff"):
            candidate = leg.get(key, None)
            try:
                candidate_f = float(candidate)
            except Exception:
                continue
            if math.isfinite(candidate_f):
                p = candidate_f
                break
        tier = str(leg.get("tier", leg.get("type", "STANDARD")) or "STANDARD")
        stat = str(leg.get("stat", leg.get("market", "")) or "")
        mult *= leg_factor(p_adj=p, tier=tier, stat=stat, kernel=kernel)
    return float(mult)

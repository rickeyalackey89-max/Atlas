# src/minutes.py
from __future__ import annotations

def minutes_sensitivity(market: str) -> float:
    m = market.strip().lower()

    high = {"points", "pts", "pra", "pa", "pr", "ra"}
    medium = {"rebounds", "reb", "assists", "ast"}
    low = {"3pt", "threes", "3pm", "fg3m", "fg3a"}
    lowest = {"steals", "stl", "blocks", "blk", "stocks"}

    if m in high:
        return 1.00
    if m in medium:
        return 0.70
    if m in low:
        return 0.45
    if m in lowest:
        return 0.30

    return 0.60

def adjust_probability_for_blowout(
    p_raw: float,
    blowout_risk: float,
    sens: float,
    *,
    direction: str | None = None,
    post_sim_exponent: float | None = None,
    base_minutes: float | None = None,
    curve_crossover: float = 14.0,
) -> float:
    """Post-sim blowout probability adjustment with continuous minute curve.

    Players above ``curve_crossover`` baseline minutes are attenuated (starters
    lose production in blowouts).  Players below crossover get a gentle boost
    (bench gains garbage-time minutes).  The magnitude scales linearly with
    distance from the crossover.
    """
    exponent = 1.35 if post_sim_exponent is None else float(post_sim_exponent)
    risk = max(0.0, min(1.0, float(blowout_risk) * float(sens)))

    # Continuous curve: scale effect strength by baseline minutes
    if base_minutes is not None and base_minutes > 0:
        # Normalise so 36-min player -> +1.0 scale, crossover -> 0, bench below -> negative
        curve_scale = (float(base_minutes) - curve_crossover) / max(1.0, 36.0 - curve_crossover)
        curve_scale = max(-0.5, min(1.0, curve_scale))
    else:
        curve_scale = 0.5  # moderate default when minutes unknown

    effective_risk = risk * abs(curve_scale)

    direction_u = str(direction or "").strip().upper()

    if curve_scale >= 0:
        # Above crossover: attenuate (starters lose production)
        attenuation = (1.0 - effective_risk) ** exponent
        if direction_u == "UNDER":
            p_adj = 1.0 - ((1.0 - float(p_raw)) * attenuation)
        else:
            p_adj = float(p_raw) * attenuation
    else:
        # Below crossover: gentle boost (bench gains garbage-time production)
        boost = effective_risk * exponent * 0.01  # conservative boost factor
        if direction_u == "UNDER":
            p_adj = float(p_raw) - boost  # UNDER less likely (bench plays more → more stats)
        else:
            p_adj = float(p_raw) + boost  # OVER more likely
    return max(0.03, min(0.97, p_adj))

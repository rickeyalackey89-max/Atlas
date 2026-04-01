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
) -> float:
    exponent = 1.35 if post_sim_exponent is None else float(post_sim_exponent)
    risk = max(0.0, min(1.0, float(blowout_risk) * float(sens)))
    attenuation = (1.0 - risk) ** exponent
    direction_u = str(direction or "").strip().upper()
    if direction_u == "UNDER":
        p_adj = 1.0 - ((1.0 - float(p_raw)) * attenuation)
    else:
        p_adj = float(p_raw) * attenuation
    return max(0.03, min(0.97, p_adj))

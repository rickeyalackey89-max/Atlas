# src/minutes.py
from __future__ import annotations

def minutes_sensitivity(market: str) -> float:
    m = market.strip().lower()

    high = {"points", "pra", "pa", "pr", "ra"}
    medium = {"rebounds", "assists"}
    low = {"3pt", "threes", "3pm"}
    lowest = {"steals", "blocks", "stocks"}

    if m in high:
        return 1.00
    if m in medium:
        return 0.70
    if m in low:
        return 0.45
    if m in lowest:
        return 0.30

    return 0.60

def adjust_probability_for_blowout(p_raw: float, blowout_risk: float, sens: float) -> float:
    p_adj = p_raw * (1.0 - blowout_risk * sens)
    return max(0.03, min(0.97, p_adj))

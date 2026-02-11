# src/slip_scoring.py
from __future__ import annotations
from collections import Counter

def prob_all_hit(ps: list[float]) -> float:
    out = 1.0
    for p in ps:
        out *= p
    return out

def diversity_penalty(legs: list[dict], mode: str) -> float:
    mode = mode.lower()
    w_same_game = 0.10 if mode == "power" else 0.06
    w_same_team = 0.06 if mode == "power" else 0.04
    w_same_player = 0.12 if mode == "power" else 0.07
    w_same_market = 0.05 if mode == "power" else 0.03

    games = Counter([l.get("game_id") for l in legs])
    teams = Counter([l.get("team") for l in legs])
    players = Counter([l.get("player") for l in legs])
    markets = Counter([l.get("market") for l in legs])

    penalty = 1.0
    for _, c in games.items():
        if c > 1: penalty *= (1.0 - w_same_game * (c - 1))
    for _, c in teams.items():
        if c > 1: penalty *= (1.0 - w_same_team * (c - 1))
    for _, c in players.items():
        if c > 1: penalty *= (1.0 - w_same_player * (c - 1))
    for _, c in markets.items():
        if c > 1: penalty *= (1.0 - w_same_market * (c - 1))

    return max(0.50, min(1.0, penalty))

def score_slip_power(legs: list[dict], p_col: str = "p_adj") -> float:
    ps = [float(l[p_col]) for l in legs]
    return prob_all_hit(ps) * diversity_penalty(legs, mode="power")

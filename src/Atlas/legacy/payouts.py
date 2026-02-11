from typing import List
from .payout_tables import PayoutTable


def ev_power(p_all: float, multiplier: float) -> float:
    """
    Expected value for a Power play where all legs must hit.
    Stake assumed = 1 unit.
    """
    return multiplier * p_all - 1.0


def ev_flex_from_phit(phit: List[float], payout: PayoutTable) -> float:
    """
    Flex EV using a Poisson-binomial DP (independent approximation).
    phit: list of per-leg hit probabilities.
    payout: a PayoutTable mapping (k_hits, n_legs) -> multiplier.
    """
    n = len(phit)
    dp = [0.0] * (n + 1)
    dp[0] = 1.0

    for p in phit:
        nxt = [0.0] * (n + 1)
        for k in range(n + 1):
            if dp[k] == 0.0:
                continue
            nxt[k] += dp[k] * (1.0 - p)
            if k + 1 <= n:
                nxt[k + 1] += dp[k] * p
        dp = nxt

    ev = 0.0
    for k in range(n + 1):
        ev += payout.multipliers.get((k, n), 0.0) * dp[k]

    return ev - 1.0

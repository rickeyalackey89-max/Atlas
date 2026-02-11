import numpy as np
import pandas as pd

from .features import summarize_stat, get_player_window, blowout_probability


def _smoothed_prob(hits: np.ndarray) -> float:
    """
    Laplace smoothing to prevent exact 0/1 probabilities due to finite Monte Carlo.

    For boolean hits with N trials:
        p = (sum(hits) + 0.5) / (N + 1.0)

    This is intentionally minimal and preserves ordering while preventing
    hard-invariant failures (p_adj == 0 unless explicitly DATA_MISSING).
    """
    n = int(hits.size)
    if n <= 0:
        return 0.0
    s = float(hits.sum())
    p = (s + 0.5) / (n + 1.0)

    # Keep it strictly inside (0,1) so downstream never sees exact 0/1.
    eps = 1e-12
    if p <= 0.0:
        return eps
    if p >= 1.0:
        return 1.0 - eps
    return float(p)


def simulate_leg_probability(
    gamelogs: pd.DataFrame,
    row: pd.Series,
    lookback: int,
    sims: int,
    spread_sd: float,
    blowout_threshold: float,
    star_minute_drop: float,
    role_minute_drop: float,
) -> dict:
    player = row["player"]
    stat = row["stat"]
    line = float(row["line"])
    direction = str(row["direction"]).upper()
    spread = float(row.get("spread", 0.0))

    g = get_player_window(gamelogs, player, lookback)
    s = summarize_stat(g, stat)

    # Heuristic: treat “stars” as players averaging high minutes
    is_star = s["min_mean"] >= 33.0
    minute_drop = star_minute_drop if is_star else role_minute_drop

    q = blowout_probability(spread=spread, threshold=blowout_threshold, sd=spread_sd)

    # Close-game minutes distribution
    mu_close = max(0.0, s["min_mean"])
    sd_close = max(1.0, s["min_std"])  # avoid zero variance

    # Blowout minutes distribution (clipped)
    mu_blow = max(0.0, mu_close - minute_drop)
    sd_blow = max(1.0, sd_close)

    # Stat-per-minute distribution
    rate_mu = s["rate_mean"]
    rate_sd = max(0.01, s["rate_std"])  # avoid zero

    rng = np.random.default_rng(42)

    # Mix close vs blowout scenarios
    u = rng.random(sims)
    minutes = np.where(
        u < q,
        rng.normal(mu_blow, sd_blow, sims),
        rng.normal(mu_close, sd_close, sims),
    )
    minutes = np.clip(minutes, 0, 48)

    # Sample per-minute rate and compute stat
    rate = rng.normal(rate_mu, rate_sd, sims)
    rate = np.clip(rate, 0, None)

    stat_vals = rate * minutes

    if direction == "OVER":
        hits = stat_vals > line
    elif direction == "UNDER":
        hits = stat_vals < line
    else:
        raise ValueError(f"Unknown direction: {direction} (expected OVER or UNDER)")

    # Smoothed probability (prevents exact 0/1 due to finite sims)
    p = _smoothed_prob(hits)

    # Fragility: recompute as if q=0 (close-only minutes)
    minutes_close_only = np.clip(rng.normal(mu_close, sd_close, sims), 0, 48)
    stat_close_only = np.clip(rng.normal(rate_mu, rate_sd, sims), 0, None) * minutes_close_only

    if direction == "OVER":
        hits_close = stat_close_only > line
    else:
        hits_close = stat_close_only < line

    p_close = _smoothed_prob(hits_close)

    # Use a *relative* fragility in [0, 1] so it remains interpretable and
    # doesn't disappear due to downstream rounding/formatting.
    #
    # Interpretation:
    #   0.00 -> blowout/minutes mixture doesn't change the hit probability
    #   0.10 -> mixture reduces hit probability by ~10% relative to close-only
    eps = 1e-9
    if p_close <= eps:
        frag = 0.0
    else:
        frag = max(0.0, (p_close - p) / p_close)

    # Keep the absolute drop too (useful for debugging / calibration)
    frag_abs = max(0.0, p_close - p)

    return {
        "p": float(p),
        "p_close": float(p_close),
        "fragility": float(frag),
        "fragility_abs": float(frag_abs),
        "is_star": bool(is_star),
        "q_blowout": float(q),
        "min_mean": float(s["min_mean"]),
        "min_std": float(s["min_std"]),
        "rate_mean": float(s["rate_mean"]),
        "rate_std": float(s["rate_std"]),
        "games_used": int(s["games"]),
    }
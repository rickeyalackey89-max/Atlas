#!/usr/bin/env python
"""
kernel_trainer_v1.py — MC Kernel Parameter Trainer

Sweeps Monte Carlo simulation parameters against the v13 resim cache,
recomputing raw p for every leg under each config, and measures Brier
score against truth.  No replays needed — pure vectorised numpy.

Two-phase approach:
  Phase 1: Coarse grid per parameter family (~30s per family)
  Phase 2: Fine grid around combined winners (~2 min)

Tunable parameter families:
  A. Variance: rate_std_multiplier per stat, rate_min_correlation
  B. Blowout: spread_sd, threshold_margin, star_minute_drop, post_sim_exponent
  C. Thin-sample: thin_window_games, thin_window_max_mult
  D. Defense/form: opp_defense_strength (requires opp_defense_rel in cache)

Usage:
  python tools/kernel_trainer_v1.py                    # full 2-phase run
  python tools/kernel_trainer_v1.py --phase 1          # coarse only
  python tools/kernel_trainer_v1.py --phase 2          # fine only (reads phase 1 yaml)
  python tools/kernel_trainer_v1.py --sims 3000        # override sim count
  python tools/kernel_trainer_v1.py --apply             # apply best to config.yaml
"""
from __future__ import annotations

import argparse
import itertools
import math
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from Atlas.core.fingerprint import build_manifest, config_fingerprint

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = REPO_ROOT / "data" / "model" / "_v13_resim_cache.pkl"
CONFIG_PATH = REPO_ROOT / "config.yaml"
RESULTS_PATH = REPO_ROOT / "tools" / "kernel_trainer_results_v1.yaml"

DEFAULT_SIMS = 1000       # coarse phase (94K legs average out MC noise)
FINE_SIMS = 2000          # fine phase
BATCH_SIZE = 10000         # legs per batch to limit memory
COARSE_SAMPLE = 30000     # subsample legs for coarse phase (0 = use all)
SEED = 42

# Current production values (read from config at runtime)
CURRENT_DEFAULTS: dict[str, Any] = {}

# Stat categories for per-stat rate_std sweeps
STAT_GROUPS: dict[str, list[str]] = {
    "PTS": ["PTS"],
    "AST": ["AST"],
    "REB": ["REB"],
    "FG3M": ["FG3M", "3PM"],
    "PRA": ["PRA"],
    "PR": ["PR"],
    "PA": ["PA"],
    "RA": ["RA"],
}

COMBO_STATS = frozenset({"PRA", "PR", "PA", "RA"})


# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------
def load_cache() -> pd.DataFrame:
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    # Ensure numeric
    for c in ["rate_mean", "rate_std", "min_mean", "min_std", "spread",
              "q_blowout", "minutes_s", "line", "games_used", "hit",
              "opp_defense_rel"]:
        if c in cv.columns:
            cv[c] = pd.to_numeric(cv[c], errors="coerce")
    cv["direction_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
    cv["is_under"] = (cv["direction_u"] == "UNDER").astype(np.float64)
    cv["is_star"] = (cv["min_mean"] >= 33.0).astype(bool)
    # Normalise stat names
    _stat_norm = {"POINTS": "PTS", "REBOUNDS": "REB", "ASSISTS": "AST",
                  "REBS": "REB", "ASTS": "AST", "3PM": "FG3M"}
    cv["stat_u"] = cv["stat_u"].replace(_stat_norm)
    print(f"Loaded {len(cv):,} legs, {cv['game_date'].nunique()} dates")
    print(f"  hit coverage: {cv['hit'].notna().sum():,} / {len(cv):,}")
    return cv


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _read_current_defaults() -> dict[str, Any]:
    cfg = load_config()
    blow = cfg.get("blowout", {}) or {}
    by_stat = blow.get("rate_std_multiplier_by_stat", {}) or {}
    return {
        "spread_sd": float(blow.get("spread_sd", 10.0)),
        "threshold_margin": float(blow.get("threshold_margin", 15.5)),
        "star_minute_drop": float(blow.get("star_minute_drop", 6.0)),
        "role_minute_drop": float(blow.get("role_minute_drop", 0.5)),
        "post_sim_exponent": float(blow.get("post_sim_exponent", 0.3)),
        "rate_std_multiplier": float(blow.get("rate_std_multiplier", 1.0)),
        "rate_std_PTS": float(by_stat.get("PTS", 1.3)),
        "rate_std_AST": float(by_stat.get("AST", 1.2)),
        "rate_std_REB": float(by_stat.get("REB", 1.0)),
        "rate_std_FG3M": float(by_stat.get("FG3M", 1.0)),
        "rate_std_PRA": float(by_stat.get("PRA", 1.3)),
        "rate_std_PR": float(by_stat.get("PR", 1.3)),
        "rate_std_PA": float(by_stat.get("PA", 1.3)),
        "rate_std_RA": float(by_stat.get("RA", 1.1)),
        "rate_min_correlation": float(blow.get("rate_min_correlation", 0.35)),
        "thin_window_games": int(blow.get("thin_window_games", 15)),
        "thin_window_max_mult": float(blow.get("thin_window_max_mult", 1.6)),
        "opp_defense_strength": float(blow.get("opp_defense_strength", 1.0)),
        "starter_minute_drop": float((blow.get("rotation_tiers", {}) or {}).get("starter_minute_drop", 3.5)),
    }


# ---------------------------------------------------------------------------
# Vectorised MC simulation
# ---------------------------------------------------------------------------
def _norm_cdf_vec(z: np.ndarray) -> np.ndarray:
    """Vectorised normal CDF using scipy.special.ndtr or erf fallback."""
    try:
        from scipy.special import ndtr
        return ndtr(z)
    except ImportError:
        from scipy.special import erf  # type: ignore
        return 0.5 * (1.0 + erf(z / np.sqrt(2.0)))


def compute_blowout_q(spread: np.ndarray, threshold: float, sd: float) -> np.ndarray:
    """Vectorised two-tailed blowout probability."""
    sd = max(1e-9, sd)
    z_hi = (threshold - spread) / sd
    z_lo = (-threshold - spread) / sd
    p_hi = 1.0 - _norm_cdf_vec(z_hi)
    p_lo = _norm_cdf_vec(z_lo)
    return np.clip(p_hi + p_lo, 0.0, 1.0)


def simulate_batch(
    rate_mean: np.ndarray,     # (N,)
    rate_std: np.ndarray,      # (N,)
    min_mean: np.ndarray,      # (N,)
    min_std: np.ndarray,       # (N,)
    line: np.ndarray,          # (N,)
    is_under: np.ndarray,      # (N,) bool
    q: np.ndarray,             # (N,) blowout probability
    minute_drop: np.ndarray,   # (N,) per-leg star/role drop
    rate_min_corr: float,
    sims: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Vectorised MC for a batch of legs. Returns p_raw (N,).

    Model: stat = rate * minutes
      minutes ~ blowout_draw ? N(min_mean - minute_drop, min_std) : N(min_mean, min_std)
      rate ~ N(rate_mean, rate_std)  [clipped >= 0]
      With optional rate-minutes correlation.
    """
    N = len(rate_mean)

    # Random draws: (N, sims)
    u = rng.random((N, sims))
    z_min = rng.standard_normal((N, sims))
    z_rate_indep = rng.standard_normal((N, sims))

    # Blowout mask
    blow_mask = u < q[:, None]

    # Minutes: blowout draws get reduced mean
    mu_close = min_mean[:, None]
    mu_blow = np.maximum(0.0, min_mean[:, None] - minute_drop[:, None])
    sd_min = np.maximum(1.0, min_std[:, None])

    minutes = np.where(blow_mask, mu_blow + sd_min * z_min, mu_close + sd_min * z_min)
    minutes = np.clip(minutes, 0.0, 48.0)

    # Rate with optional correlation to minutes
    if rate_min_corr != 0.0:
        z_rate = rate_min_corr * z_min + np.sqrt(max(0.0, 1.0 - rate_min_corr ** 2)) * z_rate_indep
    else:
        z_rate = z_rate_indep

    rate = rate_mean[:, None] + rate_std[:, None] * z_rate
    rate = np.clip(rate, 0.0, None)

    # Stat outcome
    stat = rate * minutes

    # Hit check
    hits = np.where(
        is_under[:, None],
        stat < line[:, None],
        stat > line[:, None],
    )

    # Laplace-smoothed probability
    p = (hits.sum(axis=1).astype(np.float64) + 0.5) / (sims + 1.0)
    return np.clip(p, 1e-12, 1.0 - 1e-12)


def apply_post_sim_adjustment(
    p_raw: np.ndarray,
    q: np.ndarray,
    minutes_s: np.ndarray,
    is_under: np.ndarray,
    post_sim_exponent: float,
) -> np.ndarray:
    """Vectorised blowout haircut (same math as adjust_probability_for_blowout)."""
    risk = np.clip(q * minutes_s, 0.0, 1.0)
    attenuation = (1.0 - risk) ** post_sim_exponent
    p_adj = np.where(
        is_under.astype(bool),
        1.0 - ((1.0 - p_raw) * attenuation),
        p_raw * attenuation,
    )
    return np.clip(p_adj, 0.03, 0.97)


def run_simulation(
    cv: pd.DataFrame,
    params: dict[str, float],
    sims: int = DEFAULT_SIMS,
    seed: int = SEED,
    return_per_date: bool = False,
) -> dict[str, Any]:
    """
    Full MC simulation for all legs under given params.
    Returns dict with brier_p (raw kernel Brier) and optionally per-date breakdown.
    """
    rng = np.random.default_rng(seed)
    N = len(cv)

    # Extract base arrays
    rate_mean_base = cv["rate_mean"].values.astype(np.float64)
    rate_std_base = cv["rate_std"].values.astype(np.float64)
    min_mean = cv["min_mean"].values.astype(np.float64)
    min_std = cv["min_std"].values.astype(np.float64)
    line = cv["line"].values.astype(np.float64)
    is_under = cv["is_under"].values.astype(bool)
    spread = cv["spread"].values.astype(np.float64)
    minutes_s = cv["minutes_s"].values.astype(np.float64)
    is_star = cv["is_star"].values.astype(bool)
    games_used = cv["games_used"].values.astype(np.float64)
    hit = cv["hit"].values.astype(np.float64)
    stat_u = cv["stat_u"].values

    # --- Apply opp_defense_strength to rate_mean ---
    opp_def_strength = float(params.get("opp_defense_strength", 1.0))
    if "opp_defense_rel" in cv.columns and opp_def_strength > 0:
        opp_def_rel = cv["opp_defense_rel"].values.astype(np.float64)
        opp_def_rel = np.nan_to_num(opp_def_rel, 0.0)
        opp_adj = 1.0 + opp_def_strength * opp_def_rel
        rate_mean = rate_mean_base * opp_adj
    else:
        rate_mean = rate_mean_base.copy()

    # --- Apply per-stat rate_std multipliers ---
    rate_std = rate_std_base.copy()
    global_mult = float(params.get("rate_std_multiplier", 1.0))
    rate_std *= global_mult

    for stat_key, stat_names in STAT_GROUPS.items():
        param_name = f"rate_std_{stat_key}"
        if param_name in params:
            mult = float(params[param_name])
            mask = np.isin(stat_u, stat_names)
            rate_std[mask] *= mult

    # --- Direction-aware UNDER inflation ---
    under_mult = float(params.get("rate_std_under_mult", 1.0))
    if under_mult != 1.0:
        rate_std[is_under] *= under_mult

    # --- Thin-sample inflation ---
    thin_games = int(params.get("thin_window_games", 15))
    thin_max_mult = float(params.get("thin_window_max_mult", 1.6))
    if thin_games > 0 and thin_max_mult > 1.0:
        thin_mask = (games_used > 0) & (games_used < thin_games)
        thin_frac = games_used / thin_games
        thin_mult = 1.0 + (thin_max_mult - 1.0) * (1.0 - thin_frac)
        rate_std = np.where(thin_mask, rate_std * thin_mult, rate_std)

    rate_std = np.maximum(rate_std, 0.01)

    # --- Blowout q ---
    spread_sd = float(params.get("spread_sd", 10.0))
    threshold = float(params.get("threshold_margin", 15.5))
    q = compute_blowout_q(spread, threshold, spread_sd)

    # --- Minute drop ---
    star_drop = float(params.get("star_minute_drop", 6.0))
    starter_drop = float(params.get("starter_minute_drop", 3.5))
    role_drop = float(params.get("role_minute_drop", 0.5))
    # Simplified tier: star >= 33min, starter >= 25min, else role
    minute_drop = np.where(
        is_star, star_drop,
        np.where(min_mean >= 25.0, starter_drop, role_drop),
    )

    # --- Rate-minutes correlation ---
    rate_min_corr = float(params.get("rate_min_correlation", 0.35))

    # --- Batched MC simulation ---
    p_all = np.empty(N, dtype=np.float64)
    for start in range(0, N, BATCH_SIZE):
        end = min(start + BATCH_SIZE, N)
        sl = slice(start, end)
        p_all[sl] = simulate_batch(
            rate_mean[sl], rate_std[sl], min_mean[sl], min_std[sl],
            line[sl], is_under[sl], q[sl], minute_drop[sl],
            rate_min_corr, sims, rng,
        )

    # --- Post-sim blowout adjustment (p -> p_adj) ---
    post_sim_exp = float(params.get("post_sim_exponent", 0.3))
    p_adj = apply_post_sim_adjustment(p_all, q, minutes_s, is_under, post_sim_exp)

    # --- Metrics ---
    valid = np.isfinite(hit)
    hit_v = hit[valid]
    p_v = p_all[valid]
    p_adj_v = p_adj[valid]

    brier_p = float(np.mean((p_v - hit_v) ** 2))
    brier_adj = float(np.mean((p_adj_v - hit_v) ** 2))

    result: dict[str, Any] = {
        "brier_p": brier_p,
        "brier_adj": brier_adj,
        "n_legs": int(valid.sum()),
    }

    if return_per_date:
        dates = cv["game_date"].values[valid]
        unique_dates = np.unique(dates)
        per_date = {}
        for d in unique_dates:
            mask_d = dates == d
            b_p = float(np.mean((p_v[mask_d] - hit_v[mask_d]) ** 2))
            b_adj = float(np.mean((p_adj_v[mask_d] - hit_v[mask_d]) ** 2))
            per_date[str(d)] = {"brier_p": b_p, "brier_adj": b_adj, "n": int(mask_d.sum())}
        result["per_date"] = per_date

    return result


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------
def _frange(lo: float, hi: float, step: float) -> list[float]:
    """Inclusive float range."""
    vals: list[float] = []
    v = lo
    while v <= hi + step * 0.01:
        vals.append(round(v, 4))
        v += step
    return vals


def generate_coarse_grid_variance() -> list[dict[str, float]]:
    """Family A: per-stat rate_std multipliers + rate_min_correlation.

    Strategy: sweep correlation + a single global scale factor first,
    then per-stat refinement in Phase 2.  Keeps grid small (~200 configs).
    """
    # Global rate_std scale applied on top of per-stat defaults
    global_scale_vals = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]
    corr_vals = [0.0, 0.10, 0.20, 0.30, 0.35, 0.40, 0.50]
    # Per-stat ratios relative to global (only the 4 key stats)
    pts_ratio = [0.85, 1.0, 1.15, 1.3]
    combo_ratio = [0.85, 1.0, 1.15, 1.3]

    configs: list[dict[str, float]] = []
    for gscale, corr, pts_r, combo_r in itertools.product(
        global_scale_vals, corr_vals, pts_ratio, combo_ratio
    ):
        pts = round(gscale * pts_r, 3)
        ast = round(gscale * 0.92, 3)   # AST tracks global
        reb = round(gscale * 0.77, 3)   # REB needs less inflation
        fg3m = round(gscale * 0.77, 3)
        combo = round(gscale * combo_r, 3)
        configs.append({
            "rate_std_PTS": pts,
            "rate_std_AST": ast,
            "rate_std_REB": reb,
            "rate_std_FG3M": fg3m,
            "rate_std_PRA": combo,
            "rate_std_PR": combo,
            "rate_std_PA": combo,
            "rate_std_RA": round(combo * 0.85, 3),
            "rate_min_correlation": corr,
        })
    return configs


def generate_coarse_grid_blowout() -> list[dict[str, float]]:
    """Family B: blowout parameters."""
    configs: list[dict[str, float]] = []
    for spread_sd, threshold, star_drop, pse in itertools.product(
        [8.0, 9.0, 10.0, 11.0, 13.0],
        [13.0, 15.5, 17.0, 19.0],
        [3.0, 5.0, 6.0, 8.0],
        [0.0, 0.15, 0.3, 0.5],
    ):
        configs.append({
            "spread_sd": spread_sd,
            "threshold_margin": threshold,
            "star_minute_drop": star_drop,
            "post_sim_exponent": pse,
        })
    return configs


def generate_coarse_grid_thin() -> list[dict[str, float]]:
    """Family C: thin-sample parameters."""
    configs: list[dict[str, float]] = []
    for thin_games, thin_mult in itertools.product(
        [8, 12, 15, 20, 25],
        [1.0, 1.3, 1.6, 2.0, 2.5],
    ):
        configs.append({
            "thin_window_games": float(thin_games),
            "thin_window_max_mult": thin_mult,
        })
    return configs


def generate_coarse_grid_defense() -> list[dict[str, float]]:
    """Family D: opponent defense strength."""
    return [{"opp_defense_strength": v} for v in _frange(0.0, 1.5, 0.1)]


def generate_fine_grid(winners: dict[str, float]) -> list[dict[str, float]]:
    """Phase 2: fine grid around combined winners from Phase 1.

    Only refine parameters from the two winning families (variance + blowout).
    Fix thin_sample and defense at their Phase 1 values.
    """
    # Separate into sweep-worthy vs fixed
    fixed_keys = {"thin_window_games", "thin_window_max_mult", "opp_defense_strength"}
    fixed = {k: v for k, v in winners.items() if k in fixed_keys}
    sweep_keys = {k: v for k, v in winners.items() if k not in fixed_keys}

    # Define fine ranges per parameter
    fine_ranges: dict[str, list[float]] = {}
    for key, val in sweep_keys.items():
        if key == "post_sim_exponent":
            fine_ranges[key] = _frange(max(0.0, val - 0.05), val + 0.1, 0.025)
        elif key == "spread_sd":
            fine_ranges[key] = _frange(max(5.0, val - 1.0), val + 1.0, 0.5)
        elif key == "threshold_margin":
            fine_ranges[key] = _frange(max(10.0, val - 2.0), val + 2.0, 1.0)
        elif key == "star_minute_drop":
            fine_ranges[key] = _frange(max(1.0, val - 1.5), val + 1.5, 0.5)
        elif key.startswith("rate_std_"):
            fine_ranges[key] = _frange(max(0.5, val - 0.15), min(2.5, val + 0.15), 0.05)
        elif key == "rate_min_correlation":
            fine_ranges[key] = _frange(max(0.0, val - 0.1), min(0.7, val + 0.1), 0.05)
        else:
            fine_ranges[key] = [val]

    # Random sampling (full grid would be millions)
    keys = sorted(fine_ranges.keys())
    ranges = [fine_ranges[k] for k in keys]
    rng = np.random.default_rng(SEED)
    n_samples = 2000
    configs = []
    for _ in range(n_samples):
        cfg = dict(fixed)  # start with fixed params
        for k, r in zip(keys, ranges):
            cfg[k] = float(rng.choice(r))
        configs.append(cfg)

    # Always include the Phase 1 winner as-is
    configs.insert(0, dict(winners))
    return configs


# ---------------------------------------------------------------------------
# Sweep runner
# ---------------------------------------------------------------------------
def sweep_family(
    cv: pd.DataFrame,
    configs: list[dict[str, float]],
    family_name: str,
    base_params: dict[str, float],
    sims: int = DEFAULT_SIMS,
    metric: str = "brier_p",
) -> dict[str, Any]:
    """
    Run a parameter family sweep. Each config overrides base_params for the
    family-specific keys only.
    """
    print(f"\n{'='*60}")
    print(f"Sweeping {family_name}: {len(configs):,} configs, {sims} sims")
    print(f"{'='*60}")

    best_brier = float("inf")
    best_cfg: dict[str, float] = {}
    results: list[dict[str, Any]] = []
    t0 = time.time()

    for i, cfg in enumerate(configs):
        # Merge: base + this config's overrides
        params = {**base_params, **cfg}
        res = run_simulation(cv, params, sims=sims)
        brier = res[metric]
        results.append({"config": cfg, metric: brier, "brier_p": res["brier_p"], "brier_adj": res["brier_adj"]})

        if brier < best_brier:
            best_brier = brier
            best_cfg = cfg.copy()

        if (i + 1) % 50 == 0 or i == len(configs) - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(configs) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1:>5}/{len(configs)}]  best={best_brier*1000:.3f} mB  "
                  f"({elapsed:.0f}s, {rate:.1f} cfg/s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    base_brier = run_simulation(cv, base_params, sims=sims)[metric]

    delta = (best_brier - base_brier) * 1000
    print(f"\n  {family_name} result:")
    print(f"    Current:  {base_brier*1000:.3f} mB")
    print(f"    Best:     {best_brier*1000:.3f} mB  (Δ = {delta:+.3f} mB)")
    print(f"    Config:   {best_cfg}")
    print(f"    Time:     {elapsed:.0f}s")

    return {
        "family": family_name,
        "best_config": best_cfg,
        "best_brier": best_brier,
        "base_brier": base_brier,
        "delta_mB": delta,
        "n_configs": len(configs),
        "elapsed_s": elapsed,
    }


def run_phase1(cv: pd.DataFrame, sims: int, metric: str = "brier_p") -> dict[str, Any]:
    """Phase 1: sweep each family independently."""
    base = _read_current_defaults()
    print(f"\nCurrent production params:")
    for k, v in sorted(base.items()):
        print(f"  {k}: {v}")

    # Baseline
    print(f"\nComputing baseline ({sims} sims)...")
    baseline = run_simulation(cv, base, sims=sims)
    print(f"  Baseline brier_p:   {baseline['brier_p']*1000:.3f} mB")
    print(f"  Baseline brier_adj: {baseline['brier_adj']*1000:.3f} mB")

    families = {
        "variance": generate_coarse_grid_variance(),
        "blowout": generate_coarse_grid_blowout(),
        "thin_sample": generate_coarse_grid_thin(),
        "defense": generate_coarse_grid_defense(),
    }

    results = {}
    combined_winners: dict[str, float] = {}

    for name, configs in families.items():
        res = sweep_family(cv, configs, name, base, sims=sims, metric=metric)
        results[name] = res
        combined_winners.update(res["best_config"])

    # Combined result
    combined_params = {**base, **combined_winners}
    combined = run_simulation(cv, combined_params, sims=sims)
    combined_brier = combined[metric]
    base_brier = baseline[metric]
    delta = (combined_brier - base_brier) * 1000

    print(f"\n{'='*60}")
    print(f"PHASE 1 COMBINED RESULT")
    print(f"{'='*60}")
    print(f"  Current:  {base_brier*1000:.3f} mB")
    print(f"  Combined: {combined_brier*1000:.3f} mB  (Δ = {delta:+.3f} mB)")
    print(f"\n  Winner params:")
    for k, v in sorted(combined_winners.items()):
        cur = base.get(k, "?")
        changed = " ***" if v != cur else ""
        print(f"    {k}: {cur} -> {v}{changed}")

    phase1_out = {
        "baseline": {metric: base_brier, "brier_p": baseline["brier_p"], "brier_adj": baseline["brier_adj"]},
        "combined": {metric: combined_brier, "brier_p": combined["brier_p"], "brier_adj": combined["brier_adj"]},
        "delta_mB": delta,
        "combined_winners": {k: float(v) for k, v in combined_winners.items()},
        "families": {k: {kk: vv for kk, vv in v.items() if kk != "results"} for k, v in results.items()},
    }
    return phase1_out


def run_phase2(
    cv: pd.DataFrame,
    phase1_winners: dict[str, float],
    sims: int = FINE_SIMS,
    metric: str = "brier_p",
    cv_sweep: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Phase 2: fine grid around combined Phase 1 winners.

    cv_sweep is used for the grid search (can be sub-sampled for speed).
    cv (full dataset) is used for the final per-date breakdown.
    """
    base = _read_current_defaults()
    if cv_sweep is None:
        cv_sweep = cv

    # Merge phase1 winners as the new base
    fine_base = {**base, **phase1_winners}

    print(f"\n{'='*60}")
    print(f"PHASE 2: Fine sweep ({sims} sims)")
    print(f"{'='*60}")

    configs = generate_fine_grid(phase1_winners)
    print(f"  Fine grid: {len(configs)} configs")
    print(f"  Sweep data: {len(cv_sweep):,} legs, Final check: {len(cv):,} legs")

    best_brier = float("inf")
    best_cfg: dict[str, float] = {}
    t0 = time.time()

    for i, cfg in enumerate(configs):
        params = {**base, **cfg}   # override from base, not fine_base
        res = run_simulation(cv_sweep, params, sims=sims)
        brier = res[metric]

        if brier < best_brier:
            best_brier = brier
            best_cfg = cfg.copy()

        if (i + 1) % 100 == 0 or i == len(configs) - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 1
            eta = (len(configs) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1:>5}/{len(configs)}]  best={best_brier*1000:.3f} mB  "
                  f"({elapsed:.0f}s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0

    # Per-date breakdown of winner on FULL dataset with more sims
    full_sims = max(sims, 2000)
    print(f"\n  Running per-date breakdown on FULL {len(cv):,} legs ({full_sims} sims)...")
    final_params = {**base, **best_cfg}
    final_res = run_simulation(cv, final_params, sims=full_sims, return_per_date=True)

    base_res = run_simulation(cv, base, sims=full_sims, return_per_date=True)

    print(f"\n  Per-date results (Phase 2 winner vs current):")
    per_date_final = final_res.get("per_date", {})
    per_date_base = base_res.get("per_date", {})
    n_better = 0
    n_worse = 0
    worst_delta = 0.0
    worst_date = ""

    for d in sorted(per_date_final.keys()):
        b_new = per_date_final[d][metric]
        b_old = per_date_base.get(d, {}).get(metric, b_new)
        delta_d = (b_new - b_old) * 1000
        n_d = per_date_final[d]["n"]
        tag = "GOOD" if delta_d <= 0 else "HURT"
        if delta_d <= 0:
            n_better += 1
        else:
            n_worse += 1
        if delta_d > worst_delta:
            worst_delta = delta_d
            worst_date = str(d)
        print(f"    {d}  N={n_d:>5}  Δ={delta_d:+.3f} mB  {tag}")

    base_brier = base_res[metric]
    delta_total = (best_brier - base_brier) * 1000

    print(f"\n  PHASE 2 FINAL:")
    print(f"    Current:  {base_brier*1000:.3f} mB")
    print(f"    Winner:   {best_brier*1000:.3f} mB  (Δ = {delta_total:+.3f} mB)")
    print(f"    Dates better/worse: {n_better}/{n_worse}")
    print(f"    Worst slate: {worst_date}  Δ={worst_delta:+.3f} mB")
    print(f"\n  Winner params:")
    for k, v in sorted(best_cfg.items()):
        cur = base.get(k, "?")
        changed = " ***" if v != cur else ""
        print(f"    {k}: {cur} -> {v}{changed}")

    phase2_out = {
        "winner_params": {k: float(v) for k, v in best_cfg.items()},
        "winner_brier": best_brier,
        "base_brier": base_brier,
        "delta_mB": delta_total,
        "n_configs": len(configs),
        "dates_better": n_better,
        "dates_worse": n_worse,
        "worst_slate": worst_date,
        "worst_delta_mB": worst_delta,
        "elapsed_s": elapsed,
    }
    return phase2_out


# ---------------------------------------------------------------------------
# Apply to config
# ---------------------------------------------------------------------------
def apply_to_config(winner_params: dict[str, float]) -> None:
    """Apply winner params to config.yaml blowout section."""
    cfg = load_config()
    blow = cfg.setdefault("blowout", {})
    by_stat = blow.setdefault("rate_std_multiplier_by_stat", {})

    mapping = {
        "spread_sd": "spread_sd",
        "threshold_margin": "threshold_margin",
        "star_minute_drop": "star_minute_drop",
        "role_minute_drop": "role_minute_drop",
        "post_sim_exponent": "post_sim_exponent",
        "rate_std_multiplier": "rate_std_multiplier",
        "rate_min_correlation": "rate_min_correlation",
        "opp_defense_strength": "opp_defense_strength",
    }

    for param_key, cfg_key in mapping.items():
        if param_key in winner_params:
            blow[cfg_key] = float(winner_params[param_key])

    # Per-stat rate_std
    stat_mapping = {"rate_std_PTS": "PTS", "rate_std_AST": "AST", "rate_std_REB": "REB",
                    "rate_std_FG3M": "FG3M", "rate_std_PRA": "PRA", "rate_std_PR": "PR",
                    "rate_std_PA": "PA", "rate_std_RA": "RA"}
    for param_key, stat_key in stat_mapping.items():
        if param_key in winner_params:
            by_stat[stat_key] = float(winner_params[param_key])

    # Thin-sample
    if "thin_window_games" in winner_params:
        blow["thin_window_games"] = int(winner_params["thin_window_games"])
    if "thin_window_max_mult" in winner_params:
        blow["thin_window_max_mult"] = float(winner_params["thin_window_max_mult"])

    # Rotation tiers
    rot = blow.setdefault("rotation_tiers", {})
    if "starter_minute_drop" in winner_params:
        rot["starter_minute_drop"] = float(winner_params["starter_minute_drop"])

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n  Applied winner params to {CONFIG_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="MC Kernel Parameter Trainer v1")
    ap.add_argument("--phase", type=int, choices=[1, 2], default=None,
                    help="Run only phase 1 or 2 (default: both)")
    ap.add_argument("--sims", type=int, default=None,
                    help="Override MC sim count")
    ap.add_argument("--metric", choices=["brier_p", "brier_adj"], default="brier_p",
                    help="Optimisation target (default: brier_p = raw kernel)")
    ap.add_argument("--apply", action="store_true",
                    help="Apply Phase 2 winner to config.yaml")
    args = ap.parse_args()

    coarse_sims = args.sims or DEFAULT_SIMS
    fine_sims = args.sims or FINE_SIMS

    print(f"MC Kernel Trainer v1")
    print(f"  Cache: {CACHE_PATH}")
    print(f"  Coarse sims: {coarse_sims}, Fine sims: {fine_sims}")
    print(f"  Metric: {args.metric}")
    print(f"  Batch size: {BATCH_SIZE}")

    cv = load_cache()

    # Drop legs without truth
    valid_mask = cv["hit"].notna()
    cv = cv[valid_mask].reset_index(drop=True)
    print(f"  Valid legs (with hit): {len(cv):,}")

    all_results: dict[str, Any] = {"version": "kernel_trainer_v1"}

    # Embed config fingerprint for traceability
    with open(CONFIG_PATH) as _cf:
        _full_cfg = yaml.safe_load(_cf)
    all_results["_manifest"] = build_manifest(
        source="kernel_trainer_v1", cfg=_full_cfg,
        ensemble_dir=_full_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    )
    print(f"  Config fingerprint: {all_results['_manifest']['config_fingerprint']}")

    # Stratified sub-sample for coarse phase (speed)
    if COARSE_SAMPLE > 0 and len(cv) > COARSE_SAMPLE:
        cv_coarse = cv.groupby("game_date", group_keys=False).apply(
            lambda g: g.sample(n=min(len(g), max(100, int(COARSE_SAMPLE * len(g) / len(cv)))),
                               random_state=SEED)
        ).reset_index(drop=True)
        print(f"  Coarse sub-sample: {len(cv_coarse):,} legs (from {len(cv):,})")
    else:
        cv_coarse = cv

    if args.phase is None or args.phase == 1:
        phase1 = run_phase1(cv_coarse, sims=coarse_sims, metric=args.metric)
        all_results["phase1"] = phase1

        # Save intermediate
        with open(RESULTS_PATH, "w") as f:
            yaml.dump(all_results, f, default_flow_style=False, sort_keys=False)
        print(f"\n  Saved Phase 1 -> {RESULTS_PATH}")

    if args.phase is None or args.phase == 2:
        # Load Phase 1 winners
        if "phase1" in all_results:
            p1_winners = all_results["phase1"]["combined_winners"]
        elif RESULTS_PATH.exists():
            with open(RESULTS_PATH) as f:
                saved = yaml.safe_load(f)
            p1_winners = saved.get("phase1", {}).get("combined_winners", {})
            if not p1_winners:
                print("ERROR: No Phase 1 winners found. Run --phase 1 first.")
                return
        else:
            print("ERROR: No Phase 1 results. Run --phase 1 first.")
            return

        phase2 = run_phase2(cv, p1_winners, sims=fine_sims, metric=args.metric,
                             cv_sweep=cv_coarse)
        all_results["phase2"] = phase2

        with open(RESULTS_PATH, "w") as f:
            yaml.dump(all_results, f, default_flow_style=False, sort_keys=False)
        print(f"\n  Saved Phase 1+2 -> {RESULTS_PATH}")

        if args.apply:
            apply_to_config(phase2["winner_params"])

    print("\nDone.")


if __name__ == "__main__":
    main()

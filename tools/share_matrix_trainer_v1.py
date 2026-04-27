#!/usr/bin/env python
"""
Share Matrix Weight Trainer v1
==============================
Optimizes how per-out share-matrix weights are accumulated into the
role_ctx_mult bump, BEFORE dampening is applied.

Architecture:
  - Tier 1 (cache-based, fast): re-accumulates per-out weights from
    resim cache's `role_ctx_by_out` column with different params, then
    applies existing dampening chain and estimates p_role via linear
    interpolation.  No share matrix rebuild required.

Sweep parameters:
  - weight_scale     : multiplicative amplifier on raw weights
  - weight_power     : power transform (w^power); <1 amplifies small weights
  - accumulation     : 'union' | 'additive' | 'capped_additive'
  - additive_cap     : cap when accumulation='capped_additive'
  - max_outs_used    : how many outs to include

Usage:
  python tools/share_matrix_trainer_v1.py [--cache PATH] [--config PATH]
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
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
# Helpers
# ---------------------------------------------------------------------------

MAX_OUTS_PAD = 12  # padded dimension for weight arrays


def _parse_by_out(raw: Any) -> list[dict[str, Any]]:
    """Parse role_ctx_by_out from cache (JSON string or list)."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    return []


# ---------------------------------------------------------------------------
# Data loading — returns pre-vectorized numpy arrays
# ---------------------------------------------------------------------------

def load_data(cache_path: str, config_path: str) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Load resim cache and config; return pre-vectorized arrays."""
    print(f"Loading cache: {cache_path}")
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    cv: pd.DataFrame = cache["cv"]
    print(f"  Total legs: {len(cv):,}")

    with open(config_path) as f:
        config: dict[str, Any] = yaml.safe_load(f)

    # Filter to active role_ctx legs with non-trivial mult
    active_mask = cv["role_ctx_outs_used"].fillna(0).astype(int) > 0
    active = cv[active_mask].copy()
    mult_arr = np.asarray(active["role_ctx_mult"].astype(float).values, dtype=np.float64)
    nontrivial = mult_arr > (1.0 + 1e-9)
    active = active[nontrivial].copy()
    mult_arr = mult_arr[nontrivial]
    print(f"  Active role_ctx legs: {len(active):,}")

    N = len(active)

    # Parse per-out weights into padded 2-D array (N x MAX_OUTS_PAD)
    weight_matrix = np.zeros((N, MAX_OUTS_PAD), dtype=np.float64)
    n_outs = np.zeros(N, dtype=np.int32)

    for i, by_out_raw in enumerate(active["role_ctx_by_out"].values):
        entries = _parse_by_out(by_out_raw)
        weights = [float(e.get("weight", 0)) for e in entries if isinstance(e, dict)]
        k = min(len(weights), MAX_OUTS_PAD)
        n_outs[i] = k
        if k > 0:
            weight_matrix[i, :k] = weights[:k]

    # Vectorized metadata
    p = np.asarray(active["p"].astype(float).values, dtype=np.float64)
    p_role = np.asarray(active["p_role"].astype(float).values, dtype=np.float64)
    hit = np.asarray(active["hit"].astype(float).values, dtype=np.float64)
    sensitivity = (p_role - p) / np.maximum(mult_arr - 1.0, 1e-12)

    min_mean = np.asarray(active["min_mean"].fillna(0).astype(float).values, dtype=np.float64)
    direction_is_over = np.asarray(
        (active["direction"].astype(str).str.upper().str.strip() == "OVER").values, dtype=bool)
    tier_is_demon = np.asarray(
        (active["tier"].astype(str).str.upper().str.strip() == "DEMON").values, dtype=bool)

    arrays: dict[str, np.ndarray] = {
        "weight_matrix": weight_matrix,
        "n_outs": n_outs,
        "p": p,
        "p_role": p_role,
        "hit": hit,
        "mult_current": mult_arr,
        "sensitivity": sensitivity,
        "min_mean": min_mean,
        "is_star": min_mean >= 33.0,
        "is_core": (min_mean >= 28.0) & (min_mean < 33.0),
        "is_over": direction_is_over,
        "is_demon": tier_is_demon,
    }

    print(f"  Legs loaded: {N:,}")
    return arrays, config


# ---------------------------------------------------------------------------
# Vectorized evaluation — no row-by-row loops
# ---------------------------------------------------------------------------

def evaluate_config(
    arr: dict[str, np.ndarray],
    *,
    weight_scale: float,
    weight_power: float,
    accumulation: str,
    additive_cap: float,
    max_outs_used: int,
    star_damp: float,
    core_damp: float,
    demon_damp: float,
    over_damp: float,
    multi_boost: float,
    proj_hi: float,
    proj_lo: float,
    k_soft: float,
) -> dict[str, Any]:
    """Evaluate a single parameter configuration — fully vectorized."""
    wm = arr["weight_matrix"][:, :max_outs_used].copy()  # (N, max_outs_used)

    # Transform weights
    wm *= weight_scale
    if weight_power != 1.0:
        wm = np.power(np.clip(wm, 1e-12, None), weight_power)
    np.clip(wm, 0.0, 0.95, out=wm)

    # Zero out positions beyond each leg's actual n_outs
    n_outs = arr["n_outs"]
    for j in range(max_outs_used):
        mask = n_outs <= j
        wm[mask, j] = 0.0

    # Accumulate bumps
    if accumulation == "union":
        bump = 1.0 - np.prod(1.0 - wm, axis=1)
    elif accumulation == "additive":
        bump = np.sum(wm, axis=1)
    elif accumulation == "capped_additive":
        bump = np.minimum(np.sum(wm, axis=1), additive_cap)
    else:
        bump = 1.0 - np.prod(1.0 - wm, axis=1)

    # Dampening (vectorized)
    damp_mult = np.ones_like(bump)
    damp_mult[arr["is_star"]] *= star_damp
    damp_mult[arr["is_core"]] *= core_damp
    damp_mult[arr["is_demon"]] *= demon_damp
    if over_damp < 1.0:
        damp_mult[arr["is_over"]] *= over_damp
    if multi_boost > 1.0:
        multi_mask = np.minimum(n_outs, max_outs_used) >= 3
        damp_mult[multi_mask] *= multi_boost

    bump_damped = bump * damp_mult

    # Softcap (vectorized)
    cap_bump = max(proj_hi - 1.0, 1e-12)
    bump_soft = cap_bump * (1.0 - np.exp(-k_soft * bump_damped / cap_bump))

    # Clamp
    new_mults = np.clip(1.0 + bump_soft, proj_lo, proj_hi)

    # Estimate new p_role via linear interpolation
    p_role_new = arr["p"] + arr["sensitivity"] * (new_mults - 1.0)
    np.clip(p_role_new, 0.01, 0.99, out=p_role_new)

    hit = arr["hit"]
    brier_new = float(np.mean((p_role_new - hit) ** 2))
    brier_old = float(np.mean((arr["p_role"] - hit) ** 2))
    brier_raw = float(np.mean((arr["p"] - hit) ** 2))

    return {
        "brier_new": brier_new,
        "brier_old": brier_old,
        "brier_raw": brier_raw,
        "delta_vs_current": (brier_new - brier_old) * 1000,
        "delta_vs_raw": (brier_new - brier_raw) * 1000,
        "mean_mult": float(np.mean(new_mults)),
        "max_mult": float(np.max(new_mults)),
        "mean_bump": float(np.mean(bump_soft)),
    }


# ---------------------------------------------------------------------------
# Phase 1 — Coarse sweep
# ---------------------------------------------------------------------------

PHASE1_GRID: dict[str, list[Any]] = {
    "weight_scale": [0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 25.0],
    "weight_power": [0.5, 0.75, 1.0],
    "accumulation": ["union", "additive", "capped_additive"],
    "additive_cap": [0.08, 0.15, 0.25],
    "max_outs_used": [3, 6, 10],
}


def _build_phase1_combos() -> list[tuple[float, float, str, float, int]]:
    """Build de-duplicated Phase 1 config list."""
    combos = list(itertools.product(
        PHASE1_GRID["weight_scale"],
        PHASE1_GRID["weight_power"],
        PHASE1_GRID["accumulation"],
        PHASE1_GRID["additive_cap"],
        PHASE1_GRID["max_outs_used"],
    ))
    filtered: list[tuple[float, float, str, float, int]] = []
    seen: set[tuple[float, float, str, float, int]] = set()
    for ws, wp, acc, ac, mo in combos:
        if acc != "capped_additive":
            key = (ws, wp, acc, 0.0, mo)
        else:
            key = (ws, wp, acc, ac, mo)
        if key not in seen:
            seen.add(key)
            filtered.append((ws, wp, acc, ac if acc == "capped_additive" else 0.15, mo))
    return filtered


def run_phase1(arr: dict[str, np.ndarray], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Coarse grid sweep."""
    role_cfg = config.get("role_ctx", {})
    proj_hi = float(role_cfg.get("projection_clamp_hi", 1.11))
    proj_lo = float(role_cfg.get("projection_clamp_lo", 0.9))
    k_soft = float(role_cfg.get("projection_softcap_k", 0.9))
    star_d = float(role_cfg.get("star_beneficiary_damp", 0.4))
    core_d = float(role_cfg.get("core_beneficiary_damp", 1.0))
    demon_d = float(role_cfg.get("demon_tier_damp", 0.0))
    over_d = float(role_cfg.get("over_direction_damp", 1.0))
    multi_b = float(role_cfg.get("multi_injury_boost", 1.0))

    filtered = _build_phase1_combos()
    print(f"\nPhase 1: {len(filtered)} configs")
    results: list[dict[str, Any]] = []
    t0 = time.time()

    for i, (ws, wp, acc, ac, mo) in enumerate(filtered):
        r = evaluate_config(
            arr,
            weight_scale=ws, weight_power=wp, accumulation=acc,
            additive_cap=ac, max_outs_used=mo,
            star_damp=star_d, core_damp=core_d, demon_damp=demon_d,
            over_damp=over_d, multi_boost=multi_b,
            proj_hi=proj_hi, proj_lo=proj_lo, k_soft=k_soft,
        )
        r.update({
            "weight_scale": ws, "weight_power": wp, "accumulation": acc,
            "additive_cap": ac, "max_outs_used": mo,
        })
        results.append(r)
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            best_delta = min(r2["delta_vs_current"] for r2 in results)
            print(f"  {i+1}/{len(filtered)} ({rate:.0f} cfg/s) "
                  f"best delta_vs_current={best_delta:.4f} mB")

    results.sort(key=lambda x: x["brier_new"])
    elapsed = time.time() - t0
    print(f"Phase 1 done in {elapsed:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Phase 2 — Fine sweep around best
# ---------------------------------------------------------------------------

def run_phase2(
    arr: dict[str, np.ndarray],
    config: dict[str, Any],
    phase1_best: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fine sweep around Phase 1 winner."""
    role_cfg = config.get("role_ctx", {})
    proj_hi = float(role_cfg.get("projection_clamp_hi", 1.11))
    proj_lo = float(role_cfg.get("projection_clamp_lo", 0.9))
    k_soft = float(role_cfg.get("projection_softcap_k", 0.9))
    star_d = float(role_cfg.get("star_beneficiary_damp", 0.4))
    core_d = float(role_cfg.get("core_beneficiary_damp", 1.0))
    demon_d = float(role_cfg.get("demon_tier_damp", 0.0))
    over_d = float(role_cfg.get("over_direction_damp", 1.0))
    multi_b = float(role_cfg.get("multi_injury_boost", 1.0))

    ws_best = float(phase1_best["weight_scale"])
    wp_best = float(phase1_best["weight_power"])
    acc_best: str = phase1_best["accumulation"]
    ac_best = float(phase1_best["additive_cap"])
    mo_best = int(phase1_best["max_outs_used"])

    ws_range = sorted(set(float(np.clip(ws_best * f, 0.1, 100.0))
                          for f in [0.5, 0.7, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.3, 1.5, 2.0]))
    wp_range = sorted(set(float(np.clip(wp_best + d, 0.1, 2.0))
                          for d in [-0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2]))
    mo_range = sorted(set(max(1, mo_best + d) for d in [-2, -1, 0, 1, 2]))

    if acc_best == "capped_additive":
        ac_range = sorted(set(float(np.clip(ac_best * f, 0.02, 0.50))
                              for f in [0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5]))
    else:
        ac_range = [ac_best]

    combos = list(itertools.product(ws_range, wp_range, [acc_best], ac_range, mo_range))
    print(f"\nPhase 2: {len(combos)} configs (around {acc_best} ws={ws_best} wp={wp_best})")

    results: list[dict[str, Any]] = []
    t0 = time.time()

    for i, (ws, wp, acc, ac, mo) in enumerate(combos):
        r = evaluate_config(
            arr,
            weight_scale=ws, weight_power=wp, accumulation=acc,
            additive_cap=ac, max_outs_used=mo,
            star_damp=star_d, core_damp=core_d, demon_damp=demon_d,
            over_damp=over_d, multi_boost=multi_b,
            proj_hi=proj_hi, proj_lo=proj_lo, k_soft=k_soft,
        )
        r.update({
            "weight_scale": ws, "weight_power": wp, "accumulation": acc,
            "additive_cap": ac, "max_outs_used": mo,
        })
        results.append(r)
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            print(f"  {i+1}/{len(combos)} ({rate:.0f} cfg/s)")

    results.sort(key=lambda x: x["brier_new"])
    elapsed = time.time() - t0
    print(f"Phase 2 done in {elapsed:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Phase 3 — Softcap sweep
# ---------------------------------------------------------------------------

def run_phase3(
    arr: dict[str, np.ndarray],
    config: dict[str, Any],
    best_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Sweep softcap / projection clamp parameters with best weight params."""
    role_cfg = config.get("role_ctx", {})
    proj_lo = float(role_cfg.get("projection_clamp_lo", 0.9))
    star_d = float(role_cfg.get("star_beneficiary_damp", 0.4))
    core_d = float(role_cfg.get("core_beneficiary_damp", 1.0))
    demon_d = float(role_cfg.get("demon_tier_damp", 0.0))
    over_d = float(role_cfg.get("over_direction_damp", 1.0))
    multi_b = float(role_cfg.get("multi_injury_boost", 1.0))

    proj_hi_range = [1.06, 1.08, 1.10, 1.11, 1.13, 1.15, 1.18, 1.20, 1.25, 1.30]
    k_soft_range = [0.5, 0.7, 0.9, 1.1, 1.3, 1.6, 2.0, 3.0]

    combos = list(itertools.product(proj_hi_range, k_soft_range))
    print(f"\nPhase 3 (softcap sweep): {len(combos)} configs")

    results: list[dict[str, Any]] = []
    t0 = time.time()

    for ph, ks in combos:
        r = evaluate_config(
            arr,
            weight_scale=float(best_params["weight_scale"]),
            weight_power=float(best_params["weight_power"]),
            accumulation=best_params["accumulation"],
            additive_cap=float(best_params["additive_cap"]),
            max_outs_used=int(best_params["max_outs_used"]),
            star_damp=star_d, core_damp=core_d, demon_damp=demon_d,
            over_damp=over_d, multi_boost=multi_b,
            proj_hi=ph, proj_lo=proj_lo, k_soft=ks,
        )
        r.update({"proj_hi": ph, "k_soft": ks})
        results.append(r)

    results.sort(key=lambda x: x["brier_new"])
    elapsed = time.time() - t0
    print(f"Phase 3 done in {elapsed:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Phase 4 — Dampening sweep
# ---------------------------------------------------------------------------

def run_phase4(
    arr: dict[str, np.ndarray],
    config: dict[str, Any],
    best_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Sweep dampening parameters with best weight + softcap params."""
    role_cfg = config.get("role_ctx", {})
    proj_lo = float(role_cfg.get("projection_clamp_lo", 0.9))

    # Fixed from earlier phases
    ws = float(best_params["weight_scale"])
    wp = float(best_params["weight_power"])
    acc = best_params["accumulation"]
    ac = float(best_params.get("additive_cap", 0.15))
    mo = int(best_params["max_outs_used"])
    ph = float(best_params.get("proj_hi", role_cfg.get("projection_clamp_hi", 1.11)))
    ks = float(best_params.get("k_soft", role_cfg.get("projection_softcap_k", 0.9)))

    star_range = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
    core_range = [0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
    demon_range = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    over_range = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    multi_range = [1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0]

    combos = list(itertools.product(star_range, core_range, demon_range, over_range, multi_range))
    print(f"\nPhase 4 (dampening sweep): {len(combos)} configs")

    results: list[dict[str, Any]] = []
    t0 = time.time()

    for i, (sd, cd, dd, od, mb) in enumerate(combos):
        r = evaluate_config(
            arr,
            weight_scale=ws, weight_power=wp, accumulation=acc,
            additive_cap=ac, max_outs_used=mo,
            star_damp=sd, core_damp=cd, demon_damp=dd,
            over_damp=od, multi_boost=mb,
            proj_hi=ph, proj_lo=proj_lo, k_soft=ks,
        )
        r.update({
            "star_damp": sd, "core_damp": cd, "demon_damp": dd,
            "over_damp": od, "multi_boost": mb,
        })
        results.append(r)
        if (i + 1) % 5000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            best_delta = min(r2["delta_vs_current"] for r2 in results)
            print(f"  {i+1}/{len(combos)} ({rate:.0f} cfg/s) "
                  f"best delta_vs_current={best_delta:.4f} mB")

    results.sort(key=lambda x: x["brier_new"])
    elapsed = time.time() - t0
    print(f"Phase 4 done in {elapsed:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Phase 5 — Fine dampening sweep around Phase 4 winner
# ---------------------------------------------------------------------------

def run_phase5(
    arr: dict[str, np.ndarray],
    config: dict[str, Any],
    best_params: dict[str, Any],
    phase4_best: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fine sweep around Phase 4 dampening winner."""
    role_cfg = config.get("role_ctx", {})
    proj_lo = float(role_cfg.get("projection_clamp_lo", 0.9))

    ws = float(best_params["weight_scale"])
    wp = float(best_params["weight_power"])
    acc = best_params["accumulation"]
    ac = float(best_params.get("additive_cap", 0.15))
    mo = int(best_params["max_outs_used"])
    ph = float(best_params.get("proj_hi", role_cfg.get("projection_clamp_hi", 1.11)))
    ks = float(best_params.get("k_soft", role_cfg.get("projection_softcap_k", 0.9)))

    sd_c = float(phase4_best["star_damp"])
    cd_c = float(phase4_best["core_damp"])
    dd_c = float(phase4_best["demon_damp"])
    od_c = float(phase4_best["over_damp"])
    mb_c = float(phase4_best["multi_boost"])

    def _fine(center: float, lo: float, hi: float, step: float) -> list[float]:
        vals = sorted(set(round(center + d * step, 4)
                          for d in range(-3, 4)))
        return [v for v in vals if lo <= v <= hi]

    star_range = _fine(sd_c, 0.0, 1.0, 0.05)
    core_range = _fine(cd_c, 0.3, 1.5, 0.05)
    demon_range = _fine(dd_c, 0.0, 1.0, 0.05)
    over_range = _fine(od_c, 0.3, 1.0, 0.05)
    multi_range = _fine(mb_c, 1.0, 2.5, 0.1)

    combos = list(itertools.product(star_range, core_range, demon_range, over_range, multi_range))
    print(f"\nPhase 5 (fine dampening): {len(combos)} configs "
          f"(around sd={sd_c} cd={cd_c} dd={dd_c} od={od_c} mb={mb_c})")

    results: list[dict[str, Any]] = []
    t0 = time.time()

    for i, (sd, cd, dd, od, mb) in enumerate(combos):
        r = evaluate_config(
            arr,
            weight_scale=ws, weight_power=wp, accumulation=acc,
            additive_cap=ac, max_outs_used=mo,
            star_damp=sd, core_damp=cd, demon_damp=dd,
            over_damp=od, multi_boost=mb,
            proj_hi=ph, proj_lo=proj_lo, k_soft=ks,
        )
        r.update({
            "star_damp": sd, "core_damp": cd, "demon_damp": dd,
            "over_damp": od, "multi_boost": mb,
        })
        results.append(r)
        if (i + 1) % 5000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            print(f"  {i+1}/{len(combos)} ({rate:.0f} cfg/s)")

    results.sort(key=lambda x: x["brier_new"])
    elapsed = time.time() - t0
    print(f"Phase 5 done in {elapsed:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_top10_weight(results: list[dict[str, Any]], label: str) -> None:
    top = results[:10]
    print(f"\n=== {label} Top 10 ===")
    print(f"{'Rank':>4} {'acc':>15} {'ws':>6} {'wp':>5} {'cap':>5} {'mo':>3} "
          f"{'brier':>9} {'vs_cur':>8} {'vs_raw':>8} {'mean_m':>7}")
    for i, r in enumerate(top):
        print(f"{i+1:4d} {r['accumulation']:>15} {r['weight_scale']:6.1f} "
              f"{r['weight_power']:5.2f} {r['additive_cap']:5.2f} {r['max_outs_used']:3d} "
              f"{r['brier_new']*1000:9.3f} {r['delta_vs_current']:8.4f} "
              f"{r['delta_vs_raw']:8.4f} {r['mean_mult']:7.4f}")


def _print_top10_softcap(results: list[dict[str, Any]]) -> None:
    top = results[:10]
    print("\n=== Phase 3 Top 10 (softcap sweep) ===")
    print(f"{'Rank':>4} {'proj_hi':>8} {'k_soft':>7} {'brier':>9} {'vs_cur':>8} {'vs_raw':>8}")
    for i, r in enumerate(top):
        print(f"{i+1:4d} {r['proj_hi']:8.2f} {r['k_soft']:7.2f} "
              f"{r['brier_new']*1000:9.3f} {r['delta_vs_current']:8.4f} "
              f"{r['delta_vs_raw']:8.4f}")


def _print_top10_damp(results: list[dict[str, Any]], label: str) -> None:
    top = results[:10]
    print(f"\n=== {label} Top 10 (dampening) ===")
    print(f"{'Rank':>4} {'star':>6} {'core':>6} {'demon':>6} {'over':>6} {'multi':>6} "
          f"{'brier':>9} {'vs_cur':>8} {'vs_raw':>8}")
    for i, r in enumerate(top):
        print(f"{i+1:4d} {r['star_damp']:6.2f} {r['core_damp']:6.2f} "
              f"{r['demon_damp']:6.2f} {r['over_damp']:6.2f} {r['multi_boost']:6.2f} "
              f"{r['brier_new']*1000:9.3f} {r['delta_vs_current']:8.4f} "
              f"{r['delta_vs_raw']:8.4f}")


def _to_yaml_safe(val: Any) -> Any:
    """Convert numpy types to Python natives for YAML serialization."""
    if isinstance(val, float) or type(val).__name__ in ('float64', 'float32', 'float16'):
        return float(val)
    if isinstance(val, int) or type(val).__name__ in ('int64', 'int32', 'int16'):
        return int(val)
    if isinstance(val, dict):
        return {k: _to_yaml_safe(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_yaml_safe(v) for v in val]
    return val


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Share Matrix Weight Trainer v1")
    parser.add_argument("--cache", default="data/model/_v13_resim_cache.pkl")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="tools/share_matrix_trainer_results_v1.yaml")
    parser.add_argument("--phase", type=int, default=0,
                        help="Run only a specific phase (1-5). 0=all.")
    args = parser.parse_args()

    arr, config = load_data(args.cache, args.config)
    n_legs = len(arr["p"])

    if n_legs < 100:
        print("ERROR: Too few active role_ctx legs with non-trivial mult.")
        sys.exit(1)

    # Current baseline
    brier_raw = float(np.mean((arr["p"] - arr["hit"]) ** 2))
    brier_current = float(np.mean((arr["p_role"] - arr["hit"]) ** 2))
    print(f"\nBaseline (N={n_legs:,} active legs):")
    print(f"  p (raw):      {brier_raw*1000:.3f} mB")
    print(f"  p_role (cur): {brier_current*1000:.3f} mB")
    print(f"  delta:        {(brier_current - brier_raw)*1000:.3f} mB")

    p1_results: list[dict[str, Any]] = []
    p2_results: list[dict[str, Any]] = []
    p3_results: list[dict[str, Any]] = []
    p4_results: list[dict[str, Any]] = []
    p5_results: list[dict[str, Any]] = []
    p1_best: dict[str, Any] | None = None
    p2_best: dict[str, Any] | None = None
    p3_best: dict[str, Any] | None = None
    p4_best: dict[str, Any] | None = None
    p5_best: dict[str, Any] | None = None

    # Phase 1
    if args.phase in (0, 1):
        p1_results = run_phase1(arr, config)
        _print_top10_weight(p1_results, "Phase 1")
        p1_best = p1_results[0]

    # Phase 2
    if args.phase in (0, 2):
        if p1_best is None:
            print("Phase 2 requires Phase 1 results. Run --phase 0 or --phase 1 first.")
            sys.exit(1)
        p2_results = run_phase2(arr, config, p1_best)
        _print_top10_weight(p2_results, "Phase 2")
        p2_best = p2_results[0]

    # Phase 3
    best_weights = p2_best or p1_best
    if args.phase in (0, 3) and best_weights is not None:
        p3_results = run_phase3(arr, config, best_weights)
        _print_top10_softcap(p3_results)
        p3_best = p3_results[0]

    # Merge best so far (weight params + softcap params)
    best_so_far = dict(best_weights or {})
    if p3_best is not None:
        best_so_far["proj_hi"] = p3_best["proj_hi"]
        best_so_far["k_soft"] = p3_best["k_soft"]

    # Phase 4 — coarse dampening
    if args.phase in (0, 4) and best_so_far:
        p4_results = run_phase4(arr, config, best_so_far)
        _print_top10_damp(p4_results, "Phase 4")
        p4_best = p4_results[0]

    # Phase 5 — fine dampening
    if args.phase in (0, 5) and best_so_far and p4_best is not None:
        p5_results = run_phase5(arr, config, best_so_far, p4_best)
        _print_top10_damp(p5_results, "Phase 5")
        p5_best = p5_results[0]

    # Final winner — merge all params
    final_best = dict(best_so_far)
    if p3_best:
        final_best.update({"proj_hi": p3_best["proj_hi"], "k_soft": p3_best["k_soft"]})
        final_best["brier_new"] = p3_best["brier_new"]
        final_best["delta_vs_current"] = p3_best["delta_vs_current"]
        final_best["delta_vs_raw"] = p3_best["delta_vs_raw"]
        final_best["mean_mult"] = p3_best["mean_mult"]
        final_best["max_mult"] = p3_best["max_mult"]
        final_best["mean_bump"] = p3_best["mean_bump"]
    damp_winner = p5_best or p4_best
    if damp_winner:
        final_best.update({
            "star_damp": damp_winner["star_damp"],
            "core_damp": damp_winner["core_damp"],
            "demon_damp": damp_winner["demon_damp"],
            "over_damp": damp_winner["over_damp"],
            "multi_boost": damp_winner["multi_boost"],
            "brier_new": damp_winner["brier_new"],
            "delta_vs_current": damp_winner["delta_vs_current"],
            "delta_vs_raw": damp_winner["delta_vs_raw"],
            "mean_mult": damp_winner["mean_mult"],
            "max_mult": damp_winner["max_mult"],
            "mean_bump": damp_winner["mean_bump"],
        })
    if final_best is None:
        print("No results produced.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("FINAL WINNER")
    print(f"{'='*60}")
    for k, v in sorted(final_best.items()):
        if isinstance(v, float):
            print(f"  {k:25s}: {v:.6f}")
        else:
            print(f"  {k:25s}: {v}")
    print(f"\n  Current p_role Brier:   {brier_current*1000:.3f} mB")
    print(f"  New p_role Brier:       {final_best['brier_new']*1000:.3f} mB")
    print(f"  Improvement:            {final_best['delta_vs_current']:.4f} mB")
    print(f"  vs raw p:               {final_best['delta_vs_raw']:.4f} mB")

    # Save results
    with open(args.config) as _cf:
        _full_cfg = yaml.safe_load(_cf)
    output: dict[str, Any] = {
        "version": "share_matrix_trainer_v1",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "_manifest": build_manifest(
            source="share_matrix_trainer_v1", cfg=_full_cfg,
            ensemble_dir=_full_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
        ),
        "n_legs": n_legs,
        "baseline": {
            "brier_raw_mB": round(brier_raw * 1000, 4),
            "brier_current_mB": round(brier_current * 1000, 4),
        },
        "phase1_top10": [_to_yaml_safe(r) for r in p1_results[:10]],
        "phase2_top10": [_to_yaml_safe(r) for r in p2_results[:10]],
        "phase3_top10": [_to_yaml_safe(r) for r in p3_results[:10]],
        "phase4_top10": [_to_yaml_safe(r) for r in p4_results[:10]],
        "phase5_top10": [_to_yaml_safe(r) for r in p5_results[:10]],
        "winner": _to_yaml_safe(final_best),
    }

    with open(args.output, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()

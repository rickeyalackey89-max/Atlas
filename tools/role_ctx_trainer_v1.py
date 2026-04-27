#!/usr/bin/env python
"""
Role-Context Dampening Trainer v1
==================================
Sweeps role_ctx dampening parameters on the v13 resim cache (94K legs)
to optimize Brier score at the p_role stage.

Operates on the *bump* (p_role - p) which is proportional to role_mult - 1.
The dampening factors multiply the bump before it becomes p_role_new.

Parameters swept:
  - star_beneficiary_damp: 33+ min players (stars at capacity)
  - core_beneficiary_damp: 28-33 min players
  - demon_tier_damp: DEMON tier legs (market-efficient)
  - over_direction_damp: OVER direction legs
  - multi_injury_boost: outs >= 3 amplification (>= 1.0)
  - projection_clamp_hi: hard ceiling on role_mult

Output: YAML results file + auto-apply best config to config.yaml.

Usage:
    python tools/role_ctx_trainer_v1.py [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import pickle
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from Atlas.core.fingerprint import build_manifest, config_fingerprint

CACHE_PATH = Path("data/model/_v13_resim_cache.pkl")
CONFIG_PATH = Path("config.yaml")
RESULTS_PATH = Path("tools/role_ctx_trainer_results_v1.yaml")

# ── Grid definition ────────────────────────────────────────────────
# Phase 1: Coarse sweep
GRID_COARSE = {
    "star_beneficiary_damp":  [0.0, 0.15, 0.25, 0.35, 0.50, 0.75, 1.0],
    "core_beneficiary_damp":  [0.50, 0.75, 1.0],
    "demon_tier_damp":        [0.0, 0.25, 0.50, 0.75, 1.0],
    "over_direction_damp":    [0.70, 0.85, 1.0],
    "multi_injury_boost":     [1.0, 1.10, 1.20],      # boost for outs >= 3
    "projection_clamp_hi":    [1.06, 1.08, 1.10, 1.12],
}

# Phase 2: Fine sweep around coarse winner (built dynamically)
FINE_STEPS = {
    "star_beneficiary_damp":  0.05,
    "core_beneficiary_damp":  0.10,
    "demon_tier_damp":        0.05,
    "over_direction_damp":    0.05,
    "multi_injury_boost":     0.05,
    "projection_clamp_hi":    0.01,
}


def load_cache() -> pd.DataFrame:
    """Load v13 resim cache and return the full DataFrame."""
    print(f"Loading cache from {CACHE_PATH} ...")
    c = pickle.load(open(CACHE_PATH, "rb"))
    df = c["cv"].copy()
    print(f"  {len(df):,} total legs, {df['game_date'].nunique()} dates")
    rc_n = (df["role_ctx_outs_used"] > 0).sum()
    print(f"  {rc_n:,} legs with role_ctx ({rc_n / len(df) * 100:.1f}%)")
    return df


def simulate_config(
    df: pd.DataFrame,
    rc: pd.DataFrame,
    masks: dict,
    cfg: dict,
) -> dict:
    """
    Simulate a dampening config on the cache.
    Returns metrics dict.
    """
    star_d = cfg["star_beneficiary_damp"]
    core_d = cfg["core_beneficiary_damp"]
    demon_d = cfg["demon_tier_damp"]
    over_d = cfg["over_direction_damp"]
    multi_boost = cfg["multi_injury_boost"]
    clamp_hi = cfg["projection_clamp_hi"]

    bump: np.ndarray = np.asarray(rc["bump"].values, dtype=float)

    # Apply dampening multipliers to the bump
    damp = np.ones(len(rc))

    # Star / core (mutually exclusive)
    if star_d < 1.0:
        damp[masks["is_star"]] *= star_d
    if core_d < 1.0:
        damp[masks["is_core"]] *= core_d

    # DEMON tier
    if demon_d < 1.0:
        damp[masks["is_demon"]] *= demon_d

    # OVER direction
    if over_d < 1.0:
        damp[masks["is_over"]] *= over_d

    # Multi-injury boost (outs >= 3)
    if multi_boost > 1.0:
        damp[masks["is_multi_inj"]] *= multi_boost

    new_bump = bump * damp

    # Apply clamp: limit the effective mult to clamp_hi
    # bump corresponds to (mult - 1), so cap bump at (clamp_hi - 1)
    max_bump = clamp_hi - 1.0
    new_bump = np.minimum(new_bump, max_bump)

    p_new = np.clip(rc["p"].values + new_bump, 0.001, 0.999)

    # Full corpus Brier
    all_p: np.ndarray = np.asarray(df["p"].values, dtype=float).copy()
    rc_idx = np.asarray(rc["_idx"].values, dtype=int)
    all_p[rc_idx] = p_new
    hit_all: np.ndarray = np.asarray(df["hit"].values, dtype=float)
    full_brier = float(np.mean((all_p - hit_all) ** 2))

    # Role_ctx only Brier
    rc_hit: np.ndarray = np.asarray(rc["hit"].values, dtype=float)
    rc_brier = float(np.mean((p_new - rc_hit) ** 2))

    # Per-date worst regression vs current
    worst_slate_delta = 0.0
    p_cur: np.ndarray = np.asarray(df["p_role"].values, dtype=float)
    for start, end in masks["date_ranges"]:
        sl = slice(start, end)
        b_cur = float(np.mean((p_cur[sl] - hit_all[sl]) ** 2))
        b_new = float(np.mean((all_p[sl] - hit_all[sl]) ** 2))
        d = (b_new - b_cur) * 1000
        if d > worst_slate_delta:
            worst_slate_delta = d

    # Per-date wins vs current
    dates_better = dates_worse = 0
    for start, end in masks["date_ranges"]:
        sl = slice(start, end)
        b_cur = float(np.mean((p_cur[sl] - hit_all[sl]) ** 2))
        b_new = float(np.mean((all_p[sl] - hit_all[sl]) ** 2))
        if b_new < b_cur:
            dates_better += 1
        elif b_new > b_cur:
            dates_worse += 1

    return {
        "full_brier": full_brier,
        "rc_brier": rc_brier,
        "worst_slate_mB": worst_slate_delta,
        "dates_better": dates_better,
        "dates_worse": dates_worse,
    }


def build_masks(df: pd.DataFrame, rc: pd.DataFrame) -> dict[str, Any]:
    """Pre-compute boolean masks and date ranges for speed."""
    masks: dict[str, Any] = {
        "is_star": np.asarray((rc["min_mean"] >= 33.0).values),
        "is_core": np.asarray(((rc["min_mean"] >= 28.0) & (rc["min_mean"] < 33.0)).values),
        "is_demon": np.asarray((rc["tier"] == "DEMON").values),
        "is_over": np.asarray((rc["direction"] == "OVER").values),
        "is_multi_inj": np.asarray((rc["role_ctx_outs_used"] >= 3).values),
    }

    # Pre-compute date ranges (start, end) indices into sorted df
    # df must be sorted by game_date for this to work
    date_ranges: list[tuple[int, int]] = []
    gd_arr = np.asarray(df["game_date"].values)
    for gd in np.unique(gd_arr):
        idx = np.where(gd_arr == gd)[0]
        if len(idx) >= 50:
            date_ranges.append((int(idx[0]), int(idx[-1] + 1)))
    masks["date_ranges"] = date_ranges

    return masks


def run_sweep(
    grid: dict,
    df: pd.DataFrame,
    rc: pd.DataFrame,
    masks: dict,
    base_brier: float,
    cur_brier: float,
    label: str,
) -> list[dict]:
    """Run a grid sweep and return sorted results."""
    keys = list(grid.keys())
    combos = list(product(*[grid[k] for k in keys]))
    print(f"\n{'='*60}")
    print(f"{label}: {len(combos):,} configurations")
    print(f"{'='*60}")

    results = []
    t0 = time.time()
    for i, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        m = simulate_config(df, rc, masks, cfg)
        m.update(cfg)
        m["full_delta_vs_p"] = (m["full_brier"] - base_brier) * 1000
        m["full_delta_vs_cur"] = (m["full_brier"] - cur_brier) * 1000
        results.append(m)

        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(combos) - i - 1) / rate
            print(f"  {i+1}/{len(combos)} ({rate:.0f}/s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s ({len(combos)/elapsed:.0f}/s)")

    results.sort(key=lambda r: r["full_brier"])
    return results


def build_fine_grid(winner: dict) -> dict:
    """Build a fine grid centered on the coarse winner."""
    fine = {}
    for param, step in FINE_STEPS.items():
        center = winner[param]
        # Generate ±2 steps around center
        vals = sorted(set(
            round(center + i * step, 3)
            for i in range(-2, 3)
        ))
        # Clamp to valid ranges
        if param == "projection_clamp_hi":
            vals = [v for v in vals if 1.02 <= v <= 1.20]
        elif param == "multi_injury_boost":
            vals = [v for v in vals if 1.0 <= v <= 1.50]
        else:
            vals = [v for v in vals if 0.0 <= v <= 1.0]
        fine[param] = vals
    return fine


def print_top(results: list[dict], n: int = 20, label: str = ""):
    """Print top N configs."""
    print(f"\n{label} TOP {n}:")
    hdr = (
        f"{'star':>5s} {'core':>5s} {'demon':>5s} {'over':>5s} "
        f"{'multi':>5s} {'clamp':>5s} | {'dlt_p':>7s} {'dlt_c':>7s} "
        f"| {'worst':>6s} {'w/l':>5s}"
    )
    print(hdr)
    print("-" * 72)
    for r in results[:n]:
        wl = f"{r['dates_better']}/{r['dates_worse']}"
        print(
            f"{r['star_beneficiary_damp']:5.2f} "
            f"{r['core_beneficiary_damp']:5.2f} "
            f"{r['demon_tier_damp']:5.2f} "
            f"{r['over_direction_damp']:5.2f} "
            f"{r['multi_injury_boost']:5.2f} "
            f"{r['projection_clamp_hi']:5.2f} | "
            f"{r['full_delta_vs_p']:+7.3f} {r['full_delta_vs_cur']:+7.3f} "
            f"| {r['worst_slate_mB']:6.3f} {wl:>5s}"
        )


def per_date_breakdown(
    df: pd.DataFrame,
    rc: pd.DataFrame,
    masks: dict,
    cfg: dict,
    base_brier: float,
):
    """Print per-date breakdown of winning config."""
    star_d = cfg["star_beneficiary_damp"]
    core_d = cfg["core_beneficiary_damp"]
    demon_d = cfg["demon_tier_damp"]
    over_d = cfg["over_direction_damp"]
    multi_boost = cfg["multi_injury_boost"]
    clamp_hi = cfg["projection_clamp_hi"]

    bump_arr: np.ndarray = np.asarray(rc["bump"].values, dtype=float)
    damp = np.ones(len(rc))
    if star_d < 1.0: damp[masks["is_star"]] *= star_d
    if core_d < 1.0: damp[masks["is_core"]] *= core_d
    if demon_d < 1.0: damp[masks["is_demon"]] *= demon_d
    if over_d < 1.0: damp[masks["is_over"]] *= over_d
    if multi_boost > 1.0: damp[masks["is_multi_inj"]] *= multi_boost
    new_bump = np.minimum(bump_arr * damp, clamp_hi - 1.0)
    p_new = np.clip(np.asarray(rc["p"].values, dtype=float) + new_bump, 0.001, 0.999)

    all_p: np.ndarray = np.asarray(df["p"].values, dtype=float).copy()
    all_p[np.asarray(rc["_idx"].values, dtype=int)] = p_new

    print("\nPER-DATE BREAKDOWN (winner):")
    print(f"{'date':>12s} {'legs':>5s} {'rc':>5s} | {'cur_dp':>8s} {'new_dp':>8s} {'gain':>8s}")
    print("-" * 55)

    p_all = np.asarray(df["p"].values, dtype=float)
    pr_all = np.asarray(df["p_role"].values, dtype=float)
    hit_all = np.asarray(df["hit"].values, dtype=float)
    gd_arr = np.asarray(df["game_date"].values)
    gd_rc_arr = np.asarray(rc["game_date"].values)
    for gd in sorted(np.unique(gd_arr)):
        gm = gd_arr == gd
        n = int(gm.sum())
        rc_gm = gd_rc_arr == gd
        rc_n = int(rc_gm.sum())
        if rc_n == 0:
            continue
        bp = float(np.mean((p_all[gm] - hit_all[gm]) ** 2))
        br_cur = float(np.mean((pr_all[gm] - hit_all[gm]) ** 2))
        br_new = float(np.mean((all_p[gm] - hit_all[gm]) ** 2))
        cur_d = (br_cur - bp) * 1000
        new_d = (br_new - bp) * 1000
        gain = new_d - cur_d
        tag = ""
        if gain < -0.5: tag = " <<<"
        elif gain > 0.5: tag = " !!!"
        print(f"  {gd:>12s} {n:5d} {rc_n:5d} | {cur_d:+8.3f} {new_d:+8.3f} {gain:+8.3f}{tag}")


def slice_breakdown(
    df: pd.DataFrame,
    rc: pd.DataFrame,
    masks: dict,
    cfg: dict,
):
    """Print breakdown by slice."""
    star_d = cfg["star_beneficiary_damp"]
    core_d = cfg["core_beneficiary_damp"]
    demon_d = cfg["demon_tier_damp"]
    over_d = cfg["over_direction_damp"]
    multi_boost = cfg["multi_injury_boost"]
    clamp_hi = cfg["projection_clamp_hi"]

    bump_arr: np.ndarray = np.asarray(rc["bump"].values, dtype=float)
    damp = np.ones(len(rc))
    if star_d < 1.0: damp[masks["is_star"]] *= star_d
    if core_d < 1.0: damp[masks["is_core"]] *= core_d
    if demon_d < 1.0: damp[masks["is_demon"]] *= demon_d
    if over_d < 1.0: damp[masks["is_over"]] *= over_d
    if multi_boost > 1.0: damp[masks["is_multi_inj"]] *= multi_boost
    new_bump = np.minimum(bump_arr * damp, clamp_hi - 1.0)
    p_new = np.clip(np.asarray(rc["p"].values, dtype=float) + new_bump, 0.001, 0.999)

    p_base: np.ndarray = np.asarray(rc["p"].values, dtype=float)
    p_cur: np.ndarray = np.asarray(rc["p_role"].values, dtype=float)
    hit: np.ndarray = np.asarray(rc["hit"].values, dtype=float)

    slices = [
        ("ALL rc",       np.ones(len(rc), dtype=bool)),
        ("OVER",         masks["is_over"]),
        ("UNDER",        ~masks["is_over"]),
        ("DEMON",        masks["is_demon"]),
        ("GOBLIN",       (rc["tier"] == "GOBLIN").values),
        ("STANDARD",     (rc["tier"] == "STANDARD").values),
        ("star (33+)",   masks["is_star"]),
        ("core (28-33)", masks["is_core"]),
        ("role (<28)",   (~masks["is_star"] & ~masks["is_core"])),
        ("outs=1",       (rc["role_ctx_outs_used"] == 1).values),
        ("outs=2",       (rc["role_ctx_outs_used"] == 2).values),
        ("outs>=3",      masks["is_multi_inj"]),
        ("mult<1.03",    (rc["role_ctx_mult"] < 1.03).values),
        ("mult 1.03-06", ((rc["role_ctx_mult"] >= 1.03) & (rc["role_ctx_mult"] < 1.06)).values),
        ("mult 1.06+",   (rc["role_ctx_mult"] >= 1.06).values),
    ]

    print("\nSLICE BREAKDOWN (winner vs current vs p-only):")
    print(f"  {'slice':>14s} {'legs':>6s} | {'new_dp':>8s} {'cur_dp':>8s} {'gain':>8s}")
    print("  " + "-" * 55)
    for name, m in slices:
        if m.sum() < 30:
            continue
        bp = float(np.mean((p_base[m] - hit[m]) ** 2))
        bc = float(np.mean((p_cur[m] - hit[m]) ** 2))
        bn = float(np.mean((p_new[m] - hit[m]) ** 2))
        new_dp = (bn - bp) * 1000
        cur_dp = (bc - bp) * 1000
        gain = (bn - bc) * 1000
        print(f"  {name:>14s} {m.sum():6d} | {new_dp:+8.3f} {cur_dp:+8.3f} {gain:+8.3f}")


def apply_config(cfg: dict, dry_run: bool = False):
    """Apply the winning config to config.yaml."""
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    rc_section = config.get("role_ctx", {})

    before = {
        "star_beneficiary_damp": rc_section.get("star_beneficiary_damp", 1.0),
        "core_beneficiary_damp": rc_section.get("core_beneficiary_damp", 1.0),
        "demon_tier_damp": rc_section.get("demon_tier_damp", 1.0),
        "over_direction_damp": rc_section.get("over_direction_damp", 1.0),
        "projection_clamp_hi": rc_section.get("projection_clamp_hi", 1.20),
    }

    after = {
        "star_beneficiary_damp": cfg["star_beneficiary_damp"],
        "core_beneficiary_damp": cfg["core_beneficiary_damp"],
        "demon_tier_damp": cfg["demon_tier_damp"],
        "over_direction_damp": cfg["over_direction_damp"],
        "projection_clamp_hi": cfg["projection_clamp_hi"],
    }

    print("\n" + "=" * 60)
    print("CONFIG CHANGES:")
    print("=" * 60)
    any_change = False
    for k in after:
        b, a = before[k], after[k]
        if abs(b - a) > 1e-6:
            print(f"  {k}: {b} -> {a}")
            any_change = True
        else:
            print(f"  {k}: {b} (unchanged)")

    if not any_change:
        print("  No changes to apply.")
        return

    if dry_run:
        print("\n  [DRY RUN] Would apply above changes to config.yaml")
        return

    # Read raw text and do surgical replacements
    text = CONFIG_PATH.read_text()
    import re
    for k, v in after.items():
        # Match the key in the role_ctx section
        pattern = rf"(\s+{k}:\s*)[^\s#]+"
        repl = rf"\g<1>{v}"
        text, n = re.subn(pattern, repl, text, count=1)
        if n == 0:
            print(f"  WARNING: could not find {k} in config.yaml")

    CONFIG_PATH.write_text(text)
    print(f"\n  Applied to {CONFIG_PATH}")

    # Note about multi_injury_boost: this is a NEW param, needs code support
    if cfg.get("multi_injury_boost", 1.0) > 1.0:
        print(f"\n  NOTE: multi_injury_boost={cfg['multi_injury_boost']} requires code change in new_probability.py")


def save_results(
    coarse_top: list[dict],
    fine_top: list[dict] | None,
    winner: dict,
    base_brier: float,
    cur_brier: float,
):
    """Save results to YAML."""
    out = {
        "version": "role_ctx_trainer_v1",
        "cache": str(CACHE_PATH),
        "base_brier_mB": round(base_brier * 1000, 3),
        "current_brier_mB": round(cur_brier * 1000, 3),
        "winner": {k: round(v, 4) if isinstance(v, float) else v for k, v in winner.items()},
        "coarse_top10": [
            {k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}
            for r in coarse_top[:10]
        ],
    }
    # Embed config fingerprint
    with open(CONFIG_PATH) as _cf:
        _full_cfg = yaml.safe_load(_cf)
    out["_manifest"] = build_manifest(
        source="role_ctx_trainer_v1", cfg=_full_cfg,
        ensemble_dir=_full_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    )
    print(f"  Config fingerprint: {out['_manifest']['config_fingerprint']}")
    if fine_top:
        out["fine_top10"] = [
            {k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}
            for r in fine_top[:10]
        ]

    with open(RESULTS_PATH, "w") as f:
        yaml.dump(out, f, default_flow_style=False, sort_keys=False)
    print(f"\nResults saved to {RESULTS_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Role-ctx dampening trainer")
    parser.add_argument("--dry-run", action="store_true", help="Don't apply changes")
    args = parser.parse_args()

    df = load_cache()

    # Prepare role_ctx subset
    rc = df[df["role_ctx_outs_used"] > 0].copy()
    rc["bump"] = rc["p_role"] - rc["p"]
    rc["_idx"] = np.where(np.asarray(df["role_ctx_outs_used"].values, dtype=float) > 0)[0]

    masks = build_masks(df, rc)

    # Baselines
    _p = np.asarray(df["p"].values, dtype=float)
    _hit = np.asarray(df["hit"].values, dtype=float)
    _pr = np.asarray(df["p_role"].values, dtype=float)
    base_brier = float(np.mean((_p - _hit) ** 2))
    cur_brier = float(np.mean((_pr - _hit) ** 2))
    print(f"\nBaseline (p only):  {base_brier*1000:.3f} mB")
    print(f"Current  (p_role):  {cur_brier*1000:.3f} mB  (delta: {(cur_brier-base_brier)*1000:+.3f})")

    # Phase 1: Coarse sweep
    coarse = run_sweep(GRID_COARSE, df, rc, masks, base_brier, cur_brier, "COARSE SWEEP")
    print_top(coarse, 20, "COARSE")

    # Phase 2: Fine sweep around coarse winner
    coarse_winner = coarse[0]
    fine_grid = build_fine_grid(coarse_winner)
    fine_combos = 1
    for v in fine_grid.values():
        fine_combos *= len(v)
    print(f"\nFine grid: {fine_combos:,} combos centered on coarse winner")
    for k, v in fine_grid.items():
        print(f"  {k}: {v}")

    fine = run_sweep(fine_grid, df, rc, masks, base_brier, cur_brier, "FINE SWEEP")
    print_top(fine, 20, "FINE")

    # Winner: best fine config that doesn't regress any slate > 1.0 mB
    safe = [r for r in fine if r["worst_slate_mB"] < 1.0]
    if safe:
        winner = safe[0]
        print(f"\nWINNER (safe, worst slate < 1.0 mB):")
    else:
        winner = fine[0]
        print(f"\nWINNER (best overall, no safe config found):")

    for k in ["star_beneficiary_damp", "core_beneficiary_damp", "demon_tier_damp",
              "over_direction_damp", "multi_injury_boost", "projection_clamp_hi"]:
        print(f"  {k}: {winner[k]}")
    print(f"  full delta vs p:   {winner['full_delta_vs_p']:+.3f} mB")
    print(f"  full delta vs cur: {winner['full_delta_vs_cur']:+.3f} mB")
    print(f"  worst slate:       {winner['worst_slate_mB']:.3f} mB")
    print(f"  dates better/worse: {winner['dates_better']}/{winner['dates_worse']}")

    # Breakdowns
    per_date_breakdown(df, rc, masks, winner, base_brier)
    slice_breakdown(df, rc, masks, winner)

    # Save and apply
    save_results(coarse[:20], fine[:20], winner, base_brier, cur_brier)
    apply_config(winner, dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()

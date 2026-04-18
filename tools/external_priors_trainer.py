#!/usr/bin/env python3
"""
External Priors Trainer — sweep cap/scale/p_floor/p_ceil against truth-backed legs.

Reads the resim cache (or D-drive corpus) which already has:
  - external_prior_score (the raw tanh(edge/scale) score)
  - p_cal (calibrated probability pre-nudge)
  - hit (truth label)

We re-derive the nudge from scratch using the raw edge, sweeping parameters,
then measure Brier against hit to find optimal settings.

Usage:
  python tools/external_priors_trainer.py
  python tools/external_priors_trainer.py --save   # auto-apply best to config.yaml

Output:
  tools/external_priors_trainer_results.yaml
"""
from __future__ import annotations

import itertools
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
from Atlas.core.fingerprint import build_manifest, config_fingerprint

CACHE_PATH = REPO_ROOT / "data" / "model" / "_v12_resim_cache.pkl"
CONFIG_PATH = REPO_ROOT / "config.yaml"
RESULTS_PATH = REPO_ROOT / "tools" / "external_priors_trainer_results.yaml"

# Corpus location (workspace-relative)
D_CORPUS = Path(__file__).resolve().parents[1] / "data" / "telemetry" / "replay_runs"

# ── Sweep grid ───────────────────────────────────────────────────────────
# These are the knobs from external_priors.py apply_external_priors()

CAP_OPTIONS     = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
SCALE_OPTIONS   = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0]
P_FLOOR_OPTIONS = [0.01, 0.02]
P_CEIL_OPTIONS  = [0.98, 0.99]

# Total: 7×7×2×2 = 196 combos — runs in seconds


def load_legs() -> pd.DataFrame:
    """Load truth-backed legs with external prior data."""
    if CACHE_PATH.exists():
        print(f"[TRAINER] Loading resim cache: {CACHE_PATH}")
        cache = pickle.load(open(CACHE_PATH, "rb"))
        cv = cache["cv"]
        print(f"[TRAINER] Cache: {len(cv)} legs, {cv['game_date'].nunique()} dates")
    else:
        print("[TRAINER] No resim cache found, trying D-drive corpus...")
        cv = _load_d_corpus()

    # Filter to legs with external prior data + truth
    required = {"external_prior_score", "hit", "p_cal"}
    missing = required - set(cv.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    cv["_hit"] = pd.to_numeric(cv["hit"], errors="coerce")
    cv["_p_cal"] = pd.to_numeric(cv["p_cal"], errors="coerce")
    cv["_ep_score"] = pd.to_numeric(cv["external_prior_score"], errors="coerce")

    # We need the raw edge to re-derive the score with different scale values
    # If edge_at_pp_line is available, use it; otherwise reconstruct from score
    if "edge_at_pp_line" in cv.columns:
        cv["_raw_edge"] = pd.to_numeric(cv["edge_at_pp_line"], errors="coerce")
    else:
        cv["_raw_edge"] = np.nan  # will use _ep_score directly

    valid = cv["_hit"].notna() & cv["_p_cal"].notna()
    has_prior = cv["_ep_score"].notna() & (cv["_ep_score"].abs() > 1e-9)

    print(f"[TRAINER] Valid legs: {valid.sum()}, with priors: {has_prior.sum()}")
    print(f"[TRAINER] Prior coverage: {100 * has_prior.sum() / max(valid.sum(), 1):.1f}%")

    # Also get direction for direction-split analysis
    for col in ["direction", "game_date", "stat"]:
        if col not in cv.columns:
            cv[col] = ""

    return cv[valid].copy()


def _load_d_corpus() -> pd.DataFrame:
    """Fallback: load from D-drive corpus dirs."""
    frames = []
    if not D_CORPUS.exists():
        raise FileNotFoundError(f"No resim cache and D-drive corpus not found: {D_CORPUS}")
    for d in sorted(D_CORPUS.iterdir()):
        evl = d / "eval_legs.csv"
        scored = d / "scored_legs_deduped.csv"
        if evl.exists() and scored.exists():
            try:
                s = pd.read_csv(scored, low_memory=False)
                e = pd.read_csv(evl, low_memory=False)
                if "hit" in e.columns and "projection_id" in s.columns and "projection_id" in e.columns:
                    m = s.merge(e[["projection_id", "hit"]].drop_duplicates(), on="projection_id", how="left")
                    frames.append(m)
            except Exception:
                pass
    if not frames:
        raise FileNotFoundError("No valid corpus dirs found on D drive")
    return pd.concat(frames, ignore_index=True)


def brier(p: np.ndarray, hit: np.ndarray) -> float:
    mask = np.isfinite(p) & np.isfinite(hit)
    if mask.sum() == 0:
        return 1.0
    return float(np.mean((p[mask] - hit[mask]) ** 2))


def score_config(
    df: pd.DataFrame,
    cap: float,
    scale: float,
    p_floor: float,
    p_ceil: float,
) -> dict[str, Any]:
    """Apply external prior nudge with given params and measure Brier."""
    p_cal = np.asarray(df["_p_cal"].values, dtype="float64").copy()
    ep_score = np.asarray(df["_ep_score"].values, dtype="float64").copy()
    raw_edge = np.asarray(df["_raw_edge"].values, dtype="float64").copy()
    hit = np.asarray(df["_hit"].values, dtype="float64")

    # Re-derive score if we have raw edge and are testing different scale
    has_edge = np.isfinite(raw_edge)
    if has_edge.any():
        new_score = np.zeros_like(ep_score)
        new_score[has_edge] = np.tanh(raw_edge[has_edge] / max(scale, 1e-9))
        new_score[~has_edge] = ep_score[~has_edge]  # fallback to cached score
        ep_score = new_score

    # Apply nudge: p_new = clip(p_cal + cap * score, p_floor, p_ceil)
    has_prior = np.isfinite(ep_score) & (np.abs(ep_score) > 1e-9)
    nudge = np.where(has_prior, cap * np.clip(ep_score, -1.0, 1.0), 0.0)
    p_new = np.clip(p_cal + nudge, p_floor, p_ceil)

    brier_base = brier(p_cal, hit)
    brier_new = brier(p_new, hit)

    # Direction split
    dirs = np.asarray(df["direction"].astype(str).str.strip().str.upper().values)
    over_mask = dirs == "OVER"
    under_mask = dirs == "UNDER"

    result = {
        "cap": cap,
        "scale": scale,
        "p_floor": p_floor,
        "p_ceil": p_ceil,
        "brier_base": round(brier_base, 7),
        "brier_new": round(brier_new, 7),
        "delta_mB": round((brier_new - brier_base) * 1000, 4),
        "n_total": int(len(hit)),
        "n_nudged": int(has_prior.sum()),
    }

    if over_mask.sum() > 100:
        result["brier_over_base"] = round(brier(p_cal[over_mask], hit[over_mask]), 7)
        result["brier_over_new"] = round(brier(p_new[over_mask], hit[over_mask]), 7)
        result["delta_over_mB"] = round((result["brier_over_new"] - result["brier_over_base"]) * 1000, 4)
    if under_mask.sum() > 100:
        result["brier_under_base"] = round(brier(p_cal[under_mask], hit[under_mask]), 7)
        result["brier_under_new"] = round(brier(p_new[under_mask], hit[under_mask]), 7)
        result["delta_under_mB"] = round((result["brier_under_new"] - result["brier_under_base"]) * 1000, 4)

    # Per-date non-regression check
    dates = df["game_date"].values
    unique_dates = sorted(set(d for d in dates if d and str(d) != "nan"))
    regressed_dates = 0
    for d in unique_dates:
        dm = dates == d
        if dm.sum() < 20:
            continue
        b_base_d = brier(p_cal[dm], hit[dm])
        b_new_d = brier(p_new[dm], hit[dm])
        if b_new_d > b_base_d + 0.001:  # 1 mB regression threshold
            regressed_dates += 1
    result["regressed_dates"] = regressed_dates
    result["total_dates"] = len(unique_dates)

    return result


def main():
    save_mode = "--save" in sys.argv

    df = load_legs()

    combos = list(itertools.product(CAP_OPTIONS, SCALE_OPTIONS, P_FLOOR_OPTIONS, P_CEIL_OPTIONS))
    print(f"\n[TRAINER] Sweeping {len(combos)} parameter combinations...")

    results: list[dict[str, Any]] = []
    best_brier = 1.0
    best_result: dict[str, Any] = {}

    t0 = time.time()
    for i, (cap, scale, p_floor, p_ceil) in enumerate(combos):
        r = score_config(df, cap, scale, p_floor, p_ceil)
        results.append(r)

        if r["brier_new"] < best_brier:
            best_brier = r["brier_new"]
            best_result = r

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(combos)}] elapsed={elapsed:.1f}s best_delta={best_result['delta_mB']:+.4f} mB")

    elapsed = time.time() - t0
    print(f"\n[TRAINER] Sweep complete: {len(combos)} combos in {elapsed:.1f}s")

    # Sort by brier_new ascending
    results.sort(key=lambda r: r["brier_new"])
    top10 = results[:10]

    # Also find best non-regressive result
    non_reg = [r for r in results if r["regressed_dates"] == 0]
    non_reg.sort(key=lambda r: r["brier_new"])
    best_safe: dict[str, Any] | None = non_reg[0] if non_reg else None

    # Load current config for comparison
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    ep_cfg = cfg.get("optimizer", cfg).get("external_priors", cfg.get("external_priors", {}))
    current = {
        "cap": float(ep_cfg.get("cap", 0.03)),
        "scale": float(ep_cfg.get("scale", 3.0)),
        "p_floor": float(ep_cfg.get("p_floor", 0.01)),
        "p_ceil": float(ep_cfg.get("p_ceil", 0.99)),
    }

    # Evaluate current config
    current_result = score_config(df, **current)

    print("\n" + "=" * 70)
    print("EXTERNAL PRIORS TRAINER RESULTS")
    print("=" * 70)
    print(f"\nCurrent config:  cap={current['cap']}, scale={current['scale']}, "
          f"p_floor={current['p_floor']}, p_ceil={current['p_ceil']}")
    print(f"  Brier: {current_result['brier_new']:.6f} (delta: {current_result['delta_mB']:+.4f} mB vs no-prior)")
    print(f"  Nudged: {current_result['n_nudged']}/{current_result['n_total']} legs")
    print(f"  Regressed dates: {current_result['regressed_dates']}/{current_result['total_dates']}")

    if current_result.get("delta_over_mB") is not None:
        print(f"  OVER delta: {current_result['delta_over_mB']:+.4f} mB  |  UNDER delta: {current_result.get('delta_under_mB', 'N/A'):+.4f} mB")

    print(f"\nBest result:     cap={best_result['cap']}, scale={best_result['scale']}, "
          f"p_floor={best_result['p_floor']}, p_ceil={best_result['p_ceil']}")
    print(f"  Brier: {best_result['brier_new']:.6f} (delta: {best_result['delta_mB']:+.4f} mB vs no-prior)")
    print(f"  Nudged: {best_result['n_nudged']}/{best_result['n_total']} legs")
    print(f"  Regressed dates: {best_result['regressed_dates']}/{best_result['total_dates']}")

    if best_result.get("delta_over_mB") is not None:
        print(f"  OVER delta: {best_result['delta_over_mB']:+.4f} mB  |  UNDER delta: {best_result.get('delta_under_mB', 'N/A'):+.4f} mB")

    if best_safe and best_safe != best_result:
        print(f"\nBest safe (0 regressions): cap={best_safe['cap']}, scale={best_safe['scale']}, "
              f"p_floor={best_safe['p_floor']}, p_ceil={best_safe['p_ceil']}")
        print(f"  Brier: {best_safe['brier_new']:.6f} (delta: {best_safe['delta_mB']:+.4f} mB)")

    improvement_vs_current = (current_result["brier_new"] - best_result["brier_new"]) * 1000
    print(f"\nImprovement over current: {improvement_vs_current:+.4f} mB")

    print("\nTop 10:")
    print(f"{'rank':>4} {'cap':>5} {'scale':>5} {'floor':>5} {'ceil':>5} {'brier':>10} {'delta_mB':>10} {'reg':>4}")
    for i, r in enumerate(top10):
        print(f"{i+1:>4} {r['cap']:>5.2f} {r['scale']:>5.1f} {r['p_floor']:>5.2f} {r['p_ceil']:>5.2f} "
              f"{r['brier_new']:>10.6f} {r['delta_mB']:>+10.4f} {r['regressed_dates']:>4}")

    # Save results
    with open(CONFIG_PATH) as _cf:
        _full_cfg = yaml.safe_load(_cf)
    output = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_manifest": build_manifest(
            source="external_priors_trainer", cfg=_full_cfg,
            ensemble_dir=_full_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
        ),
        "corpus_legs": int(len(df)),
        "corpus_dates": int(df["game_date"].nunique()),
        "legs_with_priors": int((df["_ep_score"].abs() > 1e-9).sum()),
        "combos_tested": len(combos),
        "current_config": current,
        "current_brier": current_result["brier_new"],
        "current_delta_mB": current_result["delta_mB"],
        "best_config": {
            "cap": best_result["cap"],
            "scale": best_result["scale"],
            "p_floor": best_result["p_floor"],
            "p_ceil": best_result["p_ceil"],
        },
        "best_brier": best_result["brier_new"],
        "best_delta_mB": best_result["delta_mB"],
        "best_regressed_dates": best_result["regressed_dates"],
        "improvement_vs_current_mB": round(improvement_vs_current, 4),
        "best_safe_config": {
            "cap": best_safe["cap"],
            "scale": best_safe["scale"],
            "p_floor": best_safe["p_floor"],
            "p_ceil": best_safe["p_ceil"],
        } if best_safe else None,
        "top10": top10,
    }

    with open(RESULTS_PATH, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False)
    print(f"\n[TRAINER] Results saved: {RESULTS_PATH}")

    # Auto-apply if --save and there's improvement
    if save_mode and improvement_vs_current > 0:
        target: dict[str, Any] = best_safe if best_safe else best_result
        print(f"\n[TRAINER] Applying best config to config.yaml...")
        _apply_to_config(target)
        print(f"[TRAINER] Applied: cap={target['cap']}, scale={target['scale']}, "
              f"p_floor={target['p_floor']}, p_ceil={target['p_ceil']}")
    elif save_mode:
        print(f"\n[TRAINER] No improvement over current config — not applying.")


def _apply_to_config(result: dict):
    """Write best params back to config.yaml."""
    with open(CONFIG_PATH) as f:
        raw = f.read()

    # Simple targeted replacements
    import re
    replacements = {
        "cap": result["cap"],
        "scale": result["scale"],
        "p_floor": result["p_floor"],
        "p_ceil": result["p_ceil"],
    }
    for key, val in replacements.items():
        # Match within external_priors block
        pattern = rf"(external_priors:.*?{key}:\s*)\S+"
        raw = re.sub(pattern, rf"\g<1>{val}", raw, count=1, flags=re.DOTALL)

    with open(CONFIG_PATH, "w") as f:
        f.write(raw)


if __name__ == "__main__":
    main()

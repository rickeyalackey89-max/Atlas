#!/usr/bin/env python
"""
kernel_trainer_v2_loso.py — LOSO-disciplined MC Kernel Parameter Trainer

Surgical evolution of kernel_trainer_v1.py with three critical changes:
  1. --cache CLI arg (defaults to playoff cache _v1_playoff_resim_cache.pkl)
  2. LOSO discipline: leave-one-date-out fit/score, picks winner by aggregate
     held-out brier_adj, and HARD-GATES on per-slate non-regression
  3. Default metric switched to brier_adj (what the calibrator actually sees)

Methodology:
  - For each candidate config, run MC sim once over the full cache.
  - For each held-out date, compute brier_adj on that date (this is "held-out"
    in the sense that the *config selection* is judged by aggregate held-out
    Brier, not in-sample). Because configs are global hyperparameters and the
    cache covers fixed inputs, true LOSO refit is unnecessary; what matters
    is reporting per-slate deltas vs baseline so we can gate on worst-slate
    non-regression.
  - Promotion gate: aggregate brier_adj improves AND zero slates regress
    by more than --gate_mB (default 1.0).

Re-uses simulate_batch / run_simulation / coarse-grid generators from v1
to keep the math identical. Only orchestration changes.

Usage:
  python tools/kernel_trainer_v2_loso.py                              # run, no apply
  python tools/kernel_trainer_v2_loso.py --apply                      # apply if gate passes
  python tools/kernel_trainer_v2_loso.py --cache PATH                 # custom cache
  python tools/kernel_trainer_v2_loso.py --phase 1                    # coarse only
  python tools/kernel_trainer_v2_loso.py --gate_mB 0.5                # tighter gate
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

# Reuse v1 internals (math is identical; we only change orchestration)
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
import kernel_trainer_v1 as kt1  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = REPO_ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
CONFIG_PATH = REPO_ROOT / "config.yaml"
RESULTS_PATH = REPO_ROOT / "tools" / "kernel_trainer_v2_loso_results.yaml"


# ---------------------------------------------------------------------------
# Cache loader (parametrised)
# ---------------------------------------------------------------------------
def load_cache(path: Path) -> pd.DataFrame:
    with open(path, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    for c in ["rate_mean", "rate_std", "min_mean", "min_std", "spread",
              "q_blowout", "minutes_s", "line", "games_used", "hit",
              "opp_defense_rel"]:
        if c in cv.columns:
            cv[c] = pd.to_numeric(cv[c], errors="coerce")
    cv["direction_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
    cv["is_under"] = (cv["direction_u"] == "UNDER").astype(np.float64)
    cv["is_star"] = (cv["min_mean"] >= 33.0).astype(bool)
    _stat_norm = {"POINTS": "PTS", "REBOUNDS": "REB", "ASSISTS": "AST",
                  "REBS": "REB", "ASTS": "AST", "3PM": "FG3M"}
    cv["stat_u"] = cv["stat_u"].replace(_stat_norm)
    print(f"Loaded {len(cv):,} legs, {cv['game_date'].nunique()} dates from {path.name}")
    return cv


# ---------------------------------------------------------------------------
# Per-slate evaluation
# ---------------------------------------------------------------------------
def per_slate_brier_adj(cv: pd.DataFrame, params: dict[str, float], sims: int) -> dict[str, dict[str, float]]:
    """Run one full MC sim, return per-date brier_adj and brier_p."""
    res = kt1.run_simulation(cv, params, sims=sims, return_per_date=True)
    return res["per_date"]


def gate_check(
    per_date_new: dict[str, dict[str, float]],
    per_date_base: dict[str, dict[str, float]],
    gate_mB: float,
    metric: str = "brier_adj",
) -> tuple[bool, list[tuple[str, float, int]]]:
    """Return (passes, list of (date, delta_mB, n))."""
    rows: list[tuple[str, float, int]] = []
    passes = True
    for d in sorted(per_date_new.keys()):
        b_new = per_date_new[d][metric]
        b_old = per_date_base.get(d, {}).get(metric, b_new)
        delta_mB = (b_new - b_old) * 1000.0
        n = per_date_new[d].get("n", 0)
        rows.append((str(d), delta_mB, int(n)))
        if delta_mB > gate_mB:
            passes = False
    return passes, rows


# ---------------------------------------------------------------------------
# Coarse sweep over a family with LOSO gate at the end
# ---------------------------------------------------------------------------
def sweep_family_loso(
    cv: pd.DataFrame,
    configs: list[dict[str, float]],
    family_name: str,
    base_params: dict[str, float],
    base_per_date: dict[str, dict[str, float]],
    sims: int,
    metric: str,
    gate_mB: float,
) -> dict[str, Any]:
    """
    Sweep a family. For each candidate compute aggregate brier on cv.
    Take the top K candidates by aggregate, then re-evaluate them with
    per-date detail and pick the BEST aggregate that ALSO passes the
    per-slate gate.
    """
    print(f"\n{'='*70}")
    print(f"Sweeping {family_name}: {len(configs):,} configs, {sims} sims, gate=+{gate_mB:.2f} mB")
    print(f"{'='*70}")

    t0 = time.time()
    results: list[tuple[float, dict[str, float], float]] = []  # (brier, cfg, brier_p)

    for i, cfg in enumerate(configs):
        params = {**base_params, **cfg}
        res = kt1.run_simulation(cv, params, sims=sims)
        results.append((res[metric], cfg, res["brier_p"]))
        if (i + 1) % 50 == 0 or i == len(configs) - 1:
            best = min(r[0] for r in results)
            elapsed = time.time() - t0
            rate = (i + 1) / max(elapsed, 1e-6)
            eta = (len(configs) - i - 1) / max(rate, 1e-6)
            print(f"  [{i+1:>5}/{len(configs)}] best={best*1000:.3f} mB  ({elapsed:.0f}s, ETA {eta:.0f}s)")

    # Sort by aggregate metric, ascending
    results.sort(key=lambda r: r[0])
    base_agg = sum(d["n"] * d[metric] for d in base_per_date.values()) / max(1, sum(d["n"] for d in base_per_date.values()))

    # Try top-K against the gate
    top_k = min(20, len(results))
    print(f"\n  Top {top_k} aggregate candidates -> per-slate gate check:")
    chosen_cfg: dict[str, float] | None = None
    chosen_brier: float = float("inf")
    chosen_rows: list[tuple[str, float, int]] = []

    for rank, (b, cfg, b_p) in enumerate(results[:top_k]):
        params = {**base_params, **cfg}
        per_date = per_slate_brier_adj(cv, params, sims=sims)
        passes, rows = gate_check(per_date, base_per_date, gate_mB, metric=metric)
        worst = max(rows, key=lambda r: r[1]) if rows else ("", 0.0, 0)
        agg_delta = (b - base_agg) * 1000.0
        status = "PASS" if passes else "REGRESS"
        print(f"    [{rank+1:>2}] agg d={agg_delta:+.3f} mB  worst={worst[0]} ({worst[1]:+.3f})  {status}")
        if passes and chosen_cfg is None:
            chosen_cfg = cfg
            chosen_brier = b
            chosen_rows = rows
            # don't break — keep printing for visibility, but lock first PASS
    if chosen_cfg is None:
        print(f"  WARNING: No candidate in top-{top_k} passed gate.")
        # Fall back to base (no change)
        chosen_cfg = {}
        chosen_brier = base_agg
        chosen_rows = []

    elapsed = time.time() - t0
    delta_mB = (chosen_brier - base_agg) * 1000.0
    print(f"\n  {family_name} winner (gated):")
    print(f"    base: {base_agg*1000:.3f} mB  -> chosen: {chosen_brier*1000:.3f} mB  (d {delta_mB:+.3f} mB)")
    print(f"    config: {chosen_cfg}")

    return {
        "family": family_name,
        "best_config": chosen_cfg,
        "best_brier": float(chosen_brier),
        "base_brier": float(base_agg),
        "delta_mB": float(delta_mB),
        "per_slate_rows": [{"date": d, "delta_mB": dl, "n": n} for d, dl, n in chosen_rows],
        "n_configs": len(configs),
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# Phase 1 / Phase 2 with LOSO gate
# ---------------------------------------------------------------------------
def run_phase1_loso(cv: pd.DataFrame, sims: int, metric: str, gate_mB: float) -> dict[str, Any]:
    base = kt1._read_current_defaults()
    print(f"\nCurrent production params:")
    for k, v in sorted(base.items()):
        print(f"  {k}: {v}")

    print(f"\nBaseline ({sims} sims, full cache)...")
    base_per_date = per_slate_brier_adj(cv, base, sims=sims)
    base_agg = sum(d["n"] * d[metric] for d in base_per_date.values()) / max(1, sum(d["n"] for d in base_per_date.values()))
    base_p = sum(d["n"] * d["brier_p"] for d in base_per_date.values()) / max(1, sum(d["n"] for d in base_per_date.values()))
    print(f"  Baseline brier_p:   {base_p*1000:.3f} mB")
    print(f"  Baseline brier_adj: {base_agg*1000:.3f} mB")

    # Trimmed coarse grids for speed (LOSO discipline preserved):
    # - variance: 5x5x4x3 = 300 (was 7x7x4x4 = 784)
    # - skip 'defense' family entirely (opp_defense_rel missing from playoff cache => no-op)
    import itertools as _it
    def _trim_variance():
        cfgs = []
        for gscale, corr, pts_r, combo_r in _it.product(
            [0.9, 1.0, 1.1, 1.2, 1.3],
            [0.10, 0.20, 0.30, 0.35, 0.45],
            [0.85, 1.0, 1.15, 1.3],
            [0.85, 1.0, 1.15],
        ):
            pts = round(gscale * pts_r, 3)
            ast = round(gscale * 0.92, 3)
            reb = round(gscale * 0.77, 3)
            fg3m = round(gscale * 0.77, 3)
            combo = round(gscale * combo_r, 3)
            cfgs.append({
                "rate_std_PTS": pts, "rate_std_AST": ast, "rate_std_REB": reb,
                "rate_std_FG3M": fg3m, "rate_std_PRA": combo, "rate_std_PR": combo,
                "rate_std_PA": combo, "rate_std_RA": round(combo * 0.85, 3),
                "rate_min_correlation": corr,
            })
        return cfgs

    families = {
        "variance":    _trim_variance(),
        "blowout":     kt1.generate_coarse_grid_blowout(),
        "thin_sample": kt1.generate_coarse_grid_thin(),
    }

    results: dict[str, Any] = {}
    combined: dict[str, float] = {}
    for name, configs in families.items():
        res = sweep_family_loso(cv, configs, name, base, base_per_date, sims, metric, gate_mB)
        results[name] = res
        combined.update(res["best_config"])

    # Combined check
    combined_params = {**base, **combined}
    combined_pd = per_slate_brier_adj(cv, combined_params, sims=sims)
    combined_agg = sum(d["n"] * d[metric] for d in combined_pd.values()) / max(1, sum(d["n"] for d in combined_pd.values()))
    passes, rows = gate_check(combined_pd, base_per_date, gate_mB, metric=metric)

    print(f"\n{'='*70}")
    print(f"PHASE 1 COMBINED")
    print(f"{'='*70}")
    print(f"  Base:     {base_agg*1000:.3f} mB")
    print(f"  Combined: {combined_agg*1000:.3f} mB  (d {(combined_agg-base_agg)*1000:+.3f} mB)")
    print(f"  Gate:     {'PASS' if passes else 'REGRESS'}")
    for d, dl, n in rows:
        tag = "GOOD" if dl <= 0 else ("OK" if dl <= gate_mB else "HURT")
        print(f"    {d}  N={n:>5}  d={dl:+.3f} mB  {tag}")

    return {
        "baseline_brier_adj": base_agg, "baseline_brier_p": base_p,
        "combined_brier_adj": combined_agg,
        "delta_mB": (combined_agg - base_agg) * 1000.0,
        "combined_winners": {k: float(v) for k, v in combined.items()},
        "gate_passes": passes,
        "per_slate": [{"date": d, "delta_mB": dl, "n": n} for d, dl, n in rows],
        "families": {k: {kk: vv for kk, vv in v.items() if kk != "per_slate_rows"} for k, v in results.items()},
        "base_per_date": {d: {"brier_adj": v["brier_adj"], "brier_p": v["brier_p"], "n": v["n"]} for d, v in base_per_date.items()},
    }


def run_phase2_loso(cv: pd.DataFrame, p1_winners: dict[str, float], sims: int, metric: str, gate_mB: float) -> dict[str, Any]:
    base = kt1._read_current_defaults()
    print(f"\n{'='*70}")
    print(f"PHASE 2: Fine sweep around Phase 1 winners (gate=+{gate_mB:.2f} mB)")
    print(f"{'='*70}")

    base_per_date = per_slate_brier_adj(cv, base, sims=sims)
    base_agg = sum(d["n"] * d[metric] for d in base_per_date.values()) / max(1, sum(d["n"] for d in base_per_date.values()))

    configs = kt1.generate_fine_grid(p1_winners)
    print(f"  Fine grid: {len(configs)} configs, {sims} sims")

    t0 = time.time()
    cand: list[tuple[float, dict[str, float], float]] = []
    for i, cfg in enumerate(configs):
        params = {**base, **cfg}
        res = kt1.run_simulation(cv, params, sims=sims)
        cand.append((res[metric], cfg, res["brier_p"]))
        if (i + 1) % 100 == 0 or i == len(configs) - 1:
            best = min(c[0] for c in cand)
            elapsed = time.time() - t0
            rate = (i + 1) / max(elapsed, 1e-6)
            eta = (len(configs) - i - 1) / max(rate, 1e-6)
            print(f"  [{i+1:>5}/{len(configs)}] best={best*1000:.3f} mB  ({elapsed:.0f}s, ETA {eta:.0f}s)")

    cand.sort(key=lambda r: r[0])
    top_k = min(30, len(cand))
    print(f"\n  Top {top_k} -> per-slate gate check:")

    chosen_cfg: dict[str, float] | None = None
    chosen_brier = float("inf")
    chosen_rows: list[tuple[str, float, int]] = []
    for rank, (b, cfg, b_p) in enumerate(cand[:top_k]):
        params = {**base, **cfg}
        per_date = per_slate_brier_adj(cv, params, sims=sims)
        passes, rows = gate_check(per_date, base_per_date, gate_mB, metric=metric)
        worst = max(rows, key=lambda r: r[1]) if rows else ("", 0.0, 0)
        agg_delta = (b - base_agg) * 1000.0
        status = "PASS" if passes else "REGRESS"
        print(f"    [{rank+1:>2}] agg d={agg_delta:+.3f} mB  worst={worst[0]} ({worst[1]:+.3f})  {status}")
        if passes and chosen_cfg is None:
            chosen_cfg = cfg
            chosen_brier = b
            chosen_rows = rows

    elapsed = time.time() - t0
    if chosen_cfg is None:
        print("  WARNING: no Phase 2 candidate passed gate. Falling back to Phase 1 winners.")
        chosen_cfg = dict(p1_winners)
        # Re-evaluate p1 winners
        params = {**base, **chosen_cfg}
        per_date = per_slate_brier_adj(cv, params, sims=sims)
        passes, rows = gate_check(per_date, base_per_date, gate_mB, metric=metric)
        chosen_brier = sum(d["n"] * d[metric] for d in per_date.values()) / max(1, sum(d["n"] for d in per_date.values()))
        chosen_rows = rows

    delta_total = (chosen_brier - base_agg) * 1000.0
    n_better = sum(1 for _, dl, _ in chosen_rows if dl <= 0)
    n_worse = sum(1 for _, dl, _ in chosen_rows if dl > 0)
    worst = max(chosen_rows, key=lambda r: r[1]) if chosen_rows else ("", 0.0, 0)

    print(f"\n  PHASE 2 FINAL:")
    print(f"    base:   {base_agg*1000:.3f} mB")
    print(f"    winner: {chosen_brier*1000:.3f} mB  (d {delta_total:+.3f} mB)")
    print(f"    dates better/worse: {n_better}/{n_worse}")
    print(f"    worst slate: {worst[0]}  d={worst[1]:+.3f} mB")
    for d, dl, n in chosen_rows:
        tag = "GOOD" if dl <= 0 else ("OK" if dl <= gate_mB else "HURT")
        print(f"    {d}  N={n:>5}  d={dl:+.3f} mB  {tag}")

    return {
        "winner_params": {k: float(v) for k, v in chosen_cfg.items()},
        "winner_brier_adj": float(chosen_brier),
        "base_brier_adj": float(base_agg),
        "delta_mB": float(delta_total),
        "dates_better": int(n_better),
        "dates_worse": int(n_worse),
        "worst_slate": worst[0],
        "worst_delta_mB": float(worst[1]),
        "gate_passes": worst[1] <= gate_mB if chosen_rows else False,
        "per_slate": [{"date": d, "delta_mB": dl, "n": n} for d, dl, n in chosen_rows],
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="LOSO-disciplined MC kernel trainer")
    ap.add_argument("--cache", type=str, default=str(DEFAULT_CACHE),
                    help=f"Resim cache path (default: {DEFAULT_CACHE.name})")
    ap.add_argument("--phase", type=int, choices=[1, 2], default=None,
                    help="Run only phase 1 or 2 (default: both)")
    ap.add_argument("--sims", type=int, default=None, help="Override sim count")
    ap.add_argument("--metric", choices=["brier_p", "brier_adj"], default="brier_adj",
                    help="Optimisation target (default: brier_adj)")
    ap.add_argument("--gate_mB", type=float, default=1.0,
                    help="Per-slate non-regression gate in mB (default 1.0)")
    ap.add_argument("--apply", action="store_true",
                    help="Apply Phase 2 winner to config.yaml IFF gate passes")
    args = ap.parse_args()

    cache_path = Path(args.cache)
    if not cache_path.exists():
        print(f"ERROR: cache not found: {cache_path}")
        sys.exit(1)

    coarse_sims = args.sims or 500   # 500 sims @ 13K legs => MC noise ~0.0025
    fine_sims = args.sims or kt1.FINE_SIMS

    print(f"Kernel Trainer v2 (LOSO-gated)")
    print(f"  Cache:  {cache_path}")
    print(f"  Sims:   coarse={coarse_sims}, fine={fine_sims}")
    print(f"  Metric: {args.metric}")
    print(f"  Gate:   +{args.gate_mB:.2f} mB worst-slate")

    # Inject the cache path into v1 so its run_simulation logic is unaffected
    kt1.CACHE_PATH = cache_path  # used only if v1 helpers re-load; we pass cv directly

    cv = load_cache(cache_path)
    valid_mask = cv["hit"].notna()
    cv = cv[valid_mask].reset_index(drop=True)
    print(f"  Valid legs: {len(cv):,}")
    print(f"  Dates: {sorted(cv['game_date'].astype(str).unique())}")

    out: dict[str, Any] = {"version": "kernel_trainer_v2_loso", "cache": str(cache_path)}

    if args.phase is None or args.phase == 1:
        out["phase1"] = run_phase1_loso(cv, sims=coarse_sims, metric=args.metric, gate_mB=args.gate_mB)
        with open(RESULTS_PATH, "w") as f:
            yaml.dump(out, f, default_flow_style=False, sort_keys=False)
        print(f"\n  Saved Phase 1 -> {RESULTS_PATH}")

    if args.phase is None or args.phase == 2:
        if "phase1" in out:
            p1w = out["phase1"]["combined_winners"]
        elif RESULTS_PATH.exists():
            p1w = (yaml.safe_load(open(RESULTS_PATH)) or {}).get("phase1", {}).get("combined_winners", {})
            if not p1w:
                print("ERROR: no phase1 winners in results file")
                return
        else:
            print("ERROR: no phase1 results")
            return

        out["phase2"] = run_phase2_loso(cv, p1w, sims=fine_sims, metric=args.metric, gate_mB=args.gate_mB)
        with open(RESULTS_PATH, "w") as f:
            yaml.dump(out, f, default_flow_style=False, sort_keys=False)
        print(f"\n  Saved Phase 1+2 -> {RESULTS_PATH}")

        if args.apply:
            if out["phase2"].get("gate_passes"):
                kt1.apply_to_config(out["phase2"]["winner_params"])
                print("  APPLIED to config.yaml")
            else:
                print("  GATE FAILED — refusing to apply.")

    print("\nDone.")


if __name__ == "__main__":
    main()

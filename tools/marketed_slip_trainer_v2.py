#!/usr/bin/env python
"""
Marketed Slip Trainer v2
========================
Deep parameter optimization for the marketed slip builder.

Templates are FIXED (not swept):
  3-leg: 1 GOBLIN + 2 STANDARD
  4-leg: 2 GOBLIN + 2 STANDARD
  5-leg: 2 GOBLIN + 2 STANDARD + 1 DEMON

Sweeps:
  Phase 1 — Threshold grid (fine-grained, per tier)
  Phase 2 — Scoring weights (l20_edge weight for GOBLIN/DEMON, dir_te weight for STANDARD)
  Phase 3 — Stat exclusion combinations
  Phase 4 — Direction filters (per tier OVER/UNDER/both)
  Phase 5 — Combined best-of-each

Reports per-stat and per-direction breakdowns for every sweep winner.
"""
from __future__ import annotations

import copy
import json
import itertools
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# ── Paths ────────────────────────────────────────────────────────────
CACHE_PATH = Path(r"C:\Users\13142\Atlas\NBA\data\model\_v17_resim_cache.pkl")
BASE = Path(r"C:\Users\13142\Atlas\NBA\data\telemetry\v18_corpus")

# ── Fixed templates — DO NOT SWEEP ───────────────────────────────────
FIXED_TEMPLATES = [
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
]

# ── Base config ──────────────────────────────────────────────────────
BASE_CONFIG = {
    "marketed_slips": {
        "enabled": True,
        "calibration_path": "data/model/marketed_calibration.json",
        "excluded_stats": ["BLK", "STL", "TO"],
        "min_thresholds": {
            "GOBLIN": 0.57,     # matches production config.yaml
            "STANDARD": 0.30,   # matches production config.yaml
            "DEMON": 0.28,      # matches production config.yaml
        },
        "direction_filters": {},
        "correlation": {
            "same_team_penalty": 0.03,
            "hedge_bonus": 0.015,
            "blowout_penalty": 0.02,
        },
    }
}

# ── Sweep grids ──────────────────────────────────────────────────────

# Phase 1: Fine-grained threshold sweep
THRESHOLD_GRID = {
    "GOBLIN":   [0.50, 0.52, 0.55, 0.57, 0.60, 0.62, 0.65, 0.68, 0.70],
    "STANDARD": [0.30, 0.33, 0.35, 0.37, 0.40, 0.42, 0.45, 0.47, 0.50],
    "DEMON":    [0.20, 0.25, 0.28, 0.30, 0.33, 0.35, 0.38, 0.40],
}

# Phase 2: Scoring weight sweep
# GOBLIN score = p_cal^(1-w) * l20_edge^w  (w=0.5 is current sqrt-blend, w=1.0 is pure l20)
# STANDARD score = dir_te^(1-v) * p_cal^v
GOBLIN_L20_WEIGHTS  = [0.0, 0.25, 0.50, 0.75, 1.0]   # weight on l20_edge in GOBLIN score
STANDARD_TE_WEIGHTS = [0.5, 0.65, 0.75, 0.85, 1.0]   # weight on dir_te in STANDARD score
DEMON_L20_WEIGHTS   = [0.0, 0.25, 0.50, 0.75, 1.0]   # weight on l20_edge in DEMON score

# Phase 3: Stat exclusions (combinations of optional exclusions)
ALWAYS_EXCLUDE = ["BLK", "STL", "TO"]     # always excluded, not swept
OPTIONAL_EXCLUDE = ["FG3M", "PA", "RA", "PRA", "PR"]  # sweep inclusion/exclusion

# Phase 4: Direction filters per tier
DIRECTION_OPTIONS = {
    "GOBLIN":   [None, "OVER", "UNDER"],    # None = no filter
    "STANDARD": [None, "OVER", "UNDER"],
    "DEMON":    [None, "OVER", "UNDER"],
}

# ── Data ─────────────────────────────────────────────────────────────
_CV_CACHE: pd.DataFrame | None = None
_TRAIN_DATES: list[str] | None = None

def load_data() -> tuple[pd.DataFrame, list[str]]:
    global _CV_CACHE, _TRAIN_DATES
    if _CV_CACHE is not None:
        return _CV_CACHE, _TRAIN_DATES

    import pickle
    print(f"Loading cache: {CACHE_PATH}")
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)

    cv = cache["cv"]
    all_dates = sorted(cv["game_date"].unique())

    # Match to corpus manifest dates if available
    manifest = BASE / "corpus_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        corpus_dates = set(data.get("dates", []))
        train_dates = [d for d in all_dates if d.replace("-", "") in corpus_dates]
    else:
        train_dates = all_dates

    cv_train = cv[cv["game_date"].isin(train_dates)].copy()
    print(f"Loaded {len(train_dates)} dates, {len(cv_train):,} legs\n")

    _CV_CACHE = cv_train
    _TRAIN_DATES = train_dates
    return _CV_CACHE, _TRAIN_DATES


# ── Evaluation ───────────────────────────────────────────────────────
def evaluate_config(config: dict, scoring_overrides: dict | None = None) -> dict:
    """
    Build slips for every training date and return full metrics dict.
    scoring_overrides: optional dict with keys goblin_l20_w, standard_te_w, demon_l20_w
    """
    cv, dates = load_data()
    builder = MarketedSlipBuilder(config)
    builder.templates = FIXED_TEMPLATES

    # Inject scoring weight overrides into builder if provided
    if scoring_overrides:
        builder._score_overrides = scoring_overrides

    total_slips = 0
    total_wins  = 0
    by_label    = {t["label"]: {"slips": 0, "wins": 0} for t in FIXED_TEMPLATES}
    by_stat     = {}
    by_dir      = {"OVER": {"slips": 0, "wins": 0}, "UNDER": {"slips": 0, "wins": 0}}

    for date in dates:
        date_df = cv[cv["game_date"] == date].copy()
        if date_df.empty:
            continue

        # Apply scoring overrides at the DataFrame level if present
        if scoring_overrides:
            date_df = _apply_scoring_overrides(date_df, scoring_overrides)

        slips = builder.build_slips(date_df)
        if not slips:
            continue

        for slip in slips:
            label = slip["label"]
            legs  = slip["legs"]

            # Evaluate all legs against truth in date_df
            all_hit = True
            for leg in legs:
                mask = (
                    (date_df["player"].str.strip() == str(leg.get("player", "")).strip()) &
                    (date_df["stat"].str.upper()   == str(leg.get("stat", "")).upper()) &
                    (date_df["direction"].str.upper() == str(leg.get("direction", "")).upper()) &
                    (abs(date_df["line"] - float(leg.get("line", 0))) < 0.01)
                )
                if not mask.any() or not bool(date_df[mask]["hit"].iloc[0]):
                    all_hit = False

            won = int(all_hit)
            total_slips += 1
            total_wins  += won
            by_label[label]["slips"] += 1
            by_label[label]["wins"]  += won

            # Per-stat and per-direction breakdown (keyed on first GOBLIN leg stat)
            for leg in legs:
                stat = str(leg.get("stat", "UNK")).upper()
                direction = str(leg.get("direction", "UNK")).upper()
                if stat not in by_stat:
                    by_stat[stat] = {"slips": 0, "wins": 0}
                by_stat[stat]["slips"] += 1
                by_stat[stat]["wins"]  += won
                if direction in by_dir:
                    by_dir[direction]["slips"] += 1
                    by_dir[direction]["wins"]  += won

    win_rate = total_wins / max(total_slips, 1)
    label_rates = {
        lbl: d["wins"] / max(d["slips"], 1)
        for lbl, d in by_label.items()
    }

    return {
        "win_rate": win_rate,
        "total_wins": total_wins,
        "total_slips": total_slips,
        "by_label": label_rates,
        "by_stat": {s: v["wins"] / max(v["slips"], 1) for s, v in by_stat.items() if v["slips"] >= 5},
        "by_dir": {d: v["wins"] / max(v["slips"], 1) for d, v in by_dir.items() if v["slips"] >= 5},
    }


def _apply_scoring_overrides(df: pd.DataFrame, overrides: dict) -> pd.DataFrame:
    """Recompute marketed_score using override weights before builder sees it."""
    df = df.copy()
    goblin_w   = overrides.get("goblin_l20_w",   0.5)
    standard_w = overrides.get("standard_te_w",  1.0)
    demon_w    = overrides.get("demon_l20_w",    0.5)

    p_cal  = pd.to_numeric(df.get("p_cal",        pd.Series(0.5, index=df.index)), errors="coerce").fillna(0.5)
    l20    = pd.to_numeric(df.get("l20_edge",      pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).clip(0, 1)
    dir_te = pd.to_numeric(df.get("player_dir_te", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0)

    # Weighted blend: score = signal_a^w * signal_b^(1-w)  (geometric interpolation)
    goblin_score   = (p_cal ** (1 - goblin_w))   * (l20.clip(1e-6) ** goblin_w)
    standard_score = (dir_te ** standard_w)       * (p_cal ** (1 - standard_w))
    demon_score    = (p_cal ** (1 - demon_w))     * (l20.clip(1e-6) ** demon_w)

    tier_arr = df["tier"].values
    df["marketed_score"] = np.where(
        tier_arr == "STANDARD", standard_score.values,
        np.where(tier_arr == "DEMON", demon_score.values, goblin_score.values)
    )
    return df


def fmt(r: dict) -> str:
    lbl = r["by_label"]
    return (
        f"{r['win_rate']:.1%} ({r['total_wins']}/{r['total_slips']})  "
        f"3L={lbl.get('3-leg', 0):.1%}  "
        f"4L={lbl.get('4-leg', 0):.1%}  "
        f"5L={lbl.get('5-leg', 0):.1%}"
    )


def print_breakdown(r: dict, label: str = ""):
    if label:
        print(f"\n  {label}")
    if r["by_stat"]:
        print("  By stat (leg win rate):")
        for s, v in sorted(r["by_stat"].items(), key=lambda x: -x[1]):
            print(f"    {s:<6} {v:.1%}")
    if r["by_dir"]:
        print("  By direction:")
        for d, v in sorted(r["by_dir"].items(), key=lambda x: -x[1]):
            print(f"    {d:<6} {v:.1%}")


def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ── Main ─────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    load_data()  # pre-warm

    # ── Baseline ─────────────────────────────────────────────────────
    section("BASELINE")
    baseline_result = evaluate_config(copy.deepcopy(BASE_CONFIG))
    print(f"  Baseline: {fmt(baseline_result)}")
    print_breakdown(baseline_result)
    best_config = copy.deepcopy(BASE_CONFIG)
    best_result = baseline_result

    # ── Phase 1: Threshold sweep ──────────────────────────────────────
    section("PHASE 1 — THRESHOLD SWEEP")
    goblin_vals   = THRESHOLD_GRID["GOBLIN"]
    standard_vals = THRESHOLD_GRID["STANDARD"]
    demon_vals    = THRESHOLD_GRID["DEMON"]
    combos = list(itertools.product(goblin_vals, standard_vals, demon_vals))
    print(f"  Testing {len(combos)} combinations...")

    phase1_results = []
    for i, (g, s, d) in enumerate(combos, 1):
        cfg = copy.deepcopy(best_config)
        cfg["marketed_slips"]["min_thresholds"] = {"GOBLIN": g, "STANDARD": s, "DEMON": d}
        r = evaluate_config(cfg)
        phase1_results.append((r["win_rate"], g, s, d, r))
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(combos)}")

    phase1_results.sort(key=lambda x: -x[0])
    best_g, best_s, best_d, best_phase1 = phase1_results[0][1], phase1_results[0][2], phase1_results[0][3], phase1_results[0][4]

    print(f"\n  Top 10 threshold configs:")
    for wr, g, s, d, r in phase1_results[:10]:
        print(f"    G={g:.2f} S={s:.2f} D={d:.2f}  ->  {fmt(r)}")

    if best_phase1["win_rate"] > best_result["win_rate"]:
        best_config["marketed_slips"]["min_thresholds"] = {"GOBLIN": best_g, "STANDARD": best_s, "DEMON": best_d}
        best_result = best_phase1
        print(f"\n  ++ Phase 1 improved to {best_result['win_rate']:.1%} (G={best_g} S={best_s} D={best_d})")
    else:
        print(f"\n  Phase 1: no improvement over baseline")

    print_breakdown(best_phase1, f"Best threshold breakdown (G={best_g} S={best_s} D={best_d})")

    # ── Phase 2: Scoring weight sweep ─────────────────────────────────
    section("PHASE 2 — SCORING WEIGHT SWEEP")
    combos2 = list(itertools.product(GOBLIN_L20_WEIGHTS, STANDARD_TE_WEIGHTS, DEMON_L20_WEIGHTS))
    print(f"  Testing {len(combos2)} weight combinations...")

    phase2_results = []
    for i, (gw, sw, dw) in enumerate(combos2, 1):
        overrides = {"goblin_l20_w": gw, "standard_te_w": sw, "demon_l20_w": dw}
        r = evaluate_config(copy.deepcopy(best_config), scoring_overrides=overrides)
        phase2_results.append((r["win_rate"], gw, sw, dw, r))
        if i % 20 == 0:
            print(f"  Progress: {i}/{len(combos2)}")

    phase2_results.sort(key=lambda x: -x[0])
    best_gw, best_sw, best_dw, best_phase2 = phase2_results[0][1], phase2_results[0][2], phase2_results[0][3], phase2_results[0][4]

    print(f"\n  Top 10 scoring weight configs:")
    for wr, gw, sw, dw, r in phase2_results[:10]:
        print(f"    goblin_l20={gw:.2f} std_te={sw:.2f} demon_l20={dw:.2f}  ->  {fmt(r)}")

    best_score_overrides = None
    if best_phase2["win_rate"] > best_result["win_rate"]:
        best_score_overrides = {"goblin_l20_w": best_gw, "standard_te_w": best_sw, "demon_l20_w": best_dw}
        best_result = best_phase2
        print(f"\n  ++ Phase 2 improved to {best_result['win_rate']:.1%}")
    else:
        print(f"\n  Phase 2: no improvement (current scoring weights are optimal)")

    print_breakdown(best_phase2, f"Best weight breakdown (goblin_l20={best_gw} std_te={best_sw} demon_l20={best_dw})")

    # ── Phase 3: Stat exclusion sweep ─────────────────────────────────
    section("PHASE 3 — STAT EXCLUSION SWEEP")
    # Test each optional stat: include vs exclude
    exclusion_combos = list(itertools.product([True, False], repeat=len(OPTIONAL_EXCLUDE)))
    print(f"  Testing {len(exclusion_combos)} stat exclusion combinations...")
    print(f"  Always excluded: {ALWAYS_EXCLUDE}")
    print(f"  Optional: {OPTIONAL_EXCLUDE}")

    phase3_results = []
    for i, flags in enumerate(exclusion_combos, 1):
        excluded = list(ALWAYS_EXCLUDE) + [s for s, excl in zip(OPTIONAL_EXCLUDE, flags) if excl]
        cfg = copy.deepcopy(best_config)
        cfg["marketed_slips"]["excluded_stats"] = excluded
        r = evaluate_config(cfg, scoring_overrides=best_score_overrides)
        phase3_results.append((r["win_rate"], excluded, r))

    phase3_results.sort(key=lambda x: -x[0])
    best_excl, best_phase3 = phase3_results[0][1], phase3_results[0][2]

    print(f"\n  Top 10 exclusion configs:")
    for wr, excl, r in phase3_results[:10]:
        extra = [s for s in excl if s not in ALWAYS_EXCLUDE]
        print(f"    also_excl={extra}  ->  {fmt(r)}")

    if best_phase3["win_rate"] > best_result["win_rate"]:
        best_config["marketed_slips"]["excluded_stats"] = best_excl
        best_result = best_phase3
        extra = [s for s in best_excl if s not in ALWAYS_EXCLUDE]
        print(f"\n  ++ Phase 3 improved to {best_result['win_rate']:.1%} (also excl: {extra})")
    else:
        print(f"\n  Phase 3: no improvement (current stat exclusions are optimal)")

    print_breakdown(best_phase3, f"Best exclusion breakdown")

    # ── Phase 4: Direction filter sweep ───────────────────────────────
    section("PHASE 4 — DIRECTION FILTER SWEEP")
    dir_combos = list(itertools.product(
        DIRECTION_OPTIONS["GOBLIN"],
        DIRECTION_OPTIONS["STANDARD"],
        DIRECTION_OPTIONS["DEMON"],
    ))
    print(f"  Testing {len(dir_combos)} direction filter combinations...")

    phase4_results = []
    for i, (gd, sd, dd) in enumerate(dir_combos, 1):
        dir_filters = {}
        if gd:  dir_filters["GOBLIN"]   = [gd]
        if sd:  dir_filters["STANDARD"] = [sd]
        if dd:  dir_filters["DEMON"]    = [dd]
        cfg = copy.deepcopy(best_config)
        cfg["marketed_slips"]["direction_filters"] = dir_filters
        r = evaluate_config(cfg, scoring_overrides=best_score_overrides)
        phase4_results.append((r["win_rate"], gd, sd, dd, dir_filters, r))

    phase4_results.sort(key=lambda x: -x[0])
    best_gd, best_sd, best_dd, best_dir_filters, best_phase4 = (
        phase4_results[0][1], phase4_results[0][2], phase4_results[0][3],
        phase4_results[0][4], phase4_results[0][5]
    )

    print(f"\n  Top 10 direction filter configs:")
    for wr, gd, sd, dd, df_, r in phase4_results[:10]:
        print(f"    G={gd or 'both':<5} S={sd or 'both':<5} D={dd or 'both':<5}  ->  {fmt(r)}")

    if best_phase4["win_rate"] > best_result["win_rate"]:
        best_config["marketed_slips"]["direction_filters"] = best_dir_filters
        best_result = best_phase4
        print(f"\n  ++ Phase 4 improved to {best_result['win_rate']:.1%}")
    else:
        print(f"\n  Phase 4: no improvement (no direction filter helps)")

    print_breakdown(best_phase4, f"Best direction filter breakdown (G={best_gd} S={best_sd} D={best_dd})")

    # ── Phase 5: Combined final validation ────────────────────────────
    section("PHASE 5 — COMBINED FINAL VALIDATION")
    final_result = evaluate_config(best_config, scoring_overrides=best_score_overrides)
    print(f"  Final combined: {fmt(final_result)}")
    print_breakdown(final_result, "Full breakdown")

    # ── Phase 6: hit_prob filter sweep ────────────────────────────────
    section("PHASE 6 — MIN SLIP HIT_PROB FILTER")
    print(f"  Drop slips whose correlation-adjusted joint probability < threshold.")
    print(f"  Applied on top of Phase 5 optimal config.")
    print(f"  Baseline to beat: {final_result['win_rate']:.1%} ({final_result['total_wins']}/{final_result['total_slips']})\n")

    cv_p6, dates_p6 = load_data()

    def evaluate_with_hitprob(min_hit_prob: float) -> dict:
        builder = MarketedSlipBuilder(best_config)
        builder.templates = FIXED_TEMPLATES
        total_slips = 0
        total_wins = 0
        by_label = {t["label"]: {"slips": 0, "wins": 0} for t in FIXED_TEMPLATES}
        for date in dates_p6:
            date_df = cv_p6[cv_p6["game_date"] == date].copy()
            if date_df.empty:
                continue
            if best_score_overrides:
                date_df = _apply_scoring_overrides(date_df, best_score_overrides)
            slips = builder.build_slips(date_df)
            for slip in slips:
                if min_hit_prob > 0.0 and slip.get("hit_prob", 0.0) < min_hit_prob:
                    continue
                legs = slip["legs"]
                all_hit = True
                for leg in legs:
                    mask = (
                        (date_df["player"].str.strip() == str(leg.get("player", "")).strip()) &
                        (date_df["stat"].str.upper()   == str(leg.get("stat", "")).upper()) &
                        (date_df["direction"].str.upper() == str(leg.get("direction", "")).upper()) &
                        (abs(date_df["line"] - float(leg.get("line", 0))) < 0.01)
                    )
                    if not mask.any() or not bool(date_df[mask]["hit"].iloc[0]):
                        all_hit = False
                total_slips += 1
                total_wins += int(all_hit)
                by_label[slip["label"]]["slips"] += 1
                by_label[slip["label"]]["wins"] += int(all_hit)
        wr = total_wins / max(total_slips, 1)
        return {
            "win_rate": wr, "total_wins": total_wins, "total_slips": total_slips,
            "by_label": {l: d["wins"] / max(d["slips"], 1) for l, d in by_label.items()},
            "by_stat": {}, "by_dir": {},
        }

    phase6_results = []
    for mhp in [0.0, 0.04, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.15]:
        r6 = evaluate_with_hitprob(mhp)
        phase6_results.append((mhp, r6))
        beat = "  <-- BEATS" if r6["win_rate"] > final_result["win_rate"] else ""
        print(f"  mhp={mhp:.2f}  {fmt(r6)}{beat}")

    meaningful_p6 = [(mhp, r) for mhp, r in phase6_results if r["total_slips"] >= 30]
    best_p6 = max(meaningful_p6, key=lambda x: x[1]["win_rate"]) if meaningful_p6 else None
    if best_p6 and best_p6[1]["win_rate"] > final_result["win_rate"]:
        print(f"\n  ++ Phase 6 best (>=30 slips): mhp={best_p6[0]}  {fmt(best_p6[1])}")
        print(f"     Improvement: {final_result['win_rate']:.1%} -> {best_p6[1]['win_rate']:.1%} "
              f"({(best_p6[1]['win_rate'] - final_result['win_rate'])*100:+.1f}pp)")
    else:
        print(f"\n  Phase 6: no improvement over {final_result['win_rate']:.1%} baseline (at >=30 slips)")

    # ── Summary ───────────────────────────────────────────────────────
    elapsed = time.time() - t0
    section("OPTIMIZATION SUMMARY")
    print(f"  Baseline:    {fmt(baseline_result)}")
    print(f"  Phase 1 best:{fmt(best_phase1)}")
    print(f"  Phase 2 best:{fmt(best_phase2)}")
    print(f"  Phase 3 best:{fmt(best_phase3)}")
    print(f"  Phase 4 best:{fmt(best_phase4)}")
    print(f"  FINAL:       {fmt(final_result)}")
    if best_p6 and best_p6[1]["win_rate"] > final_result["win_rate"]:
        print(f"  PHASE 6 (mhp={best_p6[0]}): {fmt(best_p6[1])}")
    print(f"\n  Improvement: {baseline_result['win_rate']:.1%} -> {final_result['win_rate']:.1%} "
          f"({(final_result['win_rate'] - baseline_result['win_rate'])*100:+.1f}pp)")
    print(f"\n  RECOMMENDED CONFIG:")
    ms = best_config["marketed_slips"]
    print(f"    min_thresholds: {ms['min_thresholds']}")
    print(f"    excluded_stats:  {ms['excluded_stats']}")
    print(f"    direction_filters: {ms['direction_filters']}")
    if best_score_overrides:
        print(f"    scoring_weights: {best_score_overrides}")
    print(f"\n  Completed in {elapsed:.1f}s")

    # ── Save artifact ─────────────────────────────────────────────────
    from datetime import datetime

    def _sum(r: dict) -> dict:
        return {
            "win_rate": round(r["win_rate"], 4),
            "wins": r.get("total_wins", r.get("wins", 0)),
            "total": r.get("total_slips", r.get("total", 0)),
            "by_label": {k: round(v, 4) for k, v in r.get("by_label", {}).items()},
        }

    artifact = {
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(elapsed, 1),
        "cache_path": str(CACHE_PATH),
        "n_legs": int(len(df)),
        "summary": {
            "baseline":    _sum(baseline_result),
            "phase1_best": _sum(best_phase1),
            "phase2_best": _sum(best_phase2),
            "phase3_best": _sum(best_phase3),
            "phase4_best": _sum(best_phase4),
            "final":       _sum(final_result),
        },
        "improvement_pp": round((final_result["win_rate"] - baseline_result["win_rate"]) * 100, 2),
        "by_stat":      {k: round(v, 4) for k, v in final_result.get("by_stat", {}).items()},
        "by_direction": {k: round(v, 4) for k, v in final_result.get("by_dir", {}).items()},
        "recommended_config": {
            "min_thresholds":   best_config["marketed_slips"]["min_thresholds"],
            "excluded_stats":   best_config["marketed_slips"]["excluded_stats"],
            "direction_filters": best_config["marketed_slips"]["direction_filters"],
            "scoring_weights":  best_score_overrides or {},
        },
    }
    artifact_dir = Path(__file__).resolve().parents[1] / "data" / "model"
    artifact_path = artifact_dir / "marketed_slip_trainer_result.json"
    with open(artifact_path, "w") as f:
        json.dump(artifact, f, indent=2)
    print(f"\n  Artifact saved: {artifact_path}")


if __name__ == "__main__":
    main()


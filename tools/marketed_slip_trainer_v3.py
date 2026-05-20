#!/usr/bin/env python
"""
Marketed Slip Trainer v3
========================
Extends v2 with three novel optimization dimensions not covered by v2:

  Phase 5 — Min weak-link leg score
    After building each slip, compute min(marketed_score) across all legs.
    Filter out slips where the weakest leg falls below the threshold.
    Rationale: one bad leg tanks the whole slip; raise the floor.

  Phase 6 — Min slip hit_prob
    Filter out built slips where joint hit_prob < threshold.
    Tests whether model-calibrated joint probability predicts actual wins.

  Phase 7 — Per-stat threshold boosts for low-hit stats
    AST/REB/PTS/PA show 27-32% leg win rate vs PRA/RA/FG3M at 46-52%.
    Test whether requiring higher p_cal_marketed for these specific stats
    lifts overall slip win rate.

  Phase 8 — Combined best of Phases 5-7

Starts from confirmed optimal: G=0.57 S=0.30 D=0.28, no stat exclusions beyond
BLK/STL/TO, no direction filters.
"""
from __future__ import annotations

import copy
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# ── Paths ────────────────────────────────────────────────────────────
CACHE_PATH = Path(r"C:\Users\13142\Atlas\NBA\data\model\_v18_resim_cache.pkl")
BASE = Path(r"C:\Users\13142\Atlas\NBA\data\telemetry\v18_corpus")

# ── Fixed templates — DO NOT SWEEP ───────────────────────────────────
FIXED_TEMPLATES = [
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
]

# ── Confirmed optimal base config — read from config.yaml ────────────
def _load_best_config() -> dict:
    import yaml
    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        full_cfg = yaml.safe_load(f)
    ms = full_cfg.get("marketed_slips", {})
    return {
        "marketed_slips": {
            "enabled": True,
            "calibration_path": ms.get("calibration_path", "data/model/marketed_calibration.json"),
            "excluded_stats": ms.get("excluded_stats", ["BLK", "STL", "TO"]),
            "min_thresholds": {
                k: float(v)
                for k, v in ms.get(
                    "min_thresholds", {"GOBLIN": 0.57, "STANDARD": 0.30, "DEMON": 0.28}
                ).items()
            },
            "direction_filters": ms.get("direction_filters", {}),
            "correlation": ms.get(
                "correlation",
                {"same_team_penalty": 0.03, "hedge_bonus": 0.015, "blowout_penalty": 0.02},
            ),
        }
    }


BEST_CONFIG = _load_best_config()

# ── Phase 5: Min weak-link leg score ─────────────────────────────────
# marketed_score for GOBLIN/DEMON = p_cal * l20_edge  (typical range 0.10-0.60)
# marketed_score for STANDARD = player_dir_te           (typical range 0.40-0.75)
MIN_LEG_SCORE_VALUES = [0.0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]

# ── Phase 6: Min slip joint hit_prob ─────────────────────────────────
# hit_prob = product of p_cal_marketed with correlation adjustments
MIN_HIT_PROB_VALUES = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20]

# ── Phase 7: Per-stat threshold boosts ───────────────────────────────
# WEAK_STATS is recomputed dynamically in main() from corpus hit rates.
# Default fallback shown here; actual values depend on the loaded corpus.
# Boost = added to base tier threshold for low-hit-rate stats.
# e.g., GOBLIN boost 0.10 means AST GOBLIN legs need p_cal_marketed >= 0.67
WEAK_STATS: list[str] = ["AST", "REB", "PTS", "PA"]  # fallback only
STAT_BOOST_VALUES = [0.0, 0.05, 0.08, 0.10, 0.12, 0.15]  # per-stat boost options


def compute_weak_stats(cv: pd.DataFrame, min_samples: int = 200) -> list[str]:
    """Return stats with below-median leg hit rate in the corpus."""
    if "hit" not in cv.columns or "stat" not in cv.columns:
        return list(WEAK_STATS)
    agg = cv.groupby("stat")["hit"].agg(["mean", "count"])
    agg = agg[agg["count"] >= min_samples]
    if agg.empty:
        return list(WEAK_STATS)
    median_rate = float(agg["mean"].median())
    return sorted(agg[agg["mean"] < median_rate].index.tolist())


def _phase7_worker(args: tuple) -> tuple:
    """Pool worker for Phase 7 per-stat boost sweep. Evaluates one (stat, boost) pair."""
    config_dict, stat, boost = args
    r = evaluate_config(config_dict, stat_boosts={stat: boost})
    return stat, boost, r


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

    manifest = BASE / "corpus_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        corpus_dates = set(data.get("dates", []))
        train_dates = [d for d in all_dates if d.replace("-", "") in corpus_dates]
    else:
        train_dates = all_dates

    cv_train = cv[cv["game_date"].isin(train_dates)].copy()
    # Preflight check
    assert len(cv_train) > 1000, f"Preflight FAIL: only {len(cv_train)} legs loaded"
    for _col in ("game_date", "stat", "hit", "p_cal", "tier", "direction"):
        assert _col in cv_train.columns, f"Preflight FAIL: missing column '{_col}'"
    print(f"Loaded {len(train_dates)} dates, {len(cv_train):,} legs\n")

    _CV_CACHE = cv_train
    _TRAIN_DATES = train_dates
    return _CV_CACHE, _TRAIN_DATES


# ── Evaluation ───────────────────────────────────────────────────────
def evaluate_config(
    config: dict,
    min_leg_score: float = 0.0,
    min_hit_prob: float = 0.0,
    stat_boosts: dict[str, float] | None = None,
) -> dict:
    """
    Build slips for every training date and return full metrics dict.

    min_leg_score : filter out slips where min(marketed_score per leg) < this value
    min_hit_prob  : filter out slips where hit_prob < this value
    stat_boosts   : dict mapping stat -> added threshold for that stat
                    e.g., {"AST": 0.10} means AST legs need p_cal_marketed
                    >= base_tier_threshold + 0.10
    """
    cv, dates = load_data()

    # Apply stat boosts by pre-patching the config's pool to remove low-quality stat legs
    effective_config = copy.deepcopy(config)

    builder = MarketedSlipBuilder(effective_config)
    builder.templates = FIXED_TEMPLATES

    total_slips = 0
    total_wins = 0
    by_label = {t["label"]: {"slips": 0, "wins": 0} for t in FIXED_TEMPLATES}
    by_stat: dict[str, dict] = {}
    by_dir = {"OVER": {"slips": 0, "wins": 0}, "UNDER": {"slips": 0, "wins": 0}}

    base_thresholds = effective_config["marketed_slips"]["min_thresholds"]
    # Pre-instantiate calibration builder once (not per-date)
    builder2 = MarketedSlipBuilder(effective_config) if stat_boosts else None

    for date in dates:
        date_df = cv[cv["game_date"] == date].copy()
        if date_df.empty:
            continue

        # Apply per-stat threshold boosts by masking out legs that don't clear
        # the boosted threshold for their stat
        if stat_boosts:
            keep_mask = pd.Series(True, index=date_df.index)
            tmp_df = builder2._apply_stat_calibration(date_df.copy())
            for stat, boost in stat_boosts.items():
                if boost <= 0:
                    continue
                stat_rows = tmp_df["stat"].str.upper() == stat.upper()
                for tier, base_thresh in base_thresholds.items():
                    tier_rows = tmp_df["tier"] == tier
                    boosted_thresh = base_thresh + boost
                    # Remove legs that pass base threshold but fail boosted threshold
                    fail_boost = stat_rows & tier_rows & (tmp_df["p_cal_marketed"] < boosted_thresh)
                    keep_mask &= ~fail_boost
            date_df = date_df[keep_mask].copy()

        if date_df.empty:
            continue

        slips = builder.build_slips(date_df)
        if not slips:
            continue

        for slip in slips:
            # Phase 5 filter: min weak-link leg score
            if min_leg_score > 0.0:
                leg_scores = [float(leg.get("marketed_score", 0.0)) for leg in slip["legs"]]
                if not leg_scores or min(leg_scores) < min_leg_score:
                    continue

            # Phase 6 filter: min slip hit_prob
            if min_hit_prob > 0.0:
                if slip.get("hit_prob", 0.0) < min_hit_prob:
                    continue

            label = slip["label"]
            legs = slip["legs"]

            # Evaluate all legs against truth (use pre-filtered date_df, not full cv)
            all_hit = True
            for leg in legs:
                mask = (
                    (date_df["player"].str.strip() == str(leg.get("player", "")).strip()) &
                    (date_df["stat"].str.upper() == str(leg.get("stat", "")).upper()) &
                    (date_df["direction"].str.upper() == str(leg.get("direction", "")).upper()) &
                    (abs(date_df["line"] - float(leg.get("line", 0))) < 0.01)
                )
                if not mask.any() or not bool(date_df[mask]["hit"].iloc[0]):
                    all_hit = False
                    break

            won = int(all_hit)
            total_slips += 1
            total_wins += won
            by_label[label]["slips"] += 1
            by_label[label]["wins"] += won

            for leg in legs:
                stat = str(leg.get("stat", "UNK")).upper()
                direction = str(leg.get("direction", "UNK")).upper()
                if stat not in by_stat:
                    by_stat[stat] = {"slips": 0, "wins": 0}
                by_stat[stat]["slips"] += 1
                by_stat[stat]["wins"] += won
                if direction in by_dir:
                    by_dir[direction]["slips"] += 1
                    by_dir[direction]["wins"] += won

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


def main():
    t0 = time.time()
    cv_loaded, _ = load_data()
    weak_stats = compute_weak_stats(cv_loaded)
    print(f"  Weak stats (below-median leg hit rate): {weak_stats}\n")

    TARGET_WIN_RATE = 0.395  # v2 confirmed optimal

    # ── Baseline (should reproduce v2 final: 39.5%) ──────────────────
    section("BASELINE (v2 optimal config)")
    baseline = evaluate_config(copy.deepcopy(BEST_CONFIG))
    print(f"  Baseline: {fmt(baseline)}")
    print_breakdown(baseline)

    best_result = baseline
    best_min_leg_score = 0.0
    best_min_hit_prob = 0.0
    best_stat_boosts: dict[str, float] = {}

    # ── Phase 5: Min weak-link leg score ─────────────────────────────
    section("PHASE 5 — MIN WEAK-LINK LEG SCORE SWEEP")
    print(f"  Tests: filter slips where weakest leg marketed_score < threshold")
    print(f"  Values: {MIN_LEG_SCORE_VALUES}\n")

    phase5_results = []
    for mls in MIN_LEG_SCORE_VALUES:
        r = evaluate_config(copy.deepcopy(BEST_CONFIG), min_leg_score=mls)
        phase5_results.append((r["win_rate"], mls, r))
        sign = "🔥" if r["win_rate"] > best_result["win_rate"] else "  "
        print(f"  {sign} min_leg_score={mls:.2f}  ->  {fmt(r)}")

    phase5_results.sort(key=lambda x: -x[0])
    best_p5_rate, best_p5_mls, best_p5 = phase5_results[0]

    if best_p5_rate > best_result["win_rate"]:
        best_result = best_p5
        best_min_leg_score = best_p5_mls
        print(f"\n  ++ Phase 5 improved to {best_result['win_rate']:.1%} (min_leg_score={best_p5_mls})")
    else:
        print(f"\n  Phase 5: no improvement (min_leg_score={best_p5_mls} was best at {best_p5_rate:.1%})")

    print_breakdown(best_p5, f"Best Phase 5 breakdown (min_leg_score={best_p5_mls})")

    # ── Phase 6: Min slip hit_prob ────────────────────────────────────
    section("PHASE 6 — MIN SLIP HIT_PROB SWEEP")
    print(f"  Tests: filter slips where joint hit_prob < threshold")
    print(f"  Values: {MIN_HIT_PROB_VALUES}\n")

    phase6_results = []
    for mhp in MIN_HIT_PROB_VALUES:
        r = evaluate_config(copy.deepcopy(BEST_CONFIG), min_hit_prob=mhp)
        phase6_results.append((r["win_rate"], mhp, r))
        sign = "🔥" if r["win_rate"] > best_result["win_rate"] else "  "
        print(f"  {sign} min_hit_prob={mhp:.2f}  ->  {fmt(r)}")

    phase6_results.sort(key=lambda x: -x[0])
    best_p6_rate, best_p6_mhp, best_p6 = phase6_results[0]

    if best_p6_rate > best_result["win_rate"]:
        best_result = best_p6
        best_min_hit_prob = best_p6_mhp
        print(f"\n  ++ Phase 6 improved to {best_result['win_rate']:.1%} (min_hit_prob={best_p6_mhp})")
    else:
        print(f"\n  Phase 6: no improvement (min_hit_prob={best_p6_mhp} was best at {best_p6_rate:.1%})")

    print_breakdown(best_p6, f"Best Phase 6 breakdown (min_hit_prob={best_p6_mhp})")

    # ── Phase 7: Per-stat threshold boosts ───────────────────────────
    section("PHASE 7 — PER-STAT THRESHOLD BOOST SWEEP")
    print(f"  Weak stats: {weak_stats}")
    print(f"  Tests boost added to base tier threshold for each weak stat individually,")
    print(f"  then combined best-of.")
    print(f"  Boost values: {STAT_BOOST_VALUES}\n")

    # 7a: Individual stat boosts — parallel pool
    tasks_7a = [
        (copy.deepcopy(BEST_CONFIG), stat, boost)
        for stat in weak_stats
        for boost in STAT_BOOST_VALUES
    ]
    n_p7_workers = min(4, max(1, mp.cpu_count() - 1), len(tasks_7a))
    print(f"  Running {len(tasks_7a)} tasks with {n_p7_workers} workers...")
    with mp.Pool(n_p7_workers) as pool:
        p7a_raw = pool.map(_phase7_worker, tasks_7a)

    from collections import defaultdict
    p7a_by_stat: dict[str, list] = defaultdict(list)
    for _stat, _boost, _r in p7a_raw:
        p7a_by_stat[_stat].append((_r["win_rate"], _boost, _r))

    best_individual_boosts: dict[str, float] = {}
    for stat in weak_stats:
        stat_results = sorted(p7a_by_stat[stat], key=lambda x: -x[0])
        print(f"  -- {stat} boost sweep --")
        for wr, boost, r in stat_results:
            sign = "🔥" if wr > best_result["win_rate"] else "  "
            print(f"    {sign} {stat} boost={boost:.2f}  ->  {fmt(r)}")
        best_individual_boosts[stat] = stat_results[0][1]
        print(f"    Best for {stat}: boost={stat_results[0][1]:.2f} at {stat_results[0][0]:.1%}")

    # 7b: Combined best boosts (apply all at once)
    print(f"\n  -- Combined best per-stat boosts --")
    combined_boosts = {s: b for s, b in best_individual_boosts.items() if b > 0}
    if combined_boosts:
        r_combined = evaluate_config(copy.deepcopy(BEST_CONFIG), stat_boosts=combined_boosts)
        sign = "🔥" if r_combined["win_rate"] > best_result["win_rate"] else "  "
        print(f"  {sign} Combined {combined_boosts}  ->  {fmt(r_combined)}")
        if r_combined["win_rate"] > best_result["win_rate"]:
            best_result = r_combined
            best_stat_boosts = combined_boosts
            print(f"\n  ++ Phase 7 (combined) improved to {best_result['win_rate']:.1%}")
        else:
            # Reuse 7a results — no re-evaluation needed
            for stat in weak_stats:
                single_results = sorted(p7a_by_stat[stat], key=lambda x: -x[0])
                if single_results[0][0] > best_result["win_rate"]:
                    best_result = single_results[0][2]
                    best_stat_boosts = {stat: single_results[0][1]}
                    print(f"\n  ++ Phase 7 ({stat} only) improved to {best_result['win_rate']:.1%}")
    else:
        print(f"  No per-stat boosts showed individual improvement.")

    print_breakdown(best_result, "Best after Phase 7")

    # ── Phase 8: Combined best of Phases 5-7 ─────────────────────────
    section("PHASE 8 — COMBINED BEST (Phases 5+6+7)")
    print(f"  Best from each phase:")
    print(f"    min_leg_score = {best_min_leg_score}")
    print(f"    min_hit_prob  = {best_min_hit_prob}")
    print(f"    stat_boosts   = {best_stat_boosts}")

    # Sweep combinations of the top individual values
    top_mls = sorted({0.0, best_min_leg_score, phase5_results[0][1], phase5_results[1][1] if len(phase5_results) > 1 else 0.0})[:4]
    top_mhp = sorted({0.0, best_min_hit_prob, phase6_results[0][1], phase6_results[1][1] if len(phase6_results) > 1 else 0.0})[:4]

    import itertools
    phase8_results = []
    combos = list(itertools.product(top_mls, top_mhp))
    print(f"\n  Testing {len(combos)} combined combinations...")

    for mls, mhp in combos:
        r = evaluate_config(
            copy.deepcopy(BEST_CONFIG),
            min_leg_score=mls,
            min_hit_prob=mhp,
            stat_boosts=best_stat_boosts if best_stat_boosts else None,
        )
        phase8_results.append((r["win_rate"], mls, mhp, r))

    phase8_results.sort(key=lambda x: -x[0])
    print(f"\n  Top 5 combined configs:")
    for wr, mls, mhp, r in phase8_results[:5]:
        sign = "🔥" if wr > TARGET_WIN_RATE else "  "
        print(f"  {sign} min_leg={mls:.2f} min_hp={mhp:.2f}  ->  {fmt(r)}")

    final_rate, final_mls, final_mhp, final_result = phase8_results[0]
    if final_rate > best_result["win_rate"]:
        best_result = final_result
        best_min_leg_score = final_mls
        best_min_hit_prob = final_mhp
        print(f"\n  ++ Phase 8 combined improved to {best_result['win_rate']:.1%}")

    # ── Summary ───────────────────────────────────────────────────────
    section("OPTIMIZATION SUMMARY")
    print(f"  Baseline (v2 optimal):  {fmt(baseline)}")
    print(f"  Best found (v3):        {fmt(best_result)}")
    improvement = best_result["win_rate"] - baseline["win_rate"]
    print(f"  Improvement: {baseline['win_rate']:.1%} -> {best_result['win_rate']:.1%} ({improvement:+.1%})")
    print()
    print(f"  RECOMMENDED ADDITIONS TO CONFIG:")
    print(f"    min_slip_leg_score:  {best_min_leg_score}")
    print(f"    min_slip_hit_prob:   {best_min_hit_prob}")
    if best_stat_boosts:
        print(f"    per_stat_threshold_boosts:")
        for s, b in best_stat_boosts.items():
            base_thresholds = BEST_CONFIG["marketed_slips"]["min_thresholds"]
            print(f"      {s}: +{b:.2f} (effective thresholds: "
                  f"GOBLIN={base_thresholds['GOBLIN']+b:.2f} "
                  f"STANDARD={base_thresholds['STANDARD']+b:.2f} "
                  f"DEMON={base_thresholds['DEMON']+b:.2f})")
    else:
        print(f"    per_stat_threshold_boosts: none")

    if best_result["win_rate"] > TARGET_WIN_RATE:
        print(f"\n  🎯 SUCCESS! Beat {TARGET_WIN_RATE:.1%} baseline")
    else:
        print(f"\n  ⚠ Did not beat {TARGET_WIN_RATE:.1%} baseline — current config remains optimal")

    print_breakdown(best_result, "Final breakdown")
    print(f"\n  Completed in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()


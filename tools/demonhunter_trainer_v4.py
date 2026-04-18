#!/usr/bin/env python
"""
DemonHunter Slip Trainer v4
============================
All-DEMON slip trainer (HIT mode only).

v4 changes from v3 (fixing efficiency):
  - 2 seeds instead of 5 (DEMON pool is large, seeds produce near-identical results)
  - Minimum 4 dates before early-exit pruning kicks in (prevents 87/90 skip rate)
  - 2 stages: S1 structural+filters → S2 beam/pool exploration
  - No S3 fine-tuning (±25 beam is noise for DEMON)
  - TOP_K 3 (not 5) — faster per-config
  - Focused S2: per_tier is the key lever, not beam width
  - Grid sizes: S1 ~200 combos, S2 ~80 combos → ~280 total per category
  - Expected runtime: ~2-4 hours total (was 4 days in v3)

Output: demonhunter_trainer_results_v4.yaml
"""
from __future__ import annotations

import copy
import itertools
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.fingerprint import build_manifest, config_fingerprint
from Atlas.core.slip_builders import build_slips_by_tier_buckets

# ── data paths ──────────────────────────────────────────────────────
BASE = Path(r"C:\Users\rick\projects\Atlas\data\telemetry\v17_corpus")

def _load_run_dates() -> list[str]:
    """Load dates from corpus_manifest.json if available, else hardcoded fallback."""
    manifest = BASE / "corpus_manifest.json"
    if manifest.exists():
        import json
        data = json.loads(manifest.read_text(encoding="utf-8"))
        dates = data.get("dates", [])
        if dates:
            print(f"Loaded {len(dates)} dates from {manifest.name}")
            return dates
    # Fallback: scan directory for date folders
    if BASE.exists():
        found = sorted(d.name for d in BASE.iterdir()
                       if d.is_dir() and d.name.isdigit() and len(d.name) == 8)
        if found:
            print(f"Discovered {len(found)} date dirs in {BASE.name}")
            return found
    return []

RUN_DATES = _load_run_dates()

CATEGORIES = [
    ("3-leg DEMON HIT", 3, "hit"),
    ("4-leg DEMON HIT", 4, "hit"),
    ("5-leg DEMON HIT", 5, "hit"),
]

DEMON_MIXES = {
    3: {"DEMON": 3},
    4: {"DEMON": 4},
    5: {"DEMON": 5},
}

PAYOUT_POWER_MULT = {3: 1.0, 4: 1.0, 5: 1.0}
PAYOUT_FLEX = {3: 2.25, 4: 5.0, 5: 10.0}

SEEDS = [42, 137]          # 2 seeds (was 5) — DEMON pool is 800-3000 legs, seeds barely vary
TOP_K = 3                  # 3 slips per seed (was 5)
MAX_ATTEMPTS = 30_000
SLIP_WIN_WEIGHT = 10
MIN_DATES_BEFORE_PRUNE = 4  # Don't prune until 4 dates have been scored


def _demon_mix_ok(n_legs: int, legs: Any) -> bool:
    s = str(legs or "")
    return (s.count("(DEMON)") == n_legs
            and s.count("(GOBLIN)") == 0
            and s.count("(STANDARD)") == 0)


# ── data loading ────────────────────────────────────────────────────
def load_all_dates() -> list[tuple[str, pd.DataFrame, dict]]:
    loaded = []
    for date in RUN_DATES:
        run_dir = BASE / date
        if not run_dir.exists():
            continue
        eval_files = list(run_dir.rglob("eval_legs.csv"))
        scored_files = list(run_dir.rglob("scored_legs_deduped.csv"))
        if not eval_files or not scored_files:
            continue
        eval_df = pd.read_csv(eval_files[0], low_memory=False)
        scored_df = pd.read_csv(scored_files[0], low_memory=False)

        truth: dict[tuple, int] = {}
        for _, row in eval_df.iterrows():
            player = str(row.get("player", "")).strip().lower()
            line_val = row.get("line", 0)
            line = float(line_val if pd.notna(line_val) else 0)
            stat = str(row.get("stat", "")).strip().upper()
            direction = str(row.get("direction", "")).strip().lower()
            hit_val = row.get("hit", 0)
            if pd.isna(hit_val):
                continue
            truth[(player, line, stat, direction)] = int(hit_val)
        loaded.append((date, scored_df, truth))
    print(f"Loaded {len(loaded)} dates from corpus")
    return loaded


def sort_dates_by_difficulty(
    data: list[tuple[str, pd.DataFrame, dict]],
    base_cfg: dict,
    n_legs: int,
) -> list[tuple[str, pd.DataFrame, dict]]:
    """Sort dates hardest-first so early-exit pruning is most effective."""
    wins_per_date: list[tuple[int, int]] = []
    for idx, (date, scored_df, truth) in enumerate(data):
        total_wins = 0
        mixes = {n_legs: DEMON_MIXES[n_legs]}
        for seed in SEEDS:
            try:
                slips = build_slips_by_tier_buckets(
                    legs_df=scored_df, n_legs=n_legs, top_n=TOP_K,
                    payout_power_mult=PAYOUT_POWER_MULT[n_legs],
                    payout_flex=PAYOUT_FLEX,
                    pricing_engine="atlas", cfg=base_cfg, seed=seed,
                    per_tier=400, max_attempts=MAX_ATTEMPTS, sort_mode="hit",
                    mixes=mixes, required_tiers=["DEMON"],
                    mix_ok_fn=lambda n, s: _demon_mix_ok(n, s),
                )
            except Exception:
                continue
            if slips is None or slips.empty:
                continue
            for rank in range(min(TOP_K, len(slips))):
                all_hit, _, _ = evaluate_slip(slips.iloc[rank], truth)
                if all_hit:
                    total_wins += 1
        wins_per_date.append((total_wins, idx))
    wins_per_date.sort(key=lambda x: x[0])
    sorted_data = [data[idx] for _, idx in wins_per_date]
    order_str = ", ".join(f"{data[idx][0]}({w}w)" for w, idx in wins_per_date)
    print(f"  Date difficulty order: {order_str}")
    return sorted_data


# ── slip evaluation ─────────────────────────────────────────────────
def evaluate_slip(slip_row, truth: dict) -> tuple[bool, int, int]:
    legs_str = str(slip_row.get("legs", ""))
    parts = legs_str.split(" | ")
    matched = hit = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "[id:" in part:
            part = part[: part.index("[id:")].strip()
        if "(" in part:
            part = part[: part.rindex("(")].strip()
        tokens = part.split()
        if len(tokens) < 4:
            continue
        direction = tokens[-3].lower()
        stat = tokens[-2].upper()
        try:
            line = float(tokens[-1])
        except ValueError:
            continue
        player = " ".join(tokens[:-3]).strip().lower()
        key = (player, line, stat, direction)
        if key in truth:
            matched += 1
            hit += truth[key]
    all_hit = hit == matched and matched > 0
    return all_hit, matched, hit


# ── score a config ──────────────────────────────────────────────────
def score_config(
    overrides: dict[str, Any],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    best_weighted: float = -1.0,
) -> dict[str, Any] | None:
    cfg = copy.deepcopy(base_cfg)
    sb = cfg.setdefault("slip_build", {})

    per_tier_override = None
    for key, val in overrides.items():
        if key == "penalty":
            pen = sb.setdefault("penalty", {})
            pen.update(val)
        elif key == "per_tier":
            per_tier_override = int(val)
        else:
            sb[key] = val

    total_slip_wins = 0
    total_dates = 0
    total_legs_matched = 0
    total_legs_hit = 0

    for idx, (date, scored_df, truth) in enumerate(data):
        # Only prune after MIN_DATES_BEFORE_PRUNE dates have been scored
        if idx >= MIN_DATES_BEFORE_PRUNE:
            remaining = len(data) - idx
            max_possible_future = remaining * len(SEEDS) * TOP_K
            current_weighted = total_slip_wins * SLIP_WIN_WEIGHT + total_legs_hit
            best_possible = current_weighted + max_possible_future * SLIP_WIN_WEIGHT
            if best_weighted >= 0 and best_possible <= best_weighted:
                return None

        total_dates += 1
        mixes = {n_legs: DEMON_MIXES[n_legs]}
        pt = per_tier_override or 400

        for seed in SEEDS:
            try:
                slips = build_slips_by_tier_buckets(
                    legs_df=scored_df,
                    n_legs=n_legs,
                    top_n=TOP_K,
                    payout_power_mult=PAYOUT_POWER_MULT[n_legs],
                    payout_flex=PAYOUT_FLEX,
                    pricing_engine="atlas",
                    cfg=cfg,
                    seed=seed,
                    per_tier=pt,
                    max_attempts=MAX_ATTEMPTS,
                    sort_mode=sort_mode,
                    mixes=mixes,
                    required_tiers=["DEMON"],
                    mix_ok_fn=lambda n, s: _demon_mix_ok(n, s),
                )
            except Exception:
                continue
            if slips is None or slips.empty:
                continue

            for rank in range(min(TOP_K, len(slips))):
                all_hit, matched, hit_count = evaluate_slip(slips.iloc[rank], truth)
                if all_hit:
                    total_slip_wins += 1
                total_legs_matched += matched
                total_legs_hit += hit_count

    weighted = total_slip_wins * SLIP_WIN_WEIGHT + total_legs_hit
    return {
        "slip_wins": total_slip_wins,
        "weighted": weighted,
        "dates": total_dates,
        "legs_hit": total_legs_hit,
        "legs_matched": total_legs_matched,
        "leg_rate": total_legs_hit / max(total_legs_matched, 1),
    }


# ── S1: structural + filter grid ────────────────────────────────────
def build_s1_grid() -> list[dict[str, Any]]:
    """Combined structural + filter sweep. ~200 combos."""
    min_leg_prob_options = [0.50, 0.52, 0.54, 0.56, 0.58]
    min_edge_options = [0.0, 0.005, 0.01, 0.03]
    max_same_stat_options = [0, 2, 3]
    max_players_per_team_options = [1, 2, 3]
    penalty_options = [
        {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0},
        {"team_w": 0.05, "family_w": 0.05, "frag_w": 0.05},
    ]

    grid: list[dict[str, Any]] = []
    for mlp, me, ms, mpt, pen in itertools.product(
        min_leg_prob_options, min_edge_options,
        max_same_stat_options, max_players_per_team_options,
        penalty_options,
    ):
        combo: dict[str, Any] = {
            "min_leg_prob": mlp,
            "max_same_stat": ms,
            "max_players_per_team": mpt,
            "penalty": dict(pen),
        }
        if me > 0.0:
            combo["min_edge"] = me
        grid.append(combo)

    # Also add the v2 winner and near-variants as anchors
    v2_base = {"min_leg_prob": 0.56, "max_same_stat": 2, "max_players_per_team": 1,
               "penalty": {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0}}
    for frag in [0.0, 0.03, 0.05, 0.10]:
        combo = copy.deepcopy(v2_base)
        combo["penalty"]["frag_w"] = frag
        grid.append(combo)
    for mlp_delta in [-0.02, -0.01, 0.01, 0.02]:
        combo = copy.deepcopy(v2_base)
        combo["min_leg_prob"] = round(0.56 + mlp_delta, 2)
        grid.append(combo)

    # Deduplicate
    seen = set()
    unique = []
    for c in grid:
        key = str(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    random.seed(42)
    random.shuffle(unique)
    return unique


# ── S2: beam/pool/per_tier exploration ───────────────────────────────
def build_s2_grid(n_legs: int, s1_winner: dict[str, Any]) -> list[dict[str, Any]]:
    """Focused exploration. per_tier is the key lever for DEMON.
    ~80 combos total."""
    per_tier_options = [200, 400, 600, 800, 1000]
    beam_options = [200, 400, 600]
    pool_mult_options = [150, 350, 600]
    phase1_options = [0.10, 0.30, 0.50]

    grid: list[dict[str, Any]] = []

    # Primary sweep: per_tier × beam (15 combos)
    for pt, bw in itertools.product(per_tier_options, beam_options):
        combo = copy.deepcopy(s1_winner)
        combo["per_tier"] = pt
        combo["beam_width"] = bw
        grid.append(combo)

    # Secondary: per_tier × pool_mult (15 combos)
    for pt, pm in itertools.product(per_tier_options, pool_mult_options):
        combo = copy.deepcopy(s1_winner)
        combo["per_tier"] = pt
        combo["target_pool_mult"] = pm
        grid.append(combo)

    # Tertiary: per_tier × phase1 (15 combos)
    for pt, pf in itertools.product(per_tier_options, phase1_options):
        combo = copy.deepcopy(s1_winner)
        combo["per_tier"] = pt
        combo["phase1_frac"] = pf
        grid.append(combo)

    # Full combos on best per_tier values (3×3×3 = 27 combos, on 2 per_tier values)
    for pt in [400, 800]:
        for bw, pm, pf in itertools.product(beam_options, pool_mult_options, phase1_options):
            combo = copy.deepcopy(s1_winner)
            combo["per_tier"] = pt
            combo["beam_width"] = bw
            combo["target_pool_mult"] = pm
            combo["phase1_frac"] = pf
            grid.append(combo)

    # phase1_pool_frac variants on a few promising combos
    for ppf in [0.25, 0.50, 0.75]:
        combo = copy.deepcopy(s1_winner)
        combo["per_tier"] = 600
        combo["beam_width"] = 400
        combo["target_pool_mult"] = 350
        combo["phase1_frac"] = 0.30
        combo["phase1_pool_frac"] = ppf
        grid.append(combo)

    # Deduplicate
    seen = set()
    unique = []
    for c in grid:
        key = str(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    random.shuffle(unique)
    return unique


# ── Grid runner ──────────────────────────────────────────────────────
def _run_grid(
    grid: list[dict[str, Any]],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    total_combos = len(grid)
    start = time.time()
    best_weighted: float = -1.0
    best_combo: dict[str, Any] = {}
    best_result: dict[str, Any] = {}
    skipped = 0
    evaluated = 0

    for i, combo in enumerate(grid):
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total_combos - i - 1) / rate if rate > 0 else 0
            print(f"    ... {i + 1}/{total_combos}  eval={evaluated} skip={skipped}"
                  f"  best_w={best_weighted:.0f}"
                  f"  ({best_result.get('slip_wins', 0)} wins)"
                  f"  {elapsed:.0f}s elapsed  ETA {eta:.0f}s")

        result = score_config(
            combo, base_cfg, data, n_legs, sort_mode,
            best_weighted=best_weighted,
        )
        if result is None:
            skipped += 1
            continue

        evaluated += 1
        if result["weighted"] > best_weighted:
            best_weighted = result["weighted"]
            best_combo = copy.deepcopy(combo)
            best_result = result

    elapsed = time.time() - start
    print(f"    {label} BEST: weighted={best_result.get('weighted', 0)}"
          f"  slips={best_result.get('slip_wins', 0)}"
          f"  legs={best_result.get('legs_hit', 0)}/{best_result.get('legs_matched', 0)}"
          f" ({best_result.get('leg_rate', 0):.0%})"
          f"  [{elapsed:.0f}s, {evaluated} eval, {skipped} skipped]")
    return best_combo, best_result


def _print_combo(combo: dict[str, Any]) -> None:
    mlp = combo.get("min_leg_prob", "-")
    me = combo.get("min_edge", 0.0)
    ms = combo.get("max_same_stat", "-")
    mpt = combo.get("max_players_per_team", "-")
    pen = combo.get("penalty", {})
    tw = pen.get("team_w", 0.0)
    fw = pen.get("family_w", 0.0)
    fragw = pen.get("frag_w", 0.0)
    bw = combo.get("beam_width", "-")
    pf = combo.get("phase1_frac", "-")
    pm = combo.get("target_pool_mult", "-")
    pt = combo.get("per_tier", "-")
    ppf = combo.get("phase1_pool_frac", "-")
    print(f"    min_leg_prob={mlp}  min_edge={me}  max_same_stat={ms}"
          f"  max_players_per_team={mpt}")
    print(f"    team_w={tw}  family_w={fw}  frag_w={fragw}")
    print(f"    beam={bw}  phase1={pf}  pool={pm}  per_tier={pt}  ppf={ppf}")


# ── 2-stage per-category search ──────────────────────────────────────
def train(base_cfg: dict, data: list[tuple[str, pd.DataFrame, dict]]) -> dict:
    results: dict[str, dict[str, Any]] = {}
    total_start = time.time()

    for cat_name, n_legs, sort_mode in CATEGORIES:
        cat_start = time.time()
        print(f"\n  === {cat_name} ===")
        sorted_data = sort_dates_by_difficulty(data, base_cfg, n_legs)

        # S1: structural + filters
        s1_grid = build_s1_grid()
        print(f"  S1: structural+filters ({len(s1_grid)} combos, {len(SEEDS)} seeds, TOP_K={TOP_K})")
        s1_combo, s1_result = _run_grid(s1_grid, base_cfg, sorted_data, n_legs, sort_mode, "S1")
        _print_combo(s1_combo)

        # S2: beam/pool/per_tier exploration
        s2_grid = build_s2_grid(n_legs, s1_combo)
        print(f"  S2: exploration ({len(s2_grid)} combos)")
        s2_combo, s2_result = _run_grid(s2_grid, base_cfg, sorted_data, n_legs, sort_mode, "S2")
        _print_combo(s2_combo)

        best = (s2_combo, s2_result) if s2_result.get("weighted", 0) >= s1_result.get("weighted", 0) else (s1_combo, s1_result)

        cat_elapsed = time.time() - cat_start
        print(f"\n  >>> {cat_name} FINAL: weighted={best[1]['weighted']}"
              f"  slip_wins={best[1]['slip_wins']}"
              f"  leg_rate={best[1]['leg_rate']:.1%}"
              f"  [{cat_elapsed:.0f}s]")
        _print_combo(best[0])

        results[cat_name] = {
            "overrides": best[0],
            **best[1],
        }

    total_elapsed = time.time() - total_start
    print(f"\n  Total elapsed: {total_elapsed:.0f}s ({total_elapsed / 3600:.1f}h)")
    return results


# ── main ─────────────────────────────────────────────────────────────
def main() -> None:
    print("DemonHunter Trainer v4")
    print("=" * 50)
    print(f"Seeds: {SEEDS} | TOP_K: {TOP_K} | MIN_DATES_BEFORE_PRUNE: {MIN_DATES_BEFORE_PRUNE}")

    data = load_all_dates()
    if not data:
        print("No data loaded, exiting.")
        return

    # Load production config as base (same as EV/HIT trainers)
    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(cfg_path) as f:
        base_cfg = yaml.safe_load(f)
    sb = base_cfg.get("slip_build", {})
    sb.pop("by_legs", None)
    sb.pop("by_sort_mode", None)

    results = train(base_cfg, data)

    # Embed config fingerprint
    results["_manifest"] = build_manifest(
        source="demonhunter_trainer_v4", cfg=base_cfg,
        ensemble_dir=base_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    )
    print(f"  Config fingerprint: {results['_manifest']['config_fingerprint']}")

    out_path = Path(__file__).parent / "demonhunter_trainer_results_v4.yaml"
    with open(out_path, "w") as f:
        yaml.dump(results, f, default_flow_style=False, sort_keys=False)
    print(f"\nResults saved to {out_path}")

    # Print comparison vs v2
    print("\n  === v2 → v4 Comparison ===")
    v2_wins = {"3-leg DEMON HIT": 39, "4-leg DEMON HIT": 25, "5-leg DEMON HIT": 17}
    v2_weighted = {"3-leg DEMON HIT": 679, "4-leg DEMON HIT": 612, "5-leg DEMON HIT": 621}
    for cat in ["3-leg DEMON HIT", "4-leg DEMON HIT", "5-leg DEMON HIT"]:
        if cat in results:
            v4w = results[cat]["weighted"]
            v4s = results[cat]["slip_wins"]
            v2w_val = v2_weighted.get(cat, 0)
            v2s_val = v2_wins.get(cat, 0)
            delta_w = ((v4w / v2w_val - 1) * 100) if v2w_val else 0
            delta_s = ((v4s / v2s_val - 1) * 100) if v2s_val else 0
            print(f"  {cat}: weighted {v2w_val}→{v4w} ({delta_w:+.1f}%), "
                  f"slip_wins {v2s_val}→{v4s} ({delta_s:+.1f}%)")


if __name__ == "__main__":
    main()

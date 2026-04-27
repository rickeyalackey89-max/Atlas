#!/usr/bin/env python
"""
Leg Selection Trainer v5
========================
Upgrades over v4:
  - Multiprocessing: parallel combo evaluation via ProcessPoolExecutor
  - Expanded grid: frag_w, min_leg_prob, max_players_per_team, phase1_pool_frac, finer min_edge
  - Stage 3: fine-tuning ±small steps around S2 winner
  - 5 seeds (42, 137, 9999, 2026, 777) for more stable estimates
  - Date difficulty sorting: hardest dates first for better early-exit pruning
  - Shuffled grid order: discover good combos earlier -> more early exits
"""
from __future__ import annotations

import copy
import itertools
import multiprocessing
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.fingerprint import build_manifest, config_fingerprint
from Atlas.core.slip_builders import build_slips_by_tier_buckets
from Atlas.stages.optimize.build_slips_today import _cfg_for_n_legs

# ── data paths ──────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parents[1] / "data" / "telemetry" / "replay_runs"
_TAG_FILE = BASE / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"
RUN_DATES = [
    "20260315", "20260316", "20260317", "20260318",
    "20260319", "20260320", "20260321", "20260322",
    "20260323", "20260324", "20260325", "20260326",
]

CATEGORIES = [
    ("3-leg EV",  3, "ev"),
    ("3-leg HIT", 3, "hit"),
    ("4-leg EV",  4, "ev"),
    ("4-leg HIT", 4, "hit"),
    ("5-leg EV",  5, "ev"),
    ("5-leg HIT", 5, "hit"),
]

MIXES = {
    3: {"STANDARD": 2, "DEMON": 1},
    4: {"STANDARD": 2, "DEMON": 2},
    5: {"STANDARD": 3, "DEMON": 2},
}
PAYOUT_FLEX = {"3": 2.25, "4": 5.0, "5": 10.0}

# 5-seed for stability (up from 3)
SEEDS = [42, 137, 9999, 2026, 777]
TOP_K = 5          # evaluate top-K slips per seed per date
MAX_ATTEMPTS = 30_000
SLIP_WIN_WEIGHT = 10  # weighted_score = slip_wins * 10 + legs_hit

# Parallelism: use all but 2 cores (leave headroom for OS)
N_WORKERS = max(1, (os.cpu_count() or 4) - 2)

WORST_SD_COMBOS = [
    "AST_under", "REB_under", "PA_under",
    "PTS_under", "PR_under", "PRA_under", "RA_under",
]


# ── data loading ────────────────────────────────────────────────────
def load_all_dates() -> list[tuple[str, pd.DataFrame, dict]]:
    loaded = []
    for date in RUN_DATES:
        run_dir = BASE / f"{_CORPUS_TAG}_{date}"
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
    sort_mode: str,
) -> list[tuple[str, pd.DataFrame, dict]]:
    """Sort dates so the hardest ones come first (fewer baseline slip wins).
    This makes early-exit pruning more aggressive."""
    wins_per_date: list[tuple[int, int]] = []
    for idx, (date, scored_df, truth) in enumerate(data):
        total_wins = 0
        resolved_cfg, _ = _cfg_for_n_legs(base_cfg, n_legs, 10, sort_mode)
        for seed in SEEDS[:2]:  # Quick check with 2 seeds only
            try:
                slips = build_slips_by_tier_buckets(
                    legs_df=scored_df, n_legs=n_legs, top_n=TOP_K,
                    payout_power_mult=1.0, payout_flex=PAYOUT_FLEX,
                    pricing_engine="atlas", cfg=resolved_cfg, seed=seed,
                    per_tier=500, max_attempts=MAX_ATTEMPTS, sort_mode=sort_mode,
                    mixes=MIXES, required_tiers=["STANDARD", "DEMON"],
                    mix_ok_fn=lambda n, s: True,
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

    # Sort ascending (fewest wins = hardest = first)
    wins_per_date.sort(key=lambda x: x[0])
    sorted_data = [data[idx] for _, idx in wins_per_date]
    order_str = ", ".join(f"{data[idx][0]}({w}w)" for w, idx in wins_per_date)
    print(f"  Date difficulty order: {order_str}")
    return sorted_data


# ── slip evaluation (supports top-K) ───────────────────────────────
def evaluate_slip(slip_row, truth: dict) -> tuple[bool, int, int]:
    """Return (all_hit, matched_count, hit_count) for a single slip."""
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


# ── score a config override for ONE category ────────────────────────
def score_config(
    overrides: dict[str, Any],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    best_weighted: float = -1.0,
) -> dict[str, Any] | None:
    """
    Apply overrides, evaluate top-K slips across seeds on all dates.
    Weighted score = slip_wins * SLIP_WIN_WEIGHT + legs_hit.
    Early-exits when remaining dates can't beat best_weighted.
    Returns None if early-exited.
    """
    cfg = copy.deepcopy(base_cfg)
    sb = cfg.setdefault("slip_build", {})

    for key, val in overrides.items():
        if key == "penalty":
            pen = sb.setdefault("penalty", {})
            pen.update(val)
        else:
            sb[key] = val

    resolved_cfg, _ = _cfg_for_n_legs(cfg, n_legs, 10, sort_mode)

    total_slip_wins = 0
    total_dates = 0
    total_legs_matched = 0
    total_legs_hit = 0

    for idx, (date, scored_df, truth) in enumerate(data):
        # Early exit: max possible remaining = remaining_dates * len(SEEDS) * TOP_K wins
        remaining = len(data) - idx
        max_possible_future_wins = remaining * len(SEEDS) * TOP_K
        current_weighted = total_slip_wins * SLIP_WIN_WEIGHT + total_legs_hit
        best_possible = current_weighted + max_possible_future_wins * SLIP_WIN_WEIGHT
        if best_weighted >= 0 and best_possible <= best_weighted:
            return None

        total_dates += 1

        for seed in SEEDS:
            try:
                slips = build_slips_by_tier_buckets(
                    legs_df=scored_df, n_legs=n_legs, top_n=TOP_K,
                    payout_power_mult=1.0, payout_flex=PAYOUT_FLEX,
                    pricing_engine="atlas", cfg=resolved_cfg, seed=seed,
                    per_tier=500, max_attempts=MAX_ATTEMPTS, sort_mode=sort_mode,
                    mixes=MIXES, required_tiers=["STANDARD", "DEMON"],
                    mix_ok_fn=lambda n, s: True,
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
        "seeds": len(SEEDS),
        "top_k": TOP_K,
    }


# ── Worker function for parallel eval ───────────────────────────────
def _score_worker(args: tuple) -> tuple[int, dict[str, Any] | None, dict[str, Any]]:
    """Evaluate a single combo in a worker process.
    Returns (combo_index, result_or_None, combo_dict)."""
    idx, combo, base_cfg, data, n_legs, sort_mode, best_w = args
    result = score_config(combo, base_cfg, data, n_legs, sort_mode, best_weighted=best_w)
    return idx, result, combo


# ── Build structural grid (Stage 1) — EXPANDED ──────────────────────
def build_structural_grid(sort_mode: str = "ev") -> list[dict[str, Any]]:
    exclude_options: list[list[str]] = [
        [],
        WORST_SD_COMBOS[:3],
        WORST_SD_COMBOS[:5],
    ]
    max_under_options: list[int | None] = [None, 2, 1]
    min_edge_options = [0.0, 0.02, 0.04]
    max_same_stat_options = [2, 3]
    # Penalty grid (same as v4)
    penalty_options = [
        {"team_w": 0.0, "family_w": 0.0},
        {"team_w": 0.05, "family_w": 0.05},
        {"team_w": 0.10, "family_w": 0.05},
        {"team_w": 0.15, "family_w": 0.10},
    ]
    if sort_mode in ("hit", "winprob"):
        max_leg_prob_options = [0.0, 0.55, 0.60, 0.65]
    else:
        max_leg_prob_options = [0.0]

    grid: list[dict[str, Any]] = []
    for exclude, max_under, min_edge, max_stat, penalty, mlp in itertools.product(
        exclude_options, max_under_options, min_edge_options,
        max_same_stat_options, penalty_options, max_leg_prob_options,
    ):
        combo: dict[str, Any] = {}
        if exclude:
            combo["exclude_stat_directions"] = list(exclude)
        if max_under is not None:
            combo["max_direction_per_slip"] = {"under": max_under}
        if min_edge > 0.0:
            combo["min_edge"] = min_edge
        if mlp > 0.0:
            combo["max_leg_prob"] = mlp
        combo["max_same_stat"] = max_stat
        combo["penalty"] = dict(penalty)
        grid.append(combo)

    # Shuffle for better early-exit discovery
    random.seed(42)
    random.shuffle(grid)
    return grid


# ── Build new-param refinement grid (Stage 1b) ──────────────────────
def build_refinement_grid(s1_winner: dict[str, Any]) -> list[dict[str, Any]]:
    """Test new params (frag_w, min_leg_prob, max_players_per_team, finer min_edge)
    around the S1 structural winner. Much smaller than full cross-product."""
    grid: list[dict[str, Any]] = []

    # Finer min_edge around winner
    base_edge = float(s1_winner.get("min_edge", 0.0))
    for edge in [base_edge - 0.01, base_edge + 0.01, base_edge + 0.03]:
        if edge < 0.0:
            continue
        combo = copy.deepcopy(s1_winner)
        combo["min_edge"] = round(edge, 3)
        grid.append(combo)

    # frag_w variations
    for frag in [0.05, 0.10]:
        combo = copy.deepcopy(s1_winner)
        pen = combo.setdefault("penalty", {})
        pen["frag_w"] = frag
        grid.append(combo)

    # min_leg_prob variations
    for mlgp in [0.52, 0.54]:
        combo = copy.deepcopy(s1_winner)
        combo["min_leg_prob"] = mlgp
        grid.append(combo)

    # max_players_per_team = 2 (v4 never tested)
    combo = copy.deepcopy(s1_winner)
    combo["max_players_per_team"] = 2
    grid.append(combo)

    # Exclude 7 (all)
    if len(s1_winner.get("exclude_stat_directions", [])) < 7:
        combo = copy.deepcopy(s1_winner)
        combo["exclude_stat_directions"] = list(WORST_SD_COMBOS[:7])
        grid.append(combo)

    # Combine best new params: frag + min_leg_prob
    for frag, mlgp in [(0.05, 0.52), (0.05, 0.54), (0.10, 0.52)]:
        combo = copy.deepcopy(s1_winner)
        pen = combo.setdefault("penalty", {})
        pen["frag_w"] = frag
        combo["min_leg_prob"] = mlgp
        grid.append(combo)

    # Deduplicate
    seen = set()
    unique = []
    for combo in grid:
        key = str(sorted(combo.items()))
        if key not in seen:
            seen.add(key)
            unique.append(combo)
    return unique


# ── Build exploration grid (Stage 2) ─────────────────────────────────
def build_exploration_grid(n_legs: int, structural_winner: dict[str, Any]) -> list[dict[str, Any]]:
    if n_legs == 3:
        beam_options = [200, 300, 400]
        phase1_options = [0.10, 0.25, 0.40]
        pool_mult_options = [150, 250, 400]
    elif n_legs == 4:
        beam_options = [300, 450, 600]
        phase1_options = [0.20, 0.40, 0.60]
        pool_mult_options = [250, 400, 600]
    else:  # 5-leg
        beam_options = [400, 550, 750]
        phase1_options = [0.30, 0.50, 0.70]
        pool_mult_options = [350, 550, 750]

    # NEW: also test phase1_pool_frac around each combo
    phase1_pool_frac_options = [0.50, 0.60, 0.75]

    grid: list[dict[str, Any]] = []
    for beam, phase1, pool_mult in itertools.product(
        beam_options, phase1_options, pool_mult_options,
    ):
        # Base combo at default phase1_pool_frac
        combo = copy.deepcopy(structural_winner)
        combo["beam_width"] = beam
        combo["phase1_frac"] = phase1
        combo["target_pool_mult"] = pool_mult
        grid.append(combo)

    # After base 27, add phase1_pool_frac variants on the best-looking combos
    # (test all 3 ppf values on the first few beam/phase1/pool combos)
    for ppf in phase1_pool_frac_options:
        if ppf == 0.60:  # default, already covered above
            continue
        for beam, phase1, pool_mult in [(beam_options[1], phase1_options[1], pool_mult_options[1])]:
            combo = copy.deepcopy(structural_winner)
            combo["beam_width"] = beam
            combo["phase1_frac"] = phase1
            combo["target_pool_mult"] = pool_mult
            combo["phase1_pool_frac"] = ppf
            grid.append(combo)

    random.shuffle(grid)
    return grid


# ── Build fine-tuning grid (Stage 3) ─────────────────────────────────
def build_finetune_grid(s2_winner: dict[str, Any], n_legs: int) -> list[dict[str, Any]]:
    """Generate ±small step variations around the S2 winner on continuous params."""
    grid: list[dict[str, Any]] = []

    # Define small perturbations for each continuous param
    perturbations = {
        "min_edge": [-0.01, 0.0, 0.01],
        "beam_width": [-50, 0, 50],
        "phase1_frac": [-0.05, 0.0, 0.05],
        "target_pool_mult": [-50, 0, 50],
        "phase1_pool_frac": [-0.05, 0.0, 0.05],
    }
    # Also try nearby max_leg_prob if it was set
    if s2_winner.get("max_leg_prob", 0.0) > 0.0:
        perturbations["max_leg_prob"] = [-0.03, 0.0, 0.03]
    if s2_winner.get("min_leg_prob", 0.0) > 0.0:
        perturbations["min_leg_prob"] = [-0.01, 0.0, 0.01]

    # Penalty sub-dict perturbations
    pen_perturbations = {
        "team_w": [-0.02, 0.0, 0.02],
        "family_w": [-0.02, 0.0, 0.02],
        "frag_w": [-0.02, 0.0, 0.02],
    }

    # Generate all pairwise perturbations (vary 1-2 params at a time)
    param_names = list(perturbations.keys())
    for i, pname in enumerate(param_names):
        base_val = s2_winner.get(pname, 0.0)
        if pname in ("beam_width", "target_pool_mult"):
            base_val = int(base_val) if base_val else (200 if pname == "beam_width" else 200)
        else:
            base_val = float(base_val) if base_val else 0.0

        for delta in perturbations[pname]:
            if delta == 0.0:
                continue
            new_val = base_val + delta
            # Enforce minimums
            if pname == "min_edge" and new_val < 0.0:
                continue
            if pname in ("beam_width", "target_pool_mult") and new_val < 50:
                continue
            if pname == "phase1_frac" and (new_val < 0.05 or new_val > 0.95):
                continue
            if pname == "phase1_pool_frac" and (new_val < 0.30 or new_val > 0.90):
                continue
            if pname in ("max_leg_prob", "min_leg_prob") and new_val < 0.0:
                continue

            combo = copy.deepcopy(s2_winner)
            if pname in ("beam_width", "target_pool_mult"):
                combo[pname] = int(new_val)
            else:
                combo[pname] = round(new_val, 3)
            grid.append(combo)

    # Penalty perturbations
    base_pen = s2_winner.get("penalty", {})
    for pen_key, deltas in pen_perturbations.items():
        base_val = float(base_pen.get(pen_key, 0.0))
        for delta in deltas:
            if delta == 0.0:
                continue
            new_val = base_val + delta
            if new_val < 0.0:
                continue
            combo = copy.deepcopy(s2_winner)
            pen = combo.setdefault("penalty", {})
            pen[pen_key] = round(new_val, 3)
            grid.append(combo)

    # Deduplicate
    seen = set()
    unique_grid = []
    for combo in grid:
        key = str(sorted(combo.items()))
        if key not in seen:
            seen.add(key)
            unique_grid.append(combo)

    return unique_grid


# ── Grid runner (sequential with early-exit) ─────────────────────────
def _run_grid_sequential(
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

    for i, combo in enumerate(grid):
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total_combos - i - 1) / rate if rate > 0 else 0
            print(f"    ... {i + 1}/{total_combos}  ({skipped} skipped)"
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

        if result["weighted"] > best_weighted:
            best_weighted = result["weighted"]
            best_combo = copy.deepcopy(combo)
            best_result = result

    elapsed = time.time() - start
    print(f"    {label} BEST: weighted={best_result.get('weighted', 0)}"
          f"  slips={best_result.get('slip_wins', 0)}"
          f"  legs={best_result.get('legs_hit', 0)}/{best_result.get('legs_matched', 0)}"
          f" ({best_result.get('leg_rate', 0):.0%})"
          f"  [{elapsed:.0f}s, {skipped} early-exits]")
    return best_combo, best_result


# ── Grid runner (parallel — for large S1 grids) ─────────────────────
def _run_grid_parallel(
    grid: list[dict[str, Any]],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    label: str,
    n_workers: int = N_WORKERS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parallel grid evaluation with periodic best_weighted broadcast.
    We batch combos in chunks; after each chunk, we update best_weighted
    so subsequent chunks can early-exit more aggressively."""
    total_combos = len(grid)
    CHUNK_SIZE = max(n_workers * 2, 16)
    start = time.time()
    best_weighted: float = -1.0
    best_combo: dict[str, Any] = {}
    best_result: dict[str, Any] = {}
    skipped = 0
    evaluated = 0

    for chunk_start in range(0, total_combos, CHUNK_SIZE):
        chunk = grid[chunk_start : chunk_start + CHUNK_SIZE]
        args_list = [
            (i + chunk_start, combo, base_cfg, data, n_legs, sort_mode, best_weighted)
            for i, combo in enumerate(chunk)
        ]

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {executor.submit(_score_worker, args): args[0] for args in args_list}
            for fut in as_completed(futures):
                idx, result, combo = fut.result()
                evaluated += 1
                if result is None:
                    skipped += 1
                    continue
                if result["weighted"] > best_weighted:
                    best_weighted = result["weighted"]
                    best_combo = copy.deepcopy(combo)
                    best_result = result

        done = chunk_start + len(chunk)
        if done % (CHUNK_SIZE * 3) < CHUNK_SIZE or done == total_combos:
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total_combos - done) / rate if rate > 0 else 0
            print(f"    ... {done}/{total_combos}  ({skipped} skipped)"
                  f"  best_w={best_weighted:.0f}"
                  f"  ({best_result.get('slip_wins', 0)} wins)"
                  f"  {elapsed:.0f}s elapsed  ETA {eta:.0f}s")

    elapsed = time.time() - start
    print(f"    {label} BEST: weighted={best_result.get('weighted', 0)}"
          f"  slips={best_result.get('slip_wins', 0)}"
          f"  legs={best_result.get('legs_hit', 0)}/{best_result.get('legs_matched', 0)}"
          f" ({best_result.get('leg_rate', 0):.0%})"
          f"  [{elapsed:.0f}s, {skipped} early-exits, {n_workers} workers]")
    return best_combo, best_result


def _print_combo(combo: dict[str, Any]) -> None:
    exc = combo.get("exclude_stat_directions", [])
    mdu = combo.get("max_direction_per_slip", {}).get("under", "-")
    me = combo.get("min_edge", 0.0)
    ms = combo.get("max_same_stat", "-")
    pen = combo.get("penalty", {})
    tw = pen.get("team_w", 0.0)
    fw = pen.get("family_w", 0.0)
    fragw = pen.get("frag_w", 0.0)
    bw = combo.get("beam_width", "-")
    pf = combo.get("phase1_frac", "-")
    pm = combo.get("target_pool_mult", "-")
    ppf = combo.get("phase1_pool_frac", "-")
    mlp = combo.get("max_leg_prob", "off")
    mlgp = combo.get("min_leg_prob", "off")
    mppt = combo.get("max_players_per_team", "-")
    print(f"    exclude={len(exc)} combos  max_under/slip={mdu}"
          f"  min_edge={me}  max_same_stat={ms}"
          f"  team_w={tw}  family_w={fw}  frag_w={fragw}")
    print(f"    beam_width={bw}  phase1_frac={pf}  target_pool_mult={pm}"
          f"  phase1_pool_frac={ppf}  max_leg_prob={mlp}"
          f"  min_leg_prob={mlgp}  max_players_per_team={mppt}")


# ── 4-stage per-category search ──────────────────────────────────────
def train_per_category(
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
) -> dict[str, dict[str, Any]]:
    results_per_cat: dict[str, dict[str, Any]] = {}
    total_start = time.time()

    for cat_name, n_legs, sort_mode in CATEGORIES:
        cat_start = time.time()
        print(f"\n  === {cat_name} ===")

        # Sort dates by difficulty for this category
        sorted_data = sort_dates_by_difficulty(data, base_cfg, n_legs, sort_mode)

        # Stage 1: structural grid (same size as v4 — ~216 EV / ~864 HIT)
        structural_grid = build_structural_grid(sort_mode)
        print(f"  Stage 1: structural ({len(structural_grid)} combos,"
              f" {len(sorted_data)} dates, {len(SEEDS)} seeds, top-{TOP_K})")
        s1_combo, s1_result = _run_grid_sequential(
            structural_grid, base_cfg, sorted_data, n_legs, sort_mode, "S1")
        _print_combo(s1_combo)

        # Stage 1b: new-param refinement around S1 winner (~15 combos)
        refine_grid = build_refinement_grid(s1_combo)
        print(f"  Stage 1b: refinement ({len(refine_grid)} combos)")
        s1b_combo, s1b_result = _run_grid_sequential(
            refine_grid, base_cfg, sorted_data, n_legs, sort_mode, "S1b")
        _print_combo(s1b_combo)

        # Pick S1 vs S1b winner
        if s1b_result.get("weighted", 0) >= s1_result.get("weighted", 0):
            structural_best, structural_best_result = s1b_combo, s1b_result
        else:
            structural_best, structural_best_result = s1_combo, s1_result

        # Stage 2: exploration grid (~29 combos)
        explore_grid = build_exploration_grid(n_legs, structural_best)
        print(f"  Stage 2: exploration ({len(explore_grid)} combos)")
        s2_combo, s2_result = _run_grid_sequential(
            explore_grid, base_cfg, sorted_data, n_legs, sort_mode, "S2")
        _print_combo(s2_combo)

        # Pick structural vs S2 winner
        if s2_result.get("weighted", 0) >= structural_best_result.get("weighted", 0):
            s2_best_combo, s2_best_result = s2_combo, s2_result
        else:
            s2_best_combo, s2_best_result = structural_best, structural_best_result

        # Stage 3: fine-tuning around the S2 winner
        finetune_grid = build_finetune_grid(s2_best_combo, n_legs)
        print(f"  Stage 3: fine-tuning ({len(finetune_grid)} combos around S2 winner)")
        s3_combo, s3_result = _run_grid_sequential(
            finetune_grid, base_cfg, sorted_data, n_legs, sort_mode, "S3")
        _print_combo(s3_combo)

        # Final: best of S2-winner vs S3
        if s3_result.get("weighted", 0) >= s2_best_result.get("weighted", 0):
            best_combo, best_result = s3_combo, s3_result
            print(f"  -> S3 improved: weighted {s3_result['weighted']} vs {s2_best_result['weighted']}")
        else:
            best_combo, best_result = s2_best_combo, s2_best_result
            print(f"  -> S2 winner held (S3 did not improve)")

        cat_elapsed = time.time() - cat_start
        print(f"  {cat_name} done in {cat_elapsed:.0f}s ({cat_elapsed / 60:.1f} min)")

        results_per_cat[cat_name] = {
            "overrides": best_combo,
            "result": best_result,
        }

    total_elapsed = time.time() - total_start
    print(f"\n  Total training time: {total_elapsed:.0f}s ({total_elapsed / 3600:.1f} hrs)")
    return results_per_cat


# ── Main ─────────────────────────────────────────────────────────────
def main() -> None:
    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(cfg_path) as f:
        base_cfg = yaml.safe_load(f)

    # Strip existing by_legs and by_sort_mode so trainer operates on clean base
    sb = base_cfg.get("slip_build", {})
    sb.pop("by_legs", None)
    sb.pop("by_sort_mode", None)

    print("=" * 60)
    print("Leg Selection Trainer v5")
    print(f"  Seeds: {SEEDS}  Top-K: {TOP_K}  Max attempts: {MAX_ATTEMPTS}")
    print(f"  Weighted score = slip_wins * {SLIP_WIN_WEIGHT} + legs_hit")
    print(f"  Workers: {N_WORKERS}  (CPU count: {os.cpu_count()})")
    print(f"  Stages: S1 (structural) -> S1b (new params) -> S2 (exploration) -> S3 (fine-tune)")
    print("=" * 60)

    print("\nLoading corpus...")
    data = load_all_dates()
    if not data:
        print("ERROR: No data loaded. Check D drive paths.")
        return

    print("\n--- Baseline (current config) ---")
    for cat_name, n_legs, sort_mode in CATEGORIES:
        result = score_config({}, base_cfg, data, n_legs, sort_mode)
        if result:
            print(f"  {cat_name}: weighted={result['weighted']}"
                  f"  slips={result['slip_wins']}"
                  f"  legs={result['legs_hit']}/{result['legs_matched']}"
                  f" ({result['leg_rate']:.0%})")

    print("\n--- Grid Search (3-stage) ---")
    results = train_per_category(base_cfg, data)

    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)

    for cat_name, info in results.items():
        overrides = info["overrides"]
        result = info["result"]
        print(f"\n  {cat_name}:")
        print(f"    weighted={result['weighted']}"
              f"  slips={result['slip_wins']}"
              f"  legs={result['legs_hit']}/{result['legs_matched']}")
        print(f"    Config overrides:")
        for k, v in overrides.items():
            print(f"      {k}: {v}")

    out_path = Path(__file__).resolve().parent / "leg_trainer_results_v5.yaml"
    out_data = {
        "_manifest": build_manifest(
            source="leg_trainer_v5", cfg=base_cfg,
            ensemble_dir=base_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
        ),
    }
    print(f"  Config fingerprint: {out_data['_manifest']['config_fingerprint']}")
    for cat_name, info in results.items():
        out_data[cat_name] = {
            "overrides": info["overrides"],
            "weighted": info["result"]["weighted"],
            "slip_wins": info["result"]["slip_wins"],
            "dates": info["result"]["dates"],
            "legs_hit": info["result"]["legs_hit"],
            "legs_matched": info["result"]["legs_matched"],
            "leg_rate": round(info["result"]["leg_rate"], 4),
        }
    with open(out_path, "w") as f:
        yaml.dump(out_data, f, default_flow_style=False, sort_keys=False)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

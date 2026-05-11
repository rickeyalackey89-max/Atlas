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
import multiprocessing as mp
from multiprocessing.pool import Pool
import os
import pickle
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
BASE = Path(r"C:\Users\13142\Atlas\Atlas\data\telemetry\v18_corpus")

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
N_WORKERS = os.cpu_count() or 1


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
    data: list[tuple],
    base_cfg: dict,
    n_legs: int,
    sweep_seeds: list | None = None,
) -> list[tuple]:
    """Sort dates hardest-first so early-exit pruning is most effective."""
    wins_per_date: list[tuple[int, int]] = []
    _quick_seeds = (sweep_seeds or SEEDS)[:2]
    for idx, entry in enumerate(data):
        date, scored_df, truth = entry[0], entry[1], entry[2]
        total_wins = 0
        mixes = {n_legs: DEMON_MIXES[n_legs]}
        for seed in _quick_seeds:
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
    sorted_data = [(data[idx][0], data[idx][1], data[idx][2], w) for w, idx in wins_per_date]
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
    data: list[tuple],
    n_legs: int,
    sort_mode: str,
    best_weighted: float = -1.0,
    sweep_seeds: list | None = None,
    sweep_top_k: int | None = None,
) -> dict[str, Any] | None:
    _seeds = sweep_seeds if sweep_seeds is not None else SEEDS
    _top_k = sweep_top_k if sweep_top_k is not None else TOP_K
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

    for idx, entry in enumerate(data):
        date, scored_df, truth = entry[0], entry[1], entry[2]
        # Only prune after MIN_DATES_BEFORE_PRUNE dates have been scored
        if idx >= MIN_DATES_BEFORE_PRUNE:
            remaining = len(data) - idx
            max_possible_future = remaining * len(_seeds) * _top_k
            current_weighted = total_slip_wins * SLIP_WIN_WEIGHT + total_legs_hit
            best_possible = current_weighted + max_possible_future * SLIP_WIN_WEIGHT
            if best_weighted >= 0 and best_possible <= best_weighted:
                return None

        total_dates += 1
        mixes = {n_legs: DEMON_MIXES[n_legs]}
        pt = per_tier_override or 400

        for seed in _seeds:
            try:
                slips = build_slips_by_tier_buckets(
                    legs_df=scored_df,
                    n_legs=n_legs,
                    top_n=_top_k,
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

            for rank in range(min(_top_k, len(slips))):
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


# ── S3: fine-tune around S2 winner ────────────────────────────────────
def build_s3_grid(n_legs: int, s2_winner: dict[str, Any]) -> list[dict[str, Any]]:
    """Fine-grained ±delta sweep around S2 winner. ~20-30 combos, all seeds, full corpus."""
    grid: list[dict[str, Any]] = []

    base_pt = int(s2_winner.get("per_tier", 400))
    base_mlp = float(s2_winner.get("min_leg_prob", 0.56))
    base_bw = int(s2_winner.get("beam_width", 400))

    for pt_delta in [-200, -100, 0, 100, 200]:
        pt = max(100, base_pt + pt_delta)
        combo = copy.deepcopy(s2_winner)
        combo["per_tier"] = pt
        grid.append(combo)

    for mlp_delta in [-0.02, -0.01, 0.0, 0.01, 0.02]:
        mlp = round(base_mlp + mlp_delta, 3)
        if mlp <= 0:
            continue
        combo = copy.deepcopy(s2_winner)
        combo["min_leg_prob"] = mlp
        grid.append(combo)

    for bw_delta in [-200, -100, 0, 100, 200]:
        bw = max(50, base_bw + bw_delta)
        combo = copy.deepcopy(s2_winner)
        combo["beam_width"] = bw
        grid.append(combo)

    seen = set()
    unique = []
    for c in grid:
        key = str(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


# ── Parallel worker infrastructure ────────────────────────────────────
_DH_WORKER_DATA: list | None = None
_DH_WORKER_CFG: dict | None = None


def _dh_worker_init(data_pkl: bytes, cfg_pkl: bytes) -> None:
    """Pool initializer: load data into worker-global state once per process."""
    global _DH_WORKER_DATA, _DH_WORKER_CFG
    import pickle as _pkl
    _DH_WORKER_DATA = _pkl.loads(data_pkl)
    _DH_WORKER_CFG = _pkl.loads(cfg_pkl)


def _dh_score_worker(args: tuple) -> tuple:
    """Pool worker: score one combo using worker-global data/cfg."""
    combo, n_legs, sort_mode, best_weighted, sweep_seeds, sweep_top_k = args
    result = score_config(
        combo, _DH_WORKER_CFG, _DH_WORKER_DATA, n_legs, sort_mode,
        best_weighted=best_weighted,
        sweep_seeds=sweep_seeds,
        sweep_top_k=sweep_top_k,
    )
    return combo, result


# ── Grid runner ──────────────────────────────────────────────────────
def _run_grid(
    grid: list[dict[str, Any]],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    label: str,
    n_workers: int = 1,
    sweep_seeds: list | None = None,
    sweep_top_k: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _sweep_seeds = sweep_seeds if sweep_seeds is not None else SEEDS
    _sweep_top_k = sweep_top_k if sweep_top_k is not None else TOP_K
    total_combos = len(grid)
    start = time.time()
    best_weighted: float = -1.0
    best_combo: dict[str, Any] = {}
    best_result: dict[str, Any] = {}
    skipped = 0
    evaluated = 0

    if n_workers > 1:
        import pickle as _pkl
        data_bytes = _pkl.dumps(data)
        cfg_bytes = _pkl.dumps(base_cfg)
        tasks = [
            (combo, n_legs, sort_mode, -1.0, _sweep_seeds, _sweep_top_k)
            for combo in grid
        ]
        with mp.Pool(n_workers, initializer=_dh_worker_init,
                     initargs=(data_bytes, cfg_bytes)) as pool:
            for i, (combo, result) in enumerate(
                pool.imap_unordered(_dh_score_worker, tasks)
            ):
                if result is None:
                    skipped += 1
                else:
                    evaluated += 1
                    if result["weighted"] > best_weighted:
                        best_weighted = result["weighted"]
                        best_combo = copy.deepcopy(combo)
                        best_result = result
                if (i + 1) % 10 == 0:
                    elapsed = time.time() - start
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    eta = (total_combos - i - 1) / rate if rate > 0 else 0
                    print(f"    ... {i + 1}/{total_combos}  eval={evaluated} skip={skipped}"
                          f"  best_w={best_weighted:.0f}"
                          f"  ({best_result.get('slip_wins', 0)} wins)"
                          f"  {elapsed:.0f}s elapsed  ETA {eta:.0f}s", flush=True)
    else:
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
                sweep_seeds=_sweep_seeds,
                sweep_top_k=_sweep_top_k,
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


# ── 3-stage per-category search ──────────────────────────────────────
def train(
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_workers: int = 1,
    hard_only: int = 0,
    hard_min_wins: int = 1,
    resume_winners: dict | None = None,
    sweep_seeds: list | None = None,
    sweep_top_k: int | None = None,
) -> dict:
    _seeds = sweep_seeds if sweep_seeds is not None else SEEDS
    _top_k = sweep_top_k if sweep_top_k is not None else TOP_K
    results: dict[str, dict[str, Any]] = {}
    total_start = time.time()
    structural_winner: dict[str, Any] | None = None  # warm-start for 4/5-leg

    for cat_name, n_legs, sort_mode in CATEGORIES:
        cat_start = time.time()
        print(f"\n  === {cat_name} ===")
        sorted_data = sort_dates_by_difficulty(data, base_cfg, n_legs)

        # Optionally trim to N hardest dates for sweep, re-verify on full corpus
        sweep_data = sorted_data
        if hard_only > 0:
            hard_dates = [e for e in sorted_data if e[3] <= hard_min_wins][:hard_only]
            if hard_dates:
                sweep_data = hard_dates
                print(f"  hard-only: sweeping on {len(sweep_data)} hardest dates "
                      f"(re-verify on all {len(sorted_data)})")

        # S1: structural — resume / warm-start for 4/5-leg / full grid for 3-leg
        _resume_combo = (resume_winners or {}).get(n_legs)
        if _resume_combo is not None:
            print(f"  S1: RESUMED from prior results (n_legs={n_legs})")
            s1_combo = copy.deepcopy(_resume_combo)
            s1_result_raw = score_config(s1_combo, base_cfg, sweep_data, n_legs, sort_mode,
                                          sweep_seeds=_seeds, sweep_top_k=_top_k)
            s1_result = s1_result_raw or {"weighted": 0, "slip_wins": 0, "legs_hit": 0, "legs_matched": 0, "leg_rate": 0}
            _print_combo(s1_combo)
        elif structural_winner is not None and n_legs > 3:
            s1_grid_size = len(build_s1_grid())
            print(f"  S1: WARM-START from 3-leg winner (skipped {s1_grid_size} combos)")
            s1_combo = copy.deepcopy(structural_winner)
            s1_result_raw = score_config(s1_combo, base_cfg, sweep_data, n_legs, sort_mode,
                                          sweep_seeds=_seeds, sweep_top_k=_top_k)
            s1_result = s1_result_raw or {"weighted": 0, "slip_wins": 0, "legs_hit": 0, "legs_matched": 0, "leg_rate": 0}
            _print_combo(s1_combo)
        else:
            s1_grid = build_s1_grid()
            print(f"  S1: structural+filters ({len(s1_grid)} combos, {len(_seeds)} seeds, TOP_K={_top_k})")
            s1_combo, s1_result = _run_grid(s1_grid, base_cfg, sweep_data, n_legs, sort_mode, "S1",
                                             n_workers=n_workers, sweep_seeds=_seeds, sweep_top_k=_top_k)
            _print_combo(s1_combo)

        # S2: beam/pool/per_tier exploration
        s2_grid = build_s2_grid(n_legs, s1_combo)
        print(f"  S2: exploration ({len(s2_grid)} combos)")
        s2_combo, s2_result = _run_grid(s2_grid, base_cfg, sweep_data, n_legs, sort_mode, "S2",
                                         n_workers=n_workers, sweep_seeds=_seeds, sweep_top_k=_top_k)
        _print_combo(s2_combo)

        s12_best = (
            (s2_combo, s2_result)
            if s2_result.get("weighted", 0) >= s1_result.get("weighted", 0)
            else (s1_combo, s1_result)
        )

        # S3: fine-tune around S1/S2 winner (all seeds, full corpus)
        s3_grid = build_s3_grid(n_legs, s12_best[0])
        print(f"  S3: fine-tune ({len(s3_grid)} combos, {len(SEEDS)} seeds, full corpus)")
        s3_combo, s3_result = _run_grid(s3_grid, base_cfg, sorted_data, n_legs, sort_mode, "S3",
                                         n_workers=n_workers, sweep_seeds=SEEDS, sweep_top_k=TOP_K)
        _print_combo(s3_combo)

        best = (
            (s3_combo, s3_result)
            if s3_result.get("weighted", 0) >= s12_best[1].get("weighted", 0)
            else s12_best
        )

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

        # Save 3-leg structural winner for warm-starting 4/5-leg
        if n_legs == 3 and structural_winner is None:
            structural_winner = copy.deepcopy(best[0])
            print(f"  -> Saved 3-leg structural winner for warm-start")

    total_elapsed = time.time() - total_start
    print(f"\n  Total elapsed: {total_elapsed:.0f}s ({total_elapsed / 3600:.1f}h)")
    return results


# ── main ─────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    mp.freeze_support()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=N_WORKERS,
                    help=f"Parallel workers (default: {N_WORKERS}, 1=serial)")
    ap.add_argument("--hard-only", type=int, default=0, metavar="N",
                    help="Sweep on N hardest dates only, re-verify winner on full corpus")
    ap.add_argument("--hard-min-wins", type=int, default=1, metavar="W",
                    help="When --hard-only is set, skip dates with fewer than W baseline wins (default: 1)")
    ap.add_argument("--fast", action="store_true",
                    help="Fast mode: 1 seed + top-2 during sweep (full seeds/top-k for final verify)")
    ap.add_argument("--resume", type=str, default=None, metavar="FILE",
                    help="Resume from a prior results YAML — skip S1 for already-completed leg counts")
    args = ap.parse_args()
    sweep_seeds = SEEDS[:1] if args.fast else SEEDS
    sweep_top_k = 2 if args.fast else TOP_K

    resume_winners: dict | None = None
    if args.resume:
        import yaml as _yaml
        try:
            with open(args.resume) as _f:
                _prior = _yaml.safe_load(_f)
            resume_winners = {}
            for _cat, _info in _prior.items():
                if _cat.startswith("_") or not isinstance(_info, dict):
                    continue
                _n = int(_cat.split("-")[0])
                resume_winners[_n] = _info.get("overrides", {})
            print(f"  Resumed from {args.resume}: {list(resume_winners.keys())} leg counts")
        except Exception as _e:
            print(f"  WARNING: could not parse resume file: {_e}")
            resume_winners = None

    print("DemonHunter Trainer v4")
    print("=" * 50)
    print(f"  Seeds: {sweep_seeds}  Top-K: {sweep_top_k}  Workers: {args.workers}  (cores: {os.cpu_count()})")
    print(f"  Hard-only: {args.hard_only or 'all'}  Hard-min-wins: {args.hard_min_wins}  Fast: {args.fast}")
    print(f"  MIN_DATES_BEFORE_PRUNE: {MIN_DATES_BEFORE_PRUNE}")

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

    results = train(base_cfg, data, n_workers=args.workers,
                    hard_only=args.hard_only, hard_min_wins=args.hard_min_wins,
                    resume_winners=resume_winners,
                    sweep_seeds=sweep_seeds, sweep_top_k=sweep_top_k)

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

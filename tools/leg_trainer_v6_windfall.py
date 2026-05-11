#!/usr/bin/env python
"""
Leg Selection Trainer v6 — Windfall Slips (probability-sorted)
===============================================================
Optimizes params for Windfall family slips: GOBLIN+STANDARD+DEMON mix,
probability-sorted (sort_mode='hit'), using build_windfall_slips() to match
production exactly (correct mixes, payout tables, mix_ok_fn, per_tier=400).

Windfall-specific: min_edge and exclude_stat_directions are stripped before
each builder call — Windfall never uses them (they starve DEMON-tier legs).
S1 grid therefore skips exclude/edge sweeps and focuses on beam, penalty,
min_leg_prob, and stat_family settings.

Grid lessons (from prior HIT training):
  - All improvement from beam/pool tuning (S2/S3), not structural S1
  - Strategy: SMALL S1, LARGE S2/S3
  - min_edge=0 always wins for Windfall (DEMON legs have no edge signal)
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
from Atlas.core.slip_builders import build_windfall_slips
from Atlas.stages.optimize.build_slips_today import _cfg_for_n_legs

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

# Production Windfall mixes (GOBLIN+STANDARD+DEMON)
# These are enforced inside build_windfall_slips(); listed here for reference.
# 3-leg: {G:1,S:1,D:1}  4-leg: {G:1,S:2,D:1}  5-leg: {G:2,S:2,D:1}
CATEGORIES = [
    ("3-leg WINDFALL", 3, "hit"),
    ("4-leg WINDFALL", 4, "hit"),
    ("5-leg WINDFALL", 5, "hit"),
]

SEEDS = [42, 137, 9999, 2026, 777]
TOP_K = 5
SLIP_WIN_WEIGHT = 10
N_WORKERS = max(1, (os.cpu_count() or 1) - 1)

# v18 corpus hit rates (low-performers)
WORST_SD_COMBOS = [
    "REB_over", "FG3M_over", "AST_over", "RA_over",
    "PR_over", "PA_over", "PRA_over",
]


def _strip_windfall_cfg(cfg: dict) -> dict:
    """Strip keys that Windfall ignores at production runtime.
    Mirrors _windfall_cfg() in build_slips_today.py.
    """
    out = dict(cfg)
    sb = dict(out.get("slip_build") or {})
    sb.pop("exclude_stat_directions", None)
    sb.pop("min_edge", None)
    out["slip_build"] = sb
    return out


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
    sort_mode: str,
) -> list[tuple[str, pd.DataFrame, dict]]:
    wins_per_date: list[tuple[int, int]] = []
    resolved_cfg, _ = _cfg_for_n_legs(base_cfg, n_legs, 10, sort_mode)
    for idx, (date, scored_df, truth) in enumerate(data):
        total_wins = 0
        for seed in SEEDS[:2]:
            try:
                windfall_cfg = _strip_windfall_cfg(resolved_cfg)
                slips = build_windfall_slips(
                    scored_df, n_legs=n_legs, top_n=TOP_K,
                    seed=seed, sort_mode=sort_mode,
                    pricing_engine="atlas", cfg=windfall_cfg,
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
        remaining = len(data) - idx
        max_possible_future_wins = remaining * len(SEEDS) * TOP_K
        current_weighted = total_slip_wins * SLIP_WIN_WEIGHT + total_legs_hit
        best_possible = current_weighted + max_possible_future_wins * SLIP_WIN_WEIGHT
        if best_weighted >= 0 and best_possible <= best_weighted:
            return None
        total_dates += 1
        for seed in SEEDS:
            try:
                windfall_cfg = _strip_windfall_cfg(resolved_cfg)
                slips = build_windfall_slips(
                    scored_df, n_legs=n_legs, top_n=TOP_K,
                    seed=seed, sort_mode=sort_mode,
                    pricing_engine="atlas", cfg=windfall_cfg,
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


# ── parallel worker functions ────────────────────────────────────
_W_DATA = None


def _worker_init(data_pickle_path):
    """Each worker loads shared data from pickle once at pool creation."""
    global _W_DATA
    with open(data_pickle_path, 'rb') as f:
        _W_DATA = pickle.load(f)


def _score_worker(args):
    """Worker target — runs score_config with worker-local data."""
    combo, base_cfg, n_legs, sort_mode, best_w = args
    assert _W_DATA is not None, "Worker data not initialized"
    result = score_config(combo, base_cfg, _W_DATA, n_legs, sort_mode, best_weighted=best_w)
    return (combo, result)


def _prepare_worker_data(data):
    """Serialize sorted data to temp pickle for worker processes."""
    import tempfile as _tf
    tmp = _tf.NamedTemporaryFile(delete=False, suffix='.pkl')
    pickle.dump(data, tmp)
    tmp.close()
    return tmp.name


def _cleanup_worker_data(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Windfall-tuned grids ─────────────────────────────────────────────
# Windfall strips exclude_stat_directions and min_edge at runtime — sweeping
# them wastes compute. Focus S1 on penalty structure, stat_family_mode,
# beam_window_growth, min_leg_prob, and max_direction_per_slip.
# S2/S3 beam/pool tuning is where Windfall improvement lives.
def build_structural_grid() -> list[dict[str, Any]]:
    """Windfall structural grid — no exclude/edge, focus on penalty and family mode."""
    max_under_options: list[int | None] = [None, 2]
    max_same_stat_options = [2, 3]
    penalty_options = [
        {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0},
        {"team_w": 0.05, "family_w": 0.05, "frag_w": 0.0},
        {"team_w": 0.05, "family_w": 0.05, "frag_w": 0.05},
        {"team_w": 0.10, "family_w": 0.05, "frag_w": 0.05},
    ]
    stat_family_options = ["coarse", "fine"]
    beam_window_options = [1.5, 2.0]

    grid: list[dict[str, Any]] = []
    for max_under, max_stat, penalty, sfm, bwg in itertools.product(
        max_under_options, max_same_stat_options, penalty_options,
        stat_family_options, beam_window_options,
    ):
        combo: dict[str, Any] = {}
        if max_under is not None:
            combo["max_direction_per_slip"] = {"under": max_under}
        combo["max_same_stat"] = max_stat
        combo["penalty"] = dict(penalty)
        combo["stat_family_mode"] = sfm
        combo["beam_window_growth"] = bwg
        grid.append(combo)

    random.seed(42)
    random.shuffle(grid)
    return grid


def build_refinement_grid(s1_winner: dict[str, Any]) -> list[dict[str, Any]]:
    """Minimal refinement — try min_leg_prob variants and max_players."""
    grid: list[dict[str, Any]] = []
    for mlgp in [0.57, 0.60, 0.62]:
        combo = copy.deepcopy(s1_winner)
        combo["min_leg_prob"] = mlgp
        grid.append(combo)
    combo = copy.deepcopy(s1_winner)
    combo["max_players_per_team"] = 2
    grid.append(combo)
    # Try frag_w=0.05 if not already there
    base_frag = s1_winner.get("penalty", {}).get("frag_w", 0.0)
    if base_frag < 0.05:
        combo = copy.deepcopy(s1_winner)
        pen = combo.setdefault("penalty", {})
        pen["frag_w"] = 0.05
        grid.append(combo)

    seen = set()
    unique = []
    for c in grid:
        key = str(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def build_exploration_grid(n_legs: int, winner: dict[str, Any]) -> list[dict[str, Any]]:
    """EXPANDED beam/pool grid — this is where HIT improvement lives."""
    if n_legs == 4:
        beam_options = [200, 300, 400, 500, 600]
        phase1_options = [0.05, 0.10, 0.20, 0.40]
        pool_mult_options = [200, 300, 400, 500]
    else:  # 5-leg
        beam_options = [300, 400, 500, 650, 800]
        phase1_options = [0.05, 0.10, 0.30, 0.50]
        pool_mult_options = [250, 400, 550, 700]

    grid: list[dict[str, Any]] = []
    for beam, phase1, pool_mult in itertools.product(
        beam_options, phase1_options, pool_mult_options,
    ):
        combo = copy.deepcopy(winner)
        combo["beam_width"] = beam
        combo["phase1_frac"] = phase1
        combo["target_pool_mult"] = pool_mult
        grid.append(combo)

    # phase1_pool_frac variants
    for ppf in [0.25, 0.50, 0.75]:
        for beam in beam_options[1:3]:
            combo = copy.deepcopy(winner)
            combo["beam_width"] = beam
            combo["phase1_frac"] = phase1_options[1]
            combo["target_pool_mult"] = pool_mult_options[1]
            combo["phase1_pool_frac"] = ppf
            grid.append(combo)

    random.shuffle(grid)
    return grid


def build_finetune_grid(s2_winner: dict[str, Any], n_legs: int) -> list[dict[str, Any]]:
    """EXPANDED fine-tuning — beam/pool and penalty perturbations for Windfall."""
    grid: list[dict[str, Any]] = []
    perturbations = {
        "beam_width": [-25, 25, -50, 50, -100, 100],
        "phase1_frac": [-0.02, 0.02, -0.05, 0.05],
        "target_pool_mult": [-25, 25, -50, 50, -100, 100],
    }

    for pname, deltas in perturbations.items():
        if pname in ("beam_width", "target_pool_mult"):
            base_val = int(s2_winner.get(pname, 200))
        else:
            base_val = float(s2_winner.get(pname, 0.0))
        for delta in deltas:
            new_val = base_val + delta
            if pname == "min_edge" and new_val < 0.0:
                continue
            if pname in ("beam_width", "target_pool_mult") and new_val < 50:
                continue
            if pname == "phase1_frac" and (new_val < 0.01 or new_val > 0.95):
                continue
            combo = copy.deepcopy(s2_winner)
            if pname in ("beam_width", "target_pool_mult"):
                combo[pname] = int(new_val)
            else:
                combo[pname] = round(new_val, 4)
            grid.append(combo)

    # phase1_pool_frac fine-tuning
    for ppf in [0.25, 0.50, 0.75]:
        combo = copy.deepcopy(s2_winner)
        combo["phase1_pool_frac"] = ppf
        grid.append(combo)

    pen_perturbations = {
        "team_w": [-0.02, 0.02, -0.05],
        "family_w": [-0.02, 0.02, -0.05],
        "frag_w": [-0.02, 0.02, 0.05],
    }
    base_pen = s2_winner.get("penalty", {})
    for pen_key, deltas in pen_perturbations.items():
        base_val = float(base_pen.get(pen_key, 0.0))
        for delta in deltas:
            new_val = base_val + delta
            if new_val < 0.0:
                continue
            combo = copy.deepcopy(s2_winner)
            pen = combo.setdefault("penalty", {})
            pen[pen_key] = round(new_val, 3)
            grid.append(combo)

    seen = set()
    unique = []
    for c in grid:
        key = str(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _run_grid(
    grid: list[dict[str, Any]],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    label: str,
    pool: Pool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    total_combos = len(grid)
    start = time.time()
    best_weighted: float = -1.0
    best_combo: dict[str, Any] = {}
    best_result: dict[str, Any] = {}
    skipped = 0

    if pool is not None and total_combos > 1:
        # ── parallel: process in batches, update best_weighted between batches
        batch_size = pool._processes
        for batch_start in range(0, total_combos, batch_size):
            batch = grid[batch_start:batch_start + batch_size]
            args = [(c, base_cfg, n_legs, sort_mode, best_weighted) for c in batch]
            batch_results = pool.map(_score_worker, args)
            for combo_r, result_r in batch_results:
                if result_r is None:
                    skipped += 1
                    continue
                if result_r["weighted"] > best_weighted:
                    best_weighted = result_r["weighted"]
                    best_combo = copy.deepcopy(combo_r)
                    best_result = result_r
            done = min(batch_start + len(batch), total_combos)
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total_combos - done) / rate if rate > 0 else 0
            print(f"    ... {done}/{total_combos}  ({skipped} skipped)"
                  f"  best_w={best_weighted:.0f}"
                  f"  ({best_result.get('slip_wins', 0)} wins)"
                  f"  {elapsed:.0f}s elapsed  ETA {eta:.0f}s"
                  f"  [{batch_size}w]")
    else:
        # ── serial fallback
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
    mlgp = combo.get("min_leg_prob", "off")
    mppt = combo.get("max_players_per_team", "-")
    print(f"    exclude={len(exc)} combos  max_under/slip={mdu}"
          f"  min_edge={me}  max_same_stat={ms}"
          f"  team_w={tw}  family_w={fw}  frag_w={fragw}")
    print(f"    beam={bw}  phase1={pf}  pool={pm}"
          f"  ppf={ppf}  min_leg_prob={mlgp}  max_players={mppt}")


def train(base_cfg: dict, data: list[tuple[str, pd.DataFrame, dict]], cats: list | None = None, n_workers: int = 1) -> dict:
    results: dict[str, dict[str, Any]] = {}
    total_start = time.time()
    structural_winner: dict[str, Any] | None = None  # warm-start for 4/5-leg

    for cat_name, n_legs, sort_mode in (cats or CATEGORIES):
        cat_start = time.time()
        print(f"\n  === {cat_name} ===")
        sorted_data = sort_dates_by_difficulty(data, base_cfg, n_legs, sort_mode)

        # Create worker pool for this category (shared data via temp pickle)
        pool = None
        data_path = None
        if n_workers > 1:
            data_path = _prepare_worker_data(sorted_data)
            pool = mp.Pool(n_workers, initializer=_worker_init, initargs=(data_path,))
            print(f"  Pool: {n_workers} workers")

        try:
            # S1: structural — run fully for 3-leg, warm-start for 4/5-leg
            if structural_winner is not None and n_legs > 3:
                s1_grid_size = len(build_structural_grid())
                print(f"  S1: WARM-START from 3-leg winner (skipped {s1_grid_size} combos)")
                s1_combo = copy.deepcopy(structural_winner)
                # Score the warm-start config on this leg count to get a baseline
                s1_result_raw = score_config(s1_combo, base_cfg, sorted_data, n_legs, sort_mode)
                s1_result = s1_result_raw or {"weighted": 0, "slip_wins": 0, "legs_hit": 0, "legs_matched": 0, "leg_rate": 0}
                _print_combo(s1_combo)
            else:
                s1_grid = build_structural_grid()
                print(f"  S1: structural ({len(s1_grid)} combos, {len(SEEDS)} seeds)")
                s1_combo, s1_result = _run_grid(s1_grid, base_cfg, sorted_data, n_legs, sort_mode, "S1", pool=pool)
                _print_combo(s1_combo)

            # S1b: refinement (SMALL — always run)
            s1b_grid = build_refinement_grid(s1_combo)
            print(f"  S1b: refinement ({len(s1b_grid)} combos)")
            s1b_combo, s1b_result = _run_grid(s1b_grid, base_cfg, sorted_data, n_legs, sort_mode, "S1b", pool=pool)
            _print_combo(s1b_combo)

            best = (s1b_combo, s1b_result) if s1b_result.get("weighted", 0) >= s1_result.get("weighted", 0) else (s1_combo, s1_result)

            # S2: exploration (LARGE for Windfall — this is where the value lives)
            s2_grid = build_exploration_grid(n_legs, best[0])
            print(f"  S2: exploration ({len(s2_grid)} combos)")
            s2_combo, s2_result = _run_grid(s2_grid, base_cfg, sorted_data, n_legs, sort_mode, "S2", pool=pool)
            _print_combo(s2_combo)

            best = (s2_combo, s2_result) if s2_result.get("weighted", 0) >= best[1].get("weighted", 0) else best

            # S3: fine-tuning (EXPANDED for Windfall)
            s3_grid = build_finetune_grid(best[0], n_legs)
            print(f"  S3: fine-tuning ({len(s3_grid)} combos)")
            s3_combo, s3_result = _run_grid(s3_grid, base_cfg, sorted_data, n_legs, sort_mode, "S3", pool=pool)
            _print_combo(s3_combo)

            if s3_result.get("weighted", 0) >= best[1].get("weighted", 0):
                best = (s3_combo, s3_result)
                print(f"  -> S3 improved: weighted {s3_result['weighted']}")
            else:
                print(f"  -> S2 winner held")
        finally:
            if pool:
                pool.close()
                pool.join()
            if data_path:
                _cleanup_worker_data(data_path)

        cat_elapsed = time.time() - cat_start
        print(f"  {cat_name} done in {cat_elapsed:.0f}s ({cat_elapsed / 60:.1f} min)")
        results[cat_name] = {"overrides": best[0], "result": best[1]}

        # Save 3-leg structural winner for warm-starting 4/5-leg
        if n_legs == 3 and structural_winner is None:
            structural_winner = copy.deepcopy(s1_combo)
            print(f"  -> Saved 3-leg structural winner for 4/5-leg warm-start")

    total_elapsed = time.time() - total_start
    print(f"\n  Total: {total_elapsed:.0f}s ({total_elapsed / 3600:.1f} hrs)")
    return results


def main() -> None:
    import argparse
    mp.freeze_support()
    # Force line-buffered stdout so output appears immediately when piped
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[], help="Category prefixes to skip, e.g. '3-leg'")
    ap.add_argument("--workers", type=int, default=N_WORKERS,
                    help=f"Parallel workers (default: {N_WORKERS}, 1=serial)")
    args = ap.parse_args()
    skip_set = set(s.lower() for s in args.skip)

    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(cfg_path) as f:
        base_cfg = yaml.safe_load(f)
    sb = base_cfg.get("slip_build", {})
    sb.pop("by_legs", None)
    sb.pop("by_sort_mode", None)

    cats = [c for c in CATEGORIES if not any(c[0].lower().startswith(s) for s in skip_set)]
    if skip_set:
        print(f"Skipping: {skip_set}")

    print("=" * 60)
    print("Leg Trainer v6 — WINDFALL (probability-sorted)")
    print(f"  Categories: {[c[0] for c in cats]}")
    print(f"  Seeds: {SEEDS}  Top-K: {TOP_K}  Builder: build_windfall_slips (GOBLIN+STANDARD+DEMON)")
    print(f"  Workers: {args.workers}  (cores: {os.cpu_count()})")
    print(f"  Stages: S1 (small, no exclude/edge) -> S1b (small) -> S2 (LARGE) -> S3 (EXPANDED)")
    print("=" * 60)

    data = load_all_dates()
    if not data:
        print("ERROR: No data loaded.")
        return

    print("\n--- Baseline ---")
    for cat_name, n_legs, sort_mode in cats:
        result = score_config({}, base_cfg, data, n_legs, sort_mode)
        if result:
            print(f"  {cat_name}: weighted={result['weighted']}"
                  f"  slips={result['slip_wins']}"
                  f"  legs={result['legs_hit']}/{result['legs_matched']}"
                  f" ({result['leg_rate']:.0%})")

    print("\n--- Training ---")
    results = train(base_cfg, data, cats, n_workers=args.workers)

    print("\n" + "=" * 60)
    print("WINDFALL RESULTS")
    print("=" * 60)
    out_data = {}
    for cat_name, info in results.items():
        ov = info["overrides"]
        r = info["result"]
        print(f"\n  {cat_name}: weighted={r['weighted']}  slips={r['slip_wins']}"
              f"  legs={r['legs_hit']}/{r['legs_matched']}")
        for k, v in ov.items():
            print(f"    {k}: {v}")
        out_data[cat_name] = {
            "overrides": ov,
            "weighted": r["weighted"],
            "slip_wins": r["slip_wins"],
            "dates": r["dates"],
            "legs_hit": r["legs_hit"],
            "legs_matched": r["legs_matched"],
            "leg_rate": round(r["leg_rate"], 4),
        }

    out_path = Path(__file__).resolve().parent / "leg_trainer_results_v6_windfall.yaml"
    out_data["_manifest"] = build_manifest(
        source="leg_trainer_v6_windfall", cfg=base_cfg,
        ensemble_dir=base_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    )
    print(f"  Config fingerprint: {out_data['_manifest']['config_fingerprint']}")
    with open(out_path, "w") as f:
        yaml.dump(out_data, f, default_flow_style=False, sort_keys=False)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()

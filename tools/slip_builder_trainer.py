#!/usr/bin/env python
"""
Slip Builder Trainer
====================
Assembly-only parameter sweep for System and Windfall slip families.

Sweeps:
  beam_width, phase1_frac, target_pool_mult, phase1_pool_frac,
  beam_window_growth, stat_family_mode, min_leg_prob, max_leg_prob,
  max_players_per_team, penalty (team_w / family_w / frag_w)

NOT swept here (reserved for leg trainers after playoff data):
  exclude_stat_directions, min_edge, fragility_cap,
  max_same_stat, max_direction_per_slip

Reads v18_corpus (50 dates) via corpus_manifest.json or dir scan.
Uses build_system_slips() / build_windfall_slips() for production-exact assembly.
Parallel workers share data via temp pickle (same pattern as v6 leg trainers).

Scoring: weighted = slip_wins * (SLIP_WIN_WEIGHT * n_legs) + legs_hit
  Rationale: 5-leg all-hit (10x payout) should score more than 3-leg (2.25x).

Families:
  System   3/4/5-leg EV-sorted  — build_system_slips()
  Windfall 3/4/5-leg HIT-sorted — build_windfall_slips()

Stages per category:
  S1 — structural: penalty, stat_family_mode, beam_window_growth,
                   min_leg_prob, max_leg_prob, max_players_per_team
  S2 — exploration: beam_width, phase1_frac, target_pool_mult, phase1_pool_frac
  S3 — fine-tuning: small perturbations around S2 winner
"""
from __future__ import annotations

import copy
import itertools
import json
import multiprocessing as mp
import os
import pickle
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.fingerprint import build_manifest
from Atlas.core.slip_builders import build_system_slips, build_windfall_slips
from Atlas.stages.optimize.build_slips_today import _cfg_for_n_legs

# ── corpus ───────────────────────────────────────────────────────────
BASE = Path(r"C:\Users\13142\Atlas\NBA\data\telemetry\v18_corpus")


def _load_run_dates() -> list[str]:
    manifest = BASE / "corpus_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        dates = data.get("dates", [])
        if dates:
            return dates
    if BASE.exists():
        found = sorted(
            d.name for d in BASE.iterdir()
            if d.is_dir() and d.name.isdigit() and len(d.name) == 8
        )
        if found:
            return found
    return []


RUN_DATES = _load_run_dates()

# ── categories ───────────────────────────────────────────────────────
# (name, n_legs, sort_mode, family)
CATEGORIES: list[tuple[str, int, str, str]] = [
    ("3-leg SYSTEM",   3, "ev",  "system"),
    ("4-leg SYSTEM",   4, "ev",  "system"),
    ("5-leg SYSTEM",   5, "ev",  "system"),
    ("3-leg WINDFALL", 3, "hit", "windfall"),
    ("4-leg WINDFALL", 4, "hit", "windfall"),
    ("5-leg WINDFALL", 5, "hit", "windfall"),
]

SEEDS = [42, 137, 9999, 2026, 777]
TOP_K = 5
SLIP_WIN_WEIGHT = 10          # multiplied by n_legs in weighted score
N_WORKERS = max(1, (os.cpu_count() or 1) - 1)


# ── Windfall config strip ─────────────────────────────────────────────
def _strip_windfall_cfg(cfg: dict) -> dict:
    """Strip keys Windfall ignores at production runtime."""
    out = dict(cfg)
    sb = dict(out.get("slip_build") or {})
    sb.pop("exclude_stat_directions", None)
    sb.pop("min_edge", None)
    out["slip_build"] = sb
    return out


# ── data loading ──────────────────────────────────────────────────────
# Minimal column set for the slip builder — keeps pickle small (~55 MB vs 347 MB full)
# so 7+ workers don't exhaust RAM. Derived from all df["col"] accesses in
# slip_builders.py and slip_scoring.py.  Unknown columns are silently ignored.
_BUILDER_COLS = {
    # Identity / leg string
    "player", "team", "team_abbrev", "player_team",
    "stat", "stat_type", "line", "direction", "tier", "type",
    "projection_id", "source_projection_id", "game_id", "gameId",
    # Probability chain — builder picks best available
    "p", "p_role", "p_adj", "p_for_cal", "p_cal",
    "p_cal_role", "p_adj_role", "p_close_adj", "p_close_role", "p_eff",
    # Scoring / selection
    "edge_score", "fragility", "l20_edge", "player_dir_te", "stat_family",
    "games_used", "data_health_flag", "blowout_risk",
    # Role context
    "role_ctx_outs_used", "role_ctx_outs_used_sort",
    "role_ctx_mult", "role_ctx_allocator_bonus", "role_ctx_allocator_priority",
    "allocator_score",
    # Usage / minutes
    "minutes_s", "usage_dep", "usage_dep_eff",
}


def load_all_dates() -> list[tuple[str, pd.DataFrame, dict]]:
    """Return [(date, scored_df, truth_dict), ...] for all corpus dates."""
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
        # Slim to builder-required columns only — critical for worker RAM efficiency
        keep = [c for c in scored_df.columns if c in _BUILDER_COLS]
        scored_df = scored_df[keep].copy()

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

    print(f"Loaded {len(loaded)} dates from v18_corpus")
    return loaded


# ── preflight validation ──────────────────────────────────────────────
def preflight_check(data: list[tuple[str, pd.DataFrame, dict]]) -> None:
    assert data, "No dates loaded — check BASE path"
    total_legs = sum(len(df) for _, df, _ in data)
    total_truth = sum(len(t) for _, _, t in data)
    truth_rate = total_truth / max(total_legs, 1)
    print(f"  Preflight: {len(data)} dates | {total_legs:,} legs | "
          f"{total_truth:,} truth labels ({truth_rate:.0%} match rate)")

    _, sample_df, _ = data[0]
    required_cols = {"player", "stat", "line", "direction", "tier", "p_cal"}
    missing = required_cols - set(sample_df.columns)
    if missing:
        print(f"  WARNING: scored_df missing expected columns: {missing}")

    assert len(data) >= 10, f"Too few dates ({len(data)}) — corpus likely incomplete"
    print("  Preflight: OK")


# ── slip evaluation ───────────────────────────────────────────────────
def evaluate_slip(slip_row: pd.Series, truth: dict) -> tuple[bool, int, int]:
    """Return (all_hit, matched, hit_count) by parsing the legs string."""
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


# ── builder dispatch ──────────────────────────────────────────────────
def _run_builder(
    scored_df: pd.DataFrame,
    cfg: dict,
    n_legs: int,
    sort_mode: str,
    family: str,
    seed: int,
    top_k: int,
) -> pd.DataFrame | None:
    """Dispatch to production-exact builder for the given family.

    Uses a capped max_attempts (50K) for training speed — the full 500K cap
    is unnecessary when we just need relative config ranking across 50 dates.
    """
    resolved_cfg, _ = _cfg_for_n_legs(cfg, n_legs, top_k, sort_mode)
    try:
        if family == "system":
            return build_system_slips(
                scored_df, n_legs=n_legs, top_n=top_k,
                seed=seed, sort_mode=sort_mode,
                pricing_engine="atlas", cfg=resolved_cfg,
                max_attempts=50_000,
            )
        else:  # windfall
            windfall_cfg = _strip_windfall_cfg(resolved_cfg)
            return build_windfall_slips(
                scored_df, n_legs=n_legs, top_n=top_k,
                seed=seed, sort_mode=sort_mode,
                pricing_engine="atlas", cfg=windfall_cfg,
                max_attempts=50_000,
            )
    except Exception:
        return None


# ── scoring ───────────────────────────────────────────────────────────
def score_config(
    overrides: dict[str, Any],
    base_cfg: dict,
    data: list[tuple[str, pd.DataFrame, dict]],
    n_legs: int,
    sort_mode: str,
    family: str,
    best_weighted: float = -1.0,
    seeds: list[int] | None = None,
    top_k: int | None = None,
) -> dict[str, Any] | None:
    """Score one assembly config across all dates. Returns None if early-exited."""
    _seeds = seeds if seeds is not None else SEEDS
    _top_k = top_k if top_k is not None else TOP_K
    win_weight = SLIP_WIN_WEIGHT * n_legs   # payout-proportional scaling

    cfg = copy.deepcopy(base_cfg)
    sb = cfg.setdefault("slip_build", {})
    for key, val in overrides.items():
        if key == "penalty":
            pen = sb.setdefault("penalty", {})
            pen.update(val)
        else:
            sb[key] = val

    total_slip_wins = 0
    total_dates = 0
    total_legs_matched = 0
    total_legs_hit = 0

    for idx, (date, scored_df, truth) in enumerate(data):
        # Early exit: remaining wins can't beat current best
        remaining = len(data) - idx
        current_weighted = total_slip_wins * win_weight + total_legs_hit
        best_possible = current_weighted + remaining * len(_seeds) * _top_k * win_weight
        if best_weighted >= 0 and best_possible <= best_weighted:
            return None

        total_dates += 1
        for seed in _seeds:
            slips = _run_builder(scored_df, cfg, n_legs, sort_mode, family,
                                 seed, _top_k)
            if slips is None or slips.empty:
                continue
            for rank in range(min(_top_k, len(slips))):
                all_hit, matched, hit_count = evaluate_slip(slips.iloc[rank], truth)
                if all_hit:
                    total_slip_wins += 1
                total_legs_matched += matched
                total_legs_hit += hit_count

    weighted = total_slip_wins * win_weight + total_legs_hit
    return {
        "slip_wins": total_slip_wins,
        "weighted": weighted,
        "dates": total_dates,
        "legs_hit": total_legs_hit,
        "legs_matched": total_legs_matched,
        "leg_rate": total_legs_hit / max(total_legs_matched, 1),
    }


# ── parallel workers ──────────────────────────────────────────────────
_W_DATA: list | None = None


def _worker_init(data_pickle_path: str) -> None:
    import os as _os
    _os.environ.setdefault("OMP_NUM_THREADS", "1")
    _os.environ.setdefault("MKL_NUM_THREADS", "1")
    _os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    global _W_DATA
    with open(data_pickle_path, "rb") as f:
        _W_DATA = pickle.load(f)


def _score_worker(args: tuple) -> tuple[dict, dict | None]:
    try:
        overrides, base_cfg, n_legs, sort_mode, family, seeds, top_k, date_sample = args
        data = _W_DATA if date_sample is None else _W_DATA[:date_sample]
        import sys as _sys
        print(f"[W] task start n_legs={n_legs} family={family} dates={len(data)}", flush=True, file=_sys.stderr)
        result = score_config(
            overrides, base_cfg, data, n_legs, sort_mode, family,
            best_weighted=-1.0,     # no early exit in parallel path
            seeds=seeds, top_k=top_k,
        )
        print(f"[W] task done weighted={result['weighted'] if result else None}", flush=True, file=_sys.stderr)
        return overrides, result
    except Exception as _e:
        import traceback as _tb
        print(f"[W] EXCEPTION: {_e}\n{_tb.format_exc()}", flush=True, file=_sys.stderr)
        return args[0] if args else {}, None


def _prepare_worker_data(data: list) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
    pickle.dump(data, tmp)
    tmp.close()
    return tmp.name


def _cleanup_worker_data(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ── grid runner ───────────────────────────────────────────────────────
def _run_grid(
    grid: list[dict],
    base_cfg: dict,
    data: list,
    n_legs: int,
    sort_mode: str,
    family: str,
    label: str,
    pool: mp.Pool | None = None,
    seeds: list[int] | None = None,
    top_k: int | None = None,
    date_sample: int | None = None,   # None = all dates; set for S1/S2 to speed up
) -> tuple[dict, dict]:
    """Run all combos in grid, return (best_combo, best_result)."""
    _seeds = seeds if seeds is not None else SEEDS
    _top_k = top_k if top_k is not None else TOP_K
    best_weighted = -1.0
    best_combo: dict = {}
    best_result: dict = {
        "weighted": 0, "slip_wins": 0, "legs_hit": 0,
        "legs_matched": 0, "leg_rate": 0.0,
    }
    skipped = 0
    start = time.time()

    if pool is not None:
        args_list = [
            (c, base_cfg, n_legs, sort_mode, family, _seeds, _top_k, date_sample)
            for c in grid
        ]
        sample_str = f"{date_sample} dates" if date_sample is not None else "all dates"
        print(f"    dispatching {len(args_list)} tasks to {pool._processes} workers ({sample_str})...", flush=True)
        for i, (overrides, result) in enumerate(
            pool.imap_unordered(_score_worker, args_list, chunksize=1), 1
        ):
            if i % 5 == 0:
                elapsed = time.time() - start
                eta = elapsed / i * (len(grid) - i)
                print(f"    [{label}] {i}/{len(grid)}  "
                      f"best_wins={best_result['slip_wins']}"
                      f"  [{elapsed:.0f}s  ETA {eta:.0f}s]", flush=True)
            if result is None:
                skipped += 1
                continue
            if result["weighted"] > best_weighted:
                best_weighted = result["weighted"]
                best_combo = copy.deepcopy(overrides)
                best_result = result
    else:
        for i, overrides in enumerate(grid, 1):
            if i % 20 == 0:
                elapsed = time.time() - start
                eta = elapsed / i * (len(grid) - i)
                print(f"    [{label}] {i}/{len(grid)}  "
                      f"best_wins={best_result['slip_wins']}"
                      f"  [{elapsed:.0f}s  ETA {eta:.0f}s]")
            result = score_config(
                overrides, base_cfg, data, n_legs, sort_mode, family,
                best_weighted=best_weighted,
                seeds=_seeds, top_k=_top_k,
            )
            if result is None:
                skipped += 1
                continue
            if result["weighted"] > best_weighted:
                best_weighted = result["weighted"]
                best_combo = copy.deepcopy(overrides)
                best_result = result

    elapsed = time.time() - start
    print(f"    {label} BEST: weighted={best_result['weighted']}"
          f"  slip_wins={best_result['slip_wins']}"
          f"  leg_rate={best_result['leg_rate']:.1%}"
          f"  [{elapsed:.0f}s, {skipped} early-exits]")
    return best_combo, best_result


# ── grid definitions (assembly params only) ───────────────────────────
PENALTY_OPTIONS: list[dict[str, float]] = [
    {"team_w": 0.0,  "family_w": 0.0,  "frag_w": 0.0},
    {"team_w": 0.05, "family_w": 0.05, "frag_w": 0.0},
    {"team_w": 0.05, "family_w": 0.05, "frag_w": 0.05},
    {"team_w": 0.10, "family_w": 0.05, "frag_w": 0.05},
    {"team_w": 0.10, "family_w": 0.10, "frag_w": 0.10},
]


def build_s1_grid() -> list[dict[str, Any]]:
    """S1: structural — penalty, stat_family, beam_growth, prob gates, max_players."""
    stat_family_options = ["coarse", "fine"]
    beam_growth_options = [1.5, 2.0]
    min_prob_options = [0.50, 0.52, 0.55]
    max_prob_options = [0.0, 0.75, 0.80]    # 0.0 = off (no ceiling)
    max_ppt_options: list[int | None] = [None, 2]

    grid: list[dict[str, Any]] = []
    for pen, sfm, bwg, min_p, max_p, mppt in itertools.product(
        PENALTY_OPTIONS,
        stat_family_options,
        beam_growth_options,
        min_prob_options,
        max_prob_options,
        max_ppt_options,
    ):
        combo: dict[str, Any] = {
            "penalty": dict(pen),
            "stat_family_mode": sfm,
            "beam_window_growth": bwg,
            "min_leg_prob": min_p,
        }
        if max_p > 0.0:
            combo["max_leg_prob"] = max_p
        if mppt is not None:
            combo["max_players_per_team"] = mppt
        grid.append(combo)

    random.seed(42)
    random.shuffle(grid)
    return grid


def build_s2_grid(n_legs: int, s1_winner: dict[str, Any]) -> list[dict[str, Any]]:
    """S2: beam/pool exploration — branches from S1 winner."""
    if n_legs == 3:
        beam_options = [150, 200, 300, 400]
        phase1_options = [0.05, 0.10, 0.20]
        pool_mult_options = [150, 250, 400]
    elif n_legs == 4:
        beam_options = [300, 400, 500, 600]
        phase1_options = [0.10, 0.20, 0.30, 0.40]
        pool_mult_options = [250, 400, 600]
    else:  # 5
        beam_options = [400, 500, 650, 750]
        phase1_options = [0.10, 0.25, 0.40, 0.50]
        pool_mult_options = [350, 500, 700]

    grid: list[dict[str, Any]] = []
    for beam, phase1, pool_mult in itertools.product(
        beam_options, phase1_options, pool_mult_options
    ):
        combo = copy.deepcopy(s1_winner)
        combo["beam_width"] = beam
        combo["phase1_frac"] = phase1
        combo["target_pool_mult"] = pool_mult
        grid.append(combo)

    # phase1_pool_frac variants on the midpoint combo
    mid_beam = beam_options[len(beam_options) // 2]
    mid_phase1 = phase1_options[len(phase1_options) // 2]
    mid_pool = pool_mult_options[len(pool_mult_options) // 2]
    for ppf in [0.25, 0.50, 0.75]:
        combo = copy.deepcopy(s1_winner)
        combo["beam_width"] = mid_beam
        combo["phase1_frac"] = mid_phase1
        combo["target_pool_mult"] = mid_pool
        combo["phase1_pool_frac"] = ppf
        grid.append(combo)

    random.shuffle(grid)
    return grid


def build_s3_grid(s2_winner: dict[str, Any]) -> list[dict[str, Any]]:
    """S3: fine-tuning — small perturbations around S2 winner."""
    grid: list[dict[str, Any]] = []

    int_perturbations = {"beam_width": [-50, 50], "target_pool_mult": [-50, 50]}
    float_perturbations = {"phase1_frac": [-0.05, 0.05]}
    pen_perturbations = {
        "team_w": [-0.02, 0.02], "family_w": [-0.02, 0.02], "frag_w": [-0.02, 0.02],
    }

    for pname, deltas in int_perturbations.items():
        base_val = int(s2_winner.get(pname, 200) or 200)
        for delta in deltas:
            new_val = base_val + delta
            if new_val < 50:
                continue
            combo = copy.deepcopy(s2_winner)
            combo[pname] = new_val
            grid.append(combo)

    for pname, deltas in float_perturbations.items():
        base_val = float(s2_winner.get(pname, 0.10) or 0.10)
        for delta in deltas:
            new_val = round(base_val + delta, 4)
            if new_val < 0.01 or new_val > 0.95:
                continue
            combo = copy.deepcopy(s2_winner)
            combo[pname] = new_val
            grid.append(combo)

    base_pen = s2_winner.get("penalty", {})
    for pname, deltas in pen_perturbations.items():
        base_val = float(base_pen.get(pname, 0.0))
        for delta in deltas:
            new_val = round(base_val + delta, 3)
            if new_val < 0.0 or new_val > 0.30:
                continue
            combo = copy.deepcopy(s2_winner)
            pen = combo.setdefault("penalty", {})
            pen[pname] = new_val
            grid.append(combo)

    # Deduplicate
    seen: set[str] = set()
    unique: list[dict] = []
    for c in grid:
        key = str(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


# ── print helper ──────────────────────────────────────────────────────
def _print_combo(combo: dict) -> None:
    pen = combo.get("penalty", {})
    print(f"    beam={combo.get('beam_width', '-')}  "
          f"phase1={combo.get('phase1_frac', '-')}  "
          f"pool={combo.get('target_pool_mult', '-')}  "
          f"ppf={combo.get('phase1_pool_frac', '-')}")
    print(f"    sfm={combo.get('stat_family_mode', '-')}  "
          f"bwg={combo.get('beam_window_growth', '-')}  "
          f"min_p={combo.get('min_leg_prob', 'off')}  "
          f"max_p={combo.get('max_leg_prob', 'off')}  "
          f"max_ppt={combo.get('max_players_per_team', '-')}")
    print(f"    team_w={pen.get('team_w', 0)}  "
          f"family_w={pen.get('family_w', 0)}  "
          f"frag_w={pen.get('frag_w', 0)}")


# ── trainer ───────────────────────────────────────────────────────────
def train(
    base_cfg: dict,
    data: list,
    cats: list[tuple[str, int, str, str]] | None = None,
    n_workers: int = 1,
    seeds: list[int] | None = None,
    top_k: int | None = None,
) -> dict:
    """Run S1 -> S2 -> S3 assembly sweep for each category."""
    _cats = cats if cats is not None else CATEGORIES
    results: dict[str, dict] = {}
    total_start = time.time()

    for cat_name, n_legs, sort_mode, family in _cats:
        cat_start = time.time()
        print(f"\n  === {cat_name} (family={family}, n_legs={n_legs}, sort={sort_mode}) ===")

        pool = None
        data_path = None
        if n_workers > 1:
            data_path = _prepare_worker_data(data)
            pool = mp.Pool(
                n_workers,
                initializer=_worker_init,
                initargs=(data_path,),
            )
            print(f"  Pool: {n_workers} workers  ({os.cpu_count()} cores)")

        # Stage-specific seeds: S1 uses 1 seed (structural ranking is stable),
        # S2 uses 3, S3 uses all seeds for full precision.
        # Stage-specific date samples: S1 uses 25 dates for speed (structural winners
        # are robust), S2 uses 35, S3 uses all 50 for final precision.
        _s = seeds if seeds is not None else SEEDS
        s1_seeds = _s[:1]
        s2_seeds = _s[:3]
        s3_seeds = _s
        n_dates = len(data)
        s1_sample = min(25, n_dates) if n_dates > 25 else None
        s2_sample = min(35, n_dates) if n_dates > 35 else None
        s3_sample = None  # all dates

        try:
            # S1: structural params
            s1_grid = build_s1_grid()
            s1_dates_label = f"{s1_sample or n_dates} dates"
            print(f"  S1: structural ({len(s1_grid)} combos, {len(s1_seeds)} seed, {s1_dates_label})")
            s1_combo, s1_result = _run_grid(
                s1_grid, base_cfg, data, n_legs, sort_mode, family,
                "S1", pool=pool, seeds=s1_seeds, top_k=top_k,
                date_sample=s1_sample,
            )
            _print_combo(s1_combo)

            # S2: beam/pool exploration
            s2_grid = build_s2_grid(n_legs, s1_combo)
            s2_dates_label = f"{s2_sample or n_dates} dates"
            print(f"  S2: beam/pool exploration ({len(s2_grid)} combos, {len(s2_seeds)} seeds, {s2_dates_label})")
            s2_combo, s2_result = _run_grid(
                s2_grid, base_cfg, data, n_legs, sort_mode, family,
                "S2", pool=pool, seeds=s2_seeds, top_k=top_k,
                date_sample=s2_sample,
            )
            _print_combo(s2_combo)

            best = (
                (s2_combo, s2_result)
                if s2_result["weighted"] >= s1_result["weighted"]
                else (s1_combo, s1_result)
            )

            # S3: fine-tuning on best of S1/S2 — full seeds, all dates
            s3_grid = build_s3_grid(best[0])
            print(f"  S3: fine-tuning ({len(s3_grid)} combos, {len(s3_seeds)} seeds, {n_dates} dates)")
            s3_combo, s3_result = _run_grid(
                s3_grid, base_cfg, data, n_legs, sort_mode, family,
                "S3", pool=pool, seeds=s3_seeds, top_k=top_k,
                date_sample=s3_sample,
            )
            _print_combo(s3_combo)

            if s3_result["weighted"] >= best[1]["weighted"]:
                best = (s3_combo, s3_result)
                print("  -> S3 improved")
            else:
                print("  -> S2/S1 winner held")

        finally:
            if pool:
                pool.close()
                pool.join()
            if data_path:
                _cleanup_worker_data(data_path)

        cat_elapsed = time.time() - cat_start
        print(f"\n  >>> {cat_name} FINAL: "
              f"weighted={best[1]['weighted']}  "
              f"slip_wins={best[1]['slip_wins']}  "
              f"leg_rate={best[1]['leg_rate']:.1%}  "
              f"[{cat_elapsed:.0f}s]")
        _print_combo(best[0])

        results[cat_name] = {
            "overrides": best[0],
            "family": family,
            "sort_mode": sort_mode,
            "n_legs": n_legs,
            **best[1],
        }

    total_elapsed = time.time() - total_start
    print(f"\n  Total elapsed: {total_elapsed:.0f}s ({total_elapsed / 3600:.1f}h)")
    return results


# ── YAML output helper ────────────────────────────────────────────────
def _print_yaml_overrides(
    results: dict,
    cats: list[tuple[str, int, str, str]],
) -> None:
    print("\n" + "=" * 70)
    print("  RECOMMENDED config.yaml OVERRIDES")
    print("=" * 70)
    print("\nslip_build:")
    print("  by_sort_mode:")

    for sort_label, sort_mode in [("ev", "ev"), ("hit", "hit")]:
        family_cats = [
            (c, n, sm, fam) for c, n, sm, fam in cats
            if sm == sort_mode and c in results
        ]
        if not family_cats:
            continue
        print(f"    {sort_label}:")
        print(f"      by_legs:")
        for cat_name, n_legs, _, _ in family_cats:
            r = results[cat_name]
            ov = r.get("overrides", {})
            if not ov:
                continue
            print(f'        "{n_legs}":')
            for k, v in ov.items():
                if isinstance(v, dict):
                    print(f"          {k}:")
                    for k2, v2 in v.items():
                        print(f"            {k2}: {v2}")
                elif v is not None:
                    print(f"          {k}: {v}")


# ── main ──────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    mp.freeze_support()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    ap = argparse.ArgumentParser(
        description="Slip Builder Trainer — assembly params only (v18_corpus)"
    )
    ap.add_argument(
        "--workers", type=int, default=N_WORKERS,
        help=f"Parallel workers (default: {N_WORKERS}, 1=serial)",
    )
    ap.add_argument(
        "--fast", action="store_true",
        help="Fast mode: 1 seed + top-2 for quick validation (no full sweep)",
    )
    ap.add_argument(
        "--family", choices=["system", "windfall", "both"], default="both",
        help="Which family to train (default: both)",
    )
    ap.add_argument(
        "--legs", type=int, choices=[3, 4, 5], default=None,
        help="Restrict to one leg count (default: all)",
    )
    args = ap.parse_args()

    print("Slip Builder Trainer")
    print("=" * 50)
    print(f"  Corpus:  {BASE}")
    print(f"  Dates:   {len(RUN_DATES)} available")
    print(f"  Workers: {args.workers}  Fast: {args.fast}  Family: {args.family}")

    # Load config — strip per-category overrides so we baseline from clean slate
    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(cfg_path) as f:
        base_cfg = yaml.safe_load(f)
    sb = base_cfg.get("slip_build", {})
    sb.pop("by_legs", None)
    sb.pop("by_sort_mode", None)

    # Load corpus
    data = load_all_dates()
    if not data:
        print("ERROR: No corpus data loaded — check v18_corpus path.")
        return
    preflight_check(data)

    # Apply category filters
    cats = [
        c for c in CATEGORIES
        if (args.family == "both" or c[3] == args.family)
        and (args.legs is None or c[1] == args.legs)
    ]
    print(f"  Categories: {[c[0] for c in cats]}")

    # Fast mode: reduce seeds and top_k (workers still see correct values via args)
    sweep_seeds = SEEDS[:1] if args.fast else SEEDS
    sweep_top_k = 2 if args.fast else TOP_K
    if args.fast:
        print(f"  FAST MODE: seeds={sweep_seeds}  top_k={sweep_top_k}")

    results = train(
        base_cfg, data,
        cats=cats,
        n_workers=args.workers,
        seeds=sweep_seeds,
        top_k=sweep_top_k,
    )

    # Embed manifest
    results["_manifest"] = build_manifest(
        source="slip_builder_trainer", cfg=base_cfg,
        ensemble_dir=base_cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    )
    print(f"\n  Config fingerprint: {results['_manifest']['config_fingerprint']}")

    # Summary
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    for cat_name, n_legs, sort_mode, family in cats:
        if cat_name not in results:
            continue
        r = results[cat_name]
        print(f"\n  {cat_name}:")
        print(f"    slip_wins={r['slip_wins']}  "
              f"leg_rate={r['leg_rate']:.1%}  "
              f"weighted={r['weighted']}")
        _print_combo(r.get("overrides", {}))

    _print_yaml_overrides(results, cats)

    # Save
    out_path = Path(__file__).resolve().parent / "slip_builder_trainer_results.yaml"
    with open(out_path, "w") as f:
        yaml.dump(results, f, default_flow_style=False, sort_keys=False)
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()


"""Minimal multiprocessing diagnostic for slip_builder_trainer hang.
Tests the EXACT same code path as the trainer (score_config + all 50 dates).
"""
from __future__ import annotations
import multiprocessing as mp
import os
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── worker globals ─────────────────────────────────────────────────────
_W_DATA = None

def _init(path: str) -> None:
    global _W_DATA
    print(f"    [pid={os.getpid()}] loading pickle...", flush=True)
    t0 = time.time()
    with open(path, "rb") as f:
        _W_DATA = pickle.load(f)
    print(f"    [pid={os.getpid()}] loaded {len(_W_DATA)} dates in {time.time()-t0:.1f}s", flush=True)


def _task(args):
    """Exact same code path as _score_worker in the trainer."""
    import yaml
    from pathlib import Path as P
    from tools.slip_builder_trainer import score_config

    overrides, base_cfg, n_legs, sort_mode, family, seeds, top_k = args
    result = score_config(
        overrides, base_cfg, _W_DATA, n_legs, sort_mode, family,
        best_weighted=-1.0,
        seeds=seeds, top_k=top_k,
    )
    return overrides, result


if __name__ == "__main__":
    import yaml
    from tools.slip_builder_trainer import (
        load_all_dates, build_s1_grid, _prepare_worker_data, _cleanup_worker_data
    )

    print("Loading corpus (slimmed)...")
    data = load_all_dates()
    print(f"Loaded {len(data)} dates, pickle size check...")

    path = _prepare_worker_data(data)
    pkl_size = os.path.getsize(path) / 1e6
    print(f"Pickle: {pkl_size:.1f} MB")

    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(cfg_path) as f:
        base_cfg = yaml.safe_load(f)
    base_cfg.get("slip_build", {}).pop("by_legs", None)
    base_cfg.get("slip_build", {}).pop("by_sort_mode", None)

    grid = build_s1_grid()
    args_list = [
        (c, base_cfg, 3, "ev", "system", [42], 5)
        for c in grid[:20]   # first 20 combos — enough to confirm
    ]

    for n_workers in [2, 4, 7]:
        print(f"\nTesting {n_workers} workers, {len(args_list)} tasks...")
        t0 = time.time()
        completed = 0
        with mp.Pool(n_workers, initializer=_init, initargs=(path,)) as pool:
            for overrides, result in pool.imap_unordered(_task, args_list, chunksize=1):
                completed += 1
                if completed % 5 == 0:
                    print(f"  {completed}/{len(args_list)} done  [{time.time()-t0:.0f}s]", flush=True)
        print(f"  DONE: {completed} tasks in {time.time()-t0:.1f}s")

    _cleanup_worker_data(path)
    print("\nAll worker counts passed.")

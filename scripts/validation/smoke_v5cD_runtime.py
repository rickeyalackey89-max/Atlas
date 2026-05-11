"""Smoke test: run runtime CatBoost calibrator on the resim cache and
verify it reproduces the trainer's in-sample Brier (0.162631).

This validates that the runtime applier (catboost_calibrator.py) extracts
the same features and applies the same residual formula as the trainer.
"""
from __future__ import annotations

import pathlib
import pickle
import sys

import numpy as np
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from Atlas.engine.catboost_calibrator import apply_catboost_calibrator  # noqa: E402

CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
CFG_PATH = ROOT / "config.yaml"
EXPECTED_BRIER = 0.162631
TOL = 0.001


def main() -> int:
    print("=" * 80)
    print("Runtime CatBoost calibrator smoke test")
    print("=" * 80)

    cfg = yaml.safe_load(CFG_PATH.read_text())
    cat_cfg = cfg.get("catboost_playoff_calibrator", {})
    print(f"config: kind={cat_cfg.get('kind')}, mode={cat_cfg.get('mode')}, "
          f"enabled={cat_cfg.get('enabled')}")
    print(f"model:  {cat_cfg.get('model_path')}")
    print()

    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    import pandas as pd
    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    print(f"loaded {len(cv):,} legs from cache")

    hit = cv["hit"].astype(float).to_numpy()
    p_for_cal = cv["p_for_cal"].to_numpy()
    b_baseline = float(np.mean((p_for_cal - hit) ** 2))
    print(f"baseline Brier (p_for_cal): {b_baseline:.6f}")
    print()

    # Run through runtime applier
    out = apply_catboost_calibrator(
        scored=cv, logs=pd.DataFrame(), cfg=cfg, repo_root=ROOT
    )
    p_cal = out["p_cal"].astype(float).to_numpy()
    b_after = float(np.mean((p_cal - hit) ** 2))
    delta_mb = (b_after - b_baseline) * 1000
    print()
    print(f"runtime Brier after calibration: {b_after:.6f}  ({delta_mb:+.2f} mB)")
    print(f"trainer  Brier (in-sample):      {EXPECTED_BRIER:.6f}")
    print(f"diff: {abs(b_after - EXPECTED_BRIER):.6f}")

    if abs(b_after - EXPECTED_BRIER) <= TOL:
        print()
        print("PASS -- runtime matches trainer within tolerance")
        return 0
    else:
        print()
        print(f"FAIL -- diff exceeds {TOL}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

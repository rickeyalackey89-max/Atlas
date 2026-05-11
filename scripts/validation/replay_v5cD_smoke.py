#!/usr/bin/env python
"""Run 2-date replay (5/05, 5/07) with CatBoost v5cD active.

Compares post-CatBoost Brier vs raw p_adj Brier on each slate, apples-to-
apples vs the same dates already in the resim cache.
"""
from __future__ import annotations
import sys
import pickle
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import batch_replay_backfill as brb  # type: ignore[import]

SELECTIONS = [
    ("20260505", "prizepicks_20260505_171008.json"),
    ("20260507", "prizepicks_20260507_173007.json"),
]

TAG = f"atlas_replay_v5cD_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def main() -> int:
    raw_dir = ROOT / "data" / "raw"
    for _, fn in SELECTIONS:
        if not (raw_dir / fn).exists():
            print(f"[FATAL] missing: {fn}")
            return 1

    print(f"[REPLAY] Tag: {TAG}")
    print(f"[REPLAY] Dates: {[d for d,_ in SELECTIONS]}")
    brb._write_corpus_tag(TAG)

    results = []
    for i, (date, fn) in enumerate(SELECTIONS, 1):
        raw_path = raw_dir / fn
        print(f"\n{'='*70}\n[{i}/{len(SELECTIONS)}] {date}  {fn}\n{'='*70}", flush=True)
        ok, msg = brb._replay_one(date, raw_json=raw_path, tag=TAG)
        results.append((date, ok, msg))

    # Score each replay's eval_legs
    print(f"\n{'='*70}\nBRIER COMPARISON\n{'='*70}", flush=True)
    cache = pickle.load(open(ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl", "rb"))
    cv = cache["cv"]

    rows = []
    for date, ok, _ in results:
        if not ok:
            rows.append((date, "FAIL", None, None, None, None, None))
            continue
        iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        run_dir = ROOT / "data" / "telemetry" / "replay_runs" / f"{TAG}_{date}"
        eval_csv = run_dir / "eval_legs.csv"
        scored_csv = run_dir / "scored_legs_deduped.csv"
        if not eval_csv.exists() or not scored_csv.exists():
            rows.append((date, "MISSING_CSV", None, None, None, None, None))
            continue
        ev = pd.read_csv(eval_csv)
        sc = pd.read_csv(scored_csv)
        # eval_legs has hit; merge p_cal from scored
        keys = [c for c in ["player","stat","line","direction","tier"] if c in ev.columns and c in sc.columns]
        m = ev.merge(sc[keys + ["p_cal","p_adj","p_for_cal"]].drop_duplicates(keys),
                     on=keys, how="left")
        m = m.dropna(subset=["hit","p_cal","p_adj"])
        m = m[m["hit"].isin([0,1,0.0,1.0])]
        n = len(m)
        b_padj   = brier(m["hit"].astype(float), m["p_adj"].astype(float))
        b_pcal   = brier(m["hit"].astype(float), m["p_cal"].astype(float))
        # Cache reference (same date, pre-CatBoost): p_adj baseline
        sub = cv[cv["game_date"].astype(str).str[:10] == iso]
        b_cache_padj = brier(sub["hit"].astype(float), sub["p_adj"].astype(float)) if len(sub) else None
        rows.append((date, "OK", n, b_padj, b_pcal, (b_pcal-b_padj)*1000, b_cache_padj))

    print(f"\n{'date':<10} {'status':<10} {'n':>6} {'p_adj':>10} {'p_cal':>10} {'delta_mB':>10} {'cache_p_adj':>12}")
    for date, status, n, bp, bc, d, cb in rows:
        n_s  = f"{n}" if n is not None else "-"
        bp_s = f"{bp:.6f}" if bp is not None else "-"
        bc_s = f"{bc:.6f}" if bc is not None else "-"
        d_s  = f"{d:+.2f}" if d is not None else "-"
        cb_s = f"{cb:.6f}" if cb is not None else "-"
        print(f"{date:<10} {status:<10} {n_s:>6} {bp_s:>10} {bc_s:>10} {d_s:>10} {cb_s:>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

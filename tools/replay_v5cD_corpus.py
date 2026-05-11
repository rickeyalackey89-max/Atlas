#!/usr/bin/env python
"""Full 10-date playoff corpus replay with CatBoost v5cD active.

Same plumbing as replay_v5cD_smoke.py but covers all 10 dates in the
_v1_playoff_resim_cache. Per-date Brier comparison written to a CSV
summary at the end so we can audit slate-by-slate.
"""
from __future__ import annotations
import sys
import pickle
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import batch_replay_backfill as brb  # type: ignore[import]

# Hand-picked late-afternoon snapshot per date (closest to lock without being post-tip)
SELECTIONS = [
    ("20260430", "prizepicks_20260430_181838.json"),
    ("20260501", "prizepicks_20260501_173002.json"),
    ("20260502", "prizepicks_20260502_173005.json"),
    ("20260503", "prizepicks_20260503_173004.json"),
    ("20260504", "prizepicks_20260504_173004.json"),
    ("20260505", "prizepicks_20260505_173004.json"),
    ("20260506", "prizepicks_20260506_173009.json"),
    ("20260507", "prizepicks_20260507_173007.json"),
    ("20260508", "prizepicks_20260508_173017.json"),
    ("20260509", "prizepicks_20260509_164439.json"),
]

TAG = f"atlas_replay_v5cD_corpus_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def _score_replay(date_iso: str, run_dir: Path):
    """Compute Brier on eval_legs for this replay vs. cached p_adj baseline."""
    eval_csv = run_dir / "eval_legs.csv"
    if not eval_csv.exists():
        return None
    ev = pd.read_csv(eval_csv)
    if "hit" not in ev.columns or "p_cal" not in ev.columns:
        return None
    ev = ev.dropna(subset=["hit", "p_cal"])
    if len(ev) == 0:
        return None
    p_cal_b = brier(ev["hit"].values, ev["p_cal"].values)
    p_adj_b = brier(ev["hit"].values, ev["p_adj"].values) if "p_adj" in ev.columns else None
    return {
        "date": date_iso,
        "n": len(ev),
        "brier_p_cal_v5cD": p_cal_b,
        "brier_p_adj_raw": p_adj_b,
        "delta_mB": (p_adj_b - p_cal_b) * 1000 if p_adj_b is not None else None,
    }


def main() -> int:
    raw_dir = ROOT / "data" / "raw"
    missing = [fn for _, fn in SELECTIONS if not (raw_dir / fn).exists()]
    if missing:
        print(f"[FATAL] missing raw JSONs: {missing}")
        return 1

    print(f"[REPLAY] Tag: {TAG}")
    print(f"[REPLAY] Dates: {[d for d,_ in SELECTIONS]}")
    brb._write_corpus_tag(TAG)

    results = []
    for i, (date, fn) in enumerate(SELECTIONS, 1):
        raw_path = raw_dir / fn
        print(f"\n{'='*70}\n[{i}/{len(SELECTIONS)}] {date}  {fn}\n{'='*70}", flush=True)
        t0 = datetime.now()
        ok, msg = brb._replay_one(date, raw_json=raw_path, tag=TAG)
        dt = (datetime.now() - t0).total_seconds()
        print(f"  -> ok={ok} ({dt:.1f}s)  {msg[:120] if msg else ''}", flush=True)
        results.append((date, ok, msg))

    # Score each replay's eval_legs
    print(f"\n{'='*70}\nBRIER COMPARISON\n{'='*70}", flush=True)
    rows = []
    for date, ok, _ in results:
        if not ok:
            rows.append({"date": date, "status": "FAIL"})
            continue
        iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        run_root = ROOT / "data" / "telemetry" / "replay_runs" / f"{TAG}_{date}" / "runs"
        if not run_root.exists():
            rows.append({"date": date, "status": "NO_RUN_DIR"})
            continue
        run_dirs = sorted(run_root.glob("*"))
        if not run_dirs:
            rows.append({"date": date, "status": "NO_RUN_TS"})
            continue
        scored = _score_replay(iso, run_dirs[-1])
        if scored is None:
            rows.append({"date": date, "status": "NO_EVAL"})
        else:
            scored["status"] = "OK"
            rows.append(scored)

    df = pd.DataFrame(rows)
    out_csv = ROOT / "logs" / f"replay_v5cD_corpus_{TAG}_summary.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(df.to_string(index=False))
    print(f"\n[SUMMARY] {out_csv}")
    ok_rows = df[df.get("status", "") == "OK"] if "status" in df.columns else df
    if len(ok_rows) > 0 and "delta_mB" in ok_rows.columns:
        agg = ok_rows["delta_mB"].mean()
        print(f"[AGG] mean delta vs raw p_adj = {agg:+.2f} mB across {len(ok_rows)} dates")
    return 0


if __name__ == "__main__":
    sys.exit(main())

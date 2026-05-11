#!/usr/bin/env python
"""Replay the playoff corpus with locked kernel config (2026-05-10).

Replays specific raw JSONs per user-selected timestamps, runs eval backfill,
copies output into a fresh corpus dir.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import batch_replay_backfill as brb

# (YYYYMMDD, raw_json_filename) — picked per user rules:
#   default 4-6pm, except 5/2, 5/3, 5/9 must be before 2:30pm
SELECTIONS = [
    ("20260430", "prizepicks_20260430_170641.json"),  # 17:06
    ("20260501", "prizepicks_20260501_170034.json"),  # 17:00
    ("20260502", "prizepicks_20260502_143004.json"),  # 14:30 (cutoff)
    ("20260503", "prizepicks_20260503_143007.json"),  # 14:30 (cutoff)
    ("20260504", "prizepicks_20260504_170555.json"),  # 17:05
    ("20260505", "prizepicks_20260505_171008.json"),  # 17:10
    ("20260506", "prizepicks_20260506_173009.json"),  # 17:30
    ("20260507", "prizepicks_20260507_173007.json"),  # 17:30
    ("20260508", "prizepicks_20260508_173017.json"),  # 17:30
    ("20260509", "prizepicks_20260509_131914.json"),  # 13:19 (last before 14:30)
]

TAG = f"atlas_replay_postkernel_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def main() -> int:
    raw_dir = ROOT / "data" / "raw"
    # Pre-flight all files exist
    missing = []
    for d, fn in SELECTIONS:
        if not (raw_dir / fn).exists():
            missing.append(fn)
    if missing:
        print("[FATAL] missing raw JSONs:", missing)
        return 1

    print(f"[REPLAY] Corpus tag: {TAG}")
    print(f"[REPLAY] Output: data/telemetry/replay_runs/{TAG}_*")
    brb._write_corpus_tag(TAG)

    print(f"\n[REPLAY] {len(SELECTIONS)} dates queued:")
    for d, fn in SELECTIONS:
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        print(f"  {iso}  {fn}")

    results: list[tuple[str, bool, str]] = []
    for i, (date, fn) in enumerate(SELECTIONS, 1):
        raw_path = raw_dir / fn
        print(f"\n{'='*70}")
        print(f"[REPLAY] {i}/{len(SELECTIONS)}  {date}  {fn}")
        print(f"{'='*70}")
        ok, msg = brb._replay_one(date, raw_json=raw_path, tag=TAG)
        results.append((date, ok, msg))

    print(f"\n{'='*70}")
    print(f"[REPLAY] SUMMARY (tag={TAG})")
    print(f"{'='*70}")
    ok_count = sum(1 for _, ok, _ in results if ok)
    for d, ok, msg in results:
        s = "OK  " if ok else "FAIL"
        print(f"  {d}  [{s}]  {msg}")
    print(f"\n  {ok_count}/{len(results)} successful")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

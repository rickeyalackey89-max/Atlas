"""Build a clean resim cache from the D-drive kv2 corpus.

Merges scored_legs_deduped.csv + eval_legs.csv from each date's kernel_v2
replay dir into a single DataFrame with hit labels.

Usage:
    python tools/build_clean_cache.py              # build from D drive corpus
    python tools/build_clean_cache.py --dry-run    # show plan only
    python tools/build_clean_cache.py --out v17    # change output version tag
"""
from __future__ import annotations

import argparse
import glob
import os
import pickle
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

CORPUS_ROOT = Path(r"D:\AtlasTestMarch26\telemetry_replay_runs")
_TAG_FILE = ROOT / "data" / "telemetry" / "replay_runs" / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"
PATTERN = f"{_CORPUS_TAG}_*"

# All-Star break dates to skip
ALL_STAR_SKIP = {"20260213", "20260214", "20260215", "20260216", "20260217", "20260218"}

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--out", default="v17", help="Version tag for output cache")
parser.add_argument("--min-hit-rate", type=float, default=0.80,
                    help="Minimum hit fill rate to include a date (default 0.80)")
args = parser.parse_args()

OUTPUT = ROOT / "data" / "model" / f"_{args.out}_resim_cache.pkl"


def _find_file(base: Path, name: str) -> Path | None:
    candidates = list(base.rglob(name))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> int:
    dirs = sorted(glob.glob(str(CORPUS_ROOT / PATTERN)))
    print(f"Found {len(dirs)} corpus dirs")

    plan: list[dict] = []
    for d in dirs:
        m = re.search(r"_(\d{8})$", os.path.basename(d))
        if not m:
            continue
        date_str = m.group(1)
        if date_str in ALL_STAR_SKIP:
            continue

        scored = _find_file(Path(d), "scored_legs_deduped.csv")
        evalf = _find_file(Path(d), "eval_legs.csv")
        if not scored or not evalf:
            print(f"  SKIP {date_str}: missing scored={scored is not None} eval={evalf is not None}")
            continue

        plan.append({"date": date_str, "scored": scored, "eval": evalf})

    print(f"\nDates with both files: {len(plan)}")
    for p in plan:
        print(f"  {p['date']}")

    if args.dry_run:
        print("\n--dry-run: stopping here")
        return 0

    # Load and merge
    frames = []
    stats = []
    for p in plan:
        scored = pd.read_csv(p["scored"], low_memory=False)
        evalf = pd.read_csv(p["eval"], low_memory=False)

        # Merge hit from eval into scored
        if "hit" in evalf.columns:
            # Match on player + stat + line + direction (robust key)
            merge_keys = []
            for k in ["player", "stat", "line", "direction"]:
                if k in scored.columns and k in evalf.columns:
                    merge_keys.append(k)

            if merge_keys and "hit" not in scored.columns:
                hit_map = evalf[merge_keys + ["hit"]].drop_duplicates(subset=merge_keys)
                scored = scored.merge(hit_map, on=merge_keys, how="left")
            elif "hit" in scored.columns:
                pass  # already has hit
            else:
                # Fallback: take hit from eval by index alignment
                if len(evalf) == len(scored):
                    scored["hit"] = evalf["hit"].values
                else:
                    print(f"  WARN {p['date']}: cannot align hit — scored={len(scored)} eval={len(evalf)}")

        if "hit" not in scored.columns:
            print(f"  SKIP {p['date']}: no hit column after merge")
            continue

        hit_fill = scored["hit"].notna().mean()
        n_legs = len(scored)
        hit_rate = scored["hit"].mean() if hit_fill > 0 else 0

        if hit_fill < args.min_hit_rate:
            print(f"  SKIP {p['date']}: hit fill {hit_fill:.1%} < {args.min_hit_rate:.0%}")
            continue

        scored["game_date"] = p["date"][:4] + "-" + p["date"][4:6] + "-" + p["date"][6:8]
        frames.append(scored)
        stats.append({"date": p["date"], "legs": n_legs, "hit_fill": hit_fill, "hit_rate": hit_rate})
        print(f"  OK {p['date']}: {n_legs} legs, hit fill {hit_fill:.1%}, hit rate {hit_rate:.3f}")

    if not frames:
        print("ERROR: No usable dates")
        return 1

    cv = pd.concat(frames, ignore_index=True)

    # Compute raw Brier from MC kernel probability
    p_col = "p" if "p" in cv.columns else "p_new"
    valid = cv.dropna(subset=[p_col, "hit"])
    raw_brier = float(((valid[p_col] - valid["hit"]) ** 2).mean())

    dates = sorted(cv["game_date"].astype(str).str[:10].unique())

    # Read current config for snapshot
    config_path = ROOT / "config.yaml"
    config_snapshot = {}
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        blowout = cfg.get("blowout", {})
        config_snapshot = {
            "spread_sd": blowout.get("spread_sd"),
            "star_minute_drop": blowout.get("star_minute_drop"),
            "role_minute_drop": blowout.get("role_minute_drop"),
            "starter_minute_drop": blowout.get("rotation_tiers", {}).get("starter_minute_drop"),
        }

    cache = {
        "version": args.out,
        "cv": cv,
        "dates": dates,
        "raw_brier": raw_brier,
        "config_snapshot": config_snapshot,
        "capture_keys": list(cv.columns),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"\n=== Cache Built ===")
    print(f"Version: {args.out}")
    print(f"Dates: {len(dates)}")
    print(f"Legs: {len(cv)}")
    print(f"Raw Brier: {raw_brier:.6f}")
    print(f"Output: {OUTPUT}")
    print(f"\nPer-date stats:")
    for s in stats:
        print(f"  {s['date']}: {s['legs']} legs, hit {s['hit_fill']:.1%}, rate {s['hit_rate']:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

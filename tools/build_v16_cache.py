"""Build v16 resim cache from the C-drive replay corpus.

Merges scored_legs_deduped.csv + eval_legs.csv (for `hit`) from each date's
replay output into a single DataFrame, saved as _v16_resim_cache.pkl.

Skips All-Star break dates (Feb 13-18).

Usage:
    python tools/build_v16_cache.py              # build from default corpus dirs
    python tools/build_v16_cache.py --dry-run    # show plan only
    python tools/build_v16_cache.py --min-hit-rate 0.8  # require 80% hit coverage
"""
from __future__ import annotations

import argparse
import glob
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
from Atlas.core.fingerprint import build_manifest, config_fingerprint

# All replay data lives on C drive in the workspace
REPLAY_RUNS = ROOT / "data" / "telemetry" / "replay_runs"

CACHE_DST = ROOT / "data" / "model" / "_v16_resim_cache.pkl"

# v16 kernel marker columns — must ALL be present to confirm v16 kernel output
V16_MARKERS = {"blowout_base_min_for_curve", "blowout_minute_delta", "role_ctx_damp_applied"}

# All-Star break dates to skip
ALL_STAR_SKIP = {"20260213", "20260214", "20260215", "20260216", "20260217", "20260218"}


def _find_latest_scored(scenario_dir: Path) -> Path | None:
    """Find the most recent scored_legs_deduped.csv in a scenario dir (by mtime)."""
    candidates = list(scenario_dir.rglob("scored_legs_deduped.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _find_latest_eval(scenario_dir: Path) -> Path | None:
    """Find the most recent eval_legs.csv in a scenario dir (by mtime)."""
    candidates = list(scenario_dir.rglob("eval_legs.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


_TAG_FILE = REPLAY_RUNS / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"


def find_all_dates(tag: str = _CORPUS_TAG) -> list[tuple[str, Path, Path]]:
    """Find all replay dates with both scored_legs and eval_legs.
    Prefers scored_legs and eval_legs from the same run directory.
    Returns (date_str, scored_path, eval_path) tuples."""
    results = []
    seen_dates = set()

    # Search C-drive replay_runs only
    for base in [REPLAY_RUNS]:
        if not base.exists():
            continue
        for d in sorted(base.glob(f"{tag}_*")):
            m = re.search(r"(\d{8})$", d.name)
            if not m:
                continue
            date = m.group(1)
            if date in seen_dates:
                continue
            if date in ALL_STAR_SKIP:
                continue

            # Find all scored_legs, prefer newest by mtime
            scored_candidates = list(d.rglob("scored_legs_deduped.csv"))
            if not scored_candidates:
                continue

            # Sort by mtime descending, try to find co-located eval_legs
            scored_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            best_scored = None
            best_eval = None
            for scored in scored_candidates:
                co_eval = scored.parent / "eval_legs.csv"
                if co_eval.is_file() and co_eval.stat().st_size > 100:
                    best_scored = scored
                    best_eval = co_eval
                    break

            # Fallback: newest scored + any eval from the scenario dir
            if not best_scored:
                best_scored = scored_candidates[0]
                eval_f = _find_latest_eval(d)
                if eval_f:
                    best_eval = eval_f

            if best_scored and best_eval:
                seen_dates.add(date)
                results.append((date, best_scored, best_eval))

    results.sort(key=lambda x: x[0])
    return results


def load_and_merge_date(date: str, scored_path: Path, eval_path: Path,
                         min_hit_rate: float = 0.5) -> pd.DataFrame | None:
    """Load scored_legs + eval_legs, merge hit column, validate."""
    try:
        scored = pd.read_csv(scored_path, low_memory=False)
        eval_df = pd.read_csv(eval_path, low_memory=False)
    except Exception as e:
        print(f"  [{date}] Read error: {e}")
        return None

    if scored.empty:
        print(f"  [{date}] Empty scored_legs")
        return None

    # Require v16 kernel markers
    scored_cols = set(scored.columns)
    missing_markers = V16_MARKERS - scored_cols
    if missing_markers:
        print(f"  [{date}] SKIP — missing v16 markers: {missing_markers}")
        return None

    # Check for p_cal (valid replay)
    if "p_cal" in scored.columns:
        pct_nan = scored["p_cal"].isna().mean()
        if pct_nan > 0.5:
            print(f"  [{date}] p_cal {pct_nan*100:.0f}% NaN — bad replay")
            return None

    # Merge hit from eval_legs
    if "hit" in eval_df.columns and eval_df["hit"].notna().any():
        # Merge on player + stat + line + direction
        merge_cols = ["player", "stat", "line", "direction"]
        available = [c for c in merge_cols if c in scored.columns and c in eval_df.columns]
        if available:
            eval_sub = eval_df[available + ["hit"]].copy()
            eval_sub = eval_sub.drop_duplicates(subset=available, keep="last")
            if "hit" in scored.columns:
                scored = scored.drop(columns=["hit"])
            scored = scored.merge(eval_sub, on=available, how="left")

    if "hit" not in scored.columns or scored["hit"].isna().all():
        print(f"  [{date}] No hit data after merge")
        return None

    hit_coverage = scored["hit"].notna().mean()
    if hit_coverage < min_hit_rate:
        print(f"  [{date}] Low hit coverage: {hit_coverage*100:.1f}% (min {min_hit_rate*100:.0f}%)")
        return None

    # Column mapping: scored_legs → trainer expectations
    # p → p_new (raw MC kernel probability)
    if "p" in scored.columns and "p_new" not in scored.columns:
        scored["p_new"] = scored["p"]

    # stat → stat_u
    if "stat" in scored.columns and "stat_u" not in scored.columns:
        scored["stat_u"] = scored["stat"].astype(str).str.upper().str.strip()

    # home → is_home
    if "home" in scored.columns and "is_home" not in scored.columns:
        scored["is_home"] = scored["home"].astype(float).fillna(0.0)
    elif "is_home" not in scored.columns:
        scored["is_home"] = 0.0

    # Ensure game_date is set correctly (use corpus date, not execution date)
    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    scored["game_date"] = iso_date

    n_hit = scored["hit"].notna().sum()
    n_role = (scored.get("role_ctx_outs_used", pd.Series([0])) > 0).sum()
    print(f"  [{date}] OK: {len(scored)} legs, {n_hit} with hit ({hit_coverage*100:.1f}%), "
          f"{n_role} role_ctx active")

    return scored


def main() -> int:
    ap = argparse.ArgumentParser(description="Build v16 resim cache from C-drive replay corpus")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-hit-rate", type=float, default=0.5,
                    help="Min fraction of legs with hit labels (default: 0.5)")
    ap.add_argument("--corpus-tag", default=DEFAULT_CORPUS_TAG,
                    help=f"Folder prefix to scan for replay output (default: {DEFAULT_CORPUS_TAG})")
    args = ap.parse_args()

    tag = args.corpus_tag
    print(f"Scanning for replay dates (tag={tag})...")
    all_dates = find_all_dates(tag=tag)
    print(f"Found {len(all_dates)} dates with scored_legs + eval_legs\n")

    if args.dry_run:
        for date, scored, eval_f in all_dates:
            print(f"  {date}: {scored}")
        return 0

    # Load and merge all dates
    frames = []
    for date, scored_path, eval_path in all_dates:
        df = load_and_merge_date(date, scored_path, eval_path,
                                  min_hit_rate=args.min_hit_rate)
        if df is not None:
            frames.append(df)

    if not frames:
        print("ERROR: No valid dates found!")
        return 1

    print(f"\nMerging {len(frames)} dates...")
    cv = pd.concat(frames, ignore_index=True)

    # Filter to rows with hit labels only
    has_hit = cv["hit"].notna()
    print(f"Total: {len(cv)} legs, {has_hit.sum()} with hit labels")
    cv = cv[has_hit].reset_index(drop=True)

    # Compute basic stats
    dates = sorted(cv["game_date"].unique().tolist())
    raw_brier = float(np.mean((cv["p_new"].values - cv["hit"].values) ** 2))
    role_active = (cv.get("role_ctx_outs_used", pd.Series([0]*len(cv))) > 0).sum()

    print(f"\nv16 cache summary:")
    print(f"  Legs: {len(cv)}")
    print(f"  Dates: {len(dates)}")
    print(f"  Raw Brier (p_new): {raw_brier:.6f}")
    print(f"  Hit rate: {cv['hit'].mean()*100:.2f}%")
    print(f"  Role ctx active: {role_active} ({role_active/len(cv)*100:.1f}%)")
    print(f"  Date range: {dates[0]} to {dates[-1]}")

    # Load current config for snapshot + fingerprint
    cfg_path = ROOT / "config.yaml"
    config_snapshot = {}
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        blow = cfg.get("blowout", {})
        config_snapshot = {
            "spread_sd": blow.get("spread_sd"),
            "star_minute_drop": blow.get("star_minute_drop"),
            "role_minute_drop": blow.get("role_minute_drop"),
            "starter_minute_drop": blow.get("rotation_tiers", {}).get("starter_minute_drop"),
            "share_matrix_rebuilt_per_replay": True,
        }

    # Check run_manifest.json fingerprint consistency across replay dirs
    import json as _json
    fingerprints: dict[str, list[str]] = {}
    for date, scored_path, eval_path in all_dates:
        manifest_path = scored_path.parent / "run_manifest.json"
        if manifest_path.exists():
            try:
                m = _json.loads(manifest_path.read_text(encoding="utf-8"))
                fp = m.get("config_fingerprint", "unknown")
                fingerprints.setdefault(fp, []).append(date)
            except Exception:
                fingerprints.setdefault("unreadable", []).append(date)
        else:
            fingerprints.setdefault("missing", []).append(date)

    print(f"\n  Config fingerprint consistency check:")
    for fp, fp_dates in sorted(fingerprints.items()):
        print(f"    {fp}: {len(fp_dates)} dates ({fp_dates[0]}..{fp_dates[-1]})")
    current_fp = config_fingerprint(cfg)
    print(f"    Current config fingerprint: {current_fp}")

    real_fps = {k for k in fingerprints if k not in ("missing", "unreadable")}
    if len(real_fps) > 1:
        print(f"\n  WARNING: Mixed config fingerprints detected across replay dates!")
        print(f"  This cache will contain data from {len(real_fps)} different configs.")
        print(f"  Consider re-replaying all dates with the same config.")
    elif real_fps and current_fp not in real_fps:
        print(f"\n  WARNING: Replay fingerprint(s) {real_fps} != current config {current_fp}")
        print(f"  The cache data was produced by a different config than what's active now.")

    cache = {
        "cv": cv,
        "dates": dates,
        "raw_brier": raw_brier,
        "version": "v16",
        "config_snapshot": config_snapshot,
        "config_fingerprint": current_fp,
        "fingerprint_consistency": {k: len(v) for k, v in fingerprints.items()},
        "_manifest": build_manifest(
            source="build_v16_cache", cfg=cfg,
            ensemble_dir=cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
        ),
        "capture_keys": list(cv.columns),
        "um": (cv["direction"].astype(str).str.upper() == "UNDER").values,
    }

    # Save local first (C drive)
    CACHE_DST.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_DST, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = CACHE_DST.stat().st_size / (1024 * 1024)
    print(f"\nSaved: {CACHE_DST} ({size_mb:.1f} MB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

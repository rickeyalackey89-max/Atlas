"""Build resim cache + trainer corpus from replay runs.

Pipeline:
  1. Scan replay_runs for dates with scored_legs_deduped.csv + eval_legs.csv
  2. Load, validate kernel markers, merge hit labels
  3. Emit per-date quality diagnostics (stat splits, OVER/UNDER, role ctx)
  4. Save _v{VERSION}_resim_cache.pkl for GBM trainer
  5. Export flat corpus dir for leg/builder trainers
  6. Write corpus_manifest.json with date list + stats
  7. Show expansion candidates (raw JSONs with no replay)

Usage:
    python tools/build_resim_cache.py --version v17            # full build
    python tools/build_resim_cache.py --version v17 --dry-run  # plan only
    python tools/build_resim_cache.py --version v17 --force    # overwrite
    python tools/build_resim_cache.py --version v17 --export-corpus
    python tools/build_resim_cache.py --version v17 --force --export-corpus
"""
from __future__ import annotations

import argparse
import datetime as dt
import json as _json
import pickle
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from Atlas.core.fingerprint import build_manifest, config_fingerprint

REPLAY_RUNS = ROOT / "data" / "telemetry" / "replay_runs"
LIVE_RUNS = ROOT / "data" / "telemetry" / "live_runs"
RAW_DIR = ROOT / "data" / "raw"
CORPUS_OUT = ROOT / "data" / "telemetry"  # corpus dirs go here

_TAG_FILE = REPLAY_RUNS / ".corpus_tag"
CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"

# All-Star break dates to skip (no games)
ALL_STAR_SKIP = frozenset({
    "20260213", "20260214", "20260215", "20260216", "20260217", "20260218",
})

# v17 kernel marker columns -- must ALL be present to confirm v17 kernel output
V17_MARKERS = frozenset({
    "blowout_base_min_for_curve",
    "blowout_minute_delta",
    "role_ctx_damp_applied",
    "under_relief_applied",
})


# ---------------------------------------------------------------------------
# Date discovery
# ---------------------------------------------------------------------------

def find_all_dates(tag: str = CORPUS_TAG,
                   skip_dates: frozenset[str] | None = None,
                   ) -> list[tuple[str, Path, Path]]:
    """Find all replay dates with both scored_legs and eval_legs.

    Returns (date_str, scored_path, eval_path) tuples sorted by date.
    """
    if skip_dates is None:
        skip_dates = ALL_STAR_SKIP

    # Also skip today's date -- games haven't finished yet
    today = dt.date.today().strftime("%Y%m%d")
    skip_dates = skip_dates | {today}

    results: list[tuple[str, Path, Path]] = []
    seen: set[str] = set()

    if not REPLAY_RUNS.exists():
        return results

    for d in sorted(REPLAY_RUNS.glob(f"{tag}_*")):
        m = re.search(r"(\d{8})$", d.name)
        if not m:
            continue
        date = m.group(1)
        if date in seen or date in skip_dates:
            continue

        # Find all scored_legs, prefer newest by mtime
        scored_candidates = sorted(
            d.rglob("scored_legs_deduped.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not scored_candidates:
            continue

        # Prefer scored + eval co-located in the same run dir
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
            all_evals = sorted(d.rglob("eval_legs.csv"), key=lambda p: p.stat().st_mtime)
            if all_evals:
                best_eval = all_evals[-1]

        if best_scored and best_eval:
            seen.add(date)
            results.append((date, best_scored, best_eval))

    results.sort(key=lambda x: x[0])
    return results


def find_live_run_dates(
        skip_dates: frozenset[str] | None = None,
) -> list[tuple[str, Path, Path]]:
    """Find dates from live runs (data/telemetry/live_runs/) that have both
    scored_legs_deduped.csv and eval_legs.csv.

    Live run dirs are named YYYYMMDD_HHMMSS or YYYYMMDD_<label>.  For each
    calendar date the latest run dir (by mtime) that carries both files is
    used.  Returns (date_str, scored_path, eval_path) sorted by date.
    """
    if skip_dates is None:
        skip_dates = ALL_STAR_SKIP

    today = dt.date.today().strftime("%Y%m%d")
    skip_dates = skip_dates | {today}

    if not LIVE_RUNS.exists():
        return []

    # Group run dirs by date (first 8 chars)
    by_date: dict[str, list[Path]] = {}
    for d in LIVE_RUNS.iterdir():
        if not d.is_dir():
            continue
        date = d.name[:8]
        if not date.isdigit() or len(date) != 8:
            continue
        if date in skip_dates:
            continue
        by_date.setdefault(date, []).append(d)

    results: list[tuple[str, Path, Path]] = []
    for date, run_dirs in sorted(by_date.items()):
        # Among run dirs for this date, prefer the latest one with BOTH files
        candidates = sorted(run_dirs, key=lambda p: p.stat().st_mtime, reverse=True)
        best_scored: Path | None = None
        best_eval: Path | None = None
        for run_dir in candidates:
            s = run_dir / "scored_legs_deduped.csv"
            e = run_dir / "eval_legs.csv"
            if s.is_file() and s.stat().st_size > 100 and e.is_file() and e.stat().st_size > 100:
                best_scored = s
                best_eval = e
                break
        if best_scored and best_eval:
            results.append((date, best_scored, best_eval))

    results.sort(key=lambda x: x[0])
    return results


def find_expansion_candidates(existing_dates: set[str], tag: str = CORPUS_TAG) -> dict[str, str]:
    """Find dates that have raw JSONs but no replay run (potential corpus expansion).

    Returns {date_str: earliest_raw_json_name}.
    """
    today = dt.date.today().strftime("%Y%m%d")

    # Dates with replay runs
    replay_dates: set[str] = set()
    if REPLAY_RUNS.exists():
        for d in REPLAY_RUNS.glob(f"{tag}_*"):
            m = re.search(r"(\d{8})$", d.name)
            if m:
                replay_dates.add(m.group(1))

    # Dates with raw JSONs
    candidates: dict[str, str] = {}
    if RAW_DIR.exists():
        for f in sorted(RAW_DIR.glob("prizepicks_*.json")):
            m = re.match(r"prizepicks_(\d{8})_", f.name)
            if not m:
                continue
            date = m.group(1)
            if date in replay_dates or date in existing_dates:
                continue
            if date in ALL_STAR_SKIP or date == today:
                continue
            if date not in candidates:
                candidates[date] = f.name

    return dict(sorted(candidates.items()))


# ---------------------------------------------------------------------------
# Per-date loading
# ---------------------------------------------------------------------------

def load_and_merge_date(date: str, scored_path: Path, eval_path: Path,
                         kernel_markers: frozenset[str] = V17_MARKERS,
                         min_hit_rate: float = 0.5,
                         ) -> pd.DataFrame | None:
    """Load scored_legs + eval_legs, merge hit column, validate."""
    try:
        scored = pd.read_csv(scored_path, low_memory=False)
        eval_df = pd.read_csv(eval_path, low_memory=False)
    except Exception as e:
        print(f"  [{date}] SKIP -- read error: {e}")
        return None

    if scored.empty:
        print(f"  [{date}] SKIP -- empty scored_legs")
        return None

    # Require kernel markers
    scored_cols = set(scored.columns)
    missing_markers = kernel_markers - scored_cols
    if missing_markers:
        print(f"  [{date}] SKIP -- missing kernel markers: {missing_markers}")
        return None

    # Check for p_cal (valid replay)
    if "p_cal" in scored.columns:
        pct_nan = scored["p_cal"].isna().mean()
        if pct_nan > 0.5:
            print(f"  [{date}] SKIP -- p_cal {pct_nan*100:.0f}% NaN (bad replay)")
            return None

    # Merge hit from eval_legs
    if "hit" in eval_df.columns and eval_df["hit"].notna().any():
        merge_cols = ["player", "stat", "line", "direction"]
        available = [c for c in merge_cols if c in scored.columns and c in eval_df.columns]
        if available:
            eval_sub = eval_df[available + ["hit"]].copy()
            eval_sub = eval_sub.drop_duplicates(subset=available, keep="last")
            if "hit" in scored.columns:
                scored = scored.drop(columns=["hit"])
            scored = scored.merge(eval_sub, on=available, how="left")

    if "hit" not in scored.columns or scored["hit"].isna().all():
        print(f"  [{date}] SKIP -- no hit data after merge")
        return None

    hit_coverage = scored["hit"].notna().mean()
    if hit_coverage < min_hit_rate:
        print(f"  [{date}] SKIP -- low hit coverage: {hit_coverage*100:.1f}% (min {min_hit_rate*100:.0f}%)")
        return None

    # Column mapping: scored_legs -> trainer expectations
    extras = {}
    if "p" in scored.columns and "p_new" not in scored.columns:
        extras["p_new"] = scored["p"].values
    if "stat" in scored.columns and "stat_u" not in scored.columns:
        extras["stat_u"] = scored["stat"].astype(str).str.upper().str.strip().values
    if "home" in scored.columns and "is_home" not in scored.columns:
        extras["is_home"] = scored["home"].astype(float).fillna(0.0).values
    elif "is_home" not in scored.columns:
        extras["is_home"] = np.zeros(len(scored))
    if extras:
        scored = scored.assign(**extras).copy()

    # Ensure game_date uses the corpus date
    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    scored["game_date"] = iso_date

    n_hit = scored["hit"].notna().sum()
    n_role = (scored.get("role_ctx_outs_used", pd.Series([0])) > 0).sum()
    print(f"  [{date}] OK: {len(scored):>5d} legs, {n_hit:>5d} hit ({hit_coverage*100:.0f}%), "
          f"{n_role:>3d} role_ctx")
    return scored


# ---------------------------------------------------------------------------
# Per-date quality diagnostics
# ---------------------------------------------------------------------------

def date_quality_row(date: str, df: pd.DataFrame) -> dict:
    """Compute quality metrics for a single date's scored legs."""
    hit = df["hit"]
    n = len(df)
    n_hit = hit.notna().sum()
    hit_rate = hit.mean() if n_hit > 0 else float("nan")

    # Direction split
    is_over = df["direction"].astype(str).str.upper() == "OVER"
    over_n = is_over.sum()
    under_n = n - over_n

    # Role context
    role_col = df.get("role_ctx_outs_used", pd.Series([0] * n))
    n_role = int((role_col > 0).sum())

    # Stat distribution
    if "stat" in df.columns:
        stat_counts = df["stat"].astype(str).str.upper().value_counts()
        top_stat = stat_counts.index[0] if len(stat_counts) > 0 else "?"
        n_stats = len(stat_counts)
    else:
        top_stat, n_stats = "?", 0

    # Brier on this date (raw p vs hit)
    p_col = "p_new" if "p_new" in df.columns else "p"
    mask = hit.notna()
    if mask.any() and p_col in df.columns:
        raw_b = float(np.mean((df.loc[mask, p_col].values - hit[mask].values) ** 2))
    else:
        raw_b = float("nan")

    return {
        "date": date,
        "legs": n,
        "hit_labels": n_hit,
        "hit_coverage": f"{n_hit/n*100:.0f}%" if n else "0%",
        "hit_rate": f"{hit_rate*100:.1f}%" if not np.isnan(hit_rate) else "?",
        "over": over_n,
        "under": under_n,
        "role_ctx": n_role,
        "n_stats": n_stats,
        "top_stat": top_stat,
        "raw_brier": raw_b,
    }


# ---------------------------------------------------------------------------
# Corpus export for leg trainers
# ---------------------------------------------------------------------------

def export_corpus_dir(version: str, date_frames: list[tuple[str, pd.DataFrame]],
                       scored_paths: dict[str, Path], eval_paths: dict[str, Path]) -> Path:
    """Export flat corpus directory: data/telemetry/{version}_corpus/{date}/
    Each date dir gets a copy of scored_legs_deduped.csv and eval_legs.csv.
    """
    corpus_dir = CORPUS_OUT / f"{version}_corpus"
    if corpus_dir.exists():
        backup = corpus_dir.with_name(f"{version}_corpus_bak_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}")
        print(f"  Backing up existing corpus: {corpus_dir.name} -> {backup.name}")
        shutil.move(str(corpus_dir), str(backup))

    corpus_dir.mkdir(parents=True, exist_ok=True)
    exported = 0
    for date, _ in date_frames:
        date_dir = corpus_dir / date
        date_dir.mkdir(exist_ok=True)
        # Copy original files (not the merged DataFrame) to preserve fidelity
        if date in scored_paths:
            shutil.copy2(str(scored_paths[date]), str(date_dir / "scored_legs_deduped.csv"))
        if date in eval_paths:
            shutil.copy2(str(eval_paths[date]), str(date_dir / "eval_legs.csv"))
        exported += 1

    print(f"  Exported {exported} dates to {corpus_dir.relative_to(ROOT)}")
    return corpus_dir


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def check_existing_cache(cache_path: Path, force: bool) -> bool:
    """Return True if OK to proceed, False to abort."""
    if not cache_path.exists():
        return True
    if force:
        print(f"\n  --force: will overwrite existing cache at {cache_path.name}")
        return True

    try:
        with open(cache_path, "rb") as f:
            old = pickle.load(f)
        old_dates = len(old.get("dates", []))
        old_legs = len(old.get("cv", []))
        old_brier = old.get("raw_brier", "?")
        print(f"\n  ERROR: Cache already exists: {cache_path.name}")
        print(f"    {old_dates} dates, {old_legs} legs, raw Brier={old_brier}")
        print(f"    Use --force to overwrite, or change --version")
        return False
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Build resim cache from replay corpus")
    ap.add_argument("--version", required=True,
                    help="Cache version label (e.g. v17, v18)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show plan only, don't build cache")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing cache file")
    ap.add_argument("--export-corpus", action="store_true",
                    help="Also export flat corpus dir for leg/builder trainers")
    ap.add_argument("--min-hit-rate", type=float, default=0.5,
                    help="Min fraction of legs with hit labels (default: 0.5)")
    ap.add_argument("--corpus-tag", default=CORPUS_TAG,
                    help=f"Folder prefix to scan (default: {CORPUS_TAG})")
    args = ap.parse_args()

    version = args.version
    cache_path = ROOT / "data" / "model" / f"_{version}_resim_cache.pkl"

    print(f"{'='*70}")
    print(f"Resim Cache Builder -- {version}")
    print(f"{'='*70}")
    print(f"  Corpus tag:  {args.corpus_tag}")
    print(f"  Output:      {cache_path.name}")
    print(f"  Min hit:     {args.min_hit_rate*100:.0f}%")
    print()

    # Safety check
    if not check_existing_cache(cache_path, args.force):
        return 1

    # Discover dates
    print(f"Scanning replay dates (tag={args.corpus_tag})...")
    replay_dates = find_all_dates(tag=args.corpus_tag)
    print(f"  Replay corpus: {len(replay_dates)} dates")

    print("Scanning live run dates (data/telemetry/live_runs/)...")
    live_dates = find_live_run_dates()
    print(f"  Live runs:     {len(live_dates)} dates")

    # Merge: replay takes priority; live fills in dates not covered by replay
    replay_date_set = {d for d, _, _ in replay_dates}
    live_fill = [(d, s, e) for d, s, e in live_dates if d not in replay_date_set]
    if live_fill:
        print(f"  Adding {len(live_fill)} new dates from live runs: {[d for d,_,_ in live_fill]}")

    all_dates = sorted(replay_dates + live_fill, key=lambda x: x[0])
    print(f"Total: {len(all_dates)} dates\n")

    if not all_dates:
        print("ERROR: No valid dates found in replay corpus or live runs!")
        return 1

    # Show expansion candidates
    existing = {d for d, _, _ in all_dates}
    expansion = find_expansion_candidates(existing, tag=args.corpus_tag)
    if expansion:
        print(f"Expansion candidates ({len(expansion)} dates with raw JSON but no replay):")
        for date, raw_name in expansion.items():
            print(f"  {date}  ({raw_name})")
        print()

    if args.dry_run:
        print("Date plan:")
        for date, scored, eval_f in all_dates:
            print(f"  {date}: {scored.relative_to(ROOT)}")
        print(f"\n[DRY RUN] No files written.")
        return 0

    # Load and merge
    print(f"Loading {len(all_dates)} dates...")
    frames: list[tuple[str, pd.DataFrame]] = []  # (date, df) for corpus export
    skipped = []
    scored_source: dict[str, Path] = {}
    eval_source: dict[str, Path] = {}
    quality_rows: list[dict] = []

    for date, scored_path, eval_path in all_dates:
        df = load_and_merge_date(date, scored_path, eval_path,
                                  min_hit_rate=args.min_hit_rate)
        if df is not None:
            frames.append((date, df))
            scored_source[date] = scored_path
            eval_source[date] = eval_path
            quality_rows.append(date_quality_row(date, df))
        else:
            skipped.append(date)

    if not frames:
        print("\nERROR: No valid dates after loading!")
        return 1

    print(f"\nMerging {len(frames)} dates ({len(skipped)} skipped)...")
    if skipped:
        print(f"  Skipped: {skipped}")

    # Quality diagnostics table
    if quality_rows:
        qdf = pd.DataFrame(quality_rows)
        print(f"\n{'='*70}")
        print("Per-Date Quality Report")
        print(f"{'='*70}")
        print(qdf.to_string(index=False, max_cols=12))
        avg_brier = qdf["raw_brier"].dropna().mean()
        print(f"\n  Mean per-date raw Brier: {avg_brier:.6f}")
        worst = qdf.loc[qdf["raw_brier"].idxmax()]
        best = qdf.loc[qdf["raw_brier"].idxmin()]
        print(f"  Best:  {best['date']} ({best['raw_brier']:.6f})")
        print(f"  Worst: {worst['date']} ({worst['raw_brier']:.6f})")

    cv = pd.concat([df for _, df in frames], ignore_index=True)
    has_hit = cv["hit"].notna()
    n_total = len(cv)
    n_hit = has_hit.sum()
    n_no_hit = n_total - n_hit
    print(f"  Total: {n_total:,} legs, {n_hit:,} with hit, {n_no_hit:,} without")

    dates = sorted(cv["game_date"].unique().tolist())
    mask = cv["hit"].notna()
    raw_brier = float(np.mean((cv.loc[mask, "p_new"].values - cv.loc[mask, "hit"].values) ** 2))
    role_active = int((cv.get("role_ctx_outs_used", pd.Series([0]*len(cv))) > 0).sum())

    # Config fingerprint
    cfg_path = ROOT / "config.yaml"
    cfg = {}
    config_snapshot = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        blow = cfg.get("blowout", {})
        config_snapshot = {
            "spread_sd": blow.get("spread_sd"),
            "star_minute_drop": blow.get("star_minute_drop"),
            "role_minute_drop": blow.get("role_minute_drop"),
            "starter_minute_drop": blow.get("rotation_tiers", {}).get("starter_minute_drop"),
        }

    current_fp = config_fingerprint(cfg)

    # Check fingerprint consistency across replay dirs
    fingerprints: dict[str, list[str]] = {}
    for date, scored_path, eval_path in all_dates:
        if date in skipped:
            continue
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

    # Summary
    print(f"\n{'='*70}")
    print(f"{version} Cache Summary")
    print(f"{'='*70}")
    print(f"  Legs:          {n_hit:,} (with hit labels)")
    print(f"  Dates:         {len(dates)}")
    print(f"  Date range:    {dates[0]} to {dates[-1]}")
    print(f"  Raw Brier:     {raw_brier:.6f}")
    print(f"  Hit rate:      {cv['hit'].mean()*100:.2f}%")
    print(f"  Role ctx:      {role_active:,} legs ({role_active/n_hit*100:.1f}%)")
    print(f"  Columns:       {len(cv.columns)}")
    print(f"  Config FP:     {current_fp}")

    print(f"\n  Fingerprint consistency:")
    for fp, fp_dates in sorted(fingerprints.items()):
        print(f"    {fp}: {len(fp_dates)} dates ({fp_dates[0]}..{fp_dates[-1]})")

    real_fps = {k for k in fingerprints if k not in ("missing", "unreadable")}
    if len(real_fps) > 1:
        print(f"\n  WARNING: Mixed config fingerprints across replay dates!")
        print(f"  Cache contains data from {len(real_fps)} different configs.")
    elif real_fps and current_fp not in real_fps:
        print(f"\n  WARNING: Replay fingerprint(s) {real_fps} != current {current_fp}")

    # Build cache dict
    cache = {
        "cv": cv,
        "dates": dates,
        "raw_brier": raw_brier,
        "version": version,
        "config_snapshot": config_snapshot,
        "config_fingerprint": current_fp,
        "fingerprint_consistency": {k: len(v) for k, v in fingerprints.items()},
        "_manifest": build_manifest(
            source="build_resim_cache",
            cfg=cfg,
            ensemble_dir=cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
        ),
        "capture_keys": list(cv.columns),
        "um": (cv["direction"].astype(str).str.upper() == "UNDER").values,
    }

    # Save
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = cache_path.stat().st_size / (1024 * 1024)
    print(f"\nSaved: {cache_path} ({size_mb:.1f} MB)")

    # Compare with previous cache if it existed
    old_path = cache_path.with_suffix(".pkl.bak")
    if old_path.exists():
        try:
            with open(old_path, "rb") as f:
                old = pickle.load(f)
            old_dates = len(old.get("dates", []))
            old_legs = len(old.get("cv", []))
            old_brier = old.get("raw_brier", 0)
            print(f"\n  vs previous cache:")
            print(f"    Dates: {old_dates} -> {len(dates)} ({len(dates)-old_dates:+d})")
            print(f"    Legs:  {old_legs:,} -> {n_hit:,} ({n_hit-old_legs:+,d})")
            print(f"    Brier: {old_brier:.6f} -> {raw_brier:.6f} ({(raw_brier-old_brier)*1000:+.3f} mB)")
        except Exception:
            pass

    # ---------------------------------------------------------------
    # Corpus export for leg/builder trainers
    # ---------------------------------------------------------------
    if args.export_corpus:
        print(f"\n{'='*70}")
        print(f"Exporting flat corpus for leg trainers...")
        print(f"{'='*70}")
        corpus_dir = export_corpus_dir(version, frames, scored_source, eval_source)

        # Write corpus manifest
        manifest = {
            "version": version,
            "created": dt.datetime.now().isoformat(),
            "corpus_dir": str(corpus_dir.relative_to(ROOT)),
            "cache_path": str(cache_path.relative_to(ROOT)),
            "dates": [d for d, _ in frames],
            "n_dates": len(frames),
            "n_legs": n_hit,
            "raw_brier": raw_brier,
            "skipped": skipped,
            "expansion_candidates": list(expansion.keys()) if expansion else [],
            "per_date": quality_rows,
        }
        manifest_path = corpus_dir / "corpus_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            _json.dump(manifest, f, indent=2, default=str)
        print(f"  Manifest: {manifest_path.relative_to(ROOT)}")

        # Print dates list in trainer-ready format
        print(f"\n  Trainer RUN_DATES ({len(frames)} dates):")
        date_list = [d for d, _ in frames]
        chunk = 8
        for i in range(0, len(date_list), chunk):
            sl = date_list[i:i+chunk]
            print(f'    {", ".join(repr(d) for d in sl)},')

    print(f"\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

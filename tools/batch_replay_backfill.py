#!/usr/bin/env python
r"""
Batch Replay Backfill — expand the leg trainer corpus
=====================================================
Replays bundles through the full Atlas pipeline and copies output
to data/telemetry/replay_runs/<corpus_tag>_<YYYYMMDD>
in the format the leg trainers expect (scored_legs_deduped.csv + eval_legs.csv).

Usage:
    python tools/batch_replay_backfill.py              # replay all missing dates
    python tools/batch_replay_backfill.py --dry-run    # show plan without executing
    python tools/batch_replay_backfill.py --dates 20260328 20260330  # specific dates only

Output structure (matches existing corpus):
    data/telemetry/replay_runs/<corpus_tag>_<YYYYMMDD>/
        <timestamp>/runs/<run_ts>/
            scored_legs_deduped.csv
            eval_legs.csv
            scored_legs.csv
            recommended_*leg*.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLES_DIRS = [
    ROOT / "data" / "bundles",
]
RAW_JSON_DIRS = [
    ROOT / "data" / "raw",
]
REPLAY_OUT = ROOT / "data" / "telemetry" / "replay_runs"
CORPUS_DIR = ROOT / "data" / "telemetry" / "replay_runs"
LOCAL_CORPUS = ROOT / "data" / "telemetry" / "v13_corpus"
ODDSAPI_HIST = ROOT / "data" / "archives" / "oddsapi" / "historical"
ODDSAPI_LIVE = ROOT / "data" / "archives" / "oddsapi"

# Map: date -> earliest bundle for that date (morning run preferred)
def _build_bundle_map() -> dict[str, Path]:
    """Return {YYYYMMDD: Path} picking the earliest non-DEAD bundle per date.
    Searches multiple bundle directories; prefers data/bundles over relics."""
    bmap: dict[str, Path] = {}
    for bdir in BUNDLES_DIRS:
        if not bdir.exists():
            continue
        for zp in sorted(bdir.glob("atlas_bundle_*.zip")):
            if "DEAD_PERIOD" in zp.name or "TEST" in zp.name:
                continue
            m = re.search(r"atlas_bundle_(\d{8})_(\d+)", zp.name)
            if m:
                d = m.group(1)
                if d not in bmap:
                    bmap[d] = zp
    return bmap


def _build_raw_json_map() -> dict[str, Path]:
    """Return {YYYYMMDD: Path} picking the earliest raw prizepicks JSON per date.
    Only includes dates NOT already covered by bundles."""
    rmap: dict[str, Path] = {}
    for rdir in RAW_JSON_DIRS:
        if not rdir.exists():
            continue
        for jp in sorted(rdir.glob("prizepicks_*.json")):
            if "seed" in jp.name or "snapshot" in jp.name:
                continue
            m = re.search(r"prizepicks_(\d{8})_(\d+)", jp.name)
            if m:
                d = m.group(1)
                if d not in rmap:
                    rmap[d] = jp
    return rmap


DEFAULT_CORPUS_PREFIX = "atlas_replay"
CORPUS_TAG_FILE = REPLAY_OUT / ".corpus_tag"


def _read_corpus_tag() -> str:
    """Read the active corpus tag from .corpus_tag file."""
    if CORPUS_TAG_FILE.exists():
        tag = CORPUS_TAG_FILE.read_text().strip()
        if tag:
            return tag
    return DEFAULT_CORPUS_PREFIX


def _write_corpus_tag(tag: str) -> None:
    """Write the active corpus tag to .corpus_tag file."""
    CORPUS_TAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_TAG_FILE.write_text(tag + "\n")


def _get_existing_corpus(tag: str) -> set[str]:
    """Dynamically detect existing corpus dates on D drive."""
    existing = set()
    for f in CORPUS_DIR.glob(f"{tag}_*"):
        m = re.search(r"(\d{8})$", f.name)
        if m:
            existing.add(m.group(1))
    # Also check C-drive replay_runs
    for f in REPLAY_OUT.glob(f"{tag}_*"):
        m = re.search(r"(\d{8})$", f.name)
        if m:
            existing.add(m.group(1))
    return existing


def _get_gamelog_dates() -> set[str]:
    """Get dates that have gamelog truth data (YYYYMMDD format)."""
    import pandas as pd
    gl_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
    if not gl_path.exists():
        return set()
    gl = pd.read_csv(gl_path, usecols=["game_date"], low_memory=False)
    gl["game_date"] = pd.to_datetime(gl["game_date"], errors="coerce")
    return set(gl.dropna()["game_date"].dt.strftime("%Y%m%d").unique())


def _find_backfill_dates(
    bundle_map: dict[str, Path],
    raw_map: dict[str, Path],
    gamelog_dates: set[str],
    only_dates: list[str] | None = None,
    force: bool = False,
    tag: str = DEFAULT_CORPUS_PREFIX,
) -> tuple[list[str], list[str]]:
    """Return (bundle_dates, raw_dates) that need backfill.
    Raw-only dates require gamelog coverage for eval truth."""
    existing = _get_existing_corpus(tag=tag) if not force else set()
    bundle_dates = sorted(d for d in bundle_map if d not in existing)
    raw_only_dates = sorted(
        d for d in raw_map
        if d not in existing
        and d not in bundle_map
        and d in gamelog_dates
    )
    if only_dates:
        s = set(only_dates)
        bundle_dates = [d for d in bundle_dates if d in s]
        raw_only_dates = [d for d in raw_only_dates if d in s]
    return bundle_dates, raw_only_dates


def _find_best_iael_archive_dir(date: str) -> Path | None:
    """Find the best IAEL archive timestamp dir for a date (YYYYMMDD).
    Returns the dir containing injury_invalidations.json + status.json."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    date_dir = ROOT / "data" / "archives" / "iael" / "2026" / iso
    if not date_dir.is_dir():
        return None
    best: Path | None = None
    for child in sorted(date_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / "injury_invalidations.json").is_file() and (child / "status.json").is_file():
            best = child  # take latest
    return best


def _find_rotowire_for_date(date: str) -> Path | None:
    """Find a rotowire_lines.json in the IAEL archive for a date (YYYYMMDD)."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    date_dir = ROOT / "data" / "archives" / "iael" / "2026" / iso
    if not date_dir.is_dir():
        return None
    for child in sorted(date_dir.iterdir(), reverse=True):
        roto = child / "rotowire_lines.json"
        if roto.is_file():
            return roto
    return None


def _find_best_normalized(date: str) -> Path | None:
    """Find a normalized IAEL snapshot for a date (YYYYMMDD)."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    norm_dir = ROOT / "data" / "output" / "injury" / "normalized"
    if not norm_dir.is_dir():
        return None
    prefix = f"{iso}_"
    candidates = sorted(f for f in norm_dir.iterdir() if f.name.startswith(prefix) and f.suffix == ".json")
    if candidates:
        return candidates[-1]
    latest = norm_dir / "latest.json"
    return latest if latest.is_file() else None


def _find_oddsapi_archive(date: str) -> Path | None:
    """Find OddsAPI historical props CSV for a date (YYYYMMDD)."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    # Check historical archive first, then live archive
    hist = ODDSAPI_HIST / f"oddsapi_props_{iso}.csv"
    if hist.is_file():
        return hist
    live = ODDSAPI_LIVE / f"oddsapi_props_{iso}.csv"
    if live.is_file():
        return live
    return None


CSV_FIELDS = [
    "source", "league", "player", "stat", "asof_ts", "projection",
    "confidence", "over_prob", "under_prob", "over_rating", "under_rating",
    "opp_rank", "notes",
]


def _build_merged_priors(date: str, out_dir: Path) -> Path | None:
    """Build a merged external_priors CSV with OddsAPI historical data for raw JSON replays.

    Returns path to the merged CSV, or None if no OddsAPI data available."""
    oa_path = _find_oddsapi_archive(date)
    if not oa_path:
        return None

    oa_rows: list[dict[str, str]] = []
    with oa_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            oa_rows.append(row)

    if not oa_rows:
        return None

    merged_path = out_dir / "external_priors_today.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in oa_rows:
            safe_row = {k: row.get(k, "") for k in CSV_FIELDS}
            writer.writerow(safe_row)

    print(f"[BACKFILL] Built external priors for {date}: {len(oa_rows)} oddsapi rows -> {merged_path}")
    return merged_path


def _replay_one(date: str, bundle_path: Path | None = None, raw_json: Path | None = None,
                tag: str = DEFAULT_CORPUS_PREFIX) -> tuple[bool, str]:
    """Replay a single bundle or raw JSON and copy output to corpus folder."""
    scenario_id = f"{tag}_{date}"

    if bundle_path:
        # Bundle path: use replay_bundle.py (handles all env setup internally)
        cmd = [
            sys.executable,
            str(ROOT / "tools" / "replay_bundle.py"),
            str(bundle_path),
            "--scenario-id", scenario_id,
        ]
        # Inject OddsAPI historical overlay if available
        oa_path = _find_oddsapi_archive(date)
        if oa_path:
            cmd.extend(["--oddsapi-overlay", str(oa_path)])
            print(f"[BACKFILL] OddsAPI overlay for {date}: {oa_path.name}")
        source_label = bundle_path.name
        env_override = None
    elif raw_json:
        # Raw JSON path: set up env vars like replay_bundle.py and call engine directly
        source_label = raw_json.name
        iael_dir = _find_best_iael_archive_dir(date)
        roto_path = _find_rotowire_for_date(date)
        norm_path = _find_best_normalized(date)
        gamelogs_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"

        # Pre-flight
        missing = []
        if not iael_dir:
            missing.append("IAEL archive dir")
        if not roto_path:
            missing.append("rotowire_lines.json")
        if not norm_path:
            missing.append("normalized snapshot")
        if not gamelogs_path.exists():
            missing.append("gamelogs")
        if missing:
            print(f"[BACKFILL] SKIPPED {date} — missing: {', '.join(missing)}")
            return False, f"missing {', '.join(missing)}"

        assert iael_dir is not None  # guarded above

        # Set up output dirs
        out_dir = REPLAY_OUT / scenario_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Derive game_date from the date string (YYYYMMDD -> YYYY-MM-DD)
        game_date_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

        env_override = os.environ.copy()
        env_override["ATLAS_AUTHORITY"] = "replay"
        env_override["ATLAS_STRICT_REPLAY"] = "1"
        env_override["ATLAS_GAME_DATE"] = game_date_iso
        env_override["ATLAS_DATA_DIR"] = str(ROOT / "data")
        env_override["ATLAS_OUT_DIR"] = str(out_dir)
        env_override["ATLAS_GAMELOGS_PATH"] = str(gamelogs_path)
        env_override["ATLAS_REPLAY_RAW"] = str(raw_json)
        env_override["ATLAS_ROTOWIRE_LINES_PATH"] = str(roto_path)
        env_override["ATLAS_IAEL_INVALIDATIONS_PATH"] = str(iael_dir / "injury_invalidations.json")
        env_override["ATLAS_IAEL_STATUS_PATH"] = str(iael_dir / "status.json")
        env_override["ATLAS_IAEL_NORMALIZED_PATH"] = str(norm_path)

        # Build merged external priors with OddsAPI historical data
        merged_priors = _build_merged_priors(date, out_dir)
        if merged_priors:
            env_override["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(merged_priors)
        else:
            print(f"[BACKFILL] No OddsAPI archive for {date} — replay without external priors")

        # Call orchestrator run_today() directly via a small inline script.
        # We cannot use Atlas.cli replay because it overrides ATLAS_OUT_DIR.
        # The env already has ATLAS_GAME_DATE, ATLAS_STRICT_REPLAY, etc.
        inline = (
            "from Atlas.runtime.orchestrator import run_today; "
            f"run_today(authority='sandbox', raw_path=r'{raw_json}')"
        )
        cmd = [sys.executable, "-c", inline]
    else:
        return False, "no source"

    print(f"\n{'='*60}")
    print(f"[BACKFILL] Replaying {date} from {source_label}")
    print(f"[BACKFILL] scenario_id={scenario_id}")
    print(f"{'='*60}")

    t0 = time.time()
    kwargs = {"cwd": str(ROOT), "capture_output": True, "text": True}
    if env_override:
        kwargs["env"] = env_override
    result = subprocess.run(cmd, **kwargs)
    elapsed = time.time() - t0

    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").splitlines()[-20:])
        print(f"[BACKFILL] FAILED {date} (exit={result.returncode}, {elapsed:.0f}s)")
        print(f"[BACKFILL] stderr tail:\n{tail}")
        return False, f"exit={result.returncode}"

    # Find the replay output directory
    replay_dir = REPLAY_OUT / scenario_id
    if not replay_dir.exists():
        print(f"[BACKFILL] FAILED {date} — no output at {replay_dir}")
        return False, "no output dir"

    # Find the most recent timestamp subfolder under runs/
    runs_dir = replay_dir / "runs"
    if not runs_dir.exists():
        # Fallback: maybe output is directly in replay_dir (old format)
        ts_dirs = sorted(d for d in replay_dir.iterdir() if d.is_dir())
        if not ts_dirs:
            print(f"[BACKFILL] FAILED {date} — empty output at {replay_dir}")
            return False, "empty output dir"
        latest_ts = ts_dirs[-1]
    else:
        ts_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
        if not ts_dirs:
            print(f"[BACKFILL] FAILED {date} — no timestamp dirs under {runs_dir}")
            return False, "empty runs dir"
        latest_ts = ts_dirs[-1]

    # Verify critical files exist — check direct path first, then rglob for nested bundle layouts
    scored_path = latest_ts / "scored_legs_deduped.csv"
    eval_path = latest_ts / "eval_legs.csv"
    if not scored_path.exists():
        # Bundle replays nest output: <ts>/runs/<run_ts>/scored_legs_deduped.csv
        found = list(latest_ts.rglob("scored_legs_deduped.csv"))
        if found:
            scored_path = found[-1]  # latest by sort order
            latest_ts = scored_path.parent  # repoint to the actual run dir
            eval_path = latest_ts / "eval_legs.csv"
        else:
            print(f"[BACKFILL] FAILED {date} — no scored_legs_deduped.csv in {latest_ts}")
            return False, "missing scored_legs_deduped.csv"

    # Always run eval backfill when eval_legs is missing
    if not eval_path.exists():
        _backfill_eval_legs(latest_ts, date)
        eval_path = latest_ts / "eval_legs.csv" if (latest_ts / "eval_legs.csv").exists() else None

    n_scored = 0
    n_eval = 0
    import pandas as pd
    try:
        sf = pd.read_csv(scored_path, low_memory=False)
        n_scored = len(sf)
    except Exception:
        pass
    if eval_path and eval_path.exists():
        try:
            ef = pd.read_csv(eval_path, low_memory=False)
            n_eval = len(ef)
        except Exception:
            pass

    # Copy to corpus dir (skip if replay output is already inside corpus dir)
    dest = CORPUS_DIR / scenario_id
    if CORPUS_DIR.exists():
        try:
            already_in_place = latest_ts.resolve().is_relative_to(dest.resolve())
        except (ValueError, OSError):
            already_in_place = False
        if already_in_place:
            print(f"[BACKFILL] Output already in corpus dir — no copy needed")
        else:
            if dest.exists():
                shutil.rmtree(dest)
                print(f"[BACKFILL] Replaced existing {dest}")
            shutil.copytree(latest_ts, dest)
            print(f"[BACKFILL] Copied to {dest}")
    else:
        print(f"[BACKFILL] D drive not available, skipping copy to {dest}")

    print(f"[BACKFILL] OK {date} ({elapsed:.0f}s) — scored={n_scored}, eval_legs={n_eval}")
    return True, f"ok ({elapsed:.0f}s, eval={n_eval})"


def _backfill_eval_legs(run_dir: Path, date: str) -> None:
    """Run eval leg backfill for a replay directory."""
    try:
        from Atlas.runtime.replay_eval import backfill_latest_replay_eval_legs
        gamelogs = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
        backfill_latest_replay_eval_legs(
            output_root=run_dir,
            gamelogs_path=[gamelogs],
            repo_root=ROOT,
            python_executable=sys.executable,
        )
    except Exception as e:
        print(f"[BACKFILL] eval backfill failed for {date}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch replay backfill for leg trainer corpus expansion.")
    ap.add_argument("--dry-run", action="store_true", help="Show plan without executing.")
    ap.add_argument("--dates", nargs="*", help="Specific dates (YYYYMMDD) to backfill.")
    ap.add_argument("--include-extra", action="store_true",
                    help="Include dates beyond resim cache (Apr 5-7 etc).")
    ap.add_argument("--force", action="store_true",
                    help="Re-replay dates even if they already exist in the corpus.")
    ap.add_argument("--corpus-tag", default=None,
                    help="Folder prefix for replay output. "
                         "Default: auto-timestamped 'atlas_replay_YYYYMMDD_HHMMSS' (unique per run).")
    args = ap.parse_args()

    # Auto-generate timestamped tag if not explicitly provided
    if args.corpus_tag is None:
        tag = f"{DEFAULT_CORPUS_PREFIX}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        tag = args.corpus_tag

    # Write active tag so reader tools can auto-discover this corpus
    _write_corpus_tag(tag)
    print(f"[BACKFILL] Corpus tag: {tag}")
    print(f"[BACKFILL] Written to: {CORPUS_TAG_FILE}")
    print(f"[BACKFILL] C-drive output: {REPLAY_OUT / (tag + '_*')}")
    if CORPUS_DIR.exists():
        print(f"[BACKFILL] D-drive output: {CORPUS_DIR / (tag + '_*')}")
    else:
        print(f"[BACKFILL] D-drive not available — C-drive only")

    bundle_map = _build_bundle_map()
    raw_map = _build_raw_json_map()
    gamelog_dates = _get_gamelog_dates()
    bundle_dates, raw_dates = _find_backfill_dates(bundle_map, raw_map, gamelog_dates, args.dates, force=args.force, tag=tag)

    # Exclude All-Star break, test dirs, and future dates without truth
    SKIP_DATES = {"20260213", "20260214", "20260215", "20260216", "20260217", "20260218", "test"}
    bundle_dates = [d for d in bundle_dates if d not in SKIP_DATES]
    raw_dates = [d for d in raw_dates if d not in SKIP_DATES]

    all_dates = bundle_dates + raw_dates

    # Count existing corpus dynamically
    existing_count = len(_get_existing_corpus(tag=tag))

    if not all_dates:
        print(f"[BACKFILL] No dates to backfill. Corpus has {existing_count} dates. All caught up!")
        return 0

    print(f"[BACKFILL] Backfill plan: {len(all_dates)} dates ({len(bundle_dates)} bundle, {len(raw_dates)} raw JSON)")
    print(f"[BACKFILL] Existing corpus: {existing_count} dates")
    print(f"[BACKFILL] Target after backfill: {existing_count + len(all_dates)} dates")
    print()
    for d in bundle_dates:
        print(f"  {d}  [BUNDLE] {bundle_map[d].name}")
    for d in raw_dates:
        print(f"  {d}  [RAW]    {raw_map[d].name}")

    if args.dry_run:
        print("\n[BACKFILL] Dry run — no replays executed.")
        return 0

    print(f"\n[BACKFILL] Starting {len(all_dates)} replays...")
    results: list[tuple[str, bool, str]] = []
    for i, d in enumerate(sorted(all_dates), 1):
        print(f"\n[BACKFILL] === Date {i}/{len(all_dates)}: {d} ===")
        if d in bundle_map and d in bundle_dates:
            ok, msg = _replay_one(d, bundle_path=bundle_map[d], tag=tag)
        else:
            ok, msg = _replay_one(d, raw_json=raw_map[d], tag=tag)
        results.append((d, ok, msg))

    # Summary
    print(f"\n{'='*60}")
    print("[BACKFILL] SUMMARY")
    print(f"{'='*60}")
    ok_count = sum(1 for _, ok, _ in results if ok)
    print(f"  Success: {ok_count}/{len(results)}")
    for d, ok, msg in results:
        status = "OK" if ok else "FAIL"
        print(f"  {d}  [{status}]  {msg}")

    # Count new corpus total
    # Count from C-drive (canonical) and D-drive (if available)
    c_folders = list(REPLAY_OUT.glob(f"{tag}_*"))
    d_folders = list(CORPUS_DIR.glob(f"{tag}_*")) if CORPUS_DIR.exists() else []
    print(f"\n  Total corpus folders (C-drive): {len(c_folders)}")
    if d_folders:
        print(f"  Total corpus folders (D-drive): {len(d_folders)}")
    print(f"  New trainer RUN_DATES list:")
    all_dates = sorted(set(
        m.group(1) for f in c_folders + d_folders
        if (m := re.search(r"(\d{8})$", f.name))
    ))
    for d in all_dates:
        print(f'    "{d}",')

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

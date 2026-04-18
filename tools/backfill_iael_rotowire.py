#!/usr/bin/env python
r"""
tools/backfill_iael_rotowire.py
================================
Synthesize missing rotowire_lines.json snapshots in the IAEL archive
for historical dates that have gamelogs but no actual Rotowire capture.

What it does:
  1. Reads nba_gamelogs.csv to find unique (game_date, team, opp) matchups
  2. For each IAEL date dir missing rotowire_lines.json, creates a synthetic
     snapshot with neutral spreads (home=0, away=0) so the replay pipeline
     can proceed through the strict-replay gate.
  3. Also ensures a normalized stub exists in data/output/injury/normalized/
     for dates that lack one.

The synthesized spreads are neutral (0) — meaning the blowout model won't
have real spread signal for those dates, but all other pipeline stages
(kernel, calibration, slip builder) will run normally.

Usage:
    python tools/backfill_iael_rotowire.py              # backfill all missing
    python tools/backfill_iael_rotowire.py --dry-run    # preview only
    python tools/backfill_iael_rotowire.py --dates 20260225 20260226  # specific dates
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GAMELOGS_PATH = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
IAEL_BASE = ROOT / "data" / "archives" / "iael" / "2026"
NORMALIZED_DIR = ROOT / "data" / "output" / "injury" / "normalized"

# NBA team abbreviation normalization (gamelogs may use non-standard abbrs)
TEAM_REMAP = {
    "NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP",
    "UTAH": "UTA", "PHX": "PHO",
}


def _norm_team(t: str) -> str:
    t = t.strip().upper()
    return TEAM_REMAP.get(t, t)


def _norm_date_yyyymmdd(d: str) -> str:
    """Convert M/D/YYYY or YYYY-MM-DD to YYYYMMDD."""
    d = str(d).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(d, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return ""


def _norm_date_iso(d: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD."""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _load_game_matchups() -> dict[str, list[tuple[str, str]]]:
    """
    Return {YYYYMMDD: [(home_team, away_team), ...]} from gamelogs.

    Since gamelogs don't indicate home/away, we pick sorted order
    (first alphabetically = away, second = home) as a stable convention.
    """
    df = pd.read_csv(GAMELOGS_PATH, low_memory=False, usecols=["game_date", "team", "opp"])
    df["date8"] = df["game_date"].apply(_norm_date_yyyymmdd)
    df["team_n"] = df["team"].apply(_norm_team)
    df["opp_n"] = df["opp"].apply(_norm_team)

    matchups: dict[str, set[tuple[str, str]]] = {}
    for _, row in df[["date8", "team_n", "opp_n"]].drop_duplicates().iterrows():
        d = row["date8"]
        if not d:
            continue
        pair = tuple(sorted([row["team_n"], row["opp_n"]]))
        matchups.setdefault(d, set()).add(pair)

    # Convert to list of (away, home) — alphabetical first = away
    return {d: [(p[0], p[1]) for p in sorted(pairs)] for d, pairs in matchups.items()}


def _build_rotowire_json(date8: str, games: list[tuple[str, str]]) -> dict:
    """Build a synthetic rotowire_lines.json payload."""
    iso_date = _norm_date_iso(date8)
    events = []
    for i, (away, home) in enumerate(games):
        events.append({
            "gameID": f"synth_{date8}_{i:03d}",
            "eventTime": 0,
            "game_date": iso_date,
            "homeTeam": home,
            "awayTeam": away,
            "spread": {"home": 0.0, "away": 0.0},
            "ml": {"home": -110, "away": -110},
            "ou": 220.0,
            "source": "synthetic_gamelog",
        })
    return {
        "sport": "NBA",
        "source": "synthetic_from_gamelogs",
        "date": iso_date,
        "events": events,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "synthetic": True,
        "note": "Backfilled from gamelogs — neutral spreads. No real Rotowire capture for this date.",
    }


def _build_normalized_stub(date8: str) -> dict:
    """Build a minimal normalized IAEL stub."""
    iso_date = _norm_date_iso(date8)
    return {
        "report_date": iso_date,
        "report_label": "synthetic_backfill",
        "source_url": "",
        "pulled_at_local": datetime.now().strftime("%Y-%m-%d %I:%M%p"),
        "pdf_sha1": "",
        "rows": [],
    }


def _build_invalidations_stub(date8: str) -> dict:
    """Build a minimal injury_invalidations.json stub."""
    iso_date = _norm_date_iso(date8)
    return {
        "report_date": iso_date,
        "source": "synthetic_backfill",
        "invalidations": [],
    }


def _build_status_stub(date8: str) -> dict:
    """Build a minimal status.json stub."""
    iso_date = _norm_date_iso(date8)
    return {
        "report_date": iso_date,
        "source": "synthetic_backfill",
        "players": [],
    }


def _find_missing_dates(
    target_dates: list[str] | None = None,
    game_dates: set[str] | None = None,
    create_dirs: bool = False,
) -> list[str]:
    """Find dates that lack rotowire_lines.json in IAEL archive.

    When *create_dirs* is True and *game_dates* is provided, also includes
    dates that have gamelogs but no IAEL directory at all.
    """
    if not IAEL_BASE.exists():
        print(f"[BACKFILL] IAEL base not found: {IAEL_BASE}")
        return []

    missing = []
    seen_dates: set[str] = set()

    # Scan existing IAEL dirs
    for d in sorted(IAEL_BASE.iterdir()):
        if not d.is_dir() or not d.name.startswith("2026-"):
            continue
        date8 = d.name.replace("-", "")
        seen_dates.add(date8)
        if target_dates and date8 not in target_dates:
            continue
        # Check if any timestamp subdir has rotowire_lines.json
        has_roto = any(d.rglob("rotowire_lines.json"))
        if not has_roto:
            missing.append(date8)

    # Also include game dates that have no IAEL dir at all
    if create_dirs and game_dates:
        for date8 in sorted(game_dates):
            if date8 in seen_dates:
                continue
            if target_dates and date8 not in target_dates:
                continue
            missing.append(date8)
        missing = sorted(set(missing))

    return missing


def _find_dates_needing_normalized(dates: list[str]) -> list[str]:
    """Find dates that don't have a normalized JSON snapshot."""
    if not NORMALIZED_DIR.exists():
        return dates

    existing = set()
    for f in NORMALIZED_DIR.iterdir():
        if f.suffix == ".json" and f.name != "latest.json":
            # Format: YYYY-MM-DD_HH_MMam.json
            date_part = f.name[:10]  # YYYY-MM-DD
            existing.add(date_part.replace("-", ""))

    return [d for d in dates if d not in existing]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill IAEL rotowire snapshots from gamelogs")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write")
    parser.add_argument("--dates", nargs="*", help="Specific YYYYMMDD dates to backfill")
    parser.add_argument("--create-dirs", action="store_true",
                        help="Also create full IAEL dir structure for dates with no IAEL dir at all")
    args = parser.parse_args()

    target_dates = args.dates if args.dates else None

    print("[BACKFILL] Loading gamelogs...")
    game_matchups = _load_game_matchups()
    print(f"[BACKFILL] Gamelogs cover {len(game_matchups)} game dates")

    print("[BACKFILL] Scanning IAEL archive for missing rotowire...")
    missing = _find_missing_dates(
        target_dates,
        game_dates=set(game_matchups.keys()) if args.create_dirs else None,
        create_dirs=args.create_dirs,
    )

    # Filter to dates that actually have games
    no_games = {"20260217", "20260218", "20260219"}  # All-Star break
    replayable = [d for d in missing if d in game_matchups and d not in no_games]
    skipped_no_games = [d for d in missing if d not in game_matchups or d in no_games]

    print(f"[BACKFILL] Missing rotowire: {len(missing)} dates")
    print(f"[BACKFILL] Replayable (have gamelogs): {len(replayable)}")
    if skipped_no_games:
        print(f"[BACKFILL] Skipped (no games/All-Star): {skipped_no_games}")

    # Also check normalized
    need_normalized = _find_dates_needing_normalized(replayable)
    print(f"[BACKFILL] Need normalized stub: {len(need_normalized)}")

    if not replayable:
        print("[BACKFILL] Nothing to backfill")
        return 0

    print(f"\n[BACKFILL] Plan:")
    for d in replayable:
        games = game_matchups[d]
        norm_tag = " +normalized" if d in need_normalized else ""
        print(f"  {d}: {len(games)} games{norm_tag}")

    if args.dry_run:
        print("\n[BACKFILL] --dry-run: no files written")
        return 0

    # Write rotowire snapshots (+ IAEL stubs when creating new dirs)
    wrote_roto = 0
    wrote_norm = 0
    wrote_stubs = 0
    for d in replayable:
        iso = _norm_date_iso(d)
        iael_date_dir = IAEL_BASE / iso
        created_new_dir = False
        if not iael_date_dir.exists():
            print(f"  {d}: IAEL date dir missing, creating {iael_date_dir}")
            iael_date_dir.mkdir(parents=True, exist_ok=True)
            created_new_dir = True

        # Find or create a timestamp subdir
        ts_dirs = sorted([
            sd for sd in iael_date_dir.iterdir()
            if sd.is_dir() and sd.name[0].isdigit()
        ])
        if ts_dirs:
            # Add rotowire to the latest existing timestamp dir
            target_dir = ts_dirs[-1]
        else:
            # Create a new timestamp dir
            ts_name = f"{d}_120000Z"
            target_dir = iael_date_dir / ts_name
            target_dir.mkdir(parents=True, exist_ok=True)

        roto_path = target_dir / "rotowire_lines.json"
        games = game_matchups[d]
        payload = _build_rotowire_json(d, games)
        roto_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        wrote_roto += 1
        print(f"  {d}: wrote {roto_path.relative_to(ROOT)} ({len(games)} games)")

        # Also write rotowire_manifest.json for consistency
        manifest_path = target_dir / "rotowire_manifest.json"
        if not manifest_path.exists():
            manifest = {
                "sport": "NBA",
                "source": "synthetic_from_gamelogs",
                "date": iso,
                "events_count": len(games),
                "fetched_at": payload["fetched_at"],
            }
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Write IAEL stub files (invalidations + status) if missing
        inval_path = target_dir / "injury_invalidations.json"
        if not inval_path.exists():
            inval_path.write_text(json.dumps(_build_invalidations_stub(d), indent=2), encoding="utf-8")
            wrote_stubs += 1
            print(f"  {d}: wrote invalidations stub")

        status_path = target_dir / "status.json"
        if not status_path.exists():
            status_path.write_text(json.dumps(_build_status_stub(d), indent=2), encoding="utf-8")
            wrote_stubs += 1
            print(f"  {d}: wrote status stub")

        # Write normalized stub if needed
        if d in need_normalized:
            NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
            norm_name = f"{iso}_12_00PM.json"
            norm_path = NORMALIZED_DIR / norm_name
            norm_payload = _build_normalized_stub(d)
            norm_path.write_text(json.dumps(norm_payload, indent=2), encoding="utf-8")
            wrote_norm += 1
            print(f"  {d}: wrote normalized stub {norm_path.name}")

    print(f"\n[BACKFILL] Done: {wrote_roto} rotowire + {wrote_stubs} IAEL stubs + {wrote_norm} normalized stubs written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

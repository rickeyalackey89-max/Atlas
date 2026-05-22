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
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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

def _bundle_has_raw_snapshot(bundle_path: Path) -> bool:
    try:
        with zipfile.ZipFile(bundle_path, "r") as z:
            return any(
                name.lower().startswith("data/raw/")
                and name.lower().endswith(".json")
                for name in z.namelist()
            )
    except Exception:
        return False


def _zip_csv_row_count(bundle_path: Path, arcname: str) -> int:
    try:
        with zipfile.ZipFile(bundle_path, "r") as z:
            with z.open(arcname) as f:
                lines = (line.decode("utf-8-sig", errors="replace") for line in f)
                return max(0, sum(1 for _ in csv.DictReader(lines)))
    except Exception:
        return 0


def _bundle_board_window(bundle_path: Path, date: str) -> tuple[bool, str, dict[str, object]]:
    """Return whether bundle board rows are one-date and safely pre-start.

    A strict replay bundle can be selected only when its board is scoped to the
    replay date and the run timestamp is at least 15 minutes before the first
    game represented in that board.
    """
    target_utc, target_local = _bundle_capture_times(bundle_path, date)
    expected_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    rows = 0
    game_dates: set[str] = set()
    start_times: list[datetime] = []
    try:
        with zipfile.ZipFile(bundle_path, "r") as z:
            with z.open("data/board/today.csv") as f:
                lines = (line.decode("utf-8-sig", errors="replace") for line in f)
                for row in csv.DictReader(lines):
                    rows += 1
                    game_date = str(row.get("game_date", "")).strip()
                    if game_date:
                        game_dates.add(game_date)
                    start_raw = str(row.get("start_time", "")).strip()
                    if start_raw:
                        try:
                            parsed = datetime.fromisoformat(start_raw)
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            start_times.append(parsed.astimezone(timezone.utc))
                        except Exception:
                            continue
    except Exception as exc:
        return False, f"unreadable_board:{type(exc).__name__}", {"rows": rows}

    meta: dict[str, object] = {
        "rows": rows,
        "game_dates": sorted(game_dates),
        "target_utc": target_utc.isoformat() if target_utc else None,
        "target_local": target_local.isoformat() if target_local else None,
    }
    if rows <= 0:
        return False, "empty_board", meta
    if game_dates != {expected_iso}:
        return False, f"date_mismatch expected={expected_iso} found={sorted(game_dates)}", meta
    if not start_times:
        return False, "missing_start_times", meta
    first_start = min(start_times)
    meta["first_start_utc"] = first_start.isoformat()
    if target_utc is None:
        return False, "missing_bundle_time", meta
    buffer_seconds = 15 * 60
    if target_utc.timestamp() > first_start.timestamp() - buffer_seconds:
        return False, "not_15min_prestart", meta
    return True, "ok", meta


def _market_overlay_rows_for_bundle(date: str, bundle_path: Path) -> int:
    target_utc, _target_local = _bundle_capture_times(bundle_path, date)
    paths = _archive_market_source_paths(date, target_utc)
    total = 0
    for path in paths.values():
        if path.suffix.lower() == ".csv":
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    total += max(0, sum(1 for _ in csv.DictReader(f)))
            except Exception:
                continue
    return total


# Map: date -> best strict-fidelity bundle for that date.
def _build_bundle_map() -> dict[str, Path]:
    """Return {YYYYMMDD: Path} picking the best complete pre-start bundle.

    Complete means the bundle contains a replay raw snapshot under data/raw.
    Pre-start means its board is one game date and the run timestamp is at least
    15 minutes before the first represented game. Among valid bundles, prefer
    the most time-safe market overlay coverage, then bundled prior coverage,
    then the latest run timestamp. If no valid pre-start complete bundle exists,
    fall back to the earliest complete bundle so preflight can fail explicitly.
    """
    candidates_by_date: dict[str, list[Path]] = {}
    for bdir in BUNDLES_DIRS:
        if not bdir.exists():
            continue
        for zp in sorted(bdir.glob("atlas_bundle_*.zip")):
            if "DEAD_PERIOD" in zp.name or "TEST" in zp.name:
                continue
            m = re.search(r"atlas_bundle_(\d{8})_(\d+)", zp.name)
            if m:
                d = m.group(1)
                candidates_by_date.setdefault(d, []).append(zp)
    bmap: dict[str, Path] = {}
    for d, paths in candidates_by_date.items():
        paths = sorted(paths)
        complete = [p for p in paths if _bundle_has_raw_snapshot(p)]
        valid: list[tuple[int, int, float, Path]] = []
        for path in complete:
            ok, _reason, _meta = _bundle_board_window(path, d)
            if not ok:
                continue
            overlay_rows = _market_overlay_rows_for_bundle(d, path)
            prior_rows = _zip_csv_row_count(path, "data/input/external_priors_today.csv")
            target_utc, _target_local = _bundle_capture_times(path, d)
            target_ts = target_utc.timestamp() if target_utc else 0.0
            valid.append((overlay_rows, prior_rows, target_ts, path))
        if valid:
            valid.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            bmap[d] = valid[0][3]
        elif complete:
            bmap[d] = complete[0]
        else:
            bmap[d] = paths[0]
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


def _raw_capture_times(raw_json: Path | None, date: str) -> tuple[datetime | None, datetime | None]:
    """Return (utc, local) replay run-start approximation from a raw PP filename."""
    if raw_json is not None:
        m = re.search(r"prizepicks_(\d{8})_(\d{6})", raw_json.name)
        if m:
            local_dt = datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("America/Chicago"))
            return local_dt.astimezone(timezone.utc), local_dt
    local_dt = datetime.strptime(date, "%Y%m%d").replace(tzinfo=ZoneInfo("America/Chicago"))
    return local_dt.astimezone(timezone.utc), local_dt


def _bundle_capture_times(bundle_path: Path | None, date: str) -> tuple[datetime | None, datetime | None]:
    """Return (utc, local) replay run-start approximation from bundle filename."""
    if bundle_path is not None:
        m = re.search(r"atlas_bundle_(\d{8})_(\d{6})", bundle_path.name)
        if m:
            local_dt = datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("America/Chicago"))
            return local_dt.astimezone(timezone.utc), local_dt
    return _raw_capture_times(None, date)


def _archive_child_dt(child: Path) -> datetime | None:
    try:
        return datetime.strptime(child.name, "%Y%m%d_%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _choose_by_target(candidates: list[tuple[datetime, Path]], target_utc: datetime | None, *, max_future_minutes: int = 30) -> Path | None:
    if not candidates:
        return None
    if target_utc is None:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    future_limit = target_utc.timestamp() + (max_future_minutes * 60)
    eligible = [
        (abs((dt - target_utc).total_seconds()), 1 if dt > target_utc else 0, dt, path)
        for dt, path in candidates
        if dt.timestamp() <= future_limit
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item[1], item[0]))
    return eligible[0][3]


def _parse_market_asof(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _market_csv_asof_bounds(path: Path) -> tuple[datetime | None, datetime | None, int]:
    if not path.is_file():
        return None, None, 0
    first: datetime | None = None
    last: datetime | None = None
    count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                count += 1
                dt = _parse_market_asof(str(row.get("asof_ts", "")))
                if dt is None:
                    continue
                first = dt if first is None or dt < first else first
                last = dt if last is None or dt > last else last
    except Exception:
        return None, None, count
    return first, last, count


def _market_source_time_ok(path: Path, target_utc: datetime | None, *, max_future_minutes: int = 15) -> bool:
    if target_utc is None:
        return True
    _first, last, row_count = _market_csv_asof_bounds(path)
    if row_count <= 0:
        return False
    if last is None:
        return False
    return last.timestamp() <= target_utc.timestamp() + (max_future_minutes * 60)


def _find_best_iael_archive_dir(date: str, target_utc: datetime | None = None) -> Path | None:
    """Find the best IAEL archive timestamp dir for a date (YYYYMMDD).
    Returns the dir containing injury_invalidations.json + status.json."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    date_dir = ROOT / "data" / "archives" / "iael" / "2026" / iso
    if not date_dir.is_dir():
        return None
    candidates: list[tuple[datetime, Path]] = []
    for child in sorted(date_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / "injury_invalidations.json").is_file() and (child / "status.json").is_file():
            child_dt = _archive_child_dt(child)
            if child_dt is not None:
                candidates.append((child_dt, child))
    return _choose_by_target(candidates, target_utc)


def _find_rotowire_for_date(date: str, target_utc: datetime | None = None) -> Path | None:
    """Find a rotowire_lines.json in the IAEL archive for a date (YYYYMMDD)."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    date_dir = ROOT / "data" / "archives" / "iael" / "2026" / iso
    if not date_dir.is_dir():
        return None
    candidates: list[tuple[datetime, Path]] = []
    for child in sorted(date_dir.iterdir()):
        roto = child / "rotowire_lines.json"
        child_dt = _archive_child_dt(child)
        if roto.is_file() and child_dt is not None:
            try:
                obj = json.loads(roto.read_text(encoding="utf-8"))
            except Exception:
                continue
            source_date = str(obj.get("date", "")).strip()
            if source_date and source_date != iso:
                continue
            candidates.append((child_dt, roto))
    return _choose_by_target(candidates, target_utc)


def _find_best_normalized(date: str, target_local: datetime | None = None) -> Path | None:
    """Find a normalized IAEL snapshot for a date (YYYYMMDD)."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    norm_dir = ROOT / "data" / "output" / "injury" / "normalized"
    if not norm_dir.is_dir():
        return None
    prefix = f"{iso}_"
    candidates: list[tuple[datetime, Path]] = []
    for child in norm_dir.iterdir():
        if not child.name.startswith(prefix) or child.suffix != ".json":
            continue
        try:
            child_dt = datetime.strptime(child.stem, "%Y-%m-%d_%I_%M%p").replace(tzinfo=ZoneInfo("America/Chicago"))
        except ValueError:
            continue
        candidates.append((child_dt.astimezone(timezone.utc), child))
    chosen = _choose_by_target(candidates, target_local.astimezone(timezone.utc) if target_local else None)
    if chosen is not None:
        return chosen
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


def _game_line_context_status(path: Path, *, game_date: str | None) -> tuple[bool, str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"unreadable:{type(exc).__name__}"
    if not isinstance(obj, dict):
        return False, "bad_shape"
    source_date = str(obj.get("date", "")).strip()
    if game_date and source_date and source_date != game_date:
        return False, f"date_mismatch expected={game_date} found={source_date}"
    events = obj.get("events")
    if not isinstance(events, list) or not events:
        return False, "no_events"
    missing: list[str] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            missing.append(f"event_{idx}:bad_shape")
            continue
        spread = ev.get("spread")
        if not isinstance(spread, dict):
            spread = {}
        if spread.get("home") is None or spread.get("away") is None:
            missing.append(f"event_{idx}:missing_spread")
        if ev.get("ou") is None:
            missing.append(f"event_{idx}:missing_total")
    if missing:
        return False, ";".join(missing[:8])
    return True, f"ok events={len(events)}"


def _github_prop_archive_dt(path: Path) -> datetime | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})[_-]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})", path.name)
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y-%m-%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _find_github_prop_odds_archive(date: str, target_utc: datetime | None = None) -> Path | None:
    """Find GitHub-recovered player prop odds CSV for a date (YYYYMMDD)."""
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    archive_dir = ROOT / "data" / "archives" / "github_prop_odds"
    exact_names = [
        archive_dir / f"github_childersjac_props_{iso}.csv",
        archive_dir / f"github_prop_odds_{iso}.csv",
        archive_dir / f"nba_prop_odds_{iso}.csv",
    ]
    for path in exact_names:
        if path.is_file():
            return path
    if archive_dir.is_dir():
        timed: list[tuple[datetime, Path]] = []
        undated: list[Path] = []
        for path in sorted(archive_dir.glob(f"*{iso}*.csv")):
            dt = _github_prop_archive_dt(path)
            if dt is None:
                undated.append(path)
            else:
                timed.append((dt, path))
        chosen = _choose_by_target(timed, target_utc, max_future_minutes=15)
        if chosen:
            return chosen
        if target_utc is None and undated:
            return undated[-1]
    return None


CSV_FIELDS = [
    "source", "league", "player", "stat", "line", "asof_ts", "projection",
    "confidence", "over_prob", "under_prob", "over_rating", "under_rating",
    "opp_rank", "notes",
]


def _build_merged_priors(date: str, out_dir: Path, target_utc: datetime | None = None) -> Path | None:
    """Build a merged external_priors CSV with OddsAPI historical data for raw JSON replays.

    Returns path to the merged CSV, or None if no OddsAPI data available."""
    oa_path = _find_oddsapi_archive(date)
    gh_path = _find_github_prop_odds_archive(date, target_utc)
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    bp_path = ROOT / "data" / "archives" / "bettingpros" / f"bettingpros_props_{iso}.csv"
    dk_path = ROOT / "data" / "archives" / "draftkings" / f"draftkings_props_{iso}.csv"

    all_rows: list[dict[str, str]] = []
    for source_path in [bp_path, dk_path, oa_path, gh_path]:
        if source_path is None or not source_path.is_file():
            continue
        with source_path.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                all_rows.append(row)

    if not all_rows:
        return None

    merged_path = out_dir / "external_priors_today.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            safe_row = {k: row.get(k, "") for k in CSV_FIELDS}
            writer.writerow(safe_row)

    print(f"[BACKFILL] Built external priors for {date}: {len(all_rows)} pinned rows -> {merged_path}")
    return merged_path


def _archive_market_source_paths(date: str, target_utc: datetime | None = None) -> dict[str, Path]:
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    candidates = {
        "ATLAS_BETTINGPROS_PROPS_CSV_PATH": ROOT / "data" / "archives" / "bettingpros" / f"bettingpros_props_{iso}.csv",
        "ATLAS_DRAFTKINGS_PROPS_CSV_PATH": ROOT / "data" / "archives" / "draftkings" / f"draftkings_props_{iso}.csv",
    }
    gh_path = _find_github_prop_odds_archive(date, target_utc)
    if gh_path:
        candidates["ATLAS_GITHUB_PROP_ODDS_CSV_PATH"] = gh_path
    return {
        key: path
        for key, path in candidates.items()
        if path.is_file() and _market_source_time_ok(path, target_utc)
    }


def _replay_one(date: str, bundle_path: Path | None = None, raw_json: Path | None = None,
                tag: str = DEFAULT_CORPUS_PREFIX) -> tuple[bool, str]:
    """Replay a single bundle or raw JSON and copy output to corpus folder."""
    scenario_id = f"{tag}_{date}"

    if bundle_path:
        target_utc, _target_local = _bundle_capture_times(bundle_path, date)
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
        archive_paths = _archive_market_source_paths(date, target_utc)
        bp_path = archive_paths.get("ATLAS_BETTINGPROS_PROPS_CSV_PATH")
        dk_path = archive_paths.get("ATLAS_DRAFTKINGS_PROPS_CSV_PATH")
        if bp_path:
            cmd.extend(["--bettingpros-overlay", str(bp_path)])
            print(f"[BACKFILL] BettingPros overlay for {date}: {bp_path.name}")
        if dk_path:
            cmd.extend(["--draftkings-overlay", str(dk_path)])
            print(f"[BACKFILL] DraftKings overlay for {date}: {dk_path.name}")
        gh_path = archive_paths.get("ATLAS_GITHUB_PROP_ODDS_CSV_PATH")
        if gh_path:
            cmd.extend(["--github-props-overlay", str(gh_path)])
            print(f"[BACKFILL] GitHub prop odds overlay for {date}: {gh_path.name}")
        source_label = bundle_path.name
        env_override = None
    elif raw_json:
        # Raw JSON path: set up env vars like replay_bundle.py and call engine directly
        source_label = raw_json.name
        target_utc, target_local = _raw_capture_times(raw_json, date)
        iael_dir = _find_best_iael_archive_dir(date, target_utc)
        roto_path = _find_rotowire_for_date(date, target_utc)
        norm_path = _find_best_normalized(date, target_local)
        gamelogs_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
        role_metrics_artifacts: dict[str, Path] = {}
        try:
            from replay_bundle import _find_best_role_metrics_artifacts

            role_metrics_artifacts = _find_best_role_metrics_artifacts(ROOT, target_utc)
        except Exception as exc:
            print(f"[BACKFILL] role metrics lookup failed for {date}: {exc}")

        # Pre-flight
        missing = []
        if not iael_dir:
            missing.append("IAEL archive dir")
        if not roto_path:
            missing.append("rotowire_lines.json")
        elif roto_path:
            game_date_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            line_ok, line_reason = _game_line_context_status(roto_path, game_date=game_date_iso)
            if not line_ok:
                missing.append(f"usable game-line spread/total context ({line_reason})")
        if not norm_path:
            missing.append("normalized snapshot")
        if not gamelogs_path.exists():
            missing.append("gamelogs")
        if not role_metrics_artifacts.get("ATLAS_ROLE_METRICS_PATH"):
            missing.append("role metrics snapshot")
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
        for key, path in role_metrics_artifacts.items():
            env_override[key] = str(path)

        # Build merged external priors with OddsAPI historical data
        merged_priors = _build_merged_priors(date, out_dir, target_utc)
        if merged_priors:
            env_override["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(merged_priors)
            for key, source_path in _archive_market_source_paths(date, target_utc).items():
                env_override[key] = str(source_path)
        else:
            print(f"[BACKFILL] SKIPPED {date} — missing pinned market priors")
            return False, "missing pinned market priors"

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
    timeout_sec = int(os.environ.get("ATLAS_REPLAY_TIMEOUT_SEC", "1800"))
    try:
        result = subprocess.run(cmd, timeout=timeout_sec, **kwargs)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - t0
        tail = "\n".join((exc.stderr or "").splitlines()[-20:]) if isinstance(exc.stderr, str) else ""
        print(f"[BACKFILL] FAILED {date} (timeout={timeout_sec}s, elapsed={elapsed:.0f}s)")
        if tail:
            print(f"[BACKFILL] stderr tail:\n{tail}")
        return False, f"timeout={timeout_sec}s"
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

    try:
        from scripts.audits.strict_replay_fidelity_audit import audit_run as strict_replay_audit

        expected_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        strict_result = strict_replay_audit(latest_ts, expected_date=expected_iso)
        strict_path = latest_ts / "strict_replay_fidelity_audit.json"
        strict_path.write_text(json.dumps(strict_result, indent=2, sort_keys=True), encoding="utf-8")
        print(
            f"[BACKFILL] strict fidelity audit {strict_result.get('verdict')} "
            f"failures={len(strict_result.get('failures') or [])} -> {strict_path}"
        )
        if strict_result.get("verdict") != "PASS":
            return False, f"strict fidelity {strict_result.get('verdict')}"
    except Exception as exc:
        print(f"[BACKFILL] strict fidelity audit failed for {date}: {exc}")
        return False, f"strict fidelity audit error: {exc}"

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
            copy_dest = dest
            if copy_dest.exists():
                suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
                copy_dest = CORPUS_DIR / f"{scenario_id}_rerun_{suffix}"
                print(f"[BACKFILL] Existing corpus output preserved; copying to {copy_dest}")
            shutil.copytree(latest_ts, copy_dest)
            print(f"[BACKFILL] Copied to {copy_dest}")
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

    print(f"[BACKFILL] Corpus tag: {tag}")
    if not args.dry_run:
        # Write active tag so reader tools can auto-discover this corpus.
        _write_corpus_tag(tag)
        print(f"[BACKFILL] Written to: {CORPUS_TAG_FILE}")
    else:
        print(f"[BACKFILL] Dry run will not update: {CORPUS_TAG_FILE}")
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

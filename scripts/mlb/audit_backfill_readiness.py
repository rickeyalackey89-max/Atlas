"""Audit MLB replay/backfill source coverage by date.

This is intentionally conservative. A date is only marked strict-runnable when
we have a local MLB PrizePicks board snapshot plus normalized primary market
context for that exact date. Other sources are reported as coverage/warnings so
we can improve fidelity without accidentally replaying invented context.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATE_FMT = "%Y-%m-%d"
_MARKET_BY_DATE_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


@dataclass(frozen=True)
class SourceDir:
    path: Path
    manifest: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Atlas MLB-dev repository root.")
    parser.add_argument("--start", default="2026-04-26", help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", default="2026-05-11", help="End date, YYYY-MM-DD.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Audit output directory. Defaults to data/mlb/audits.",
    )
    return parser.parse_args()


def iter_dates(start: date, end: date) -> list[date]:
    current = start
    dates: list[date] = []
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def count_json_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(payload, list):
        return sum(1 for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return sum(1 for row in rows if isinstance(row, dict))
    return 0


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return 0


def actual_artifact_rows(source: SourceDir, names: tuple[str, ...]) -> int:
    total = 0
    for name in names:
        path = source.path / name
        suffix = path.suffix.lower()
        if suffix == ".jsonl":
            total += count_jsonl(path)
        elif suffix == ".json":
            total += count_json_rows(path)
        elif suffix == ".csv":
            total += count_csv_rows(path)
    return total


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def text_contains_mlb(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return '"league": "MLB"' in text or '"league":"MLB"' in text


def source_dirs(root: Path, relative: str) -> list[SourceDir]:
    base = root / relative
    if not base.exists():
        return []
    dirs: list[SourceDir] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest = read_json(child / "normalize_manifest.json") or read_json(child / "manifest.json")
        if not manifest:
            for manifest_path in sorted(child.glob("*_manifest.json")):
                manifest = read_json(manifest_path)
                if manifest:
                    break
        dirs.append(SourceDir(path=child, manifest=manifest))
    return dirs


def date_compact(day: date) -> str:
    return day.strftime("%Y%m%d")


def dir_matches_date(source: SourceDir, day: date) -> bool:
    day_text = day.strftime(DATE_FMT)
    compact = date_compact(day)
    manifest = source.manifest
    candidates = [
        str(manifest.get("game_date", "")),
        str(manifest.get("date", "")),
        str(manifest.get("target_date", "")),
        str(manifest.get("run_id", "")),
        str(manifest.get("snapshot_id", "")),
        source.path.name,
    ]
    return any(day_text in candidate or compact in candidate for candidate in candidates)


def latest_payload(payloads: list[Path]) -> str:
    if not payloads:
        return ""
    return str(sorted(payloads)[-1])


def prizepicks_payloads(root: Path, day: date) -> list[Path]:
    date_key = day.strftime(DATE_FMT)
    payloads: list[Path] = []
    for relative in ("data/mlb/raw/prizepicks", "data/mlb/raw/prizepicks_all_sports"):
        base = root / relative / date_key
        if not base.exists():
            continue
        for payload in sorted(base.glob("*/payload.json")):
            if text_contains_mlb(payload):
                payloads.append(payload)
    return payloads


def github_prizepicks_imports(root: Path, day: date) -> list[tuple[Path, int]]:
    base = root / "data/mlb/raw/mlb_github_imports"
    if not base.exists():
        return []
    date_key = day.strftime(DATE_FMT)
    imports: list[tuple[Path, int]] = []
    for csv_path in sorted(base.rglob("*.csv")):
        if date_key not in csv_path.name:
            continue
        mlb_rows = github_prizepicks_mlb_row_count(csv_path)
        if mlb_rows:
            imports.append((csv_path, mlb_rows))
    return imports


def github_prizepicks_mlb_row_count(path: Path) -> int:
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return sum(1 for row in reader if str(row.get("league") or "").upper() == "MLB")
    except OSError:
        return 0


def raw_oddsapi_payloads(root: Path, day: date) -> list[Path]:
    base = root / "data/mlb/raw/oddsapi_mlb_historical" / day.strftime(DATE_FMT)
    if not base.exists():
        return []
    return sorted(base.glob("*/payload.json"))


def staged_count_by_date(root: Path, relative: str, day: date, rows_name: str | None = None) -> tuple[int, int]:
    matches = [source for source in source_dirs(root, relative) if dir_matches_date(source, day)]
    rows = 0
    if rows_name:
        rows = sum(count_jsonl(source.path / rows_name) for source in matches)
    else:
        for source in matches:
            rows += actual_artifact_rows(
                source,
                (
                    "advanced_profiles_source.jsonl",
                    "advanced_profiles_source.json",
                    "advanced_profiles.jsonl",
                    "advanced_profiles.json",
                    "ballpark_factors_source.jsonl",
                    "ballpark_factors_source.json",
                    "ballpark_profiles.jsonl",
                    "ballpark_profiles.json",
                    "schedule.jsonl",
                    "trending_players.jsonl",
                ),
            )
    return len(matches), rows


def _manifest_row_count(manifest: dict[str, Any]) -> int:
    return int(
        manifest.get("row_count")
        or manifest.get("injury_count")
        or manifest.get("profile_count")
        or manifest.get("park_profile_count")
        or manifest.get("league_effect_count")
        or manifest.get("park_count")
        or manifest.get("team_count")
        or sum(v for v in manifest.get("row_counts", {}).values() if isinstance(v, int))
        or 0
    )


def staged_source_counts_by_date(root: Path, relative: str, day: date) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in source_dirs(root, relative):
        if not dir_matches_date(source, day):
            continue
        source_name = str(source.manifest.get("source") or source.path.name).strip() or "unknown"
        counts[source_name] = counts.get(source_name, 0) + 1
    return dict(sorted(counts.items()))


def staged_market_by_game_date(root: Path, day: date) -> tuple[int, int, dict[str, int]]:
    day_text = day.strftime(DATE_FMT)
    cache_key = str(root.resolve())
    if cache_key not in _MARKET_BY_DATE_CACHE:
        _MARKET_BY_DATE_CACHE[cache_key] = _build_market_by_date_index(root)
    item = _MARKET_BY_DATE_CACHE[cache_key].get(day_text, {})
    return int(item.get("dirs", 0)), int(item.get("rows", 0)), dict(item.get("source_counts", {}))


def _build_market_by_date_index(root: Path) -> dict[str, dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for source in source_dirs(root, "data/mlb/staged/oddsapi"):
        rows = iter_jsonl(source.path / "oddsapi_props.jsonl")
        dates_in_source: dict[str, dict[str, Any]] = {}
        for row in rows:
            game_date = str(row.get("game_date") or "")
            if not game_date:
                continue
            source_name = str(source.manifest.get("source") or row.get("source") or source.path.name).strip() or "unknown"
            item = dates_in_source.setdefault(game_date, {"rows": 0, "source_name": source_name})
            item["rows"] += 1
        for game_date, source_item in dates_in_source.items():
            target = by_date.setdefault(game_date, {"dirs": 0, "rows": 0, "source_counts": {}})
            target["dirs"] += 1
            target["rows"] += int(source_item["rows"])
            source_name = str(source_item["source_name"] or "unknown")
            target["source_counts"][source_name] = target["source_counts"].get(source_name, 0) + 1
    for item in by_date.values():
        item["source_counts"] = dict(sorted(item["source_counts"].items()))
    return by_date


def date_safe_source_rows(root: Path, relative: str, day: date, rows_name: str) -> tuple[int, int]:
    source = latest_source_on_or_before(root, relative, day, rows_name)
    if source is None:
        return 0, 0
    return 1, count_jsonl(source.path / rows_name)


def date_safe_roster_rows(root: Path, day: date) -> tuple[int, int, int, int]:
    candidates: list[tuple[int, SourceDir, str]] = []
    for source_type, relative, rows_name in (
        (1, "data/mlb/staged/statsapi_rosters_bulk", "statsapi_rosters_bulk.jsonl"),
        (0, "data/mlb/staged/statsapi_rosters", "statsapi_rosters.jsonl"),
    ):
        source = latest_source_on_or_before(root, relative, day, rows_name)
        if source is not None:
            candidates.append((source_type, source, rows_name))
    if not candidates:
        return 0, 0, 0, 0
    source_type, source, rows_name = sorted(
        candidates,
        key=lambda item: (
            snapshot_date_key(item[1]),
            item[0],
            item[1].path.stat().st_mtime,
            item[1].path.name,
        ),
    )[-1]
    row_count = count_jsonl(source.path / rows_name)
    if source_type == 1:
        return 0, 0, 1, row_count
    return 1, row_count, 0, 0


def latest_source_on_or_before(root: Path, relative: str, day: date, rows_name: str) -> SourceDir | None:
    target = day.strftime(DATE_FMT)
    eligible: list[SourceDir] = []
    for source in source_dirs(root, relative):
        rows_path = source.path / rows_name
        allow_empty_injury_manifest = (
            rows_name == "injuries.jsonl"
            and bool(source.manifest.get("empty_snapshot"))
            and int(source.manifest.get("injury_count") or 0) == 0
        )
        if not rows_path.exists() and not allow_empty_injury_manifest:
            continue
        source_date = snapshot_date_key(source)
        if source_date and source_date <= target:
            eligible.append(source)
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda source: (
            snapshot_date_key(source),
            1 if snapshot_date_key(source) == target else 0,
            1 if "cbs_injuries" in source.path.name.lower() else 0,
            source.path.stat().st_mtime,
            source.path.name,
        ),
    )[-1]


def snapshot_date_key(source: SourceDir) -> str:
    candidates = [
        str(source.manifest.get("game_date", "")),
        str(source.manifest.get("date", "")),
        str(source.manifest.get("target_date", "")),
        str(source.manifest.get("run_id", "")),
        str(source.manifest.get("snapshot_id", "")),
        source.path.name,
    ]
    for candidate in candidates:
        match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", candidate)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def staged_context_counts_by_date(root: Path, relative: str, day: date) -> dict[str, int]:
    matches = [source for source in source_dirs(root, relative) if dir_matches_date(source, day)]
    latest_start = latest_schedule_start_for_date(root, day)
    counts = {
        "dirs": len(matches),
        "rows": 0,
        "fidelity_rows": 0,
        "reconstructed_pregame_rows": 0,
        "postgame_rows": 0,
        "post_start_rows": 0,
    }
    for source in matches:
        rows = []
        for rows_name in ("batting_orders.jsonl", "pitchers.jsonl", "environment.jsonl", "bullpens.jsonl"):
            rows.extend(iter_jsonl(source.path / rows_name))
        if not rows:
            # A manifest without row files is not replay context. Counting it
            # as runnable coverage is how a preflight can pass while runtime
            # source selection later fails.
            continue

        for row in rows:
            counts["rows"] += 1
            if manifest_is_postgame(source.manifest) or manifest_is_postgame(row):
                counts["postgame_rows"] += 1
                continue
            if row_indicates_started(row):
                counts["post_start_rows"] += 1
                continue
            if is_reconstructed_pregame_context(source.manifest) or is_reconstructed_pregame_context(row):
                counts["reconstructed_pregame_rows"] += 1
                counts["fidelity_rows"] += 1
                continue
            row_snapshot = snapshot_time_utc(row) or snapshot_time_utc(source.manifest, source.path)
            if latest_start and row_snapshot and row_snapshot > latest_start:
                counts["post_start_rows"] += 1
                continue
            counts["fidelity_rows"] += 1
    return counts


def schedule_games_for_date(root: Path, day: date) -> int:
    total = 0
    for source in source_dirs(root, "data/mlb/staged/statsapi_schedule"):
        rows_path = source.path / "statsapi_schedule.jsonl"
        if not rows_path.exists():
            continue
        try:
            with rows_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(row.get("official_date", "")) == day.strftime(DATE_FMT):
                        total += 1
        except OSError:
            continue
    return total


def latest_schedule_start_for_date(root: Path, day: date) -> datetime | None:
    starts: list[datetime] = []
    for source in source_dirs(root, "data/mlb/staged/statsapi_schedule"):
        rows_path = source.path / "statsapi_schedule.jsonl"
        for row in iter_jsonl(rows_path):
            if str(row.get("official_date", "")) != day.strftime(DATE_FMT):
                continue
            parsed = parse_utc_datetime(row.get("game_date"))
            if parsed:
                starts.append(parsed)
    return max(starts) if starts else None


def manifest_is_postgame(payload: dict[str, Any]) -> bool:
    timing = str(payload.get("context_timing") or payload.get("slate_status") or "").lower()
    return "postgame" in timing


def is_reconstructed_pregame_context(payload: dict[str, Any]) -> bool:
    timing = str(payload.get("context_timing") or payload.get("slate_status") or "").lower()
    content_timing = str(payload.get("lineup_content_timing") or "").lower()
    source = str(payload.get("source") or "").lower()
    if "postgame" in timing:
        return False
    if content_timing != "pregame_starting_lineup":
        return False
    return "pregame" in timing or source == "baseball_reference_boxscore_context"


def row_indicates_started(row: dict[str, Any]) -> bool:
    value = row.get("game_started")
    if isinstance(value, bool):
        return value
    if str(value or "").strip().lower() in {"true", "1", "yes"}:
        return True
    status = str(row.get("slate_status") or row.get("status") or "").lower()
    return "has-started" in status or "postgame" in status


def source_after_latest_start(manifest: dict[str, Any], path: Path, latest_start: datetime | None) -> bool:
    snapshot = snapshot_time_utc(manifest, path)
    return bool(snapshot and latest_start and snapshot > latest_start)


def snapshot_time_utc(payload: dict[str, Any], path: Path | None = None) -> datetime | None:
    candidates: list[Any] = [
        payload.get("pulled_at_utc"),
        payload.get("fetched_at_utc"),
        payload.get("generated_at_utc"),
        payload.get("generated_at"),
        payload.get("snapshot_id"),
        payload.get("run_id"),
    ]
    if path is not None:
        candidates.append(path.name)
    for value in candidates:
        parsed = parse_utc_datetime(value)
        if parsed:
            return parsed
    return None


def parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.search(r"(20\d{2})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", text)
    if compact:
        try:
            return datetime(
                int(compact.group(1)),
                int(compact.group(2)),
                int(compact.group(3)),
                int(compact.group(4)),
                int(compact.group(5)),
                int(compact.group(6)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def advanced_profile_rows(root: Path, day: date) -> int:
    compact = date_compact(day)
    base = root / "data/mlb/staged/advanced_profiles"
    rows = 0
    for source in sorted(base.glob(f"*{compact}*")):
        rows += actual_artifact_rows(
            SourceDir(path=source, manifest=read_json(source / "advanced_profiles_manifest.json")),
            ("advanced_profiles.json", "advanced_profiles.jsonl", "advanced_profiles.csv"),
        )
    return rows


def wind_factor_rows(root: Path) -> int:
    manifest = read_json(root / "data/mlb/staged/wind_factors/latest_manifest.json")
    if not manifest:
        return 0
    return _manifest_row_count(manifest)


def prior_history_identity_rows(root: Path, day: date) -> int:
    path = root / "data/mlb/season_gamelogs/latest.jsonl"
    if not path.exists():
        return 0
    target = day.strftime(DATE_FMT)
    count = 0
    for row in iter_jsonl(path):
        if not row.get("person_id") or not row.get("player_name"):
            continue
        row_date = str(row.get("official_date") or row.get("game_date") or "")[:10]
        if row_date and row_date < target:
            count += 1
    return count


def audit_date(root: Path, day: date) -> dict[str, Any]:
    pp_payloads = prizepicks_payloads(root, day)
    github_pp_imports = github_prizepicks_imports(root, day)
    github_pp_rows = sum(row_count for _, row_count in github_pp_imports)
    raw_odds = raw_oddsapi_payloads(root, day)
    staged_market_count, staged_market_rows, market_source_counts = staged_market_by_game_date(root, day)
    injury_count, injury_rows = date_safe_source_rows(root, "data/mlb/staged/injuries", day, "injuries.jsonl")
    roster_count, roster_rows, roster_bulk_count, roster_bulk_rows = date_safe_roster_rows(root, day)
    roster_rows_total = roster_rows + roster_bulk_rows
    prior_identity_rows = prior_history_identity_rows(root, day)
    espn_context = staged_context_counts_by_date(root, "data/mlb/staged/espn_game_context", day)
    rotowire_context = staged_context_counts_by_date(root, "data/mlb/staged/rotowire_context", day)
    baseball_reference_context = staged_context_counts_by_date(
        root,
        "data/mlb/staged/baseball_reference_boxscore_context",
        day,
    )
    espn_count = espn_context["dirs"]
    espn_rows = espn_context["rows"]
    rotowire_count = rotowire_context["dirs"]
    rotowire_rows = rotowire_context["rows"]
    baseball_reference_rows = baseball_reference_context["rows"]
    reconstructed_pregame_rows = baseball_reference_context["reconstructed_pregame_rows"]
    fidelity_context_rows = (
        espn_context["fidelity_rows"]
        + rotowire_context["fidelity_rows"]
        + baseball_reference_context["fidelity_rows"]
    )
    postgame_context_rows = (
        espn_context["postgame_rows"]
        + rotowire_context["postgame_rows"]
        + baseball_reference_context["postgame_rows"]
    )
    post_start_context_rows = (
        espn_context["post_start_rows"]
        + rotowire_context["post_start_rows"]
        + baseball_reference_context["post_start_rows"]
    )
    savant_count, savant_rows = staged_count_by_date(root, "data/mlb/staged/baseball_savant", day)
    schedule_games = schedule_games_for_date(root, day)
    advanced_rows = advanced_profile_rows(root, day)
    ballpark_count, ballpark_rows = staged_count_by_date(root, "data/mlb/staged/ballparks", day)
    umpire_count, umpire_rows = staged_count_by_date(root, "data/mlb/staged/umpires", day)
    wind_rows = wind_factor_rows(root)

    hard_blockers: list[str] = []
    warnings: list[str] = []
    if not pp_payloads and not github_pp_imports:
        hard_blockers.append("missing_mlb_prizepicks_snapshot")
    if not staged_market_count:
        hard_blockers.append("missing_normalized_primary_market_context")
    if "bettingpros_mlb_props" not in market_source_counts:
        warnings.append("missing_bettingpros_primary_market_context")
    if raw_odds and not staged_market_count:
        warnings.append("oddsapi_raw_present_but_not_normalized")
    if injury_count == 0:
        warnings.append("missing_injury_context_snapshot")
    if roster_rows_total < 700 and prior_identity_rows < 5000:
        warnings.append(f"thin_roster_identity_rows={roster_rows_total};prior_history_identity_rows={prior_identity_rows}")
    elif roster_rows_total < 700:
        warnings.append(
            f"thin_roster_snapshot_rows={roster_rows_total};prior_history_identity_rows={prior_identity_rows}"
        )
    if schedule_games == 0:
        warnings.append("missing_statsapi_schedule_rows_for_date")
    if espn_rows == 0 and rotowire_rows == 0 and baseball_reference_rows == 0:
        warnings.append("missing_lineup_pitcher_environment_context")
    elif fidelity_context_rows == 0:
        warnings.append("lineup_pitcher_environment_context_not_fidelity_valid")
    if reconstructed_pregame_rows:
        warnings.append(f"baseball_reference_reconstructed_pregame_lineup_rows={reconstructed_pregame_rows}")
    if postgame_context_rows:
        warnings.append(f"postgame_context_rows_excluded={postgame_context_rows}")
    if post_start_context_rows:
        warnings.append(f"post_start_context_rows_excluded={post_start_context_rows}")
    if rotowire_rows == 0:
        warnings.append("missing_rotowire_context")
    if savant_rows == 0:
        warnings.append("missing_dated_baseball_savant_context")
    if not advanced_rows:
        warnings.append("missing_advanced_profiles")
    if ballpark_rows == 0 and wind_rows == 0:
        warnings.append("missing_dated_ballpark_context")
    elif ballpark_rows == 0:
        warnings.append(f"thin_ballpark_profiles=0;wind_factor_rows={wind_rows}")
    if umpire_rows == 0:
        warnings.append("missing_dated_umpire_context")

    return {
        "date": day.strftime(DATE_FMT),
        "strict_runnable": not hard_blockers,
        "recommended_replay_snapshot": latest_payload(pp_payloads)
        or latest_payload([path for path, _ in github_pp_imports]),
        "prizepicks_mlb_snapshots": len(pp_payloads),
        "prizepicks_github_csv_imports": len(github_pp_imports),
        "prizepicks_github_mlb_rows": github_pp_rows,
        "raw_oddsapi_payloads": len(raw_odds),
        "staged_market_dirs": staged_market_count,
        "staged_market_rows": staged_market_rows,
        "market_source_counts": market_source_counts,
        "staged_oddsapi_dirs": staged_market_count,
        "staged_oddsapi_rows": staged_market_rows,
        "injury_dirs": injury_count,
        "injury_rows": injury_rows,
        "roster_dirs": roster_count,
        "roster_rows": roster_rows,
        "roster_bulk_dirs": roster_bulk_count,
        "roster_bulk_rows": roster_bulk_rows,
        "roster_rows_total": roster_rows_total,
        "prior_history_identity_rows": prior_identity_rows,
        "statsapi_schedule_games": schedule_games,
        "espn_game_context_dirs": espn_count,
        "espn_game_context_rows": espn_rows,
        "espn_fidelity_context_rows": espn_context["fidelity_rows"],
        "espn_postgame_context_rows": espn_context["postgame_rows"],
        "espn_post_start_context_rows": espn_context["post_start_rows"],
        "rotowire_context_dirs": rotowire_count,
        "rotowire_context_rows": rotowire_rows,
        "rotowire_fidelity_context_rows": rotowire_context["fidelity_rows"],
        "rotowire_postgame_context_rows": rotowire_context["postgame_rows"],
        "rotowire_post_start_context_rows": rotowire_context["post_start_rows"],
        "baseball_reference_context_dirs": baseball_reference_context["dirs"],
        "baseball_reference_context_rows": baseball_reference_rows,
        "baseball_reference_fidelity_context_rows": baseball_reference_context["fidelity_rows"],
        "baseball_reference_reconstructed_pregame_rows": reconstructed_pregame_rows,
        "baseball_reference_postgame_context_rows": baseball_reference_context["postgame_rows"],
        "baseball_reference_post_start_context_rows": baseball_reference_context["post_start_rows"],
        "fidelity_context_rows": fidelity_context_rows,
        "postgame_context_rows": postgame_context_rows,
        "post_start_context_rows": post_start_context_rows,
        "baseball_savant_dirs": savant_count,
        "baseball_savant_rows": savant_rows,
        "advanced_profile_rows": advanced_rows,
        "ballpark_dirs": ballpark_count,
        "ballpark_rows": ballpark_rows,
        "wind_factor_rows": wind_rows,
        "umpire_dirs": umpire_count,
        "umpire_rows": umpire_rows,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
    }


def write_outputs(output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"backfill_readiness_{stamp}.json"
    csv_path = output_dir / f"backfill_readiness_{stamp}.csv"
    md_path = output_dir / f"backfill_readiness_{stamp}.md"

    payload = {
        "generated_at": stamp,
        "strict_runnable_dates": [row["date"] for row in rows if row["strict_runnable"]],
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fieldnames = [
        "date",
        "strict_runnable",
        "prizepicks_mlb_snapshots",
        "prizepicks_github_csv_imports",
        "prizepicks_github_mlb_rows",
        "raw_oddsapi_payloads",
        "staged_market_rows",
        "market_source_counts",
        "injury_rows",
        "roster_rows",
        "roster_bulk_rows",
        "roster_rows_total",
        "prior_history_identity_rows",
        "statsapi_schedule_games",
        "espn_game_context_rows",
        "espn_fidelity_context_rows",
        "espn_postgame_context_rows",
        "espn_post_start_context_rows",
        "rotowire_context_rows",
        "rotowire_fidelity_context_rows",
        "rotowire_postgame_context_rows",
        "rotowire_post_start_context_rows",
        "baseball_reference_context_rows",
        "baseball_reference_fidelity_context_rows",
        "baseball_reference_reconstructed_pregame_rows",
        "baseball_reference_postgame_context_rows",
        "baseball_reference_post_start_context_rows",
        "fidelity_context_rows",
        "postgame_context_rows",
        "post_start_context_rows",
        "baseball_savant_rows",
        "advanced_profile_rows",
        "ballpark_rows",
        "wind_factor_rows",
        "umpire_rows",
        "recommended_replay_snapshot",
        "hard_blockers",
        "warnings",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            csv_row = {name: row.get(name, "") for name in fieldnames}
            csv_row["hard_blockers"] = ";".join(row["hard_blockers"])
            csv_row["warnings"] = ";".join(row["warnings"])
            writer.writerow(csv_row)

    lines = [
        "# MLB Backfill Readiness",
        "",
        f"Generated: {stamp}",
        "",
        "Strict-runnable dates require an MLB PrizePicks board snapshot or GitHub CSV import plus normalized primary market context.",
        "",
        "| Date | Strict | PP Raw | PP GitHub Rows | Market Rows | Market Sources | Injuries | Roster Snap | Prior IDs | Schedule Games | Raw Ctx | Fidelity Ctx | Excluded Ctx | Savant | Blockers |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        blockers = ", ".join(row["hard_blockers"]) or "-"
        raw_context = (
            row["espn_game_context_rows"]
            + row["rotowire_context_rows"]
            + row["baseball_reference_context_rows"]
        )
        excluded_context = row["postgame_context_rows"] + row["post_start_context_rows"]
        lines.append(
            "| {date} | {strict} | {pp} | {pp_github_rows} | {market_rows} | {market_sources} | {inj} | {rost} | {prior_ids} | {sched} | {raw_ctx} | {fid_ctx} | {excluded_ctx} | {sav} | {blockers} |".format(
                date=row["date"],
                strict="yes" if row["strict_runnable"] else "no",
                pp=row["prizepicks_mlb_snapshots"],
                pp_github_rows=row["prizepicks_github_mlb_rows"],
                market_rows=row["staged_market_rows"],
                market_sources=", ".join(row.get("market_source_counts", {}).keys()) or "-",
                inj=row["injury_rows"],
                rost=row["roster_rows_total"],
                prior_ids=row["prior_history_identity_rows"],
                sched=row["statsapi_schedule_games"],
                raw_ctx=raw_context,
                fid_ctx=row["fidelity_context_rows"],
                excluded_ctx=excluded_context,
                sav=row["baseball_savant_rows"],
                blockers=blockers,
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    latest_json = output_dir / "backfill_readiness_latest.json"
    latest_csv = output_dir / "backfill_readiness_latest.csv"
    latest_md = output_dir / "backfill_readiness_latest.md"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "md": str(md_path),
        "latest_json": str(latest_json),
        "latest_csv": str(latest_csv),
        "latest_md": str(latest_md),
    }


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    start = datetime.strptime(args.start, DATE_FMT).date()
    end = datetime.strptime(args.end, DATE_FMT).date()
    output_dir = args.output_dir or root / "data/mlb/audits"
    rows = [audit_date(root, day) for day in iter_dates(start, end)]
    paths = write_outputs(output_dir, rows)
    strict_dates = [row["date"] for row in rows if row["strict_runnable"]]
    print(f"[MLB_BACKFILL_AUDIT] dates={len(rows)} strict_runnable={strict_dates or []}")
    print(f"[MLB_BACKFILL_AUDIT] json={paths['json']}")
    print(f"[MLB_BACKFILL_AUDIT] csv={paths['csv']}")
    print(f"[MLB_BACKFILL_AUDIT] md={paths['md']}")


if __name__ == "__main__":
    main()

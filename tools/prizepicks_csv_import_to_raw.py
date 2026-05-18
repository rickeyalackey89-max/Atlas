#!/usr/bin/env python3
"""Convert imported PrizePicks CSV snapshots into Atlas PP-style raw JSON.

The GitHub prizepicks-data-mirror exports are flat CSV rows. Atlas replay
expects a small PrizePicks-like JSON payload with projection records and
included player/game records. This converter preserves tier information
(`standard`, `goblin`, `demon`) and writes a manifest with row-count checks.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Atlas.core.share_name_key import share_name_key  # noqa: E402

DEFAULT_IMPORT_DIR = ROOT / "data" / "import"
DEFAULT_OUT_DIR = ROOT / "data" / "raw"
DEFAULT_MANIFEST_DIR = ROOT / "data" / "archives" / "prizepicks_imports"
ODDSAPI_RAW_ROOT = ROOT / "data" / "archives" / "oddsapi" / "historical" / "raw"
TZ_CT = ZoneInfo("America/Chicago")

TEAM_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

# 2026-04-26 was not present in the local OddsAPI raw archive. These are only
# used to set the home flag and opponent context in the included game metadata.
MANUAL_HOME_BY_DATE_PAIR = {
    ("2026-04-26", frozenset({"TOR", "CLE"})): "CLE",
    ("2026-04-26", frozenset({"POR", "SAS"})): "SAS",
    ("2026-04-26", frozenset({"PHI", "BOS"})): "BOS",
    ("2026-04-26", frozenset({"HOU", "LAL"})): "LAL",
}


@dataclass(frozen=True)
class GameContext:
    game_id: str
    home: str
    away: str
    start_time: str


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_").lower()


def _parse_datetime(value: Any) -> datetime | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        text = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _pp_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(TZ_CT).isoformat(timespec="milliseconds")


def _target_date_from_name(path: Path) -> str:
    match = re.search(r"prizepicks_(\d{4}-\d{2}-\d{2})T", path.name)
    if not match:
        raise ValueError(f"Cannot infer target date from filename: {path.name}")
    return match.group(1)


def _is_combo(row: dict[str, str]) -> bool:
    player = _clean(row.get("player"))
    team = _clean(row.get("team"))
    stat = _clean(row.get("stat_type")).lower()
    if "combo" in stat:
        return True
    if "/" in team:
        return True
    if re.search(r"[A-Za-z]\s*(?:\+|&|/)\s*[A-Za-z]", player):
        return True
    return False


def _load_oddsapi_schedule(date: str) -> dict[tuple[str, frozenset[str]], str]:
    """Return {(ct_start, {team_a, team_b}): home_abbr} from local OddsAPI raw."""
    schedule: dict[tuple[str, frozenset[str]], str] = {}
    raw_dir = ODDSAPI_RAW_ROOT / date
    if not raw_dir.exists():
        return schedule

    for event_path in sorted(raw_dir.glob("event_*.json")):
        try:
            payload = json.loads(event_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        event = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        start_dt = _parse_datetime(event.get("commence_time"))
        if start_dt is None or start_dt.astimezone(TZ_CT).date().isoformat() != date:
            continue
        home = TEAM_NAME_TO_ABBR.get(_clean(event.get("home_team")), "")
        away = TEAM_NAME_TO_ABBR.get(_clean(event.get("away_team")), "")
        if not home or not away:
            continue
        schedule[(start_dt.astimezone(TZ_CT).isoformat(timespec="milliseconds"), frozenset({home, away}))] = home
    return schedule


def _game_context(row: dict[str, str], target_date: str, schedule: dict[tuple[str, frozenset[str]], str]) -> GameContext:
    start_dt = _parse_datetime(row.get("start_time"))
    start_time = _pp_time(start_dt)
    team = _clean(row.get("team")).upper()
    opp = _clean(row.get("description")).upper()
    pair = frozenset({team, opp})
    home = schedule.get((start_time, pair)) or MANUAL_HOME_BY_DATE_PAIR.get((target_date, pair), "")
    if not home and team and opp:
        home = sorted(pair)[-1]
    away = next((x for x in pair if x != home), "")
    game_id = _safe_id(f"{target_date}_{start_time}_{away}_{home}") or _safe_id(f"{target_date}_{team}_{opp}")
    return GameContext(game_id=game_id, home=home, away=away, start_time=start_time)


def _player_record(player_id: str, row: dict[str, str]) -> dict[str, Any]:
    player = _clean(row.get("player"))
    team = _clean(row.get("team")).upper()
    return {
        "type": "new_player",
        "id": player_id,
        "attributes": {
            "combo": False,
            "display_name": player,
            "image_url": None,
            "league": "NBA",
            "league_id": 7,
            "market": "",
            "name": player,
            "position": _clean(row.get("position")),
            "ppid": f"csv_import_{player_id}",
            "team": team,
            "team_name": team,
        },
        "relationships": {"league": {"data": {"type": "league", "id": "7"}}},
    }


def _game_record(ctx: GameContext, updated_at: str) -> dict[str, Any]:
    return {
        "type": "game",
        "id": ctx.game_id,
        "attributes": {
            "created_at": updated_at,
            "end_time": None,
            "external_game_id": f"NBA_game_{ctx.game_id}",
            "is_live": False,
            "metadata": {
                "game_id": f"NBA_game_{ctx.game_id}",
                "game_info": {
                    "teams": {
                        "away": {"abbreviation": ctx.away},
                        "home": {"abbreviation": ctx.home},
                    }
                },
                "league_name": "NBA",
                "status": "scheduled",
            },
            "start_time": ctx.start_time,
            "status": "scheduled",
            "updated_at": updated_at,
        },
        "relationships": {},
    }


def _projection_record(row: dict[str, str], ctx: GameContext, player_id: str, projection_id: str, main_line: float | None) -> dict[str, Any]:
    stat_raw = _clean(row.get("stat_type"))
    line = float(row["line"])
    odds_type = _clean(row.get("odds_type")).lower()
    updated_at = _pp_time(_parse_datetime(row.get("scraped_at"))) or ctx.start_time
    is_main = odds_type == "standard"
    return {
        "type": "projection",
        "id": projection_id,
        "attributes": {
            "adjusted_odds": False,
            "board_time": updated_at,
            "custom_image": None,
            "description": _clean(row.get("team")).upper(),
            "end_time": None,
            "event_type": "player",
            "flash_sale_line_score": None,
            "game_id": f"NBA_game_{ctx.game_id}",
            "group_key": f"{player_id}-{_safe_id(stat_raw)}-{ctx.game_id}",
            "in_game": False,
            "is_live": False,
            "is_live_scored": True,
            "is_main": is_main,
            "is_promo": False,
            "line_score": line,
            "main_line": main_line if main_line is not None else (line if is_main else None),
            "alt_line": None if is_main else line,
            "odds_type": odds_type,
            "projection_type": stat_raw,
            "rank": 1,
            "refundable": True,
            "start_time": ctx.start_time,
            "stat_display_name": stat_raw,
            "stat_type": stat_raw,
            "status": "pre_game",
            "today": True,
            "updated_at": updated_at,
        },
        "relationships": {
            "game": {"data": {"type": "game", "id": ctx.game_id}},
            "league": {"data": {"type": "league", "id": "7"}},
            "new_player": {"data": {"type": "new_player", "id": player_id}},
            "projection_type": {"data": {"type": "projection_type", "id": _safe_id(stat_raw)}},
            "score": {"data": None},
            "stat_type": {"data": {"type": "stat_type", "id": _safe_id(stat_raw)}},
        },
    }


def _read_target_rows(csv_path: Path, target_date: str) -> tuple[list[dict[str, str]], Counter[str]]:
    counters: Counter[str] = Counter()
    deduped: dict[tuple[str, str, str, str, str, str, str], dict[str, str]] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            counters["source_rows"] += 1
            if _clean(row.get("league")).upper() != "NBA":
                counters["drop_non_nba"] += 1
                continue
            start_dt = _parse_datetime(row.get("start_time"))
            if start_dt is None:
                counters["drop_missing_start"] += 1
                continue
            if start_dt.astimezone(TZ_CT).date().isoformat() != target_date:
                counters["drop_other_slate_date"] += 1
                continue
            if _is_combo(row):
                counters["drop_combo"] += 1
                continue
            try:
                float(row.get("line") or "")
            except ValueError:
                counters["drop_bad_line"] += 1
                continue
            if not _clean(row.get("projection_id")) or not _clean(row.get("player")) or not _clean(row.get("team")):
                counters["drop_missing_identity"] += 1
                continue
            key = (
                _clean(row.get("projection_id")),
                _clean(row.get("player")),
                _clean(row.get("team")).upper(),
                _clean(row.get("stat_type")),
                _clean(row.get("line")),
                _clean(row.get("odds_type")).lower(),
                _pp_time(start_dt),
            )
            deduped[key] = row
            counters["target_rows"] += 1
    counters["deduped_rows"] = len(deduped)
    return list(deduped.values()), counters


def _main_lines(rows: list[dict[str, str]], target_date: str, schedule: dict[tuple[str, frozenset[str]], str]) -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    for row in rows:
        if _clean(row.get("odds_type")).lower() != "standard":
            continue
        ctx = _game_context(row, target_date, schedule)
        key = (_safe_id(share_name_key(_clean(row.get("player")))), _clean(row.get("stat_type")).upper(), ctx.game_id)
        try:
            out[key] = float(row["line"])
        except ValueError:
            continue
    return out


def convert_file(csv_path: Path, out_dir: Path, manifest_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    target_date = _target_date_from_name(csv_path)
    rows, counters = _read_target_rows(csv_path, target_date)
    schedule = _load_oddsapi_schedule(target_date)
    main_lines = _main_lines(rows, target_date, schedule)

    included: dict[tuple[str, str], dict[str, Any]] = {}
    projections: list[dict[str, Any]] = []
    tier_counts: Counter[str] = Counter()
    stat_counts: Counter[str] = Counter()
    game_counts: Counter[str] = Counter()

    for row in rows:
        ctx = _game_context(row, target_date, schedule)
        player_id = _safe_id(share_name_key(_clean(row.get("player")))) or _safe_id(_clean(row.get("player")))
        stat_key = _clean(row.get("stat_type")).upper()
        main_line = main_lines.get((player_id, stat_key, ctx.game_id))
        projection_id = _safe_id(
            "|".join(
                [
                    "csv_pp",
                    _clean(row.get("projection_id")),
                    player_id,
                    stat_key,
                    _clean(row.get("line")),
                    _clean(row.get("odds_type")).lower(),
                    ctx.game_id,
                ]
            )
        )

        updated_at = _pp_time(_parse_datetime(row.get("scraped_at"))) or ctx.start_time
        included.setdefault(("game", ctx.game_id), _game_record(ctx, updated_at))
        included.setdefault(("new_player", player_id), _player_record(player_id, row))
        projections.append(_projection_record(row, ctx, player_id, projection_id, main_line))
        tier_counts[_clean(row.get("odds_type")).lower()] += 1
        stat_counts[_clean(row.get("stat_type")).upper()] += 1
        game_counts[ctx.game_id] += 1

    payload = {
        "data": projections,
        "included": list(included.values()),
        "links": {},
        "meta": {
            "source": "prizepicks_csv_import",
            "source_file": str(csv_path),
            "slate_date": target_date,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "preserves_odds_type": True,
        },
    }

    scrape_dt = _parse_datetime(rows[0].get("scraped_at")) if rows else None
    suffix = scrape_dt.astimezone(TZ_CT).strftime("%H%M%S") if scrape_dt else "000000"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"prizepicks_{target_date.replace('-', '')}_{suffix}_fulltier.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = {
        "source_file": str(csv_path),
        "out_path": str(out_path),
        "target_date": target_date,
        "counts": dict(counters),
        "projection_count": len(projections),
        "included_count": len(payload["included"]),
        "tier_counts": dict(tier_counts),
        "stat_counts_top30": dict(stat_counts.most_common(30)),
        "game_count": len(game_counts),
        "game_rows": dict(game_counts),
        "schedule_source": "oddsapi_raw" if schedule else "manual_or_pair_fallback",
    }
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{out_path.stem}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_path, manifest_path, manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_IMPORT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--files", nargs="*", type=Path, help="Specific CSV files. Defaults to data/import/prizepicks_2026-04-*.csv.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    files = args.files or sorted(args.input_dir.glob("prizepicks_2026-04-*.csv"))
    if not files:
        raise FileNotFoundError(f"No import CSVs found in {args.input_dir}")

    for csv_path in files:
        out_path, manifest_path, manifest = convert_file(csv_path, args.out_dir, args.manifest_dir)
        print(f"[CONVERT] {csv_path.name} -> {out_path.name}")
        print(f"          projections={manifest['projection_count']} games={manifest['game_count']} tiers={manifest['tier_counts']}")
        print(f"          manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Convert PP-only OddsAPI historical raw responses into PrizePicks-style raw JSON.

The generated payload is intentionally minimal but compatible with
``Atlas.stages.rebuild.rebuild_today.run_rebuild``. It is meant for replay
preparation when the original PrizePicks board snapshot is unavailable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Atlas.core.share_name_key import share_name_key  # noqa: E402

RAW_ODDSAPI_ROOT = ROOT / "data" / "archives" / "oddsapi" / "historical" / "raw"
DEFAULT_OUT_DIR = ROOT / "data" / "raw"
DEFAULT_MANIFEST_DIR = ROOT / "data" / "archives" / "oddsapi" / "historical" / "pp_style"
ROSTER_MAP = ROOT / "data" / "input" / "roster_map.csv"
GAMELOGS = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
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


MARKET_TO_STAT = {
    "player_points": "POINTS",
    "player_rebounds": "REBOUNDS",
    "player_assists": "ASSISTS",
    "player_threes": "3-PT MADE",
    "player_blocks": "BLOCKS",
    "player_steals": "STEALS",
    "player_turnovers": "TURNOVERS",
    "player_points_rebounds_assists": "PTS+REBS+ASTS",
    "player_points_rebounds": "PTS+REBS",
    "player_points_assists": "PTS+ASTS",
    "player_rebounds_assists": "REBS+ASTS",
    "player_blocks_steals": "BLKS+STLS",
}


@dataclass(frozen=True)
class TeamContext:
    home_name: str
    away_name: str
    home_abbr: str
    away_abbr: str


def _parse_utc(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        text = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _pp_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(TZ_CT).isoformat(timespec="milliseconds")


def _safe_id(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")


def _name_aliases(name: str) -> list[str]:
    base = share_name_key(name)
    aliases = [base] if base else []
    parts = base.split()
    if len(parts) >= 3 and len(parts[0]) == 1 and len(parts[1]) == 1:
        aliases.append(" ".join([parts[0] + parts[1], *parts[2:]]))
    compact = re.sub(r"\b([a-z])\s+([a-z])\b", r"\1\2", base, count=1)
    if compact and compact not in aliases:
        aliases.append(compact)
    return aliases


def _load_event_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _load_roster_map() -> dict[str, str]:
    if not ROSTER_MAP.exists():
        return {}
    df = pd.read_csv(ROSTER_MAP, low_memory=False)
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        team = str(row.get("team", "") or "").strip().upper()
        if team:
            for key in _name_aliases(str(row.get("player", ""))):
                out[key] = team
    return out


def _load_gamelog_team_map() -> dict[str, list[tuple[str, str, str]]]:
    if not GAMELOGS.exists():
        return {}
    usecols = ["game_date", "player", "team", "opp"]
    df = pd.read_csv(GAMELOGS, usecols=lambda c: c in usecols, low_memory=False)
    df["game_date_norm"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out: dict[str, list[tuple[str, str, str]]] = {}
    for _, row in df.dropna(subset=["game_date_norm"]).iterrows():
        team = str(row.get("team", "") or "").strip().upper()
        opp = str(row.get("opp", "") or "").strip().upper()
        date = str(row.get("game_date_norm", "") or "")
        if team:
            for key in _name_aliases(str(row.get("player", ""))):
                out.setdefault(key, []).append((date, team, opp))
    return out


def _infer_team(
    player: str,
    date: str,
    ctx: TeamContext,
    roster: dict[str, str],
    gamelogs: dict[str, list[tuple[str, str, str]]],
) -> str:
    valid = {ctx.home_abbr, ctx.away_abbr}

    for key in _name_aliases(player):
        for row_date, team, opp in gamelogs.get(key, []):
            if row_date == date and team in valid:
                return team
            if row_date == date and opp in valid and team in valid:
                return team

    for key in _name_aliases(player):
        team = roster.get(key, "")
        if team in valid:
            return team

    for key in _name_aliases(player):
        for _, team, opp in gamelogs.get(key, []):
            if team in valid and opp in valid:
                return team

    return ""


def _pair_player_lines(market: dict[str, Any]) -> list[tuple[str, float]]:
    paired: dict[tuple[str, float], set[str]] = {}
    for outcome in market.get("outcomes", []) or []:
        name = str(outcome.get("description", "") or "").strip()
        side = str(outcome.get("name", "") or "").strip().lower()
        point = outcome.get("point")
        if not name or point is None or side not in {"over", "under"}:
            continue
        key = (name, float(point))
        paired.setdefault(key, set()).add(side)
    return [(player, line) for (player, line), sides in paired.items() if {"over", "under"} <= sides]


def _projection_record(
    *,
    projection_id: str,
    player_id: str,
    game_id: str,
    stat_raw: str,
    line: float,
    team: str,
    start_time: str,
    updated_at: str,
) -> dict[str, Any]:
    return {
        "type": "projection",
        "id": projection_id,
        "attributes": {
            "adjusted_odds": False,
            "board_time": updated_at,
            "custom_image": None,
            "description": team,
            "end_time": None,
            "event_type": "player",
            "flash_sale_line_score": None,
            "game_id": f"NBA_game_{game_id}",
            "group_key": f"{player_id}-{_safe_id(stat_raw)}-{game_id}",
            "in_game": False,
            "is_live": False,
            "is_live_scored": True,
            "is_promo": False,
            "line_score": line,
            "odds_type": "standard",
            "projection_type": stat_raw,
            "rank": 1,
            "refundable": True,
            "start_time": start_time,
            "stat_display_name": stat_raw,
            "stat_type": stat_raw,
            "status": "pre_game",
            "today": True,
            "updated_at": updated_at,
        },
        "relationships": {
            "game": {"data": {"type": "game", "id": game_id}},
            "league": {"data": {"type": "league", "id": "7"}},
            "new_player": {"data": {"type": "new_player", "id": player_id}},
            "projection_type": {"data": {"type": "projection_type", "id": "1"}},
            "score": {"data": None},
            "stat_type": {"data": {"type": "stat_type", "id": _safe_id(stat_raw)}},
        },
    }


def convert_date(date: str, out_dir: Path, manifest_dir: Path) -> tuple[Path, dict[str, Any]]:
    raw_dir = RAW_ODDSAPI_ROOT / date
    if not raw_dir.exists():
        raise FileNotFoundError(f"OddsAPI raw directory not found: {raw_dir}")

    roster = _load_roster_map()
    gamelogs = _load_gamelog_team_map()
    data: list[dict[str, Any]] = []
    included_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    skipped: dict[str, int] = {
        "non_target_slate_game": 0,
        "missing_team_abbr": 0,
        "missing_bookmaker": 0,
        "unsupported_market": 0,
        "team_unresolved": 0,
    }
    unresolved_players: dict[str, int] = {}

    for event_path in sorted(raw_dir.glob("event_*.json")):
        event = _load_event_file(event_path)
        start_dt = _parse_utc(event.get("commence_time"))
        if start_dt is None:
            continue
        slate_date = start_dt.astimezone(TZ_CT).date().isoformat()
        if slate_date != date:
            skipped["non_target_slate_game"] += 1
            continue

        home_name = str(event.get("home_team", "") or "").strip()
        away_name = str(event.get("away_team", "") or "").strip()
        ctx = TeamContext(
            home_name=home_name,
            away_name=away_name,
            home_abbr=TEAM_NAME_TO_ABBR.get(home_name, ""),
            away_abbr=TEAM_NAME_TO_ABBR.get(away_name, ""),
        )
        if not ctx.home_abbr or not ctx.away_abbr:
            skipped["missing_team_abbr"] += 1
            continue

        game_id = _safe_id(str(event.get("id", "") or f"{ctx.away_abbr}_{ctx.home_abbr}_{date}"))
        start_time = _pp_time(start_dt)
        game_updated = _pp_time(_parse_utc(event.get("last_update")) or start_dt)
        included_by_key[("game", game_id)] = {
            "type": "game",
            "id": game_id,
            "attributes": {
                "created_at": game_updated,
                "end_time": None,
                "external_game_id": f"NBA_game_{game_id}",
                "is_live": False,
                "metadata": {
                    "game_id": f"NBA_game_{game_id}",
                    "game_info": {
                        "teams": {
                            "away": {"abbreviation": ctx.away_abbr},
                            "home": {"abbreviation": ctx.home_abbr},
                        }
                    },
                    "league_name": "NBA",
                    "status": "scheduled",
                },
                "start_time": start_time,
                "status": "scheduled",
                "updated_at": game_updated,
            },
            "relationships": {},
        }

        prizepicks_books = [
            bm for bm in event.get("bookmakers", []) or [] if str(bm.get("key", "")).lower() == "prizepicks"
        ]
        if not prizepicks_books:
            skipped["missing_bookmaker"] += 1
            continue

        for bm in prizepicks_books:
            book_updated = _pp_time(_parse_utc(bm.get("last_update")) or start_dt)
            for market in bm.get("markets", []) or []:
                stat_raw = MARKET_TO_STAT.get(str(market.get("key", "")))
                if not stat_raw:
                    skipped["unsupported_market"] += 1
                    continue
                market_updated = _pp_time(_parse_utc(market.get("last_update")) or _parse_utc(bm.get("last_update")) or start_dt)
                updated_at = market_updated or book_updated
                for player, line in _pair_player_lines(market):
                    team = _infer_team(player, date, ctx, roster, gamelogs)
                    if not team:
                        skipped["team_unresolved"] += 1
                        unresolved_players[player] = unresolved_players.get(player, 0) + 1
                        continue
                    player_id = _safe_id(share_name_key(player)) or _safe_id(player)
                    included_by_key[("new_player", player_id)] = {
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
                            "position": "",
                            "ppid": f"oddsapi_pp_{player_id}",
                            "team": team,
                            "team_name": team,
                        },
                        "relationships": {"league": {"data": {"type": "league", "id": "7"}}},
                    }
                    projection_id = _safe_id(f"oddsapi_pp_{date}_{game_id}_{player_id}_{stat_raw}_{line:g}")
                    data.append(
                        _projection_record(
                            projection_id=projection_id,
                            player_id=player_id,
                            game_id=game_id,
                            stat_raw=stat_raw,
                            line=line,
                            team=team,
                            start_time=start_time,
                            updated_at=updated_at,
                        )
                    )

    payload = {
        "data": data,
        "included": list(included_by_key.values()),
        "links": {},
        "meta": {
            "source": "oddsapi_historical_prizepicks_bookmaker",
            "slate_date": date,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"prizepicks_{date.replace('-', '')}_173000.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = {
        "date": date,
        "source_raw_dir": str(raw_dir),
        "out_path": str(out_path),
        "projection_count": len(data),
        "included_count": len(payload["included"]),
        "skipped": skipped,
        "unresolved_players_top20": sorted(
            unresolved_players.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )[:20],
    }
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"prizepicks_{date.replace('-', '')}_173000_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_path, manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", required=True, help="Comma-separated YYYY-MM-DD dates.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir)
    manifest_dir = Path(args.manifest_dir)
    for date in [d.strip() for d in args.dates.split(",") if d.strip()]:
        out_path, manifest = convert_date(date, out_dir, manifest_dir)
        print(
            "[ODDSAPI->PP] {date}: projections={projections} included={included} "
            "skipped={skipped} -> {path}".format(
                date=date,
                projections=manifest["projection_count"],
                included=manifest["included_count"],
                skipped=manifest["skipped"],
                path=out_path,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

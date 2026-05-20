"""Normalization for Rotowire MLB context snapshots."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

_LINEUP_BLOCK_RE = re.compile(r'<div class="lineup (?P<classes>[^"]*)">(?P<body>.*?)(?=<div class="lineup [^"]*"|$)', re.S)
_TEAM_RE = re.compile(
    r'<div class="lineup__team is-(?P<side>visit|home)">.*?alt="(?P<alt>[^"]*)".*?'
    r'<div class="lineup__abbr">(?P<abbr>.*?)</div>',
    re.S,
)
_TEAM_NAME_RE = re.compile(r'<div class="lineup__mteam is-(?P<side>visit|home)">(?P<body>.*?)<span', re.S)
_LINEUP_LIST_RE = re.compile(r'<ul class="lineup__list is-(?P<side>visit|home)">(?P<body>.*?)</ul>', re.S)
_PITCHER_RE = re.compile(
    r'lineup__player-highlight-name">\s*<a href="(?P<href>[^"]+)">(?P<name>.*?)</a>\s*'
    r'<span class="lineup__throws">(?P<throws>.*?)</span>.*?'
    r'lineup__player-highlight-stats">\s*(?P<stats>.*?)\s*</div>',
    re.S,
)
_STATUS_RE = re.compile(r'<li class="lineup__status (?P<status_class>[^"]*)">(?P<body>.*?)</li>', re.S)
_PLAYER_RE = re.compile(
    r'<li class="lineup__player">\s*<div class="lineup__pos">(?P<position>.*?)</div>\s*'
    r'<a title="(?P<title>[^"]*)" href="(?P<href>[^"]+)">(?P<label>.*?)</a>\s*'
    r'(?:<span class="lineup__bats">(?P<bats>.*?)</span>)?',
    re.S,
)


def normalize_rotowire_mlb_context(payload: dict[str, Any], *, snapshot_id: str = "") -> dict[str, Any]:
    """Normalize raw Rotowire MLB context pages into staged row groups."""

    page_rows = _raw_page_rows(payload)
    daily_page = _page_by_name(payload, "daily_lineups")
    bullpen_table_page = _page_by_name(payload, "bullpen_usage_table")
    reliever_table_page = _page_by_name(payload, "reliever_usage_table")
    game_date = _clean_str(payload.get("game_date"))
    historical_backfill = _is_historical_date_query(
        payload,
        game_date=game_date,
        snapshot_id=snapshot_id,
    )
    context_timing = "historical_pregame_lineup_backfill" if historical_backfill else ""
    lineup_content_timing = "pregame_starting_lineup" if historical_backfill else ""
    parsed = _parse_daily_lineups(
        daily_page.get("body", "") if daily_page else "",
        snapshot_id=snapshot_id,
        game_date=game_date,
        context_timing=context_timing,
        lineup_content_timing=lineup_content_timing,
        historical_backfill=historical_backfill,
    )
    bullpens = _parse_bullpen_usage_table(
        bullpen_table_page.get("body", "") if bullpen_table_page else "",
        snapshot_id=snapshot_id,
        game_date=game_date,
    )
    relievers = _parse_reliever_usage_table(
        reliever_table_page.get("body", "") if reliever_table_page else "",
        snapshot_id=snapshot_id,
        game_date=game_date,
    )
    parser_status = {
        "daily_lineups": "parsed" if daily_page else "missing",
        "pitchers": "parsed_from_daily_lineups" if parsed["pitchers"] else "empty",
        "batting_orders": "parsed_from_daily_lineups" if parsed["batting_orders"] else "empty",
        "bullpens": "parsed_from_bullpen_usage_table" if bullpens["rows"] else bullpens["status"],
        "hitter_context": "parsed_from_reliever_usage_table" if relievers["rows"] else relievers["status"],
        "environment": "parsed_from_daily_lineups" if parsed["environment"] else "empty",
    }
    return {
        "snapshot_id": snapshot_id,
        "source": "rotowire_mlb_context",
        "game_date": game_date,
        "context_timing": context_timing,
        "lineup_content_timing": lineup_content_timing,
        "historical_date_query_verified": historical_backfill,
        "raw_pages": page_rows,
        "daily_lineups": parsed["daily_lineups"],
        "pitchers": parsed["pitchers"],
        "batting_orders": parsed["batting_orders"],
        "bullpens": bullpens["rows"],
        "hitter_context": relievers["rows"],
        "environment": parsed["environment"],
        "parse_warnings": parsed["warnings"] + bullpens["warnings"] + relievers["warnings"],
        "parser_status": parser_status,
    }


def write_rotowire_mlb_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a saved Rotowire context snapshot and write JSONL artifacts."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or "rotowire_mlb_context")
    normalized = normalize_rotowire_mlb_context(payload, snapshot_id=str(manifest.get("snapshot_id") or resolved_run_id))

    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "rotowire_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "raw_pages": _write_jsonl(output_dir / "raw_pages.jsonl", normalized["raw_pages"]),
        "daily_lineups": _write_jsonl(output_dir / "daily_lineups.jsonl", normalized["daily_lineups"]),
        "pitchers": _write_jsonl(output_dir / "pitchers.jsonl", normalized["pitchers"]),
        "batting_orders": _write_jsonl(output_dir / "batting_orders.jsonl", normalized["batting_orders"]),
        "bullpens": _write_jsonl(output_dir / "bullpens.jsonl", normalized["bullpens"]),
        "hitter_context": _write_jsonl(output_dir / "hitter_context.jsonl", normalized["hitter_context"]),
        "environment": _write_jsonl(output_dir / "environment.jsonl", normalized["environment"]),
    }
    out = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": "rotowire_mlb_context",
        "game_date": normalized["game_date"],
        "context_timing": normalized["context_timing"],
        "lineup_content_timing": normalized["lineup_content_timing"],
        "historical_date_query_verified": normalized["historical_date_query_verified"],
        "output_dir": str(output_dir),
        "row_counts": {key: _count_jsonl(Path(path)) for key, path in artifacts.items()},
        "artifacts": artifacts,
        "parser_status": normalized["parser_status"],
        "parse_warnings": normalized["parse_warnings"],
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _parse_daily_lineups(
    body: str,
    *,
    snapshot_id: str,
    game_date: str,
    context_timing: str,
    lineup_content_timing: str,
    historical_backfill: bool,
) -> dict[str, list[dict[str, Any]]]:
    daily_lineups: list[dict[str, Any]] = []
    pitchers: list[dict[str, Any]] = []
    batting_orders: list[dict[str, Any]] = []
    environment: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not body:
        return {
            "daily_lineups": daily_lineups,
            "pitchers": pitchers,
            "batting_orders": batting_orders,
            "environment": environment,
            "warnings": [{"page": "daily_lineups", "warning": "empty_body"}],
        }

    blocks = list(_LINEUP_BLOCK_RE.finditer(body))
    if not blocks:
        warnings.append({"page": "daily_lineups", "warning": "no_lineup_blocks"})

    for game_index, match in enumerate(blocks, start=1):
        classes = _clean_str(match.group("classes"))
        block = match.group("body")
        row_status = _lineup_status_fields(classes=classes, historical_backfill=historical_backfill)
        teams = _extract_teams(block)
        names = _extract_team_names(block)
        game_id = _first_match(block, r'data-gid="(?P<value>\d+)"')
        box_score_href = _first_match(block, r'<a href="(?P<value>/baseball/box-score/[^"]+)" class="lineup__matchup"')
        game_time_et = _clean_str(_first_match(block, r'<div class="lineup__time">(?P<value>.*?)</div>'))
        env_row = _environment_row(
            block,
            snapshot_id=snapshot_id,
            game_date=game_date,
            game_index=game_index,
            game_id=game_id,
            classes=classes,
            teams=teams,
            names=names,
            game_time_et=game_time_et,
            box_score_href=box_score_href,
        )
        environment.append(env_row)

        for side, list_body in _lineup_lists(block).items():
            opponent_side = "home" if side == "visit" else "visit"
            team = teams.get(side, {})
            opponent = teams.get(opponent_side, {})
            team_name = names.get(side) or team.get("abbr", "")
            opponent_name = names.get(opponent_side) or opponent.get("abbr", "")
            pitcher = _extract_pitcher(list_body)
            status = _extract_lineup_status(list_body)
            if pitcher:
                pitchers.append(
                    {
                        "source": "rotowire_mlb_context",
                        "snapshot_id": snapshot_id,
                        "context_timing": context_timing,
                        "lineup_content_timing": lineup_content_timing,
                        "game_date": game_date,
                        "game_index": game_index,
                        "game_id": game_id,
                        "team_side": side,
                        "team_abbr": team.get("abbr", ""),
                        "team_name": team_name,
                        "opponent_abbr": opponent.get("abbr", ""),
                        "opponent_name": opponent_name,
                        "pitcher_name": pitcher["name"],
                        "rotowire_player_id": pitcher["player_id"],
                        "rotowire_href": pitcher["href"],
                        "throws": pitcher["throws"],
                        "pitcher_stats": pitcher["stats"],
                        "lineup_status": status["label"],
                        "lineup_status_key": status["status_key"],
                        "game_time_et": game_time_et,
                        **row_status,
                    }
                )
            players = _extract_players(list_body)
            for batting_order, player in enumerate(players, start=1):
                row = {
                    "source": "rotowire_mlb_context",
                    "snapshot_id": snapshot_id,
                    "context_timing": context_timing,
                    "lineup_content_timing": lineup_content_timing,
                    "game_date": game_date,
                    "game_index": game_index,
                    "game_id": game_id,
                    "team_side": side,
                    "team_abbr": team.get("abbr", ""),
                    "team_name": team_name,
                    "opponent_abbr": opponent.get("abbr", ""),
                    "opponent_name": opponent_name,
                    "batting_order": batting_order,
                    "player_name": player["title"],
                    "display_name": player["label"],
                    "rotowire_player_id": player["player_id"],
                    "rotowire_href": player["href"],
                    "position": player["position"],
                    "bats": player["bats"],
                    "opposing_pitcher": pitcher["name"] if pitcher else "",
                    "opposing_pitcher_throws": pitcher["throws"] if pitcher else "",
                    "lineup_status": status["label"],
                    "lineup_status_key": status["status_key"],
                    "game_time_et": game_time_et,
                    **row_status,
                }
                daily_lineups.append(row)
                batting_orders.append(row)

    return {
        "daily_lineups": daily_lineups,
        "pitchers": pitchers,
        "batting_orders": batting_orders,
        "environment": environment,
        "warnings": warnings,
    }


def _parse_bullpen_usage_table(body: str, *, snapshot_id: str, game_date: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not body:
        return {
            "rows": rows,
            "warnings": [{"page": "bullpen_usage_table", "warning": "missing_body"}],
            "status": "missing_table",
        }
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return {
            "rows": rows,
            "warnings": [{"page": "bullpen_usage_table", "warning": "invalid_json", "detail": str(exc)}],
            "status": "invalid_json",
        }
    if not isinstance(payload, dict):
        return {
            "rows": rows,
            "warnings": [{"page": "bullpen_usage_table", "warning": "unexpected_payload_type"}],
            "status": "unexpected_payload",
        }

    for team_abbr, players in payload.items():
        if not isinstance(players, list):
            warnings.append({"page": "bullpen_usage_table", "warning": "team_payload_not_list", "team": team_abbr})
            continue
        player_rows = [player for player in players if isinstance(player, dict)]
        pitcher_count = len(player_rows)
        last2_total = sum(_number(player.get("last2")) for player in player_rows)
        last3_total = sum(_number(player.get("last3")) for player in player_rows)
        last5_total = sum(_number(player.get("last5")) for player in player_rows)
        last3_values = [_number(player.get("last3")) for player in player_rows]
        last5_values = [_number(player.get("last5")) for player in player_rows]
        heavy_arms_last3 = sum(1 for value in last3_values if value >= 30.0)
        recent_arms_last2 = sum(1 for player in player_rows if _number(player.get("last2")) > 0.0)
        injury_count = sum(1 for player in player_rows if _clean_str(player.get("inj")))
        avg_last3 = last3_total / pitcher_count if pitcher_count else 0.0
        avg_last2 = last2_total / pitcher_count if pitcher_count else 0.0
        fatigue_score = _clamp(((avg_last3 - 18.0) / 28.0) + (0.05 * heavy_arms_last3), -0.30, 0.70)
        late_game_run_score = _clamp((avg_last2 - 8.0) / 20.0, -0.20, 0.35)
        flags = []
        if not pitcher_count:
            flags.append("bullpen_usage_table_empty_team")
        if injury_count:
            flags.append("bullpen_injury_notes_present")
        rows.append(
            {
                "source": "rotowire_mlb_context",
                "snapshot_id": snapshot_id,
                "game_date": game_date,
                "team_abbr": _clean_str(team_abbr).upper(),
                "team": _clean_str(team_abbr).upper(),
                "pitcher_count": pitcher_count,
                "last2_total": round(last2_total, 3),
                "last3_total": round(last3_total, 3),
                "last5_total": round(last5_total, 3),
                "last3_max": round(max(last3_values), 3) if last3_values else 0.0,
                "last5_max": round(max(last5_values), 3) if last5_values else 0.0,
                "heavy_arms_last3": heavy_arms_last3,
                "recent_arms_last2": recent_arms_last2,
                "injury_count": injury_count,
                "bullpen_fatigue_score": round(fatigue_score, 6),
                "bullpen_quality_score": 0.0,
                "late_game_run_score": round(late_game_run_score, 6),
                "handedness_balance_score": 0.0,
                "confidence": 0.65 if pitcher_count else 0.0,
                "flags": flags,
            }
        )
    return {
        "rows": rows,
        "warnings": warnings,
        "status": "empty" if not rows else "parsed_from_bullpen_usage_table",
    }


def _parse_reliever_usage_table(body: str, *, snapshot_id: str, game_date: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not body:
        return {
            "rows": rows,
            "warnings": [{"page": "reliever_usage_table", "warning": "missing_body"}],
            "status": "missing_table",
        }
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return {
            "rows": rows,
            "warnings": [{"page": "reliever_usage_table", "warning": "invalid_json", "detail": str(exc)}],
            "status": "invalid_json",
        }
    if not isinstance(payload, list):
        return {
            "rows": rows,
            "warnings": [{"page": "reliever_usage_table", "warning": "unexpected_payload_type"}],
            "status": "unexpected_payload",
        }

    for player in payload:
        if not isinstance(player, dict):
            continue
        player_name = _clean_str(player.get("player"))
        team = _clean_str(player.get("team")).upper()
        if not (player_name and team):
            continue
        rows.append(
            {
                "source": "rotowire_mlb_context",
                "snapshot_id": snapshot_id,
                "game_date": game_date,
                "context_type": "recent_reliever_usage",
                "team_abbr": team,
                "team": team,
                "player_name": player_name,
                "rotowire_player_id": _clean_str(player.get("id")),
                "rotowire_href": _clean_str(player.get("url")),
                "position": _clean_str(player.get("position")),
                "opponent_text": _clean_str(player.get("vs")),
                "innings_pitched": _number(player.get("ip")),
                "hits_allowed": _number(player.get("hits")),
                "runs_allowed": _number(player.get("runs")),
                "walks_allowed": _number(player.get("walks")),
                "strikeouts": _number(player.get("strikes")),
                "confidence": 0.45,
                "flags": [],
            }
        )
    return {
        "rows": rows,
        "warnings": warnings,
        "status": "empty" if not rows else "parsed_from_reliever_usage_table",
    }


def _raw_page_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for page in payload.get("data", []) or []:
        body = str(page.get("body") or "")
        rows.append(
            {
                "source": "rotowire_mlb_context",
                "page": _clean_str(page.get("page")),
                "url": _clean_str(page.get("url")),
                "resolved_url": _clean_str(page.get("resolved_url")),
                "status_code": page.get("status_code"),
                "content_type": _clean_str(page.get("content_type")),
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "body_length": len(body),
            }
        )
    return rows


def _page_by_name(payload: dict[str, Any], page_name: str) -> dict[str, Any] | None:
    for page in payload.get("data", []) or []:
        if page.get("page") == page_name:
            return page
    return None


def _is_historical_date_query(payload: dict[str, Any], *, game_date: str, snapshot_id: str) -> bool:
    requested = _parse_date(game_date)
    captured = _snapshot_date(snapshot_id)
    if not (requested and captured and requested < captured):
        return False
    daily_page = _page_by_name(payload, "daily_lineups") or {}
    resolved_url = _clean_str(daily_page.get("resolved_url"))
    date_markers = {
        f"date={requested.isoformat()}",
        f"date={requested.year}-{requested.month}-{requested.day}",
        f"date={requested:%Y%m%d}",
    }
    return any(marker in resolved_url for marker in date_markers)


def _snapshot_date(snapshot_id: str) -> date | None:
    match = re.search(r"(?P<date>20\d{6})T", snapshot_id or "")
    if not match:
        return None
    text = match.group("date")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    text = _clean_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _lineup_status_fields(*, classes: str, historical_backfill: bool) -> dict[str, Any]:
    if not historical_backfill:
        return {
            "game_started": "has-started" in classes,
            "slate_status": classes,
        }
    return {
        "game_started": False,
        "historical_date_query_verified": True,
        "raw_game_started": "has-started" in classes,
        "slate_status": "historical_pregame_lineup_backfill",
        "raw_slate_status": classes,
        "flags": ["historical_rotowire_pregame_lineup_backfill"],
    }


def _extract_teams(block: str) -> dict[str, dict[str, str]]:
    teams: dict[str, dict[str, str]] = {}
    for match in _TEAM_RE.finditer(block):
        side = match.group("side")
        teams[side] = {
            "abbr": _clean_str(match.group("abbr") or match.group("alt")),
            "logo_alt": _clean_str(match.group("alt")),
        }
    return teams


def _extract_team_names(block: str) -> dict[str, str]:
    names = {}
    for match in _TEAM_NAME_RE.finditer(block):
        names[match.group("side")] = _strip_tags(match.group("body"))
    return names


def _lineup_lists(block: str) -> dict[str, str]:
    return {match.group("side"): match.group("body") for match in _LINEUP_LIST_RE.finditer(block)}


def _extract_pitcher(list_body: str) -> dict[str, str] | None:
    match = _PITCHER_RE.search(list_body)
    if not match:
        return None
    href = _clean_str(match.group("href"))
    return {
        "name": _strip_tags(match.group("name")),
        "href": href,
        "player_id": _rotowire_player_id(href),
        "throws": _strip_tags(match.group("throws")),
        "stats": _strip_tags(match.group("stats")).replace("\xa0", " "),
    }


def _extract_lineup_status(list_body: str) -> dict[str, str]:
    match = _STATUS_RE.search(list_body)
    if not match:
        return {"label": "", "status_key": ""}
    label = _strip_tags(match.group("body"))
    status_class = _clean_str(match.group("status_class"))
    return {
        "label": label,
        "status_key": status_class.replace("is-", ""),
    }


def _extract_players(list_body: str) -> list[dict[str, str]]:
    rows = []
    for match in _PLAYER_RE.finditer(list_body):
        href = _clean_str(match.group("href"))
        rows.append(
            {
                "position": _strip_tags(match.group("position")),
                "title": _clean_str(html.unescape(match.group("title"))),
                "label": _strip_tags(match.group("label")),
                "href": href,
                "player_id": _rotowire_player_id(href),
                "bats": _strip_tags(match.group("bats") or ""),
            }
        )
    return rows


def _environment_row(
    block: str,
    *,
    snapshot_id: str,
    game_date: str,
    game_index: int,
    game_id: str,
    classes: str,
    teams: dict[str, dict[str, str]],
    names: dict[str, str],
    game_time_et: str,
    box_score_href: str,
) -> dict[str, Any]:
    umpire_text = _strip_tags(_first_match(block, r'<div class="lineup__umpire">(?P<value>.*?)</div>'))
    weather_text = _strip_tags(_first_match(block, r'<div class="lineup__weather-text">\s*(?P<value>.*?)</div>'))
    line = _strip_tags(_first_match(block, r'<b>LINE</b>.*?<span class="composite hide">(?P<value>.*?)</span>'))
    total_runs = _strip_tags(_first_match(block, r'<b>O/U</b>.*?<span class="composite hide">(?P<value>.*?)</span>'))
    return {
        "source": "rotowire_mlb_context",
        "snapshot_id": snapshot_id,
        "game_date": game_date,
        "game_index": game_index,
        "game_id": game_id,
        "away_team_abbr": (teams.get("visit") or {}).get("abbr", ""),
        "home_team_abbr": (teams.get("home") or {}).get("abbr", ""),
        "away_team_name": names.get("visit", ""),
        "home_team_name": names.get("home", ""),
        "game_time_et": game_time_et,
        "box_score_href": box_score_href,
        "slate_status": classes,
        "game_started": "has-started" in classes,
        "umpire_text": umpire_text,
        "weather_text": weather_text,
        "moneyline": line,
        "total_runs": total_runs,
    }


def _first_match(value: str, pattern: str) -> str:
    match = re.search(pattern, value, flags=re.S)
    return match.group("value") if match else ""


def _rotowire_player_id(href: str) -> str:
    match = re.search(r"-(\d+)(?:$|[/?#])", href)
    return match.group(1) if match else ""


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return _clean_str(html.unescape(text).replace("\xa0", " "))


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")
    return str(path)


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8").strip()
    return 0 if not text else len(text.splitlines())

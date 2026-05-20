"""Normalize Baseball Reference boxscore starting-lineup tables."""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr, compact_team_key
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

SOURCE = "baseball_reference_boxscore_context"
CONTEXT_TIMING = "historical_pregame_lineup_backfill"
LINEUP_CONTENT_TIMING = "pregame_starting_lineup"


def normalize_baseball_reference_boxscore(payload: dict[str, Any], *, snapshot_id: str = "") -> dict[str, Any]:
    """Parse Baseball Reference ``Starting Lineups`` tables from raw page payloads."""

    batting_orders: list[dict[str, Any]] = []
    pitchers: list[dict[str, Any]] = []
    raw_games: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    pages = payload.get("data", [])
    if not isinstance(pages, list):
        pages = []

    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        body = str(page.get("body") or "")
        url = str(page.get("resolved_url") or page.get("url") or "")
        game = _game_context(
            body,
            url=url,
            fallback_date=str(payload.get("game_date") or ""),
            fallback_game_context=page.get("game_context") if isinstance(page.get("game_context"), dict) else {},
        )
        if not game["game_date"]:
            warnings.append({"page_index": page_index, "warning": "missing_game_date", "url": url})

        tables = _lineup_tables(body)
        if not tables:
            warnings.append({"page_index": page_index, "warning": "missing_starting_lineups", "url": url})
            continue

        raw_games.append(
            {
                "source": SOURCE,
                "snapshot_id": snapshot_id,
                "context_timing": CONTEXT_TIMING,
                "lineup_content_timing": LINEUP_CONTENT_TIMING,
                "game_date": game["game_date"],
                "game_id": game["game_id"],
                "url": url,
                "away_team_abbr": game["away_team_abbr"],
                "home_team_abbr": game["home_team_abbr"],
                "away_team_name": game["away_team_name"],
                "home_team_name": game["home_team_name"],
            }
        )

        for table_index, table in enumerate(tables, start=1):
            team = _team_from_caption(table["caption"], game)
            opponent = _opponent_for_team(team, game)
            for row in table["rows"]:
                base = {
                    "source": SOURCE,
                    "snapshot_id": snapshot_id,
                    "context_timing": CONTEXT_TIMING,
                    "lineup_content_timing": LINEUP_CONTENT_TIMING,
                    "game_date": game["game_date"],
                    "game_id": game["game_id"],
                    "team_abbr": team,
                    "opponent_abbr": opponent,
                    "team_name": _team_name(team, game) or table["caption"],
                    "opponent_name": _team_name(opponent, game),
                    "boxscore_url": url,
                    "lineup_table_index": table_index,
                    "player_name": row["player_name"],
                    "bref_player_id": row["bref_player_id"],
                    "player_href": row["player_href"],
                    "position": row["position"],
                }
                if row["batting_order"]:
                    batting_orders.append(
                        {
                            **base,
                            "batting_order": row["batting_order"],
                            "display_name": row["player_name"],
                            "rotowire_player_id": f"bref:{row['bref_player_id']}" if row["bref_player_id"] else "",
                            "lineup_status": "Confirmed Starting Lineup",
                            "lineup_status_key": "confirmed_starting_lineup",
                        }
                    )
                elif row["position"] == "P":
                    pitchers.append(
                        {
                            **base,
                            "pitcher_name": row["player_name"],
                            "rotowire_player_id": f"bref:{row['bref_player_id']}" if row["bref_player_id"] else "",
                            "throws": "",
                            "pitcher_stats": "",
                            "is_probable_starter": True,
                            "lineup_status": "Confirmed Starting Pitcher",
                            "lineup_status_key": "confirmed_starting_pitcher",
                        }
                    )

    return {
        "snapshot_id": snapshot_id,
        "source": SOURCE,
        "context_timing": CONTEXT_TIMING,
        "lineup_content_timing": LINEUP_CONTENT_TIMING,
        "game_dates": sorted({row["game_date"] for row in raw_games if row.get("game_date")}),
        "raw_games": raw_games,
        "daily_lineups": batting_orders,
        "batting_orders": batting_orders,
        "pitchers": pitchers,
        "parse_warnings": warnings,
        "parser_status": {
            "raw_games": "parsed" if raw_games else "empty",
            "batting_orders": "parsed_from_starting_lineups" if batting_orders else "empty",
            "pitchers": "parsed_from_starting_lineups" if pitchers else "empty",
        },
    }


def write_baseball_reference_boxscore_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Stage Baseball Reference starting-lineup artifacts."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or "baseball_reference_boxscore_context")
    normalized = normalize_baseball_reference_boxscore(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or resolved_run_id),
    )

    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / SOURCE / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "raw_games": _write_jsonl(output_dir / "raw_games.jsonl", normalized["raw_games"]),
        "daily_lineups": _write_jsonl(output_dir / "daily_lineups.jsonl", normalized["daily_lineups"]),
        "batting_orders": _write_jsonl(output_dir / "batting_orders.jsonl", normalized["batting_orders"]),
        "pitchers": _write_jsonl(output_dir / "pitchers.jsonl", normalized["pitchers"]),
    }
    out = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": SOURCE,
        "context_timing": normalized["context_timing"],
        "lineup_content_timing": normalized["lineup_content_timing"],
        "game_date": normalized["game_dates"][0] if len(normalized["game_dates"]) == 1 else "",
        "game_dates": normalized["game_dates"],
        "output_dir": str(output_dir),
        "row_counts": {key: _count_jsonl(Path(path)) for key, path in artifacts.items()},
        "artifacts": artifacts,
        "parser_status": normalized["parser_status"],
        "parse_warnings": normalized["parse_warnings"],
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _game_context(
    body: str,
    *,
    url: str,
    fallback_date: str,
    fallback_game_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    fallback_game_context = fallback_game_context or {}
    title = _strip_tags(_first_match(body, r"<h1[^>]*>(?P<value>.*?)</h1>")) or _markdown_heading(body)
    away_name, home_name, title_date = _teams_and_date_from_title(title)
    if not away_name:
        away_name = _clean(
            fallback_game_context.get("away_team_name")
            or fallback_game_context.get("away_name")
            or fallback_game_context.get("away_team")
        )
    if not home_name:
        home_name = _clean(
            fallback_game_context.get("home_team_name")
            or fallback_game_context.get("home_name")
            or fallback_game_context.get("home_team")
        )
    game_date = fallback_date or title_date or _date_from_url(url)
    game_id = Path(url).stem if url else ""
    away = canonical_team_abbr(away_name)
    home = canonical_team_abbr(home_name)
    return {
        "game_date": game_date,
        "game_id": game_id,
        "away_team_name": away_name,
        "home_team_name": home_name,
        "away_team_abbr": away,
        "home_team_abbr": home,
    }


def _markdown_heading(body: str) -> str:
    match = re.search(r"^#\s+(?P<value>.+?)\s*$", body or "", flags=re.M)
    return _clean(match.group("value")) if match else ""


def _teams_and_date_from_title(title: str) -> tuple[str, str, str]:
    match = re.search(
        r"(?P<away>.+?)\s+vs\s+(?P<home>.+?)\s+Box Score:\s+(?P<date>.+)$",
        title,
        flags=re.I,
    )
    if not match:
        return "", "", ""
    return (
        _clean(match.group("away")),
        _clean(match.group("home")),
        _date_from_text(match.group("date")),
    )


def _lineup_tables(body: str) -> list[dict[str, Any]]:
    text = body.replace("<!--", "").replace("-->", "")
    tables: list[dict[str, Any]] = []
    for match in re.finditer(r'<div id="lineups_\d+"[^>]*>\s*<table>(?P<table>.*?)</table>', text, flags=re.S | re.I):
        table_html = match.group("table")
        caption = _strip_tags(_first_match(table_html, r"<caption>(?P<value>.*?)</caption>"))
        rows = [_lineup_row(row_match.group("row")) for row_match in re.finditer(r"<tr[^>]*>(?P<row>.*?)</tr>", table_html, flags=re.S | re.I)]
        rows = [row for row in rows if row and row.get("player_name")]
        if rows:
            tables.append({"caption": caption, "rows": rows})
    return tables or _markdown_lineup_tables(body)


def _markdown_lineup_tables(body: str) -> list[dict[str, Any]]:
    start = body.find("## Starting Lineups")
    if start < 0:
        return []
    next_section = body.find("\n## ", start + len("## Starting Lineups"))
    section = body[start: next_section if next_section > start else len(body)]
    tables: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in section.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        row = _markdown_lineup_row(line)
        if not row:
            continue
        caption = row.pop("caption")
        if caption:
            current = {"caption": caption, "rows": []}
            tables.append(current)
        if current is not None:
            current["rows"].append(row)
    return [table for table in tables if table["rows"]]


def _markdown_lineup_row(line: str) -> dict[str, Any]:
    match = re.match(
        r"^(?:(?P<caption>[^\d\[]+?)\s+)?(?:(?P<order>\d+))?"
        r"\[(?P<name>[^\]]+)\]\((?P<href>[^)]+)\)(?P<position>[A-Z0-9/ -]+)$",
        line,
    )
    if not match:
        return {}
    href = html_lib.unescape(_clean(match.group("href")))
    return {
        "caption": _clean(match.group("caption")),
        "batting_order": _int(match.group("order")),
        "player_name": _clean(match.group("name")),
        "bref_player_id": _bref_player_id(href),
        "player_href": href,
        "position": _clean(match.group("position")).upper(),
    }


def _lineup_row(row_html: str) -> dict[str, Any]:
    cells = re.findall(r"<td[^>]*>(?P<cell>.*?)</td>", row_html, flags=re.S | re.I)
    if len(cells) < 3:
        return {}
    order_text = _strip_tags(cells[0])
    name_cell = cells[1]
    player_name = _strip_tags(name_cell)
    href = html_lib.unescape(_first_match(name_cell, r'<a href="(?P<value>[^"]+)"'))
    position = _strip_tags(cells[2]).upper()
    return {
        "batting_order": _int(order_text),
        "player_name": player_name,
        "bref_player_id": _bref_player_id(href),
        "player_href": href,
        "position": position,
    }


def _team_from_caption(caption: str, game: dict[str, str]) -> str:
    caption_key = compact_team_key(caption)
    for side in ("away", "home"):
        full_name = game.get(f"{side}_team_name", "")
        if caption_key and caption_key in compact_team_key(full_name):
            return str(game.get(f"{side}_team_abbr") or "")
    return canonical_team_abbr(caption)


def _opponent_for_team(team: str, game: dict[str, str]) -> str:
    if team and team == game.get("away_team_abbr"):
        return game.get("home_team_abbr", "")
    if team and team == game.get("home_team_abbr"):
        return game.get("away_team_abbr", "")
    return ""


def _team_name(team: str, game: dict[str, str]) -> str:
    if team and team == game.get("away_team_abbr"):
        return game.get("away_team_name", "")
    if team and team == game.get("home_team_abbr"):
        return game.get("home_team_name", "")
    return ""


def _date_from_url(url: str) -> str:
    match = re.search(r"(20\d{2})(\d{2})(\d{2})\d?\.shtml", url)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _date_from_text(value: str) -> str:
    cleaned = " ".join(str(value or "").replace(",", " ,").split()).replace(" ,", ",")
    try:
        return datetime.strptime(cleaned, "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def _bref_player_id(href: str) -> str:
    match = re.search(r"/players/[a-z]/(?P<id>[^/.]+)\.shtml", href)
    return match.group("id") if match else ""


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text or "", flags=re.S | re.I)
    return match.group("value") if match else ""


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return _clean(html_lib.unescape(text))


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return str(path)


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

"""Runtime artifact writer for MLB StatsAPI player game-log history context."""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.market_context import latest_engine_board_path
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.season_gamelogs import load_season_gamelog_rows

PLAYER_HISTORY_CONTEXT_VERSION = "statsapi_player_history_context_v0"

PITCHER_HISTORY_MARKETS = {
    "pitcher_strikeouts",
    "pitching_outs",
    "hits_allowed",
    "earned_runs_allowed",
    "walks_allowed",
    "pitches_thrown",
    "pitcher_fantasy_score",
    "first_inning_runs_allowed",
    "first_inning_walks_allowed",
}

PLAYER_HISTORY_CONTEXT_COLUMNS = (
    "run_id",
    "source_projection_id",
    "event_id",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "game_date",
    "market",
    "line",
    "tier",
    "player_history_context_available",
    "history_person_id",
    "history_games_season",
    "history_games_7d",
    "history_games_14d",
    "season_pa_per_game",
    "recent_pa_per_game_7d",
    "recent_pa_per_game_14d",
    "plate_appearance_projection",
    "plate_appearance_projection_source",
    "history_hits_per_pa_14d",
    "history_total_bases_per_pa_14d",
    "history_strikeouts_per_pa_14d",
    "history_walks_per_pa_14d",
    "history_context_confidence",
    "history_context_flags",
)


def build_player_history_context_result(
    *,
    engine_board_path: Path | None = None,
    roster_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> RuntimeCommandResult:
    manifest = build_player_history_context_artifacts(
        engine_board_path=engine_board_path,
        roster_context_path=roster_context_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
    )
    lines = [
        "Built MLB player history context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  gamelog_source_row_count: {manifest['gamelog_source_row_count']}",
        f"  row_count: {manifest['row_count']}",
        f"  coverage_rate: {manifest['coverage_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
    ]
    return RuntimeCommandResult(name="build_player_history_context", payload=manifest, lines=tuple(lines))


def build_player_history_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    roster_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    source_path = engine_board_path or latest_engine_board_path(root=root)
    engine_board = _load_json(source_path)
    source_run_id = str(engine_board.get("run_id") or source_path.parent.name)
    source_rows = [row for row in engine_board.get("rows", []) if isinstance(row, dict)]
    filtered_rows = _filter_rows_by_date(source_rows, game_date)
    resolved_run_id = run_id or game_date or source_run_id

    gamelog_rows = _load_gamelog_rows(paths)
    roster_rows = _load_context_rows(roster_context_path)
    history_index = _index_gamelogs(gamelog_rows)
    rows = [
        _history_context_row(
            row,
            run_id=resolved_run_id,
            history=_match_history(
                row,
                history_index,
                roster_row=roster_rows.get(_matchup_key(row)),
            ),
            source_available=bool(gamelog_rows),
        )
        for row in filtered_rows
    ]

    output_dir = paths.features / "player_history_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "player_history_context.csv"
    json_path = output_dir / "player_history_context.json"
    manifest_path = output_dir / "player_history_context_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "player_history_context_version": PLAYER_HISTORY_CONTEXT_VERSION,
                "row_count": len(rows),
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "source_run_id": source_run_id,
        "source_engine_board_path": str(source_path),
        "roster_context_path": str(roster_context_path) if roster_context_path else "",
        "game_date": game_date or "",
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "player_history_context_version": PLAYER_HISTORY_CONTEXT_VERSION,
        "gamelog_source_row_count": len(gamelog_rows),
        "coverage_rate": _true_rate(row["player_history_context_available"] for row in rows),
        "coverage_by_market": _true_rate_by_key(rows, key="market", value="player_history_context_available"),
        "history_context_flag_counts": _flag_counts(row["history_context_flags"] for row in rows),
        "pa_projection_mean": _mean(
            row["plate_appearance_projection"] for row in rows if row["player_history_context_available"]
        ),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "player_history_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "player_history_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "player_history_context" / "latest_manifest.json"),
        "columns": list(PLAYER_HISTORY_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "player_history_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "player_history_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "player_history_context" / "latest_manifest.json")
    return manifest


def _history_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    history: list[dict[str, Any]],
    source_available: bool,
) -> dict[str, Any]:
    game_date = _parse_date(row.get("game_date"))
    market = str(row.get("market") or "")
    history_group = "pitching" if market in PITCHER_HISTORY_MARKETS else "hitting"
    before_game = [
        item
        for item in history
        if (item_date := _parse_date(item.get("game_date"))) and game_date and item_date < game_date
    ]
    if history_group == "pitching":
        season = _pitching_summary(before_game)
        last_14 = _pitching_summary(_within_days(before_game, game_date=game_date, days=14))
        last_7 = _pitching_summary(_within_days(before_game, game_date=game_date, days=7))
        projection = 0.0
        projection_source = ""
    else:
        season = _hitting_summary(before_game)
        last_14 = _hitting_summary(_within_days(before_game, game_date=game_date, days=14))
        last_7 = _hitting_summary(_within_days(before_game, game_date=game_date, days=7))
        projection = _plate_appearance_projection(season=season, last_14=last_14, last_7=last_7)
        projection_source = "statsapi_player_gamelog" if before_game else ""
    confidence = _history_confidence(season["games"], last_14["games"])
    flags: list[str] = []
    if not source_available:
        flags.append("no_statsapi_player_gamelog_snapshot_available")
    elif not before_game:
        flags.append("missing_player_history_context")
    else:
        flags.append(
            "statsapi_pitcher_gamelog_history_match"
            if history_group == "pitching"
            else "statsapi_player_gamelog_history_match"
        )
        if last_14["games"] < 3:
            flags.append("thin_recent_pitching_history" if history_group == "pitching" else "thin_recent_pa_history")
    return {
        "run_id": run_id,
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "game_date": str(row.get("game_date") or ""),
        "market": market,
        "line": _float(row.get("line")),
        "tier": str(row.get("tier") or "STANDARD").upper() or "STANDARD",
        "player_history_context_available": bool(before_game),
        "history_person_id": _int(before_game[-1].get("person_id")) if before_game else 0,
        "history_games_season": season["games"],
        "history_games_7d": last_7["games"],
        "history_games_14d": last_14["games"],
        "season_pa_per_game": season["pa_per_game"],
        "recent_pa_per_game_7d": last_7["pa_per_game"],
        "recent_pa_per_game_14d": last_14["pa_per_game"],
        "plate_appearance_projection": projection,
        "plate_appearance_projection_source": projection_source,
        "history_hits_per_pa_14d": last_14["hits_per_pa"],
        "history_total_bases_per_pa_14d": last_14["total_bases_per_pa"],
        "history_strikeouts_per_pa_14d": last_14["strikeouts_per_pa"],
        "history_walks_per_pa_14d": last_14["walks_per_pa"],
        "history_context_confidence": confidence,
        "history_context_flags": tuple(flags),
    }


def _load_gamelog_rows(paths) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = load_season_gamelog_rows(root=paths.repo_root)
    for root, rows_name in (
        (paths.staged / "statsapi_player_gamelog", "statsapi_player_gamelog.jsonl"),
        (paths.staged / "statsapi_player_gamelogs_bulk", "statsapi_player_gamelogs_bulk.jsonl"),
        (paths.staged / "espn_player_gamelog", "espn_player_gamelog.jsonl"),
        (paths.staged / "espn_player_gamelogs_bulk", "espn_player_gamelogs_bulk.jsonl"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*/{rows_name}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
            rows.extend(_load_jsonl(path))
    return _dedupe_gamelog_rows(rows)


def _dedupe_gamelog_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[tuple[int, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            _int(row.get("person_id")),
            _name_key(row.get("player_name")),
            str(row.get("game_date") or ""),
            str(row.get("game_pk") or row.get("game_id") or row.get("espn_event_id") or ""),
            str(row.get("group") or "").lower(),
        )
        if not key[1] or not key[2] or not key[4]:
            continue
        out[key] = row
    return list(out.values())


def _index_gamelogs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_person_id: dict[str, dict[int, list[dict[str, Any]]]] = {"hitting": {}, "pitching": {}}
    by_name: dict[str, dict[str, list[dict[str, Any]]]] = {"hitting": {}, "pitching": {}}
    for row in rows:
        group = str(row.get("group") or "").lower() or "hitting"
        if group not in {"hitting", "pitching"}:
            continue
        person_id = _int(row.get("person_id"))
        if person_id:
            by_person_id[group].setdefault(person_id, []).append(row)
        name_key = _name_key(row.get("player_name"))
        if name_key:
            by_name[group].setdefault(name_key, []).append(row)
    return {"by_person_id": by_person_id, "by_name": by_name}


def _match_history(
    row: dict[str, Any],
    index: dict[str, Any],
    *,
    roster_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    person_id = _int(roster_row.get("statsapi_person_id")) if roster_row else 0
    group = "pitching" if str(row.get("market") or "") in PITCHER_HISTORY_MARKETS else "hitting"
    matches = list(index["by_person_id"].get(group, {}).get(person_id, [])) if person_id else []
    if not matches:
        matches = list(index["by_name"].get(group, {}).get(_name_key(row.get("player_name")), []))
    return sorted(matches, key=lambda item: _date_key(item.get("game_date")))


def _within_days(rows: list[dict[str, Any]], *, game_date: date | None, days: int) -> list[dict[str, Any]]:
    if not game_date:
        return []
    start = game_date - timedelta(days=days)
    return [row for row in rows if (row_date := _parse_date(row.get("game_date"))) and start <= row_date < game_date]


def _hitting_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    games = len({(_int(row.get("game_pk")), str(row.get("game_date") or "")) for row in rows})
    pa = sum(_plate_appearances(row.get("stat") or {}) for row in rows)
    hits = sum(_stat_float(row.get("stat") or {}, "hits") for row in rows)
    total_bases = sum(_stat_float(row.get("stat") or {}, "totalBases") for row in rows)
    strikeouts = sum(_stat_float(row.get("stat") or {}, "strikeOuts", "strikeouts") for row in rows)
    walks = sum(_stat_float(row.get("stat") or {}, "baseOnBalls", "walks") for row in rows)
    return {
        "games": games,
        "pa": pa,
        "pa_per_game": round(pa / games, 4) if games else 0.0,
        "hits_per_pa": round(hits / pa, 6) if pa else 0.0,
        "total_bases_per_pa": round(total_bases / pa, 6) if pa else 0.0,
        "strikeouts_per_pa": round(strikeouts / pa, 6) if pa else 0.0,
        "walks_per_pa": round(walks / pa, 6) if pa else 0.0,
    }


def _pitching_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    games = len({(_int(row.get("game_pk")), str(row.get("game_date") or "")) for row in rows})
    batters_faced = sum(_stat_float(row.get("stat") or {}, "battersFaced") for row in rows)
    strikeouts = sum(_stat_float(row.get("stat") or {}, "strikeOuts", "strikeouts") for row in rows)
    walks = sum(_stat_float(row.get("stat") or {}, "baseOnBalls", "walks") for row in rows)
    hits = sum(_stat_float(row.get("stat") or {}, "hits") for row in rows)
    return {
        "games": games,
        "pa": 0.0,
        "pa_per_game": 0.0,
        "hits_per_pa": round(hits / batters_faced, 6) if batters_faced else 0.0,
        "total_bases_per_pa": 0.0,
        "strikeouts_per_pa": round(strikeouts / batters_faced, 6) if batters_faced else 0.0,
        "walks_per_pa": round(walks / batters_faced, 6) if batters_faced else 0.0,
    }


def _plate_appearance_projection(*, season: dict[str, Any], last_14: dict[str, Any], last_7: dict[str, Any]) -> float:
    values: list[tuple[float, float]] = []
    if season["games"]:
        values.append((0.30, season["pa_per_game"]))
    if last_14["games"]:
        values.append((0.50, last_14["pa_per_game"]))
    if last_7["games"]:
        values.append((0.20, last_7["pa_per_game"]))
    if not values:
        return 0.0
    weight_sum = sum(weight for weight, _ in values)
    projection = sum(weight * value for weight, value in values) / weight_sum
    return round(_clamp(projection, 2.25, 5.65), 4)


def _history_confidence(season_games: int, recent_games: int) -> float:
    if season_games <= 0:
        return 0.0
    score = 0.25 + min(season_games, 35) / 70.0 + min(recent_games, 8) / 30.0
    return round(_clamp(score, 0.25, 0.88), 6)


def _plate_appearances(stat: dict[str, Any]) -> float:
    pa = _stat_float(stat, "plateAppearances")
    if pa:
        return pa
    return sum(
        _stat_float(stat, key)
        for key in ("atBats", "baseOnBalls", "hitByPitch", "sacFlies", "sacBunts")
    )


def _stat_float(stat: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = stat.get(key)
        if value not in (None, ""):
            return _float(value)
    return 0.0


def _load_context_rows(path: Path | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return {}
    return {_matchup_key(row): row for row in rows if isinstance(row, dict)}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PLAYER_HISTORY_CONTEXT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in PLAYER_HISTORY_CONTEXT_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _matchup_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("source_projection_id") or "").strip(),
        str(row.get("market") or "").strip(),
        _line_key(row.get("line")),
        str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
    )


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _date_key(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _parse_date(value: Any) -> date | None:
    key = _date_key(value)
    if not key:
        return None
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _true_rate_by_key(rows: list[dict[str, Any]], *, key: str, value: str) -> dict[str, float | None]:
    groups: dict[str, list[bool]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or ""), []).append(bool(row.get(value)))
    return {group: _true_rate(values) for group, values in sorted(groups.items())}


def _flag_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for flag in _tuple_flags(value):
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return (value,)
            return _tuple_flags(decoded)
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _mean(values) -> float | None:
    collected = [float(value) for value in values]
    if not collected:
        return None
    return round(sum(collected) / len(collected), 6)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

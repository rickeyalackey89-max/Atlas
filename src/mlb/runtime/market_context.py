"""Runtime artifact writer for external MLB market context.

The market context is a replay-safe bridge between the PrizePicks board and
normalized OddsAPI consensus lines. It is intentionally separate from the
parameter table so a run manifest can show exactly which market snapshot was
available before probabilities were built.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

MARKET_CONTEXT_VERSION = "oddsapi_market_context_v2"

DEFAULT_NEAREST_LINE_DELTA = 0.5
NEAREST_LINE_DELTA_LIMITS = {
    "first_inning_runs_allowed": 0.5,
    "first_inning_walks_allowed": 0.5,
    "hitter_fantasy_score": 1.0,
    "pitcher_fantasy_score": 1.0,
}
WIDE_NEAREST_LINE_DELTA_LIMITS = {
    "hits": 1.0,
    "singles": 1.0,
    "doubles": 1.0,
    "home_runs": 1.0,
    "stolen_bases": 1.0,
    "runs": 2.0,
    "rbis": 2.0,
    "walks": 1.0,
    "hitter_strikeouts": 1.0,
    "total_bases": 3.0,
    "hits_runs_rbis": 4.0,
    "plate_appearances": 1.5,
    "pitcher_strikeouts": 2.5,
    "pitching_outs": 3.0,
    "hits_allowed": 2.5,
    "earned_runs_allowed": 2.0,
    "walks_allowed": 2.0,
    "pitches_thrown": 12.0,
    "hitter_fantasy_score": 6.0,
    "pitcher_fantasy_score": 8.0,
}

MARKET_CONTEXT_COLUMNS = (
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
    "market_context_available",
    "market_line_match_type",
    "market_source_line",
    "market_line_delta",
    "market_over_probability",
    "market_under_probability",
    "market_n_books",
    "market_home_team",
    "market_away_team",
    "market_event_id",
    "market_snapshot_id",
    "market_snapshot_timestamp",
    "market_pulled_at_utc",
    "market_source",
    "bettingpros_recommended_side",
    "bettingpros_projection_value",
    "bettingpros_projection_probability",
    "bettingpros_projection_expected_value",
    "bettingpros_projection_diff",
    "bettingpros_streak",
    "bettingpros_streak_type",
    "bettingpros_last_5_over_rate",
    "bettingpros_last_5_under_rate",
    "bettingpros_last_10_over_rate",
    "bettingpros_last_10_under_rate",
    "bettingpros_last_20_over_rate",
    "bettingpros_last_20_under_rate",
    "bettingpros_season_over_rate",
    "bettingpros_season_under_rate",
    "bettingpros_prior_season_over_rate",
    "bettingpros_prior_season_under_rate",
    "market_context_flags",
)


def build_market_context_result(
    *,
    engine_board_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    market_source_dirs: list[Path] | None = None,
) -> RuntimeCommandResult:
    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
        market_source_dirs=market_source_dirs,
    )
    lines = [
        "Built MLB market context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source_run_id: {manifest['source_run_id']}",
        f"  source_row_count: {manifest['source_row_count']}",
        f"  row_count: {manifest['row_count']}",
        f"  coverage_rate: {manifest['coverage_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="build_market_context", payload=manifest, lines=tuple(lines))


def build_market_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    market_source_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    source_path = engine_board_path or latest_engine_board_path(root=root)
    engine_board = _load_json(source_path)
    source_run_id = str(engine_board.get("run_id") or source_path.parent.name)
    source_rows = [row for row in engine_board.get("rows", []) if isinstance(row, dict)]
    filtered_rows = _filter_rows_by_date(source_rows, game_date)
    resolved_run_id = run_id or game_date or source_run_id
    dates = sorted({str(row.get("game_date") or "") for row in filtered_rows if row.get("game_date")})
    selected_market_source_dirs = (
        _explicit_oddsapi_dirs_by_date(market_source_dirs, dates)
        if market_source_dirs is not None
        else _oddsapi_dirs_by_date(paths.staged / "oddsapi", dates)
    )
    odds_rows = _load_oddsapi_rows(selected_market_source_dirs)
    odds_index, odds_player_market_index = _index_odds_rows(odds_rows)

    rows = [
        _market_context_row(
            row,
            run_id=resolved_run_id,
            odds_match=_select_odds_match(
                row,
                exact_index=odds_index,
                player_market_index=odds_player_market_index,
            ),
        )
        for row in filtered_rows
    ]

    output_dir = paths.features / "market_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "market_context.csv"
    json_path = output_dir / "market_context.json"
    manifest_path = output_dir / "market_context_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "market_context_version": MARKET_CONTEXT_VERSION,
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
        "game_date": game_date or "",
        "dates": dates,
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "market_context_version": MARKET_CONTEXT_VERSION,
        "market_source_dirs_by_date": {
            date: [str(path) for path in paths]
            for date, paths in sorted(selected_market_source_dirs.items())
        },
        "market_source_row_count": len(odds_rows),
        "coverage_rate": _true_rate(row["market_context_available"] for row in rows),
        "coverage_by_market": _true_rate_by_key(rows, key="market", value="market_context_available"),
        "coverage_by_tier": _true_rate_by_key(rows, key="tier", value="market_context_available"),
        "market_context_flag_counts": _flag_counts(row["market_context_flags"] for row in rows),
        "board_rows_by_market": _count_by_key(rows, "market"),
        "matched_rows_by_market": _count_by_key(
            [row for row in rows if row.get("market_context_available")],
            "market",
        ),
        "market_source_counts_by_market": _source_market_counts(odds_rows),
        "market_n_books_mean": _mean(
            row["market_n_books"] for row in rows if row.get("market_context_available")
        ),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "market_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "market_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "market_context" / "latest_manifest.json"),
        "columns": list(MARKET_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "market_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "market_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "market_context" / "latest_manifest.json")
    return manifest


def latest_engine_board_path(*, root: Path | None = None) -> Path:
    paths = ensure_mlb_dirs(root)
    latest = paths.staged / "engine_board" / "latest.json"
    if latest.exists():
        return latest
    candidates = sorted(
        (paths.staged / "engine_board").glob("*/engine_board.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No engine-board JSON found under {paths.staged / 'engine_board'}")
    return candidates[-1]


def _market_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    odds_match: dict[str, Any] | None,
) -> dict[str, Any]:
    flags: list[str] = []
    odds_row = dict(odds_match.get("row") or {}) if odds_match else None
    match_type = str(odds_match.get("match_type") or "") if odds_match else ""
    line_delta = _float(odds_match.get("line_delta")) if odds_match else 0.0
    projection = odds_row.get("bettingpros_projection") if odds_row else {}
    performance = odds_row.get("bettingpros_performance") if odds_row else {}
    projection = projection if isinstance(projection, dict) else {}
    performance = performance if isinstance(performance, dict) else {}
    if not odds_row:
        flags.append("missing_market_context")
    else:
        n_books = _int(odds_row.get("n_books"))
        if n_books < 2:
            flags.append("thin_market_context")
        if match_type == "nearest":
            flags.append("nearest_player_market_line_match")
            flags.append("nearest_line_delta_within_threshold")
        elif match_type == "wide_nearest":
            flags.append("wide_nearest_player_market_line_match")
            flags.append("wide_line_delta_reference_context")
        else:
            flags.append("exact_player_market_line_match")

    return {
        "run_id": run_id,
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "game_date": str(row.get("game_date") or ""),
        "market": str(row.get("market") or ""),
        "line": _float(row.get("line")),
        "tier": str(row.get("tier") or "STANDARD").upper() or "STANDARD",
        "market_context_available": odds_row is not None,
        "market_line_match_type": match_type,
        "market_source_line": _float(odds_row.get("line")) if odds_row else 0.0,
        "market_line_delta": line_delta,
        "market_over_probability": _float(odds_row.get("over_prob")) if odds_row else 0.0,
        "market_under_probability": _float(odds_row.get("under_prob")) if odds_row else 0.0,
        "market_n_books": _int(odds_row.get("n_books")) if odds_row else 0,
        "market_home_team": str(odds_row.get("home_team") or "") if odds_row else "",
        "market_away_team": str(odds_row.get("away_team") or "") if odds_row else "",
        "market_event_id": str(odds_row.get("event_id") or "") if odds_row else "",
        "market_snapshot_id": str(odds_row.get("snapshot_id") or "") if odds_row else "",
        "market_snapshot_timestamp": str(odds_row.get("snapshot_timestamp") or "") if odds_row else "",
        "market_pulled_at_utc": str(odds_row.get("pulled_at_utc") or "") if odds_row else "",
        "market_source": str(odds_row.get("source") or "") if odds_row else "",
        "bettingpros_recommended_side": str(projection.get("recommended_side") or ""),
        "bettingpros_projection_value": _float(projection.get("projection_value")),
        "bettingpros_projection_probability": _float(projection.get("projection_probability")),
        "bettingpros_projection_expected_value": _float(projection.get("projection_expected_value")),
        "bettingpros_projection_diff": _float(projection.get("projection_diff")),
        "bettingpros_streak": _int(performance.get("streak")),
        "bettingpros_streak_type": str(performance.get("streak_type") or ""),
        "bettingpros_last_5_over_rate": _float(performance.get("last_5_over_rate")),
        "bettingpros_last_5_under_rate": _float(performance.get("last_5_under_rate")),
        "bettingpros_last_10_over_rate": _float(performance.get("last_10_over_rate")),
        "bettingpros_last_10_under_rate": _float(performance.get("last_10_under_rate")),
        "bettingpros_last_20_over_rate": _float(performance.get("last_20_over_rate")),
        "bettingpros_last_20_under_rate": _float(performance.get("last_20_under_rate")),
        "bettingpros_season_over_rate": _float(performance.get("season_over_rate")),
        "bettingpros_season_under_rate": _float(performance.get("season_under_rate")),
        "bettingpros_prior_season_over_rate": _float(performance.get("prior_season_over_rate")),
        "bettingpros_prior_season_under_rate": _float(performance.get("prior_season_under_rate")),
        "market_context_flags": tuple(flags),
    }


def _oddsapi_dirs_by_date(root: Path, dates: list[str]) -> dict[str, list[Path]]:
    if not root.exists() or not dates:
        return {}
    manifests = sorted(root.glob("*/normalize_manifest.json"))
    by_date: dict[str, list[Path]] = {date: [] for date in dates}
    for manifest_path in manifests:
        rows_path = manifest_path.parent / "oddsapi_props.jsonl"
        if not rows_path.exists():
            continue
        row_dates = _game_dates_in_rows(rows_path)
        for date in dates:
            if date in row_dates:
                by_date.setdefault(date, []).append(manifest_path.parent)
    return {date: sorted(paths, key=lambda path: path.name) for date, paths in by_date.items() if paths}


def _explicit_oddsapi_dirs_by_date(source_dirs: list[Path] | None, dates: list[str]) -> dict[str, list[Path]]:
    if not source_dirs or not dates:
        return {}
    by_date: dict[str, list[Path]] = {date: [] for date in dates}
    for source_dir in source_dirs:
        path = Path(source_dir)
        rows_path = path / "oddsapi_props.jsonl"
        if not rows_path.exists():
            continue
        row_dates = _game_dates_in_rows(rows_path)
        for date in dates:
            if date in row_dates:
                by_date.setdefault(date, []).append(path)
    return {date: sorted(paths, key=lambda path: path.name) for date, paths in by_date.items() if paths}


def _game_dates_in_rows(rows_path: Path) -> set[str]:
    dates: set[str] = set()
    for line in rows_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        game_date = str(row.get("game_date") or "")
        if game_date:
            dates.add(game_date)
    return dates


def _load_oddsapi_rows(source_dirs: dict[str, list[Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paths in source_dirs.values():
        for path in paths:
            rows.extend(_load_jsonl(path / "oddsapi_props.jsonl"))
    return rows


def _index_odds_rows(
    rows: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, str], list[dict[str, Any]]], dict[tuple[str, str, str], list[dict[str, Any]]]]:
    index: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    player_market_index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("game_date") or ""),
            _player_key(row.get("player_name") or row.get("player_norm") or ""),
            str(row.get("market") or ""),
            _line_key(row.get("line")),
        )
        index.setdefault(key, []).append(row)
        player_market_key = key[:3]
        player_market_index.setdefault(player_market_key, []).append(row)
    return index, player_market_index


def _select_odds_match(
    row: dict[str, Any],
    *,
    exact_index: dict[tuple[str, str, str, str], list[dict[str, Any]]],
    player_market_index: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    exact_candidates = exact_index.get(_market_key(row), [])
    if exact_candidates:
        if _has_team_context(row):
            exact_candidates = [candidate for candidate in exact_candidates if _same_game(row, candidate)]
        if exact_candidates:
            exact = sorted(exact_candidates, key=lambda candidate: _int(candidate.get("n_books")), reverse=True)[0]
            return {"row": exact, "match_type": "exact", "line_delta": 0.0}

    key = (
        str(row.get("game_date") or ""),
        _player_key(row.get("player_name") or ""),
        str(row.get("market") or ""),
    )
    candidates = player_market_index.get(key, [])
    if not candidates:
        return None
    same_game = [candidate for candidate in candidates if _same_game(row, candidate)]
    if same_game:
        candidates = same_game
    elif _has_team_context(row):
        return None

    target_line = _float(row.get("line"))
    max_delta = _nearest_line_delta_limit(str(row.get("market") or ""))
    viable: list[tuple[float, int, dict[str, Any]]] = []
    wide_viable: list[tuple[float, int, dict[str, Any]]] = []
    wide_max_delta = _wide_nearest_line_delta_limit(str(row.get("market") or ""))
    for candidate in candidates:
        delta = abs(_float(candidate.get("line")) - target_line)
        if 0.0 < delta <= max_delta:
            viable.append((delta, _int(candidate.get("n_books")), candidate))
        elif max_delta < delta <= wide_max_delta:
            wide_viable.append((delta, _int(candidate.get("n_books")), candidate))
    if viable:
        delta, _, candidate = sorted(viable, key=lambda item: (item[0], -item[1]))[0]
        return {"row": candidate, "match_type": "nearest", "line_delta": round(delta, 4)}
    if wide_viable:
        delta, _, candidate = sorted(wide_viable, key=lambda item: (item[0], -item[1]))[0]
        return {"row": candidate, "match_type": "wide_nearest", "line_delta": round(delta, 4)}
    return None


def _market_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("game_date") or ""),
        _player_key(row.get("player_name") or ""),
        str(row.get("market") or ""),
        _line_key(row.get("line")),
    )


def _same_game(board_row: dict[str, Any], odds_row: dict[str, Any]) -> bool:
    team = canonical_team_abbr(board_row.get("player_team"))
    opponent = canonical_team_abbr(board_row.get("opponent"))
    home = canonical_team_abbr(odds_row.get("home_team"))
    away = canonical_team_abbr(odds_row.get("away_team"))
    teams = {value for value in (home, away) if value}
    if not teams:
        return True
    if team and team not in teams:
        return False
    if opponent and opponent not in teams:
        return False
    return True


def _has_team_context(row: dict[str, Any]) -> bool:
    return bool(canonical_team_abbr(row.get("player_team")) or canonical_team_abbr(row.get("opponent")))


def _nearest_line_delta_limit(market: str) -> float:
    return NEAREST_LINE_DELTA_LIMITS.get(market, DEFAULT_NEAREST_LINE_DELTA)


def _wide_nearest_line_delta_limit(market: str) -> float:
    return max(_nearest_line_delta_limit(market), WIDE_NEAREST_LINE_DELTA_LIMITS.get(market, DEFAULT_NEAREST_LINE_DELTA))


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MARKET_CONTEXT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in MARKET_CONTEXT_COLUMNS})


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _player_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _true_rate_by_key(rows: list[dict[str, Any]], *, key: str, value: str) -> dict[str, float]:
    grouped: dict[str, list[bool]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or ""), []).append(bool(row.get(value)))
    return {
        group: round(sum(1 for item in values if item) / len(values), 6)
        for group, values in sorted(grouped.items())
        if values
    }


def _flag_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for flag in _tuple_flags(value):
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))


def _count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _source_market_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        source = str(row.get("source") or "")
        market = str(row.get("market") or "")
        if not source or not market:
            continue
        source_counts = counts.setdefault(source, {})
        source_counts[market] = source_counts.get(market, 0) + 1
    return {
        source: dict(sorted(source_counts.items()))
        for source, source_counts in sorted(counts.items())
    }


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

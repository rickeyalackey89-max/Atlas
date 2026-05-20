"""MLB context coverage audit.

This module checks whether a scored run had the context inputs the model
expected before probabilities were built. It is intentionally read-only against
run artifacts, except for writing an audit report artifact.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from mlb.runtime.paths import candidate_run_dirs, ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult


CONTEXT_FIELDS = (
    "external_market_context_available",
    "matchup_context_available",
    "lineup_context_available",
    "probable_pitcher_context_available",
    "weather_context_available",
    "statsapi_context_available",
    "roster_context_available",
    "advanced_context_available",
)

TOP_MISSING_FIELDS = (
    "external_market_context_available",
    "lineup_context_available",
    "probable_pitcher_context_available",
    "weather_context_available",
    "roster_context_available",
    "advanced_context_available",
)


def build_context_audit_result(
    *,
    run_id: str | None = None,
    root: Path | None = None,
    write_artifacts: bool = True,
) -> RuntimeCommandResult:
    """Build a runtime result for a completed MLB run context audit."""

    payload = build_context_audit_artifacts(run_id=run_id, root=root, write_artifacts=write_artifacts)
    lines = _audit_lines(payload)
    return RuntimeCommandResult(name="context-audit", payload=payload, lines=tuple(lines))


def build_context_audit_artifacts(
    *,
    run_id: str | None = None,
    root: Path | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """Audit context coverage and optionally write audit report artifacts."""

    paths = ensure_mlb_dirs(root)
    manifest_path = _resolve_run_manifest(paths, run_id)
    manifest = _read_json(manifest_path)
    resolved_run_id = str(manifest.get("run_id") or manifest_path.parent.name)

    features_manifest = dict(manifest.get("features") or {})
    engine_board_manifest = dict(manifest.get("engine_board") or {})
    parameters_manifest = dict(manifest.get("parameters") or {})
    matchups_manifest = dict(manifest.get("matchups") or {})
    market_manifest = dict(manifest.get("market_context") or {})
    roster_manifest = dict(manifest.get("roster_context") or {})
    statsapi_manifest = dict(manifest.get("statsapi_context") or {})
    advanced_manifest = dict(manifest.get("advanced_context") or {})

    engine_board_rows = _load_rows(
        _resolve_artifact_path(
            paths.repo_root,
            engine_board_manifest.get("json_path") or features_manifest.get("engine_board_path"),
        )
    )
    feature_rows = _load_rows(_resolve_artifact_path(paths.repo_root, features_manifest.get("json_path")))
    feature_rows = _enrich_rows_from_engine_board(feature_rows, engine_board_rows)
    parameter_rows = _load_rows(_resolve_artifact_path(paths.repo_root, parameters_manifest.get("json_path")))

    coverage_summary = _coverage_summary(feature_rows, CONTEXT_FIELDS)
    by_game_date = _coverage_by(feature_rows, "game_date", CONTEXT_FIELDS)
    by_market = _coverage_by(feature_rows, "market", CONTEXT_FIELDS)
    by_market_group = _coverage_by(feature_rows, "market_group", CONTEXT_FIELDS)
    by_tier = _coverage_by(feature_rows, "tier", CONTEXT_FIELDS)
    by_team = _coverage_by(feature_rows, "player_team", CONTEXT_FIELDS)
    by_team_game = _coverage_by_key(feature_rows, _team_game_key, CONTEXT_FIELDS)
    top_missing_players = {
        field: _top_missing_players(feature_rows, field, limit=15) for field in TOP_MISSING_FIELDS
    }
    missing_drivers = {
        field: {
            "teams": _top_missing_groups(feature_rows, field, ("player_team",), limit=10),
            "games": _top_missing_groups(feature_rows, field, ("game_date", "player_team", "opponent"), limit=10),
            "markets": _top_missing_groups(feature_rows, field, ("market_group", "market"), limit=10),
            "players": top_missing_players[field],
        }
        for field in TOP_MISSING_FIELDS
    }

    parameter_summary = _parameter_summary(parameter_rows)
    component_sources = dict(matchups_manifest.get("component_sources") or {})
    warnings = _build_warnings(
        coverage_summary=coverage_summary,
        parameter_summary=parameter_summary,
        component_sources=component_sources,
        matchups_manifest=matchups_manifest,
        market_manifest=market_manifest,
        roster_manifest=roster_manifest,
        engine_board_manifest=engine_board_manifest,
        coverage_by_game_date=by_game_date,
    )

    payload: dict[str, Any] = {
        "run_id": resolved_run_id,
        "run_manifest_path": str(manifest_path),
        "row_count": len(feature_rows),
        "parameter_row_count": len(parameter_rows),
        "coverage_summary": coverage_summary,
        "coverage_by_game_date": by_game_date,
        "coverage_by_market_group": by_market_group,
        "coverage_by_market": by_market,
        "coverage_by_tier": by_tier,
        "coverage_by_team": by_team,
        "coverage_by_team_game": by_team_game,
        "top_missing_players": top_missing_players,
        "missing_drivers": missing_drivers,
        "parameter_summary": parameter_summary,
        "component_sources": component_sources,
        "manifest_metrics": {
            "engine_board": _selected_manifest_metrics(
                engine_board_manifest,
                (
                    "source_row_count",
                    "row_count",
                    "game_date_filter",
                    "date_filter_policy",
                    "date_counts_before_filter",
                    "date_counts_after_filter",
                    "dropped_by_date_filter_count",
                ),
            ),
            "market_context": _selected_manifest_metrics(
                market_manifest,
                (
                    "coverage_rate",
                    "market_source_row_count",
                    "market_source_dirs_by_date",
                    "market_context_flag_counts",
                ),
            ),
            "matchups": _selected_manifest_metrics(
                matchups_manifest,
                (
                    "missing_context_rate",
                    "missing_context_counts",
                    "pitcher_prop_missing_context_rate",
                    "pitcher_prop_missing_context_counts",
                    "pitcher_prop_thin_context_count",
                ),
            ),
            "roster_context": _selected_manifest_metrics(
                roster_manifest,
                ("coverage_rate", "roster_source_row_count", "roster_context_flag_counts"),
            ),
            "statsapi_context": _selected_manifest_metrics(
                statsapi_manifest,
                ("coverage_rate", "schedule_source_row_count", "team_source_row_count", "venue_counts"),
            ),
            "advanced_context": _selected_manifest_metrics(
                advanced_manifest,
                (
                    "coverage_rate",
                    "profile_source_row_count",
                    "advanced_context_flag_counts",
                    "advanced_context_score_mean",
                    "advanced_sample_confidence_mean",
                ),
            ),
        },
        "warnings": warnings,
    }

    if write_artifacts:
        artifact_paths = _write_audit_artifacts(paths.features, resolved_run_id, payload)
        payload["artifact_paths"] = artifact_paths

    return payload


def _resolve_run_manifest(paths, run_id: str | None) -> Path:
    if run_id:
        for runs_dir in candidate_run_dirs(paths):
            path = runs_dir / run_id / "run_manifest.json"
            if path.exists():
                return path
        raise FileNotFoundError(f"MLB run manifest not found for run_id={run_id}")

    candidates = []
    for runs_dir in candidate_run_dirs(paths):
        if not runs_dir.exists():
            continue
        candidates.extend(
            path
            for path in runs_dir.iterdir()
            if path.is_dir() and (path / "run_manifest.json").exists()
        )
    if not candidates:
        raise FileNotFoundError(f"No MLB run manifests found under {paths.data_root}")
    return max(candidates, key=lambda path: (path / "run_manifest.json").stat().st_mtime) / "run_manifest.json"


def _resolve_artifact_path(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    return root / path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_rows(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("rows", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _enrich_rows_from_engine_board(
    rows: list[dict[str, Any]],
    engine_board_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows or not engine_board_rows:
        return rows
    board_by_key = {_row_key(row): row for row in engine_board_rows}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        ref = board_by_key.get(_row_key(row))
        if not ref:
            enriched.append(row)
            continue
        updated = dict(row)
        for field in ("game_date", "start_time_utc", "source_market"):
            if not updated.get(field) and ref.get(field):
                updated[field] = ref.get(field)
        enriched.append(updated)
    return enriched


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
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


def _coverage_summary(rows: list[dict[str, Any]], fields: Iterable[str]) -> dict[str, float]:
    total = len(rows)
    return {field: _round_rate(sum(1 for row in rows if _as_bool(row.get(field))), total) for field in fields}


def _coverage_by(
    rows: list[dict[str, Any]],
    group_field: str,
    context_fields: Iterable[str],
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get(group_field) or "unknown")
        grouped[key].append(row)

    result: dict[str, dict[str, float | int]] = {}
    for key in sorted(grouped):
        group_rows = grouped[key]
        entry: dict[str, float | int] = {"row_count": len(group_rows)}
        entry.update(_coverage_summary(group_rows, context_fields))
        result[key] = entry
    return result


def _coverage_by_key(
    rows: list[dict[str, Any]],
    key_func: Any,
    context_fields: Iterable[str],
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[key_func(row)].append(row)

    result: dict[str, dict[str, float | int]] = {}
    for key in sorted(grouped):
        group_rows = grouped[key]
        entry: dict[str, float | int] = {"row_count": len(group_rows)}
        entry.update(_coverage_summary(group_rows, context_fields))
        result[key] = entry
    return result


def _team_game_key(row: dict[str, Any]) -> str:
    game_date = str(row.get("game_date") or "unknown")
    team = str(row.get("player_team") or row.get("team") or "unknown")
    opponent = str(row.get("opponent") or "unknown")
    return f"{game_date} {team} vs {opponent}"


def _top_missing_players(
    rows: list[dict[str, Any]],
    field: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        if _as_bool(row.get(field)):
            continue
        player = str(row.get("player_name") or "unknown")
        team = str(row.get("player_team") or row.get("team") or "")
        market = str(row.get("market") or "unknown")
        counter[(player, team, market)] += 1

    return [
        {"player_name": player, "team": team, "market": market, "missing_rows": count}
        for (player, team, market), count in counter.most_common(limit)
    ]


def _top_missing_groups(
    rows: list[dict[str, Any]],
    field: str,
    group_fields: tuple[str, ...],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, ...]] = Counter()
    for row in rows:
        if _as_bool(row.get(field)):
            continue
        key = tuple(str(row.get(group_field) or "unknown") for group_field in group_fields)
        counter[key] += 1

    entries: list[dict[str, Any]] = []
    for key, count in counter.most_common(limit):
        entry = {group_field: value for group_field, value in zip(group_fields, key)}
        entry["missing_rows"] = count
        entries.append(entry)
    return entries


def _parameter_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    market_shifts = [_as_float(row.get("market_target_shift")) for row in rows]
    matchup_shifts = [_as_float(row.get("matchup_target_shift")) for row in rows]
    advanced_shifts = [_as_float(row.get("advanced_target_shift")) for row in rows]
    blend_weights = [_as_float(row.get("market_target_blend_weight")) for row in rows]
    return {
        "market_context_available_rate": _round_rate(
            sum(1 for row in rows if _as_bool(row.get("market_context_available"))),
            len(rows),
        ),
        "matchup_context_available_rate": _round_rate(
            sum(1 for row in rows if _as_bool(row.get("matchup_context_available"))),
            len(rows),
        ),
        "market_target_shift_mean": _round_float(_mean(market_shifts)),
        "market_target_shift_min": _round_float(min(market_shifts) if market_shifts else 0.0),
        "market_target_shift_max": _round_float(max(market_shifts) if market_shifts else 0.0),
        "market_target_blend_weight_mean": _round_float(_mean(blend_weights)),
        "matchup_target_shift_mean": _round_float(_mean(matchup_shifts)),
        "matchup_target_shift_min": _round_float(min(matchup_shifts) if matchup_shifts else 0.0),
        "matchup_target_shift_max": _round_float(max(matchup_shifts) if matchup_shifts else 0.0),
        "advanced_context_available_rate": _round_rate(
            sum(1 for row in rows if _as_bool(row.get("advanced_context_available"))),
            len(rows),
        ),
        "advanced_target_shift_mean": _round_float(_mean(advanced_shifts)),
        "advanced_target_shift_min": _round_float(min(advanced_shifts) if advanced_shifts else 0.0),
        "advanced_target_shift_max": _round_float(max(advanced_shifts) if advanced_shifts else 0.0),
        "flag_counts": _flag_counts(rows),
    }


def _build_warnings(
    *,
    coverage_summary: dict[str, float],
    parameter_summary: dict[str, Any],
    component_sources: dict[str, Any],
    matchups_manifest: dict[str, Any],
    market_manifest: dict[str, Any],
    roster_manifest: dict[str, Any],
    engine_board_manifest: dict[str, Any],
    coverage_by_game_date: dict[str, dict[str, float | int]],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    dropped_by_date = int(engine_board_manifest.get("dropped_by_date_filter_count") or 0)
    if dropped_by_date > 0:
        target = str(engine_board_manifest.get("game_date_filter") or "target date")
        warnings.append(
            {
                "severity": "low",
                "code": "future_date_props_filtered",
                "message": f"Engine board filtered {dropped_by_date} non-{target} props before scoring.",
            }
        )
    for game_date, values in coverage_by_game_date.items():
        if game_date == "unknown":
            continue
        row_count = int(values.get("row_count") or 0)
        if row_count <= 0:
            continue
        lineup_rate = float(values.get("lineup_context_available") or 0.0)
        pitcher_rate = float(values.get("probable_pitcher_context_available") or 0.0)
        statsapi_rate = float(values.get("statsapi_context_available") or 0.0)
        if lineup_rate == 0.0 and pitcher_rate == 0.0 and statsapi_rate == 0.0:
            warnings.append(
                {
                    "severity": "high",
                    "code": "game_date_context_missing",
                    "message": f"Game date {game_date} has {row_count} rows but no lineup, pitcher, or StatsAPI context.",
                }
            )
    if coverage_summary.get("external_market_context_available", 0.0) <= 0.0:
        warnings.append(
            {
                "severity": "high",
                "code": "external_market_context_zero",
                "message": "No OddsAPI market context reached probability parameters; market prior is operating neutral.",
            }
        )
    if component_sources.get("ballpark") == "missing":
        warnings.append(
            {
                "severity": "medium",
                "code": "ballpark_context_missing",
                "message": "No staged ballpark factors were available; park/environment scores are incomplete.",
            }
        )
    if coverage_summary.get("lineup_context_available", 1.0) < 0.75:
        warnings.append(
            {
                "severity": "medium",
                "code": "lineup_context_thin",
                "message": "Lineup coverage is below 75%; audit Rotowire lineup timing and player/team joins.",
            }
        )
    if coverage_summary.get("probable_pitcher_context_available", 1.0) < 0.85:
        warnings.append(
            {
                "severity": "medium",
                "code": "pitcher_context_thin",
                "message": "Probable pitcher/weather context is below 85%; some games are scoring closer to neutral.",
            }
        )
    if coverage_summary.get("roster_context_available", 1.0) < 0.95:
        warnings.append(
            {
                "severity": "medium",
                "code": "roster_context_thin",
                "message": "StatsAPI roster identity coverage is below 95%; player identity joins need review.",
            }
        )
    if float(matchups_manifest.get("pitcher_prop_missing_context_rate") or 0.0) > 0.10:
        warnings.append(
            {
                "severity": "medium",
                "code": "pitcher_prop_context_thin",
                "message": "Pitcher prop context has more than 10% missing rows.",
            }
        )
    if int(matchups_manifest.get("pitcher_prop_thin_context_count") or 0) > 0:
        warnings.append(
            {
                "severity": "low",
                "code": "pitcher_prop_era_only_context",
                "message": "Some pitcher props only have ERA-level context until deeper pitcher matrices are fed.",
            }
        )
    if float(parameter_summary.get("market_target_blend_weight_mean") or 0.0) == 0.0 and float(
        market_manifest.get("market_source_row_count") or 0.0
    ) == 0.0:
        warnings.append(
            {
                "severity": "medium",
                "code": "market_source_snapshot_missing",
                "message": "No normalized market rows were found for this run's dates.",
            }
        )
    if int(roster_manifest.get("roster_source_row_count") or 0) == 0:
        warnings.append(
            {
                "severity": "high",
                "code": "roster_source_missing",
                "message": "No StatsAPI roster source rows were available.",
            }
        )
    advanced_rate = coverage_summary.get("advanced_context_available", 0.0)
    if advanced_rate <= 0.0:
        warnings.append(
            {
                "severity": "low",
                "code": "advanced_profile_context_zero",
                "message": "No advanced player profile context reached probability parameters; advanced profiles are neutral.",
            }
        )
    elif advanced_rate < 0.75:
        warnings.append(
            {
                "severity": "low",
                "code": "advanced_profile_context_thin",
                "message": "Advanced player profile coverage is below 75%; profile source joins need review.",
            }
        )
    return warnings


def _selected_manifest_metrics(manifest: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in keys if key in manifest}


def _write_audit_artifacts(features_dir: Path, run_id: str, payload: dict[str, Any]) -> dict[str, str]:
    output_dir = features_dir / "context_audit" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "context_audit.json"
    csv_path = output_dir / "context_audit.csv"
    md_path = output_dir / "context_audit.md"

    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_summary_csv(csv_path, payload)
    md_path.write_text(_render_markdown(payload), encoding="utf-8")

    latest_dir = features_dir / "context_audit"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "latest.json").write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    (latest_dir / "latest.csv").write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    (latest_dir / "latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "markdown_path": str(md_path),
        "latest_json_path": str(latest_dir / "latest.json"),
        "latest_csv_path": str(latest_dir / "latest.csv"),
        "latest_markdown_path": str(latest_dir / "latest.md"),
    }


def _write_summary_csv(path: Path, payload: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for source, rate in payload["coverage_summary"].items():
        rows.append({"section": "overall", "name": source, "metric": "coverage_rate", "value": rate})
    for group, values in payload["coverage_by_market_group"].items():
        for source, value in values.items():
            rows.append({"section": "market_group", "name": group, "metric": source, "value": value})
    for team, values in payload.get("coverage_by_team", {}).items():
        for source, value in values.items():
            rows.append({"section": "team", "name": team, "metric": source, "value": value})
    for field, sections in payload.get("missing_drivers", {}).items():
        for section, entries in sections.items():
            for entry in entries[:10]:
                rows.append(
                    {
                        "section": f"missing_{section}",
                        "name": field,
                        "metric": " | ".join(
                            f"{key}={value}" for key, value in entry.items() if key != "missing_rows"
                        ),
                        "value": entry.get("missing_rows", 0),
                    }
                )
    for game_date, values in payload.get("coverage_by_game_date", {}).items():
        for source, value in values.items():
            rows.append({"section": "game_date", "name": game_date, "metric": source, "value": value})
    for warning in payload["warnings"]:
        rows.append(
            {
                "section": "warning",
                "name": warning["code"],
                "metric": warning["severity"],
                "value": warning["message"],
            }
        )

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("section", "name", "metric", "value"))
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# MLB Context Audit: {payload['run_id']}",
        "",
        "## Overall Coverage",
        "",
        "| Source | Coverage |",
        "|---|---:|",
    ]
    for source, rate in payload["coverage_summary"].items():
        lines.append(f"| {source} | {rate:.2%} |")

    lines.extend(["", "## Warnings", ""])
    if payload["warnings"]:
        for warning in payload["warnings"]:
            lines.append(f"- **{warning['severity']}** `{warning['code']}`: {warning['message']}")
    else:
        lines.append("- none")

    engine_board = payload.get("manifest_metrics", {}).get("engine_board", {})
    if engine_board:
        lines.extend(
            [
                "",
                "## Date Filter",
                "",
                f"- policy: `{engine_board.get('date_filter_policy', 'unknown')}`",
                f"- target: `{engine_board.get('game_date_filter', '') or 'all'}`",
                f"- rows before: `{engine_board.get('source_row_count', engine_board.get('row_count', 0))}`",
                f"- rows after: `{engine_board.get('row_count', 0)}`",
                f"- dropped: `{engine_board.get('dropped_by_date_filter_count', 0)}`",
            ]
        )

    lines.extend(["", "## Game Date Coverage", "", "| Date | Rows | Market | Matchup | Lineup | Pitcher | Roster | Advanced |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for game_date, values in payload.get("coverage_by_game_date", {}).items():
        lines.append(
            "| {date} | {rows} | {market:.2%} | {matchup:.2%} | {lineup:.2%} | {pitcher:.2%} | {roster:.2%} | {advanced:.2%} |".format(
                date=game_date,
                rows=values.get("row_count", 0),
                market=float(values.get("external_market_context_available", 0.0)),
                matchup=float(values.get("matchup_context_available", 0.0)),
                lineup=float(values.get("lineup_context_available", 0.0)),
                pitcher=float(values.get("probable_pitcher_context_available", 0.0)),
                roster=float(values.get("roster_context_available", 0.0)),
                advanced=float(values.get("advanced_context_available", 0.0)),
            )
        )

    lines.extend(["", "## Market Group Coverage", "", "| Group | Rows | Market | Matchup | Lineup | Pitcher | Roster | Advanced |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for group, values in payload["coverage_by_market_group"].items():
        lines.append(
            "| {group} | {rows} | {market:.2%} | {matchup:.2%} | {lineup:.2%} | {pitcher:.2%} | {roster:.2%} | {advanced:.2%} |".format(
                group=group,
                rows=values.get("row_count", 0),
                market=float(values.get("external_market_context_available", 0.0)),
                matchup=float(values.get("matchup_context_available", 0.0)),
                lineup=float(values.get("lineup_context_available", 0.0)),
                pitcher=float(values.get("probable_pitcher_context_available", 0.0)),
                roster=float(values.get("roster_context_available", 0.0)),
                advanced=float(values.get("advanced_context_available", 0.0)),
            )
        )

    lines.extend(
        [
            "",
            "## Team Coverage",
            "",
            "| Team | Rows | Market | Matchup | Lineup | Pitcher | Roster | Advanced |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for team, values in payload.get("coverage_by_team", {}).items():
        lines.append(
            "| {team} | {rows} | {market:.2%} | {matchup:.2%} | {lineup:.2%} | {pitcher:.2%} | {roster:.2%} | {advanced:.2%} |".format(
                team=team,
                rows=values.get("row_count", 0),
                market=float(values.get("external_market_context_available", 0.0)),
                matchup=float(values.get("matchup_context_available", 0.0)),
                lineup=float(values.get("lineup_context_available", 0.0)),
                pitcher=float(values.get("probable_pitcher_context_available", 0.0)),
                roster=float(values.get("roster_context_available", 0.0)),
                advanced=float(values.get("advanced_context_available", 0.0)),
            )
        )

    lines.extend(["", "## Top Missing Drivers", ""])
    for field, sections in payload.get("missing_drivers", {}).items():
        lines.extend([f"### {field}", ""])
        team_entries = sections.get("teams", [])[:5]
        market_entries = sections.get("markets", [])[:5]
        player_entries = sections.get("players", [])[:5]
        if team_entries:
            lines.append("Top teams:")
            for entry in team_entries:
                lines.append(f"- `{entry.get('player_team')}`: {entry.get('missing_rows')} rows")
        if market_entries:
            lines.append("Top markets:")
            for entry in market_entries:
                lines.append(
                    f"- `{entry.get('market_group')}/{entry.get('market')}`: {entry.get('missing_rows')} rows"
                )
        if player_entries:
            lines.append("Top players:")
            for entry in player_entries:
                lines.append(
                    "- `{player}` {team} {market}: {rows} rows".format(
                        player=entry.get("player_name"),
                        team=entry.get("team"),
                        market=entry.get("market"),
                        rows=entry.get("missing_rows"),
                    )
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def _flag_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        flags = row.get("flags")
        if isinstance(flags, list):
            counter.update(str(flag) for flag in flags)
        elif flags:
            counter.update(part.strip() for part in str(flags).split("|") if part.strip())
    return dict(counter.most_common())


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _round_rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 6)


def _round_float(value: float) -> float:
    return round(float(value), 6)


def _audit_lines(payload: dict[str, Any]) -> list[str]:
    engine_board = payload.get("manifest_metrics", {}).get("engine_board", {})
    lines = [
        f"[MLB_CONTEXT_AUDIT] run_id={payload['run_id']} rows={payload['row_count']} warnings={len(payload['warnings'])}",
        "Coverage:",
    ]
    if engine_board:
        lines.append(
            "Date filter: policy={policy} target={target} dropped={dropped}".format(
                policy=engine_board.get("date_filter_policy", "unknown"),
                target=engine_board.get("game_date_filter") or "all",
                dropped=engine_board.get("dropped_by_date_filter_count", 0),
            )
        )
    for source, rate in payload["coverage_summary"].items():
        lines.append(f"  - {source}: {rate:.2%}")
    if payload["warnings"]:
        lines.append("Warnings:")
        for warning in payload["warnings"]:
            lines.append(f"  - {warning['severity'].upper()} {warning['code']}: {warning['message']}")
    if "artifact_paths" in payload:
        lines.append(f"Wrote: {payload['artifact_paths']['json_path']}")
        lines.append(f"Wrote: {payload['artifact_paths']['markdown_path']}")
    return lines

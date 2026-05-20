"""Advanced player profile context for MLB props.

This module is intentionally source-neutral. Baseball Savant, Rotowire, or any
future paid source can write CSV/JSON rows into the profile contract; the model
then receives stable per-prop context rows. Missing sources stay neutral.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.market_context import latest_engine_board_path
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

ADVANCED_PROFILE_VERSION = "advanced_player_profiles_v1"
ADVANCED_CONTEXT_VERSION = "advanced_player_context_v1"

ADVANCED_PROFILE_COLUMNS = (
    "statsapi_person_id",
    "player_id",
    "player_name",
    "player_name_key",
    "player_team",
    "bats",
    "throws",
    "profile_role",
    "sample_pa",
    "sample_bf",
    "xera",
    "xwoba",
    "xba",
    "xslg",
    "woba",
    "ba",
    "slg",
    "era",
    "iso",
    "barrel_rate",
    "hard_hit_rate",
    "k_rate",
    "bb_rate",
    "whiff_rate",
    "chase_rate",
    "contact_rate",
    "avg_exit_velocity",
    "avg_launch_angle",
    "sweet_spot_rate",
    "avg_best_speed",
    "source",
    "flags",
)

ADVANCED_CONTEXT_COLUMNS = (
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
    "advanced_context_available",
    "advanced_context_score",
    "advanced_hit_context_score",
    "advanced_power_context_score",
    "advanced_plate_discipline_score",
    "advanced_k_context_score",
    "advanced_contact_quality_score",
    "advanced_sample_confidence",
    "advanced_profile_source",
    "advanced_profile_match_type",
    "advanced_context_flags",
)


def prepare_advanced_profiles_result(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    """Stage source CSV/JSON player profile rows into the advanced profile contract."""

    manifest = prepare_advanced_profile_artifacts(source_path=source_path, root=root, run_id=run_id)
    lines = [
        "Prepared MLB advanced player profiles:",
        f"  run_id: {manifest['run_id']}",
        f"  source_path: {manifest['source_path']}",
        f"  row_count: {manifest['row_count']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="prepare_advanced_profiles", payload=manifest, lines=tuple(lines))


def build_advanced_context_result(
    *,
    engine_board_path: Path | None = None,
    source_path: Path | None = None,
    profiles_path: Path | None = None,
    roster_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> RuntimeCommandResult:
    """Build per-prop advanced profile context rows for an engine board."""

    manifest = build_advanced_context_artifacts(
        engine_board_path=engine_board_path,
        source_path=source_path,
        profiles_path=profiles_path,
        roster_context_path=roster_context_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
    )
    lines = [
        "Built MLB advanced player context:",
        f"  run_id: {manifest['run_id']}",
        f"  row_count: {manifest['row_count']}",
        f"  coverage_rate: {manifest['coverage_rate']:.2%}",
        f"  profile_source_row_count: {manifest['profile_source_row_count']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="build_advanced_context", payload=manifest, lines=tuple(lines))


def prepare_advanced_profile_artifacts(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Normalize raw advanced profile rows into staged artifacts."""

    paths = ensure_mlb_dirs(root)
    resolved_run_id = run_id or source_path.stem
    raw_rows = _load_source_rows(source_path)
    source_name = source_path.parent.name or source_path.stem
    rows = [_normalize_profile_row(row, source=source_name) for row in raw_rows]

    output_dir = paths.staged / "advanced_profiles" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "advanced_profiles.csv"
    json_path = output_dir / "advanced_profiles.json"
    manifest_path = output_dir / "advanced_profiles_manifest.json"
    _write_csv(csv_path, rows, ADVANCED_PROFILE_COLUMNS)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "row_count": len(rows), "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "source_path": str(source_path),
        "row_count": len(rows),
        "profile_version": ADVANCED_PROFILE_VERSION,
        "profile_role_counts": _counts(row["profile_role"] for row in rows),
        "source_counts": _counts(row["source"] for row in rows),
        "flag_counts": _flag_counts(row["flags"] for row in rows),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.staged / "advanced_profiles" / "latest.csv"),
        "latest_json_path": str(paths.staged / "advanced_profiles" / "latest.json"),
        "latest_manifest_path": str(paths.staged / "advanced_profiles" / "latest_manifest.json"),
        "columns": list(ADVANCED_PROFILE_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.staged / "advanced_profiles" / "latest.csv")
    _copy_latest(json_path, paths.staged / "advanced_profiles" / "latest.json")
    _copy_latest(manifest_path, paths.staged / "advanced_profiles" / "latest_manifest.json")
    return manifest


def build_advanced_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    source_path: Path | None = None,
    profiles_path: Path | None = None,
    roster_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> dict[str, Any]:
    """Write advanced player profile context for each engine-board prop."""

    paths = ensure_mlb_dirs(root)
    resolved_engine_board_path = engine_board_path or latest_engine_board_path(root=root)
    engine_board = _load_json(resolved_engine_board_path)
    resolved_run_id = run_id or str(engine_board.get("run_id") or resolved_engine_board_path.parent.name)

    staged_profile_manifest: dict[str, Any] | None = None
    if source_path:
        staged_profile_manifest = prepare_advanced_profile_artifacts(
            source_path=source_path,
            root=root,
            run_id=f"{resolved_run_id}_profiles",
        )
        profiles_path = Path(staged_profile_manifest["json_path"])
    resolved_profiles_path = profiles_path or _latest_profiles_path(root=root, game_date=game_date)
    profiles = _load_profile_rows(resolved_profiles_path)
    indexes = _index_profiles(profiles)
    roster_rows = _load_context_rows(roster_context_path)

    source_rows = [
        row
        for row in engine_board.get("rows", [])
        if isinstance(row, dict) and (not game_date or str(row.get("game_date") or "") == game_date)
    ]
    rows = []
    for row in source_rows:
        profile, match_type = _find_profile(
            row,
            indexes,
            roster_row=roster_rows.get(_matchup_key(row)),
        )
        rows.append(_advanced_context_row(row, run_id=resolved_run_id, profile=profile, match_type=match_type))

    output_dir = paths.features / "advanced_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "advanced_context.csv"
    json_path = output_dir / "advanced_context.json"
    manifest_path = output_dir / "advanced_context_manifest.json"
    _write_csv(csv_path, rows, ADVANCED_CONTEXT_COLUMNS)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "row_count": len(rows), "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    coverage_rate = _true_rate(row["advanced_context_available"] for row in rows) or 0.0
    manifest = {
        "run_id": resolved_run_id,
        "engine_board_path": str(resolved_engine_board_path),
        "game_date": game_date or "",
        "profiles_path": str(resolved_profiles_path) if resolved_profiles_path else "",
        "roster_context_path": str(roster_context_path) if roster_context_path else "",
        "staged_profile_manifest": staged_profile_manifest or {},
        "row_count": len(rows),
        "profile_source_row_count": len(profiles),
        "coverage_rate": coverage_rate,
        "advanced_context_version": ADVANCED_CONTEXT_VERSION,
        "advanced_profile_version": ADVANCED_PROFILE_VERSION,
        "match_type_counts": _counts(row["advanced_profile_match_type"] for row in rows),
        "advanced_context_flag_counts": _flag_counts(row["advanced_context_flags"] for row in rows),
        "advanced_context_score_mean": _mean(row["advanced_context_score"] for row in rows),
        "advanced_sample_confidence_mean": _mean(row["advanced_sample_confidence"] for row in rows),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "advanced_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "advanced_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "advanced_context" / "latest_manifest.json"),
        "columns": list(ADVANCED_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "advanced_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "advanced_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "advanced_context" / "latest_manifest.json")
    return manifest


def _normalize_profile_row(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    player_name = _player_name(_first_text(row, "player_name", "last_name, first_name", "name", "batter_name", "pitcher_name"))
    player_team = _first_text(row, "player_team", "team", "team_abbreviation", "mlb_team", "current_team")
    sample_pa = _int(_first_value(row, "sample_pa", "pa", "plate_appearances", "batter_pa"))
    sample_bf = _int(_first_value(row, "sample_bf", "bf", "batters_faced", "pitcher_bf"))
    flags = []
    if not player_name:
        flags.append("missing_player_name")
    if not player_team:
        flags.append("missing_player_team")
    if sample_pa < 25 and sample_bf < 25:
        flags.append("thin_advanced_sample")
    role = _profile_role(row, sample_pa=sample_pa, sample_bf=sample_bf)
    return {
        "statsapi_person_id": _int(_first_value(row, "statsapi_person_id", "person_id", "mlbam_id", "mlb_id")),
        "player_id": _first_text(row, "player_id", "id"),
        "player_name": player_name,
        "player_name_key": _player_key(player_name),
        "player_team": canonical_team_abbr(player_team),
        "bats": _first_text(row, "bats", "bat_side", "stand").upper(),
        "throws": _first_text(row, "throws", "throw_hand", "p_throws").upper(),
        "profile_role": role,
        "sample_pa": sample_pa,
        "sample_bf": sample_bf,
        "xera": _float(_first_value(row, "xera")),
        "xwoba": _float(_first_value(row, "xwoba", "est_woba", "estimated_woba_using_speedangle")),
        "xba": _float(_first_value(row, "xba", "est_ba", "estimated_ba_using_speedangle")),
        "xslg": _float(_first_value(row, "xslg", "est_slg", "estimated_slg_using_speedangle")),
        "woba": _float(_first_value(row, "woba")),
        "ba": _float(_first_value(row, "ba")),
        "slg": _float(_first_value(row, "slg")),
        "era": _float(_first_value(row, "era")),
        "iso": _float(_first_value(row, "iso")),
        "barrel_rate": _rate(_first_value(row, "barrel_rate", "barrel_batted_rate", "brl_percent")),
        "hard_hit_rate": _rate(_first_value(row, "hard_hit_rate", "hardhit_rate", "hard_hit_percent")),
        "k_rate": _rate(_first_value(row, "k_rate", "strikeout_rate", "k_percent", "so_percent")),
        "bb_rate": _rate(_first_value(row, "bb_rate", "walk_rate", "bb_percent")),
        "whiff_rate": _rate(_first_value(row, "whiff_rate", "whiff_percent")),
        "chase_rate": _rate(_first_value(row, "chase_rate", "chase_percent", "ozone_swing_percent")),
        "contact_rate": _rate(_first_value(row, "contact_rate", "contact_percent")),
        "avg_exit_velocity": _float(_first_value(row, "avg_exit_velocity", "exit_velocity_avg", "avg_ev")),
        "avg_launch_angle": _float(_first_value(row, "avg_launch_angle", "launch_angle_avg", "avg_la")),
        "sweet_spot_rate": _rate(_first_value(row, "sweet_spot_rate", "sweet_spot_percent")),
        "avg_best_speed": _float(_first_value(row, "avg_best_speed", "ev50")),
        "source": _first_text(row, "source") or source,
        "flags": tuple(flags),
    }


def _advanced_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    profile: dict[str, Any] | None,
    match_type: str,
) -> dict[str, Any]:
    scores = _context_scores(profile)
    flags = list(scores["flags"])
    if match_type:
        flags.append(match_type)
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
        "tier": str(row.get("tier") or "STANDARD"),
        "advanced_context_available": scores["available"],
        "advanced_context_score": scores["context_score"],
        "advanced_hit_context_score": scores["hit_score"],
        "advanced_power_context_score": scores["power_score"],
        "advanced_plate_discipline_score": scores["plate_discipline_score"],
        "advanced_k_context_score": scores["k_context_score"],
        "advanced_contact_quality_score": scores["contact_quality_score"],
        "advanced_sample_confidence": scores["sample_confidence"],
        "advanced_profile_source": str(profile.get("source") or "") if profile else "",
        "advanced_profile_match_type": match_type,
        "advanced_context_flags": tuple(flags),
    }


def _context_scores(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {
            "available": False,
            "context_score": 0.0,
            "hit_score": 0.0,
            "power_score": 0.0,
            "plate_discipline_score": 0.0,
            "k_context_score": 0.0,
            "contact_quality_score": 0.0,
            "sample_confidence": 0.0,
            "flags": ("missing_advanced_profile",),
        }

    sample = max(_int(profile.get("sample_pa")), _int(profile.get("sample_bf")))
    sample_confidence = _clamp(sample / 250.0, 0.10, 1.0)
    xwoba_score = _score_metric(profile.get("xwoba"), center=0.320, scale=0.080)
    xba_score = _score_metric(profile.get("xba"), center=0.245, scale=0.060)
    xslg_score = _score_metric(profile.get("xslg"), center=0.410, scale=0.150)
    iso_score = _score_metric(profile.get("iso"), center=0.160, scale=0.100)
    barrel_score = _score_metric(profile.get("barrel_rate"), center=0.075, scale=0.060)
    hard_hit_score = _score_metric(profile.get("hard_hit_rate"), center=0.380, scale=0.150)
    sweet_spot_score = _score_metric(profile.get("sweet_spot_rate"), center=0.340, scale=0.120)
    avg_best_speed_score = _score_metric(profile.get("avg_best_speed"), center=96.0, scale=8.0)
    bb_score = _score_metric(profile.get("bb_rate"), center=0.085, scale=0.060)
    chase_score = _score_metric(profile.get("chase_rate"), center=0.300, scale=0.120, invert=True)
    contact_score = _score_metric(profile.get("contact_rate"), center=0.760, scale=0.120)
    whiff_risk = _score_metric(profile.get("whiff_rate"), center=0.240, scale=0.120)
    k_risk = _score_metric(profile.get("k_rate"), center=0.220, scale=0.100)

    hit_score = _mean((xba_score, contact_score, xwoba_score, sweet_spot_score))
    power_score = _mean((xslg_score, iso_score, barrel_score, hard_hit_score, avg_best_speed_score))
    plate_score = _mean((bb_score, chase_score))
    k_context_score = _mean((k_risk, whiff_risk, -contact_score))
    contact_quality_score = _mean((xwoba_score, hard_hit_score, barrel_score))
    context_score = _mean((hit_score, power_score, plate_score, contact_quality_score, -0.35 * k_context_score))
    flags = list(profile.get("flags") or [])
    flags.append("advanced_profile_context_available")
    return {
        "available": True,
        "context_score": round(_clamp(context_score, -1.0, 1.0), 6),
        "hit_score": round(_clamp(hit_score, -1.0, 1.0), 6),
        "power_score": round(_clamp(power_score, -1.0, 1.0), 6),
        "plate_discipline_score": round(_clamp(plate_score, -1.0, 1.0), 6),
        "k_context_score": round(_clamp(k_context_score, -1.0, 1.0), 6),
        "contact_quality_score": round(_clamp(contact_quality_score, -1.0, 1.0), 6),
        "sample_confidence": round(sample_confidence, 6),
        "flags": tuple(flags),
    }


def _load_source_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Advanced profile source not found: {path}")
    if path.suffix.lower() == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("rows") or payload.get("data") or payload.get("players") or []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _load_profile_rows(path: Path | None) -> list[dict[str, Any]]:
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


def _latest_profiles_path(*, root: Path | None = None, game_date: str | None = None) -> Path | None:
    paths = ensure_mlb_dirs(root)
    latest = paths.staged / "advanced_profiles" / "latest.json"
    if latest.exists() and not game_date:
        return latest
    candidates = sorted(
        (paths.staged / "advanced_profiles").glob("*/advanced_profiles.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if game_date:
        target = _date_key(game_date)
        candidates = [
            path
            for path in candidates
            if (source_date := _date_key(path.parent.name)) and target and source_date <= target
        ]
        candidates = sorted(candidates, key=_date_safe_profile_sort_key)
    return candidates[-1] if candidates else None


def _date_safe_profile_sort_key(path: Path) -> tuple[str, int, float, str]:
    return (
        _date_key(path.parent.name),
        1 if "asof" in path.parent.name.lower() else 0,
        path.stat().st_mtime,
        path.parent.name,
    )


def _index_profiles(rows: list[dict[str, Any]]) -> dict[str, dict[Any, Any]]:
    by_person_id: dict[int, dict[str, Any]] = {}
    by_name_team: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        person_id = _int(row.get("statsapi_person_id"))
        if person_id:
            by_person_id[person_id] = row
        name_keys = {
            str(row.get("player_name_key") or ""),
            _player_key(row.get("player_name")),
        }
        name_keys = {key for key in name_keys if key}
        team = canonical_team_abbr(row.get("player_team"))
        for name_key in name_keys:
            if team:
                by_name_team[(name_key, team)] = row
            by_name.setdefault(name_key, []).append(row)
    return {"by_person_id": by_person_id, "by_name_team": by_name_team, "by_name": by_name}


def _find_profile(
    row: dict[str, Any],
    indexes: dict[str, dict[Any, Any]],
    *,
    roster_row: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    roster_person_id = _int((roster_row or {}).get("statsapi_person_id"))
    if roster_person_id:
        profile = indexes["by_person_id"].get(roster_person_id)
        if profile:
            return profile, "exact_roster_statsapi_person_id_match"
    person_id = _int(row.get("statsapi_person_id") or row.get("player_id"))
    if person_id:
        profile = indexes["by_person_id"].get(person_id)
        if profile:
            return profile, "exact_statsapi_person_id_match"
    name_key = _player_key(row.get("player_name"))
    team = canonical_team_abbr(row.get("player_team"))
    if name_key and team:
        profile = indexes["by_name_team"].get((name_key, team))
        if profile:
            return profile, "exact_player_team_profile_match"
    candidates = indexes["by_name"].get(name_key, []) if name_key else []
    if len(candidates) == 1:
        return candidates[0], "unique_player_name_profile_match"
    if len(candidates) > 1:
        return None, "ambiguous_player_name_profile_match"
    return None, ""


def _load_context_rows(path: Path | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return {}
    return {_matchup_key(row): row for row in rows if isinstance(row, dict)}


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


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _first_text(row: dict[str, Any], *keys: str) -> str:
    value = _first_value(row, *keys)
    return str(value or "").strip()


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return ""


def _profile_role(row: dict[str, Any], *, sample_pa: int, sample_bf: int) -> str:
    role = _first_text(row, "profile_role", "role", "player_type").lower()
    if role in {"hitter", "pitcher"}:
        return role
    if sample_bf > sample_pa:
        return "pitcher"
    if sample_pa > 0:
        return "hitter"
    return "unknown"


def _player_name(value: Any) -> str:
    text = _first_text({"value": value}, "value")
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def _score_metric(value: Any, *, center: float, scale: float, invert: bool = False) -> float:
    number = _float(value)
    if number == 0.0:
        return 0.0
    score = _clamp((number - center) / scale, -1.0, 1.0)
    return -score if invert else score


def _rate(value: Any) -> float:
    number = _float(value)
    if abs(number) > 1.5:
        return number / 100.0
    return number


def _flag_counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for flag in _tuple_flags(value):
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _true_rate(values: Iterable[Any]) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _mean(values: Iterable[Any]) -> float:
    collected = [_float(value) for value in values]
    if not collected:
        return 0.0
    return round(sum(collected) / len(collected), 6)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return (stripped,)
            return _tuple_flags(decoded)
        if "|" in stripped:
            return tuple(part.strip() for part in stripped.split("|") if part.strip())
        return (stripped,)
    if isinstance(value, (tuple, list, set)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _player_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    return "".join(token for token in text.split() if token not in suffixes)


def _date_key(value: Any) -> str:
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", str(value or ""))
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

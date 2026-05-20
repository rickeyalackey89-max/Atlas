"""Normalization for Baseball Savant MLB context snapshots."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

_DATA_VAR_RE = re.compile(r"var\s+data\s*=\s*(?P<data>\[.*?\]);", re.S)

_MLB_TEAM_ID_TO_ABBR = {
    "108": "LAA",
    "109": "ARI",
    "110": "BAL",
    "111": "BOS",
    "112": "CHC",
    "113": "CIN",
    "114": "CLE",
    "115": "COL",
    "116": "DET",
    "117": "HOU",
    "118": "KC",
    "119": "LAD",
    "120": "WSH",
    "121": "NYM",
    "133": "OAK",
    "134": "PIT",
    "135": "SD",
    "136": "SEA",
    "137": "SF",
    "138": "STL",
    "139": "TB",
    "140": "TEX",
    "141": "TOR",
    "142": "MIN",
    "143": "PHI",
    "144": "ATL",
    "145": "CWS",
    "146": "MIA",
    "147": "NYY",
    "158": "MIL",
}


def normalize_baseball_savant_context(payload: dict[str, Any], *, snapshot_id: str = "") -> dict[str, Any]:
    """Normalize Baseball Savant raw pages into source rows for internal contracts."""

    pages = _pages(payload)
    batter_rows = _merge_profile_rows(
        _data_rows(pages.get("expected_batter", {})),
        _data_rows(pages.get("custom_batter", {})),
        _data_rows(pages.get("statcast_search_batter", {})),
    )
    pitcher_rows = _merge_profile_rows(
        _data_rows(pages.get("expected_pitcher", {})),
        _data_rows(pages.get("custom_pitcher", {})),
        _data_rows(pages.get("statcast_search_pitcher", {})),
    )
    park_rows = _data_rows(pages.get("park_factors", {}))
    schedule_rows = _json_rows(pages.get("schedule", {}))
    trending_rows = _json_rows(pages.get("trending_players", {}))

    advanced_profiles = [
        _advanced_profile_row(row, role="hitter", snapshot_id=snapshot_id)
        for row in batter_rows
        if _value(row, "player_id") and _value(row, "player_name", "last_name, first_name")
    ]
    advanced_profiles.extend(
        _advanced_profile_row(row, role="pitcher", snapshot_id=snapshot_id)
        for row in pitcher_rows
        if _value(row, "player_id") and _value(row, "player_name", "last_name, first_name")
    )

    ballparks = [
        _ballpark_row(row, snapshot_id=snapshot_id)
        for row in park_rows
        if _value(row, "venue_id") or _value(row, "venue_name")
    ]

    return {
        "snapshot_id": snapshot_id,
        "source": "baseball_savant_context",
        "game_date": _clean(payload.get("game_date")),
        "season": _clean(payload.get("season")),
        "advanced_profiles": advanced_profiles,
        "ballparks": ballparks,
        "schedule": [_source_row(row, "schedule", snapshot_id=snapshot_id) for row in schedule_rows],
        "trending_players": [_source_row(row, "trending_players", snapshot_id=snapshot_id) for row in trending_rows],
        "raw_page_status": {
            page_name: {
                "status_code": page.get("status_code"),
                "content_type": page.get("content_type", ""),
                "resolved_url": page.get("resolved_url", ""),
            }
            for page_name, page in pages.items()
        },
        "parse_warnings": _warnings(pages, batter_rows, pitcher_rows, park_rows),
    }


def write_baseball_savant_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a saved Baseball Savant context snapshot and write staged artifacts."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or "baseball_savant_context")
    normalized = normalize_baseball_savant_context(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or resolved_run_id),
    )

    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "baseball_savant" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "advanced_profiles_json": _write_json(
            output_dir / "advanced_profiles_source.json",
            normalized["advanced_profiles"],
            run_id=resolved_run_id,
        ),
        "advanced_profiles_jsonl": _write_jsonl(
            output_dir / "advanced_profiles_source.jsonl",
            normalized["advanced_profiles"],
        ),
        "ballparks_json": _write_json(
            output_dir / "ballpark_factors_source.json",
            normalized["ballparks"],
            run_id=resolved_run_id,
        ),
        "ballparks_jsonl": _write_jsonl(output_dir / "ballpark_factors_source.jsonl", normalized["ballparks"]),
        "schedule_jsonl": _write_jsonl(output_dir / "schedule.jsonl", normalized["schedule"]),
        "trending_players_jsonl": _write_jsonl(output_dir / "trending_players.jsonl", normalized["trending_players"]),
    }

    out = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": "baseball_savant_context",
        "game_date": normalized["game_date"],
        "season": normalized["season"],
        "output_dir": str(output_dir),
        "row_counts": {
            "advanced_profiles": len(normalized["advanced_profiles"]),
            "ballparks": len(normalized["ballparks"]),
            "schedule": len(normalized["schedule"]),
            "trending_players": len(normalized["trending_players"]),
        },
        "artifacts": artifacts,
        "raw_page_status": normalized["raw_page_status"],
        "parse_warnings": normalized["parse_warnings"],
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _advanced_profile_row(row: dict[str, Any], *, role: str, snapshot_id: str) -> dict[str, Any]:
    player_id = _clean(_value(row, "player_id"))
    sample_pa = _number(_value(row, "b_total_pa", "pa")) if role == "hitter" else 0.0
    sample_bf = _number(_value(row, "p_total_pa", "pa")) if role == "pitcher" else 0.0
    source_kind = "expected_statistics" if _value(row, "est_woba", "est_ba", "est_slg", "xera") else "custom"
    return {
        "source": f"baseball_savant_{source_kind}_{role}",
        "snapshot_id": snapshot_id,
        "statsapi_person_id": player_id,
        "player_id": player_id,
        "player_name": _player_name(_clean(_value(row, "player_name", "last_name, first_name"))),
        "player_team": _clean(_value(row, "player_team", "team", "team_abbr")).upper(),
        "profile_role": role,
        "sample_pa": int(sample_pa),
        "sample_bf": int(sample_bf),
        "bats": _clean(_value(row, "bats", "stand")).upper(),
        "throws": _clean(_value(row, "throws", "pitch_hand")).upper(),
        "xera": _float_or_blank(_value(row, "xera")),
        "xwoba": _float_or_blank(_value(row, "xwoba", "est_woba")),
        "xba": _float_or_blank(_value(row, "xba", "est_ba")),
        "xslg": _float_or_blank(_value(row, "xslg", "est_slg")),
        "woba": _float_or_blank(_value(row, "woba")),
        "ba": _float_or_blank(_value(row, "ba")),
        "slg": _float_or_blank(_value(row, "slg", "slg_percent")),
        "era": _float_or_blank(_value(row, "era")),
        "iso": _float_or_blank(_value(row, "iso", "isolated_power", "xiso")),
        "barrel_rate": _float_or_blank(
            _value(row, "barrel_batted_rate", "barrel", "barrels_per_bbe_percent")
        ),
        "hard_hit_rate": _float_or_blank(_value(row, "hard_hit_percent", "hardhit_percent")),
        "k_rate": _float_or_blank(_value(row, "k_percent")),
        "bb_rate": _float_or_blank(_value(row, "bb_percent")),
        "whiff_rate": _float_or_blank(_value(row, "whiff_percent", "swing_miss_percent")),
        "chase_rate": _float_or_blank(_value(row, "oz_swing_percent")),
        "contact_rate": _float_or_blank(_value(row, "iz_contact_percent", "oz_contact_percent")),
        "avg_exit_velocity": _float_or_blank(_value(row, "exit_velocity_avg", "launch_speed")),
        "avg_launch_angle": _float_or_blank(_value(row, "launch_angle_avg", "launch_angle")),
        "sweet_spot_rate": _float_or_blank(_value(row, "sweet_spot_percent")),
        "avg_best_speed": _float_or_blank(_value(row, "avg_best_speed", "hyper_speed")),
        "flags": _flags("baseball_savant", "missing_team" if not _value(row, "player_team", "team", "team_abbr") else ""),
    }


def _ballpark_row(row: dict[str, Any], *, snapshot_id: str) -> dict[str, Any]:
    main_team_id = _clean(_value(row, "main_team_id"))
    return {
        "source": "baseball_savant_statcast_park_factors",
        "snapshot_id": snapshot_id,
        "park_id": _clean(_value(row, "venue_id")),
        "park_name": _clean(_value(row, "venue_name")),
        "team": _MLB_TEAM_ID_TO_ABBR.get(main_team_id, _clean(_value(row, "team", "name_display_club")).upper()),
        "park_run_factor": _factor(_value(row, "index_runs")),
        "park_hr_factor": _factor(_value(row, "index_hr")),
        "park_hit_factor": _factor(_value(row, "index_hits")),
        "park_extra_base_factor": _weighted_extra_base_factor(row),
        "year_range": _clean(_value(row, "year_range")),
        "sample_pa": int(_number(_value(row, "n_pa"))),
        "flags": _flags("baseball_savant", "missing_team" if not main_team_id else ""),
    }


def _source_row(row: dict[str, Any], page: str, *, snapshot_id: str) -> dict[str, Any]:
    return {"source": "baseball_savant_context", "snapshot_id": snapshot_id, "page": page, **row}


def _pages(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return {}
    return {str(page.get("page") or ""): page for page in data if isinstance(page, dict)}


def _data_rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    body = str(page.get("body") or "")
    if not body:
        return []
    content_type = str(page.get("content_type") or "").lower()
    page_name = str(page.get("page") or "")
    if "csv" in content_type or page_name.startswith("statcast_search") or body.lstrip("\ufeff").startswith('"'):
        return _csv_rows(body)
    if "json" in content_type:
        return _json_rows(page)
    match = _DATA_VAR_RE.search(body)
    if not match:
        return []
    try:
        rows = json.loads(match.group("data"))
    except json.JSONDecodeError:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _merge_profile_rows(*row_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    unkeyed = 0
    for rows in row_groups:
        for row in rows:
            key = _clean(_value(row, "player_id"))
            if not key:
                key = f"_unkeyed_{unkeyed}"
                unkeyed += 1
            if key not in merged:
                merged[key] = {}
                order.append(key)
            merged[key].update(row)
    return [merged[key] for key in order]


def _csv_rows(body: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body.lstrip("\ufeff")))
    rows = []
    for raw_row in reader:
        row = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            normalized_key = str(key).lstrip("\ufeff").strip().strip('"')
            row[normalized_key] = value
        rows.append(row)
    return rows


def _json_rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    body = str(page.get("body") or "")
    if not body:
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "games", "players"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [payload]
    return []


def _warnings(
    pages: dict[str, dict[str, Any]],
    batter_rows: list[dict[str, Any]],
    pitcher_rows: list[dict[str, Any]],
    park_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    warnings = []
    batter_pages = (pages.get("expected_batter"), pages.get("custom_batter"), pages.get("statcast_search_batter"))
    pitcher_pages = (pages.get("expected_pitcher"), pages.get("custom_pitcher"), pages.get("statcast_search_pitcher"))
    if not any(batter_pages):
        warnings.append({"page": "expected_batter/custom_batter/statcast_search_batter", "warning": "missing_page"})
    if not any(pitcher_pages):
        warnings.append({"page": "expected_pitcher/custom_pitcher/statcast_search_pitcher", "warning": "missing_page"})
    if any(batter_pages) and not batter_rows:
        warnings.append({"page": "expected_batter/custom_batter/statcast_search_batter", "warning": "empty_or_unparsed_data"})
    if any(pitcher_pages) and not pitcher_rows:
        warnings.append({"page": "expected_pitcher/custom_pitcher/statcast_search_pitcher", "warning": "empty_or_unparsed_data"})
    if pages.get("park_factors") and not park_rows:
        warnings.append({"page": "park_factors", "warning": "empty_or_unparsed_data"})
    return warnings


def _write_json(path: Path, rows: list[dict[str, Any]], *, run_id: str) -> str:
    path.write_text(json.dumps({"run_id": run_id, "row_count": len(rows), "rows": rows}, indent=2), encoding="utf-8")
    return str(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")
    return str(path)


def _value(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return ""


def _player_name(value: str) -> str:
    if "," not in value:
        return value
    last, first = [part.strip() for part in value.split(",", 1)]
    return f"{first} {last}".strip()


def _weighted_extra_base_factor(row: dict[str, Any]) -> float:
    doubles = _factor(_value(row, "index_2b"))
    triples = _factor(_value(row, "index_3b"))
    return round((0.75 * doubles) + (0.25 * triples), 6)


def _factor(value: Any) -> float:
    parsed = _number(value)
    if parsed > 10.0:
        parsed = parsed / 100.0
    if parsed == 0.0:
        parsed = 1.0
    return round(max(0.5, min(1.5, parsed)), 6)


def _float_or_blank(value: Any) -> float | str:
    text = _clean(value)
    if not text:
        return ""
    return _number(text)


def _number(value: Any) -> float:
    try:
        return float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _flags(*values: str) -> tuple[str, ...]:
    return tuple(value for value in values if value)

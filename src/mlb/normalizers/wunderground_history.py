"""Normalize Weather Underground historical observations into MLB environment rows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.fetchers.historical_backfill.wunderground_history import SOURCE
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

CONTEXT_TIMING = "historical_observed_weather_backfill"
WEATHER_CONTENT_TIMING = "observed_game_time_weather"


def normalize_wunderground_history_weather(payload: dict[str, Any], *, snapshot_id: str = "") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    data = payload.get("data", [])
    if not isinstance(data, list):
        data = []

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        row = _environment_row(item, snapshot_id=snapshot_id, game_index=index)
        if row:
            rows.append(row)
        else:
            context = item.get("game_context", {}) if isinstance(item.get("game_context"), dict) else {}
            warnings.append(
                {
                    "warning": "missing_wunderground_observation",
                    "game_pk": context.get("game_pk"),
                    "official_date": context.get("official_date"),
                    "home_team_name": context.get("home_team_name"),
                    "error": item.get("error", ""),
                }
            )

    return {
        "snapshot_id": snapshot_id,
        "source": SOURCE,
        "context_timing": CONTEXT_TIMING,
        "weather_content_timing": WEATHER_CONTENT_TIMING,
        "game_dates": sorted({row["game_date"] for row in rows if row.get("game_date")}),
        "environment": rows,
        "parse_warnings": warnings,
    }


def write_wunderground_history_weather_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or SOURCE)
    normalized = normalize_wunderground_history_weather(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or resolved_run_id),
    )

    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / SOURCE / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    environment_path = output_dir / "environment.jsonl"
    environment_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in normalized["environment"])
        + ("\n" if normalized["environment"] else ""),
        encoding="utf-8",
    )
    out = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": SOURCE,
        "context_timing": CONTEXT_TIMING,
        "weather_content_timing": WEATHER_CONTENT_TIMING,
        "game_date": normalized["game_dates"][0] if len(normalized["game_dates"]) == 1 else "",
        "game_dates": normalized["game_dates"],
        "output_dir": str(output_dir),
        "row_counts": {"environment": len(normalized["environment"])},
        "artifacts": {"environment": str(environment_path)},
        "parse_warnings": normalized["parse_warnings"],
        "raw_snapshot_path": str(snapshot_path),
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _environment_row(item: dict[str, Any], *, snapshot_id: str, game_index: int) -> dict[str, Any] | None:
    context = item.get("game_context", {}) if isinstance(item.get("game_context"), dict) else {}
    payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
    observations = payload.get("observations", [])
    if not isinstance(observations, list) or not observations:
        return None

    game_time = _parse_datetime(context.get("game_date"))
    observation = _nearest_observation(observations, game_time=game_time)
    if not observation:
        return None

    away = canonical_team_abbr(context.get("away_team_abbr") or context.get("away_team_name"))
    home = canonical_team_abbr(context.get("home_team_abbr") or context.get("home_team_name"))
    if not (away and home):
        return None

    temp_f = _float(observation.get("temp"))
    wind_speed = _float(observation.get("wspd"))
    wind_direction = str(observation.get("wdir_cardinal") or "").upper()
    condition = str(observation.get("wx_phrase") or "").strip()
    weather_text = _weather_text(
        temp_f=temp_f,
        wind_speed=wind_speed,
        wind_direction=wind_direction,
        condition=condition,
    )
    flags = ["historical_observed_weather_backfill"]
    if temp_f is None:
        flags.append("wunderground_temp_missing")
    if wind_speed is None:
        flags.append("wunderground_wind_missing")
    if not wind_direction:
        flags.append("wunderground_wind_direction_missing")

    station = item.get("station", {}) if isinstance(item.get("station"), dict) else {}
    return {
        "source": SOURCE,
        "snapshot_id": snapshot_id,
        "context_timing": CONTEXT_TIMING,
        "weather_content_timing": WEATHER_CONTENT_TIMING,
        "game_date": str(context.get("official_date") or "")[:10],
        "game_index": game_index,
        "game_id": str(context.get("game_pk") or ""),
        "away_team_abbr": away,
        "home_team_abbr": home,
        "away_team_name": str(context.get("away_team_name") or ""),
        "home_team_name": str(context.get("home_team_name") or ""),
        "venue_name": str(context.get("venue_name") or ""),
        "park_name": str(context.get("venue_name") or ""),
        "game_time_utc": str(context.get("game_date") or ""),
        "weather_text": weather_text,
        "condition": condition,
        "temperature_f": temp_f if temp_f is not None else "",
        "humidity_pct": _float(observation.get("rh")) if _float(observation.get("rh")) is not None else "",
        "precipitation_in": _float(observation.get("precip_total")) if _float(observation.get("precip_total")) is not None else "",
        "precipitation_hourly_in": _float(observation.get("precip_hrly")) if _float(observation.get("precip_hrly")) is not None else "",
        "wind_speed_mph": wind_speed if wind_speed is not None else "",
        "wind_direction": wind_direction,
        "wind_direction_degrees": _float(observation.get("wdir")) if _float(observation.get("wdir")) is not None else "",
        "wind_gust_mph": _float(observation.get("gust")) if _float(observation.get("gust")) is not None else "",
        "dew_point_f": _float(observation.get("dewPt")) if _float(observation.get("dewPt")) is not None else "",
        "pressure_in": _float(observation.get("pressure")) if _float(observation.get("pressure")) is not None else "",
        "visibility_mi": _float(observation.get("vis")) if _float(observation.get("vis")) is not None else "",
        "observation_time_utc": _obs_time(observation),
        "station_id": str(station.get("station_id") or observation.get("obs_id") or ""),
        "station_name": str(observation.get("obs_name") or ""),
        "station_location_id": str(station.get("location_id") or ""),
        "umpire_text": "",
        "total_runs": "",
        "flags": tuple(flags),
    }


def _nearest_observation(observations: list[Any], *, game_time: datetime | None) -> dict[str, Any] | None:
    rows = [row for row in observations if isinstance(row, dict)]
    if not rows:
        return None
    if game_time is None:
        return rows[len(rows) // 2]

    def distance(row: dict[str, Any]) -> float:
        observed = _observation_datetime(row)
        if observed is None:
            return float("inf")
        return abs((observed - game_time).total_seconds())

    selected = min(rows, key=distance)
    return selected if distance(selected) != float("inf") else rows[len(rows) // 2]


def _observation_datetime(row: dict[str, Any]) -> datetime | None:
    value = row.get("valid_time_gmt")
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _obs_time(row: dict[str, Any]) -> str:
    observed = _observation_datetime(row)
    return observed.isoformat().replace("+00:00", "Z") if observed else ""


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _weather_text(*, temp_f: float | None, wind_speed: float | None, wind_direction: str, condition: str) -> str:
    parts = []
    if condition:
        parts.append(condition)
    if temp_f is not None:
        parts.append(f"{temp_f:g}\u00b0")
    if wind_speed is not None:
        wind = f"Wind {wind_speed:g} mph"
        if wind_direction:
            wind = f"{wind} {wind_direction}"
        parts.append(wind)
    return "Weather: " + " ".join(parts) if parts else ""


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

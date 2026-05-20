"""Normalize captured Covers MLB weather pages into environment context rows."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs


_DATE_HEADER_RE = re.compile(
    r'<div class="col-xs-12 covers-CoversWeather-dateHeader">(?P<date>.*?)</div>',
    re.S,
)
_BRICK_RE = re.compile(
    r'<div class="col-md-6 col-xs-12 covers-CoversWeather-brick">(?P<body>.*?)(?='
    r'<div class="col-md-6 col-xs-12 covers-CoversWeather-brick"|'
    r'<div class="col-xs-12 covers-CoversWeather-dateHeader"|'
    r"</article>|$)",
    re.S,
)


def normalize_covers_mlb_weather_html(text: str, *, snapshot_id: str = "") -> dict[str, Any]:
    """Parse a captured Covers MLB weather HTML page.

    The output intentionally mirrors the Rotowire/ESPN ``environment.jsonl``
    shape so the matchup matrix can consume it without model-side changes.
    """

    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    date_matches = list(_DATE_HEADER_RE.finditer(text))
    if not date_matches:
        return {
            "snapshot_id": snapshot_id,
            "source": "covers_mlb_weather",
            "game_dates": [],
            "environment": rows,
            "parse_warnings": [{"warning": "missing_date_headers"}],
        }

    for index, date_match in enumerate(date_matches):
        game_date = _parse_date(_strip_tags(date_match.group("date")))
        if not game_date:
            warnings.append({"warning": "unparseable_date_header", "value": _strip_tags(date_match.group("date"))})
            continue
        segment_end = date_matches[index + 1].start() if index + 1 < len(date_matches) else len(text)
        segment = text[date_match.end() : segment_end]
        for game_index, brick in enumerate(_BRICK_RE.finditer(segment), start=1):
            row = _environment_row(
                brick.group("body"),
                snapshot_id=snapshot_id,
                game_date=game_date,
                game_index=game_index,
            )
            if row:
                rows.append(row)
            else:
                warnings.append({"warning": "unparseable_weather_brick", "game_date": game_date, "game_index": game_index})

    return {
        "snapshot_id": snapshot_id,
        "source": "covers_mlb_weather",
        "game_dates": sorted({row["game_date"] for row in rows}),
        "environment": rows,
        "parse_warnings": warnings,
    }


def write_covers_mlb_weather_normalization(
    source_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Stage a captured Covers MLB weather file under ``data/mlb/staged``."""

    resolved_run_id = run_id or source_path.stem
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    normalized = normalize_covers_mlb_weather_html(text, snapshot_id=resolved_run_id)
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "covers_weather" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    environment_path = output_dir / "environment.jsonl"
    environment_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in normalized["environment"])
        + ("\n" if normalized["environment"] else ""),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": "covers_mlb_weather",
        "source_path": str(source_path),
        "game_dates": normalized["game_dates"],
        "game_date": normalized["game_dates"][0] if len(normalized["game_dates"]) == 1 else "",
        "output_dir": str(output_dir),
        "row_counts": {"environment": len(normalized["environment"])},
        "artifacts": {"environment": str(environment_path)},
        "parse_warnings": normalized["parse_warnings"],
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _environment_row(body: str, *, snapshot_id: str, game_date: str, game_index: int) -> dict[str, Any] | None:
    away_name = _attr_for_class(body, "covers-CoversWeather-teamLogoLeft", "alt")
    home_name = _attr_for_class(body, "covers-CoversWeather-teamLogoRight", "alt")
    away_abbr, home_abbr = _mobile_abbreviations(body)
    away = canonical_team_abbr(away_abbr or away_name)
    home = canonical_team_abbr(home_abbr or home_name)
    if not (away and home):
        return None

    park_name = _strip_tags(_first_match(body, r'<div class="covers-coversweatherPage-fieldName">(?P<value>.*?)</div>'))
    wind_speed = _float(_first_match(body, r"Wind:\s*(?P<value>\d+(?:\.\d+)?)\s*mph"))
    wind_direction = _wind_direction(body)
    temp_f = _float(_first_match(body, r"<span>\s*(?P<value>\d+(?:\.\d+)?)\s*°F\s*</span>"))
    humidity = _float(_first_match(body, r"Humidity:\s*(?P<value>\d+(?:\.\d+)?)\s*%"))
    pop = _float(_first_match(body, r"P\.O\.P\.:\s*(?P<value>\d+(?:\.\d+)?)\s*%"))
    condition = _condition(body)
    total_runs = _strip_tags(
        _first_match(body, r'<span class="covers-coversweather-line">\s*(?P<value>O/U:?\s*(?:Off|\d+(?:\.\d+)?))\s*</span>')
    )
    game_time_et = _strip_tags(_first_match(body, r'<span class="covers-CoversWeatherPage-time">(?P<value>.*?)</span>'))
    matchup_id = _first_match(body, r"/sport/baseball/mlb/matchup/(?P<value>\d+)")

    weather_text = _weather_text(temp_f=temp_f, wind_speed=wind_speed, wind_direction=wind_direction, condition=condition)
    flags = []
    if temp_f is None:
        flags.append("covers_weather_temp_missing")
    if wind_speed is None:
        flags.append("covers_weather_wind_missing")
    if not wind_direction:
        flags.append("covers_weather_wind_direction_missing")
    return {
        "source": "covers_mlb_weather",
        "snapshot_id": snapshot_id,
        "game_date": game_date,
        "game_index": game_index,
        "game_id": matchup_id,
        "away_team_abbr": away,
        "home_team_abbr": home,
        "away_team_name": _strip_tags(away_name),
        "home_team_name": _strip_tags(home_name),
        "venue_name": park_name,
        "park_name": park_name,
        "game_time_et": game_time_et,
        "weather_text": weather_text,
        "condition": condition,
        "temperature_f": temp_f if temp_f is not None else "",
        "humidity_pct": humidity if humidity is not None else "",
        "precipitation_probability_pct": pop if pop is not None else "",
        "wind_speed_mph": wind_speed if wind_speed is not None else "",
        "wind_direction": wind_direction,
        "umpire_text": "",
        "total_runs": total_runs,
        "covers_matchup_id": matchup_id,
        "flags": tuple(flags),
    }


def _mobile_abbreviations(body: str) -> tuple[str, str]:
    match = re.search(
        r'<span class="covers-CoversWeather-TeamsMobile">\s*'
        r"(?P<away>[A-Z. ]+?)\s*<span\b.*?</span>\s*@\s*"
        r"(?P<home>[A-Z. ]+?)\s*<span\b",
        body,
        flags=re.S,
    )
    if not match:
        return "", ""
    return _clean_team(match.group("away")), _clean_team(match.group("home"))


def _weather_text(*, temp_f: float | None, wind_speed: float | None, wind_direction: str, condition: str) -> str:
    parts = []
    if condition:
        parts.append(condition.replace("-", " "))
    if temp_f is not None:
        parts.append(f"{temp_f:g}\u00b0")
    if wind_speed is not None:
        wind = f"Wind {wind_speed:g} mph"
        if wind_direction:
            wind = f"{wind} {wind_direction}"
        parts.append(wind)
    return "Weather: " + " ".join(parts) if parts else ""


def _parse_date(value: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def _attr_for_class(body: str, class_name: str, attr_name: str) -> str:
    match = re.search(
        rf'<[^>]*class="[^"]*{re.escape(class_name)}[^"]*"[^>]*\s{re.escape(attr_name)}="(?P<value>[^"]*)"',
        body,
        flags=re.S,
    )
    return html.unescape(match.group("value")) if match else ""


def _wind_direction(body: str) -> str:
    match = re.search(r"wind_icons/(?P<value>[a-z-]+)\.png", body, flags=re.I)
    if match:
        return match.group("value").replace("-", "").upper()
    fallback = _first_match(body, r"imgSmFallback\\'>(?P<value>[A-Z-]+)</span>")
    return fallback.replace("-", "").upper()


def _condition(body: str) -> str:
    match = re.search(r"weather/dark_sky/(?P<value>[^./]+)\.png", body, flags=re.I)
    return match.group("value").lower() if match else ""


def _clean_team(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def _first_match(value: str, pattern: str) -> str:
    match = re.search(pattern, value, flags=re.S)
    return html.unescape(match.group("value")).strip() if match else ""


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

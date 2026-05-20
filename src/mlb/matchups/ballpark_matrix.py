"""Ballpark factor normalization for MLB environment context."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from mlb.matchups.schemas import BallparkProfile

RUN_KEYS = (
    "park_run_factor",
    "run_factor",
    "runs_factor",
    "runs",
    "r",
)
HR_KEYS = (
    "park_hr_factor",
    "hr_factor",
    "home_run_factor",
    "home_runs_factor",
    "home runs",
    "home_runs",
    "hr",
)
HIT_KEYS = (
    "park_hit_factor",
    "hit_factor",
    "hits_factor",
    "hits",
    "h",
)
EXTRA_BASE_KEYS = (
    "park_extra_base_factor",
    "extra_base_factor",
    "xbh_factor",
    "extra_base_hits",
)


def load_ballpark_profiles(path: Path, *, source: str | None = None) -> list[BallparkProfile]:
    """Load ballpark factors from Baseball Savant-style CSV or JSON exports."""

    if path.suffix.lower() == ".csv":
        rows = _load_csv_rows(path)
    else:
        rows = _load_json_rows(path)
    return build_ballpark_profiles(rows, source=source or path.name)


def build_ballpark_profiles(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str = "",
) -> list[BallparkProfile]:
    """Normalize park factor rows into model-safe 1.00-scale factors."""

    profiles: list[BallparkProfile] = []
    for row in rows:
        normalized = {_normalize_key(key): value for key, value in row.items()}
        park_id = _str(_first(normalized, "park_id", "venue_id", "stadium_id", "id"))
        park_name = _str(_first(normalized, "park_name", "venue_name", "stadium", "park", "ballpark", "name"))
        team = _str(_first(normalized, "team", "team_abbr", "home_team", "mlb_team"))
        run_factor, run_missing = _factor_from_keys(normalized, RUN_KEYS)
        hr_factor, hr_missing = _factor_from_keys(normalized, HR_KEYS)
        hit_factor, hit_missing = _factor_from_keys(normalized, HIT_KEYS)
        extra_base_factor, extra_base_missing = _extra_base_factor(normalized)
        flags = tuple(
            flag
            for flag, missing in (
                ("missing_park_identity", not (park_id or park_name)),
                ("missing_run_factor", run_missing),
                ("missing_hr_factor", hr_missing),
                ("missing_hit_factor", hit_missing),
                ("missing_extra_base_factor", extra_base_missing),
            )
            if missing
        )
        confidence = max(0.0, 1.0 - 0.2 * len(flags))
        context_score = _clamp(
            (run_factor - 1.0)
            + 0.45 * (hr_factor - 1.0)
            + 0.25 * (hit_factor - 1.0)
            + 0.20 * (extra_base_factor - 1.0),
            -0.40,
            0.40,
        )
        profiles.append(
            BallparkProfile(
                park_id=park_id,
                park_name=_title(park_name),
                team=team.upper(),
                park_run_factor=round(run_factor, 6),
                park_hr_factor=round(hr_factor, 6),
                park_hit_factor=round(hit_factor, 6),
                park_extra_base_factor=round(extra_base_factor, 6),
                park_context_score=round(context_score, 6),
                confidence=round(confidence, 6),
                source=source,
                flags=flags,
            )
        )
    return profiles


def ballpark_profiles_by_key(profiles: Iterable[BallparkProfile]) -> dict[str, BallparkProfile]:
    """Index profiles by park id, park name, and team abbreviation."""

    indexed: dict[str, BallparkProfile] = {}
    for profile in profiles:
        for key in (profile.park_id, profile.park_name, profile.team):
            normalized = _normalize_lookup_key(key)
            if normalized:
                indexed[normalized] = profile
    return indexed


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _load_json_rows(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, dict):
        if isinstance(payload.get("dataRows"), list):
            return [
                row.get("columns", row)
                for row in payload["dataRows"]
                if isinstance(row, Mapping)
            ]
        for key in ("rows", "data", "parks", "ballparks"):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, Mapping)]
    raise ValueError(f"Unsupported ballpark factor payload: {path}")


def _extra_base_factor(row: Mapping[str, Any]) -> tuple[float, bool]:
    direct, missing = _factor_from_keys(row, EXTRA_BASE_KEYS)
    if not missing:
        return direct, False
    doubles, doubles_missing = _factor_from_keys(row, ("2b_factor", "double_factor", "doubles_factor", "2b", "doubles"))
    triples, triples_missing = _factor_from_keys(row, ("3b_factor", "triple_factor", "triples_factor", "3b", "triples"))
    if not doubles_missing and not triples_missing:
        return (0.75 * doubles + 0.25 * triples), False
    if not doubles_missing:
        return doubles, False
    if not triples_missing:
        return triples, False
    return 1.0, True


def _factor_from_keys(row: Mapping[str, Any], keys: Iterable[str]) -> tuple[float, bool]:
    for key in keys:
        value = _first(row, _normalize_key(key))
        if value is None:
            continue
        parsed = _factor(value)
        if parsed is not None:
            return parsed, False
    return 1.0, True


def _factor(value: Any) -> float | None:
    parsed = _float(value)
    if parsed is None:
        return None
    if parsed > 10.0:
        parsed = parsed / 100.0
    return _clamp(parsed, 0.50, 1.50)


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_lookup_key(value: str) -> str:
    return _normalize_key(value).replace(".", "")


def _float(value: Any) -> float | None:
    try:
        return float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str:
    return str(value or "").strip()


def _title(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

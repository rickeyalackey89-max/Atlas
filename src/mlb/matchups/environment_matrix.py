"""Game environment matrix skeleton for MLB hitter props."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mlb.matchups.schemas import EnvironmentContext


def build_environment_context(rows: Iterable[Mapping[str, Any]]) -> list[EnvironmentContext]:
    """Build game/team environment context rows from staged source records."""

    contexts: list[EnvironmentContext] = []
    for row in rows:
        park_run_factor = _float(row.get("park_run_factor"), 1.0)
        park_hr_factor = _float(row.get("park_hr_factor"), 1.0)
        park_hit_factor = _float(row.get("park_hit_factor"), 1.0)
        park_extra_base_factor = _float(row.get("park_extra_base_factor"), 1.0)
        park_factor_confidence = _float(row.get("park_factor_confidence") or row.get("park_confidence"), 0.0)
        weather_run_score = _float(row.get("weather_run_score"), 0.0)
        wind_carry_score = _float(row.get("wind_carry_score"), 0.0)
        umpire_run_score = _float(row.get("umpire_run_score"), 0.0)
        environment_score = _clamp(
            (park_run_factor - 1.0)
            + 0.5 * (park_hr_factor - 1.0)
            + 0.25 * (park_hit_factor - 1.0)
            + 0.20 * (park_extra_base_factor - 1.0)
            + weather_run_score
            + wind_carry_score
            + umpire_run_score,
            -1.0,
            1.0,
        )
        flags = tuple(_flags(row, required=("game_id", "team", "opponent")))
        contexts.append(
            EnvironmentContext(
                game_id=_str(row.get("game_id")),
                game_date=_str(row.get("game_date")),
                team=_str(row.get("team")),
                opponent=_str(row.get("opponent")),
                park_id=_str(row.get("park_id")),
                park_run_factor=park_run_factor,
                park_hr_factor=park_hr_factor,
                park_hit_factor=park_hit_factor,
                park_extra_base_factor=park_extra_base_factor,
                park_factor_confidence=park_factor_confidence,
                weather_run_score=weather_run_score,
                wind_carry_score=wind_carry_score,
                home_plate_umpire=_str(row.get("home_plate_umpire") or row.get("umpire")),
                umpire_era=_float(row.get("umpire_era"), 0.0),
                umpire_rating=_str(row.get("umpire_rating")),
                umpire_run_score=round(umpire_run_score, 6),
                umpire_confidence=_float(row.get("umpire_confidence"), 0.0),
                environment_score=round(environment_score, 6),
                confidence=_optional_confidence(row.get("confidence"), flags=flags),
                flags=flags + _tuple_flags(row.get("flags")),
            )
        )
    return contexts


def _flags(row: Mapping[str, Any], *, required: tuple[str, ...]) -> list[str]:
    return [f"missing_{key}" for key in required if not _str(row.get(key))]


def _confidence(flags: tuple[str, ...]) -> float:
    return 0.0 if flags else 1.0


def _optional_confidence(value: Any, *, flags: tuple[str, ...]) -> float:
    if value in (None, ""):
        return _confidence(flags)
    return _clamp(_float(value, 0.0), 0.0, 1.0)


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return str(value or "").strip()


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

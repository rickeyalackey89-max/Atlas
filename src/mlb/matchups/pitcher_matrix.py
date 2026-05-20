"""Probable-starter matchup matrix skeleton for MLB hitter props."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mlb.matchups.schemas import PitcherContext


def build_pitcher_context(rows: Iterable[Mapping[str, Any]]) -> list[PitcherContext]:
    """Build hitter-team context against the opposing probable starter."""

    contexts: list[PitcherContext] = []
    for row in rows:
        strikeout_pressure_score = _clamp(_float(row.get("strikeout_pressure_score"), 0.0), -1.0, 1.0)
        contact_allow_score = _clamp(_float(row.get("contact_allow_score"), 0.0), -1.0, 1.0)
        power_allow_score = _clamp(_float(row.get("power_allow_score"), 0.0), -1.0, 1.0)
        walk_allow_score = _clamp(_float(row.get("walk_allow_score"), 0.0), -1.0, 1.0)
        starter_matchup_score = _clamp(
            -0.25 * strikeout_pressure_score
            + 0.25 * contact_allow_score
            + 0.25 * power_allow_score
            + 0.15 * walk_allow_score,
            -1.0,
            1.0,
        )
        flags = tuple(_flags(row, required=("game_id", "hitter_team", "opponent")))
        contexts.append(
            PitcherContext(
                game_id=_str(row.get("game_id")),
                hitter_team=_str(row.get("hitter_team") or row.get("team")),
                opponent=_str(row.get("opponent")),
                starter_pitcher_id=_str(row.get("starter_pitcher_id")),
                starter_pitcher_name=_str(row.get("starter_pitcher_name")),
                starter_hand=_str(row.get("starter_hand")).upper(),
                strikeout_pressure_score=strikeout_pressure_score,
                contact_allow_score=contact_allow_score,
                power_allow_score=power_allow_score,
                walk_allow_score=walk_allow_score,
                starter_matchup_score=round(starter_matchup_score, 6),
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

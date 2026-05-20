"""Bullpen matchup matrix skeleton for MLB hitter props."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mlb.matchups.schemas import BullpenContext


def build_bullpen_context(rows: Iterable[Mapping[str, Any]]) -> list[BullpenContext]:
    """Build hitter-team context against the opposing bullpen."""

    contexts: list[BullpenContext] = []
    for row in rows:
        fatigue_score = _clamp(_float(row.get("bullpen_fatigue_score"), 0.0), -1.0, 1.0)
        quality_score = _clamp(_float(row.get("bullpen_quality_score"), 0.0), -1.0, 1.0)
        late_game_run_score = _clamp(_float(row.get("late_game_run_score"), 0.0), -1.0, 1.0)
        handedness_balance_score = _clamp(_float(row.get("handedness_balance_score"), 0.0), -1.0, 1.0)
        bullpen_matchup_score = _clamp(
            0.25 * fatigue_score - 0.25 * quality_score + 0.30 * late_game_run_score + 0.10 * handedness_balance_score,
            -1.0,
            1.0,
        )
        flags = tuple(_flags(row, required=("game_id", "hitter_team", "opponent")))
        confidence = _optional_confidence(row.get("confidence"), flags=flags)
        contexts.append(
            BullpenContext(
                game_id=_str(row.get("game_id")),
                hitter_team=_str(row.get("hitter_team") or row.get("team")),
                opponent=_str(row.get("opponent")),
                bullpen_fatigue_score=fatigue_score,
                bullpen_quality_score=quality_score,
                late_game_run_score=late_game_run_score,
                handedness_balance_score=handedness_balance_score,
                bullpen_matchup_score=round(bullpen_matchup_score, 6),
                confidence=confidence,
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

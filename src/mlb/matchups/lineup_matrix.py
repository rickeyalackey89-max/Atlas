"""Lineup matrix skeleton for MLB hitter props."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mlb.matchups.schemas import LineupContext


def build_lineup_context(rows: Iterable[Mapping[str, Any]]) -> list[LineupContext]:
    """Build player-level lineup context from confirmed or projected lineups."""

    contexts: list[LineupContext] = []
    for row in rows:
        lineup_probability = _clamp(_float(row.get("lineup_probability"), 0.0), 0.0, 1.0)
        plate_appearances = _float(row.get("projected_plate_appearances"), 0.0)
        protection_score = _clamp(_float(row.get("protection_score"), 0.0), -1.0, 1.0)
        run_context_score = _clamp(_float(row.get("run_context_score"), 0.0), -1.0, 1.0)
        rbi_context_score = _clamp(_float(row.get("rbi_context_score"), 0.0), -1.0, 1.0)
        pinch_hit_risk = _clamp(_float(row.get("pinch_hit_risk"), 0.0), 0.0, 1.0)
        lineup_score = _lineup_score(
            lineup_probability=lineup_probability,
            plate_appearances=plate_appearances,
            protection_score=protection_score,
            run_context_score=run_context_score,
            rbi_context_score=rbi_context_score,
            pinch_hit_risk=pinch_hit_risk,
        )
        flags = tuple(_flags(row, required=("game_id", "player_id", "team", "opponent")))
        contexts.append(
            LineupContext(
                game_id=_str(row.get("game_id")),
                player_id=_str(row.get("player_id")),
                player_name=_str(row.get("player_name")),
                team=_str(row.get("team")),
                opponent=_str(row.get("opponent")),
                batting_order_slot=_optional_int(row.get("batting_order_slot")),
                lineup_probability=lineup_probability,
                projected_plate_appearances=round(plate_appearances, 4),
                protection_score=protection_score,
                run_context_score=run_context_score,
                rbi_context_score=rbi_context_score,
                pinch_hit_risk=pinch_hit_risk,
                lineup_score=round(lineup_score, 6),
                confidence=_confidence(flags, lineup_probability=lineup_probability),
                flags=flags,
            )
        )
    return contexts


def _lineup_score(
    *,
    lineup_probability: float,
    plate_appearances: float,
    protection_score: float,
    run_context_score: float,
    rbi_context_score: float,
    pinch_hit_risk: float,
) -> float:
    return _clamp(
        0.35 * (lineup_probability - 0.5)
        + 0.12 * (plate_appearances - 4.0)
        + 0.18 * protection_score
        + 0.12 * run_context_score
        + 0.12 * rbi_context_score
        - 0.25 * pinch_hit_risk,
        -1.0,
        1.0,
    )


def _flags(row: Mapping[str, Any], *, required: tuple[str, ...]) -> list[str]:
    return [f"missing_{key}" for key in required if not _str(row.get(key))]


def _confidence(flags: tuple[str, ...], *, lineup_probability: float) -> float:
    if flags:
        return 0.0
    return round(max(0.0, min(1.0, lineup_probability)), 6)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return str(value or "").strip()


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


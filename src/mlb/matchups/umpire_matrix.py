"""Home-plate umpire profile matrix for MLB run environment context."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from mlb.matchups.schemas import UmpireProfile

RATING_SCORES = {
    "EXTREME PITCHERS": -0.10,
    "PITCHERS": -0.05,
    "NEUTRAL": 0.0,
    "HITTERS": 0.05,
    "EXTREME HITTERS": 0.10,
}


def load_umpire_profiles(path: Path, *, source: str | None = None) -> list[UmpireProfile]:
    """Load umpire profile rows from a captured JSON table payload."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload_source = source or str(path)
    raw_rows = payload.get("rows")
    if isinstance(raw_rows, list):
        rows = [row for row in raw_rows if isinstance(row, Mapping)]
        if rows and _looks_like_umpscorecards_rows(rows):
            return build_umpire_profiles_from_scorecards(rows, source=payload_source)
        if rows and _looks_like_profile_rows(rows):
            return _load_existing_profile_rows(rows, source=payload_source)
        return build_umpire_profiles(rows, source=payload_source)

    rows = []
    for item in payload.get("dataRows", []):
        if isinstance(item, Mapping):
            columns = item.get("columns")
            if isinstance(columns, Mapping):
                rows.append(columns)
    return build_umpire_profiles(rows, source=payload_source)


def build_umpire_profiles(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str = "",
) -> list[UmpireProfile]:
    """Normalize umpire ERA/rating rows into bounded environment scores.

    The score is deliberately small. It is context for the probability engine,
    not a standalone projection. Positive values favor hitter/run environment;
    negative values favor pitchers/strikeout environment.
    """

    parsed_rows = list(rows)
    era_values = [_float(row.get("ERA"), None) for row in parsed_rows]
    valid_eras = [value for value in era_values if value is not None]
    era_mean = sum(valid_eras) / len(valid_eras) if valid_eras else 4.05
    era_span = max((max(valid_eras) - min(valid_eras)) / 2, 0.01) if valid_eras else 0.12

    profiles: list[UmpireProfile] = []
    for row in parsed_rows:
        umpire = _clean_name(row.get("Umpire"))
        era = _float(row.get("ERA"), 0.0) or 0.0
        rating = _clean_rating(row.get("Rating"))
        flags = tuple(_flags(umpire=umpire, era=era, rating=rating))
        rating_score = RATING_SCORES.get(rating, 0.0)
        era_score = _clamp(((era - era_mean) / era_span) * 0.06, -0.06, 0.06) if era else 0.0
        umpire_run_score = _clamp((0.70 * rating_score) + (0.30 * era_score), -0.12, 0.12)
        profiles.append(
            UmpireProfile(
                umpire=umpire,
                era=round(era, 3),
                rating=rating.title(),
                rating_score=round(rating_score, 6),
                era_score=round(era_score, 6),
                umpire_run_score=round(umpire_run_score, 6),
                confidence=_confidence(flags),
                source=source,
                flags=flags,
            )
        )
    return profiles


def build_umpire_profiles_from_scorecards(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str = "",
) -> list[UmpireProfile]:
    """Aggregate UmpScorecards game rows into per-umpire environment profiles.

    UmpScorecards is game-level data. The model needs a stable umpire profile,
    so this rolls each umpire's called-pitch sample into a small directional
    run-context score. Positive scores favor hitters/runs; negative scores
    favor pitchers/strikeouts.
    """

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if not _scorecard_row_is_usable(row):
            continue
        umpire = _clean_name(row.get("umpire"))
        if umpire:
            grouped[umpire].append(row)

    profiles: list[UmpireProfile] = []
    for umpire in sorted(grouped):
        umpire_rows = grouped[umpire]
        called_pitches = sum(max(_float(row.get("called_pitches"), 0.0) or 0.0, 1.0) for row in umpire_rows)
        game_count = len(umpire_rows)
        batter_impact = _weighted_average(
            (
                (
                    (_float(row.get("home_batter_impact"), 0.0) or 0.0)
                    + (_float(row.get("away_batter_impact"), 0.0) or 0.0)
                ),
                max(_float(row.get("called_pitches"), 0.0) or 0.0, 1.0),
            )
            for row in umpire_rows
        )
        total_run_impact = _weighted_average(
            (
                _float(row.get("total_run_impact"), 0.0) or 0.0,
                max(_float(row.get("called_pitches"), 0.0) or 0.0, 1.0),
            )
            for row in umpire_rows
        )
        accuracy_above_x = _weighted_average(
            (
                _float(row.get("accuracy_above_x"), 0.0) or 0.0,
                max(_float(row.get("called_pitches"), 0.0) or 0.0, 1.0),
            )
            for row in umpire_rows
        )
        valid_count = sum(1 for row in umpire_rows if row.get("fully_valid") is True)
        data_quality = valid_count / game_count if game_count else 0.0

        # Scorecard impact is measured in game run impact units. Dividing by 8
        # keeps this as a bounded context signal, not a primary projection.
        rating_score = _clamp(((0.70 * batter_impact) + (0.30 * total_run_impact)) / 8.0, -0.12, 0.12)
        rating = _rating_from_score(rating_score)
        flags = tuple(_scorecard_flags(game_count=game_count, data_quality=data_quality))
        profiles.append(
            UmpireProfile(
                umpire=umpire,
                era=0.0,
                rating=rating.title(),
                rating_score=round(rating_score, 6),
                era_score=round(_clamp(accuracy_above_x / 100.0, -0.03, 0.03), 6),
                umpire_run_score=round(rating_score, 6),
                confidence=_scorecard_confidence(
                    games=game_count,
                    called_pitches=called_pitches,
                    data_quality=data_quality,
                ),
                source=source,
                flags=flags,
            )
        )
    return profiles


def umpire_profiles_by_name(profiles: Iterable[UmpireProfile]) -> dict[str, UmpireProfile]:
    return {_key(profile.umpire): profile for profile in profiles if profile.umpire}


def _load_existing_profile_rows(rows: Iterable[Mapping[str, Any]], *, source: str) -> list[UmpireProfile]:
    profiles: list[UmpireProfile] = []
    for row in rows:
        profiles.append(
            UmpireProfile(
                umpire=_clean_name(row.get("umpire")),
                era=_float(row.get("era"), 0.0) or 0.0,
                rating=str(row.get("rating") or ""),
                rating_score=_float(row.get("rating_score"), 0.0) or 0.0,
                era_score=_float(row.get("era_score"), 0.0) or 0.0,
                umpire_run_score=_float(row.get("umpire_run_score"), 0.0) or 0.0,
                confidence=_float(row.get("confidence"), 0.0) or 0.0,
                source=str(row.get("source") or source),
                flags=tuple(row.get("flags") or ()),
            )
        )
    return profiles


def _flags(*, umpire: str, era: float, rating: str) -> list[str]:
    flags: list[str] = []
    if not umpire:
        flags.append("missing_umpire")
    if not era:
        flags.append("missing_umpire_era")
    if not rating:
        flags.append("missing_umpire_rating")
    elif rating not in RATING_SCORES:
        flags.append("unknown_umpire_rating")
    return flags


def _scorecard_flags(*, game_count: int, data_quality: float) -> list[str]:
    flags: list[str] = ["umpscorecards_profile", "umpire_era_unavailable"]
    if game_count < 5:
        flags.append("thin_umpire_scorecard_sample")
    if data_quality < 0.9:
        flags.append("umpire_scorecard_data_quality_warning")
    return flags


def _confidence(flags: tuple[str, ...]) -> float:
    if not flags:
        return 1.0
    if flags == ("unknown_umpire_rating",):
        return 0.5
    return 0.0


def _scorecard_confidence(*, games: int, called_pitches: float, data_quality: float) -> float:
    sample_confidence = _clamp(games / 10.0, 0.0, 1.0)
    pitch_confidence = _clamp(called_pitches / 1400.0, 0.0, 1.0)
    confidence = (0.55 * sample_confidence) + (0.35 * pitch_confidence) + (0.10 * data_quality)
    return round(_clamp(confidence, 0.0, 1.0), 6)


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").strip().title().split())


def _clean_rating(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _rating_from_score(score: float) -> str:
    if score <= -0.075:
        return "Extreme Pitchers"
    if score <= -0.025:
        return "Pitchers"
    if score < 0.025:
        return "Neutral"
    if score < 0.075:
        return "Hitters"
    return "Extreme Hitters"


def _float(value: Any, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _weighted_average(values: Iterable[tuple[float, float]]) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for value, weight in values:
        if weight <= 0:
            continue
        weighted_sum += value * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return weighted_sum / total_weight


def _looks_like_umpscorecards_rows(rows: Iterable[Mapping[str, Any]]) -> bool:
    sample = next(iter(rows), {})
    return "called_pitches" in sample and "home_batter_impact" in sample and "away_batter_impact" in sample


def _looks_like_profile_rows(rows: Iterable[Mapping[str, Any]]) -> bool:
    sample = next(iter(rows), {})
    return "umpire" in sample and "umpire_run_score" in sample


def _scorecard_row_is_usable(row: Mapping[str, Any]) -> bool:
    if row.get("failed") is True:
        return False
    if row.get("has_basic_game_data") is False and row.get("has_detailed_game_data") is False:
        return False
    if (_float(row.get("called_pitches"), 0.0) or 0.0) <= 0:
        return False
    return bool(_clean_name(row.get("umpire")))


def _key(value: str) -> str:
    return " ".join(value.casefold().split())


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

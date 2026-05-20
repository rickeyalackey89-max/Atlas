"""Pitcher-prop context matrix for MLB pitcher markets.

This module intentionally stays separate from the hitter matchup matrix. Pitcher props
need their own context because the direction of the matchup is different: a weak
starter helps hitter overs, but it can hurt pitcher strikeout and workload overs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.matchups.schemas import MATCHUP_MATRIX_VERSION, PitcherPropContext

STRIKEOUT_MARKETS = {"pitcher_strikeouts", "pitcher_strikeouts_combo"}
WORKLOAD_MARKETS = {"pitching_outs", "pitches_thrown"}
RUN_ALLOW_MARKETS = {"hits_allowed", "earned_runs", "earned_runs_allowed", "pitcher_fantasy_score", "first_inning_runs_allowed"}
WALK_MARKETS = {"walks_allowed", "first_inning_walks_allowed"}
PITCHER_PROP_MARKETS = STRIKEOUT_MARKETS | WORKLOAD_MARKETS | RUN_ALLOW_MARKETS | WALK_MARKETS


def build_pitcher_prop_context(
    prop_rows: Iterable[Mapping[str, Any]],
    *,
    pitcher_rows: Iterable[Mapping[str, Any]] = (),
    bullpen_rows: Iterable[Mapping[str, Any]] = (),
    environment_rows: Iterable[Mapping[str, Any]] = (),
    lineup_rows: Iterable[Mapping[str, Any]] = (),
    player_history_rows: Iterable[Mapping[str, Any]] = (),
    advanced_profile_rows: Iterable[Mapping[str, Any]] = (),
    run_id: str = "",
) -> list[PitcherPropContext]:
    """Build source-aware context rows for pitcher props.

    This v1 layer is still source-safe for replay, but it is no longer starter-only.
    It combines the probable starter, opponent lineup shape, opponent hitter profiles,
    pitcher recent history, bullpen support, environment, and umpire context.
    """

    history_index = _player_history_index(player_history_rows)
    profile_index = _advanced_profile_index(advanced_profile_rows)
    opponent_lineups = _opponent_lineup_index(
        lineup_rows,
        history_index=history_index,
        profile_index=profile_index,
    )
    pitcher_histories = _pitcher_history_index(player_history_rows)
    pitchers = _pitcher_index(pitcher_rows)
    bullpens = _bullpen_index(bullpen_rows)
    environments = _environment_index(environment_rows)
    contexts: list[PitcherPropContext] = []
    for row in prop_rows:
        market = _str(row.get("market"))
        if market not in PITCHER_PROP_MARKETS:
            continue
        team = _team(row.get("player_team") or row.get("team"))
        opponent = _team(row.get("opponent") or row.get("opp"))
        game_date = _str(row.get("game_date"))
        pitcher_name = _str(row.get("player_name"))
        pitcher = _lookup_pitcher(pitchers, game_date=game_date, team=team, opponent=opponent, pitcher_name=pitcher_name)
        environment = environments.get(_context_key(game_date, team, opponent), {})
        bullpen = bullpens.get(team, {})
        opponent_lineup = opponent_lineups.get(_context_key(game_date, team, opponent), {})
        pitcher_history = _lookup_pitcher_history(pitcher_histories, row=row, game_date=game_date, team=team, pitcher_name=pitcher_name)
        scores = _scores_for_pitcher(
            pitcher,
            bullpen=bullpen,
            environment=environment,
            opponent_lineup=opponent_lineup,
            pitcher_history=pitcher_history,
        )
        flags = _missing_flags(
            pitcher=pitcher,
            environment=environment,
            opponent_lineup=opponent_lineup,
            pitcher_history=pitcher_history,
        )
        composite = _market_composite(market, scores)
        confidence = _confidence(
            pitcher=pitcher,
            environment=environment,
            opponent_lineup=opponent_lineup,
            pitcher_history=pitcher_history,
            flags=flags,
        )
        contexts.append(
            PitcherPropContext(
                run_id=run_id,
                source_projection_id=_str(row.get("source_projection_id")),
                game_id=_canonical_game_id(game_date, team, opponent),
                game_date=game_date,
                pitcher_id=_str(row.get("player_id")),
                pitcher_name=pitcher_name,
                team=team,
                opponent=opponent,
                market=market,
                line=_float(row.get("line"), 0.0),
                tier=_str(row.get("tier") or "STANDARD").upper(),
                direction=_str(row.get("direction") or "over").lower(),
                starter_pitcher_name=_str(pitcher.get("pitcher_name")),
                starter_hand=_str(pitcher.get("throws")).upper(),
                starter_era=round(_float(pitcher.get("starter_era"), 0.0), 3),
                starter_score=scores["starter_score"],
                strikeout_context_score=scores["strikeout_context_score"],
                workload_context_score=scores["workload_context_score"],
                run_allow_context_score=scores["run_allow_context_score"],
                walk_context_score=scores["walk_context_score"],
                opponent_lineup_score=scores["opponent_lineup_score"],
                opponent_k_context_score=scores["opponent_k_context_score"],
                opponent_contact_context_score=scores["opponent_contact_context_score"],
                opponent_power_context_score=scores["opponent_power_context_score"],
                opponent_walk_context_score=scores["opponent_walk_context_score"],
                opponent_projected_pa=scores["opponent_projected_pa"],
                opponent_top_order_pa=scores["opponent_top_order_pa"],
                opponent_confirmed_batters=int(scores["opponent_confirmed_batters"]),
                opponent_lineup_confidence=scores["opponent_lineup_confidence"],
                pitcher_history_k_score=scores["pitcher_history_k_score"],
                pitcher_history_hit_allow_score=scores["pitcher_history_hit_allow_score"],
                pitcher_history_walk_score=scores["pitcher_history_walk_score"],
                pitcher_history_confidence=scores["pitcher_history_confidence"],
                bullpen_support_score=scores["bullpen_support_score"],
                environment_score=scores["environment_score"],
                pitcher_prop_composite_score=composite,
                pitcher_prop_confidence=confidence,
                home_plate_umpire=_str(environment.get("home_plate_umpire")),
                umpire_era=_float(environment.get("umpire_era"), 0.0),
                umpire_rating=_str(environment.get("umpire_rating")),
                umpire_run_score=_float(environment.get("umpire_run_score"), 0.0),
                matchup_matrix_version=MATCHUP_MATRIX_VERSION,
                missing_context_flags=flags,
            )
        )
    return contexts


def _pitcher_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    fallback: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        game_date = _str(row.get("game_date"))
        team = _team(row.get("team_abbr") or row.get("pitching_team") or row.get("team"))
        opponent = _team(row.get("opponent_abbr") or row.get("pitching_opponent") or row.get("opponent"))
        pitcher_name = _str(row.get("pitcher_name") or row.get("starter_pitcher_name") or row.get("player_name"))
        if not (game_date and team and opponent):
            continue
        prepared = dict(row)
        prepared["starter_era"] = _first_float(row.get("starter_era"), _parse_era(row.get("pitcher_stats")))
        indexed[(game_date, team, opponent, _name_key(pitcher_name))] = prepared
        fallback[(game_date, team, opponent, "")] = prepared
    indexed.update({key: value for key, value in fallback.items() if key not in indexed})
    return indexed


def _bullpen_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        team = _team(row.get("team_abbr") or row.get("team"))
        if team:
            indexed[team] = dict(row)
    return indexed


def _environment_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        game_date = _str(row.get("game_date"))
        team = _team(row.get("team"))
        opponent = _team(row.get("opponent"))
        if game_date and team and opponent:
            indexed[(game_date, team, opponent)] = dict(row)
    return indexed


def _lookup_pitcher(
    pitchers: dict[tuple[str, str, str, str], dict[str, Any]],
    *,
    game_date: str,
    team: str,
    opponent: str,
    pitcher_name: str,
) -> dict[str, Any]:
    return pitchers.get((game_date, team, opponent, _name_key(pitcher_name))) or pitchers.get(
        (game_date, team, opponent, "")
    ) or {}


def _opponent_lineup_index(
    rows: Iterable[Mapping[str, Any]],
    *,
    history_index: dict[tuple[str, str, str], dict[str, Any]],
    profile_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, float]]:
    grouped: dict[tuple[str, str, str], list[dict[str, float]]] = {}
    for row in rows:
        game_date = _str(row.get("game_date")) or _game_date_from_game_id(row.get("game_id"))
        batting_team = _team(row.get("team") or row.get("team_abbr"))
        pitching_team = _team(row.get("opponent") or row.get("opponent_abbr"))
        player_name = _str(row.get("player_name") or row.get("display_name"))
        if not (game_date and batting_team and pitching_team and player_name):
            continue
        player_key = _name_key(player_name)
        compact_player_key = _compact_name_key(player_name)
        history = history_index.get((game_date, player_key, batting_team), {})
        profile = (
            profile_index.get((player_key, batting_team), {})
            or profile_index.get((compact_player_key, batting_team), {})
            or profile_index.get((player_key, ""), {})
            or profile_index.get((compact_player_key, ""), {})
        )
        slot = _optional_int(row.get("batting_order_slot") or row.get("batting_order"))
        projected_pa = _float(row.get("projected_plate_appearances"), 0.0) or _projected_pa(slot)
        lineup_probability = _clamp(_float(row.get("lineup_probability"), 0.72), 0.0, 1.0)
        profile_scores = _hitter_profile_scores(profile)
        history_scores = _hitter_history_scores(history)
        weight = max(projected_pa, 1.0) * lineup_probability
        if slot is not None and slot <= 4:
            weight *= 1.15
        elif slot is not None and slot >= 8:
            weight *= 0.88
        grouped.setdefault((game_date, pitching_team, batting_team), []).append(
            {
                "weight": weight,
                "projected_pa": projected_pa * lineup_probability,
                "top_order_pa": projected_pa * lineup_probability if slot is not None and slot <= 4 else 0.0,
                "confirmed_batter": 1.0 if lineup_probability >= 0.99 else 0.0,
                "profile_available": 1.0 if profile_scores["available"] else 0.0,
                "history_available": 1.0 if history_scores["available"] else 0.0,
                "k_score": _blend_signal(history_scores["k_score"], profile_scores["k_score"], history_scores["available"], profile_scores["available"]),
                "contact_score": _blend_signal(history_scores["contact_score"], profile_scores["contact_score"], history_scores["available"], profile_scores["available"]),
                "power_score": _blend_signal(history_scores["power_score"], profile_scores["power_score"], history_scores["available"], profile_scores["available"]),
                "walk_score": _blend_signal(history_scores["walk_score"], profile_scores["walk_score"], history_scores["available"], profile_scores["available"]),
            }
        )
    return {key: _aggregate_opponent_lineup(values) for key, values in grouped.items()}


def _aggregate_opponent_lineup(rows: list[dict[str, float]]) -> dict[str, float]:
    weight_sum = sum(row["weight"] for row in rows)
    if weight_sum <= 0.0:
        return {}
    k_score = _weighted_mean(rows, "k_score", weight_sum)
    contact_score = _weighted_mean(rows, "contact_score", weight_sum)
    power_score = _weighted_mean(rows, "power_score", weight_sum)
    walk_score = _weighted_mean(rows, "walk_score", weight_sum)
    lineup_score = _clamp(0.34 * contact_score + 0.30 * power_score + 0.22 * walk_score - 0.24 * k_score, -1.0, 1.0)
    confirmed = int(round(sum(row["confirmed_batter"] for row in rows)))
    profile_rate = sum(row["profile_available"] for row in rows) / max(len(rows), 1)
    history_rate = sum(row["history_available"] for row in rows) / max(len(rows), 1)
    confidence = _clamp(0.18 + 0.42 * min(confirmed, 9) / 9.0 + 0.24 * profile_rate + 0.16 * history_rate, 0.0, 0.92)
    return {
        "opponent_lineup_score": round(lineup_score, 6),
        "opponent_k_context_score": round(k_score, 6),
        "opponent_contact_context_score": round(contact_score, 6),
        "opponent_power_context_score": round(power_score, 6),
        "opponent_walk_context_score": round(walk_score, 6),
        "opponent_projected_pa": round(sum(row["projected_pa"] for row in rows), 4),
        "opponent_top_order_pa": round(sum(row["top_order_pa"] for row in rows), 4),
        "opponent_confirmed_batters": float(confirmed),
        "opponent_lineup_confidence": round(confidence, 6),
    }


def _weighted_mean(rows: list[dict[str, float]], key: str, weight_sum: float) -> float:
    return _clamp(sum(row[key] * row["weight"] for row in rows) / weight_sum, -1.0, 1.0)


def _player_history_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not _bool(row.get("player_history_context_available")):
            continue
        game_date = _str(row.get("game_date"))
        name = _name_key(row.get("player_name"))
        team = _team(row.get("player_team"))
        market = _str(row.get("market"))
        if not (game_date and name and team):
            continue
        if market in PITCHER_PROP_MARKETS:
            continue
        index.setdefault((game_date, name, team), dict(row))
    return index


def _pitcher_history_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[Any, dict[str, Any]]]:
    by_projection: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    by_name_team: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not _bool(row.get("player_history_context_available")):
            continue
        market = _str(row.get("market"))
        if market not in PITCHER_PROP_MARKETS:
            continue
        prepared = dict(row)
        by_projection[_matchup_key(row)] = prepared
        game_date = _str(row.get("game_date"))
        name = _name_key(row.get("player_name"))
        team = _team(row.get("player_team"))
        if game_date and name and team:
            by_name_team[(game_date, name, team)] = prepared
    return {"by_projection": by_projection, "by_name_team": by_name_team}


def _lookup_pitcher_history(
    index: dict[str, dict[Any, dict[str, Any]]],
    *,
    row: Mapping[str, Any],
    game_date: str,
    team: str,
    pitcher_name: str,
) -> dict[str, Any]:
    return index.get("by_projection", {}).get(_matchup_key(row)) or index.get("by_name_team", {}).get(
        (game_date, _name_key(pitcher_name), team),
        {},
    )


def _advanced_profile_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if _str(row.get("profile_role")).lower() not in {"hitter", "batter"}:
            continue
        name_keys = {
            _name_key(row.get("player_name")),
            _name_key(row.get("player_name_key")),
            _compact_name_key(row.get("player_name")),
            _compact_name_key(row.get("player_name_key")),
        }
        team = _team(row.get("player_team"))
        for name in {key for key in name_keys if key}:
            indexed[(name, team)] = dict(row)
            if team:
                indexed.setdefault((name, ""), dict(row))
    return indexed


def _hitter_history_scores(row: Mapping[str, Any]) -> dict[str, Any]:
    if not row:
        return _empty_signal_scores()
    return {
        "available": True,
        "k_score": _score_metric(row.get("history_strikeouts_per_pa_14d"), center=0.220, scale=0.100),
        "contact_score": _score_metric(row.get("history_hits_per_pa_14d"), center=0.235, scale=0.070),
        "power_score": _score_metric(row.get("history_total_bases_per_pa_14d"), center=0.390, scale=0.170),
        "walk_score": _score_metric(row.get("history_walks_per_pa_14d"), center=0.085, scale=0.060),
    }


def _hitter_profile_scores(row: Mapping[str, Any]) -> dict[str, Any]:
    if not row:
        return _empty_signal_scores()
    k_score = _clamp(_mean(
        (
            _score_metric(row.get("k_rate"), center=0.220, scale=0.100),
            _score_metric(row.get("whiff_rate"), center=0.240, scale=0.120),
            -0.35 * _score_metric(row.get("contact_rate"), center=0.760, scale=0.120),
        )
    ), -1.0, 1.0)
    contact_score = _clamp(_mean(
        (
            _score_metric(row.get("xba") or row.get("ba"), center=0.245, scale=0.060),
            _score_metric(row.get("xwoba") or row.get("woba"), center=0.320, scale=0.080),
            _score_metric(row.get("contact_rate"), center=0.760, scale=0.120),
        )
    ), -1.0, 1.0)
    power_score = _clamp(_mean(
        (
            _score_metric(row.get("xslg") or row.get("slg"), center=0.410, scale=0.150),
            _score_metric(row.get("barrel_rate"), center=0.075, scale=0.060),
            _score_metric(row.get("hard_hit_rate"), center=0.380, scale=0.150),
        )
    ), -1.0, 1.0)
    walk_score = _score_metric(row.get("bb_rate"), center=0.085, scale=0.060)
    return {
        "available": True,
        "k_score": round(k_score, 6),
        "contact_score": round(contact_score, 6),
        "power_score": round(power_score, 6),
        "walk_score": round(walk_score, 6),
    }


def _empty_signal_scores() -> dict[str, Any]:
    return {
        "available": False,
        "k_score": 0.0,
        "contact_score": 0.0,
        "power_score": 0.0,
        "walk_score": 0.0,
    }


def _pitcher_history_scores(row: Mapping[str, Any]) -> dict[str, float]:
    if not row:
        return {
            "pitcher_history_k_score": 0.0,
            "pitcher_history_hit_allow_score": 0.0,
            "pitcher_history_walk_score": 0.0,
            "pitcher_history_confidence": 0.0,
        }
    return {
        "pitcher_history_k_score": round(_score_metric(row.get("history_strikeouts_per_pa_14d"), center=0.220, scale=0.100), 6),
        "pitcher_history_hit_allow_score": round(_score_metric(row.get("history_hits_per_pa_14d"), center=0.235, scale=0.070), 6),
        "pitcher_history_walk_score": round(_score_metric(row.get("history_walks_per_pa_14d"), center=0.085, scale=0.060), 6),
        "pitcher_history_confidence": round(_clamp(_float(row.get("history_context_confidence"), 0.0), 0.0, 1.0), 6),
    }


def _blend_signal(history_score: float, profile_score: float, history_available: bool, profile_available: bool) -> float:
    if history_available and profile_available:
        return round(_clamp(0.55 * profile_score + 0.45 * history_score, -1.0, 1.0), 6)
    if profile_available:
        return round(_clamp(profile_score, -1.0, 1.0), 6)
    if history_available:
        return round(_clamp(history_score, -1.0, 1.0), 6)
    return 0.0


def _scores_for_pitcher(
    pitcher: Mapping[str, Any],
    *,
    bullpen: Mapping[str, Any],
    environment: Mapping[str, Any],
    opponent_lineup: Mapping[str, Any],
    pitcher_history: Mapping[str, Any],
) -> dict[str, float]:
    era = pitcher.get("starter_era")
    era_delta = _clamp((_float(era, 4.20) - 4.20) / 4.0, -0.45, 0.45) if era not in (None, "") else 0.0
    umpire_run_score = _float(environment.get("umpire_run_score"), 0.0)
    environment_score = _clamp(
        _float(environment.get("environment_score"), 0.0) + _float(environment.get("weather_run_score"), 0.0),
        -0.25,
        0.25,
    )
    bullpen_fatigue = _float(bullpen.get("bullpen_fatigue_score"), 0.0)
    lineup_score = _float(opponent_lineup.get("opponent_lineup_score"), 0.0)
    opponent_k = _float(opponent_lineup.get("opponent_k_context_score"), 0.0)
    opponent_contact = _float(opponent_lineup.get("opponent_contact_context_score"), 0.0)
    opponent_power = _float(opponent_lineup.get("opponent_power_context_score"), 0.0)
    opponent_walk = _float(opponent_lineup.get("opponent_walk_context_score"), 0.0)
    history = _pitcher_history_scores(pitcher_history)
    if _has_advanced_scores(pitcher):
        strikeout_pressure = _float(pitcher.get("strikeout_pressure_score"), 0.0)
        contact_allow = _float(pitcher.get("contact_allow_score"), 0.0)
        power_allow = _float(pitcher.get("power_allow_score"), 0.0)
        walk_allow = _float(pitcher.get("walk_allow_score"), 0.0)
        strikeout_pressure = _clamp(
            strikeout_pressure
            + 0.26 * history["pitcher_history_k_score"]
            + 0.46 * opponent_k
            - 0.18 * opponent_contact,
            -1.0,
            1.0,
        )
        contact_allow = _clamp(
            contact_allow
            + 0.24 * history["pitcher_history_hit_allow_score"]
            + 0.30 * opponent_contact,
            -1.0,
            1.0,
        )
        power_allow = _clamp(power_allow + 0.26 * opponent_power + 0.10 * lineup_score, -1.0, 1.0)
        walk_allow = _clamp(
            walk_allow
            + 0.26 * history["pitcher_history_walk_score"]
            + 0.38 * opponent_walk,
            -1.0,
            1.0,
        )
        run_allow = _clamp(
            0.40 * contact_allow + 0.35 * power_allow + 0.25 * walk_allow + environment_score + 0.35 * umpire_run_score,
            -1.0,
            1.0,
        )
        starter_score = _clamp(
            0.45 * strikeout_pressure - 0.25 * contact_allow - 0.25 * power_allow - 0.15 * walk_allow,
            -1.0,
            1.0,
        )
        return {
            "starter_score": round(starter_score, 6),
            "strikeout_context_score": round(_clamp(strikeout_pressure - 0.40 * umpire_run_score, -1.0, 1.0), 6),
            "workload_context_score": round(_clamp(0.55 * starter_score - 0.25 * run_allow + 0.22 * opponent_k - 0.14 * opponent_walk + 0.25 * bullpen_fatigue, -1.0, 1.0), 6),
            "run_allow_context_score": round(run_allow, 6),
            "walk_context_score": round(_clamp(walk_allow + 0.20 * umpire_run_score, -1.0, 1.0), 6),
            **_opponent_output_scores(opponent_lineup),
            **history,
            "bullpen_support_score": round(_clamp(bullpen_fatigue, -1.0, 1.0), 6),
            "environment_score": round(environment_score, 6),
        }
    starter_score = round(_clamp(-era_delta, -0.45, 0.45), 6)
    strikeout_score = _clamp(starter_score + 0.24 * history["pitcher_history_k_score"] + 0.42 * opponent_k - 0.16 * opponent_contact, -1.0, 1.0)
    run_allow_score = _clamp(
        era_delta
        + 0.25 * history["pitcher_history_hit_allow_score"]
        + 0.30 * opponent_contact
        + 0.26 * opponent_power
        + 0.18 * opponent_walk
        + environment_score
        + 0.35 * umpire_run_score,
        -1.0,
        1.0,
    )
    walk_score = _clamp(0.40 * era_delta + 0.24 * history["pitcher_history_walk_score"] + 0.38 * opponent_walk + 0.20 * umpire_run_score, -1.0, 1.0)
    return {
        "starter_score": starter_score,
        "strikeout_context_score": round(_clamp(strikeout_score - 0.40 * umpire_run_score, -1.0, 1.0), 6),
        "workload_context_score": round(_clamp(0.65 * starter_score - 0.22 * run_allow_score + 0.22 * opponent_k - 0.14 * opponent_walk + 0.25 * bullpen_fatigue, -1.0, 1.0), 6),
        "run_allow_context_score": round(run_allow_score, 6),
        "walk_context_score": round(walk_score, 6),
        **_opponent_output_scores(opponent_lineup),
        **history,
        "bullpen_support_score": round(_clamp(bullpen_fatigue, -1.0, 1.0), 6),
        "environment_score": round(environment_score, 6),
    }


def _market_composite(market: str, scores: Mapping[str, float]) -> float:
    if market in STRIKEOUT_MARKETS:
        value = 0.70 * scores["strikeout_context_score"] + 0.20 * scores["environment_score"]
    elif market in WORKLOAD_MARKETS:
        value = 0.70 * scores["workload_context_score"] - 0.15 * scores["run_allow_context_score"]
    elif market in RUN_ALLOW_MARKETS:
        value = 0.75 * scores["run_allow_context_score"] + 0.15 * scores["environment_score"]
    elif market in WALK_MARKETS:
        value = 0.80 * scores["walk_context_score"] + 0.10 * scores["environment_score"]
    else:
        value = 0.0
    return round(_clamp(value, -1.0, 1.0), 6)


def _opponent_output_scores(opponent_lineup: Mapping[str, Any]) -> dict[str, float]:
    return {
        "opponent_lineup_score": round(_float(opponent_lineup.get("opponent_lineup_score"), 0.0), 6),
        "opponent_k_context_score": round(_float(opponent_lineup.get("opponent_k_context_score"), 0.0), 6),
        "opponent_contact_context_score": round(_float(opponent_lineup.get("opponent_contact_context_score"), 0.0), 6),
        "opponent_power_context_score": round(_float(opponent_lineup.get("opponent_power_context_score"), 0.0), 6),
        "opponent_walk_context_score": round(_float(opponent_lineup.get("opponent_walk_context_score"), 0.0), 6),
        "opponent_projected_pa": round(_float(opponent_lineup.get("opponent_projected_pa"), 0.0), 4),
        "opponent_top_order_pa": round(_float(opponent_lineup.get("opponent_top_order_pa"), 0.0), 4),
        "opponent_confirmed_batters": round(_float(opponent_lineup.get("opponent_confirmed_batters"), 0.0), 0),
        "opponent_lineup_confidence": round(_float(opponent_lineup.get("opponent_lineup_confidence"), 0.0), 6),
    }


def _missing_flags(
    *,
    pitcher: Mapping[str, Any],
    environment: Mapping[str, Any],
    opponent_lineup: Mapping[str, Any],
    pitcher_history: Mapping[str, Any],
) -> tuple[str, ...]:
    flags: list[str] = []
    if not pitcher:
        flags.append("missing_pitcher_prop_context")
    elif _has_advanced_scores(pitcher):
        flags.append("advanced_pitcher_prop_context")
    elif pitcher.get("starter_era") in (None, ""):
        flags.append("pitcher_prop_era_missing")
    else:
        flags.append("pitcher_prop_era_only_context")
    if not environment:
        flags.append("missing_pitcher_prop_environment_context")
    if not opponent_lineup:
        flags.append("missing_pitcher_prop_opponent_lineup_context")
    else:
        flags.append("pitcher_prop_opponent_lineup_context")
    if not pitcher_history:
        flags.append("thin_pitcher_prop_history_context")
    else:
        flags.append("pitcher_prop_history_context")
    return tuple(flags)


def _confidence(
    *,
    pitcher: Mapping[str, Any],
    environment: Mapping[str, Any],
    opponent_lineup: Mapping[str, Any],
    pitcher_history: Mapping[str, Any],
    flags: tuple[str, ...],
) -> float:
    if not pitcher:
        return 0.0
    if "advanced_pitcher_prop_context" in flags:
        base = max(0.56, min(0.74, _float(pitcher.get("confidence"), 0.0)))
    else:
        base = 0.48 if "pitcher_prop_era_only_context" in flags else 0.32
    if environment:
        base += min(0.12, 0.12 * _float(environment.get("confidence"), 0.0))
    if opponent_lineup:
        base += min(0.16, 0.16 * _float(opponent_lineup.get("opponent_lineup_confidence"), 0.0))
    if pitcher_history:
        base += min(0.10, 0.10 * _float(pitcher_history.get("history_context_confidence"), 0.0))
    return round(_clamp(base, 0.0, 0.90), 6)


def _has_advanced_scores(pitcher: Mapping[str, Any]) -> bool:
    flags = _tuple_flags(pitcher.get("flags"))
    return "advanced_pitcher_profile_applied" in flags


def _parse_era(value: Any) -> float | None:
    text = _str(value).upper()
    parts = text.split(" ERA", 1)
    if len(parts) < 2:
        return None
    candidate = parts[0].split()[-1] if parts[0].split() else ""
    try:
        return float(candidate)
    except ValueError:
        return None


def _canonical_game_id(game_date: Any, team: Any, opponent: Any) -> str:
    return f"{_str(game_date)}|{_team(team)}|{_team(opponent)}"


def _game_date_from_game_id(value: Any) -> str:
    text = _str(value)
    if "|" not in text:
        return ""
    return text.split("|", 1)[0]


def _context_key(game_date: str, team: str, opponent: str) -> tuple[str, str, str]:
    return (game_date, team, opponent)


def _matchup_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _str(row.get("source_projection_id")),
        _str(row.get("market")),
        _line_key(row.get("line")),
        _str(row.get("tier") or "STANDARD").upper() or "STANDARD",
    )


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _name_key(value: Any) -> str:
    return " ".join(_str(value).casefold().replace(".", "").split())


def _compact_name_key(value: Any) -> str:
    return "".join(character for character in _name_key(value) if character.isalnum())


def _str(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return canonical_team_abbr(value)


def _first_float(*values: Any) -> float | str:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _projected_pa(slot: int | None) -> float:
    if slot is None:
        return 4.0
    return {
        1: 4.75,
        2: 4.65,
        3: 4.55,
        4: 4.45,
        5: 4.30,
        6: 4.15,
        7: 3.95,
        8: 3.80,
        9: 3.65,
    }.get(slot, 4.0)


def _score_metric(value: Any, *, center: float, scale: float) -> float:
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if metric > 1.5 and center <= 1.0:
        metric /= 100.0
    return _clamp((metric - center) / scale, -1.0, 1.0)


def _mean(values: tuple[float, ...]) -> float:
    collected = [float(value) for value in values]
    return sum(collected) / len(collected) if collected else 0.0


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

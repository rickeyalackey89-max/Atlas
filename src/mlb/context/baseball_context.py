"""Passive baseball-context packets for MLB scored legs.

This module deliberately does not mutate probabilities. It creates baseball
tags and publication-gate diagnostics that can be audited before future model
or builder changes use them.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from mlb.contracts.mlb_context_contract import GATE_CAUTION, GATE_OK, GATE_SUPPRESS

HITTER_MARKETS = {
    "doubles",
    "hits",
    "hits_runs_rbis",
    "hitter_fantasy_score",
    "hitter_strikeouts",
    "home_runs",
    "plate_appearances",
    "rbis",
    "runs",
    "singles",
    "stolen_bases",
    "total_bases",
    "triples",
    "walks",
}

PITCHER_MARKETS = {
    "earned_runs_allowed",
    "hits_allowed",
    "pitcher_fantasy_score",
    "pitcher_strikeouts",
    "pitches_thrown",
    "pitching_outs",
    "walks_allowed",
}

VOLUME_SENSITIVE_HITTER_MARKETS = {
    "doubles",
    "hits",
    "hits_runs_rbis",
    "hitter_fantasy_score",
    "home_runs",
    "rbis",
    "runs",
    "singles",
    "total_bases",
}

HIGH_VARIANCE_MARKETS = {
    "doubles",
    "hits_runs_rbis",
    "hitter_fantasy_score",
    "home_runs",
    "pitcher_fantasy_score",
    "rbis",
    "stolen_bases",
    "total_bases",
    "triples",
}

POWER_ENVIRONMENT_MARKETS = {"doubles", "hits_runs_rbis", "hitter_fantasy_score", "home_runs", "total_bases", "triples"}
WORKLOAD_PITCHER_MARKETS = {"earned_runs_allowed", "hits_allowed", "pitcher_fantasy_score", "pitches_thrown", "pitching_outs"}


def build_context_packets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_context_packet(row) for row in rows]


def build_context_packet(row: dict[str, Any]) -> dict[str, Any]:
    market = _market_key(row)
    side = _side(row)
    line = _optional_float(row.get("line"))
    market_group = _market_group(row, market)
    is_hitter = market_group == "hitter"
    is_pitcher = market_group == "pitcher"
    slot = _optional_int(row.get("batting_order_slot"))
    lineup_status = _lineup_status(row, market_group=market_group, slot=slot)
    pitcher_status = _pitcher_status(row, market_group=market_group)
    batting_bucket = _batting_order_bucket(slot)
    tags: list[str] = []
    gate_reasons: list[str] = []

    identity_missing = not (_clean(row.get("player_name")) and market and side and line is not None)
    if identity_missing:
        _add(tags, "identity_incomplete")
        gate_reasons.append("identity_incomplete")

    if _truthy(row.get("feature_context_joined")) is False:
        _add(tags, "feature_context_missing")
        gate_reasons.append("feature_context_missing")

    if is_hitter:
        if lineup_status == "confirmed":
            _add(tags, "confirmed_lineup")
        elif lineup_status == "projected":
            _add(tags, "projected_lineup")
            gate_reasons.append("projected_lineup")
        else:
            _add(tags, "unknown_lineup")
            gate_reasons.append("unknown_hitter_lineup")

        if batting_bucket in {"leadoff", "premium_top_order", "middle_order"}:
            _add(tags, "top_order_volume" if batting_bucket != "middle_order" else "middle_order_role")
        elif batting_bucket in {"lower_middle_order", "bottom_order"} and market in VOLUME_SENSITIVE_HITTER_MARKETS:
            _add(tags, "bottom_order_volume_risk")
            gate_reasons.append("bottom_order_volume_risk")

    if is_pitcher:
        if pitcher_status == "confirmed":
            _add(tags, "probable_starter_confirmed")
        else:
            _add(tags, "unknown_starter_status")
            gate_reasons.append("unknown_pitcher_starter_status")
        if market in WORKLOAD_PITCHER_MARKETS:
            _add(tags, "pitcher_workload_market")

    if market in HIGH_VARIANCE_MARKETS:
        _add(tags, "high_variance_prop")
        if is_hitter and side == "over":
            gate_reasons.append("high_variance_over")

    if _truthy(row.get("prizepicks_line_only_market_context")):
        _add(tags, "line_only_market_context")
        gate_reasons.append("line_only_market_context")

    if _truthy(row.get("matchup_context_available")):
        _add(tags, "matchup_context_available")
    else:
        _add(tags, "missing_matchup_context")
        gate_reasons.append("missing_matchup_context")

    weather_available = _truthy(row.get("weather_context_available"))
    park_confidence = _optional_float(row.get("park_factor_confidence")) or 0.0
    if weather_available or park_confidence > 0:
        _add(tags, "park_weather_context_available")
    elif market in POWER_ENVIRONMENT_MARKETS or market in WORKLOAD_PITCHER_MARKETS:
        _add(tags, "missing_weather_context")
        gate_reasons.append("missing_weather_context")

    environment_score = _optional_float(row.get("environment_score")) or 0.0
    if side == "over" and market in POWER_ENVIRONMENT_MARKETS and environment_score <= -0.08:
        _add(tags, "hostile_power_environment")
        gate_reasons.append("hostile_power_environment")

    if is_pitcher and market in WORKLOAD_PITCHER_MARKETS and _has_weather_delay_risk(row):
        _add(tags, "weather_delay_workload_risk")
        gate_reasons.append("weather_delay_workload_risk")

    suppress_reasons = {
        "identity_incomplete",
        "unknown_hitter_lineup",
        "unknown_pitcher_starter_status",
        "weather_delay_workload_risk",
    }
    gate_level = GATE_SUPPRESS if any(reason in suppress_reasons for reason in gate_reasons) else (
        GATE_CAUTION if gate_reasons else GATE_OK
    )

    return {
        "projection_id": _clean(row.get("source_projection_id") or row.get("projection_id")),
        "player_name": _clean(row.get("player_name")),
        "player_id": _clean(row.get("player_id")),
        "team": _clean(row.get("player_team") or row.get("team")),
        "opponent": _clean(row.get("opponent")),
        "event_id": _clean(row.get("event_id")),
        "game_date": _clean(row.get("game_date")),
        "start_time_utc": _clean(row.get("start_time_utc")),
        "market": market,
        "source_market": _clean(row.get("source_market")),
        "market_group": market_group,
        "side": side,
        "line": line,
        "tier": _clean(row.get("tier")).upper(),
        "model_probability": _optional_float(row.get("model_probability")),
        "p_cal": _optional_float(row.get("p_cal")),
        "lineup_status": lineup_status,
        "batting_order_spot": slot,
        "batting_order_bucket": batting_bucket,
        "projected_plate_appearances": _optional_float(
            row.get("projected_plate_appearances") or row.get("plate_appearance_projection")
        ),
        "lineup_probability": _optional_float(row.get("lineup_probability")),
        "pitcher_status": pitcher_status,
        "opportunity_confidence": _optional_float(row.get("opportunity_confidence")),
        "opportunity_fragility_score": _optional_float(row.get("opportunity_fragility_score")),
        "matchup_confidence": _optional_float(row.get("matchup_confidence")),
        "environment_score": environment_score,
        "park_factor_confidence": park_confidence,
        "external_market_context_available": _truthy(row.get("external_market_context_available")),
        "line_only_market_context": _truthy(row.get("prizepicks_line_only_market_context")),
        "gate_level": gate_level,
        "public_publish_ok": gate_level != GATE_SUPPRESS,
        "tags": sorted(tags),
        "gate_reasons": sorted(set(gate_reasons)),
    }


def summarize_context_packets(packets: list[dict[str, Any]]) -> dict[str, Any]:
    tag_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    gate_counts: Counter[str] = Counter()
    for packet in packets:
        gate_counts.update([str(packet.get("gate_level") or "")])
        tag_counts.update(str(tag) for tag in packet.get("tags") or [])
        reason_counts.update(str(reason) for reason in packet.get("gate_reasons") or [])
    return {
        "row_count": len(packets),
        "gate_counts": dict(sorted(gate_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "gate_reason_counts": dict(sorted(reason_counts.items())),
        "public_publish_ok_count": sum(1 for packet in packets if packet.get("public_publish_ok")),
        "suppressed_count": gate_counts.get(GATE_SUPPRESS, 0),
        "caution_count": gate_counts.get(GATE_CAUTION, 0),
        "ok_count": gate_counts.get(GATE_OK, 0),
    }


def _lineup_status(row: dict[str, Any], *, market_group: str, slot: int | None) -> str:
    if market_group != "hitter":
        return "not_applicable"
    lineup_confirmed = _truthy(row.get("lineup_confirmed"))
    lineup_probability = _optional_float(row.get("lineup_probability")) or 0.0
    lineup_context_available = _truthy(row.get("lineup_context_available"))
    if lineup_confirmed or (slot is not None and slot > 0 and lineup_probability >= 0.99):
        return "confirmed"
    if lineup_context_available or (slot is not None and slot > 0) or lineup_probability > 0:
        return "projected"
    return "unknown"


def _pitcher_status(row: dict[str, Any], *, market_group: str) -> str:
    if market_group != "pitcher":
        return "not_applicable"
    if _truthy(row.get("probable_pitcher_context_available")):
        return "confirmed"
    return "unknown"


def _batting_order_bucket(slot: int | None) -> str:
    if slot == 1:
        return "leadoff"
    if slot == 2:
        return "premium_top_order"
    if slot in {3, 4}:
        return "middle_order"
    if slot == 5:
        return "secondary_power"
    if slot == 6:
        return "lower_middle_order"
    if slot in {7, 8, 9}:
        return "bottom_order"
    return "unknown_order"


def _market_group(row: dict[str, Any], market: str) -> str:
    explicit = _clean(row.get("market_group")).lower()
    if explicit in {"hitter", "pitcher", "team", "combo"}:
        return explicit
    if market in PITCHER_MARKETS:
        return "pitcher"
    if market in HITTER_MARKETS:
        return "hitter"
    return explicit or "unknown"


def _market_key(row: dict[str, Any]) -> str:
    return _clean(row.get("market") or row.get("source_market")).lower().replace("+", "_").replace(" ", "_").replace("-", "_")


def _side(row: dict[str, Any]) -> str:
    side = _clean(row.get("side") or row.get("direction")).lower()
    if side in {"over", "under"}:
        return side
    return side


def _has_weather_delay_risk(row: dict[str, Any]) -> bool:
    flags = row.get("flags") if isinstance(row.get("flags"), list) else []
    text = " ".join(str(flag).lower() for flag in flags)
    if any(token in text for token in ("weather_delay", "rain_delay", "delay_risk", "weather_risk_high")):
        return True
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    return int(number)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _add(tags: list[str], tag: str) -> None:
    if tag not in tags:
        tags.append(tag)


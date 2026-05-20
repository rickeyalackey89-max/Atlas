"""Deterministic anomaly checks for Atlas MLB runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mlb.evaluation.schemas import Anomaly

READINESS_GATE_TOLERANCE = 0.005


def run_deterministic_anomaly_checks(run_packet: Mapping[str, Any]) -> tuple[Anomaly, ...]:
    """Return local anomaly findings before any AI review runs."""

    anomalies: list[Anomaly] = []
    run_mode = str(run_packet.get("run_mode", "unknown"))
    board_count = _as_int(run_packet.get("board_count") or run_packet.get("normalized_candidate_count"))
    scored_count = _as_int(run_packet.get("scored_candidate_count") or run_packet.get("score_count"))
    slip_count = _as_int(run_packet.get("slip_count"))
    unsupported_market_count = _as_int(run_packet.get("unsupported_market_count"))
    missing_pitcher_context = _as_int(run_packet.get("missing_pitcher_context_count"))
    pitcher_prop_count = _as_int(run_packet.get("pitcher_prop_count"))
    pitcher_prop_matchup_neutral_count = _as_int(run_packet.get("pitcher_prop_matchup_neutral_count"))
    matchup_context_by_market_group = run_packet.get("matchup_context_available_by_market_group")
    market_context_rate = _as_float(run_packet.get("market_context_available_rate"))
    source_completeness = run_packet.get("source_completeness")
    readiness_gates = run_packet.get("readiness_gates")
    source_refresh_error_count = _as_int(run_packet.get("source_refresh_error_count"))
    primary_market_status = str(run_packet.get("primary_market_source_status") or "")
    probability_min = _as_float(run_packet.get("model_probability_min"))
    probability_max = _as_float(run_packet.get("model_probability_max"))

    if board_count <= 0 and run_mode == "live":
        anomalies.append(
            Anomaly(
                type="empty_board",
                severity="hard_stop",
                message="Live run has no PrizePicks board candidates.",
                details={"board_count": board_count},
            )
        )

    if scored_count <= 0 and board_count > 0:
        anomalies.append(
            Anomaly(
                type="empty_scored_output",
                severity="hard_stop",
                message="Board candidates exist but no scored candidates were produced.",
                details={"board_count": board_count, "scored_candidate_count": scored_count},
            )
        )

    if board_count > 0 and scored_count > 0:
        coverage = scored_count / board_count
        if coverage < 0.50:
            severity = "hard_stop"
        elif coverage < 0.80:
            severity = "warning"
        else:
            severity = "info"
        if severity != "info":
            anomalies.append(
                Anomaly(
                    type="low_score_coverage",
                    severity=severity,
                    message="Scored candidate coverage is below expected range.",
                    details={
                        "board_count": board_count,
                        "scored_candidate_count": scored_count,
                        "coverage": round(coverage, 4),
                    },
                )
            )

    if unsupported_market_count > 0:
        anomalies.append(
            Anomaly(
                type="unsupported_markets",
                severity="warning",
                message="PrizePicks board included unsupported markets.",
                details={"unsupported_market_count": unsupported_market_count},
            )
        )

    if run_mode == "live" and source_refresh_error_count > 0:
        anomalies.append(
            Anomaly(
                type="source_refresh_errors",
                severity="hard_stop",
                message="One or more live context source refreshes failed.",
                details={
                    "source_refresh_error_count": source_refresh_error_count,
                    "source_refresh_errors": _json_safe(run_packet.get("source_refresh_errors")),
                },
            )
        )

    if run_mode == "live" and primary_market_status not in {"", "fetched", "existing"}:
        anomalies.append(
            Anomaly(
                type="primary_market_source_unavailable",
                severity="hard_stop",
                message="Primary live market source did not fetch cleanly.",
                details={
                    "primary_market_source_status": primary_market_status,
                    "primary_market_source_errors": _json_safe(run_packet.get("primary_market_source_errors")),
                },
            )
        )

    if run_mode == "live" and isinstance(source_completeness, Mapping):
        anomalies.extend(_readiness_gate_anomalies(source_completeness, readiness_gates))

    if missing_pitcher_context > 0:
        severity = "hard_stop" if pitcher_prop_count and missing_pitcher_context / pitcher_prop_count >= 0.50 else "warning"
        anomalies.append(
            Anomaly(
                type="missing_pitcher_context",
                severity=severity,
                message="Pitcher props are missing starter/bulk-role context.",
                details={
                    "missing_pitcher_context_count": missing_pitcher_context,
                    "pitcher_prop_count": pitcher_prop_count,
                },
            )
        )

    if run_mode == "live" and isinstance(matchup_context_by_market_group, Mapping):
        batter_matchup_rate = _as_float(matchup_context_by_market_group.get("batter"))
        if batter_matchup_rate is not None and batter_matchup_rate < 0.55:
            anomalies.append(
                Anomaly(
                    type="low_batter_matchup_context",
                    severity="hard_stop" if batter_matchup_rate < 0.35 else "warning",
                    message="Batter props have low matchup-context coverage.",
                    details={"batter_matchup_context_available_rate": round(batter_matchup_rate, 4)},
                )
            )

    if run_mode == "live" and pitcher_prop_matchup_neutral_count > 0:
        neutral_rate = (
            pitcher_prop_matchup_neutral_count / pitcher_prop_count
            if pitcher_prop_count and pitcher_prop_count > 0
            else 1.0
        )
        if neutral_rate < 0.05 and pitcher_prop_matchup_neutral_count < 20:
            neutral_rate = 0.0
    else:
        neutral_rate = 0.0
    if run_mode == "live" and neutral_rate > 0.0:
        anomalies.append(
            Anomaly(
                type="pitcher_prop_matchup_neutral",
                severity="warning",
                message="Pitcher props were scored with neutral pitcher-prop matchup shifts because source context was missing.",
                details={
                    "pitcher_prop_matchup_neutral_count": pitcher_prop_matchup_neutral_count,
                    "pitcher_prop_count": pitcher_prop_count,
                    "pitcher_prop_matchup_neutral_rate": round(neutral_rate, 4),
                },
            )
        )

    if run_mode == "live" and scored_count > 0 and market_context_rate is not None and market_context_rate < 0.25:
        anomalies.append(
            Anomaly(
                type="low_external_market_context",
                severity="warning",
                message="External market context coverage is low; probabilities are relying mostly on internal priors.",
                details={"market_context_available_rate": round(market_context_rate, 4)},
            )
        )

    if probability_min is not None and probability_min < 0:
        anomalies.append(
            Anomaly(
                type="invalid_probability",
                severity="hard_stop",
                message="Model probability minimum is below 0.",
                details={"model_probability_min": probability_min},
            )
        )
    if probability_max is not None and probability_max > 1:
        anomalies.append(
            Anomaly(
                type="invalid_probability",
                severity="hard_stop",
                message="Model probability maximum is above 1.",
                details={"model_probability_max": probability_max},
            )
        )

    if run_mode == "live" and scored_count > 0 and slip_count <= 0:
        anomalies.append(
            Anomaly(
                type="empty_slip_output",
                severity="warning",
                message="Scored candidates exist but no slip families were produced.",
                details={"scored_candidate_count": scored_count, "slip_count": slip_count},
            )
        )

    for index, failure in enumerate(_as_list(run_packet.get("hard_failures")), start=1):
        anomalies.append(
            Anomaly(
                type="hard_failure",
                severity="hard_stop",
                message=str(failure),
                details={"failure_index": index},
            )
        )

    return tuple(anomalies)


def _readiness_gate_anomalies(
    source_completeness: Mapping[str, Any],
    readiness_gates: Any,
) -> list[Anomaly]:
    gates = readiness_gates if isinstance(readiness_gates, Mapping) else {}
    field_map = (
        ("external_market_context_available", "market_context_min_coverage", "market_context_below_gate"),
        ("lineup_context_available", "lineup_context_min_coverage", "lineup_context_below_gate"),
        ("roster_context_available", "roster_context_min_coverage", "roster_context_below_gate"),
        ("player_history_context_available", "player_history_context_min_coverage", "player_history_context_below_gate"),
        ("advanced_context_available", "advanced_context_min_coverage", "advanced_context_below_gate"),
    )
    anomalies: list[Anomaly] = []
    for field, gate_name, anomaly_type in field_map:
        threshold = _as_float(gates.get(gate_name))
        if threshold is None:
            continue
        actual = _as_float(source_completeness.get(field))
        if actual is None or actual + READINESS_GATE_TOLERANCE >= threshold:
            continue
        anomalies.append(
            Anomaly(
                type=anomaly_type,
                severity="hard_stop",
                message=f"Live source coverage for {field} is below the configured readiness gate.",
                details={
                    "field": field,
                    "actual": round(actual, 6),
                    "required": round(threshold, 6),
                },
            )
        )
    return anomalies


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]

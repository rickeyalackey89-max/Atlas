"""Publish-decision helpers for Atlas MLB operator evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from mlb.evaluation.schemas import AIStatus, Anomaly, PublishDecision, Severity, max_severity


def build_publish_decision(
    run_packet: Mapping[str, Any],
    anomalies: Sequence[Anomaly],
    *,
    ai_decision: Mapping[str, Any] | None = None,
) -> PublishDecision:
    """Build the final publish decision from deterministic and optional AI findings."""

    deterministic_anomalies = tuple(anomalies)
    deterministic_severity = max_severity(deterministic_anomalies)
    ai_status = str(run_packet.get("ai_status", "not_requested"))
    ai_model = run_packet.get("ai_model")

    ai_anomalies = _ai_anomalies(ai_decision)
    all_anomalies = deterministic_anomalies + ai_anomalies
    severity = max_severity(all_anomalies)
    deterministic_hard_stop = deterministic_severity == "hard_stop"
    ai_publish_allowed = True if ai_decision is None else bool(ai_decision.get("publish_allowed", False))
    run_mode = str(run_packet.get("run_mode", "unknown"))
    mode_publish_allowed = run_mode == "live"
    publish_allowed = (
        mode_publish_allowed
        and not deterministic_hard_stop
        and ai_publish_allowed
        and severity != "hard_stop"
    )

    summary = _summary(run_packet, deterministic_severity, ai_decision, publish_allowed)
    operator_notes = tuple(str(note) for note in (ai_decision or {}).get("operator_notes", ()))
    next_actions = tuple(str(action) for action in (ai_decision or {}).get("recommended_next_actions", ()))

    if deterministic_hard_stop:
        next_actions = ("Resolve deterministic hard-stop anomalies before publishing.",) + next_actions

    return PublishDecision(
        run_id=str(run_packet.get("run_id", "unknown")),
        run_mode=run_mode,
        publish_allowed=publish_allowed,
        severity=severity,
        summary=summary,
        anomalies=all_anomalies,
        operator_notes=operator_notes,
        recommended_next_actions=next_actions,
        ai_status=_coerce_ai_status(ai_status),
        ai_model=str(ai_model) if ai_model else None,
    )


def _summary(
    run_packet: Mapping[str, Any],
    deterministic_severity: Severity,
    ai_decision: Mapping[str, Any] | None,
    publish_allowed: bool,
) -> str:
    if deterministic_severity == "hard_stop":
        return "Publish blocked by deterministic hard-stop checks."
    if str(run_packet.get("run_mode", "unknown")) != "live":
        return "Publish blocked because replay runs are isolated from live publishing."
    if ai_decision and ai_decision.get("summary"):
        return str(ai_decision["summary"])
    if publish_allowed:
        return "Run passed deterministic checks and is eligible for publish."
    return "Publish blocked by operator evaluation."


def _ai_anomalies(ai_decision: Mapping[str, Any] | None) -> tuple[Anomaly, ...]:
    if not ai_decision:
        return ()
    anomalies: list[Anomaly] = []
    for item in ai_decision.get("anomalies", ()):
        if not isinstance(item, Mapping):
            continue
        severity = str(item.get("severity", "warning"))
        if severity not in {"info", "warning", "hard_stop"}:
            severity = "warning"
        severity_value = cast(Severity, severity)
        details = item.get("details", {})
        anomalies.append(
            Anomaly(
                type=str(item.get("type", "ai_anomaly")),
                severity=severity_value,
                message=str(item.get("message", "AI evaluator reported an anomaly.")),
                details=dict(details) if isinstance(details, Mapping) else {},
            )
        )
    return tuple(anomalies)


def _coerce_ai_status(value: str) -> AIStatus:
    if value in {"not_requested", "skipped", "completed", "unavailable", "error"}:
        return cast(AIStatus, value)
    return "not_requested"

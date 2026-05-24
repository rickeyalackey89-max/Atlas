"""Schemas for Atlas MLB operator evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Severity = Literal["info", "warning", "hard_stop"]
AIStatus = Literal["not_requested", "skipped", "completed", "unavailable", "error"]

SEVERITY_RANK: dict[Severity, int] = {
    "info": 0,
    "warning": 1,
    "hard_stop": 2,
}

DEFAULT_OPERATOR_MODEL = "gpt-5.3-spark"
DEFAULT_OPERATOR_REVIEWER_LANE = "5.3-spark"


@dataclass(frozen=True)
class Anomaly:
    type: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublishDecision:
    run_id: str
    run_mode: str
    publish_allowed: bool
    severity: Severity
    summary: str
    anomalies: tuple[Anomaly, ...] = ()
    operator_notes: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    ai_status: AIStatus = "not_requested"
    ai_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["anomalies"] = [anomaly.to_dict() for anomaly in self.anomalies]
        payload["operator_notes"] = list(self.operator_notes)
        payload["recommended_next_actions"] = list(self.recommended_next_actions)
        return payload


PUBLISH_DECISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "publish_allowed",
        "severity",
        "summary",
        "anomalies",
        "operator_notes",
        "recommended_next_actions",
    ],
    "properties": {
        "publish_allowed": {"type": "boolean"},
        "severity": {"type": "string", "enum": ["info", "warning", "hard_stop"]},
        "summary": {"type": "string"},
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "severity", "message", "details"],
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "hard_stop"]},
                    "message": {"type": "string"},
                    "details": {
                        "type": "object",
                        "additionalProperties": {
                            "type": ["string", "number", "integer", "boolean", "null"],
                        },
                    },
                },
            },
        },
        "operator_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_next_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

OPENAI_EVALUATOR_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "name": "atlas_mlb_publish_decision",
    "strict": True,
    "schema": PUBLISH_DECISION_JSON_SCHEMA,
}


def max_severity(anomalies: tuple[Anomaly, ...]) -> Severity:
    if not anomalies:
        return "info"
    return max((anomaly.severity for anomaly in anomalies), key=lambda severity: SEVERITY_RANK[severity])

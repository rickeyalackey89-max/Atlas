"""Markdown operator reports for Atlas MLB runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mlb.evaluation.schemas import PublishDecision


def build_operator_report(run_packet: Mapping[str, Any], decision: PublishDecision) -> str:
    """Create a compact operator report for a live or replay run."""

    lines = [
        f"# Atlas MLB Operator Report: {decision.run_id}",
        "",
        f"- Run mode: `{decision.run_mode}`",
        f"- Publish allowed: `{decision.publish_allowed}`",
        f"- Severity: `{decision.severity}`",
        f"- AI status: `{decision.ai_status}`",
        f"- AI model: `{decision.ai_model or 'none'}`",
        "",
        "## Summary",
        "",
        decision.summary,
        "",
        "## Run Snapshot",
        "",
    ]
    for key in (
        "board_count",
        "scored_candidate_count",
        "slip_count",
        "unsupported_market_count",
        "missing_pitcher_context_count",
        "model_probability_min",
        "model_probability_max",
    ):
        if key in run_packet:
            lines.append(f"- {key}: `{run_packet[key]}`")

    lines.extend(["", "## Anomalies", ""])
    if decision.anomalies:
        for anomaly in decision.anomalies:
            lines.append(f"- `{anomaly.severity}` `{anomaly.type}`: {anomaly.message}")
    else:
        lines.append("- No anomalies detected.")

    lines.extend(["", "## Operator Notes", ""])
    if decision.operator_notes:
        lines.extend(f"- {note}" for note in decision.operator_notes)
    else:
        lines.append("- No AI operator notes recorded.")

    lines.extend(["", "## Recommended Next Actions", ""])
    if decision.recommended_next_actions:
        lines.extend(f"- {action}" for action in decision.recommended_next_actions)
    else:
        lines.append("- Continue normal review workflow.")

    return "\n".join(lines) + "\n"


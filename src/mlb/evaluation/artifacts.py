"""Artifact writers for Atlas MLB operator evaluation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mlb.evaluation.operator_report import build_operator_report
from mlb.evaluation.schemas import Anomaly, PublishDecision


def write_operator_artifacts(
    output_dir: Path,
    *,
    run_packet: Mapping[str, Any],
    anomalies: Sequence[Anomaly],
    decision: PublishDecision,
    ai_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Write the standard operator AI artifact bundle."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "ai_evaluation": output_dir / "ai_evaluation.json",
        "anomalies": output_dir / "anomalies.jsonl",
        "operator_report": output_dir / "operator_report.md",
        "publish_decision": output_dir / "publish_decision.json",
    }

    paths["ai_evaluation"].write_text(
        json.dumps(dict(ai_evaluation or {"ai_status": decision.ai_status}), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    paths["anomalies"].write_text(
        "\n".join(json.dumps(anomaly.to_dict(), sort_keys=True) for anomaly in anomalies) + ("\n" if anomalies else ""),
        encoding="utf-8",
    )
    paths["operator_report"].write_text(build_operator_report(run_packet, decision), encoding="utf-8")
    paths["publish_decision"].write_text(
        json.dumps(decision.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return paths


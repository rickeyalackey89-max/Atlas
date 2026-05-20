"""Operator evaluation workflow planning for Atlas MLB."""

from __future__ import annotations

from mlb.runtime.results import RuntimeCommandResult


OPERATOR_EVALUATION_STAGES = (
    "run_deterministic_anomaly_checks",
    "run_openai_operator_evaluation",
    "write_operator_report",
    "write_publish_decision",
)


def operator_evaluation_plan_result() -> RuntimeCommandResult:
    """Return the operator/AI evaluation plan without running API calls."""

    payload = {
        "name": "operator_ai_evaluation",
        "status": "contracts_integrated_api_opt_in",
        "artifacts": [
            "data/mlb/test_runs/<run_id>/operator/operator_input.json",
            "data/mlb/live_runs/<run_id>/operator/operator_input.json",
            "data/mlb/<test_runs|live_runs>/<run_id>/operator/ai_evaluation.json",
            "data/mlb/<test_runs|live_runs>/<run_id>/operator/anomalies.jsonl",
            "data/mlb/<test_runs|live_runs>/<run_id>/operator/operator_report.md",
            "data/mlb/<test_runs|live_runs>/<run_id>/operator/publish_decision.json",
        ],
        "stages": list(OPERATOR_EVALUATION_STAGES),
        "publish_rule": "Dashboard publish requires deterministic checks and AI/operator decision to allow it.",
        "api_rule": "OpenAI calls require ATLAS_OPENAI_EVALUATOR_ENABLED=1 and OPENAI_API_KEY.",
    }
    lines = [
        "MLB operator AI evaluation:",
        f"  status: {payload['status']}",
        "  stages:",
        *(f"    - {stage}" for stage in OPERATOR_EVALUATION_STAGES),
        f"  publish_rule: {payload['publish_rule']}",
        f"  api_rule: {payload['api_rule']}",
    ]
    return RuntimeCommandResult(name="operator", payload=payload, lines=tuple(lines))

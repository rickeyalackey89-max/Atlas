"""OpenAI-backed operator evaluation for Atlas MLB."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from mlb.evaluation.schemas import (
    DEFAULT_OPERATOR_MODEL,
    DEFAULT_OPERATOR_REVIEWER_LANE,
    OPENAI_EVALUATOR_RESPONSE_FORMAT,
)


SYSTEM_PROMPT = """You are the Atlas MLB operator evaluator.
Review run outputs for publish safety, data integrity, model-output anomalies,
and operator risk. Do not change model probabilities or picks. Return only the
schema-valid JSON requested by the API."""


def openai_evaluator_enabled() -> bool:
    """Return whether OpenAI evaluation should be attempted."""

    value = os.getenv("ATLAS_OPENAI_EVALUATOR_ENABLED", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def configured_operator_model() -> str:
    return os.getenv("ATLAS_OPENAI_EVALUATOR_MODEL", DEFAULT_OPERATOR_MODEL).strip() or DEFAULT_OPERATOR_MODEL


def configured_operator_reviewer_lane() -> str:
    return (
        os.getenv("ATLAS_OPENAI_EVALUATOR_LANE", DEFAULT_OPERATOR_REVIEWER_LANE).strip()
        or DEFAULT_OPERATOR_REVIEWER_LANE
    )


def build_openai_review_packet(
    *,
    run_id: str,
    run_mode: str,
    run_summary: Mapping[str, Any],
    deterministic_anomalies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the compact packet sent to the operator evaluator."""

    return {
        "run_id": run_id,
        "run_mode": run_mode,
        "reviewer_lane": configured_operator_reviewer_lane(),
        "run_summary": dict(run_summary),
        "deterministic_anomalies": deterministic_anomalies,
        "instructions": {
            "do_not_mutate_model_outputs": True,
            "block_publish_for_hard_stops": True,
            "prefer_operator_next_actions_over_general_commentary": True,
        },
    }


def evaluate_with_openai(
    review_packet: Mapping[str, Any],
    *,
    model: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run the OpenAI operator evaluator.

    This function is safe to import without the OpenAI SDK installed. It only
    imports the SDK when the evaluator is enabled and a call is requested.
    """

    model_name = model or configured_operator_model()
    reviewer_lane = configured_operator_reviewer_lane()
    if client is None and not openai_evaluator_enabled():
        return _skipped("skipped", "ATLAS_OPENAI_EVALUATOR_ENABLED is not enabled.", model_name, reviewer_lane)
    if client is None and not os.getenv("OPENAI_API_KEY"):
        return _skipped("skipped", "OPENAI_API_KEY is not set.", model_name, reviewer_lane)

    if client is None:
        try:
            from openai import OpenAI
        except ImportError:
            return _skipped(
                "unavailable",
                "OpenAI SDK is not installed. Install the optional ai extra.",
                model_name,
                reviewer_lane,
            )
        client = OpenAI()

    try:
        response = client.responses.create(
            model=model_name,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(review_packet, sort_keys=True)},
            ],
            text={"format": OPENAI_EVALUATOR_RESPONSE_FORMAT},
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper around external SDK/network behavior.
        return _skipped("error", f"OpenAI evaluator failed: {exc}", model_name, reviewer_lane)

    output_text = _extract_output_text(response)
    if not output_text:
        return _skipped("error", "OpenAI evaluator returned no output text.", model_name, reviewer_lane)

    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        return _skipped("error", f"OpenAI evaluator returned invalid JSON: {exc}", model_name, reviewer_lane)

    payload["ai_status"] = "completed"
    payload["ai_model"] = model_name
    payload["ai_reviewer_lane"] = reviewer_lane
    return payload


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _skipped(status: str, reason: str, model: str, reviewer_lane: str) -> dict[str, Any]:
    return {
        "ai_status": status,
        "ai_model": model,
        "ai_reviewer_lane": reviewer_lane,
        "publish_allowed": False,
        "severity": "warning" if status in {"skipped", "unavailable"} else "hard_stop",
        "summary": reason,
        "anomalies": [],
        "operator_notes": [reason],
        "recommended_next_actions": ["Run deterministic review only or configure OpenAI evaluator credentials."],
    }

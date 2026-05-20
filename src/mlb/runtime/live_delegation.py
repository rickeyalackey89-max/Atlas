"""Live-run delegation boundaries for Atlas MLB."""

from __future__ import annotations

from mlb.runtime.pipeline import LIVE_PIPELINE_STAGES
from mlb.runtime.publishing import publishing_status
from mlb.runtime.results import RuntimeCommandResult


def live_plan_result() -> RuntimeCommandResult:
    """Return the live-run plan without executing a live job."""

    publishing = publishing_status()
    payload = {
        "mode": "live",
        "status": "disabled_dev_skeleton",
        "purpose": "Same-day PrizePicks MLB run that may later publish slips and dashboard payloads.",
        "publishing": publishing,
        "stages": list(LIVE_PIPELINE_STAGES),
        "stage_count": len(LIVE_PIPELINE_STAGES),
        "safety_rule": "Live execution remains disabled until replay/eval contracts are approved.",
    }
    lines = [
        "MLB live plan:",
        f"  status: {payload['status']}",
        f"  publishing_enabled: {publishing['enabled']}",
        "  stages:",
        *(f"    - {stage}" for stage in LIVE_PIPELINE_STAGES),
    ]
    return RuntimeCommandResult(name="live", payload=payload, lines=tuple(lines))

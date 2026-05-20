"""Publishing runtime state for Atlas MLB.

Publishing stays isolated from the pipeline definition so live/dashboard/Discord
controls do not drift into CLI parsing or model orchestration.
"""

from __future__ import annotations


PUBLISHING_STAGES = (
    "build_dashboard_payload",
    "post_discord_slips",
)


def publishing_enabled() -> bool:
    """Return whether MLB-dev may publish externally.

    This is deliberately hard-disabled until replay, eval, dashboard payloads,
    and Discord routes are reviewed.
    """

    return False


def publishing_status() -> dict[str, object]:
    """Return the current publishing guardrail state."""

    return {
        "enabled": publishing_enabled(),
        "stages": list(PUBLISHING_STAGES),
        "mode": "disabled_dev_skeleton",
        "reason": "MLB replay/eval and dashboard contracts are not production-approved.",
    }


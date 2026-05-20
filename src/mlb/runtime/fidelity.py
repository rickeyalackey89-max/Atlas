"""Run-mode and replay fidelity policy for Atlas MLB."""

from __future__ import annotations

from typing import Any

FIDELITY_POLICY_VERSION = "mlb_replay_fidelity_v1"
FIDELITY_RULE = (
    "Strict fidelity: replay inputs must match the artifacts and source-selection "
    "rules the live model would have consumed. No post-date context, invented "
    "fallbacks, or replay-only model inputs may feed probability scoring."
)

CANONICAL_RUN_MODES = ("live", "replay_single", "replay_corpus")
RUN_MODE_ALIASES = {
    "live": "live",
    "replay": "replay_single",
    "single": "replay_single",
    "replay_single": "replay_single",
    "corpus": "replay_corpus",
    "bundle": "replay_corpus",
    "replay_bundle": "replay_corpus",
    "replay_corpus": "replay_corpus",
}


def normalize_run_mode(value: str | None) -> str:
    mode = str(value or "replay_single").strip().lower().replace("-", "_")
    if mode not in RUN_MODE_ALIASES:
        raise ValueError(f"Unknown MLB run mode: {value!r}")
    return RUN_MODE_ALIASES[mode]


def replay_type_for_run_mode(value: str | None) -> str:
    mode = normalize_run_mode(value)
    if mode == "replay_single":
        return "single"
    if mode == "replay_corpus":
        return "corpus"
    return ""


def is_replay_mode(value: str | None) -> bool:
    return bool(replay_type_for_run_mode(value))


def fidelity_policy(value: str | None) -> dict[str, Any]:
    mode = normalize_run_mode(value)
    replay_type = replay_type_for_run_mode(mode)
    return {
        "policy_version": FIDELITY_POLICY_VERSION,
        "rule": FIDELITY_RULE,
        "run_mode": mode,
        "replay_type": replay_type,
        "strict_replay_fidelity": bool(replay_type),
        "post_date_context_allowed": False,
        "replay_only_model_inputs_allowed": False,
        "publish_allowed_by_mode": mode == "live",
    }

"""Replay delegation boundaries for Atlas MLB."""

from __future__ import annotations

from typing import Literal

from mlb.runtime.pipeline import CORPUS_REPLAY_PIPELINE_STAGES, SINGLE_REPLAY_PIPELINE_STAGES
from mlb.runtime.results import RuntimeCommandResult


ReplayMode = Literal["single", "corpus", "bundle"]

REPLAY_MODE_DESCRIPTIONS = {
    "single": "Replay one targeted historical run for debugging, validation, or spot checks.",
    "corpus": "Replay a group of historical runs to build a corpus, cache, LOSO set, or trainer input.",
}


def replay_summary_result() -> RuntimeCommandResult:
    """Return replay mode definitions without running a replay."""

    payload = {
        "mode": "replay",
        "modes": REPLAY_MODE_DESCRIPTIONS,
        "safety_rule": (
            "Replay artifacts must be isolated from live outputs, publish nothing by default, "
            "and obey strict live-fidelity source rules."
        ),
    }
    lines = [
        "MLB replay modes:",
        f"  single: {REPLAY_MODE_DESCRIPTIONS['single']}",
        f"  corpus: {REPLAY_MODE_DESCRIPTIONS['corpus']}",
    ]
    return RuntimeCommandResult(name="replay", payload=payload, lines=tuple(lines))


def replay_plan_result(mode: ReplayMode) -> RuntimeCommandResult:
    """Return a replay execution plan for the requested replay mode."""

    if mode == "single":
        stages = SINGLE_REPLAY_PIPELINE_STAGES
        target = "one run_id or one raw snapshot set"
        canonical_mode = "single"
    elif mode in {"corpus", "bundle"}:
        stages = CORPUS_REPLAY_PIPELINE_STAGES
        target = "many run_ids or a corpus replay manifest"
        canonical_mode = "corpus"
    else:
        raise ValueError(f"Unknown MLB replay mode: {mode}")

    payload = {
        "mode": "replay",
        "replay_type": canonical_mode,
        "target": target,
        "purpose": REPLAY_MODE_DESCRIPTIONS[canonical_mode],
        "publishing_enabled": False,
        "stages": list(stages),
        "stage_count": len(stages),
        "safety_rule": "Replay outputs must not overwrite live run artifacts or use post-date model inputs.",
    }
    lines = [
        f"MLB replay plan: {canonical_mode}",
        f"  target: {target}",
        "  publishing_enabled: False",
        "  stages:",
        *(f"    - {stage}" for stage in stages),
    ]
    return RuntimeCommandResult(name=f"replay_{canonical_mode}", payload=payload, lines=tuple(lines))

"""Run bundle contracts for Atlas MLB.

This module describes the artifact groups the runtime should eventually write.
Keeping this out of the CLI prevents the command surface from becoming the
source of truth for replay and publishing artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BundleArtifact:
    name: str
    phase: str
    path_template: str
    required: bool = True


EXPECTED_BUNDLE_ARTIFACTS = (
    BundleArtifact(
        name="raw_prizepicks_snapshot",
        phase="source_snapshots",
        path_template="data/mlb/raw/prizepicks/{date}/{timestamp}/payload.json",
    ),
    BundleArtifact(
        name="raw_injury_snapshot",
        phase="source_snapshots",
        path_template="data/mlb/raw/espn_injuries/{date}/{timestamp}/payload.*",
    ),
    BundleArtifact(
        name="normalized_board",
        phase="normalized_board",
        path_template="data/mlb/staged/board/{run_id}/normalized_board.parquet",
    ),
    BundleArtifact(
        name="source_manifest",
        phase="normalized_board",
        path_template="data/mlb/replay_runs/{run_id}/source_manifest.json",
    ),
    BundleArtifact(
        name="share_matrix",
        phase="availability",
        path_template="data/mlb/features/share_matrix/{run_id}/share_matrix.parquet",
    ),
    BundleArtifact(
        name="parameter_table",
        phase="parameters",
        path_template="data/mlb/features/parameters/{run_id}/parameter_table.csv",
    ),
    BundleArtifact(
        name="simulation_manifest",
        phase="simulation",
        path_template="data/mlb/replay_runs/{run_id}/simulation_manifest.json",
    ),
    BundleArtifact(
        name="scored_legs",
        phase="simulation",
        path_template="data/mlb/replay_runs/{run_id}/scored_legs.csv",
    ),
    BundleArtifact(
        name="eval_legs",
        phase="settlement_replay",
        path_template="data/mlb/eval/{run_id}/eval_legs.parquet",
    ),
    BundleArtifact(
        name="run_manifest",
        phase="settlement_replay",
        path_template="data/mlb/replay_runs/{run_id}/run_manifest.json",
    ),
    BundleArtifact(
        name="slip_families",
        phase="slips",
        path_template="data/mlb/replay_runs/{run_id}/{System,Windfall,marketed_slips.csv,demonhunter.csv,big_swings.csv}",
        required=False,
    ),
)


def expected_bundle_artifacts() -> tuple[BundleArtifact, ...]:
    """Return the expected MLB runtime artifacts in build order."""

    return EXPECTED_BUNDLE_ARTIFACTS


def bundle_plan() -> dict[str, object]:
    """Return a serializable artifact plan for status and docs commands."""

    artifacts = [
        {
            "name": artifact.name,
            "phase": artifact.phase,
            "path_template": artifact.path_template,
            "required": artifact.required,
        }
        for artifact in EXPECTED_BUNDLE_ARTIFACTS
    ]
    return {
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }

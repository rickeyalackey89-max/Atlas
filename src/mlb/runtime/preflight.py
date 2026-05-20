"""Preflight checks for Atlas MLB runtime commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mlb.domain.markets import SUPPORTED_MARKETS
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.pipeline import MLB_PIPELINE_STAGES
from mlb.runtime.publishing import publishing_enabled


def build_preflight_report(root: Path | None = None) -> dict[str, Any]:
    """Create the MLB-dev safety report used by doctor/status commands."""

    paths = ensure_mlb_dirs(root)
    return {
        "sport": "mlb",
        "status": "development_skeleton",
        "repo_root": str(paths.repo_root),
        "data_root": str(paths.data_root),
        "publishing_enabled": publishing_enabled(),
        "pipeline_stage_count": len(MLB_PIPELINE_STAGES),
        "legacy_nba_live_cli": "removed",
        "supported_market_count": len(SUPPORTED_MARKETS),
        "note": "MLB Dev is not wired to the copied NBA live CLI.",
    }

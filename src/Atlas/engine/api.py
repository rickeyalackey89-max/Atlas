from __future__ import annotations

"""Engine API seam for legacy retirement.

This module introduces a narrow, stable interface that both the legacy engine
and the future new engine can implement.

IMPORTANT (Phase 6):
- Additive only.
- No scoring logic changes.
- No writes to data/output from this layer.

Replay comparator tools can call this API to compute in-memory outputs and
write comparisons to archives only.
"""

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd


@dataclass(frozen=True)
class EngineOutputs:
    """In-memory engine artifacts.

    These are the canonical artifacts produced by the core pipeline stages.
    Publishing (writing to data/output) is explicitly out of scope.
    """

    scored: pd.DataFrame
    scored_for_optimizer: pd.DataFrame

    # Product outputs (DataFrames in current staged pipeline)
    sys3: pd.DataFrame
    sys4: pd.DataFrame
    sys5: pd.DataFrame
    wind3: pd.DataFrame
    wind4: pd.DataFrame
    wind5: pd.DataFrame


class Engine:
    """Abstract engine interface."""

    name: str = "engine"

    def run(
        self,
        *,
        board: pd.DataFrame,
        logs: pd.DataFrame,
        cfg: dict[str, Any],
        iael_df: Optional[pd.DataFrame] = None,
    ) -> EngineOutputs:
        raise NotImplementedError

from __future__ import annotations

from typing import Any

import pandas as pd

from Atlas.stages.score.score_board import run_score_board


def run_score_today(
    board: pd.DataFrame,
    logs: pd.DataFrame,
    cfg: dict[str, Any],
    iael_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Thin compatibility wrapper around the deterministic Score Stage.
    """
    return run_score_board(board=board, logs=logs, cfg=cfg, iael_df=iael_df)
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from Atlas.model.share_matrix_contract import require_valid_share_matrix
from Atlas.model.team_share_allocator_v2 import build_share_matrix_v2 as _build_share_matrix_v2_impl, load_iael_snapshot


def emit_share_matrix_csv(df: pd.DataFrame, out_path: str | Path) -> Path:
    """
    Emit a validated share matrix using the existing downstream contract.

    The v2 allocator will eventually feed this function.
    For now, it acts as the contract-preserving write path.
    """
    require_valid_share_matrix(df)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def build_share_matrix_v2(df: pd.DataFrame, out_path: str | Path) -> Path:
    """
    Thin v2 entry point.

    Once the allocator is rebuilt, this should become the only writer used by
    the CLI. Until then, it preserves the contract and centralizes validation.
    """
    return emit_share_matrix_csv(df.copy(), out_path)


def generate_share_matrix_v2(
    gamelogs: pd.DataFrame,
    *,
    iael_df: Optional[pd.DataFrame] = None,
    role_metrics_df: Optional[pd.DataFrame] = None,
    recent_days: int = 140,
    min_rotation_games: int = 6,
    min_rotation_avg_min: float = 8.0,
    min_pattern_games: int = 3,
    keep_zero_weights: bool = False,
) -> pd.DataFrame:
    """
    Generate a fresh v2 share matrix from gamelogs + the active IAEL snapshot.
    """
    if iael_df is None:
        iael_df = load_iael_snapshot()
    return _build_share_matrix_v2_impl(
        gamelogs,
        iael_df=iael_df,
        role_metrics_df=role_metrics_df,
        recent_days=recent_days,
        min_rotation_games=min_rotation_games,
        min_rotation_avg_min=min_rotation_avg_min,
        min_pattern_games=min_pattern_games,
        keep_zero_weights=keep_zero_weights,
    )


def build_and_write_share_matrix_v2(
    gamelogs: pd.DataFrame,
    out_path: str | Path,
    *,
    iael_df: Optional[pd.DataFrame] = None,
    role_metrics_df: Optional[pd.DataFrame] = None,
    recent_days: int = 140,
    min_rotation_games: int = 6,
    min_rotation_avg_min: float = 8.0,
    min_pattern_games: int = 3,
    keep_zero_weights: bool = False,
) -> Path:
    mat = generate_share_matrix_v2(
        gamelogs,
        iael_df=iael_df,
        role_metrics_df=role_metrics_df,
        recent_days=recent_days,
        min_rotation_games=min_rotation_games,
        min_rotation_avg_min=min_rotation_avg_min,
        min_pattern_games=min_pattern_games,
        keep_zero_weights=keep_zero_weights,
    )
    return emit_share_matrix_csv(mat, out_path)

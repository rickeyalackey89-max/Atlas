from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

REQUIRED_COLUMNS = ("team", "out_player", "beneficiary_player", "stat", "games", "weight")
OPTIONAL_COLUMNS = (
    "team_u",
    "stat_u",
    "out_canon",
    "ben_canon",
)


@dataclass(frozen=True)
class ShareMatrixValidationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_share_matrix_df(df: pd.DataFrame) -> ShareMatrixValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if df is None or not isinstance(df, pd.DataFrame):
        return ShareMatrixValidationResult(False, ("share_matrix is not a dataframe",), ())

    if df.empty:
        return ShareMatrixValidationResult(False, ("share_matrix is empty",), ())

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        errors.append(f"missing required columns: {missing}")

    if "weight" in df.columns:
        weights = pd.to_numeric(df["weight"], errors="coerce")
        if weights.isna().any():
            warnings.append("weight has non-numeric values")
        if (weights < 0).any():
            errors.append("weight contains negative values")
        if float(weights.fillna(0.0).abs().sum()) <= 0.0:
            errors.append("weight sums to zero")

    if "games" in df.columns:
        games = pd.to_numeric(df["games"], errors="coerce")
        if games.isna().any():
            warnings.append("games has non-numeric values")
        if (games < 0).any():
            errors.append("games contains negative values")

    if not errors:
        # Validate the most important grouping key is not degenerate.
        group_cols = [col for col in ("team", "out_player", "beneficiary_player", "stat") if col in df.columns]
        if group_cols:
            dupes = df.duplicated(subset=group_cols, keep=False)
            if dupes.any():
                warnings.append("duplicate share-matrix rows detected for at least one key")

    return ShareMatrixValidationResult(not errors, tuple(errors), tuple(warnings))


def require_valid_share_matrix(df: pd.DataFrame) -> None:
    result = validate_share_matrix_df(df)
    if not result.ok:
        raise ValueError("share_matrix validation failed: " + "; ".join(result.errors))

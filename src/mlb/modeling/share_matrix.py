"""MLB share-matrix skeleton.

The NBA share matrix was removed. This module defines the baseball-specific
surface we will fill in as source data becomes available.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShareMatrixSignals:
    lineup_probability: float | None = None
    batting_order_slot: int | None = None
    plate_appearance_projection: float | None = None
    platoon_risk: float | None = None
    injury_replacement_risk: float | None = None
    pitcher_role_stability: float | None = None
    bullpen_fatigue: float | None = None


def empty_share_matrix_signal() -> ShareMatrixSignals:
    return ShareMatrixSignals()

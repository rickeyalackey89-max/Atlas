from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BuiltSlips:
    sys3: pd.DataFrame
    sys4: pd.DataFrame
    sys5: pd.DataFrame
    wind3: pd.DataFrame
    wind4: pd.DataFrame
    wind5: pd.DataFrame


def run_build_slips(
    scored_for_optimizer: pd.DataFrame,
    top_n: int,
    seed: int,
    *,
    pricing_engine: str,
    cfg: dict[str, Any],
    sort_mode: str = "ev",
) -> BuiltSlips:
    """
    Deterministic Optimize Stage.

    Builds SYSTEM + WINDFALL slips (no IO).
    Must preserve legacy behavior 1:1.

    IMPORTANT: imports are inside the function to avoid circular import with LegacyEngine.main.
    """
    # Local import to break circular dependency:
    # legacy.main imports this stage, so this stage must NOT import legacy.main at module import time.
    from Atlas.core.slip_builders import build_system_slips, build_windfall_slips, expand_legs

    # SYSTEM
    sys3 = expand_legs(
        build_system_slips(scored_for_optimizer, 3, top_n, seed, pricing_engine=pricing_engine, cfg=cfg, sort_mode=sort_mode), 3
    )
    sys4 = expand_legs(
        build_system_slips(scored_for_optimizer, 4, top_n, seed, pricing_engine=pricing_engine, cfg=cfg, sort_mode=sort_mode), 4
    )
    sys5 = expand_legs(
        build_system_slips(scored_for_optimizer, 5, top_n, seed, pricing_engine=pricing_engine, cfg=cfg, sort_mode=sort_mode), 5
    )

    # WINDFALL
    wind3 = expand_legs(
        build_windfall_slips(scored_for_optimizer, 3, top_n, seed, pricing_engine=pricing_engine, cfg=cfg, sort_mode=sort_mode), 3
    )
    wind4 = expand_legs(
        build_windfall_slips(scored_for_optimizer, 4, top_n, seed, pricing_engine=pricing_engine, cfg=cfg, sort_mode=sort_mode), 4
    )
    wind5 = expand_legs(
        build_windfall_slips(scored_for_optimizer, 5, top_n, seed, pricing_engine=pricing_engine, cfg=cfg, sort_mode=sort_mode), 5
    )

    return BuiltSlips(sys3=sys3, sys4=sys4, sys5=sys5, wind3=wind3, wind4=wind4, wind5=wind5)

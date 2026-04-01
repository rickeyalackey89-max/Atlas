from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass(frozen=True)
class BuiltSlips:
    sys3: pd.DataFrame
    sys4: pd.DataFrame
    sys5: pd.DataFrame
    wind3: pd.DataFrame
    wind4: pd.DataFrame
    wind5: pd.DataFrame
    demonhunter: Optional[pd.DataFrame] = None

def _merge_cfg_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            nested = dict(out.get(key) or {})
            nested.update(value)
            out[key] = nested
        else:
            out[key] = value
    return out


def _leg_override_value(mapping: Any, n_legs: int) -> Any:
    if not isinstance(mapping, dict):
        return None
    if n_legs in mapping:
        return mapping[n_legs]
    key = str(n_legs)
    if key in mapping:
        return mapping[key]
    return None


def _cfg_for_n_legs(cfg: dict[str, Any], n_legs: int, default_top_n: int, sort_mode: str = "ev") -> tuple[dict[str, Any], int]:
    if not isinstance(cfg, dict):
        return {}, int(default_top_n)

    out_cfg = dict(cfg)

    sort_keys = [str(sort_mode or "").strip().lower()]
    if "hit" in sort_keys and "winprob" not in sort_keys:
        sort_keys.append("winprob")

    slip_rank_cfg = dict((cfg.get("slip_rank", {}) or {}))
    slip_rank_by_sort = slip_rank_cfg.get("by_sort_mode")
    if isinstance(slip_rank_by_sort, dict):
        for sort_key in sort_keys:
            sort_override = slip_rank_by_sort.get(sort_key)
            if isinstance(sort_override, dict):
                slip_rank_cfg = _merge_cfg_dict(slip_rank_cfg, sort_override)
    out_cfg["slip_rank"] = slip_rank_cfg

    slip_build_cfg = dict((cfg.get("slip_build", {}) or {}))

    by_sort_mode = slip_build_cfg.get("by_sort_mode")
    if isinstance(by_sort_mode, dict):
        for sort_key in sort_keys:
            sort_override = by_sort_mode.get(sort_key)
            if isinstance(sort_override, dict):
                slip_build_cfg = _merge_cfg_dict(slip_build_cfg, sort_override)

    slip_build_overrides = _leg_override_value(slip_build_cfg.get("by_legs") or slip_build_cfg.get("per_leg"), n_legs)
    if isinstance(slip_build_overrides, dict):
        slip_build_cfg = _merge_cfg_dict(slip_build_cfg, slip_build_overrides)
    out_cfg["slip_build"] = slip_build_cfg

    optimizer_cfg = dict((cfg.get("optimizer", {}) or {}))
    top_n = int(default_top_n)
    sort_override_applied = False
    per_sort_top_n = optimizer_cfg.get("top_n_slips_by_legs_by_sort_mode")
    if isinstance(per_sort_top_n, dict):
        for sort_key in sort_keys:
            top_n_override = _leg_override_value(per_sort_top_n.get(sort_key), n_legs)
            if top_n_override is not None:
                top_n = int(top_n_override)
                sort_override_applied = True
                break
    if not sort_override_applied:
        top_n_override = _leg_override_value(optimizer_cfg.get("top_n_slips_by_legs") or optimizer_cfg.get("top_n_by_legs"), n_legs)
        if top_n_override is not None:
            top_n = int(top_n_override)
    optimizer_cfg["top_n_slips"] = top_n
    out_cfg["optimizer"] = optimizer_cfg

    return out_cfg, top_n


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
    from Atlas.core.slip_builders import build_system_slips, build_windfall_slips, build_demonhunter_slips, expand_legs

    cfg3, top_n3 = _cfg_for_n_legs(cfg, 3, top_n, sort_mode)
    cfg4, top_n4 = _cfg_for_n_legs(cfg, 4, top_n, sort_mode)
    cfg5, top_n5 = _cfg_for_n_legs(cfg, 5, top_n, sort_mode)

    # SYSTEM
    sys3 = expand_legs(
        build_system_slips(scored_for_optimizer, 3, top_n3, seed, pricing_engine=pricing_engine, cfg=cfg3, sort_mode=sort_mode), 3
    )
    sys4 = expand_legs(
        build_system_slips(scored_for_optimizer, 4, top_n4, seed, pricing_engine=pricing_engine, cfg=cfg4, sort_mode=sort_mode), 4
    )
    sys5 = expand_legs(
        build_system_slips(scored_for_optimizer, 5, top_n5, seed, pricing_engine=pricing_engine, cfg=cfg5, sort_mode=sort_mode), 5
    )

    # WINDFALL
    wind3 = expand_legs(
        build_windfall_slips(scored_for_optimizer, 3, top_n3, seed, pricing_engine=pricing_engine, cfg=cfg3, sort_mode=sort_mode), 3
    )
    wind4 = expand_legs(
        build_windfall_slips(scored_for_optimizer, 4, top_n4, seed, pricing_engine=pricing_engine, cfg=cfg4, sort_mode=sort_mode), 4
    )
    wind5 = expand_legs(
        build_windfall_slips(scored_for_optimizer, 5, top_n5, seed, pricing_engine=pricing_engine, cfg=cfg5, sort_mode=sort_mode), 5
    )

    # DEMONHUNTER – best single all-DEMON slip at each leg count
    demonhunter = build_demonhunter_slips(
        scored_for_optimizer, seed, pricing_engine=pricing_engine, sort_mode=sort_mode, cfg=cfg,
    )

    return BuiltSlips(sys3=sys3, sys4=sys4, sys5=sys5, wind3=wind3, wind4=wind4, wind5=wind5, demonhunter=demonhunter)

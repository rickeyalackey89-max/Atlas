from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from Atlas.core.slip_family_diversity import prop_keys_from_slip_row


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


def _prop_diversity_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    section = cfg.get("slip_family_prop_diversity", {}) or {}
    return section if isinstance(section, dict) else {}


def _candidate_top_n(top_n: int, cfg: dict[str, Any]) -> int:
    div_cfg = _prop_diversity_cfg(cfg)
    if not bool(div_cfg.get("enabled", False)):
        return int(top_n)
    mult = int(div_cfg.get("candidate_multiplier", 1) or 1)
    floor = int(div_cfg.get("min_candidate_rows", 1) or 1)
    return max(int(top_n), int(top_n) * max(mult, 1), floor)


def _diversify_frames(frames: list[pd.DataFrame], limits: list[int], cfg: dict[str, Any]) -> list[pd.DataFrame]:
    div_cfg = _prop_diversity_cfg(cfg)
    if not bool(div_cfg.get("enabled", False)):
        return [frame.head(limit).reset_index(drop=True) if frame is not None else frame for frame, limit in zip(frames, limits)]

    from Atlas.core.slip_family_diversity import enforce_prop_diversity_across_frames

    max_repeats = int(div_cfg.get("max_repeats_per_family", 1) or 1)
    return enforce_prop_diversity_across_frames(frames, limits=limits, max_repeats=max_repeats)


def _frame_prop_keys(frame: pd.DataFrame | None) -> set[str]:
    keys: set[str] = set()
    if frame is None or frame.empty:
        return keys
    for _, row in frame.iterrows():
        keys.update(prop_keys_from_slip_row(row))
    return keys


def _cfg_with_reserved_prop_keys(cfg: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    if not keys:
        return cfg
    out = dict(cfg)
    sb = dict(out.get("slip_build") or {})
    sb["_reserved_prop_keys"] = sorted(keys)
    out["slip_build"] = sb
    return out


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
    cand_top_n3 = _candidate_top_n(top_n3, cfg)
    cand_top_n4 = _candidate_top_n(top_n4, cfg)
    cand_top_n5 = _candidate_top_n(top_n5, cfg)

    sys_reserved: set[str] = set()
    sys3_raw = expand_legs(
        build_system_slips(scored_for_optimizer, 3, cand_top_n3, seed, pricing_engine=pricing_engine, cfg=cfg3, sort_mode=sort_mode), 3
    )
    sys_reserved.update(_frame_prop_keys(sys3_raw))
    sys4_raw = expand_legs(
        build_system_slips(scored_for_optimizer, 4, cand_top_n4, seed, pricing_engine=pricing_engine, cfg=_cfg_with_reserved_prop_keys(cfg4, sys_reserved), sort_mode=sort_mode), 4
    )
    sys_reserved.update(_frame_prop_keys(sys4_raw))
    sys5_raw = expand_legs(
        build_system_slips(scored_for_optimizer, 5, cand_top_n5, seed, pricing_engine=pricing_engine, cfg=_cfg_with_reserved_prop_keys(cfg5, sys_reserved), sort_mode=sort_mode), 5
    )
    sys3, sys4, sys5 = _diversify_frames([sys3_raw, sys4_raw, sys5_raw], [top_n3, top_n4, top_n5], cfg)

    # WINDFALL — strip System-specific exclusions that starve DEMON-tier legs
    def _windfall_cfg(resolved: dict) -> dict:
        out = dict(resolved)
        sb = dict(out.get("slip_build") or {})
        sb.pop("exclude_stat_directions", None)
        sb.pop("min_edge", None)
        out["slip_build"] = sb
        return out

    wcfg3 = _windfall_cfg(cfg3)
    wcfg4 = _windfall_cfg(cfg4)
    wcfg5 = _windfall_cfg(cfg5)
    wind_reserved: set[str] = set()
    wind3_raw = expand_legs(
        build_windfall_slips(scored_for_optimizer, 3, cand_top_n3, seed, pricing_engine=pricing_engine, cfg=wcfg3, sort_mode=sort_mode), 3
    )
    wind_reserved.update(_frame_prop_keys(wind3_raw))
    wind4_raw = expand_legs(
        build_windfall_slips(scored_for_optimizer, 4, cand_top_n4, seed, pricing_engine=pricing_engine, cfg=_cfg_with_reserved_prop_keys(wcfg4, wind_reserved), sort_mode=sort_mode), 4
    )
    wind_reserved.update(_frame_prop_keys(wind4_raw))
    wind5_raw = expand_legs(
        build_windfall_slips(scored_for_optimizer, 5, cand_top_n5, seed, pricing_engine=pricing_engine, cfg=_cfg_with_reserved_prop_keys(wcfg5, wind_reserved), sort_mode=sort_mode), 5
    )
    wind3, wind4, wind5 = _diversify_frames([wind3_raw, wind4_raw, wind5_raw], [top_n3, top_n4, top_n5], cfg)

    # DEMONHUNTER – best single all-DEMON slip at each leg count
    demonhunter = build_demonhunter_slips(
        scored_for_optimizer, seed, pricing_engine=pricing_engine, sort_mode=sort_mode, cfg=cfg,
    )
    if demonhunter is not None and not demonhunter.empty:
        demonhunter = _diversify_frames([demonhunter], [len(demonhunter)], cfg)[0]

    return BuiltSlips(sys3=sys3, sys4=sys4, sys5=sys5, wind3=wind3, wind4=wind4, wind5=wind5, demonhunter=demonhunter)

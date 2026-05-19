from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from Atlas.core.slip_family_diversity import prop_keys_from_slip_row


@dataclass(frozen=True)
class BuiltSlips:
    sys2: pd.DataFrame
    sys3: pd.DataFrame
    sys4: pd.DataFrame
    sys5: pd.DataFrame
    wind2: pd.DataFrame
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


def _diversify_demonhunter_frame(frame: pd.DataFrame | None, cfg: dict[str, Any]) -> pd.DataFrame | None:
    """Diversify DemonHunter by leg count without suppressing whole outputs.

    DemonHunter is emitted as one combined frame. If we run the generic family
    diversity pass over that combined frame, a strong 2-leg can consume a prop
    key and erase the 3-leg output entirely. Split by n_legs first so each
    target size gets one chance; if exact prop diversity still drops a size,
    preserve the best original row for that size rather than shipping no
    DemonHunter slip for that leg count.
    """

    if frame is None or frame.empty or "n_legs" not in frame.columns:
        return frame

    leg_counts: list[int] = []
    for value in frame["n_legs"].tolist():
        try:
            n_legs = int(value)
        except (TypeError, ValueError):
            continue
        if n_legs not in leg_counts:
            leg_counts.append(n_legs)

    frames = [frame[pd.to_numeric(frame["n_legs"], errors="coerce") == n].head(1).copy() for n in leg_counts]
    diversified = _diversify_frames(frames, [1 for _ in frames], cfg)

    kept: list[pd.DataFrame] = []
    for original, candidate in zip(frames, diversified):
        if candidate is not None and not candidate.empty:
            kept.append(candidate.head(1))
        elif original is not None and not original.empty:
            kept.append(original.head(1))

    if not kept:
        return pd.DataFrame()
    return pd.concat(kept, ignore_index=True)


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


def _empty_slips() -> pd.DataFrame:
    return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"])


def _single_game_build_sizes(scored_for_optimizer: pd.DataFrame, cfg: dict[str, Any]) -> tuple[int, ...] | None:
    if scored_for_optimizer is None or scored_for_optimizer.empty:
        return None
    sg = cfg.get("single_game_mode", {}) if isinstance(cfg, dict) else {}
    if not isinstance(sg, dict):
        return None
    active = False
    if "single_game_slate" in scored_for_optimizer.columns:
        try:
            active = bool(pd.Series(scored_for_optimizer["single_game_slate"]).map(bool).any())
        except Exception:
            active = False
    if not active:
        return None
    raw_sizes = sg.get("build_slip_sizes", [2, 3, 4])
    sizes: list[int] = []
    for value in raw_sizes:
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n in {2, 3, 4, 5} and n not in sizes:
            sizes.append(n)
    return tuple(sizes or [2, 3, 4])


def _max_attempts_for_n_legs(cfg: dict[str, Any], n_legs: int, *, single_game: bool, default: int) -> int:
    sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
    keys = ["max_attempts_by_legs"]
    if single_game:
        keys.insert(0, "single_game_max_attempts_by_legs")
    for key in keys:
        mapping = sb.get(key)
        if not isinstance(mapping, dict):
            continue
        value = _leg_override_value(mapping, n_legs)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    try:
        return max(1, int(sb.get("max_attempts", default) or default))
    except (TypeError, ValueError):
        return int(default)


def _single_game_sort_mode(cfg: dict[str, Any], fallback: str) -> str:
    sg = cfg.get("single_game_mode", {}) if isinstance(cfg, dict) else {}
    raw = sg.get("sort_mode", sg.get("primary_sort_mode", fallback)) if isinstance(sg, dict) else fallback
    mode = str(raw or fallback or "hit").strip().lower()
    if mode in {"win", "winprob", "hit_prob"}:
        return "hit"
    if mode in {"ev", "hit", "hybrid"}:
        return mode
    return str(fallback or "hit").strip().lower() or "hit"


def _apply_single_game_slip_build_overrides(cfg: dict[str, Any], n_legs: int) -> dict[str, Any]:
    sg = cfg.get("single_game_mode", {}) if isinstance(cfg, dict) else {}
    if not isinstance(sg, dict):
        return cfg

    out = dict(cfg)
    sb = dict(out.get("slip_build") or {})

    base_override = sg.get("slip_build_overrides")
    if isinstance(base_override, dict):
        sb = _merge_cfg_dict(sb, base_override)

    by_legs = sg.get("slip_build_overrides_by_legs")
    leg_override = _leg_override_value(by_legs, n_legs)
    if isinstance(leg_override, dict):
        sb = _merge_cfg_dict(sb, leg_override)

    out["slip_build"] = sb
    return out


def _build_family_slip(
    builder,
    scored_for_optimizer: pd.DataFrame,
    n_legs: int,
    top_n: int,
    seed: int,
    *,
    pricing_engine: str,
    cfg: dict[str, Any],
    sort_mode: str,
    reserved: set[str],
    max_attempts: int,
) -> pd.DataFrame:
    from Atlas.core.slip_builders import expand_legs

    return expand_legs(
        builder(
            scored_for_optimizer,
            n_legs,
            top_n,
            seed,
            pricing_engine=pricing_engine,
            cfg=_cfg_with_reserved_prop_keys(cfg, reserved),
            sort_mode=sort_mode,
            max_attempts=max_attempts,
        ),
        n_legs,
    )


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
    from Atlas.core.slip_builders import build_system_slips, build_windfall_slips, build_demonhunter_slips

    single_game_sizes = _single_game_build_sizes(scored_for_optimizer, cfg)
    build_sizes = single_game_sizes or (3, 4, 5)
    single_game_active = single_game_sizes is not None
    effective_sort_mode = _single_game_sort_mode(cfg, sort_mode) if single_game_active else sort_mode
    cfg_by_legs: dict[int, dict[str, Any]] = {}
    top_n_by_legs: dict[int, int] = {}
    cand_top_n_by_legs: dict[int, int] = {}
    for n_legs in build_sizes:
        resolved_cfg, resolved_top_n = _cfg_for_n_legs(cfg, n_legs, top_n, effective_sort_mode)
        if single_game_active:
            resolved_cfg = _apply_single_game_slip_build_overrides(resolved_cfg, n_legs)
        cfg_by_legs[n_legs] = resolved_cfg
        top_n_by_legs[n_legs] = resolved_top_n
        cand_top_n_by_legs[n_legs] = _candidate_top_n(resolved_top_n, cfg)

    # SYSTEM
    sys_reserved: set[str] = set()
    sys_raw_by_legs: dict[int, pd.DataFrame] = {}
    for n_legs in build_sizes:
        raw = _build_family_slip(
            build_system_slips,
            scored_for_optimizer,
            n_legs,
            cand_top_n_by_legs[n_legs],
            seed,
            pricing_engine=pricing_engine,
            cfg=cfg_by_legs[n_legs],
            sort_mode=effective_sort_mode,
            reserved=sys_reserved,
            max_attempts=_max_attempts_for_n_legs(cfg_by_legs[n_legs], n_legs, single_game=single_game_active, default=500000),
        )
        sys_raw_by_legs[n_legs] = raw
        sys_reserved.update(_frame_prop_keys(raw))
    sys_frames = [sys_raw_by_legs[n] for n in build_sizes]
    sys_limits = [cand_top_n_by_legs[n] for n in build_sizes]
    sys_diversified = _diversify_frames(sys_frames, sys_limits, cfg)
    sys_by_legs = {n: frame for n, frame in zip(build_sizes, sys_diversified)}

    # WINDFALL — strip System-specific exclusions that starve DEMON-tier legs
    def _windfall_cfg(resolved: dict) -> dict:
        out = dict(resolved)
        sb = dict(out.get("slip_build") or {})
        sb.pop("exclude_stat_directions", None)
        sb.pop("min_edge", None)
        out["slip_build"] = sb
        return out

    wind_reserved: set[str] = set()
    wind_raw_by_legs: dict[int, pd.DataFrame] = {}
    for n_legs in build_sizes:
        raw = _build_family_slip(
            build_windfall_slips,
            scored_for_optimizer,
            n_legs,
            cand_top_n_by_legs[n_legs],
            seed,
            pricing_engine=pricing_engine,
            cfg=_windfall_cfg(cfg_by_legs[n_legs]),
            sort_mode=effective_sort_mode,
            reserved=wind_reserved,
            max_attempts=_max_attempts_for_n_legs(cfg_by_legs[n_legs], n_legs, single_game=single_game_active, default=400000),
        )
        wind_raw_by_legs[n_legs] = raw
        wind_reserved.update(_frame_prop_keys(raw))
    wind_frames = [wind_raw_by_legs[n] for n in build_sizes]
    wind_limits = [cand_top_n_by_legs[n] for n in build_sizes]
    wind_diversified = _diversify_frames(wind_frames, wind_limits, cfg)
    wind_by_legs = {n: frame for n, frame in zip(build_sizes, wind_diversified)}

    # DEMONHUNTER – best single all-DEMON slip at each leg count
    demonhunter = build_demonhunter_slips(
        scored_for_optimizer, seed, pricing_engine=pricing_engine, sort_mode=effective_sort_mode, cfg=cfg,
    )
    if demonhunter is not None and not demonhunter.empty:
        demonhunter = _diversify_demonhunter_frame(demonhunter, cfg)

    from Atlas.core.slip_quality_gate import build_slip_consensus_counts, filter_slip_frame

    consensus_counts = build_slip_consensus_counts(
        {
            "System": [sys_by_legs.get(n) for n in build_sizes],
            "Windfall": [wind_by_legs.get(n) for n in build_sizes],
            "DemonHunter": [demonhunter],
        }
    )
    sys_by_legs = {
        n: filter_slip_frame(sys_by_legs.get(n), cfg, family="System", consensus_counts=consensus_counts)
        for n in build_sizes
    }
    wind_by_legs = {
        n: filter_slip_frame(wind_by_legs.get(n), cfg, family="Windfall", consensus_counts=consensus_counts)
        for n in build_sizes
    }
    demonhunter = filter_slip_frame(demonhunter, cfg, family="DemonHunter", consensus_counts=consensus_counts)

    return BuiltSlips(
        sys2=sys_by_legs.get(2, _empty_slips()),
        sys3=sys_by_legs.get(3, _empty_slips()),
        sys4=sys_by_legs.get(4, _empty_slips()),
        sys5=sys_by_legs.get(5, _empty_slips()),
        wind2=wind_by_legs.get(2, _empty_slips()),
        wind3=wind_by_legs.get(3, _empty_slips()),
        wind4=wind_by_legs.get(4, _empty_slips()),
        wind5=wind_by_legs.get(5, _empty_slips()),
        demonhunter=demonhunter,
    )

from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd


_LEG_PART_RE = re.compile(
    r"^(?P<player>.*?)\s+(?P<direction>OVER|UNDER)\s+(?P<stat>[A-Z0-9+]+)\s+"
    r"(?P<line>-?\d+(?:\.\d+)?)\s+\((?P<tier>[^)]+)\)",
    re.IGNORECASE,
)


def infer_slate_game_count(source: pd.DataFrame | None) -> int | None:
    if source is None or source.empty:
        return None
    if "single_game_games" in source.columns:
        vals = pd.to_numeric(source["single_game_games"], errors="coerce").dropna()
        if not vals.empty:
            return int(vals.mode().iloc[0])
    if "game_id" in source.columns:
        vals = source["game_id"].dropna().astype(str)
        vals = vals[vals.str.strip() != ""]
        if not vals.empty:
            return int(vals.nunique())
    return None


def composition_drop_reason_for_item(
    item: Mapping[str, Any],
    cfg_or_section: Mapping[str, Any] | None,
    slate_games: int | None,
) -> str:
    n_legs = int(_float(item.get("n_legs"), 0) or 0)
    leg_parts = item.get("leg_parts", [])
    if not isinstance(leg_parts, list):
        leg_parts = []
    return composition_drop_reason_for_leg_parts(
        leg_parts,
        cfg_or_section,
        slate_games=slate_games,
        n_legs=n_legs,
    )


def composition_drop_reason_for_legs(
    legs: list[Any] | tuple[Any, ...],
    cfg_or_section: Mapping[str, Any] | None,
    *,
    slate_games: int | None,
    n_legs: int,
) -> str:
    return composition_drop_reason_for_leg_parts(
        leg_parts_from_legs(legs),
        cfg_or_section,
        slate_games=slate_games,
        n_legs=n_legs,
    )


def composition_drop_reason_for_leg_parts(
    leg_parts: list[dict[str, Any]],
    cfg_or_section: Mapping[str, Any] | None,
    *,
    slate_games: int | None,
    n_legs: int,
) -> str:
    section = _section(cfg_or_section)
    policy = section.get("two_game_4_5_composition", {})
    if not isinstance(policy, Mapping) or not bool(policy.get("enabled", False)):
        return ""

    apply_slate_games = policy.get("apply_to_slate_games", 2)
    if slate_games != int(_float(apply_slate_games, 2)):
        return ""

    apply_to_legs = policy.get("apply_to_legs", [4, 5])
    try:
        allowed_legs = {int(x) for x in apply_to_legs}
    except TypeError:
        allowed_legs = {4, 5}
    if int(n_legs) not in allowed_legs:
        return ""

    if not leg_parts:
        return ""

    stat_counts: dict[str, int] = {}
    for leg in leg_parts:
        stat = str(leg.get("stat", "") if isinstance(leg, Mapping) else "").strip().upper()
        if stat:
            stat_counts[stat] = stat_counts.get(stat, 0) + 1

    max_stat_counts = _by_legs(policy.get("max_stat_counts_by_legs"), int(n_legs))
    if isinstance(max_stat_counts, Mapping):
        for stat, limit in max_stat_counts.items():
            stat_s = str(stat).strip().upper()
            limit_i = int(_float(limit, 0))
            if stat_s and stat_counts.get(stat_s, 0) > limit_i:
                return f"two_game_composition_{stat_s.lower()}_count_gt_{limit_i}"

    max_same_stat = _by_legs(policy.get("max_same_stat_by_legs"), int(n_legs))
    if max_same_stat is not None and stat_counts:
        limit = int(_float(max_same_stat, 0))
        if max(stat_counts.values()) > limit:
            return f"two_game_composition_same_stat_count_gt_{limit}"

    return ""


def leg_parts_from_slip_row(row: pd.Series) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    legs = str(row.get("legs", "") or "")
    if legs:
        for part in legs.split(" | "):
            parsed = leg_part_from_text(part)
            if parsed:
                parts.append(parsed)
    if parts:
        return parts
    for i in range(1, 6):
        parsed = leg_part_from_text(row.get(f"leg_{i}", ""))
        if parsed:
            parts.append(parsed)
    return parts


def leg_parts_from_marketed_slip(slip: Mapping[str, Any]) -> list[dict[str, Any]]:
    return leg_parts_from_legs(list(slip.get("legs", []) or []))


def leg_parts_from_legs(legs: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for leg in legs:
        if not hasattr(leg, "get"):
            parsed = leg_part_from_text(leg)
            if parsed:
                parts.append(parsed)
            continue
        part = {
            "player": str(leg.get("player", "")).strip(),
            "direction": str(leg.get("direction", "")).strip().upper(),
            "stat": str(leg.get("stat", leg.get("stat_type", ""))).strip().upper(),
            "line": leg.get("line", ""),
            "tier": str(leg.get("tier", "")).strip().upper(),
        }
        if part.get("stat"):
            parts.append(part)
    return parts


def leg_part_from_text(text: Any) -> dict[str, Any]:
    match = _LEG_PART_RE.match(str(text or "").strip())
    if not match:
        return {}
    return {
        "player": match.group("player").strip(),
        "direction": match.group("direction").strip().upper(),
        "stat": match.group("stat").strip().upper(),
        "line": match.group("line").strip(),
        "tier": match.group("tier").strip().upper(),
    }


def _section(cfg_or_section: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cfg_or_section, Mapping):
        return {}
    nested = cfg_or_section.get("public_slip_quality")
    if isinstance(nested, dict):
        return nested
    return dict(cfg_or_section)


def _by_legs(mapping: Any, n_legs: int) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    if n_legs in mapping:
        return mapping[n_legs]
    key = str(int(n_legs))
    return mapping.get(key)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:
        return default
    return out

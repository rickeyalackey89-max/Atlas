from __future__ import annotations

import re
from typing import Any

import pandas as pd


_LEG_RE = re.compile(
    r"^(?P<player>.*?)\s+(?P<direction>OVER|UNDER)\s+(?P<stat>[A-Z0-9+]+)\s+(?P<line>-?\d+(?:\.\d+)?)\s+\(",
    re.IGNORECASE,
)


def prop_key_from_values(player: Any, direction: Any, stat: Any, line: Any) -> str:
    player_s = " ".join(str(player or "").strip().lower().split())
    direction_s = str(direction or "").strip().upper()
    stat_s = str(stat or "").strip().upper()
    try:
        line_s = f"{float(line):g}"
    except Exception:
        line_s = str(line or "").strip()
    if not player_s or not direction_s or not stat_s or not line_s:
        return ""
    return f"{player_s}|{direction_s}|{stat_s}|{line_s}"


def prop_key_from_leg_text(text: Any) -> str:
    match = _LEG_RE.match(str(text or "").strip())
    if not match:
        return ""
    return prop_key_from_values(
        match.group("player"),
        match.group("direction"),
        match.group("stat"),
        match.group("line"),
    )


def prop_key_from_mapping(leg: Any) -> str:
    getter = leg.get if hasattr(leg, "get") else lambda _key, _default=None: _default
    return prop_key_from_values(
        getter("player", ""),
        getter("direction", ""),
        getter("stat", getter("stat_type", "")),
        getter("line", ""),
    )


def prop_keys_from_slip_row(row: pd.Series) -> set[str]:
    keys: set[str] = set()
    legs = str(row.get("legs", "") or "")
    if legs:
        for part in legs.split(" | "):
            key = prop_key_from_leg_text(part)
            if key:
                keys.add(key)
    if keys:
        return keys
    for i in range(1, 6):
        key = prop_key_from_leg_text(row.get(f"leg_{i}", ""))
        if key:
            keys.add(key)
    return keys


def prop_keys_from_marketed_slip(slip: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for leg in slip.get("legs", []) or []:
        key = prop_key_from_mapping(leg)
        if key:
            keys.add(key)
    return keys


def enforce_prop_diversity_across_frames(
    frames: list[pd.DataFrame],
    *,
    limits: list[int] | None = None,
    max_repeats: int = 1,
) -> list[pd.DataFrame]:
    """Reserve exact player/direction/stat/line props across a slip family.

    Frames must be passed in priority order, normally 3-leg, 4-leg, 5-leg.
    """

    counts: dict[str, int] = {}
    out_frames: list[pd.DataFrame] = []
    limits = limits or [len(frame) for frame in frames]

    for frame, limit in zip(frames, limits):
        if frame is None or frame.empty:
            out_frames.append(frame)
            continue

        kept_indices: list[Any] = []
        for idx, row in frame.iterrows():
            keys = prop_keys_from_slip_row(row)
            if any(counts.get(key, 0) >= int(max_repeats) for key in keys):
                continue
            kept_indices.append(idx)
            for key in keys:
                counts[key] = counts.get(key, 0) + 1
            if len(kept_indices) >= int(limit):
                break

        out_frames.append(frame.loc[kept_indices].reset_index(drop=True))

    return out_frames


def enforce_prop_diversity_across_marketed_slips(
    slips: list[dict[str, Any]],
    *,
    max_repeats: int = 1,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for slip in slips or []:
        keys = prop_keys_from_marketed_slip(slip)
        if any(counts.get(key, 0) >= int(max_repeats) for key in keys):
            continue
        kept.append(slip)
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return kept

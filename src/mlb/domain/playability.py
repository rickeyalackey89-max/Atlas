"""Playable side rules for MLB pick'em projections."""

from __future__ import annotations

from typing import Any

CANONICAL_TIERS = {"GOBLIN", "STANDARD", "DEMON"}

TIER_PLAYABLE_SIDE_FILTERS: dict[str, tuple[str, ...]] = {
    "GOBLIN": ("OVER",),
    "STANDARD": ("OVER", "UNDER"),
    "DEMON": ("OVER",),
}


def normalize_tier(value: Any) -> str:
    tier = str(value or "STANDARD").strip().upper()
    return tier if tier in CANONICAL_TIERS else "STANDARD"


def normalize_side(value: Any) -> str:
    return str(value or "").strip().upper()


def playable_sides_for_tier(value: Any) -> tuple[str, ...]:
    return TIER_PLAYABLE_SIDE_FILTERS.get(normalize_tier(value), ("OVER", "UNDER"))


def is_playable_side(*, tier: Any, side: Any) -> bool:
    return normalize_side(side) in playable_sides_for_tier(tier)


def is_over_only_tier(value: Any) -> bool:
    return playable_sides_for_tier(value) == ("OVER",)

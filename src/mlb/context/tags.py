"""Baseball-first context tag registry for MLB legs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagDefinition:
    name: str
    group: str
    severity: str
    description: str


TAG_REGISTRY: dict[str, TagDefinition] = {
    "confirmed_lineup": TagDefinition(
        "confirmed_lineup",
        "opportunity",
        "info",
        "Hitter is tied to a confirmed lineup slot.",
    ),
    "projected_lineup": TagDefinition(
        "projected_lineup",
        "opportunity",
        "caution",
        "Hitter lineup context exists but is not confirmed.",
    ),
    "unknown_lineup": TagDefinition(
        "unknown_lineup",
        "opportunity",
        "suppress",
        "Hitter lineup status is unknown.",
    ),
    "top_order_volume": TagDefinition(
        "top_order_volume",
        "opportunity",
        "info",
        "Hitter is in a high plate-appearance lineup bucket.",
    ),
    "middle_order_role": TagDefinition(
        "middle_order_role",
        "opportunity",
        "info",
        "Hitter has run-production lineup role context.",
    ),
    "bottom_order_volume_risk": TagDefinition(
        "bottom_order_volume_risk",
        "opportunity",
        "caution",
        "Hitter is in a lower lineup bucket for a volume-dependent prop.",
    ),
    "probable_starter_confirmed": TagDefinition(
        "probable_starter_confirmed",
        "opportunity",
        "info",
        "Pitcher starter context is confirmed enough for passive publication review.",
    ),
    "unknown_starter_status": TagDefinition(
        "unknown_starter_status",
        "opportunity",
        "suppress",
        "Pitcher prop lacks confirmed starter/probable-pitcher context.",
    ),
    "pitcher_workload_market": TagDefinition(
        "pitcher_workload_market",
        "opportunity",
        "caution",
        "Pitcher prop depends on workload, leash, efficiency, and weather continuity.",
    ),
    "high_variance_prop": TagDefinition(
        "high_variance_prop",
        "prop_family",
        "caution",
        "Prop family is volatile and should not be treated as a stable anchor by default.",
    ),
    "line_only_market_context": TagDefinition(
        "line_only_market_context",
        "market",
        "caution",
        "The row has line context but no strong external market price context.",
    ),
    "matchup_context_available": TagDefinition(
        "matchup_context_available",
        "matchup",
        "info",
        "Matchup context is attached to the leg.",
    ),
    "missing_matchup_context": TagDefinition(
        "missing_matchup_context",
        "matchup",
        "caution",
        "Matchup context is missing for a baseball-dependent leg.",
    ),
    "park_weather_context_available": TagDefinition(
        "park_weather_context_available",
        "environment",
        "info",
        "Park/weather context is attached to the leg.",
    ),
    "missing_weather_context": TagDefinition(
        "missing_weather_context",
        "environment",
        "caution",
        "Weather or park context is missing for an environment-sensitive prop.",
    ),
    "hostile_power_environment": TagDefinition(
        "hostile_power_environment",
        "environment",
        "caution",
        "Environment score is unfavorable for a power or extra-base prop.",
    ),
    "weather_delay_workload_risk": TagDefinition(
        "weather_delay_workload_risk",
        "environment",
        "suppress",
        "Weather delay risk can break pitcher workload props.",
    ),
    "feature_context_missing": TagDefinition(
        "feature_context_missing",
        "source",
        "caution",
        "Scored row was not joined to the runtime feature table.",
    ),
    "identity_incomplete": TagDefinition(
        "identity_incomplete",
        "source",
        "suppress",
        "Required player/stat/line/side identity is incomplete.",
    ),
}


def tag_definition(name: str) -> TagDefinition | None:
    return TAG_REGISTRY.get(name)


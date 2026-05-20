"""Atlas-style slip writer for MLB runs."""

from __future__ import annotations

import copy
import csv
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.prizepicks_quote import (
    fallback_power_multiplier,
    load_quote_manifest,
    normalize_quote_picks,
    quote_cache_key,
    quote_prizepicks_payout,
    write_quote_manifest,
)
from core.prizepicks_payout_formula import (
    payout_formula_audit_row,
    write_payout_formula_audit,
)
from mlb.runtime.config import active_mlb_config_manifest
from mlb.domain.playability import (
    TIER_PLAYABLE_SIDE_FILTERS,
    is_playable_side,
    normalize_side,
    normalize_tier,
)
from mlb.domain.slips import supported_slip_families

SYSTEM_FULL_SLATE_SIZES = (3, 4, 5)
WINDFALL_FULL_SLATE_SIZES = (3, 4, 5)
SYSTEM_SINGLE_GAME_SIZES = (2, 3, 4)
WINDFALL_SINGLE_GAME_SIZES = (2, 3, 4)
PUBLIC_SIZED_SLIP_COUNTS = (2, 3, 4, 5)
DEMONHUNTER_SIZES = (3, 4, 5)
PAYOUT_QUOTE_MANIFEST_NAME = "payout_quote_manifest.json"
PAYOUT_FORMULA_AUDIT_NAME = "payout_formula_audit.json"
PUBLIC_SLIP_RANKER_VERSION = "atlas_mlb_public_slip_ranker_v18_market_source_context"
FEATURE_CONTEXT_FIELDS = (
    "market_group",
    "matchup_context_available",
    "lineup_context_available",
    "probable_pitcher_context_available",
    "player_history_context_available",
    "history_games_season",
    "history_games_14d",
    "history_games_7d",
    "plate_appearance_projection",
    "projected_opportunity",
    "weather_context_available",
    "advanced_context_available",
    "injury_context_available",
    "external_market_context_available",
    "market_context_source_type",
    "external_market_context_source",
    "prizepicks_line_only_market_context",
)
TIER_ORDER = ("GOBLIN", "STANDARD", "DEMON")
PUBLIC_PORTFOLIO_PRIORITY = ("Marketed", "System", "Windfall", "DemonHunter")
PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS = 1
PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS = 1
PUBLIC_MAX_SAME_MARKET_PER_SLIP = 2
PUBLIC_MAX_PITCHER_WORKLOAD_LEGS_PER_SLIP = 1
PUBLIC_TIER_DIRECTION_FILTERS = {tier: set(sides) for tier, sides in TIER_PLAYABLE_SIDE_FILTERS.items()}
PUBLIC_EXCLUDED_MARKETS = {
    "1st_inning_runs_allowed",
    "1st_inning_walks_allowed",
}
PUBLIC_PITCHER_WORKLOAD_MARKETS = {
    "earned_runs_allowed",
    "hits_allowed",
    "pitcher_fantasy_score",
    "pitcher_strikeouts",
    "pitches_thrown",
    "pitching_outs",
    "walks_allowed",
}
PUBLIC_BATTER_MARKETS = {
    "doubles",
    "hits",
    "hits_runs_rbis",
    "hitter_fantasy_score",
    "hitter_strikeouts",
    "home_runs",
    "plate_appearances",
    "rbis",
    "runs",
    "singles",
    "stolen_bases",
    "total_bases",
    "triples",
    "walks",
}
PUBLIC_BLOCKED_SEGMENTS = {
    ("DEMON", "hitter_strikeouts", "OVER"),
    ("STANDARD", "hitter_strikeouts", "UNDER"),
    ("STANDARD", "pitcher_fantasy_score", "OVER"),
    ("STANDARD", "pitcher_fantasy_score", "UNDER"),
    ("STANDARD", "pitches_thrown", "UNDER"),
    ("STANDARD", "walks", "UNDER"),
}
PUBLIC_STANDARD_PRIOR_FLOOR = 0.505
BETTINGPROS_CONTEXT_FIELDS = (
    "bettingpros_recommended_side",
    "bettingpros_projection_value",
    "bettingpros_projection_probability",
    "bettingpros_projection_expected_value",
    "bettingpros_projection_diff",
    "bettingpros_streak",
    "bettingpros_streak_type",
    "bettingpros_last_5_over_rate",
    "bettingpros_last_5_under_rate",
    "bettingpros_last_10_over_rate",
    "bettingpros_last_10_under_rate",
    "bettingpros_last_20_over_rate",
    "bettingpros_last_20_under_rate",
    "bettingpros_season_over_rate",
    "bettingpros_season_under_rate",
    "bettingpros_prior_season_over_rate",
    "bettingpros_prior_season_under_rate",
)
PROP_MARKET_IDENTIFIERS = {
    "pitching_outs": 1,
    "pitcher_fantasy_score": 2,
    "hitter_fantasy_score": 3,
    "pitches_thrown": 4,
    "walks_allowed": 5,
    "pitcher_strikeouts": 6,
    "earned_runs_allowed": 7,
    "hits_allowed": 8,
    "hitter_strikeouts": 9,
    "hits": 10,
    "hits_runs_rbis": 11,
    "singles": 12,
    "plate_appearances": 13,
    "walks": 14,
    "total_bases": 15,
    "runs": 16,
    "rbis": 17,
    "doubles": 18,
    "home_runs": 19,
    "stolen_bases": 20,
}


@dataclass(frozen=True)
class _FamilyBuilderPolicy:
    name: str
    purpose: str
    probability_weight: float
    prior_weight: float
    bettingpros_weight: float
    stability_weight: float
    fragility_weight: float
    edge_weight: float
    prop_identifier_weight: float
    tier_bonus: dict[str, float]
    market_bonus: dict[str, float]
    market_penalty: dict[str, float]
    segment_bonus: dict[tuple[str, str], float]
    segment_penalty: dict[tuple[str, str], float]
    min_probability_by_tier: dict[str, float]
    min_edge: float = 0.0


FAMILY_BUILDER_POLICIES: dict[str, _FamilyBuilderPolicy] = {
    "Marketed": _FamilyBuilderPolicy(
        name="Marketed",
        purpose="premium_public_picks",
        probability_weight=0.47,
        prior_weight=0.19,
        bettingpros_weight=0.05,
        stability_weight=0.10,
        fragility_weight=0.07,
        edge_weight=0.13,
        prop_identifier_weight=0.02,
        tier_bonus={"GOBLIN": 0.06, "STANDARD": 0.03, "DEMON": -0.02},
        market_bonus={
            "hitter_fantasy_score": 0.10,
            "total_bases": 0.05,
            "singles": 0.04,
            "runs": 0.03,
            "pitcher_strikeouts": 0.03,
            "plate_appearances": 0.02,
            "hits": 0.02,
        },
        market_penalty={
            "pitches_thrown": 0.12,
            "pitcher_fantasy_score": 0.08,
            "hits_allowed": 0.07,
            "walks_allowed": 0.03,
        },
        segment_bonus={
            ("STANDARD", "pitcher_strikeouts"): 0.05,
            ("STANDARD", "pitching_outs"): 0.05,
            ("DEMON", "singles"): 0.04,
            ("DEMON", "hits_runs_rbis"): 0.03,
        },
        segment_penalty={
            ("DEMON", "pitcher_strikeouts"): 0.10,
            ("DEMON", "pitching_outs"): 0.10,
            ("DEMON", "pitcher_fantasy_score"): 0.12,
        },
        min_probability_by_tier={"GOBLIN": 0.67, "STANDARD": 0.61, "DEMON": 0.60},
        min_edge=0.03,
    ),
    "System": _FamilyBuilderPolicy(
        name="System",
        purpose="atlas_value_ev",
        probability_weight=0.35,
        prior_weight=0.39,
        bettingpros_weight=0.05,
        stability_weight=0.09,
        fragility_weight=0.06,
        edge_weight=0.11,
        prop_identifier_weight=0.02,
        tier_bonus={"GOBLIN": 0.04, "STANDARD": 0.02, "DEMON": -0.10},
        market_bonus={
            "hitter_fantasy_score": 0.07,
            "pitching_outs": 0.04,
            "pitcher_strikeouts": 0.03,
            "total_bases": 0.03,
            "hits_runs_rbis": 0.03,
            "plate_appearances": 0.02,
        },
        market_penalty={
            "pitches_thrown": 0.08,
            "pitcher_fantasy_score": 0.04,
            "hits_allowed": 0.03,
        },
        segment_bonus={
            ("GOBLIN", "pitching_outs"): 0.03,
        },
        segment_penalty={
            ("STANDARD", "plate_appearances"): 0.05,
            ("STANDARD", "hits"): 0.04,
            ("STANDARD", "hits_allowed"): 0.06,
        },
        min_probability_by_tier={"GOBLIN": 0.63, "STANDARD": 0.58, "DEMON": 0.61},
        min_edge=0.01,
    ),
    "Windfall": _FamilyBuilderPolicy(
        name="Windfall",
        purpose="flex_upside_best_of_both_worlds",
        probability_weight=0.34,
        prior_weight=0.25,
        bettingpros_weight=0.08,
        stability_weight=0.08,
        fragility_weight=0.05,
        edge_weight=0.13,
        prop_identifier_weight=0.02,
        tier_bonus={"DEMON": 0.08, "GOBLIN": 0.04, "STANDARD": 0.02},
        market_bonus={
            "total_bases": 0.06,
            "singles": 0.06,
            "hitter_fantasy_score": 0.04,
            "runs": 0.04,
            "pitcher_strikeouts": 0.04,
            "earned_runs_allowed": 0.03,
        },
        market_penalty={
            "pitches_thrown": 0.04,
            "pitcher_fantasy_score": 0.03,
            "hits_allowed": 0.02,
        },
        segment_bonus={
            ("DEMON", "runs"): 0.10,
            ("DEMON", "total_bases"): 0.08,
            ("DEMON", "singles"): 0.06,
            ("DEMON", "hits_runs_rbis"): 0.04,
            ("STANDARD", "pitcher_strikeouts"): 0.05,
            ("STANDARD", "earned_runs_allowed"): 0.04,
            ("STANDARD", "hitter_fantasy_score"): 0.03,
        },
        segment_penalty={
            ("STANDARD", "singles"): 0.08,
            ("DEMON", "pitcher_strikeouts"): 0.12,
            ("DEMON", "pitching_outs"): 0.10,
            ("DEMON", "pitcher_fantasy_score"): 0.12,
        },
        min_probability_by_tier={"GOBLIN": 0.60, "STANDARD": 0.55, "DEMON": 0.56},
        min_edge=0.0,
    ),
    "DemonHunter": _FamilyBuilderPolicy(
        name="DemonHunter",
        purpose="high_variance_demon_over_payout",
        probability_weight=0.38,
        prior_weight=0.24,
        bettingpros_weight=0.08,
        stability_weight=0.06,
        fragility_weight=0.03,
        edge_weight=0.13,
        prop_identifier_weight=0.02,
        tier_bonus={"DEMON": 0.20, "GOBLIN": -1.00, "STANDARD": -1.00},
        market_bonus={
            "total_bases": 0.08,
            "singles": 0.08,
            "hits_runs_rbis": 0.06,
            "hitter_fantasy_score": 0.05,
            "pitcher_strikeouts": 0.03,
        },
        market_penalty={
            "pitches_thrown": 0.08,
            "pitcher_fantasy_score": 0.08,
            "hits_allowed": 0.05,
        },
        segment_bonus={
            ("DEMON", "total_bases"): 0.12,
            ("DEMON", "singles"): 0.10,
            ("DEMON", "runs"): 0.08,
            ("DEMON", "hitter_fantasy_score"): 0.06,
        },
        segment_penalty={
            ("DEMON", "hits_runs_rbis"): 0.08,
            ("DEMON", "pitcher_strikeouts"): 0.08,
            ("DEMON", "pitching_outs"): 0.08,
            ("DEMON", "walks_allowed"): 0.08,
        },
        min_probability_by_tier={"DEMON": 0.56},
        min_edge=0.0,
    ),
}

TIER_MARKET_SIDE_PRIORS = {
    ("GOBLIN", "earned_runs_allowed", "OVER"): (0.567901, 162),
    ("GOBLIN", "hitter_fantasy_score", "OVER"): (0.635422, 3574),
    ("GOBLIN", "hitter_strikeouts", "OVER"): (0.633028, 2398),
    ("GOBLIN", "hits", "OVER"): (0.597173, 2830),
    ("GOBLIN", "hits_allowed", "OVER"): (0.667368, 475),
    ("GOBLIN", "hits_runs_rbis", "OVER"): (0.636555, 3797),
    ("GOBLIN", "pitcher_fantasy_score", "OVER"): (0.696970, 297),
    ("GOBLIN", "pitcher_strikeouts", "OVER"): (0.690476, 546),
    ("GOBLIN", "pitches_thrown", "OVER"): (0.730769, 156),
    ("GOBLIN", "pitching_outs", "OVER"): (0.601695, 118),
    ("GOBLIN", "total_bases", "OVER"): (0.598790, 2809),
    ("GOBLIN", "walks_allowed", "OVER"): (0.827160, 81),
    ("STANDARD", "earned_runs_allowed", "UNDER"): (0.505263, 95),
    ("STANDARD", "hits", "OVER"): (0.478088, 251),
    ("STANDARD", "hits_allowed", "OVER"): (0.561404, 57),
    ("STANDARD", "hits_allowed", "UNDER"): (0.583333, 48),
    ("STANDARD", "hits_runs_rbis", "OVER"): (0.477152, 941),
    ("STANDARD", "hitter_fantasy_score", "OVER"): (0.470750, 2188),
    ("STANDARD", "hitter_strikeouts", "OVER"): (0.498462, 325),
    ("STANDARD", "pitcher_fantasy_score", "OVER"): (0.501931, 259),
    ("STANDARD", "pitcher_strikeouts", "OVER"): (0.487273, 275),
    ("STANDARD", "pitcher_strikeouts", "UNDER"): (0.500000, 38),
    ("STANDARD", "pitches_thrown", "UNDER"): (0.453488, 258),
    ("STANDARD", "pitching_outs", "OVER"): (0.544872, 156),
    ("STANDARD", "plate_appearances", "UNDER"): (0.554054, 74),
    ("STANDARD", "runs", "UNDER"): (0.575540, 278),
    ("STANDARD", "singles", "UNDER"): (0.549407, 759),
    ("STANDARD", "total_bases", "OVER"): (0.461017, 295),
    ("STANDARD", "total_bases", "UNDER"): (0.505155, 97),
    ("STANDARD", "walks", "UNDER"): (0.459770, 87),
    ("STANDARD", "walks_allowed", "UNDER"): (0.484375, 64),
}
TIER_MARKET_SIDE_PRIORS.update(
    {
        ("DEMON", "hitter_fantasy_score", "OVER"): (0.549000, 51),
        ("DEMON", "hits_runs_rbis", "OVER"): (0.626000, 171),
        ("DEMON", "singles", "OVER"): (0.703000, 111),
        ("DEMON", "total_bases", "OVER"): (0.686000, 51),
        ("GOBLIN", "earned_runs_allowed", "OVER"): (0.576000, 172),
        ("GOBLIN", "hits", "OVER"): (0.603000, 2780),
        ("GOBLIN", "hits_allowed", "OVER"): (0.669000, 481),
        ("GOBLIN", "hits_runs_rbis", "OVER"): (0.644000, 3701),
        ("GOBLIN", "hitter_fantasy_score", "OVER"): (0.636000, 3570),
        ("GOBLIN", "hitter_strikeouts", "OVER"): (0.637000, 2356),
        ("GOBLIN", "pitcher_fantasy_score", "OVER"): (0.698000, 298),
        ("GOBLIN", "pitcher_strikeouts", "OVER"): (0.697000, 558),
        ("GOBLIN", "pitches_thrown", "OVER"): (0.749000, 267),
        ("GOBLIN", "pitching_outs", "OVER"): (0.598000, 117),
        ("GOBLIN", "singles", "OVER"): (0.628000, 137),
        ("GOBLIN", "total_bases", "OVER"): (0.622000, 2606),
        ("GOBLIN", "walks_allowed", "OVER"): (0.744000, 176),
        ("STANDARD", "hits", "OVER"): (0.538000, 182),
        ("STANDARD", "hits_allowed", "OVER"): (0.600000, 50),
        ("STANDARD", "hits_runs_rbis", "OVER"): (0.629000, 437),
        ("STANDARD", "hitter_fantasy_score", "OVER"): (0.510000, 1732),
        ("STANDARD", "pitcher_fantasy_score", "OVER"): (0.521000, 192),
        ("STANDARD", "pitcher_strikeouts", "OVER"): (0.522000, 253),
        ("STANDARD", "pitching_outs", "OVER"): (0.667000, 111),
        ("STANDARD", "runs", "OVER"): (0.654000, 52),
        ("STANDARD", "singles", "OVER"): (0.565000, 200),
        ("STANDARD", "total_bases", "OVER"): (0.617000, 149),
    }
)

SYSTEM_TIER_MIXES = {
    3: {"GOBLIN": 1, "STANDARD": 2},
    4: {"GOBLIN": 2, "STANDARD": 2},
    5: {"GOBLIN": 3, "STANDARD": 2},
}

SINGLE_GAME_SYSTEM_TIER_MIXES = {
    2: {"GOBLIN": 2},
    3: {"GOBLIN": 2, "STANDARD": 1},
    4: {"GOBLIN": 3, "STANDARD": 1},
}

WINDFALL_TIER_MIXES = {
    3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1},
    4: {"GOBLIN": 1, "STANDARD": 2, "DEMON": 1},
    5: {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1},
}

SINGLE_GAME_WINDFALL_TIER_MIXES = {
    2: {"GOBLIN": 2},
    3: {"GOBLIN": 2, "STANDARD": 1},
    4: {"GOBLIN": 3, "STANDARD": 1},
}

MARKETED_TEMPLATES = (
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
)

SINGLE_GAME_MARKETED_TEMPLATES = (
    {"label": "2-leg", "goblin": 2, "standard": 0, "demon": 0},
    {"label": "3-leg", "goblin": 2, "standard": 1, "demon": 0},
)

SLIP_ROW_COLUMNS = (
    "n_legs",
    "legs",
    "hit_prob",
    "payout_mult",
    "payout_quote_status",
    "payout_is_exact",
    "payout_quote_key",
    "kernel_mult",
    "payout_mult_eff",
    "ev_mult",
    "atlas_power_mult",
    "pricing_engine",
    "avg_p",
    "min_p",
    "max_p",
    "min_p_raw",
    "max_p_raw",
    "avg_fragility",
    "slip_key",
    "pen_team",
    "pen_family",
    "pen_frag",
    "pen_min_std",
    "pen_role_ctx",
    "pen_minute_risk",
    "pen_total",
    "role_ctx_bonus",
    "role_ctx_on_legs",
    "role_ctx_on_share",
    "score_adj",
    "players",
    "rank_ev",
    "beam_selected",
    "leg_1",
    "leg_2",
    "leg_3",
    "leg_4",
    "leg_5",
    "public_survival_score",
    "public_quality_pass",
    "public_quality_reasons",
    "prop_market_ids",
    "bettingpros_context_avg",
    "slip_consensus_legs",
    "slip_consensus_share",
    "public_portfolio_status",
    "public_portfolio_reason",
    "q_leg_count",
    "q_players",
)

MARKETED_CSV_COLUMNS = (
    "slip",
    "high_confidence",
    "hit_prob",
    "payout_mult",
    "payout_quote_status",
    "payout_is_exact",
    "payout_quote_key",
    "ev",
    "player",
    "team",
    "opp",
    "stat",
    "direction",
    "tier",
    "line",
    "p_cal",
    "external_market_context_available",
    "market_context_source_type",
    "external_market_context_source",
    "prizepicks_line_only_market_context",
    "is_questionable",
    "q_out_frac",
    "public_survival_score",
    "public_quality_pass",
    "public_quality_reasons",
    "slip_consensus_legs",
    "slip_consensus_share",
    "public_portfolio_status",
    "public_portfolio_reason",
)


class _PayoutQuoteContext:
    def __init__(self, *, run_dir: Path, run_id: Any, run_mode: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.run_mode = run_mode
        self.quotes: list[dict[str, Any]] = []
        self.formula_rows: list[dict[str, Any]] = []
        self.quote_cache_by_key: dict[str, dict[str, Any]] = {}
        self.last_live_quote_at = 0.0
        self.live_quote_throttle_seconds = _env_float("ATLAS_PP_QUOTE_THROTTLE_S", 0.75)
        cached_path = run_dir / "slips" / PAYOUT_QUOTE_MANIFEST_NAME
        self.cached_manifest = load_quote_manifest(cached_path) if run_mode != "live" else {}

    def quote(self, legs: list[dict[str, Any]], *, family: str, label: str) -> dict[str, Any]:
        if len(legs) < 2:
            return {}
        picks = normalize_quote_picks(legs)
        cache_key = quote_cache_key(picks) if len(picks) >= 2 else ""
        if cache_key and cache_key in self.quote_cache_by_key:
            quote = copy.deepcopy(self.quote_cache_by_key[cache_key])
            quote["quote_status"] = "cached_in_run"
            quote["cache_source"] = "live_run_quote_cache"
            quote["family"] = family
            quote["label"] = label
            quote["slip_id"] = f"{family}:{label}"
            self.quotes.append(quote)
            self.formula_rows.append(
                payout_formula_audit_row(legs=legs, family=family, label=label, quote=quote, sport="mlb")
            )
            return quote
        if self.run_mode == "live" and self.live_quote_throttle_seconds > 0:
            elapsed = time.monotonic() - self.last_live_quote_at
            if self.last_live_quote_at > 0 and elapsed < self.live_quote_throttle_seconds:
                time.sleep(self.live_quote_throttle_seconds - elapsed)
        quote = quote_prizepicks_payout(
            legs,
            run_mode=self.run_mode,
            allow_network=self.run_mode == "live",
            cached_manifest=self.cached_manifest,
            include_raw=self.run_mode == "live",
            family=family,
            label=label,
        )
        if self.run_mode == "live":
            self.last_live_quote_at = time.monotonic()
        if not quote:
            return {}
        quote = dict(quote)
        if cache_key:
            self.quote_cache_by_key[cache_key] = copy.deepcopy(quote)
        quote["family"] = family
        quote["label"] = label
        quote["slip_id"] = f"{family}:{label}"
        self.quotes.append(quote)
        self.formula_rows.append(
            payout_formula_audit_row(legs=legs, family=family, label=label, quote=quote, sport="mlb")
        )
        return quote

    def write_manifest(self, path: Path) -> dict[str, Any]:
        return write_quote_manifest(
            path,
            run_id=str(self.run_id or ""),
            run_mode=self.run_mode,
            quotes=self.quotes,
        )

    def write_formula_audit(self, path: Path) -> dict[str, Any]:
        return write_payout_formula_audit(
            path,
            run_id=str(self.run_id or ""),
            run_mode=self.run_mode,
            sport="mlb",
            rows=self.formula_rows,
        )


def build_slip_families_from_scored_run(run_dir: Path) -> dict[str, Any]:
    scored_path = run_dir / "scored_legs.json"
    if not scored_path.exists():
        raise FileNotFoundError(f"scored_legs.json not found: {scored_path}")
    scored = json.loads(scored_path.read_text(encoding="utf-8"))
    run_id = scored.get("run_id")
    run_mode = _infer_run_mode(run_dir)
    config_manifest = active_mlb_config_manifest(_repo_root_for_run_dir(run_dir))
    legs = _augment_legs_with_feature_context(
        [row for row in scored.get("scored_legs", []) if isinstance(row, dict)],
        run_dir=run_dir,
        run_id=run_id,
    )
    single_game_slate = _is_single_game_slate(legs)
    system_sizes = SYSTEM_SINGLE_GAME_SIZES if single_game_slate else SYSTEM_FULL_SLATE_SIZES
    system_tier_mixes = SINGLE_GAME_SYSTEM_TIER_MIXES if single_game_slate else SYSTEM_TIER_MIXES
    windfall_sizes = WINDFALL_SINGLE_GAME_SIZES if single_game_slate else WINDFALL_FULL_SLATE_SIZES
    windfall_tier_mixes = SINGLE_GAME_WINDFALL_TIER_MIXES if single_game_slate else WINDFALL_TIER_MIXES

    slip_dir = run_dir / "slips"
    system_dir = run_dir / "System"
    windfall_dir = run_dir / "Windfall"
    for directory in (slip_dir, system_dir, windfall_dir):
        directory.mkdir(parents=True, exist_ok=True)

    portfolio_exact_counts: dict[str, int] = {}
    portfolio_exposure_counts: dict[str, int] = {}
    family_outputs: dict[str, Any] = {}
    quote_context = _PayoutQuoteContext(run_dir=run_dir, run_id=run_id, run_mode=run_mode)

    marketed_outputs = _write_marketed_slips(
        run_dir=run_dir,
        json_dir=slip_dir,
        legs=legs,
        run_id=run_id,
        single_game_slate=single_game_slate,
        portfolio_exact_counts=portfolio_exact_counts,
        portfolio_exposure_counts=portfolio_exposure_counts,
        max_exact_leg_repeats=PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
        max_exposure_repeats=PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
        quote_context=quote_context,
    )
    family_outputs["Marketed"] = marketed_outputs

    system_outputs = _write_sized_family(
        run_dir=run_dir,
        json_dir=slip_dir,
        output_dir=system_dir,
        family="System",
        rows=_ranked_legs(legs, family="System"),
        sizes=system_sizes,
        tier_mixes=system_tier_mixes,
        root_mirror=True,
        run_id=run_id,
        portfolio_exact_counts=portfolio_exact_counts,
        portfolio_exposure_counts=portfolio_exposure_counts,
        max_exact_leg_repeats=PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
        max_exposure_repeats=PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
        quote_context=quote_context,
    )
    family_outputs["System"] = system_outputs

    windfall_outputs = _write_sized_family(
        run_dir=run_dir,
        json_dir=slip_dir,
        output_dir=windfall_dir,
        family="Windfall",
        rows=_ranked_legs(legs, family="Windfall"),
        sizes=windfall_sizes,
        tier_mixes=windfall_tier_mixes,
        root_mirror=False,
        run_id=run_id,
        portfolio_exact_counts=portfolio_exact_counts,
        portfolio_exposure_counts=portfolio_exposure_counts,
        max_exact_leg_repeats=PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
        max_exposure_repeats=PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
        quote_context=quote_context,
    )
    family_outputs["Windfall"] = windfall_outputs

    demonhunter_outputs = _write_demonhunter(
        run_dir=run_dir,
        json_dir=slip_dir,
        legs=legs,
        run_id=run_id,
        portfolio_exact_counts=portfolio_exact_counts,
        portfolio_exposure_counts=portfolio_exposure_counts,
        max_exact_leg_repeats=PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
        max_exposure_repeats=PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
        quote_context=quote_context,
    )
    family_outputs["DemonHunter"] = demonhunter_outputs

    payout_quote_path = slip_dir / PAYOUT_QUOTE_MANIFEST_NAME
    payout_quote_manifest = quote_context.write_manifest(payout_quote_path)
    payout_formula_path = slip_dir / PAYOUT_FORMULA_AUDIT_NAME
    payout_formula_audit = quote_context.write_formula_audit(payout_formula_path)
    manifest = {
        "run_id": run_id,
        "builder": "atlas_mlb_slip_writer_v4",
        "selection_model_version": PUBLIC_SLIP_RANKER_VERSION,
        "mlb_config": config_manifest,
        "run_mode": run_mode,
        "single_game_slate": single_game_slate,
        "family_count": len(family_outputs),
        "supported_families": list(supported_slip_families()),
        "slip_count": sum(int(item.get("slip_count") or 0) for item in family_outputs.values()),
        "families": family_outputs,
        "payout_quote_manifest": {
            "path": str(payout_quote_path),
            "schema_version": payout_quote_manifest.get("schema_version"),
            "tool_version": payout_quote_manifest.get("tool_version"),
            "quote_count": payout_quote_manifest.get("quote_count"),
            "exact_quote_count": payout_quote_manifest.get("exact_quote_count"),
            "fallback_quote_count": payout_quote_manifest.get("fallback_quote_count"),
        },
        "payout_formula_audit": {
            "path": str(payout_formula_path),
            "schema_version": payout_formula_audit.get("schema_version"),
            "tool_version": payout_formula_audit.get("tool_version"),
            "row_count": payout_formula_audit.get("row_count"),
            "exact_compare_count": payout_formula_audit.get("exact_compare_count"),
            "summary": payout_formula_audit.get("summary"),
        },
        "tier_mix_contract": {
            "System": _stringify_mix_keys(system_tier_mixes),
            "Windfall": _stringify_mix_keys(windfall_tier_mixes),
            "DemonHunter": {str(size): {"DEMON": size} for size in DEMONHUNTER_SIZES},
            "Marketed": marketed_outputs.get("tier_templates", []),
        },
        "tier_direction_filters": {tier: sorted(values) for tier, values in PUBLIC_TIER_DIRECTION_FILTERS.items()},
        "excluded_public_markets": sorted(PUBLIC_EXCLUDED_MARKETS),
        "selection_policy": _selection_policy_manifest(),
        "family_builder_policies": _family_policy_manifest(),
        "portfolio_policy": {
            "priority": list(PUBLIC_PORTFOLIO_PRIORITY),
            "max_exact_leg_repeats_across_public": PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
            "max_exposure_repeats_across_public": PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
            "exact_leg_key": "player/event/market/line/side",
            "exposure_key": "player/event/market/side",
            "selected_exact_leg_count": len(portfolio_exact_counts),
            "selected_exposure_count": len(portfolio_exposure_counts),
            "repeat_violations": _portfolio_repeat_violations(portfolio_exact_counts),
            "exposure_repeat_violations": _portfolio_repeat_violations(portfolio_exposure_counts),
        },
        "manifest_path": str(slip_dir / "slips_manifest.json"),
    }
    (slip_dir / "slips_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _write_sized_family(
    *,
    run_dir: Path,
    json_dir: Path,
    output_dir: Path,
    family: str,
    rows: list[dict[str, Any]],
    sizes: tuple[int, ...],
    tier_mixes: dict[int, dict[str, int]],
    root_mirror: bool,
    run_id: Any,
    portfolio_exact_counts: dict[str, int],
    portfolio_exposure_counts: dict[str, int],
    max_exact_leg_repeats: int,
    max_exposure_repeats: int,
    quote_context: _PayoutQuoteContext,
) -> dict[str, Any]:
    csv_paths: dict[str, str] = {}
    json_paths: dict[str, str] = {}
    slip_count = 0
    _remove_unselected_sized_outputs(
        run_dir=run_dir,
        json_dir=json_dir,
        output_dir=output_dir,
        family=family,
        sizes=sizes,
        root_mirror=root_mirror,
    )
    for size in sizes:
        tier_mix = tier_mixes.get(size, {})
        selected = _select_tier_mix_legs(
            rows,
            mix=tier_mix,
            portfolio_exact_counts=portfolio_exact_counts,
            portfolio_exposure_counts=portfolio_exposure_counts,
            max_exact_leg_repeats=max_exact_leg_repeats,
            max_exposure_repeats=max_exposure_repeats,
            family=family,
        )
        payout_quote = quote_context.quote(selected, family=family, label=f"{size}leg") if len(selected) == size else {}
        payload = _slip_payload(
            family=family,
            run_id=run_id,
            target_leg_count=size,
            selected=selected,
            tier_mix=tier_mix,
            payout_quote=payout_quote,
        )
        csv_row = _slip_csv_row(selected, payout_quote=payout_quote)
        csv_path = output_dir / f"recommended_{size}leg.csv"
        json_path = json_dir / f"{_family_key(family)}_{size}leg.json"
        _write_slip_rows_csv(csv_path, [csv_row] if len(selected) == size else [])
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        if root_mirror:
            _write_slip_rows_csv(run_dir / f"recommended_{size}leg.csv", [csv_row] if len(selected) == size else [])
        csv_paths[f"{size}leg"] = str(csv_path)
        json_paths[f"{size}leg"] = str(json_path)
        if len(selected) == size:
            _commit_portfolio_legs(selected, portfolio_exact_counts, portfolio_exposure_counts)
            slip_count += 1
    return {
        "family": family,
        "slip_count": slip_count,
        "target_leg_counts": list(sizes),
        "tier_mixes": _stringify_mix_keys(tier_mixes),
        "builder_policy": _policy_to_manifest(_family_policy(family)),
        "csv_paths": csv_paths,
        "json_paths": json_paths,
    }


def _remove_unselected_sized_outputs(
    *,
    run_dir: Path,
    json_dir: Path,
    output_dir: Path,
    family: str,
    sizes: tuple[int, ...],
    root_mirror: bool,
) -> None:
    selected_sizes = set(sizes)
    family_key = _family_key(family)
    for size in PUBLIC_SIZED_SLIP_COUNTS:
        if size in selected_sizes:
            continue
        stale_paths = [
            output_dir / f"recommended_{size}leg.csv",
            json_dir / f"{family_key}_{size}leg.json",
        ]
        if root_mirror:
            stale_paths.append(run_dir / f"recommended_{size}leg.csv")
        for path in stale_paths:
            if path.exists():
                path.unlink()


def _write_demonhunter(
    *,
    run_dir: Path,
    json_dir: Path,
    legs: list[dict[str, Any]],
    run_id: Any,
    portfolio_exact_counts: dict[str, int],
    portfolio_exposure_counts: dict[str, int],
    max_exact_leg_repeats: int,
    max_exposure_repeats: int,
    quote_context: _PayoutQuoteContext,
) -> dict[str, Any]:
    ranked = _ranked_legs(legs, family="DemonHunter")
    rows: list[dict[str, Any]] = []
    slips: list[dict[str, Any]] = []
    for size in DEMONHUNTER_SIZES:
        selected = _select_distinct_legs(
            ranked,
            size=size,
            allowed_tiers={"DEMON"},
            portfolio_exact_counts=portfolio_exact_counts,
            portfolio_exposure_counts=portfolio_exposure_counts,
            max_exact_leg_repeats=max_exact_leg_repeats,
            max_exposure_repeats=max_exposure_repeats,
            family="DemonHunter",
        )
        if len(selected) != size:
            continue
        payout_quote = quote_context.quote(selected, family="DemonHunter", label=f"{size}leg")
        rows.append(_slip_csv_row(selected, payout_quote=payout_quote))
        slips.append(
            _slip_payload(
                family="DemonHunter",
                run_id=run_id,
                target_leg_count=size,
                selected=selected,
                tier_mix={"DEMON": size},
                payout_quote=payout_quote,
            )
        )
        _commit_portfolio_legs(selected, portfolio_exact_counts, portfolio_exposure_counts)

    csv_path = run_dir / "demonhunter.csv"
    json_path = json_dir / "demonhunter.json"
    _write_slip_rows_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "family": "DemonHunter",
                "run_id": run_id,
                "selection_model_version": PUBLIC_SLIP_RANKER_VERSION,
                "slip_count": len(slips),
                "slips": slips,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "family": "DemonHunter",
        "slip_count": len(slips),
        "target_leg_counts": list(DEMONHUNTER_SIZES),
        "tier_mixes": {str(size): {"DEMON": size} for size in DEMONHUNTER_SIZES},
        "builder_policy": _policy_to_manifest(_family_policy("DemonHunter")),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
    }


def _write_marketed_slips(
    *,
    run_dir: Path,
    json_dir: Path,
    legs: list[dict[str, Any]],
    run_id: Any,
    single_game_slate: bool,
    portfolio_exact_counts: dict[str, int],
    portfolio_exposure_counts: dict[str, int],
    max_exact_leg_repeats: int,
    max_exposure_repeats: int,
    quote_context: _PayoutQuoteContext,
) -> dict[str, Any]:
    ranked = _ranked_legs(legs, family="Marketed")
    templates = SINGLE_GAME_MARKETED_TEMPLATES if single_game_slate else MARKETED_TEMPLATES
    slips: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for template in templates:
        selected = _select_template_legs(
            ranked,
            template=template,
            portfolio_exact_counts=portfolio_exact_counts,
            portfolio_exposure_counts=portfolio_exposure_counts,
            max_exact_leg_repeats=max_exact_leg_repeats,
            max_exposure_repeats=max_exposure_repeats,
            family="Marketed",
        )
        if len(selected) != _template_size(template):
            continue
        label = str(template["label"])
        payout_quote = quote_context.quote(selected, family="Marketed", label=label)
        slip = _marketed_slip_payload(label=label, selected=selected, payout_quote=payout_quote)
        slips.append(slip)
        csv_rows.extend(_marketed_csv_rows(slip))
        _commit_portfolio_legs(selected, portfolio_exact_counts, portfolio_exposure_counts)

    json_path = run_dir / "marketed_slips.json"
    csv_path = run_dir / "marketed_slips.csv"
    companion_json_path = json_dir / "marketed_slips.json"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "slips": slips,
        "meta": {
            "builder": "atlas_mlb_marketed_slip_builder_v2",
            "selection_model_version": PUBLIC_SLIP_RANKER_VERSION,
            "single_game_slate": single_game_slate,
            "templates": [str(template["label"]) for template in templates],
            "tier_templates": list(templates),
            "payout_quote_manifest": str(json_dir / PAYOUT_QUOTE_MANIFEST_NAME),
            "tier_direction_filters": {tier: sorted(values) for tier, values in PUBLIC_TIER_DIRECTION_FILTERS.items()},
            "excluded_public_markets": sorted(PUBLIC_EXCLUDED_MARKETS),
            "selection_policy": _selection_policy_manifest(),
            "family_builder_policy": _policy_to_manifest(_family_policy("Marketed")),
            "portfolio_policy": {
                "priority": list(PUBLIC_PORTFOLIO_PRIORITY),
                "max_exact_leg_repeats_across_public": max_exact_leg_repeats,
                "max_exposure_repeats_across_public": max_exposure_repeats,
                "exact_leg_key": "player/event/market/line/side",
                "exposure_key": "player/event/market/side",
            },
            "slip_composition_policy": _slip_composition_policy_manifest(),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    companion_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    _write_dict_csv(csv_path, csv_rows, MARKETED_CSV_COLUMNS)
    return {
        "family": "Marketed",
        "slip_count": len(slips),
        "target_leg_counts": [_template_size(template) for template in templates],
        "tier_templates": list(templates),
        "builder_policy": _policy_to_manifest(_family_policy("Marketed")),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
    }


def _ranked_legs(legs: list[dict[str, Any]], *, family: str) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, float, float, float, float]:
        policy = _family_policy(family)
        probability = _float(row.get("model_probability"))
        stability = _float(row.get("stability_score"))
        fragility = _float(row.get("fragility_score"))
        prior = _tier_market_side_prior(row)
        bettingpros = _bettingpros_context_score(row)
        edge = _edge_score(row)
        prop_identifier = _prop_identifier_score(row)
        tier = _tier(row)
        market = _market_key(row)
        tier_bonus = policy.tier_bonus.get(tier, -0.04)
        segment_key = (tier, market)
        market_adjustment = (
            policy.market_bonus.get(market, 0.0)
            - policy.market_penalty.get(market, 0.0)
            + policy.segment_bonus.get(segment_key, 0.0)
            - policy.segment_penalty.get(segment_key, 0.0)
        )
        score = (
            probability * policy.probability_weight
            + prior * policy.prior_weight
            + bettingpros * policy.bettingpros_weight
            + stability * policy.stability_weight
            + (1.0 - fragility) * policy.fragility_weight
            + edge * policy.edge_weight
            + prop_identifier * policy.prop_identifier_weight
            + market_adjustment
        )
        candidate_penalty = 0.0 if _public_candidate(row, family=family) else -10.0
        return (score + tier_bonus + candidate_penalty, prior, bettingpros, probability, stability, edge, prop_identifier, -fragility)

    return sorted(legs, key=sort_key, reverse=True)


def _family_policy(family: str) -> _FamilyBuilderPolicy:
    return FAMILY_BUILDER_POLICIES.get(family, FAMILY_BUILDER_POLICIES["Marketed"])


def _select_distinct_legs(
    rows: list[dict[str, Any]],
    *,
    size: int,
    allowed_tiers: set[str],
    used_player_ids: set[str] | None = None,
    used_market_counts: dict[str, int] | None = None,
    used_pitcher_workload_count: list[int] | None = None,
    portfolio_exact_counts: dict[str, int] | None = None,
    portfolio_exposure_counts: dict[str, int] | None = None,
    max_exact_leg_repeats: int = PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
    max_exposure_repeats: int = PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
    family: str = "",
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_players = set(used_player_ids or set())
    used_player_markets: set[tuple[str, str]] = set()
    market_counts = used_market_counts if used_market_counts is not None else {}
    pitcher_workload_count = used_pitcher_workload_count if used_pitcher_workload_count is not None else [0]
    for row in rows:
        if not _public_candidate(row, family=family):
            continue
        if _tier(row) not in allowed_tiers:
            continue
        if not _tier_direction_allowed(row):
            continue
        if not _portfolio_leg_available(
            row,
            portfolio_exact_counts,
            portfolio_exposure_counts,
            max_exact_leg_repeats,
            max_exposure_repeats,
        ):
            continue
        if not _slip_composition_available(row, market_counts, pitcher_workload_count):
            continue
        player_id = _player_key(row)
        market = str(row.get("market") or "")
        player_market = (player_id, market)
        if player_id in used_players or player_market in used_player_markets:
            continue
        selected.append(row)
        used_players.add(player_id)
        used_player_markets.add(player_market)
        _commit_slip_composition(row, market_counts, pitcher_workload_count)
        if len(selected) >= size:
            break
    return selected


def _select_tier_mix_legs(
    rows: list[dict[str, Any]],
    *,
    mix: dict[str, int],
    used_player_ids: set[str] | None = None,
    portfolio_exact_counts: dict[str, int] | None = None,
    portfolio_exposure_counts: dict[str, int] | None = None,
    max_exact_leg_repeats: int = PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
    max_exposure_repeats: int = PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
    family: str = "",
) -> list[dict[str, Any]]:
    if not mix:
        return []
    selected: list[dict[str, Any]] = []
    used_players = set(used_player_ids or set())
    used_market_counts: dict[str, int] = {}
    used_pitcher_workload_count = [0]
    for tier in TIER_ORDER:
        count = int(mix.get(tier) or 0)
        if count <= 0:
            continue
        tier_rows = [row for row in rows if _tier(row) == tier]
        tier_selected = _select_distinct_legs(
            tier_rows,
            size=count,
            allowed_tiers={tier},
            used_player_ids=used_players,
            used_market_counts=used_market_counts,
            used_pitcher_workload_count=used_pitcher_workload_count,
            portfolio_exact_counts=portfolio_exact_counts,
            portfolio_exposure_counts=portfolio_exposure_counts,
            max_exact_leg_repeats=max_exact_leg_repeats,
            max_exposure_repeats=max_exposure_repeats,
            family=family,
        )
        if len(tier_selected) != count:
            return []
        selected.extend(tier_selected)
        used_players.update(_player_key(row) for row in tier_selected)
    return selected


def _select_template_legs(
    rows: list[dict[str, Any]],
    *,
    template: dict[str, Any],
    portfolio_exact_counts: dict[str, int] | None = None,
    portfolio_exposure_counts: dict[str, int] | None = None,
    max_exact_leg_repeats: int = PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS,
    max_exposure_repeats: int = PUBLIC_PORTFOLIO_MAX_EXPOSURE_REPEATS,
    family: str = "Marketed",
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_players: set[str] = set()
    used_market_counts: dict[str, int] = {}
    used_pitcher_workload_count = [0]
    for tier_key in ("goblin", "standard", "demon"):
        count = int(template.get(tier_key) or 0)
        if count <= 0:
            continue
        tier_rows = [row for row in rows if _tier(row) == tier_key.upper()]
        tier_selected = _select_distinct_legs(
            tier_rows,
            size=count,
            allowed_tiers={tier_key.upper()},
            used_player_ids=used_players,
            used_market_counts=used_market_counts,
            used_pitcher_workload_count=used_pitcher_workload_count,
            portfolio_exact_counts=portfolio_exact_counts,
            portfolio_exposure_counts=portfolio_exposure_counts,
            max_exact_leg_repeats=max_exact_leg_repeats,
            max_exposure_repeats=max_exposure_repeats,
            family=family,
        )
        if len(tier_selected) != count:
            return []
        selected.extend(tier_selected)
        used_players.update(_player_key(row) for row in tier_selected)
    return selected


def _slip_payload(
    *,
    family: str,
    run_id: Any,
    target_leg_count: int,
    selected: list[dict[str, Any]],
    tier_mix: dict[str, int] | None = None,
    payout_quote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n_legs = len(selected)
    payout = _quote_payout_mult(payout_quote, n_legs if n_legs else target_leg_count)
    return {
        "family": family,
        "run_id": run_id,
        "leg_count": n_legs,
        "target_leg_count": target_leg_count,
        "method": "atlas_mlb_ranked_tier_mix_slip_builder_v2",
        "selection_model_version": PUBLIC_SLIP_RANKER_VERSION,
        "tier_mix": dict(tier_mix or _tier_counts(selected)),
        "tier_direction_filters": {tier: sorted(values) for tier, values in PUBLIC_TIER_DIRECTION_FILTERS.items()},
        "family_builder_policy": _policy_to_manifest(_family_policy(family)),
        "prop_market_identifiers": [PROP_MARKET_IDENTIFIERS.get(_market_key(row), 0) for row in selected],
        "market_context_source_mix": _market_context_source_mix(selected),
        "avg_tier_market_side_prior": _mean([_tier_market_side_prior(row) for row in selected]) if selected else 0.0,
        "avg_bettingpros_context_score": _mean([_bettingpros_context_score(row) for row in selected]) if selected else 0.0,
        "hit_prob": _product(_float(row.get("model_probability")) for row in selected) if selected else 0.0,
        "payout_mult": payout,
        "payout_quote_status": _quote_status(payout_quote),
        "payout_is_exact": _quote_is_exact(payout_quote),
        "payout_quote_key": _quote_key(payout_quote),
        "payout_quote": _quote_summary(payout_quote),
        "slip_composition_policy": _slip_composition_policy_manifest(),
        "legs": selected,
    }


def _marketed_slip_payload(
    *,
    label: str,
    selected: list[dict[str, Any]],
    payout_quote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n_legs = len(selected)
    hit_prob = _product(_float(row.get("model_probability")) for row in selected)
    payout = _quote_payout_mult(payout_quote, n_legs)
    survival = _public_survival_score(selected)
    return {
        "label": label,
        "legs": [_marketed_leg(row) for row in selected],
        "high_confidence": hit_prob >= 0.20,
        "hit_prob": round(hit_prob, 6),
        "payout_mult": payout,
        "payout_quote_status": _quote_status(payout_quote),
        "payout_is_exact": _quote_is_exact(payout_quote),
        "payout_quote_key": _quote_key(payout_quote),
        "payout_quote": _quote_summary(payout_quote),
        "ev": round(hit_prob * payout, 6),
        "public_survival_score": survival,
        "public_quality_pass": True,
        "public_quality_reasons": "",
        "family_builder_policy": _policy_to_manifest(_family_policy("Marketed")),
        "slip_composition_policy": _slip_composition_policy_manifest(),
        "slip_consensus_legs": 0,
        "slip_consensus_share": 0.0,
        "public_portfolio_status": "kept",
        "public_portfolio_reason": "",
    }


def _marketed_leg(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player": str(row.get("player_name") or ""),
        "tier": _tier(row),
        "projection_id": str(row.get("source_projection_id") or ""),
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "game_id": str(row.get("event_id") or ""),
        "game_date": str(row.get("game_date") or ""),
        "opp": str(row.get("opponent") or ""),
        "team": str(row.get("player_team") or ""),
        "stat": _stat_label(row),
        "market": str(row.get("market") or ""),
        "stat_raw": str(row.get("source_market") or row.get("market") or ""),
        "line": _float(row.get("line")),
        "direction": str(row.get("side") or "").upper(),
        "odds_type": _tier(row).lower(),
        "start_time": str(row.get("start_time_utc") or ""),
        "p_cal": _float(row.get("model_probability")),
        "p_adj": _float(row.get("model_probability")),
        "fragility": _float(row.get("fragility_score")),
        "stability_score": _float(row.get("stability_score")),
        "simulation_kernel_version": str(row.get("simulation_kernel_version") or ""),
        "kernel_version": str(row.get("kernel_version") or ""),
        "selection_model_version": PUBLIC_SLIP_RANKER_VERSION,
        "prop_market_identifier": PROP_MARKET_IDENTIFIERS.get(_market_key(row), 0),
        "tier_market_side_prior": _tier_market_side_prior(row),
        "bettingpros_context_score": _bettingpros_context_score(row),
        "market_context_source_type": _market_context_source_type(row),
        "external_market_context_available": _truthy(row.get("external_market_context_available")),
        "external_market_context_source": str(row.get("external_market_context_source") or ""),
        "prizepicks_line_only_market_context": _truthy(row.get("prizepicks_line_only_market_context")),
    }


def _marketed_csv_rows(slip: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for leg in slip.get("legs", []):
        rows.append(
            {
                "slip": slip.get("label"),
                "high_confidence": slip.get("high_confidence", False),
                "hit_prob": round(_float(slip.get("hit_prob")), 4),
                "payout_mult": round(_float(slip.get("payout_mult")), 3),
                "payout_quote_status": slip.get("payout_quote_status", ""),
                "payout_is_exact": bool(slip.get("payout_is_exact", False)),
                "payout_quote_key": slip.get("payout_quote_key", ""),
                "ev": round(_float(slip.get("ev")), 4),
                "player": leg.get("player"),
                "team": leg.get("team"),
                "opp": leg.get("opp"),
                "stat": leg.get("stat"),
                "direction": leg.get("direction"),
                "tier": leg.get("tier"),
                "line": leg.get("line"),
                "p_cal": round(_float(leg.get("p_cal")), 4),
                "external_market_context_available": bool(leg.get("external_market_context_available")),
                "market_context_source_type": leg.get("market_context_source_type"),
                "external_market_context_source": leg.get("external_market_context_source"),
                "prizepicks_line_only_market_context": bool(leg.get("prizepicks_line_only_market_context")),
                "is_questionable": 0,
                "q_out_frac": 0.0,
                "public_survival_score": round(_float(slip.get("public_survival_score")), 4),
                "public_quality_pass": slip.get("public_quality_pass", True),
                "public_quality_reasons": slip.get("public_quality_reasons", ""),
                "slip_consensus_legs": slip.get("slip_consensus_legs", 0),
                "slip_consensus_share": round(_float(slip.get("slip_consensus_share")), 4),
                "public_portfolio_status": slip.get("public_portfolio_status", ""),
                "public_portfolio_reason": slip.get("public_portfolio_reason", ""),
            }
        )
    return rows


def _slip_csv_row(selected: list[dict[str, Any]], *, payout_quote: dict[str, Any] | None = None) -> dict[str, Any]:
    n_legs = len(selected)
    hit_prob = _product(_float(row.get("model_probability")) for row in selected) if selected else 0.0
    payout = _quote_payout_mult(payout_quote, n_legs)
    probabilities = [_float(row.get("model_probability")) for row in selected]
    fragilities = [_float(row.get("fragility_score")) for row in selected]
    leg_labels = [_leg_label(row) for row in selected]
    row: dict[str, Any] = {
        "n_legs": n_legs,
        "legs": " | ".join(leg_labels),
        "hit_prob": round(hit_prob, 12),
        "payout_mult": payout,
        "payout_quote_status": _quote_status(payout_quote),
        "payout_is_exact": _quote_is_exact(payout_quote),
        "payout_quote_key": _quote_key(payout_quote),
        "kernel_mult": 1.0,
        "payout_mult_eff": payout,
        "ev_mult": round(hit_prob * payout, 12),
        "atlas_power_mult": payout,
        "pricing_engine": "pp_kernel",
        "avg_p": _mean(probabilities),
        "min_p": min(probabilities) if probabilities else 0.0,
        "max_p": max(probabilities) if probabilities else 0.0,
        "min_p_raw": min(probabilities) if probabilities else 0.0,
        "max_p_raw": max(probabilities) if probabilities else 0.0,
        "avg_fragility": _mean(fragilities),
        "slip_key": " | ".join(leg_labels),
        "pen_team": 0.0,
        "pen_family": 0.0,
        "pen_frag": round(_mean(fragilities) * 0.01, 12) if fragilities else 0.0,
        "pen_min_std": 0.0,
        "pen_role_ctx": 0.0,
        "pen_minute_risk": 0.0,
        "pen_total": round(_mean(fragilities) * 0.01, 12) if fragilities else 0.0,
        "role_ctx_bonus": 0.0,
        "role_ctx_on_legs": sum(1 for leg in selected if leg.get("matchup_context_available")),
        "role_ctx_on_share": round(sum(1 for leg in selected if leg.get("matchup_context_available")) / n_legs, 6) if n_legs else 0.0,
        "score_adj": round(hit_prob * payout, 12),
        "players": json.dumps([str(row.get("player_name") or "") for row in selected]),
        "rank_ev": round(hit_prob * payout, 12),
        "beam_selected": 1 if selected else 0,
        "public_survival_score": _public_survival_score(selected),
        "public_quality_pass": bool(selected),
        "public_quality_reasons": "",
        "slip_consensus_legs": 0,
        "slip_consensus_share": 0.0,
        "public_portfolio_status": "kept" if selected else "",
        "public_portfolio_reason": "",
        "prop_market_ids": json.dumps([PROP_MARKET_IDENTIFIERS.get(_market_key(row), 0) for row in selected]),
        "bettingpros_context_avg": _mean([_bettingpros_context_score(row) for row in selected]),
        "q_leg_count": 0,
        "q_players": "",
    }
    for index in range(1, 6):
        row[f"leg_{index}"] = leg_labels[index - 1] if index <= len(leg_labels) else ""
    return row


def _quote_payout_mult(payout_quote: dict[str, Any] | None, n_legs: int) -> float:
    chosen = (payout_quote or {}).get("chosen") or {}
    quoted = _float(chosen.get("all_correct"))
    return quoted if quoted > 0 else fallback_power_multiplier(n_legs)


def _quote_status(payout_quote: dict[str, Any] | None) -> str:
    return str((payout_quote or {}).get("quote_status") or "")


def _quote_is_exact(payout_quote: dict[str, Any] | None) -> bool:
    return bool(((payout_quote or {}).get("chosen") or {}).get("payout_is_exact"))


def _quote_key(payout_quote: dict[str, Any] | None) -> str:
    return str((payout_quote or {}).get("quote_key") or "")


def _quote_summary(payout_quote: dict[str, Any] | None) -> dict[str, Any]:
    if not payout_quote:
        return {}
    summary_keys = (
        "schema_version",
        "tool_version",
        "source",
        "quote_status",
        "payout_is_exact",
        "game_mode",
        "amount_bet_cents",
        "n_legs",
        "quote_key",
        "request_sha256",
        "response_sha256",
        "fallback_reason",
        "error",
        "chosen",
        "power",
        "flex",
    )
    return {key: payout_quote.get(key) for key in summary_keys if key in payout_quote}


def _write_slip_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_dict_csv(path, rows, SLIP_ROW_COLUMNS)


def _write_dict_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})


def _augment_legs_with_feature_context(
    legs: list[dict[str, Any]],
    *,
    run_dir: Path,
    run_id: Any,
) -> list[dict[str, Any]]:
    feature_index = _load_feature_context_index(run_dir=run_dir, run_id=run_id)
    if not feature_index:
        return [dict(row, feature_context_joined=False) for row in legs]

    enriched_rows: list[dict[str, Any]] = []
    for row in legs:
        enriched = dict(row)
        feature = feature_index.get(_feature_projection_key(row))
        if feature:
            for field in (*FEATURE_CONTEXT_FIELDS, *BETTINGPROS_CONTEXT_FIELDS):
                if field in feature:
                    enriched[field] = feature[field]
            enriched["feature_context_joined"] = True
        else:
            enriched["feature_context_joined"] = False
        enriched_rows.append(enriched)
    return enriched_rows


def _load_feature_context_index(*, run_dir: Path, run_id: Any) -> dict[str, dict[str, Any]]:
    if not run_id:
        return {}
    feature_dir = _find_feature_context_dir(run_dir=run_dir, run_id=str(run_id))
    if not feature_dir:
        return {}

    json_path = feature_dir / "feature_table.json"
    rows: list[dict[str, Any]] = []
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        candidate_rows = payload.get("features") if isinstance(payload, dict) else payload
        if candidate_rows is None and isinstance(payload, dict):
            candidate_rows = payload.get("rows") or payload.get("feature_rows")
        if isinstance(candidate_rows, dict):
            candidate_rows = list(candidate_rows.values())
        if isinstance(candidate_rows, list):
            rows = [row for row in candidate_rows if isinstance(row, dict)]
    else:
        csv_path = feature_dir / "feature_table.csv"
        if csv_path.exists():
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = [row for row in csv.DictReader(handle)]

    feature_index: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _feature_projection_key(row)
        if key and key not in feature_index:
            feature_index[key] = row
    return feature_index


def _find_feature_context_dir(*, run_dir: Path, run_id: str) -> Path | None:
    resolved = run_dir.resolve()
    checked: set[Path] = set()
    for parent in (resolved, *resolved.parents):
        candidates = (
            parent / "data" / "mlb" / "features" / "player_props" / run_id,
            parent / "features" / "player_props" / run_id,
        )
        for candidate in candidates:
            if candidate in checked:
                continue
            checked.add(candidate)
            if (candidate / "feature_table.json").exists() or (candidate / "feature_table.csv").exists():
                return candidate
    return None


def _feature_projection_key(row: dict[str, Any]) -> str:
    return str(row.get("source_projection_id") or row.get("projection_id") or "").strip()


def _leg_label(row: dict[str, Any]) -> str:
    return "{player} {side} {stat} {line:g} ({tier}) [id:{projection_id}]".format(
        player=str(row.get("player_name") or ""),
        side=str(row.get("side") or "").upper(),
        stat=_stat_label(row),
        line=_float(row.get("line")),
        tier=_tier(row),
        projection_id=str(row.get("source_projection_id") or ""),
    )


def _stat_label(row: dict[str, Any]) -> str:
    source = str(row.get("source_market") or "").strip()
    if source:
        return source.upper().replace(" ", "_")
    return str(row.get("market") or "").upper()


def _player_key(row: dict[str, Any]) -> str:
    return str(row.get("player_id") or row.get("player_name") or "").strip().lower()


def _tier(row: dict[str, Any]) -> str:
    return normalize_tier(row.get("tier"))


def _side(row: dict[str, Any]) -> str:
    return normalize_side(row.get("side") or row.get("direction"))


def _tier_direction_allowed(row: dict[str, Any]) -> bool:
    return is_playable_side(tier=_tier(row), side=_side(row))


def _public_candidate(row: dict[str, Any], *, family: str = "") -> bool:
    if _is_combo_leg(row):
        return False
    market = _market_key(row)
    tier = _tier(row)
    side = _side(row)
    if market in PUBLIC_EXCLUDED_MARKETS:
        return False
    status = str(row.get("status") or "").strip().lower()
    if status in {"inactive", "removed", "suspended"}:
        return False
    if side not in PUBLIC_TIER_DIRECTION_FILTERS.get(tier, {side}):
        return False
    if (tier, market, side) in PUBLIC_BLOCKED_SEGMENTS:
        return False
    if not _family_policy_candidate(row, family=family):
        return False
    if family in {"Marketed", "System"} and tier == "STANDARD":
        if _tier_market_side_prior(row) < PUBLIC_STANDARD_PRIOR_FLOOR:
            return False
    if market in PUBLIC_BATTER_MARKETS:
        if family in {"Marketed", "System", "DemonHunter"} and not _batter_action_context_available(row):
            return False
    return True


def _family_policy_candidate(row: dict[str, Any], *, family: str) -> bool:
    policy = _family_policy(family)
    tier = _tier(row)
    minimum_probability = policy.min_probability_by_tier.get(tier)
    if minimum_probability is not None and _value_present(row.get("model_probability")):
        if _float(row.get("model_probability")) < minimum_probability:
            return False
    if policy.min_edge > 0 and _value_present(row.get("edge")):
        if _float(row.get("edge")) < policy.min_edge:
            return False
    return True


def _batter_action_context_available(row: dict[str, Any]) -> bool:
    if not _truthy(row.get("feature_context_joined")):
        return True
    if _truthy(row.get("lineup_context_available")):
        return True
    if _float(row.get("plate_appearance_projection")) >= 3.0:
        return True
    return False


def _is_combo_leg(row: dict[str, Any]) -> bool:
    if _truthy(row.get("is_combo")):
        return True
    player_name = str(row.get("player_name") or row.get("player") or "")
    player_team = str(row.get("player_team") or row.get("team") or "")
    opponent = str(row.get("opponent") or row.get("opp") or "")
    event_id = str(row.get("event_id") or row.get("game_id") or "")
    return " + " in player_name or "/" in player_team or "/" in opponent or "/" in event_id


def _tier_market_side_prior(row: dict[str, Any]) -> float:
    key = (_tier(row), _market_key(row), _side(row))
    rate, count = TIER_MARKET_SIDE_PRIORS.get(key, (0.5, 0))
    weight = float(count) / (float(count) + 400.0) if count else 0.0
    return round(0.5 + (float(rate) - 0.5) * weight, 6)


def _market_key(row: dict[str, Any]) -> str:
    text = str(row.get("market") or row.get("stat_raw") or row.get("source_market") or row.get("stat") or "")
    text = text.strip().lower()
    return "".join(character if character.isalnum() else "_" for character in text).strip("_")


def _edge_score(row: dict[str, Any]) -> float:
    edge = _float(row.get("edge"))
    if edge <= 0:
        return 0.0
    return min(1.0, edge / 0.20)


def _bettingpros_context_score(row: dict[str, Any]) -> float:
    """Small replay-safe tiebreaker from BettingPros projection and streak context."""
    side = _side(row).lower()
    if side not in {"over", "under"}:
        return 0.5
    score = 0.5
    recommended_side = str(row.get("bettingpros_recommended_side") or "").strip().lower()
    if recommended_side in {"over", "under"}:
        score += 0.08 if recommended_side == side else -0.05

    projection_diff = _float(row.get("bettingpros_projection_diff"))
    if projection_diff:
        direction = 1.0 if side == "over" else -1.0
        score += 0.06 * _clamp(direction * projection_diff, -1.0, 1.0)

    rate = _bettingpros_weighted_side_rate(row, side=side)
    if rate:
        score += 0.18 * _clamp(rate - 0.5, -0.5, 0.5)

    streak = _float(row.get("bettingpros_streak"))
    streak_type = str(row.get("bettingpros_streak_type") or "").strip().lower()
    if streak and streak_type:
        if side in streak_type:
            score += min(0.04, 0.006 * abs(streak))
        elif "over" in streak_type or "under" in streak_type:
            score -= min(0.03, 0.004 * abs(streak))

    return round(_clamp(score, 0.0, 1.0), 6)


def _market_context_source_type(row: dict[str, Any]) -> str:
    source_type = str(row.get("market_context_source_type") or "").strip()
    if source_type:
        return source_type
    if _truthy(row.get("external_market_context_available")):
        source = str(row.get("external_market_context_source") or "external_market").strip()
        return f"external_{source}" if source else "external_market"
    return "prizepicks_line_only"


def _market_context_source_mix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "external_confirmed_count": 0,
            "prizepicks_line_only_count": 0,
            "external_confirmed_share": 0.0,
            "prizepicks_line_only_share": 0.0,
        }
    external_count = sum(1 for row in rows if _truthy(row.get("external_market_context_available")))
    pp_only_count = len(rows) - external_count
    total = float(len(rows))
    return {
        "external_confirmed_count": external_count,
        "prizepicks_line_only_count": pp_only_count,
        "external_confirmed_share": round(external_count / total, 6),
        "prizepicks_line_only_share": round(pp_only_count / total, 6),
    }


def _bettingpros_weighted_side_rate(row: dict[str, Any], *, side: str) -> float:
    prefix = "over" if side == "over" else "under"
    weighted = 0.0
    weight_total = 0.0
    for field, weight in (
        (f"bettingpros_last_5_{prefix}_rate", 0.35),
        (f"bettingpros_last_10_{prefix}_rate", 0.25),
        (f"bettingpros_last_20_{prefix}_rate", 0.20),
        (f"bettingpros_season_{prefix}_rate", 0.15),
        (f"bettingpros_prior_season_{prefix}_rate", 0.05),
    ):
        value = _float(row.get(field))
        if value <= 0:
            continue
        if value > 1.0:
            value /= 100.0
        weighted += _clamp(value, 0.0, 1.0) * weight
        weight_total += weight
    return weighted / weight_total if weight_total else 0.0


def _prop_identifier_score(row: dict[str, Any]) -> float:
    identifier = int(PROP_MARKET_IDENTIFIERS.get(_market_key(row), 0) or 0)
    if identifier <= 0:
        return 0.5
    return round(1.0 - ((identifier - 1) / max(1, len(PROP_MARKET_IDENTIFIERS) - 1)), 6)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _tier_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {tier: sum(1 for row in rows if _tier(row) == tier) for tier in TIER_ORDER}


def _exact_leg_key(row: dict[str, Any]) -> str:
    player = _player_key(row)
    event = str(row.get("event_id") or row.get("game_id") or "").strip().lower()
    market = str(row.get("market") or row.get("stat_raw") or row.get("source_market") or "").strip().lower()
    side = _side(row).lower()
    line = f"{_float(row.get('line')):.6g}"
    if player or market:
        return "|".join((player, event, market, line, side))
    projection_id = str(row.get("source_projection_id") or row.get("projection_id") or "").strip().lower()
    return f"projection|{projection_id}|{side}" if projection_id else ""


def _exposure_leg_key(row: dict[str, Any]) -> str:
    player = _player_key(row)
    event = str(row.get("event_id") or row.get("game_id") or "").strip().lower()
    market = str(row.get("market") or row.get("stat_raw") or row.get("source_market") or "").strip().lower()
    side = _side(row).lower()
    if player or market:
        return "|".join((player, event, market, side))
    projection_id = str(row.get("source_projection_id") or row.get("projection_id") or "").strip().lower()
    return f"projection|{projection_id}|{side}" if projection_id else ""


def _portfolio_leg_available(
    row: dict[str, Any],
    portfolio_exact_counts: dict[str, int] | None,
    portfolio_exposure_counts: dict[str, int] | None,
    max_exact_leg_repeats: int,
    max_exposure_repeats: int,
) -> bool:
    exact_key = _exact_leg_key(row)
    if portfolio_exact_counts is not None and exact_key:
        if int(portfolio_exact_counts.get(exact_key, 0)) >= max_exact_leg_repeats:
            return False
    exposure_key = _exposure_leg_key(row)
    if portfolio_exposure_counts is not None and exposure_key:
        if int(portfolio_exposure_counts.get(exposure_key, 0)) >= max_exposure_repeats:
            return False
    return True


def _commit_portfolio_legs(
    rows: list[dict[str, Any]],
    portfolio_exact_counts: dict[str, int],
    portfolio_exposure_counts: dict[str, int],
) -> None:
    for row in rows:
        exact_key = _exact_leg_key(row)
        if exact_key:
            portfolio_exact_counts[exact_key] = int(portfolio_exact_counts.get(exact_key, 0)) + 1
        exposure_key = _exposure_leg_key(row)
        if exposure_key:
            portfolio_exposure_counts[exposure_key] = int(portfolio_exposure_counts.get(exposure_key, 0)) + 1


def _portfolio_repeat_violations(portfolio_counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"exact_leg_key": key, "count": count}
        for key, count in sorted(portfolio_counts.items())
        if count > PUBLIC_PORTFOLIO_MAX_EXACT_LEG_REPEATS
    ]


def _slip_composition_available(
    row: dict[str, Any],
    market_counts: dict[str, int],
    pitcher_workload_count: list[int],
) -> bool:
    market = _market_key(row)
    if int(market_counts.get(market, 0)) >= PUBLIC_MAX_SAME_MARKET_PER_SLIP:
        return False
    if market in PUBLIC_PITCHER_WORKLOAD_MARKETS:
        return int(pitcher_workload_count[0]) < PUBLIC_MAX_PITCHER_WORKLOAD_LEGS_PER_SLIP
    return True


def _commit_slip_composition(
    row: dict[str, Any],
    market_counts: dict[str, int],
    pitcher_workload_count: list[int],
) -> None:
    market = _market_key(row)
    market_counts[market] = int(market_counts.get(market, 0)) + 1
    if market in PUBLIC_PITCHER_WORKLOAD_MARKETS:
        pitcher_workload_count[0] = int(pitcher_workload_count[0]) + 1


def _selection_policy_manifest() -> dict[str, Any]:
    return {
        "selection_model_version": PUBLIC_SLIP_RANKER_VERSION,
        "tier_market_side_prior_count": len(TIER_MARKET_SIDE_PRIORS),
        "prior_shrinkage_count": 400,
        "excluded_public_markets": sorted(PUBLIC_EXCLUDED_MARKETS),
        "blocked_segments": [
            {"tier": tier, "market": market, "side": side}
            for tier, market, side in sorted(PUBLIC_BLOCKED_SEGMENTS)
        ],
        "standard_prior_floor_for_system_and_marketed": PUBLIC_STANDARD_PRIOR_FLOOR,
        "feature_context_fields": list(FEATURE_CONTEXT_FIELDS),
        "bettingpros_context_fields": list(BETTINGPROS_CONTEXT_FIELDS),
        "prop_market_identifiers": dict(sorted(PROP_MARKET_IDENTIFIERS.items(), key=lambda item: item[1])),
        "family_builder_policies": _family_policy_manifest(),
        "ranker_signal_weights": {
            "bettingpros_context_score": "family-weighted signal; projection/streak context, not a hard filter",
            "market_context_source_type": "external_bettingpros_mlb_props when a sportsbook market matched; prizepicks_line_only when PP is the only price/line source",
            "prizepicks_line_only_market_context": "playable PP prop without matched external sportsbook context; not an automatic exclusion",
            "prop_market_identifier": "family-weighted signal from replay prop ranking, not a hard filter",
            "tier_market_side_prior": "shrunk replay segment prior",
        },
        "slip_composition_policy": _slip_composition_policy_manifest(),
        "batter_action_gate": {
            "families": ["Marketed", "System", "DemonHunter"],
            "pass_if": "lineup_context_available or plate_appearance_projection >= 3.0",
            "alternate_line_policy": "Goblin and Demon selections are over-only.",
            "demonhunter_enabled": bool(DEMONHUNTER_SIZES),
        },
    }


def _family_policy_manifest() -> dict[str, Any]:
    return {family: _policy_to_manifest(policy) for family, policy in FAMILY_BUILDER_POLICIES.items()}


def _policy_to_manifest(policy: _FamilyBuilderPolicy) -> dict[str, Any]:
    return {
        "purpose": policy.purpose,
        "signal_weights": {
            "model_probability": policy.probability_weight,
            "tier_market_side_prior": policy.prior_weight,
            "bettingpros_context_score": policy.bettingpros_weight,
            "stability_score": policy.stability_weight,
            "inverse_fragility_score": policy.fragility_weight,
            "edge_score": policy.edge_weight,
            "prop_market_identifier": policy.prop_identifier_weight,
        },
        "tier_bonus": dict(policy.tier_bonus),
        "market_bonus": dict(policy.market_bonus),
        "market_penalty": dict(policy.market_penalty),
        "segment_bonus": _stringify_segment_adjustments(policy.segment_bonus),
        "segment_penalty": _stringify_segment_adjustments(policy.segment_penalty),
        "min_probability_by_tier": dict(policy.min_probability_by_tier),
        "min_edge": policy.min_edge,
    }


def _stringify_segment_adjustments(values: dict[tuple[str, str], float]) -> dict[str, float]:
    return {f"{tier}:{market}": value for (tier, market), value in sorted(values.items())}


def _slip_composition_policy_manifest() -> dict[str, Any]:
    return {
        "max_same_market_per_slip": PUBLIC_MAX_SAME_MARKET_PER_SLIP,
        "max_pitcher_workload_legs_per_slip": PUBLIC_MAX_PITCHER_WORKLOAD_LEGS_PER_SLIP,
        "pitcher_workload_markets": sorted(PUBLIC_PITCHER_WORKLOAD_MARKETS),
    }


def _stringify_mix_keys(mixes: dict[int, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {str(size): dict(mix) for size, mix in mixes.items()}


def _is_single_game_slate(rows: list[dict[str, Any]]) -> bool:
    event_ids = {str(row.get("event_id") or row.get("game_id") or "").strip() for row in rows}
    event_ids.discard("")
    return len(event_ids) == 1


def _template_size(template: dict[str, Any]) -> int:
    return sum(int(template.get(key) or 0) for key in ("goblin", "standard", "demon"))


def _family_key(family: str) -> str:
    return family.strip().lower().replace(" ", "_")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _infer_run_mode(run_dir: Path) -> str:
    parts = {part.lower() for part in run_dir.resolve().parts}
    run_name = run_dir.name.lower()
    if "live_runs" in parts:
        return "live"
    if "corpus" in run_name:
        return "replay_corpus"
    return "replay_single"


def _repo_root_for_run_dir(run_dir: Path) -> Path | None:
    for parent in run_dir.resolve().parents:
        if (parent / "config" / "sports" / "mlb.yaml").exists():
            return parent
    return None


def _product(values) -> float:
    result = 1.0
    for value in values:
        result *= max(0.0, min(1.0, float(value)))
    return result


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if not math.isnan(float(value))]
    if not clean:
        return 0.0
    return round(sum(clean) / len(clean), 12)


def _public_survival_score(selected: list[dict[str, Any]]) -> float:
    if not selected:
        return 0.0
    probabilities = [_float(row.get("model_probability")) for row in selected]
    stability = [_float(row.get("stability_score")) for row in selected]
    fragility = [_float(row.get("fragility_score")) for row in selected]
    score = _mean(probabilities) * 0.70 + _mean(stability) * 0.20 + (1.0 - _mean(fragility)) * 0.10
    return round(max(0.0, min(1.0, score)), 6)


def _float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if not math.isnan(parsed) else 0.0


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value

"""
marketed_slip_builder.py

Dedicated slip builder for marketed Power Play slips with separate configuration,
calibration, and optimization logic from Atlas System/Windfall/DemonHunter output.

DESIGN PRINCIPLES:
- Own config section: config.yaml["marketed_slips"]
- Own calibration: stat-specific adjustments for combo stat miscalibration
- Own optimization: locked tier templates with correlation-aware scoring
- Full Atlas integration: accesses p_cal, p_adj, score_adj, LODO data directly
- Separate from internal Atlas slips: completely independent pipeline branch
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import json

from .minute_risk_guard import apply_minute_risk_guard
from .single_game_script import (
    apply_single_game_script_annotations,
    apply_single_game_selection_surface,
    is_single_game_slate,
    single_game_slip_rule_status,
)
from .slip_family_diversity import prop_key_from_mapping
from .slip_quality_gate import filter_marketed_slips
from .slip_scoring import _prod


class MarketedSlipBuilder:
    """
    Dedicated builder for marketed slips with stat-aware calibration and
    correlation-adjusted probability calculations.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.full_config = config
        self.config = config.get("marketed_slips", {})
        self.slip_config = config.get("slip_build", {})
        
        # Load stat-specific calibration adjustments
        self.stat_calibration = self._load_stat_calibration()
        
        # Templates: locked tier compositions.
        # Build conservative marketed slips first. The builder intentionally uses
        # a global player set across templates, so order changes allocation.
        self.templates = [
            {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
            {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
            {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
        ]
        self.single_game_templates = [
            {"label": "2-leg", "goblin": 2, "standard": 0, "demon": 0},
            {"label": "3-leg", "goblin": 2, "standard": 1, "demon": 0},
        ]
        
    def _load_stat_calibration(self) -> Dict[str, Dict[str, float]]:
        """Load stat-specific calibration adjustments from config or file."""
        
        # Try to load from dedicated calibration file first
        cal_path = Path(self.config.get("calibration_path", "data/model/marketed_calibration.json"))
        if cal_path.exists():
            with open(cal_path) as f:
                cal_data = json.load(f)
                return cal_data.get("stat_calibration", {})
        
        # Fallback to hardcoded calibration based on cache analysis
        return {
            # Combo stats (severely miscalibrated)
            "PR": {"GOBLIN": 0.95, "STANDARD": 0.88, "DEMON": 0.82},
            "RA": {"GOBLIN": 0.94, "STANDARD": 0.86, "DEMON": 0.80},
            "PRA": {"GOBLIN": 0.94, "STANDARD": 0.86, "DEMON": 0.80},
            
            # Individual stats (moderately miscalibrated)  
            "AST": {"GOBLIN": 0.92, "STANDARD": 0.84, "DEMON": 0.78},
            "REB": {"GOBLIN": 0.92, "STANDARD": 0.84, "DEMON": 0.78},
            "FG3M": {"GOBLIN": 0.90, "STANDARD": 0.82, "DEMON": 0.76},
            
            # Well-calibrated stats (minimal adjustment)
            "PTS": {"GOBLIN": 0.98, "STANDARD": 0.94, "DEMON": 0.90},
            "PA": {"GOBLIN": 0.98, "STANDARD": 0.93, "DEMON": 0.88},
        }
    
    def _apply_stat_calibration(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply stat-specific calibration adjustments to p_cal, and compute
        tier-specific selection scores:
          GOBLIN:   goblin_score  = p_cal * l20_edge  (pure model confidence × recent form)
          STANDARD: standard_score = player_dir_te    (player historical hit rate for this stat+direction)
          DEMON:    demon_score   = p_cal * l20_edge  (same as GOBLIN)
        """
        df = df.copy()

        # Marketed probability now trusts the calibrated model probability directly.
        # v5cD CatBoost is well-calibrated across the full board, so we no longer
        # apply stat-specific haircut adjustments before selection.
        df["p_cal_marketed"] = pd.to_numeric(df["p_cal"], errors="coerce").fillna(0.5)

        # Tier-specific selection score (fully vectorized with np.where)
        p_cal   = pd.to_numeric(df["p_cal"],   errors="coerce").fillna(0.5)
        l20     = pd.to_numeric(df.get("l20_edge",   pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).clip(0, 1)

        goblin_score   = (p_cal * l20).values

        # Playoff regime fix: player_dir_te for STANDARD legs is trained on regular-season
        # data. In playoffs, TE is near-zero for OVERs (mean ~-0.002) and inflated for
        # UNDERs due to stale history — neither is a reliable ranking signal.
        # Score ALL STANDARD legs on p_cal_marketed (actual model probability) so OVER and
        # UNDER compete on equal footing. GOBLIN/DEMON keep their tier-specific signals.
        p_cal_marketed = pd.to_numeric(df.get("p_cal_marketed", p_cal), errors="coerce").fillna(p_cal)
        standard_score = p_cal_marketed.values
        demon_score    = goblin_score

        tier_arr = df["tier"].values
        df["marketed_score"] = np.where(
            tier_arr == "STANDARD", standard_score,
            np.where(tier_arr == "DEMON", demon_score, goblin_score)
        )
        df = apply_minute_risk_guard(df, self.full_config, section="marketed_slips", score_col="marketed_score")
        df = apply_single_game_script_annotations(df, self.full_config)
        df = apply_single_game_selection_surface(df, self.full_config, score_col="marketed_score", clip_score=False)

        return df
    
    def _qualify_legs(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply marketed slip qualification filters."""
        
        # Exclusions from config
        excluded_stats = set(self.config.get("excluded_stats", ["BLK", "STL", "TO"]))
        
        # Minimum thresholds from config (applied to p_cal_marketed, post-haircut)
        min_thresholds = self.config.get("min_thresholds", {
            "GOBLIN": 0.60,
            "STANDARD": 0.54, 
            "DEMON": 0.45
        })

        # Raw p_cal floor (applied before haircut) — used to enforce DEMON quality parity
        # with DemonHunter's min_leg_prob without haircut distortion
        min_raw_thresholds = self.config.get("min_raw_thresholds", {})
        
        # Direction preferences from config
        direction_filters = self.config.get("direction_filters", {})
        
        # Vectorized qualification — no iterrows
        stat_mask = ~df["stat"].isin(excluded_stats)

        threshold_ser = df["tier"].map(min_thresholds)
        thresh_mask = df["tier"].isin(min_thresholds.keys()) & (df["p_cal_marketed"] >= threshold_ser)

        # Raw p_cal guard (bypasses haircut distortion for tiers like DEMON)
        if min_raw_thresholds:
            raw_threshold_ser = df["tier"].map(min_raw_thresholds)
            raw_thresh_mask = ~df["tier"].isin(min_raw_thresholds.keys()) | (df["p_cal"] >= raw_threshold_ser)
        else:
            raw_thresh_mask = pd.Series(True, index=df.index)

        dir_mask = pd.Series(True, index=df.index)
        for _tier, _allowed in direction_filters.items():
            tier_rows = df["tier"] == _tier
            dir_mask = dir_mask & (~tier_rows | df["direction"].isin(_allowed))

        # --- UNDER probability window: exclude UNDER legs outside calibrated range ---
        # Playoff regime analysis: 0.60-0.70 is the only UNDER band where actual > model.
        # Below 0.60: actual hit rate ~38-39% (underperforming). Above 0.70: overconfident.
        # Config keys: marketed_slips.min_under_prob, marketed_slips.max_under_prob
        min_under_prob = float(self.config.get("min_under_prob", 0.0) or 0.0)
        max_under_prob = float(self.config.get("max_under_prob", 0.0) or 0.0)
        if (min_under_prob > 0.0 or max_under_prob > 0.0) and "direction" in df.columns and "p_cal" in df.columns:
            under_mask = df["direction"].astype(str).str.strip().str.upper() == "UNDER"
            under_drop = pd.Series(False, index=df.index)
            if min_under_prob > 0.0:
                under_drop = under_drop | (under_mask & (pd.to_numeric(df["p_cal"], errors="coerce") < min_under_prob))
            if max_under_prob > 0.0:
                under_drop = under_drop | (under_mask & (pd.to_numeric(df["p_cal"], errors="coerce") > max_under_prob))
            under_prob_mask = ~under_drop
        else:
            under_prob_mask = pd.Series(True, index=df.index)

        injury_mask = self._questionable_mask(df)

        pool = df[stat_mask & thresh_mask & raw_thresh_mask & dir_mask & under_prob_mask & injury_mask].copy()

        if pool.empty:
            return pd.DataFrame()

        # Best leg per (player, tier) using tier-specific selection score
        sort_cols = [
            col for col in ("marketed_score", "p_cal_marketed", "p_cal")
            if col in pool.columns
        ]
        pool = (
            pool.sort_values(sort_cols, ascending=[False] * len(sort_cols))
            .groupby(["player", "tier"], as_index=False)
            .first()
        )

        return pool

    def _questionable_mask(self, df: pd.DataFrame) -> pd.Series:
        """Return False for soft injury-risk legs only when explicitly configured.

        QUESTIONABLE/q_out is report-only by default. True OUT/DOUBTFUL removal
        belongs to the upstream IAEL hard invalidation path.
        """

        keep_mask = pd.Series(True, index=df.index)
        soft_exposure_mask = self._single_game_soft_exposure_mask(df)
        exclude_questionable = bool(self.config.get("exclude_questionable", False))
        if exclude_questionable and "is_questionable" in df.columns:
            q_vals = pd.to_numeric(df["is_questionable"], errors="coerce").fillna(0.0)
            keep_mask &= (q_vals <= 0.0) | soft_exposure_mask

        q_out_threshold_raw = self.config.get("exclude_q_out_frac_gt")
        if q_out_threshold_raw not in (None, "") and "q_out_frac" in df.columns:
            threshold = float(q_out_threshold_raw)
            q_out_vals = pd.to_numeric(df["q_out_frac"], errors="coerce").fillna(0.0)
            keep_mask &= (q_out_vals <= threshold) | soft_exposure_mask

        return keep_mask

    def _single_game_soft_exposure_mask(self, df: pd.DataFrame) -> pd.Series:
        sg = self.full_config.get("single_game_mode", {}) if isinstance(self.full_config, dict) else {}
        if not isinstance(sg, dict) or not bool(sg.get("soft_injury_exposure_not_hard_exclude", False)):
            return pd.Series(False, index=df.index)
        if not is_single_game_slate(df, self.full_config):
            return pd.Series(False, index=df.index)
        if "role_ctx_outs" not in df.columns:
            return pd.Series(False, index=df.index)
        role_outs = df["role_ctx_outs"].map(lambda x: "" if x is None else str(x).strip().lower())
        return role_outs.ne("") & role_outs.ne("[]") & role_outs.ne("nan")
    
    def _calculate_correlation_adjusted_probability(self, legs: List[pd.Series]) -> float:
        """
        Calculate slip probability with correlation adjustments.
        
        Accounts for:
        - Same team correlations (both positive and negative)
        - Same player stat correlations 
        - Blowout scenario correlations
        """
        if not legs:
            return 0.0
            
        base_prob = _prod([leg["p_cal_marketed"] for leg in legs])
        
        # Same team correlation adjustments
        corr_mult = 1.0
        same_team_penalty = self.config.get("correlation", {}).get("same_team_penalty", 0.03)
        hedge_bonus = self.config.get("correlation", {}).get("hedge_bonus", 0.015)
        
        for i in range(len(legs)):
            team_i = legs[i]["team"]
            direction_i = legs[i]["direction"] 
            
            for j in range(i + 1, len(legs)):
                team_j = legs[j]["team"]
                direction_j = legs[j]["direction"]
                
                if team_i == team_j:
                    if direction_i == direction_j:
                        # Same team, same direction: positive correlation penalty
                        corr_mult *= (1.0 - same_team_penalty)
                    else:
                        # Same team, opposite directions: hedge bonus
                        corr_mult *= (1.0 + hedge_bonus)
        
        # Blowout correlation (all legs from same game affected)
        games = set((leg["team"], leg["opp"]) for leg in legs)
        if len(games) < len(legs):  # Multiple legs from same game
            blowout_penalty = self.config.get("correlation", {}).get("blowout_penalty", 0.02)
            same_game_pairs = len(legs) - len(games)
            corr_mult *= (1.0 - blowout_penalty) ** same_game_pairs
        
        return float(base_prob * max(corr_mult, 0.3))  # Floor at 30% of base
    
    def _build_single_slip(self, pool: pd.DataFrame, template: Dict[str, Any],
                           used_players: set, used_teams: set,
                           single_game_slate: bool = False,
                           used_prop_keys: set[str] | None = None) -> Optional[Dict[str, Any]]:
        """Build a single slip following the template constraints."""

        selected_legs = []
        slip_teams = set()
        # When single_game_slate, track players per team (cap at 4) instead of 1 per team
        slip_team_counts: Dict[str, int] = {}

        # Template n_legs for per-leg-count cap lookup on single-game slates
        template_n_legs = int(template.get("goblin", 0)) + int(template.get("standard", 0)) + int(template.get("demon", 0))
        # Single-game caps by leg count (2026-05-10): 3-leg=2, 4-leg=3, 5-leg=3
        # Tight diversification on small 3-leg slips; modest relaxation on 4/5-leg
        # since the slate only has 2-4 teams to draw from.
        sg_caps_cfg = self.config.get("single_game_caps_by_legs", {}) or {}
        sg_cap_for_n = sg_caps_cfg.get(template_n_legs) or sg_caps_cfg.get(str(template_n_legs))

        # Track what we're adding to used sets (for rollback on failure)
        new_players = set()
        new_teams = set()
        new_prop_keys: set[str] = set()
        used_prop_keys = used_prop_keys if used_prop_keys is not None else set()
        template_label = template["label"]

        sg_rules = (
            self.full_config.get("single_game_mode", {}).get("slip_rules", {})
            if isinstance(self.full_config, dict)
            else {}
        )
        enforce_sg_rules = bool(self.config.get("enforce_single_game_slip_rules", True))
        apply_sg_incremental_caps = single_game_slate and enforce_sg_rules and isinstance(sg_rules, dict)

        def _flag(leg: pd.Series, key: str) -> int:
            try:
                return int(float(leg.get(key, 0) or 0) > 0)
            except Exception:
                return 0

        def _cap_exceeded(leg: pd.Series, rule_key: str, flag_key: str) -> bool:
            if not apply_sg_incremental_caps:
                return False
            raw_cap = None
            by_legs = sg_rules.get(f"{rule_key}_by_legs")
            if isinstance(by_legs, dict):
                raw_cap = by_legs.get(template_n_legs, by_legs.get(str(template_n_legs)))
            if raw_cap is None:
                raw_cap = sg_rules.get(rule_key)
            if raw_cap is None:
                return False
            cap = int(raw_cap or 0)
            current = sum(_flag(existing, flag_key) for existing in selected_legs)
            return current + _flag(leg, flag_key) > cap

        try:
            for tier, count in [("GOBLIN", template["goblin"]),
                                ("STANDARD", template["standard"]),
                                ("DEMON", template["demon"])]:
                if count == 0:
                    continue

                tier_pool = pool[pool["tier"] == tier].copy()
                sort_cols = [
                    col for col in ("marketed_score", "p_cal_marketed", "p_cal")
                    if col in tier_pool.columns
                ]
                tier_pool = tier_pool.sort_values(
                    sort_cols,
                    ascending=[False] * len(sort_cols),
                )

                selected = 0
                for _, leg in tier_pool.iterrows():
                    player = leg["player"]
                    team = leg["team"]

                    # Player uniqueness always enforced
                    if player in used_players or player in new_players:
                        continue
                    prop_key = prop_key_from_mapping(leg)
                    if prop_key and (prop_key in used_prop_keys or prop_key in new_prop_keys):
                        continue

                    # Team constraint:
                    #   - Multi-game slate: default 2 per team (or config override)
                    #   - Single-game slate: per-leg-count cap from single_game_caps_by_legs
                    #     (typical: 3-leg=2, 4-leg=3, 5-leg=3). Falls back to legacy default of 4.
                    if single_game_slate and sg_cap_for_n is not None:
                        max_per_team = int(sg_cap_for_n)
                    else:
                        max_per_team = int(self.config.get("max_players_per_team", 4 if single_game_slate else 2))
                    if slip_team_counts.get(team, 0) >= max_per_team:
                        continue
                    if _cap_exceeded(leg, "max_role_shooter_overs", "single_game_role_shooter_over_flag"):
                        continue
                    if _cap_exceeded(leg, "max_fg3m_overs", "single_game_fg3m_over_flag"):
                        continue
                    if _cap_exceeded(leg, "max_low_minute_bench_overs", "single_game_low_minute_bench_over_flag"):
                        continue
                    if _cap_exceeded(leg, "max_low_line_noise_legs", "single_game_low_line_noise_flag"):
                        continue

                    # Add to slip
                    selected_legs.append(leg)
                    slip_teams.add(team)
                    slip_team_counts[team] = slip_team_counts.get(team, 0) + 1
                    new_players.add(player)
                    new_teams.add(team)
                    if prop_key:
                        new_prop_keys.add(prop_key)
                    selected += 1
                    
                    if selected == count:
                        break
                
                # Check if we got enough for this tier
                if selected < count:
                    return None  # Not enough qualifying legs for this tier

            # Calculate correlation-adjusted probability
            hit_prob = self._calculate_correlation_adjusted_probability(selected_legs)
            
            # Calculate payout using pp_kernel
            payout_mult = self._calculate_payout(selected_legs)
            
            n_legs = len(selected_legs)
            sg_ok, sg_reasons, sg_metrics = single_game_slip_rule_status(selected_legs, self.full_config, n_legs=n_legs)
            if not sg_ok and bool(self.config.get("enforce_single_game_slip_rules", True)):
                return None

            # Commit reservations only after the slip fully passes validation.
            # A rejected 4-leg must not consume props and starve later templates.
            used_players.update(new_players)
            used_teams.update(new_teams)
            used_prop_keys.update(new_prop_keys)

            # Apply empirical calibration so displayed probability matches actual win rate
            cal_factors = self.config.get("hit_prob_calibration", {})
            scale = cal_factors.get(n_legs) or cal_factors.get(str(n_legs)) or 1.0
            hit_prob_display = min(float(hit_prob) * float(scale), 0.99)

            slip = {
                "label": template_label,
                "legs": [leg.to_dict() for leg in selected_legs],
                "hit_prob": hit_prob_display,
                "hit_prob_raw": hit_prob,
                "payout_mult": payout_mult,
                "ev": hit_prob_display * payout_mult,
                "n_legs": n_legs
            }
            if sg_metrics:
                slip.update(sg_metrics)
                slip["single_game_rule_reasons"] = ",".join(sg_reasons)
            return slip
            
        except Exception:
            # Rollback on any error
            return None
    
    def _calculate_payout(self, legs: List[pd.Series]) -> float:
        """Calculate PrizePicks payout using pp_kernel coefficients."""
        try:
            from .pp_pricing import load_kernel, power_multiplier
            kernel = load_kernel()
            return power_multiplier(legs, kernel)
        except (ImportError, Exception):
            # Fallback to simple tier-based calculation
            tier_multipliers = {"GOBLIN": 1.8, "STANDARD": 2.0, "DEMON": 3.5}
            base_mult = _prod([tier_multipliers.get(leg["tier"], 2.0) for leg in legs])
            return base_mult ** (1.0 / len(legs))  # Geometric mean
    
    def build_slips(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Main entry point: build all marketed slips from scored legs.
        
        Returns list of slip dictionaries with metadata.
        """
        
        # Apply stat-specific calibration
        df = self._apply_stat_calibration(df)
        
        # Qualify legs for marketed slips
        pool = self._qualify_legs(df)
        
        if pool.empty:
            return []
        
        # Detect single-game slate using the full board (pre-filter), not the
        # qualified pool — a tight threshold on a multi-game day would otherwise
        # falsely trigger this and bypass team-diversity caps.
        unique_games = set()
        for _, row in df.iterrows():
            teams = tuple(sorted([str(row.get("team", "")), str(row.get("opp", ""))]))
            unique_games.add(teams)
        single_game_slate = (len(unique_games) == 1)
        if single_game_slate:
            labels = "/".join(str(t.get("label", "")).replace("-leg", "") for t in self.single_game_templates)
            print(f"[MARKETED] Single-game slate detected - using {labels}-leg templates and per-leg team caps")

        # Build slips following templates. Order matters because the 3-leg is
        # the primary marketed product and should get first construction pass.
        hc_thresholds = self.config.get("high_confidence_thresholds", {})

        reserve_players_across_templates = bool(self.config.get("reserve_players_across_templates", False))
        reserve_props_across_templates = bool(self.config.get("reserve_player_props_across_templates", True))
        used_players_global: set = set()
        used_prop_keys_global: set[str] = set()
        slips = []
        templates = self.single_game_templates if single_game_slate else self.templates
        for template in templates:
            used_players = used_players_global if reserve_players_across_templates else set()
            used_prop_keys = used_prop_keys_global if reserve_props_across_templates else set()
            slip = self._build_single_slip(
                pool,
                template,
                used_players,
                set(),
                single_game_slate=single_game_slate,
                used_prop_keys=used_prop_keys,
            )
            if slip:
                if reserve_players_across_templates:
                    used_players_global = used_players
                if reserve_props_across_templates:
                    used_prop_keys_global = used_prop_keys
                n = slip.get("n_legs", 0)
                bar = hc_thresholds.get(n) or hc_thresholds.get(str(n))
                # hit_prob is already calibrated (empirical scale applied in _build_single_slip)
                slip["high_confidence"] = (
                    bar is not None and slip.get("hit_prob", 0.0) >= float(bar)
                )
                slips.append(slip)
        
        return filter_marketed_slips(slips, self.full_config, family="Marketed")


def build_marketed_slips(
    df: pd.DataFrame, config: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], "pd.Series"]:
    """
    Convenience function to build marketed slips.

    Args:
        df: Scored legs DataFrame from Atlas engine
        config: Full Atlas configuration dictionary

    Returns:
        Tuple of (slips, p_cal_marketed_series) where p_cal_marketed_series is a
        float Series indexed by df.index — NaN for legs not processed by the
        marketed builder (non-marketed legs are never passed through calibration).
    """
    builder = MarketedSlipBuilder(config)
    # Run calibration on a copy to extract p_cal_marketed keyed to df.index.
    # build_slips() repeats this step internally (pure/deterministic), so the
    # double call is harmless.
    cal_df = builder._apply_stat_calibration(df)
    p_cal_marketed = cal_df["p_cal_marketed"].reindex(df.index)
    slips = builder.build_slips(df)
    return slips, p_cal_marketed

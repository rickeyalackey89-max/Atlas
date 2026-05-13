from __future__ import annotations

# ruff: noqa: E402

import unittest
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.core.slip_builders import build_slips_by_tier_buckets
from Atlas.core.slip_scoring import build_candidates, _score_slip
from Atlas.core.pp_pricing import load_kernel, power_multiplier
from Atlas.core.marketed_slip_builder import MarketedSlipBuilder, build_marketed_slips
from Atlas.core.slip_family_diversity import enforce_prop_diversity_across_frames


class SlipParityTest(unittest.TestCase):
    def test_candidate_builder_prefers_current_probability_surface(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "player": "Alpha Guard",
                    "stat": "PTS",
                    "line": 10.5,
                    "tier": "GOBLIN",
                    "projection_id": "g1",
                    "p_cal": 0.94,
                    "p_for_cal": 0.91,
                    "p_role": 0.88,
                    "p_adj": 0.61,
                    "p_eff": 0.11,
                    "fragility": 0.2,
                },
                {
                    "player": "Beta Guard",
                    "stat": "PTS",
                    "line": 10.5,
                    "tier": "GOBLIN",
                    "projection_id": "g2",
                    "p_cal": 0.21,
                    "p_for_cal": 0.21,
                    "p_role": 0.21,
                    "p_adj": 0.21,
                    "p_eff": 0.98,
                    "fragility": 0.2,
                },
                {
                    "player": "Standard Wing",
                    "stat": "REB",
                    "line": 5.5,
                    "tier": "STANDARD",
                    "projection_id": "s1",
                    "p_cal": 0.70,
                    "p_for_cal": 0.68,
                    "p_role": 0.66,
                    "p_adj": 0.52,
                    "p_eff": 0.15,
                    "fragility": 0.2,
                },
                {
                    "player": "Demon Center",
                    "stat": "AST",
                    "line": 4.5,
                    "tier": "DEMON",
                    "projection_id": "d1",
                    "p_cal": 0.74,
                    "p_for_cal": 0.72,
                    "p_role": 0.70,
                    "p_adj": 0.55,
                    "p_eff": 0.14,
                    "fragility": 0.2,
                },
            ]
        )

        candidates = build_candidates(scored, pool_size=10)
        self.assertEqual(candidates["projection_id"].head(4).tolist(), ["g1", "d1", "s1", "g2"])
        self.assertAlmostEqual(float(candidates.loc[candidates["projection_id"] == "g1", "p_eff"].iloc[0]), 0.94, places=12)
        self.assertAlmostEqual(float(candidates.loc[candidates["projection_id"] == "s1", "p_eff"].iloc[0]), 0.70, places=12)
        self.assertAlmostEqual(float(candidates.loc[candidates["projection_id"] == "d1", "p_eff"].iloc[0]), 0.74, places=12)

    def test_slip_builder_uses_new_probability_precedence_and_math_contract(self) -> None:
        legs_df = pd.DataFrame(
            [
                {
                    "player": "Alpha Guard",
                    "stat": "PTS",
                    "direction": "OVER",
                    "line": 10.5,
                    "tier": "GOBLIN",
                    "projection_id": "g1",
                    "p_cal": 0.94,
                    "p_for_cal": 0.91,
                    "p_role": 0.88,
                    "p_adj": 0.61,
                    "p_eff": 0.11,
                    "fragility": 0.2,
                },
                {
                    "player": "Beta Guard",
                    "stat": "PTS",
                    "direction": "OVER",
                    "line": 10.5,
                    "tier": "GOBLIN",
                    "projection_id": "g2",
                    "p_cal": 0.21,
                    "p_for_cal": 0.21,
                    "p_role": 0.21,
                    "p_adj": 0.21,
                    "p_eff": 0.98,
                    "fragility": 0.2,
                },
                {
                    "player": "Standard Wing",
                    "stat": "REB",
                    "direction": "OVER",
                    "line": 5.5,
                    "tier": "STANDARD",
                    "projection_id": "s1",
                    "p_cal": 0.70,
                    "p_for_cal": 0.68,
                    "p_role": 0.66,
                    "p_adj": 0.52,
                    "p_eff": 0.15,
                    "fragility": 0.2,
                },
                {
                    "player": "Demon Center",
                    "stat": "AST",
                    "direction": "OVER",
                    "line": 4.5,
                    "tier": "DEMON",
                    "projection_id": "d1",
                    "p_cal": 0.74,
                    "p_for_cal": 0.72,
                    "p_role": 0.70,
                    "p_adj": 0.55,
                    "p_eff": 0.14,
                    "fragility": 0.2,
                },
            ]
        )

        cfg = {
            "slip_build": {"target_pool_mult": 10, "phase1_frac": 0.2, "phase1_pool_frac": 0.5, "beam_width": 10, "max_slips_per_player": 4, "prefer_calibrated_prob": True, "penalty": {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0}},
            "slip_rank": {"ev_payout_power": 1},
        }

        out = build_slips_by_tier_buckets(
            legs_df=legs_df,
            n_legs=3,
            top_n=1,
            payout_power_mult=6.0,
            payout_flex=0.0,
            pricing_engine="atlas",
            cfg=cfg,
            seed=7,
            per_tier=10,
            max_attempts=1000,
            sort_mode="ev",
            mixes={3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1}},
            required_tiers=["GOBLIN", "STANDARD", "DEMON"],
            mix_ok_fn=lambda n, legs: True,
        )

        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["players"], ["alpha guard", "standard wing", "demon center"])
        self.assertIn("Alpha Guard OVER PTS 10.5 (GOBLIN) [id:g1]", str(out.iloc[0]["legs"]))
        self.assertAlmostEqual(float(out.iloc[0]["hit_prob"]), 0.94 * 0.70 * 0.74, places=12)
        self.assertAlmostEqual(float(out.iloc[0]["payout_mult_eff"]), 6.0, places=12)
        self.assertAlmostEqual(float(out.iloc[0]["ev_mult"]), float(out.iloc[0]["hit_prob"]) * 6.0, places=12)

        scored = _score_slip(legs_df.iloc[[0, 2, 3]].to_dict(orient="records"), 3, 6.0)
        self.assertAlmostEqual(scored["payout_mult_eff"], 6.0, places=12)
        self.assertAlmostEqual(scored["ev_mult"], scored["hit_prob"] * scored["payout_mult_eff"], places=12)

    def test_slip_builder_excludes_questionable_and_q_out_legs(self) -> None:
        legs_df = pd.DataFrame(
            [
                {"player": "Risk Goblin", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "rg", "team": "NYK", "p_cal": 0.99, "q_out_frac": 0.5, "is_questionable": 0},
                {"player": "Clean Goblin", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "cg", "team": "BOS", "p_cal": 0.88, "q_out_frac": 0.0, "is_questionable": 0},
                {"player": "Risk Standard", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "rs", "team": "MIA", "p_cal": 0.98, "q_out_frac": 0.0, "is_questionable": 1},
                {"player": "Clean Standard", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "cs", "team": "CLE", "p_cal": 0.80, "q_out_frac": 0.0, "is_questionable": 0},
                {"player": "Clean Demon", "stat": "AST", "direction": "OVER", "line": 4.5, "tier": "DEMON", "projection_id": "cd", "team": "LAL", "p_cal": 0.76, "q_out_frac": 0.0, "is_questionable": 0},
            ]
        )

        cfg = {
            "slip_build": {
                "target_pool_mult": 10,
                "phase1_frac": 0.2,
                "phase1_pool_frac": 0.5,
                "beam_width": 10,
                "prefer_calibrated_prob": True,
                "exclude_questionable": True,
                "exclude_q_out_frac_gt": 0.0,
                "penalty": {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0},
            },
            "slip_rank": {"ev_payout_power": 1},
        }

        out = build_slips_by_tier_buckets(
            legs_df=legs_df,
            n_legs=3,
            top_n=1,
            payout_power_mult=6.0,
            payout_flex=0.0,
            pricing_engine="atlas",
            cfg=cfg,
            seed=7,
            per_tier=10,
            max_attempts=100,
            sort_mode="ev",
            mixes={3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1}},
            required_tiers=["GOBLIN", "STANDARD", "DEMON"],
            mix_ok_fn=lambda n, legs: True,
        )

        self.assertEqual(len(out), 1)
        selected = str(out.iloc[0]["legs"])
        self.assertIn("Clean Goblin", selected)
        self.assertIn("Clean Standard", selected)
        self.assertNotIn("Risk Goblin", selected)
        self.assertNotIn("Risk Standard", selected)

    def test_slip_builder_minute_risk_guard_penalizes_selection_only(self) -> None:
        legs_df = pd.DataFrame(
            [
                {"player": "Clean Guard", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "cg", "team": "BOS", "p_cal": 0.88, "min_mean": 26.0, "min_std": 3.0},
                {"player": "Risk Standard", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "rs", "team": "MIA", "p_cal": 0.84, "min_mean": 14.0, "min_std": 7.0},
                {"player": "Clean Standard", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "cs", "team": "CLE", "p_cal": 0.83, "min_mean": 28.0, "min_std": 3.0},
                {"player": "Clean Demon", "stat": "AST", "direction": "OVER", "line": 4.5, "tier": "DEMON", "projection_id": "cd", "team": "LAL", "p_cal": 0.76, "min_mean": 22.0, "min_std": 4.0},
            ]
        )

        cfg = {
            "minute_risk_guard": {
                "enabled": True,
                "min_modeled_minutes": 16.0,
                "bench_minutes_threshold": 18.0,
                "max_minutes_cv": 0.35,
                "low_modeled_minutes_penalty": 0.10,
                "bench_under_18_min_penalty": 0.10,
                "minutes_cv_penalty": 0.08,
                "max_total_penalty": 0.25,
            },
            "slip_build": {
                "target_pool_mult": 10,
                "phase1_frac": 0.2,
                "phase1_pool_frac": 0.5,
                "beam_width": 10,
                "prefer_calibrated_prob": True,
                "penalty": {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0},
            },
            "slip_rank": {"ev_payout_power": 1},
        }

        out = build_slips_by_tier_buckets(
            legs_df=legs_df,
            n_legs=3,
            top_n=1,
            payout_power_mult=6.0,
            payout_flex=0.0,
            pricing_engine="atlas",
            cfg=cfg,
            seed=7,
            per_tier=10,
            max_attempts=100,
            sort_mode="ev",
            mixes={3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1}},
            required_tiers=["GOBLIN", "STANDARD", "DEMON"],
            mix_ok_fn=lambda n, legs: True,
        )

        self.assertEqual(len(out), 1)
        selected = str(out.iloc[0]["legs"])
        self.assertIn("Clean Standard", selected)
        self.assertNotIn("Risk Standard", selected)
        self.assertEqual(float(out.iloc[0]["pen_minute_risk"]), 0.0)

    def test_marketed_builder_minute_risk_guard_penalizes_marketed_score(self) -> None:
        builder = MarketedSlipBuilder(
            {
                "minute_risk_guard": {
                    "enabled": True,
                    "min_modeled_minutes": 16.0,
                    "bench_minutes_threshold": 18.0,
                    "max_minutes_cv": 0.35,
                    "low_modeled_minutes_penalty": 0.10,
                    "bench_under_18_min_penalty": 0.10,
                    "minutes_cv_penalty": 0.08,
                    "max_total_penalty": 0.25,
                },
                "marketed_slips": {},
            }
        )
        df = pd.DataFrame(
            [
                {"player": "Risk Guard", "stat": "PTS", "direction": "OVER", "tier": "STANDARD", "p_cal": 0.86, "l20_edge": 1.0, "min_mean": 14.0, "min_std": 7.0},
                {"player": "Clean Guard", "stat": "PTS", "direction": "OVER", "tier": "STANDARD", "p_cal": 0.80, "l20_edge": 1.0, "min_mean": 28.0, "min_std": 3.0},
            ]
        )

        out = builder._apply_stat_calibration(df)

        risk_score = float(out.loc[out["player"] == "Risk Guard", "marketed_score"].iloc[0])
        clean_score = float(out.loc[out["player"] == "Clean Guard", "marketed_score"].iloc[0])
        risk_penalty = float(out.loc[out["player"] == "Risk Guard", "minute_risk_penalty"].iloc[0])
        self.assertGreater(risk_penalty, 0.0)
        self.assertLess(risk_score, clean_score)

    def test_marketed_builder_builds_conservative_slips_first(self) -> None:
        builder = MarketedSlipBuilder({"marketed_slips": {}})
        self.assertEqual([template["label"] for template in builder.templates], ["3-leg", "4-leg", "5-leg"])

    def test_marketed_builder_does_not_reserve_players_across_templates_by_default(self) -> None:
        builder = MarketedSlipBuilder({"marketed_slips": {}})
        self.assertFalse(bool(builder.config.get("reserve_players_across_templates", False)))

    def test_prop_diversity_keeps_exact_prop_once_per_family(self) -> None:
        row_a = {
            "n_legs": 3,
            "legs": "Dean Wade OVER REB 5.5 (GOBLIN) [id:1] | Alpha OVER PTS 10.5 (STANDARD) [id:2]",
        }
        row_b = {
            "n_legs": 4,
            "legs": "Dean Wade OVER REB 5.5 (GOBLIN) [id:1] | Beta OVER AST 2.5 (STANDARD) [id:3]",
        }
        row_c = {
            "n_legs": 4,
            "legs": "Dean Wade OVER PTS 5.5 (GOBLIN) [id:4] | Beta OVER AST 2.5 (STANDARD) [id:3]",
        }

        out3, out4 = enforce_prop_diversity_across_frames(
            [pd.DataFrame([row_a]), pd.DataFrame([row_b, row_c])],
            limits=[1, 1],
            max_repeats=1,
        )

        self.assertEqual(len(out3), 1)
        self.assertEqual(len(out4), 1)
        self.assertIn("Dean Wade OVER PTS 5.5", str(out4.iloc[0]["legs"]))

    def test_marketed_builder_reserves_exact_props_across_templates(self) -> None:
        builder = MarketedSlipBuilder({"marketed_slips": {"reserve_player_props_across_templates": True}})
        pool = pd.DataFrame(
            [
                {"player": "Dean Wade", "team": "CLE", "opp": "NYK", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "GOBLIN", "p_cal_marketed": 0.8, "marketed_score": 0.9},
                {"player": "Dean Wade", "team": "CLE", "opp": "NYK", "stat": "PTS", "direction": "OVER", "line": 5.5, "tier": "GOBLIN", "p_cal_marketed": 0.8, "marketed_score": 0.8},
                {"player": "Alpha", "team": "CLE", "opp": "NYK", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "STANDARD", "p_cal_marketed": 0.7, "marketed_score": 0.7},
                {"player": "Beta", "team": "NYK", "opp": "CLE", "stat": "AST", "direction": "OVER", "line": 2.5, "tier": "STANDARD", "p_cal_marketed": 0.7, "marketed_score": 0.6},
                {"player": "Gamma", "team": "NYK", "opp": "CLE", "stat": "REB", "direction": "OVER", "line": 4.5, "tier": "STANDARD", "p_cal_marketed": 0.7, "marketed_score": 0.5},
                {"player": "Delta", "team": "CLE", "opp": "NYK", "stat": "PA", "direction": "OVER", "line": 9.5, "tier": "STANDARD", "p_cal_marketed": 0.7, "marketed_score": 0.4},
            ]
        )
        used_props: set[str] = set()

        first = builder._build_single_slip(
            pool,
            {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
            set(),
            set(),
            used_prop_keys=used_props,
        )
        second = builder._build_single_slip(
            pool,
            {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
            set(),
            set(),
            used_prop_keys=used_props,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first["legs"][0]["stat"], "REB")
        self.assertEqual(second["legs"][0]["stat"], "PTS")

    def test_marketed_builder_rejected_single_game_slip_does_not_reserve_props(self) -> None:
        builder = MarketedSlipBuilder(
            {
                "single_game_mode": {
                    "slip_rules": {
                        "enabled": True,
                        "require_one_stable_anchor": True,
                    },
                },
                "marketed_slips": {"enforce_single_game_slip_rules": True},
            }
        )
        pool = pd.DataFrame(
            [
                {"player": "Alpha", "team": "MIN", "opp": "SAS", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "GOBLIN", "p_cal": 0.8, "p_cal_marketed": 0.8, "marketed_score": 0.9, "single_game_profile_active": True, "single_game_anchor_flag": 0},
                {"player": "Beta", "team": "SAS", "opp": "MIN", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "STANDARD", "p_cal": 0.7, "p_cal_marketed": 0.7, "marketed_score": 0.8, "single_game_profile_active": True, "single_game_anchor_flag": 0},
                {"player": "Gamma", "team": "MIN", "opp": "SAS", "stat": "AST", "direction": "OVER", "line": 2.5, "tier": "STANDARD", "p_cal": 0.7, "p_cal_marketed": 0.7, "marketed_score": 0.7, "single_game_profile_active": True, "single_game_anchor_flag": 0},
            ]
        )
        used_props: set[str] = set()

        slip = builder._build_single_slip(
            pool,
            {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
            set(),
            set(),
            single_game_slate=True,
            used_prop_keys=used_props,
        )

        self.assertIsNone(slip)
        self.assertEqual(used_props, set())

    def test_marketed_pool_collapse_uses_probability_tie_breaks(self) -> None:
        builder = MarketedSlipBuilder(
            {
                "marketed_slips": {
                    "excluded_stats": [],
                    "min_thresholds": {"GOBLIN": 0.0, "STANDARD": 0.0, "DEMON": 0.0},
                    "min_raw_thresholds": {"GOBLIN": 0.0, "STANDARD": 0.0, "DEMON": 0.0},
                }
            }
        )
        df = pd.DataFrame(
            [
                {
                    "player": "De'Aaron Fox",
                    "team": "SAS",
                    "opp": "MIN",
                    "stat": "PTS",
                    "direction": "OVER",
                    "line": 14.5,
                    "tier": "GOBLIN",
                    "p_cal": 0.74,
                    "p_cal_marketed": 0.74,
                    "marketed_score": 0.10,
                },
                {
                    "player": "De'Aaron Fox",
                    "team": "SAS",
                    "opp": "MIN",
                    "stat": "PR",
                    "direction": "OVER",
                    "line": 14.5,
                    "tier": "GOBLIN",
                    "p_cal": 0.84,
                    "p_cal_marketed": 0.84,
                    "marketed_score": 0.10,
                },
            ]
        )

        pool = builder._qualify_legs(df)

        self.assertEqual(len(pool), 1)
        self.assertEqual(str(pool.iloc[0]["stat"]), "PR")
        self.assertAlmostEqual(float(pool.iloc[0]["p_cal"]), 0.84)

    def test_marketed_builder_keeps_single_game_soft_exposure_but_drops_true_questionable(self) -> None:
        builder = MarketedSlipBuilder(
            {
                "single_game_mode": {
                    "enabled": "auto",
                    "trigger_max_games": 1,
                    "soft_injury_exposure_not_hard_exclude": True,
                },
                "marketed_slips": {
                    "exclude_questionable": True,
                    "exclude_q_out_frac_gt": 0.0,
                    "excluded_stats": [],
                    "min_thresholds": {"GOBLIN": 0.0, "STANDARD": 0.0, "DEMON": 0.0},
                    "min_raw_thresholds": {"GOBLIN": 0.0, "STANDARD": 0.0, "DEMON": 0.0},
                },
            }
        )
        df = pd.DataFrame(
            [
                {
                    "player": "Soft Exposure",
                    "team": "MIN",
                    "opp": "SAS",
                    "game_id": "g1",
                    "stat": "REB",
                    "direction": "OVER",
                    "line": 5.5,
                    "tier": "GOBLIN",
                    "projection_id": "soft",
                    "p_cal": 0.80,
                    "l20_edge": 1.0,
                    "is_questionable": 1,
                    "q_out_frac": 0.5,
                    "role_ctx_outs": '["DiVincenzo, Donte"]',
                },
                {
                    "player": "True Questionable",
                    "team": "SAS",
                    "opp": "MIN",
                    "game_id": "g1",
                    "stat": "REB",
                    "direction": "OVER",
                    "line": 5.5,
                    "tier": "GOBLIN",
                    "projection_id": "trueq",
                    "p_cal": 0.90,
                    "l20_edge": 1.0,
                    "is_questionable": 1,
                    "q_out_frac": 0.5,
                    "role_ctx_outs": "[]",
                },
            ]
        )

        pool = builder._qualify_legs(builder._apply_stat_calibration(df))

        self.assertIn("Soft Exposure", set(pool["player"]))
        self.assertNotIn("True Questionable", set(pool["player"]))

    def test_marketed_builder_excludes_questionable_and_q_out_legs(self) -> None:
        legs_df = pd.DataFrame(
            [
                {"player": "Risk Goblin", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "rg", "team": "NYK", "opp": "BOS", "p_cal": 0.99, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.5, "is_questionable": 0},
                {"player": "Clean Goblin A", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "cga", "team": "BOS", "opp": "NYK", "p_cal": 0.88, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.0, "is_questionable": 0},
                {"player": "Clean Goblin B", "stat": "REB", "direction": "OVER", "line": 4.5, "tier": "GOBLIN", "projection_id": "cgb", "team": "CLE", "opp": "MIA", "p_cal": 0.86, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.0, "is_questionable": 0},
                {"player": "Risk Standard", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "rs", "team": "MIA", "opp": "CLE", "p_cal": 0.98, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.0, "is_questionable": 1},
                {"player": "Clean Standard A", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "csa", "team": "LAL", "opp": "DEN", "p_cal": 0.80, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.0, "is_questionable": 0},
                {"player": "Clean Standard B", "stat": "AST", "direction": "OVER", "line": 3.5, "tier": "STANDARD", "projection_id": "csb", "team": "DEN", "opp": "LAL", "p_cal": 0.78, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.0, "is_questionable": 0},
                {"player": "Clean Demon", "stat": "AST", "direction": "OVER", "line": 4.5, "tier": "DEMON", "projection_id": "cd", "team": "OKC", "opp": "MIN", "p_cal": 0.76, "l20_edge": 1.0, "player_dir_te": 1.0, "q_out_frac": 0.0, "is_questionable": 0},
            ]
        )

        slips, _ = build_marketed_slips(
            legs_df,
            {
                "marketed_slips": {
                    "excluded_stats": [],
                    "min_thresholds": {"GOBLIN": 0.0, "STANDARD": 0.0, "DEMON": 0.0},
                    "min_raw_thresholds": {"GOBLIN": 0.0, "STANDARD": 0.0, "DEMON": 0.0},
                    "direction_filters": {"GOBLIN": ["OVER"], "STANDARD": ["OVER"], "DEMON": ["OVER"]},
                    "exclude_questionable": True,
                    "exclude_q_out_frac_gt": 0.0,
                    "max_players_per_team": 2,
                }
            },
        )

        selected_players = {leg["player"] for slip in slips for leg in slip["legs"]}
        self.assertTrue(selected_players)
        self.assertNotIn("Risk Goblin", selected_players)
        self.assertNotIn("Risk Standard", selected_players)

    def test_pp_kernel_prefers_calibrated_probability_surface(self) -> None:
        kernel = load_kernel(
            {
                "pp_kernel": {
                    "p_min": 0.01,
                    "p_max": 0.99,
                    "coeffs": {
                        "DEFAULT": {
                            "GOBLIN": {"a": 0.0, "b": 1.0},
                            "STANDARD": {"a": 0.0, "b": 0.0},
                            "DEMON": {"a": 0.0, "b": 0.0},
                        }
                    },
                }
            }
        )

        mult = power_multiplier(
            base_mult=1.0,
            legs=[
                {"tier": "GOBLIN", "stat": "PTS", "p_cal": 0.80, "p_adj": 0.20},
                {"tier": "STANDARD", "stat": "REB", "p_cal": 0.50, "p_adj": 0.50},
                {"tier": "DEMON", "stat": "AST", "p_cal": 0.50, "p_adj": 0.50},
            ],
            kernel=kernel,
        )

        self.assertAlmostEqual(mult, 0.80 / 0.20, places=12)

    def test_pp_kernel_prefers_close_role_surface_when_present(self) -> None:
        kernel = load_kernel(
            {
                "pp_kernel": {
                    "p_min": 0.01,
                    "p_max": 0.99,
                    "coeffs": {
                        "DEFAULT": {
                            "GOBLIN": {"a": 0.0, "b": 1.0},
                            "STANDARD": {"a": 0.0, "b": 0.0},
                            "DEMON": {"a": 0.0, "b": 0.0},
                        }
                    },
                }
            }
        )

        mult = power_multiplier(
            base_mult=1.0,
            legs=[
                {"tier": "GOBLIN", "stat": "PTS", "p_close_role": 0.75, "p_role": 0.20, "p_adj": 0.30},
                {"tier": "STANDARD", "stat": "REB", "p_close_role": 0.50, "p_role": 0.50, "p_adj": 0.50},
                {"tier": "DEMON", "stat": "AST", "p_close_role": 0.50, "p_role": 0.50, "p_adj": 0.50},
            ],
            kernel=kernel,
        )

        self.assertAlmostEqual(mult, 3.0, places=12)

    def test_diversification_penalty_scales_by_leg_count(self) -> None:
        cfg = {
            "slip_build": {
                "target_pool_mult": 10,
                "phase1_frac": 0.2,
                "phase1_pool_frac": 0.5,
                "beam_width": 10,
                "max_slips_per_player": 4,
                "penalty": {"team_w": 0.1, "family_w": 0.0, "frag_w": 0.0, "team_power": 2.0, "family_power": 2.0, "frag_power": 1.0},
            },
            "slip_rank": {"ev_payout_power": 1},
        }

        def build_df(rows: list[dict[str, object]]) -> pd.DataFrame:
            return pd.DataFrame(rows)

        three_leg = build_slips_by_tier_buckets(
            legs_df=build_df(
                [
                    {"player": "A", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "a", "team": "NYK", "p_cal": 0.9, "fragility": 0.2},
                    {"player": "B", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "b", "team": "NYK", "p_cal": 0.8, "fragility": 0.2},
                    {"player": "C", "stat": "AST", "direction": "OVER", "line": 4.5, "tier": "DEMON", "projection_id": "c", "team": "BOS", "p_cal": 0.7, "fragility": 0.2},
                ]
            ),
            n_legs=3,
            top_n=1,
            payout_power_mult=6.0,
            payout_flex=0.0,
            pricing_engine="atlas",
            cfg=cfg,
            seed=7,
            per_tier=10,
            max_attempts=100,
            sort_mode="ev",
            mixes={3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1}},
            required_tiers=["GOBLIN", "STANDARD", "DEMON"],
            mix_ok_fn=lambda n, legs: True,
        )

        five_leg = build_slips_by_tier_buckets(
            legs_df=build_df(
                [
                    {"player": "A", "stat": "PTS", "direction": "OVER", "line": 10.5, "tier": "GOBLIN", "projection_id": "a", "team": "NYK", "p_cal": 0.9, "fragility": 0.2},
                    {"player": "B", "stat": "PTS", "direction": "OVER", "line": 9.5, "tier": "GOBLIN", "projection_id": "b", "team": "LAL", "p_cal": 0.85, "fragility": 0.2},
                    {"player": "C", "stat": "REB", "direction": "OVER", "line": 5.5, "tier": "STANDARD", "projection_id": "c", "team": "NYK", "p_cal": 0.8, "fragility": 0.2},
                    {"player": "D", "stat": "AST", "direction": "OVER", "line": 4.5, "tier": "STANDARD", "projection_id": "d", "team": "BOS", "p_cal": 0.75, "fragility": 0.2},
                    {"player": "E", "stat": "PTS", "direction": "OVER", "line": 6.5, "tier": "DEMON", "projection_id": "e", "team": "MIA", "p_cal": 0.7, "fragility": 0.2},
                ]
            ),
            n_legs=5,
            top_n=1,
            payout_power_mult=20.0,
            payout_flex=0.0,
            pricing_engine="atlas",
            cfg=cfg,
            seed=7,
            per_tier=10,
            max_attempts=100,
            sort_mode="ev",
            mixes={5: {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1}},
            required_tiers=["GOBLIN", "STANDARD", "DEMON"],
            mix_ok_fn=lambda n, legs: True,
        )

        self.assertAlmostEqual(float(three_leg.iloc[0]["pen_team"]), 0.1 * (1 / 2) ** 2, places=12)
        self.assertAlmostEqual(float(five_leg.iloc[0]["pen_team"]), 0.1 * (1 / 4) ** 2, places=12)
        self.assertGreater(float(three_leg.iloc[0]["pen_team"]), float(five_leg.iloc[0]["pen_team"]))


if __name__ == "__main__":
    unittest.main()

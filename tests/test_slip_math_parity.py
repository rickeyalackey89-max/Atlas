from __future__ import annotations

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
            "slip_build": {"target_pool_mult": 10, "phase1_frac": 0.2, "phase1_pool_frac": 0.5, "beam_width": 10, "max_slips_per_player": 4, "penalty": {"team_w": 0.0, "family_w": 0.0, "frag_w": 0.0}},
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
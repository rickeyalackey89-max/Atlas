from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.engine.new_probability import _apply_under_relief, simulate_leg_probability_new
from Atlas.core.minutes import adjust_probability_for_blowout


class UnderReliefTest(unittest.TestCase):
    def test_blowout_adjustment_is_direction_aware(self) -> None:
        over = adjust_probability_for_blowout(0.58, 0.5, 0.8, direction="OVER")
        under = adjust_probability_for_blowout(0.58, 0.5, 0.8, direction="UNDER")

        self.assertLess(over, 0.58)
        self.assertGreater(under, 0.58)

    def test_under_relief_is_bounded_and_conservative(self) -> None:
        adjusted, eligible, haircut, factor, haircut_min, q_min = _apply_under_relief(
            p_role=0.67,
            p_adj=0.52,
            direction="UNDER",
            stat_u="PTS",
            q=0.25,
            cfg={"under_relief_factor": 0.10, "under_relief_haircut_min": 0.05, "under_relief_q_min": 0.10},
        )

        self.assertTrue(eligible)
        self.assertAlmostEqual(haircut, 0.15, places=12)
        self.assertAlmostEqual(factor, 0.10, places=12)
        self.assertAlmostEqual(haircut_min, 0.05, places=12)
        self.assertAlmostEqual(q_min, 0.10, places=12)
        self.assertAlmostEqual(adjusted, 0.535, places=12)
        self.assertGreater(adjusted, 0.52)
        self.assertLess(adjusted, 0.67)

    def test_under_relief_defaults_to_small_retained_share(self) -> None:
        adjusted, eligible, haircut, factor, _, _ = _apply_under_relief(
            p_role=0.67,
            p_adj=0.52,
            direction="UNDER",
            stat_u="PTS",
            q=0.25,
            cfg={},
        )

        self.assertTrue(eligible)
        self.assertAlmostEqual(haircut, 0.15, places=12)
        self.assertAlmostEqual(factor, 0.10, places=12)
        self.assertAlmostEqual(adjusted, 0.535, places=12)
        self.assertLess(adjusted, 0.67)
        self.assertGreater(adjusted, 0.52)

    def test_final_probability_preserves_under_relief_when_blowout_sensitivity_is_tilted(self) -> None:
        gamelogs = pd.DataFrame(
            [
                {"player": "Test Player", "game_date": "2026-03-01", "minutes": 36, "points": 28},
                {"player": "Test Player", "game_date": "2026-02-27", "minutes": 35, "points": 30},
                {"player": "Test Player", "game_date": "2026-02-24", "minutes": 37, "points": 24},
                {"player": "Test Player", "game_date": "2026-02-21", "minutes": 34, "points": 27},
                {"player": "Test Player", "game_date": "2026-02-18", "minutes": 38, "points": 32},
            ]
        )
        row = pd.Series(
            {
                "player": "Test Player",
                "stat": "PTS",
                "line": 28.5,
                "direction": "UNDER",
                "team": "BOS",
                "spread": -11.5,
                "minutes_projection": 36.0,
            }
        )

        out = simulate_leg_probability_new(
            gamelogs=gamelogs,
            row=row,
            lookback=5,
            sims=4000,
            spread_sd=6.0,
            blowout_threshold=10.0,
            star_minute_drop=4.0,
            role_minute_drop=2.0,
            role_cfg={},
        )

        self.assertTrue(out["under_relief_applied"])
        self.assertLess(out["under_blowout_sens_mult"], 0.75)
        self.assertGreater(out["under_relief_haircut"], 0.0)
        self.assertGreater(out["p_adj"], out["p_adj_pre_under_relief"])

    def test_under_kernel_uses_neutral_blowout_path_before_relief(self) -> None:
        gamelogs = pd.DataFrame(
            [
                {"player": "Test Player", "game_date": "2026-03-01", "minutes": 36, "points": 28},
                {"player": "Test Player", "game_date": "2026-02-27", "minutes": 35, "points": 30},
                {"player": "Test Player", "game_date": "2026-02-24", "minutes": 37, "points": 24},
                {"player": "Test Player", "game_date": "2026-02-21", "minutes": 34, "points": 27},
                {"player": "Test Player", "game_date": "2026-02-18", "minutes": 38, "points": 32},
            ]
        )
        row = pd.Series(
            {
                "player": "Test Player",
                "stat": "PTS",
                "line": 28.5,
                "direction": "UNDER",
                "team": "BOS",
                "spread": -11.5,
                "minutes_projection": 36.0,
            }
        )

        out = simulate_leg_probability_new(
            gamelogs=gamelogs,
            row=row,
            lookback=5,
            sims=4000,
            spread_sd=6.0,
            blowout_threshold=10.0,
            star_minute_drop=4.0,
            role_minute_drop=2.0,
            role_cfg={},
        )

        expected_neutral = adjust_probability_for_blowout(
            p_raw=out["p_role"],
            blowout_risk=out["q_blowout"],
            sens=out["minutes_s_blowout"],
        )
        expected_directional_under = adjust_probability_for_blowout(
            p_raw=out["p_role"],
            blowout_risk=out["q_blowout"],
            sens=out["minutes_s_blowout"],
            direction="UNDER",
        )

        self.assertAlmostEqual(out["p_adj_pre_under_relief"], expected_neutral, places=12)
        self.assertGreater(expected_directional_under, expected_neutral)
        self.assertLess(out["p_adj_pre_under_relief"], expected_directional_under)

    def test_combo_over_high_q_gets_extra_blowout_relief(self) -> None:
        gamelogs = pd.DataFrame(
            [
                {"player": "Test Player", "game_date": "2026-03-01", "minutes": 36, "points": 28},
                {"player": "Test Player", "game_date": "2026-02-27", "minutes": 35, "points": 30},
                {"player": "Test Player", "game_date": "2026-02-24", "minutes": 37, "points": 24},
                {"player": "Test Player", "game_date": "2026-02-21", "minutes": 34, "points": 27},
                {"player": "Test Player", "game_date": "2026-02-18", "minutes": 38, "points": 32},
            ]
        )
        row = pd.Series(
            {
                "player": "Test Player",
                "stat": "PTS",
                "line": 28.5,
                "direction": "OVER",
                "team": "BOS",
                "spread": -11.5,
                "minutes_projection": 36.0,
            }
        )

        out = simulate_leg_probability_new(
            gamelogs=gamelogs,
            row=row,
            lookback=5,
            sims=4000,
            spread_sd=6.0,
            blowout_threshold=10.0,
            star_minute_drop=4.0,
            role_minute_drop=2.0,
            role_cfg={},
        )

        self.assertAlmostEqual(out["minutes_s"], 0.6, places=12)
        self.assertAlmostEqual(out["under_blowout_sens_mult"], 0.64, places=12)
        self.assertAlmostEqual(out["minutes_s_blowout"], 0.384, places=12)

    def test_blowout_adjustment_rules_soften_upstream_over_profile(self) -> None:
        gamelogs = pd.DataFrame(
            [
                {"player": "Test Player", "game_date": "2026-03-01", "minutes": 36, "points": 28},
                {"player": "Test Player", "game_date": "2026-02-27", "minutes": 35, "points": 30},
                {"player": "Test Player", "game_date": "2026-02-24", "minutes": 37, "points": 24},
                {"player": "Test Player", "game_date": "2026-02-21", "minutes": 34, "points": 27},
                {"player": "Test Player", "game_date": "2026-02-18", "minutes": 38, "points": 32},
            ]
        )
        row = pd.Series(
            {
                "player": "Test Player",
                "stat": "PTS",
                "line": 28.5,
                "direction": "OVER",
                "team": "BOS",
                "spread": -11.5,
                "minutes_projection": 36.0,
            }
        )

        baseline = simulate_leg_probability_new(
            gamelogs=gamelogs,
            row=row,
            lookback=5,
            sims=4000,
            spread_sd=6.0,
            blowout_threshold=10.0,
            star_minute_drop=4.0,
            role_minute_drop=2.0,
            role_cfg={},
        )
        adjusted = simulate_leg_probability_new(
            gamelogs=gamelogs,
            row=row,
            lookback=5,
            sims=4000,
            spread_sd=6.0,
            blowout_threshold=10.0,
            star_minute_drop=4.0,
            role_minute_drop=2.0,
            role_cfg={},
            blowout_cfg={
                "adjustment_rules": [
                    {
                        "name": "combo_over_soften_high_q",
                        "direction": "OVER",
                        "families": ["combo_scoring"],
                        "min_q": 0.30,
                        "minute_drop_mult": 0.50,
                        "sensitivity_mult": 0.80,
                    }
                ]
            },
        )

        self.assertEqual(adjusted["blowout_rule_count"], 1)
        self.assertEqual(adjusted["blowout_rules_applied"], "combo_over_soften_high_q")
        self.assertLess(adjusted["blowout_minute_drop"], baseline["blowout_minute_drop"])
        self.assertLess(adjusted["minutes_s_blowout"], baseline["minutes_s_blowout"])
        self.assertAlmostEqual(adjusted["q_blowout"], baseline["q_blowout"], places=12)


if __name__ == "__main__":
    unittest.main()

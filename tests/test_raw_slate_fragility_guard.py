from __future__ import annotations

import unittest

import pandas as pd

from Atlas.core.raw_slate_fragility_guard import apply_raw_slate_fragility_guard


class RawSlateFragilityGuardTest(unittest.TestCase):
    def _cfg(self) -> dict:
        return {
            "raw_slate_fragility_guard": {
                "enabled": True,
                "max_games": 2,
                "min_q_out_frac_mean": 0.10,
                "min_q_blowout_p90": 0.50,
                "high_prob_threshold": 0.55,
                "logit_shift": -0.10,
                "over_logit_shift": -0.15,
                "under_logit_shift": 0.10,
            }
        }

    def test_thin_qout_blowout_slate_direction_shifts_only_qout_or_highp(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "a", "b", "b"],
                "q_out_frac": [0.20, 0.20, 0.0, 0.0],
                "q_blowout": [0.60, 0.60, 0.60, 0.60],
                "direction": ["OVER", "UNDER", "OVER", "OVER"],
                "p_adj": [0.60, 0.50, 0.56, 0.40],
                "p_for_cal": [0.60, 0.50, 0.56, 0.40],
                "p_cal": [0.60, 0.50, 0.56, 0.40],
            }
        )

        out = apply_raw_slate_fragility_guard(df, self._cfg())

        self.assertTrue(bool(out["raw_slate_fragility_guard_triggered"].iloc[0]))
        self.assertEqual(int(out["raw_slate_fragility_guard_shifted_count"].iloc[0]), 3)
        self.assertEqual(int(out["raw_slate_fragility_guard_over_shifted_count"].iloc[0]), 2)
        self.assertEqual(int(out["raw_slate_fragility_guard_under_shifted_count"].iloc[0]), 1)
        self.assertLess(float(out.loc[0, "p_for_cal"]), 0.60)
        self.assertGreater(float(out.loc[1, "p_for_cal"]), 0.50)
        self.assertLess(float(out.loc[2, "p_for_cal"]), 0.56)
        self.assertEqual(float(out.loc[3, "p_for_cal"]), 0.40)
        self.assertEqual(float(out.loc[0, "p_adj"]), 0.60)

    def test_two_game_clean_slate_stays_inactive(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "a", "b", "b"],
                "q_out_frac": [0.0, 0.0, 0.0, 0.0],
                "q_blowout": [0.60, 0.60, 0.60, 0.60],
                "direction": ["OVER", "UNDER", "OVER", "OVER"],
                "p_for_cal": [0.60, 0.50, 0.56, 0.40],
                "p_cal": [0.60, 0.50, 0.56, 0.40],
            }
        )

        out = apply_raw_slate_fragility_guard(df, self._cfg())

        self.assertFalse(bool(out["raw_slate_fragility_guard_triggered"].iloc[0]))
        self.assertEqual(float(out.loc[0, "p_for_cal"]), 0.60)
        self.assertEqual(int(out["raw_slate_fragility_guard_shifted_count"].iloc[0]), 0)


if __name__ == "__main__":
    unittest.main()

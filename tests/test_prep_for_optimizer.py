from __future__ import annotations

import unittest

import pandas as pd

from Atlas.stages.prep_for_optimizer.prep_for_optimizer import run_prep_for_optimizer


class PrepForOptimizerTest(unittest.TestCase):
    def test_does_not_double_apply_precat_external_prior_surface(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "player": "Alpha Guard",
                    "team": "MIN",
                    "stat": "PTS",
                    "line": 10.5,
                    "direction": "OVER",
                    "tier": "GOBLIN",
                    "p_adj": 0.55,
                    "p_cal": 0.56,
                    "p_for_cal": 0.55,
                    "data_health_flag": "OK",
                    "external_prior_n": 1,
                    "external_prior_score": 0.80,
                    "external_prior_delta_p": 0.04,
                    "external_prior_probability_applied": True,
                }
            ]
        )

        _, scored_for_optimizer = run_prep_for_optimizer(scored, {}, pd.DataFrame())

        self.assertAlmostEqual(float(scored_for_optimizer["p_adj"].iloc[0]), 0.55, places=12)
        self.assertTrue(bool(scored_for_optimizer["external_prior_probability_applied"].iloc[0]))


if __name__ == "__main__":
    unittest.main()

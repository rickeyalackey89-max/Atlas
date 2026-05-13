from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from Atlas.engine.catboost_calibrator import _build_feature_df_regressor, resolve_residual_scale


class CatBoostResidualPolicyTest(unittest.TestCase):
    def _cfg(self) -> dict:
        return {
            "residual_scale_policy": {
                "enabled": True,
                "aggressive_residual_scale": 0.55,
                "defensive_residual_scale": 0.10,
                "thin_slate_games_max": 2,
                "thin_slate_q_out_frac_mean_min": 0.05,
                "thin_slate_q_blowout_p90_min": 0.45,
                "blowout_q_p90_min": 0.55,
                "blowout_role_ctx_share_max": 0.30,
                "no_role_ctx_share_max": 0.01,
                "low_external_prior_bp_has_mean_max": 0.10,
            }
        }

    def test_thin_injury_slate_uses_defensive_scale(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "a", "b", "b"],
                "q_out_frac": [0.20, 0.20, 0.20, 0.20],
                "q_blowout": [0.40, 0.50, 0.60, 0.70],
                "role_ctx_outs_used": [1, 0, 1, 0],
                "bp_has": [1, 1, 1, 1],
            }
        )

        scale, metrics = resolve_residual_scale(df, self._cfg(), {}, fallback_scale=0.50)

        self.assertEqual(scale, 0.10)
        self.assertTrue(metrics["policy_triggered"])
        self.assertIn("thin_injury_uncertainty", metrics["policy_reasons"])

    def test_thin_injury_low_tail_pressure_keeps_aggressive_scale(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "a", "b", "b"],
                "q_out_frac": [0.50, 0.50, 0.50, 0.50],
                "q_blowout": [0.20, 0.25, 0.20, 0.25],
                "role_ctx_outs_used": [1, 0, 1, 0],
                "bp_has": [1, 1, 1, 1],
            }
        )

        scale, metrics = resolve_residual_scale(df, self._cfg(), {}, fallback_scale=0.50)

        self.assertEqual(scale, 0.55)
        self.assertFalse(metrics["policy_triggered"])

    def test_thin_clean_slate_keeps_aggressive_scale(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "a", "b", "b"],
                "q_out_frac": [0.0, 0.0, 0.0, 0.0],
                "q_blowout": [0.20, 0.30, 0.20, 0.30],
                "role_ctx_outs_used": [1, 0, 1, 0],
                "bp_has": [1, 1, 1, 1],
            }
        )

        scale, metrics = resolve_residual_scale(df, self._cfg(), {}, fallback_scale=0.50)

        self.assertEqual(scale, 0.55)
        self.assertFalse(metrics["policy_triggered"])

    def test_no_role_low_external_prior_uses_defensive_scale(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "b", "c", "d"],
                "q_out_frac": [0.0, 0.0, 0.0, 0.0],
                "q_blowout": [0.10, 0.20, 0.30, 0.40],
                "role_ctx_outs_used": [0, 0, 0, 0],
                "bp_has": [0, 0, 0, 0],
            }
        )

        scale, metrics = resolve_residual_scale(df, self._cfg(), {}, fallback_scale=0.50)

        self.assertEqual(scale, 0.10)
        self.assertIn("no_role_low_external_prior", metrics["policy_reasons"])

    def test_external_prior_n_is_bp_has_fallback_for_policy_metrics(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "b", "c", "d"],
                "q_out_frac": [0.0, 0.0, 0.0, 0.0],
                "q_blowout": [0.10, 0.20, 0.30, 0.40],
                "role_ctx_outs_used": [0, 0, 0, 0],
                "external_prior_n": [2, 1, 1, 3],
            }
        )

        scale, metrics = resolve_residual_scale(df, self._cfg(), {}, fallback_scale=0.50)

        self.assertEqual(scale, 0.55)
        self.assertFalse(metrics["policy_triggered"])
        self.assertEqual(float(metrics["bp_has_mean"]), 1.0)

    def test_blowout_limited_role_context_uses_defensive_scale(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": ["a", "b", "c", "d"],
                "q_out_frac": [0.0, 0.0, 0.0, 0.0],
                "q_blowout": [0.40, 0.60, 0.70, 0.80],
                "role_ctx_outs_used": [1, 0, 0, 0],
                "bp_has": [1, 1, 1, 1],
            }
        )

        scale, metrics = resolve_residual_scale(df, self._cfg(), {}, fallback_scale=0.50)

        self.assertEqual(scale, 0.10)
        self.assertIn("high_blowout_limited_role_context", metrics["policy_reasons"])

    def test_regressor_feature_builder_uses_gbm_feature_surface(self) -> None:
        scored = pd.DataFrame(
            {
                "player": ["Test Player"],
                "team": ["MIN"],
                "opp": ["SAS"],
                "stat": ["PTS"],
                "direction": ["OVER"],
                "tier": ["GOBLIN"],
                "line": [5.5],
                "p_adj": [0.62],
                "p_for_cal": [0.62],
                "q_blowout": [0.24],
                "rate_mean": [0.40],
                "rate_std": [0.10],
                "min_mean": [24.0],
                "min_std": [6.0],
                "games_used": [12],
                "role_ctx_outs_used": [1],
                "is_home": [1],
                "external_prior_n": [1],
                "external_prior_score": [0.75],
                "game_date": ["2026-05-12"],
            }
        )
        logs = pd.DataFrame(
            [
                {"player": "Test Player", "game_date": f"2026-05-{day:02d}", "pts": 7 + day % 3, "reb": 1, "ast": 1, "fg3m": 1, "fga": 4, "fta": 2, "tov": 1}
                for day in range(1, 8)
            ]
        )
        features = [
            "p_for_cal",
            "thin_flag",
            "tier_cat",
            "line_dist",
            "q_blowout",
            "rate_cv",
            "use_role",
        ]

        X_df, diagnostics = _build_feature_df_regressor(
            scored,
            logs,
            features,
            ["tier_cat", "use_role"],
            Path("data/model/ensemble"),
        )

        self.assertEqual(diagnostics["feature_source"], "gbm_compute_features")
        self.assertEqual(float(X_df.loc[0, "p_for_cal"]), 0.62)
        self.assertEqual(float(X_df.loc[0, "thin_flag"]), 1.0)
        self.assertEqual(X_df.loc[0, "tier_cat"], "1")
        self.assertEqual(X_df.loc[0, "use_role"], "1")
        self.assertNotEqual(float(X_df.loc[0, "line_dist"]), 0.0)
        self.assertGreater(float(X_df.loc[0, "rate_cv"]), 0.0)


if __name__ == "__main__":
    unittest.main()

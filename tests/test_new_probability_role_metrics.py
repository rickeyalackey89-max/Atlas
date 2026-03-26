from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.engine.new_probability import _competitive_usage_bonus, _crafted_role_workload_adjustment, _crafted_role_workload_minutes_projection, _fragility_root_inputs, _role_metrics_adjustment, _role_metrics_role_ctx_active, _usage_dependence_proxy


class RoleMetricsAdjustmentTest(unittest.TestCase):
    def test_drip_contributes_when_role_context_is_active(self) -> None:
        base_row = {
            "role_ctx_outs_used": 1,
            "role_metrics_usg_pct": 28.0,
            "role_metrics_cpm": 3.0,
            "role_metrics_vorp": 2.5,
            "role_metrics_darko": 1.8,
        }
        with_drip = dict(base_row, role_metrics_drip_total=4.0)
        without_drip = dict(base_row, role_metrics_drip_total=None)

        mult_with, comp_with = _role_metrics_adjustment(with_drip)
        mult_without, comp_without = _role_metrics_adjustment(without_drip)

        self.assertGreater(mult_with, mult_without)
        self.assertIn("drip_raw", comp_with)
        self.assertNotIn("drip_raw", comp_without)

    def test_role_metrics_adjustment_is_neutral_without_role_context(self) -> None:
        row = {
            "role_ctx_outs_used": 0,
            "role_metrics_usg_pct": 31.0,
            "role_metrics_cpm": 3.0,
            "role_metrics_vorp": 2.5,
            "role_metrics_darko": 1.8,
            "role_metrics_drip_total": 4.0,
        }

        mult, components = _role_metrics_adjustment(row)

        self.assertEqual(mult, 1.0)
        self.assertEqual(components.get("score"), 0.0)
        self.assertEqual(components.get("mult"), 1.0)
        self.assertEqual(components.get("gated"), 1.0)

    def test_role_metrics_adjustment_can_use_override_state(self) -> None:
        row = {
            "role_metrics_usg_pct": 31.0,
            "role_metrics_cpm": 3.0,
            "role_metrics_vorp": 2.5,
            "role_metrics_darko": 1.8,
            "role_metrics_drip_total": 4.0,
        }

        mult, components = _role_metrics_adjustment(row, role_ctx_on_override=True)

        self.assertGreater(mult, 1.0)
        self.assertGreater(components.get("score", 0.0), 0.0)
        self.assertEqual(components.get("mult"), mult)

    def test_usage_proxy_uses_usg_pct_for_scoring_burden(self) -> None:
        high_usg = _usage_dependence_proxy(
            stat_u="PTS",
            base_rate_mu=0.95,
            line=24.5,
            expected_minutes=34.0,
            usg_pct=33.0,
        )
        low_usg = _usage_dependence_proxy(
            stat_u="PTS",
            base_rate_mu=0.95,
            line=24.5,
            expected_minutes=34.0,
            usg_pct=18.0,
        )

        self.assertGreater(high_usg["usage_usg_mult"], 1.0)
        self.assertLess(low_usg["usage_usg_mult"], 1.0)
        self.assertGreater(high_usg["usage_dep"], low_usg["usage_dep"])

    def test_usage_proxy_routes_rebound_metrics_into_rebound_family(self) -> None:
        strong_rebound = _usage_dependence_proxy(
            stat_u="REB",
            base_rate_mu=0.38,
            line=10.5,
            expected_minutes=34.0,
            trb_pct=22.0,
            orb_pct=9.0,
            drb_pct=24.0,
        )
        weak_rebound = _usage_dependence_proxy(
            stat_u="REB",
            base_rate_mu=0.38,
            line=10.5,
            expected_minutes=34.0,
            trb_pct=8.0,
            orb_pct=2.0,
            drb_pct=9.0,
        )

        self.assertGreater(strong_rebound["usage_rebound_mult"], weak_rebound["usage_rebound_mult"])
        self.assertGreater(strong_rebound["usage_dep"], weak_rebound["usage_dep"])

    def test_usage_proxy_routes_assist_metrics_into_assist_family(self) -> None:
        strong_assist = _usage_dependence_proxy(
            stat_u="AST",
            base_rate_mu=0.22,
            line=7.5,
            expected_minutes=34.0,
            ast_pct=34.0,
            ast_usg=1.25,
            box_creation=11.0,
            passer_rating=7.5,
        )
        weak_assist = _usage_dependence_proxy(
            stat_u="AST",
            base_rate_mu=0.22,
            line=7.5,
            expected_minutes=34.0,
            ast_pct=12.0,
            ast_usg=0.55,
            box_creation=4.0,
            passer_rating=3.0,
        )

        self.assertGreater(strong_assist["usage_assist_mult"], weak_assist["usage_assist_mult"])
        self.assertEqual(strong_assist["usage_metric_mult"], 1.0)
        self.assertEqual(weak_assist["usage_metric_mult"], 1.0)

    def test_usage_proxy_neutralizes_scoring_family_for_combo_markets(self) -> None:
        combo_leg = _usage_dependence_proxy(
            stat_u="PRA",
            base_rate_mu=0.95,
            line=34.5,
            expected_minutes=34.0,
            usg_pct=34.0,
            ts_pct=64.0,
            sq=70.0,
            ftr=42.0,
        )

        self.assertEqual(combo_leg["usage_scoring_mult"], 1.0)
        self.assertEqual(combo_leg["usage_metric_mult"], 1.0)

    def test_role_metrics_adjustment_uses_impact_metrics_as_weak_prior(self) -> None:
        weak_prior_row = {
            "role_metrics_cpm": 0.5,
            "role_metrics_vorp": 0.3,
            "role_metrics_darko": 0.2,
            "role_metrics_drip_total": 0.1,
        }
        strong_prior_row = {
            "role_metrics_cpm": 4.0,
            "role_metrics_vorp": 3.5,
            "role_metrics_darko": 3.0,
            "role_metrics_drip_total": 5.0,
        }

        weak_mult, _ = _role_metrics_adjustment(weak_prior_row, role_ctx_on_override=True)
        strong_mult, _ = _role_metrics_adjustment(strong_prior_row, role_ctx_on_override=True)

        self.assertGreaterEqual(weak_mult, 1.0)
        self.assertGreater(strong_mult, weak_mult)
        self.assertLessEqual(strong_mult, 1.008)

    def test_crafted_role_workload_adjustment_prefers_stronger_scoring_profile(self) -> None:
        cfg = {"crafted_role_workload_enabled": True}
        weak_row = {
            "role_metrics_usage_projection": 18.0,
            "role_metrics_usg_pct": 20.0,
            "role_metrics_load": 14.0,
            "role_metrics_touches": 38.0,
            "role_metrics_ts_pct": 53.0,
            "role_metrics_sq": 42.0,
            "role_metrics_ftr": 16.0,
        }
        strong_row = {
            "role_metrics_usage_projection": 31.0,
            "role_metrics_usg_pct": 33.0,
            "role_metrics_load": 28.0,
            "role_metrics_touches": 72.0,
            "role_metrics_ts_pct": 63.0,
            "role_metrics_sq": 68.0,
            "role_metrics_ftr": 34.0,
        }

        weak_mult, _ = _crafted_role_workload_adjustment(weak_row, "PTS", role_cfg=cfg, role_ctx_on_override=True)
        strong_mult, _ = _crafted_role_workload_adjustment(strong_row, "PTS", role_cfg=cfg, role_ctx_on_override=True)

        self.assertGreater(strong_mult, weak_mult)
        self.assertGreater(strong_mult, 1.0)

    def test_crafted_role_workload_adjustment_can_be_over_only(self) -> None:
        cfg = {"crafted_role_workload_enabled": True, "crafted_role_workload_over_only": True}
        row = {
            "role_metrics_usage_projection": 31.0,
            "role_metrics_usg_pct": 33.0,
            "role_metrics_load": 28.0,
        }

        under_mult, _ = _crafted_role_workload_adjustment(row, "PRA", direction="UNDER", role_cfg=cfg, role_ctx_on_override=True)
        over_mult, _ = _crafted_role_workload_adjustment(row, "PRA", direction="OVER", role_cfg=cfg, role_ctx_on_override=True)

        self.assertEqual(under_mult, 1.0)
        self.assertGreater(over_mult, under_mult)

    def test_crafted_role_workload_minutes_projection_blends_toward_crafted_minutes(self) -> None:
        cfg = {
            "crafted_role_workload_enabled": True,
            "crafted_role_workload_minutes_blend": 0.50,
            "crafted_role_workload_minutes_ratio_lo": 0.90,
            "crafted_role_workload_minutes_ratio_hi": 1.10,
        }
        row = {
            "minutes_projection": 30.0,
            "role_metrics_minutes_projection": 40.0,
        }

        blended = _crafted_role_workload_minutes_projection(row, role_cfg=cfg, role_ctx_on_override=True)

        self.assertIsNotNone(blended)
        assert blended is not None
        self.assertAlmostEqual(float(blended), 31.5, places=12)

    def test_fragility_role_metrics_can_require_minimum_outs(self) -> None:
        blocked_row = {
            "role_ctx_outs_used": 2,
            "role_metrics_usg_pct": 34.0,
        }
        active_row = {
            "role_ctx_outs_used": 3,
            "role_metrics_usg_pct": 34.0,
        }

        _, blocked_usage = _fragility_root_inputs(
            row=pd.Series(blocked_row),
            stat_u="PTS",
            base_rate_mu=0.95,
            line=24.5,
            expected_minutes=34.0,
            role_cfg={"role_metrics_require_role_ctx": True, "role_metrics_min_role_ctx_outs": 3},
        )
        _, active_usage = _fragility_root_inputs(
            row=pd.Series(active_row),
            stat_u="PTS",
            base_rate_mu=0.95,
            line=24.5,
            expected_minutes=34.0,
            role_cfg={"role_metrics_require_role_ctx": True, "role_metrics_min_role_ctx_outs": 3},
        )

        self.assertEqual(blocked_usage["usage_usg_mult"], 1.0)
        self.assertGreater(active_usage["usage_usg_mult"], blocked_usage["usage_usg_mult"])
        self.assertGreater(active_usage["usage_dep"], blocked_usage["usage_dep"])

    def test_role_metrics_role_context_gate_can_require_minimum_outs(self) -> None:
        role_cfg = {"role_metrics_require_role_ctx": True, "role_metrics_min_role_ctx_outs": 3}

        self.assertFalse(_role_metrics_role_ctx_active({"role_ctx_outs_used": 2}, role_cfg))
        self.assertTrue(_role_metrics_role_ctx_active({"role_ctx_outs_used": 3}, role_cfg))
        self.assertTrue(_role_metrics_role_ctx_active({"role_ctx_outs_used": 4}, role_cfg))

    def test_competitive_usage_bonus_rewards_high_usage_low_fragility_tight_games(self) -> None:
        bonus, debug = _competitive_usage_bonus(
            stat_u="PTS",
            direction="OVER",
            usg_pct=32.0,
            fragility=0.05,
            q_blowout=0.09,
            headroom=0.02,
            cfg={},
        )

        self.assertGreater(bonus, 0.0)
        self.assertLessEqual(bonus, 0.006)
        self.assertGreater(debug["usage_gate"], 0.0)
        self.assertGreater(debug["frag_gate"], 0.0)
        self.assertGreater(debug["tight_gate"], 0.0)

    def test_competitive_usage_bonus_requires_usage_threshold(self) -> None:
        bonus, debug = _competitive_usage_bonus(
            stat_u="PTS",
            direction="OVER",
            usg_pct=22.0,
            fragility=0.03,
            q_blowout=0.06,
            headroom=0.02,
            cfg={},
        )

        self.assertEqual(bonus, 0.0)
        self.assertEqual(debug["usage_gate"], 0.0)

    def test_competitive_usage_bonus_turns_off_when_fragility_is_too_high(self) -> None:
        bonus, debug = _competitive_usage_bonus(
            stat_u="PTS",
            direction="OVER",
            usg_pct=34.0,
            fragility=0.18,
            q_blowout=0.07,
            headroom=0.02,
            cfg={},
        )

        self.assertEqual(bonus, 0.0)
        self.assertEqual(debug["frag_gate"], 0.0)

    def test_competitive_usage_bonus_is_capped_by_available_headroom(self) -> None:
        bonus, debug = _competitive_usage_bonus(
            stat_u="PTS",
            direction="OVER",
            usg_pct=36.0,
            fragility=0.01,
            q_blowout=0.04,
            headroom=0.002,
            cfg={},
        )

        self.assertEqual(bonus, 0.002)
        self.assertGreater(debug["bonus_uncapped"], bonus)



if __name__ == "__main__":
    unittest.main()

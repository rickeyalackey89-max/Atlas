from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.engine.main import _apply_combo_over_high_fragility_lift, _apply_combo_under_highq_telemetry_blend, _apply_combo_under_lowmidq_telemetry_blend, _apply_combo_under_midq_ra_trim, _apply_combo_under_midq_telemetry_blend


class TelemetryBlendTest(unittest.TestCase):
    def test_blend_only_applies_to_target_combo_under_midq_rows(self) -> None:
        scored = pd.DataFrame(
            [
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.40, "p_cal": 0.60},
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.31, "p_adj": 0.40, "p_cal": 0.60},
                {"stat": "AST", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.40, "p_cal": 0.60},
                {"stat": "PTS", "direction": "OVER", "q_blowout": 0.25, "p_adj": 0.40, "p_cal": 0.60},
            ]
        )
        use_role = pd.Series([False, False, False, False])
        under_relief_applied = pd.Series([True, True, True, True])

        out = _apply_combo_under_midq_telemetry_blend(
            scored,
            use_role=use_role,
            under_relief_applied=under_relief_applied,
            retain=0.40,
        )

        self.assertAlmostEqual(out.loc[0, "p_cal"], 0.48, places=12)
        self.assertAlmostEqual(out.loc[1, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[2, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[3, "p_cal"], 0.60, places=12)
        self.assertEqual(
            out["telemetry_combo_under_midq_blend_applied"].tolist(),
            [True, False, False, False],
        )

    def test_combo_over_high_fragility_lift_only_applies_to_target_rows(self) -> None:
        scored = pd.DataFrame(
            [
                {"stat": "PTS", "direction": "OVER", "fragility": 0.20, "p_adj": 0.30, "p_role": 0.50, "p_cal": 0.40},
                {"stat": "PTS", "direction": "OVER", "fragility": 0.08, "p_adj": 0.30, "p_role": 0.50, "p_cal": 0.40},
                {"stat": "AST", "direction": "OVER", "fragility": 0.20, "p_adj": 0.30, "p_role": 0.50, "p_cal": 0.40},
                {"stat": "PTS", "direction": "UNDER", "fragility": 0.20, "p_adj": 0.30, "p_role": 0.50, "p_cal": 0.40},
                {"stat": "PTS", "direction": "OVER", "fragility": 0.20, "p_adj": 0.30, "p_role": 0.50, "p_cal": 0.40},
            ]
        )
        use_role = pd.Series([False, False, False, False, True])

        out = _apply_combo_over_high_fragility_lift(
            scored,
            use_role=use_role,
            factor=0.36,
        )

        self.assertAlmostEqual(out.loc[0, "p_cal"], 0.472, places=12)
        self.assertAlmostEqual(out.loc[1, "p_cal"], 0.40, places=12)
        self.assertAlmostEqual(out.loc[2, "p_cal"], 0.40, places=12)
        self.assertAlmostEqual(out.loc[3, "p_cal"], 0.40, places=12)
        self.assertAlmostEqual(out.loc[4, "p_cal"], 0.40, places=12)
        self.assertEqual(
            out["telemetry_combo_over_high_fragility_lift_applied"].tolist(),
            [True, False, False, False, False],
        )

    def test_combo_under_highq_blend_only_applies_to_target_rows(self) -> None:
        scored = pd.DataFrame(
            [
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.35, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "AST", "direction": "UNDER", "q_blowout": 0.35, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PTS", "direction": "OVER", "q_blowout": 0.35, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.35, "p_adj": 0.30, "p_cal": 0.60},
            ]
        )
        use_role = pd.Series([False, False, False, False, True])
        under_relief_applied = pd.Series([True, True, True, True, True])

        out = _apply_combo_under_highq_telemetry_blend(
            scored,
            use_role=use_role,
            under_relief_applied=under_relief_applied,
            retain=0.68,
        )

        self.assertAlmostEqual(out.loc[0, "p_cal"], 0.504, places=12)
        self.assertAlmostEqual(out.loc[1, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[2, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[3, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[4, "p_cal"], 0.60, places=12)
        self.assertEqual(
            out["telemetry_combo_under_highq_blend_applied"].tolist(),
            [True, False, False, False, False],
        )

    def test_combo_under_lowmidq_blend_only_applies_to_target_rows(self) -> None:
        scored = pd.DataFrame(
            [
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.15, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "AST", "direction": "UNDER", "q_blowout": 0.15, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PTS", "direction": "OVER", "q_blowout": 0.15, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PTS", "direction": "UNDER", "q_blowout": 0.15, "p_adj": 0.30, "p_cal": 0.60},
            ]
        )
        use_role = pd.Series([False, False, False, False, True])
        under_relief_applied = pd.Series([True, True, True, True, True])

        out = _apply_combo_under_lowmidq_telemetry_blend(
            scored,
            use_role=use_role,
            under_relief_applied=under_relief_applied,
            retain=0.55,
        )

        self.assertAlmostEqual(out.loc[0, "p_cal"], 0.465, places=12)
        self.assertAlmostEqual(out.loc[1, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[2, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[3, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[4, "p_cal"], 0.60, places=12)
        self.assertEqual(
            out["telemetry_combo_under_lowmidq_blend_applied"].tolist(),
            [True, False, False, False, False],
        )

    def test_combo_under_midq_ra_trim_only_applies_to_target_rows(self) -> None:
        scored = pd.DataFrame(
            [
                {"stat": "RA", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "PA", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "RA", "direction": "UNDER", "q_blowout": 0.15, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "RA", "direction": "OVER", "q_blowout": 0.25, "p_adj": 0.30, "p_cal": 0.60},
                {"stat": "RA", "direction": "UNDER", "q_blowout": 0.25, "p_adj": 0.30, "p_cal": 0.60},
            ]
        )
        use_role = pd.Series([False, False, False, False, True])
        under_relief_applied = pd.Series([True, True, True, True, True])

        out = _apply_combo_under_midq_ra_trim(
            scored,
            use_role=use_role,
            under_relief_applied=under_relief_applied,
            retain=0.35,
        )

        self.assertAlmostEqual(out.loc[0, "p_cal"], 0.405, places=12)
        self.assertAlmostEqual(out.loc[1, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[2, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[3, "p_cal"], 0.60, places=12)
        self.assertAlmostEqual(out.loc[4, "p_cal"], 0.60, places=12)
        self.assertEqual(
            out["telemetry_combo_under_midq_ra_trim_applied"].tolist(),
            [True, False, False, False, False],
        )


if __name__ == "__main__":
    unittest.main()
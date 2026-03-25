from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.runtime.telemetry_calibration import TelemetryCalibration, apply_calibration_to_column


class TelemetryRuntimeCalibrationTest(unittest.TestCase):
    def test_isotonic_global_mode_applies_serialized_curve(self) -> None:
        calib = TelemetryCalibration.from_json(
            {
                "mode": "isotonic_global",
                "candidate": "isotonic_global_p_cal",
                "meta": {
                    "source_col": "p_cal",
                    "x_thresholds": [0.2, 0.4, 0.6, 0.8],
                    "y_thresholds": [0.1, 0.3, 0.7, 0.9],
                },
            }
        )
        df = pd.DataFrame(
            {
                "stat": ["PTS", "PTS", "PTS"],
                "direction": ["OVER", "OVER", "OVER"],
                "tier": ["STANDARD", "STANDARD", "STANDARD"],
                "p_for_cal": [0.2, 0.5, 0.8],
                "p_for_cal_src": ["p_adj", "p_adj", "p_adj"],
            }
        )

        result = apply_calibration_to_column(df, calib, source_col="p_for_cal", out_col="p_cal")

        self.assertAlmostEqual(float(result.loc[0, "p_cal"]), 0.1, places=12)
        self.assertAlmostEqual(float(result.loc[1, "p_cal"]), 0.5, places=12)
        self.assertAlmostEqual(float(result.loc[2, "p_cal"]), 0.9, places=12)
        self.assertTrue(bool(result.loc[0, "telemetry_cal_applied"]))
        self.assertFalse(bool(result.loc[1, "telemetry_cal_applied"]))
        self.assertTrue(bool(result.loc[2, "telemetry_cal_applied"]))

    def test_keep_identity_mode_is_noop(self) -> None:
        calib = TelemetryCalibration.from_json({"mode": "keep_identity"})
        df = pd.DataFrame(
            {
                "stat": ["PTS", "REB"],
                "direction": ["OVER", "UNDER"],
                "tier": ["STANDARD", "STANDARD"],
                "p_for_cal": [0.33, 0.61],
                "p_for_cal_src": ["p_adj", "p_adj"],
            }
        )

        result = apply_calibration_to_column(df, calib, source_col="p_for_cal", out_col="p_cal")

        self.assertAlmostEqual(float(result.loc[0, "p_cal"]), 0.33, places=12)
        self.assertAlmostEqual(float(result.loc[1, "p_cal"]), 0.61, places=12)
        self.assertFalse(bool(result.loc[0, "telemetry_cal_applied"]))
        self.assertFalse(bool(result.loc[1, "telemetry_cal_applied"]))

    def test_isotonic_can_stack_on_base_telemetry_surface(self) -> None:
        calib = TelemetryCalibration.from_json(
            {
                "mode": "isotonic_global",
                "meta": {
                    "source_col": "p_cal",
                    "x_thresholds": [0.3, 0.4],
                    "y_thresholds": [0.2, 0.5],
                },
                "pre_calibration": {
                    "version": 2,
                    "policy": {
                        "apply_only_p_cal_src_prefixes": ["p_adj"]
                    },
                    "base": {
                        "k_shrink": 0.5,
                        "standard_under_penalty": 1.0
                    }
                }
            }
        )

        df = pd.DataFrame(
            {
                "stat": ["PTS"],
                "direction": ["OVER"],
                "tier": ["STANDARD"],
                "p_for_cal": [0.8],
                "p_for_cal_src": ["p_adj"]
            }
        )

        result = apply_calibration_to_column(df, calib, source_col="p_for_cal", out_col="p_cal")

        self.assertAlmostEqual(float(result.loc[0, "p_cal"]), 0.5, places=12)
        self.assertTrue(bool(result.loc[0, "telemetry_cal_applied"]))

    def test_isotonic_hybrid_protects_role_off_stat_directions(self) -> None:
        calib = TelemetryCalibration.from_json(
            {
                "mode": "isotonic_hybrid",
                "meta": {
                    "source_col": "p_cal",
                    "mix": 0.5,
                    "x_thresholds": [0.4, 0.6],
                    "y_thresholds": [0.2, 0.4],
                    "protected_stat_directions": ["PRA|OVER"],
                    "protected_role_ctx": "off",
                    "protected_calibration": {
                        "mode": "isotonic_global",
                        "meta": {
                            "source_col": "p_cal",
                            "x_thresholds": [0.4, 0.6],
                            "y_thresholds": [0.5, 0.8]
                        }
                    }
                }
            }
        )

        df = pd.DataFrame(
            {
                "stat": ["PRA", "PRA", "PA"],
                "direction": ["OVER", "OVER", "OVER"],
                "tier": ["STANDARD", "STANDARD", "STANDARD"],
                "role_ctx_outs_used": [0, 2, 0],
                "p_cal": [0.6, 0.6, 0.4],
                "p_cal_src": ["p_adj", "p_adj", "p_adj"],
            }
        )

        result = apply_calibration_to_column(df, calib, source_col="p_cal", out_col="p_out")

        self.assertAlmostEqual(float(result.loc[0, "p_out"]), 0.8, places=12)
        self.assertAlmostEqual(float(result.loc[1, "p_out"]), 0.5, places=12)
        self.assertAlmostEqual(float(result.loc[2, "p_out"]), 0.3, places=12)
        self.assertTrue(bool(result.loc[0, "telemetry_cal_applied"]))
        self.assertTrue(bool(result.loc[1, "telemetry_cal_applied"]))
        self.assertTrue(bool(result.loc[2, "telemetry_cal_applied"]))

    def test_isotonic_hybrid_can_guard_nested_overlay_with_keep_identity(self) -> None:
        calib = TelemetryCalibration.from_json(
            {
                "mode": "isotonic_hybrid",
                "meta": {
                    "source_col": "p_cal",
                    "mix": 1.0,
                    "x_thresholds": [0.3, 0.6],
                    "y_thresholds": [0.2, 0.5],
                    "protected_stat_directions": ["PRA|OVER"],
                    "protected_role_ctx": "off",
                    "protected_calibration": {
                        "mode": "keep_identity"
                    }
                },
                "pre_calibration": {
                    "mode": "isotonic_global",
                    "meta": {
                        "source_col": "p_cal",
                        "x_thresholds": [0.4, 0.7],
                        "y_thresholds": [0.45, 0.8]
                    }
                }
            }
        )

        df = pd.DataFrame(
            {
                "stat": ["PRA", "PA"],
                "direction": ["OVER", "OVER"],
                "tier": ["STANDARD", "STANDARD"],
                "role_ctx_outs_used": [0, 0],
                "p_cal": [0.7, 0.7],
                "p_cal_src": ["p_adj", "p_adj"],
            }
        )

        result = apply_calibration_to_column(df, calib, source_col="p_cal", out_col="p_out")

        self.assertAlmostEqual(float(result.loc[0, "p_out"]), 0.8, places=12)
        self.assertAlmostEqual(float(result.loc[1, "p_out"]), 0.5, places=12)
        self.assertFalse(bool(result.loc[0, "telemetry_cal_applied"]))
        self.assertTrue(bool(result.loc[1, "telemetry_cal_applied"]))


if __name__ == "__main__":
    unittest.main()
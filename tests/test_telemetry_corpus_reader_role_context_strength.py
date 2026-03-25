from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.telemetry_corpus_reader import _role_context_strength_series, _transform_telemetry_key_role_strength


class TelemetryCorpusReaderRoleContextStrengthTest(unittest.TestCase):
    def test_role_context_strength_is_bounded_and_monotonic(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "role_ctx_outs_used": 0,
                    "role_ctx_mult": 1.0,
                    "minutes_s": 0.0,
                    "games_used": 0,
                    "usage_dep_eff": 1.0,
                },
                {
                    "role_ctx_outs_used": 1,
                    "role_ctx_mult": 1.02,
                    "minutes_s": 18.0,
                    "games_used": 12,
                    "usage_dep_eff": 1.05,
                },
                {
                    "role_ctx_outs_used": 4,
                    "role_ctx_mult": 1.12,
                    "minutes_s": 32.0,
                    "games_used": 24,
                    "usage_dep_eff": 1.20,
                },
            ]
        )

        strength = _role_context_strength_series(df)

        self.assertAlmostEqual(float(strength.iloc[0]), 0.0, places=12)
        self.assertGreater(float(strength.iloc[1]), 0.0)
        self.assertGreater(float(strength.iloc[2]), float(strength.iloc[1]))
        self.assertLessEqual(float(strength.iloc[1]), 1.0)
        self.assertLessEqual(float(strength.iloc[2]), 1.0)

    def test_role_context_strength_interpolates_between_role_off_and_on(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "telemetry_cal_key": "AST|OVER",
                    "p_cal": 0.50,
                    "telemetry_mult": 1.0,
                    "role_ctx_outs_used": 0,
                    "role_ctx_mult": 1.0,
                },
                {
                    "telemetry_cal_key": "AST|OVER",
                    "p_cal": 0.50,
                    "telemetry_mult": 1.0,
                    "role_ctx_outs_used": 1,
                    "role_ctx_mult": 1.02,
                },
                {
                    "telemetry_cal_key": "AST|OVER",
                    "p_cal": 0.50,
                    "telemetry_mult": 1.0,
                    "role_ctx_outs_used": 4,
                    "role_ctx_mult": 1.12,
                },
            ]
        )

        output = _transform_telemetry_key_role_strength(
            df,
            {"AST|OVER": 1.20},
            key_col="telemetry_cal_key",
            role_col="role_ctx_outs_used",
            mult_col="role_ctx_mult",
            k=0.96,
            under_penalty=0.98,
        )

        self.assertAlmostEqual(float(output.iloc[0]), 0.60, places=12)
        self.assertGreater(float(output.iloc[1]), 0.50)
        self.assertLess(float(output.iloc[1]), 0.60)
        self.assertGreater(float(output.iloc[2]), float(output.iloc[1]))
        self.assertLess(float(output.iloc[2]), 0.60)


if __name__ == "__main__":
    unittest.main()
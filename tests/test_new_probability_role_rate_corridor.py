from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.engine.new_probability import _bounded_role_rate_multiplier


class RoleRateCorridorTest(unittest.TestCase):
    def test_role_rate_uplift_is_soft_capped(self) -> None:
        raw_mult, bounded_mult, clamp_lo, clamp_hi, softcap_k = _bounded_role_rate_multiplier(
            role_mult=1.12,
            role_metrics_mult=1.015,
            cfg={"role_rate_clamp_lo": 0.94, "role_rate_clamp_hi": 1.08, "role_rate_softcap_k": 1.10},
        )

        self.assertGreater(raw_mult, bounded_mult)
        self.assertAlmostEqual(clamp_lo, 0.94, places=12)
        self.assertAlmostEqual(clamp_hi, 1.08, places=12)
        self.assertAlmostEqual(softcap_k, 1.10, places=12)
        self.assertLessEqual(bounded_mult, 1.08)
        self.assertGreaterEqual(bounded_mult, 1.0)

    def test_role_rate_downside_is_not_allowed_to_spill_below_floor(self) -> None:
        raw_mult, bounded_mult, clamp_lo, clamp_hi, _ = _bounded_role_rate_multiplier(
            role_mult=0.89,
            role_metrics_mult=0.97,
            cfg={"role_rate_clamp_lo": 0.95, "role_rate_clamp_hi": 1.08, "role_rate_softcap_k": 1.10},
        )

        self.assertLess(raw_mult, 1.0)
        self.assertLessEqual(bounded_mult, 1.0)
        self.assertGreaterEqual(bounded_mult, 0.95)
        self.assertAlmostEqual(clamp_lo, 0.95, places=12)
        self.assertAlmostEqual(clamp_hi, 1.08, places=12)


if __name__ == "__main__":
    unittest.main()

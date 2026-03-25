from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.engine.new_probability import _role_metrics_adjustment


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


if __name__ == "__main__":
    unittest.main()

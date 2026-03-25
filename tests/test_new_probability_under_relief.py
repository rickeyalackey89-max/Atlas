from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.engine.new_probability import _apply_under_relief


class UnderReliefTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

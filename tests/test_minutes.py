from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.core.minutes import adjust_probability_for_blowout


class MinutesAdjustmentTest(unittest.TestCase):
    def test_blowout_adjustment_is_monotonic_and_bounded(self) -> None:
        baseline = adjust_probability_for_blowout(0.70, 0.0, 1.0)
        mild = adjust_probability_for_blowout(0.70, 0.10, 1.0)
        strong = adjust_probability_for_blowout(0.70, 0.30, 1.0)
        floor = adjust_probability_for_blowout(0.70, 1.0, 1.0)

        self.assertAlmostEqual(baseline, 0.70, places=12)
        self.assertLess(mild, baseline)
        self.assertLess(strong, mild)
        self.assertLess(strong, 0.70 * (1.0 - 0.30))
        self.assertAlmostEqual(floor, 0.03, places=12)


if __name__ == "__main__":
    unittest.main()
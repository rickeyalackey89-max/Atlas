from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_role_metrics import _map_header


class FetchRoleMetricsParserTest(unittest.TestCase):
    def test_maps_role_workload_headers_from_craftednba_glossary(self) -> None:
        self.assertEqual(_map_header("Touches"), "touches")
        self.assertEqual(_map_header("AstUsg"), "ast_usg")
        self.assertEqual(_map_header("CraftedOPM"), "crafted_opm")
        self.assertEqual(_map_header("CraftedDPM"), "crafted_dpm")
        self.assertEqual(_map_header("Crafted WARP"), "crafted_warp")


if __name__ == "__main__":
    unittest.main()
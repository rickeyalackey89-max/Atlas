from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.core.external_priors import apply_external_priors


class ExternalPriorTest(unittest.TestCase):
    def test_apply_external_priors_can_be_audit_only(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "player": "Alpha Guard",
                    "stat": "PTS",
                    "line": 10.5,
                    "direction": "OVER",
                    "tier": "GOBLIN",
                    "p_adj": 0.50,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            priors_path = Path(tmpdir) / "external_priors_today.csv"
            priors_path.write_text(
                "source,asof_ts,league,player,stat,projection,confidence,notes\n"
                "rotowire,2026-03-23T00:00:00Z,NBA,Alpha Guard,PTS,12.0,1.0,test\n",
                encoding="utf-8",
            )

            old_env = os.environ.get("ATLAS_EXTERNAL_PRIORS_CSV_PATH")
            os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(priors_path)
            try:
                audit_only = apply_external_priors(scored, {"optimizer": {"external_priors": {"enabled": True, "cap": 0.03, "scale": 3.0}}}, apply_probability=False)
                nudged = apply_external_priors(scored, {"optimizer": {"external_priors": {"enabled": True, "cap": 0.03, "scale": 3.0}}}, apply_probability=True)
            finally:
                if old_env is None:
                    os.environ.pop("ATLAS_EXTERNAL_PRIORS_CSV_PATH", None)
                else:
                    os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = old_env

        self.assertAlmostEqual(float(pd.to_numeric(audit_only["p_adj"], errors="coerce").iloc[0]), 0.50, places=12)
        self.assertEqual(int(pd.to_numeric(audit_only["external_prior_n"], errors="coerce").iloc[0]), 1)
        self.assertGreater(float(pd.to_numeric(audit_only["external_prior_score"], errors="coerce").iloc[0]), 0.0)
        self.assertGreater(float(pd.to_numeric(nudged["p_adj"], errors="coerce").iloc[0]), 0.50)


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from Atlas.core.external_priors import apply_external_priors


class ExternalPriorTest(unittest.TestCase):
    def test_apply_external_priors_is_disabled_by_default(self) -> None:
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
                result = apply_external_priors(scored, {}, apply_probability=True)
            finally:
                if old_env is None:
                    os.environ.pop("ATLAS_EXTERNAL_PRIORS_CSV_PATH", None)
                else:
                    os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = old_env

        self.assertAlmostEqual(float(pd.to_numeric(result["p_adj"], errors="coerce").iloc[0]), 0.50, places=12)
        self.assertEqual(int(pd.to_numeric(result["external_prior_n"], errors="coerce").iloc[0]), 0)
        self.assertAlmostEqual(float(pd.to_numeric(result["external_prior_score"], errors="coerce").iloc[0]), 0.0, places=12)

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

    def test_apply_external_priors_rewards_supported_under_direction(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "player": "Beta Wing",
                    "stat": "PTS",
                    "line": 13.5,
                    "direction": "UNDER",
                    "tier": "STANDARD",
                    "p_adj": 0.50,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            priors_path = Path(tmpdir) / "external_priors_today.csv"
            priors_path.write_text(
                "source,asof_ts,league,player,stat,projection,confidence,notes\n"
                "oddsapi,2026-05-12T00:00:00Z,NBA,Beta Wing,PTS,11.5,1.0,test\n",
                encoding="utf-8",
            )

            old_env = os.environ.get("ATLAS_EXTERNAL_PRIORS_CSV_PATH")
            os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(priors_path)
            try:
                result = apply_external_priors(
                    scored,
                    {"optimizer": {"external_priors": {"enabled": True, "cap": 0.05, "scale": 1.5}}},
                    apply_probability=True,
                )
            finally:
                if old_env is None:
                    os.environ.pop("ATLAS_EXTERNAL_PRIORS_CSV_PATH", None)
                else:
                    os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = old_env

        self.assertEqual(int(pd.to_numeric(result["external_prior_n"], errors="coerce").iloc[0]), 1)
        self.assertGreater(float(pd.to_numeric(result["external_prior_score"], errors="coerce").iloc[0]), 0.0)
        self.assertGreater(float(pd.to_numeric(result["p_adj"], errors="coerce").iloc[0]), 0.50)

    def test_direction_cap_can_disable_under_probability_nudge(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "player": "Beta Wing",
                    "stat": "PTS",
                    "line": 13.5,
                    "direction": "UNDER",
                    "tier": "STANDARD",
                    "p_adj": 0.50,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            priors_path = Path(tmpdir) / "external_priors_today.csv"
            priors_path.write_text(
                "source,asof_ts,league,player,stat,projection,confidence,notes\n"
                "oddsapi,2026-05-12T00:00:00Z,NBA,Beta Wing,PTS,11.5,1.0,test\n",
                encoding="utf-8",
            )

            old_env = os.environ.get("ATLAS_EXTERNAL_PRIORS_CSV_PATH")
            os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(priors_path)
            try:
                result = apply_external_priors(
                    scored,
                    {
                        "optimizer": {
                            "external_priors": {
                                "enabled": True,
                                "cap": 0.03,
                                "cap_by_direction": {"OVER": 0.03, "UNDER": 0.0},
                                "scale": 6.0,
                            }
                        }
                    },
                    apply_probability=True,
                )
            finally:
                if old_env is None:
                    os.environ.pop("ATLAS_EXTERNAL_PRIORS_CSV_PATH", None)
                else:
                    os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = old_env

        self.assertEqual(int(pd.to_numeric(result["external_prior_n"], errors="coerce").iloc[0]), 1)
        self.assertGreater(float(pd.to_numeric(result["external_prior_score"], errors="coerce").iloc[0]), 0.0)
        self.assertAlmostEqual(float(pd.to_numeric(result["external_prior_cap_applied"], errors="coerce").iloc[0]), 0.0)
        self.assertAlmostEqual(float(pd.to_numeric(result["external_prior_delta_p"], errors="coerce").iloc[0]), 0.0)
        self.assertFalse(bool(result["external_prior_probability_applied"].iloc[0]))
        self.assertAlmostEqual(float(pd.to_numeric(result["p_adj"], errors="coerce").iloc[0]), 0.50, places=12)

    def test_zero_edge_prior_does_not_count_as_probability_applied(self) -> None:
        scored = pd.DataFrame(
            [
                {
                    "player": "Gamma Big",
                    "stat": "REB",
                    "line": 8.5,
                    "direction": "OVER",
                    "tier": "STANDARD",
                    "p_adj": 0.50,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            priors_path = Path(tmpdir) / "external_priors_today.csv"
            priors_path.write_text(
                "source,asof_ts,league,player,stat,projection,confidence,notes\n"
                "oddsapi,2026-05-12T00:00:00Z,NBA,Gamma Big,REB,8.5000000000001,1.0,test\n",
                encoding="utf-8",
            )

            old_env = os.environ.get("ATLAS_EXTERNAL_PRIORS_CSV_PATH")
            os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = str(priors_path)
            try:
                result = apply_external_priors(
                    scored,
                    {"optimizer": {"external_priors": {"enabled": True, "cap": 0.03, "scale": 3.0}}},
                    apply_probability=True,
                )
            finally:
                if old_env is None:
                    os.environ.pop("ATLAS_EXTERNAL_PRIORS_CSV_PATH", None)
                else:
                    os.environ["ATLAS_EXTERNAL_PRIORS_CSV_PATH"] = old_env

        self.assertEqual(int(pd.to_numeric(result["external_prior_n"], errors="coerce").iloc[0]), 1)
        self.assertLessEqual(abs(float(pd.to_numeric(result["external_prior_score"], errors="coerce").iloc[0])), 1e-12)
        self.assertAlmostEqual(float(pd.to_numeric(result["external_prior_delta_p"], errors="coerce").iloc[0]), 0.0, places=12)
        self.assertFalse(bool(result["external_prior_probability_applied"].iloc[0]))
        self.assertAlmostEqual(float(pd.to_numeric(result["p_adj"], errors="coerce").iloc[0]), 0.50, places=12)


if __name__ == "__main__":
    unittest.main()

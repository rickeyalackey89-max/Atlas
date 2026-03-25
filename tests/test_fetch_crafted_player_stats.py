from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCHER_PATH = PROJECT_ROOT / "tools" / "fetch_crafted_player_stats.py"

spec = importlib.util.spec_from_file_location("fetch_crafted_player_stats", FETCHER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load fetcher from {FETCHER_PATH}")
fetch_crafted_player_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_crafted_player_stats)


class CraftedPlayerStatsSchemaTest(unittest.TestCase):
    def test_build_row_maps_downstream_role_fields(self) -> None:
        record = {
            "player_name": "Test Player",
            "team_abbr": "okc",
            "player_position": "SG",
            "minutes": "31.5",
            "ts%": "0.612",
            "rts%": "0.041",
            "sq": "1.7",
            "3par": "0.41",
            "r3par": "0.08",
            "ftr": "0.23",
            "orb%": "3.1",
            "rorb%": "2.8",
            "raorb": "1.2",
            "drb%": "12.2",
            "rdrb%": "11.4",
            "radrb": "0.9",
            "stl%": "1.8",
            "radtov": "0.7",
            "blk%": "1.1",
            "tov%": "10.5",
            "usg%": "28.2",
            "ws": "4.2",
            "ctov%": "0.33",
            "bc": "0.88",
            "load": "0.44",
            "pr": "0.67",
            "port": "0.12",
            "plus/minus": "3.4",
            "role awareness": "0.21",
            "usage projection": "29.4",
            "starter flag": "yes",
            "rotation tier": "2",
            "depth role": "starter",
            "obpm": "1.5",
            "dbpm": "0.8",
            "bpm": "2.3",
            "vorp": "1.1",
            "odarko": "8.0",
            "ddarko": "2.0",
            "darko": "5.0",
            "copm": "1.3",
            "cdpm": "1.1",
            "cpm": "1.4",
            "odrip": "4.0",
            "ddrip": "1.8",
            "drip": "5.8",
            "drip offense": "3.6",
            "drip defense": "2.2",
            "craftedopm": "1.8",
            "crafteddpm": "-0.4",
            "craftedwarp": "2.1",
        }

        row = fetch_crafted_player_stats._build_row(
            record,
            game_date="2026-03-24",
            source_timestamp="2026-03-24T00:00:00Z",
            source_url=fetch_crafted_player_stats.API_URL,
            source_rank=7,
        )

        self.assertEqual("Test Player", row["player"])
        self.assertEqual("okc", row["team"])
        self.assertEqual("SG", row["position"])
        self.assertEqual(31.5, row["minutes_projection"])
        self.assertEqual(0.612, row["ts_pct"])
        self.assertEqual(0.041, row["rts_pct"])
        self.assertEqual(28.2, row["usg_pct"])
        self.assertEqual(3.4, row["plus_minus"])
        self.assertEqual(0.21, row["role_awareness"])
        self.assertEqual(29.4, row["usage_projection"])
        self.assertTrue(row["starter_flag"])
        self.assertEqual("2", row["rotation_tier"])
        self.assertEqual("starter", row["depth_role"])
        self.assertEqual(1.1, row["vorp"])
        self.assertEqual(5.0, row["darko"])
        self.assertEqual(8.0, row["odarko"])
        self.assertEqual(2.0, row["ddarko"])
        self.assertEqual(4.0, row["odrip"])
        self.assertEqual(1.8, row["ddrip"])
        self.assertEqual(5.8, row["drip_total"])
        self.assertEqual(3.6, row["drip_offense"])
        self.assertEqual(2.2, row["drip_defense"])
        self.assertEqual(1.4, row["cpm"])
        self.assertEqual(1.3, row["copm"])
        self.assertEqual(1.1, row["cdpm"])
        self.assertEqual(1.8, row["crafted_opm"])
        self.assertEqual(-0.4, row["crafted_dpm"])
        self.assertEqual(2.1, row["crafted_warp"])
        self.assertEqual("2026-03-24", row["game_date"])
        self.assertEqual("2026-03-24T00:00:00Z", row["source_timestamp"])
        self.assertEqual(fetch_crafted_player_stats.API_URL, row["source_url"])
        self.assertEqual(7, row["source_rank"])


if __name__ == "__main__":
    unittest.main()

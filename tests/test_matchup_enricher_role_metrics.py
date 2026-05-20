from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.core.matchup_enricher import _resolve_rotowire_lines_path, enrich_with_matchups


class MatchupEnricherRoleMetricsTest(unittest.TestCase):
    def _as_float(self, value: object) -> float:
        return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])

    def _write_csv(self, path: Path, frame: pd.DataFrame) -> None:
        frame.to_csv(path, index=False)

    def _write_role_metrics_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_rotowire_json(self, path: Path, game_date: str) -> None:
        payload = {
            "events": [
                {
                    "game_date": game_date,
                    "homeTeam": "CHA",
                    "awayTeam": "CHI",
                    "spread": {"home": -2.5, "away": 2.5},
                }
            ]
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_rotowire_path_defaults_to_current_repo_data_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rotowire_path = root / "data" / "input" / "rotowire_lines.json"
            rotowire_path.parent.mkdir(parents=True)
            self._write_rotowire_json(rotowire_path, "2026-03-17")

            old_cwd = Path.cwd()
            old_env = os.environ.pop("ATLAS_ROTOWIRE_LINES_PATH", None)
            try:
                os.chdir(root)
                self.assertEqual(Path(_resolve_rotowire_lines_path()).resolve(), rotowire_path.resolve())
            finally:
                os.chdir(old_cwd)
                if old_env is not None:
                    os.environ["ATLAS_ROTOWIRE_LINES_PATH"] = old_env

    def test_role_metrics_attach_by_player_key_and_date_when_team_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            roster_path = root / "roster_map.csv"
            slate_path = root / "slate.csv"
            rotowire_path = root / "rotowire_lines.json"
            role_metrics_path = root / "role_metrics_latest.json"

            self._write_csv(
                roster_path,
                pd.DataFrame(
                    [
                        {"player": "LaMelo Ball", "team": "CHA"},
                    ]
                ),
            )
            self._write_csv(
                slate_path,
                pd.DataFrame(
                    [
                        {"game_date": "2026-03-17", "home_team": "CHA", "away_team": "CHI"},
                    ]
                ),
            )
            self._write_rotowire_json(rotowire_path, "2026-03-17")
            self._write_role_metrics_json(
                role_metrics_path,
                {
                    "game_date": "2026-03-17",
                    "rows": [
                        {
                            "player": "LaMelo Ball",
                            "player_key": "lamelo ball",
                            "team": "Charlotte",
                            "game_date": "2026-03-17",
                            "usg_pct": 31.4,
                            "snapshot_id": "snap-123",
                        }
                    ],
                },
            )

            projections = pd.DataFrame(
                [
                    {
                        "player": "LaMelo Ball",
                        "team": "CHA",
                        "opp": "CHI",
                        "home": 1,
                        "game_date": "2026-03-17",
                        "stat": "PTS",
                        "line": 24.5,
                    }
                ]
            )

            enriched = enrich_with_matchups(
                projections=projections,
                roster_map_path=str(roster_path),
                slate_path=str(slate_path),
                default_game_date="2026-03-17",
                rotowire_lines_path=str(rotowire_path),
                role_metrics_path=str(role_metrics_path),
                attach_role_metrics=True,
            )

            self.assertEqual(len(enriched), 1)
            self.assertIn("team", enriched.columns)
            self.assertAlmostEqual(self._as_float(enriched.loc[0, "role_metrics_usg_pct"]), 31.4)
            self.assertEqual(enriched.loc[0, "role_metrics_snapshot_id"], "snap-123")
            self.assertEqual(enriched.loc[0, "team"], "CHA")

    def test_role_metrics_do_not_cross_attach_with_same_team_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            roster_path = root / "roster_map.csv"
            slate_path = root / "slate.csv"
            rotowire_path = root / "rotowire_lines.json"
            role_metrics_path = root / "role_metrics_latest.json"

            self._write_csv(
                roster_path,
                pd.DataFrame(
                    [
                        {"player": "LaMelo Ball", "team": "CHA"},
                        {"player": "Miles Bridges", "team": "CHA"},
                    ]
                ),
            )
            self._write_csv(
                slate_path,
                pd.DataFrame(
                    [
                        {"game_date": "2026-03-17", "home_team": "CHA", "away_team": "CHI"},
                    ]
                ),
            )
            self._write_rotowire_json(rotowire_path, "2026-03-17")
            self._write_role_metrics_json(
                role_metrics_path,
                {
                    "game_date": "2026-03-17",
                    "rows": [
                        {
                            "player": "LaMelo Ball",
                            "player_key": "lamelo ball",
                            "team": "Charlotte",
                            "game_date": "2026-03-17",
                            "usg_pct": 31.4,
                            "snapshot_id": "lamelo-snap",
                        },
                        {
                            "player": "Miles Bridges",
                            "player_key": "miles bridges",
                            "team": "Charlotte",
                            "game_date": "2026-03-17",
                            "usg_pct": 27.1,
                            "snapshot_id": "miles-snap",
                        },
                    ],
                },
            )

            projections = pd.DataFrame(
                [
                    {
                        "player": "LaMelo Ball",
                        "team": "CHA",
                        "opp": "CHI",
                        "home": 1,
                        "game_date": "2026-03-17",
                        "stat": "PTS",
                        "line": 24.5,
                    },
                    {
                        "player": "Miles Bridges",
                        "team": "CHA",
                        "opp": "CHI",
                        "home": 1,
                        "game_date": "2026-03-17",
                        "stat": "REB",
                        "line": 7.5,
                    },
                ]
            )

            enriched = enrich_with_matchups(
                projections=projections,
                roster_map_path=str(roster_path),
                slate_path=str(slate_path),
                default_game_date="2026-03-17",
                rotowire_lines_path=str(rotowire_path),
                role_metrics_path=str(role_metrics_path),
                attach_role_metrics=True,
            ).sort_values("player").reset_index(drop=True)

            self.assertEqual(len(enriched), 2)
            self.assertIn("team", enriched.columns)
            self.assertAlmostEqual(self._as_float(enriched.loc[0, "role_metrics_usg_pct"]), 31.4)
            self.assertEqual(enriched.loc[0, "role_metrics_snapshot_id"], "lamelo-snap")
            self.assertAlmostEqual(self._as_float(enriched.loc[1, "role_metrics_usg_pct"]), 27.1)
            self.assertEqual(enriched.loc[1, "role_metrics_snapshot_id"], "miles-snap")
            self.assertEqual(enriched.loc[0, "team"], "CHA")
            self.assertEqual(enriched.loc[1, "team"], "CHA")

    def test_role_metrics_are_not_attached_without_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            roster_path = root / "roster_map.csv"
            slate_path = root / "slate.csv"
            rotowire_path = root / "rotowire_lines.json"
            role_metrics_path = root / "role_metrics_latest.json"

            self._write_csv(
                roster_path,
                pd.DataFrame(
                    [
                        {"player": "LaMelo Ball", "team": "CHA"},
                    ]
                ),
            )
            self._write_csv(
                slate_path,
                pd.DataFrame(
                    [
                        {"game_date": "2026-03-17", "home_team": "CHA", "away_team": "CHI"},
                    ]
                ),
            )
            self._write_rotowire_json(rotowire_path, "2026-03-17")
            self._write_role_metrics_json(
                role_metrics_path,
                {
                    "game_date": "2026-03-17",
                    "rows": [
                        {
                            "player": "LaMelo Ball",
                            "player_key": "lamelo ball",
                            "team": "Charlotte",
                            "game_date": "2026-03-17",
                            "usg_pct": 31.4,
                            "snapshot_id": "snap-123",
                        }
                    ],
                },
            )

            projections = pd.DataFrame(
                [
                    {
                        "player": "LaMelo Ball",
                        "team": "CHA",
                        "opp": "CHI",
                        "home": 1,
                        "game_date": "2026-03-17",
                        "stat": "PTS",
                        "line": 24.5,
                    }
                ]
            )

            enriched = enrich_with_matchups(
                projections=projections,
                roster_map_path=str(roster_path),
                slate_path=str(slate_path),
                default_game_date="2026-03-17",
                rotowire_lines_path=str(rotowire_path),
                role_metrics_path=str(role_metrics_path),
            )

            self.assertEqual(len(enriched), 1)
            self.assertNotIn("role_metrics_usg_pct", enriched.columns)
            self.assertNotIn("role_metrics_snapshot_id", enriched.columns)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "import_github_prop_odds.py"
    spec = importlib.util.spec_from_file_location("import_github_prop_odds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_convert_rows_pairs_sides_and_devigs_market_probability() -> None:
    mod = _load_module()
    rows = mod.convert_rows(
        [
            {
                "player": "Jalen Brunson",
                "market": "player_assists",
                "side": "Over",
                "line": 6.5,
                "price_american": -105,
                "book_key": "draftkings",
                "event_id": "game-1",
                "away_team": "BOS",
                "home_team": "NYK",
            },
            {
                "player": "Jalen Brunson",
                "market": "player_assists",
                "side": "Under",
                "line": 6.5,
                "price_american": -115,
                "book_key": "draftkings",
                "event_id": "game-1",
                "away_team": "BOS",
                "home_team": "NYK",
            },
        ],
        source_name="github_childersjac_props",
        asof_ts="2026-05-04T15:33:10Z",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "github_childersjac_props"
    assert row["player"] == "Jalen Brunson"
    assert row["stat"] == "AST"
    assert row["line"] == "6.5"
    assert row["confidence"] == "0.95"
    assert abs(float(row["over_prob"]) + float(row["under_prob"]) - 1.0) < 1e-6
    assert "book=draftkings" in row["notes"]


def test_convert_rows_keeps_single_sided_rows_lower_confidence() -> None:
    mod = _load_module()
    rows = mod.convert_rows(
        [
            {
                "player": "Alpha Guard",
                "market": "player_points_rebounds_assists",
                "side": "Over",
                "line": "24.5",
                "price_american": "+120",
                "book_title": "FanDuel",
                "event_id": "game-2",
            }
        ],
        source_name="github_childersjac_props",
        asof_ts="2026-05-04T15:33:10Z",
    )

    assert len(rows) == 1
    assert rows[0]["stat"] == "PRA"
    assert rows[0]["over_prob"]
    assert rows[0]["under_prob"] == ""
    assert rows[0]["confidence"] == "0.70"

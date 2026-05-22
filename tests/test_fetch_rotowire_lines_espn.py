from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCHER_PATH = PROJECT_ROOT / "tools" / "fetch_rotowire_lines.py"

spec = importlib.util.spec_from_file_location("fetch_rotowire_lines", FETCHER_PATH)
fetch_rotowire_lines = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["fetch_rotowire_lines"] = fetch_rotowire_lines
spec.loader.exec_module(fetch_rotowire_lines)


def test_espn_details_spread_parses_home_favorite() -> None:
    odds = {
        "provider": {"name": "DraftKings"},
        "details": "OKC -7.5",
        "overUnder": 213.5,
        "spread": -7.5,
        "homeTeamOdds": {"favorite": True, "moneyLine": -258},
        "awayTeamOdds": {"favorite": False, "moneyLine": 210},
    }

    home_spread, away_spread = fetch_rotowire_lines._parse_espn_spread(odds, "OKC", "SAS")

    assert home_spread == -7.5
    assert away_spread == 7.5
    assert fetch_rotowire_lines.to_float(odds["overUnder"]) == 213.5


def test_espn_details_spread_parses_away_favorite_and_alias() -> None:
    odds = {
        "details": "SA -2.5",
        "spread": -2.5,
        "awayTeamOdds": {"favorite": True},
        "homeTeamOdds": {"favorite": False},
    }

    home_spread, away_spread = fetch_rotowire_lines._parse_espn_spread(odds, "OKC", "SAS")

    assert home_spread == 2.5
    assert away_spread == -2.5

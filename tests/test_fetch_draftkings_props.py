from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "fetch_draftkings_props.py"
    spec = importlib.util.spec_from_file_location("fetch_draftkings_props", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_draftkings_utc_start_maps_to_central_slate_date() -> None:
    tool = _load_tool()
    assert tool._local_slate_date("2026-05-21T00:45:00.0000000Z") == "2026-05-20"


def test_draftkings_milestone_maps_to_prizepicks_half_line() -> None:
    tool = _load_tool()
    assert tool._milestone_line({"milestoneValue": 10}) == 9.5
    assert tool._milestone_line({"label": "12+"}) == 11.5


def test_draftkings_american_odds_parser_handles_unicode_minus() -> None:
    tool = _load_tool()
    selection = {"displayOdds": {"american": "\u2212135"}}
    assert tool._american_odds(selection) == -135

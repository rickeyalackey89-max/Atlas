from __future__ import annotations

import pandas as pd

from Atlas.core.team_aliases import normalize_team_abbr
from Atlas.engine.new_probability import compute_role_multiplier
from Atlas.model.team_share_allocator_v2 import build_share_matrix_v2


def test_team_aliases_normalize_known_feed_variants() -> None:
    assert normalize_team_abbr("SA") == "SAS"
    assert normalize_team_abbr("SAS") == "SAS"
    assert normalize_team_abbr("GS") == "GSW"
    assert normalize_team_abbr("NO") == "NOP"
    assert normalize_team_abbr("NY") == "NYK"
    assert normalize_team_abbr("UTAH") == "UTA"
    assert normalize_team_abbr("WSH") == "WAS"
    assert normalize_team_abbr("Pnx") == "PHX"
    assert normalize_team_abbr("San Antonio Spurs") == "SAS"


def test_share_matrix_joins_sa_gamelogs_to_sas_iael() -> None:
    gamelogs = pd.DataFrame(
        [
            {
                "game_date": f"2026-01-0{day}",
                "player": "De'Aaron Fox",
                "team": "SA",
                "opp": "OKC",
                "minutes": 34,
                "pts": 24,
                "reb": 4,
                "ast": 8,
            }
            for day in range(1, 4)
        ]
        + [
            {
                "game_date": f"2026-01-0{day}",
                "player": "Victor Wembanyama",
                "team": "SA",
                "opp": "OKC",
                "minutes": 32,
                "pts": 27,
                "reb": 12,
                "ast": 4,
            }
            for day in range(1, 4)
        ]
        + [
            {
                "game_date": f"2026-01-0{day}",
                "player": "Devin Vassell",
                "team": "SA",
                "opp": "OKC",
                "minutes": 28,
                "pts": 18,
                "reb": 3,
                "ast": 3,
            }
            for day in range(1, 4)
        ]
    )
    iael = pd.DataFrame([{"team": "SAS", "player": "Fox, De'Aaron", "status": "OUT"}])

    share_matrix = build_share_matrix_v2(
        gamelogs,
        iael_df=iael,
        recent_days=365,
        min_rotation_games=1,
        min_rotation_avg_min=1,
        min_pattern_games=1,
    )

    assert not share_matrix.empty
    assert set(share_matrix["team"]) == {"SAS"}
    assert "De'Aaron Fox" in set(share_matrix["out_player"])

    mult, debug = compute_role_multiplier(
        share_matrix,
        iael,
        player="Victor Wembanyama",
        team="SAS",
        stat="PTS",
        min_games=1,
    )
    assert mult > 1.0
    assert debug["reason"] == "ok"
    assert debug["outs_used"] == 1

from __future__ import annotations

import pandas as pd

from Atlas.engine.gbm_ensemble import _ALL_FEATURE_NAMES, _derive_live_b2b_flags, compute_features


def test_live_b2b_uses_previous_completed_game_before_slate_date() -> None:
    scored = pd.DataFrame(
        [
            {"player": "Example Guard", "game_date": "2026-05-20"},
            {"player": "Rested Wing", "game_date": "2026-05-20"},
        ]
    )
    logs = pd.DataFrame(
        [
            {"player": "Example Guard", "game_date": "2026-05-19"},
            {"player": "Example Guard", "game_date": "2026-05-15"},
            {"player": "Rested Wing", "game_date": "2026-05-18"},
        ]
    )

    flags = _derive_live_b2b_flags(scored, logs)

    assert flags.tolist() == [1.0, 0.0]


def test_bp_score_gated_uses_external_prior_score_scale() -> None:
    scored = pd.DataFrame(
        [
            {
                "player": "Example Guard",
                "team": "OKC",
                "home_team": "OKC",
                "game_date": "2026-05-20",
                "stat": "PTS",
                "tier": "STANDARD",
                "direction": "OVER",
                "line": 12.5,
                "p_adj": 0.55,
                "external_prior_n": 1,
                "external_prior_score": 0.42,
                "q_blowout": 0.10,
                "rate_mean": 0.5,
                "rate_std": 0.1,
                "min_mean": 30.0,
                "min_std": 3.0,
                "games_used": 20,
            }
        ]
    )
    logs = pd.DataFrame(
        [
            {"player": "Example Guard", "game_date": "2026-05-18", "pts": 14},
            {"player": "Example Guard", "game_date": "2026-05-19", "pts": 15},
        ]
    )

    X, _ = compute_features(scored, logs)
    bp_idx = _ALL_FEATURE_NAMES.index("bp_score_gated")
    has_idx = _ALL_FEATURE_NAMES.index("bp_has")

    assert X[0, has_idx] == 1.0
    assert X[0, bp_idx] == 0.42


def test_is_home_falls_back_to_home_flag_when_home_team_is_empty() -> None:
    scored = pd.DataFrame(
        [
            {
                "player": "Example Guard",
                "team": "OKC",
                "home_team": None,
                "game_date": "2026-05-20",
                "stat": "PTS",
                "tier": "STANDARD",
                "direction": "OVER",
                "line": 12.5,
                "p_adj": 0.55,
                "home": 1,
                "q_blowout": 0.10,
                "rate_mean": 0.5,
                "rate_std": 0.1,
                "min_mean": 30.0,
                "min_std": 3.0,
                "games_used": 20,
            },
            {
                "player": "Example Wing",
                "team": "SAS",
                "home_team": None,
                "game_date": "2026-05-20",
                "stat": "REB",
                "tier": "STANDARD",
                "direction": "OVER",
                "line": 5.5,
                "p_adj": 0.55,
                "home": 0,
                "q_blowout": 0.10,
                "rate_mean": 0.2,
                "rate_std": 0.05,
                "min_mean": 28.0,
                "min_std": 3.0,
                "games_used": 20,
            },
        ]
    )
    logs = pd.DataFrame(
        [
            {"player": "Example Guard", "game_date": "2026-05-19", "pts": 15},
            {"player": "Example Wing", "game_date": "2026-05-19", "reb": 6},
        ]
    )

    X, _ = compute_features(scored, logs)
    home_idx = _ALL_FEATURE_NAMES.index("is_home_feat")

    assert X[:, home_idx].tolist() == [1.0, 0.0]

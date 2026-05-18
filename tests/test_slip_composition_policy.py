from __future__ import annotations

import pandas as pd

from Atlas.core.slip_builders import build_slips_by_tier_buckets
from Atlas.core.slip_composition_policy import (
    composition_drop_reason_for_item,
    composition_drop_reason_for_leg_parts,
    composition_drop_reason_for_legs,
    infer_slate_game_count,
    leg_parts_from_slip_row,
)


def _cfg() -> dict:
    return {
        "public_slip_quality": {
            "two_game_4_5_composition": {
                "enabled": True,
                "apply_to_slate_games": 2,
                "apply_to_legs": [4, 5],
                "max_stat_counts_by_legs": {
                    4: {"PRA": 0, "FG3M": 0},
                    5: {"PRA": 0, "FG3M": 0},
                },
                "max_same_stat_by_legs": {4: 2, 5: 2},
            }
        }
    }


def _leg(player: str, stat: str) -> dict:
    return {
        "player": player,
        "direction": "OVER",
        "stat": stat,
        "line": 10.5,
        "tier": "STANDARD",
    }


def test_infer_slate_game_count_prefers_single_game_games() -> None:
    frame = pd.DataFrame({"single_game_games": [2, 2, 3], "game_id": ["A", "B", "C"]})

    assert infer_slate_game_count(frame) == 2


def test_two_game_four_leg_rejects_pra() -> None:
    legs = [_leg("A", "PTS"), _leg("B", "PRA"), _leg("C", "REB"), _leg("D", "RA")]

    reason = composition_drop_reason_for_legs(legs, _cfg(), slate_games=2, n_legs=4)

    assert reason == "two_game_composition_pra_count_gt_0"


def test_two_game_five_leg_rejects_fg3m() -> None:
    legs = [
        _leg("A", "PTS"),
        _leg("B", "FG3M"),
        _leg("C", "REB"),
        _leg("D", "RA"),
        _leg("E", "PR"),
    ]

    reason = composition_drop_reason_for_legs(legs, _cfg(), slate_games=2, n_legs=5)

    assert reason == "two_game_composition_fg3m_count_gt_0"


def test_three_leg_is_not_controlled_by_two_game_four_five_policy() -> None:
    legs = [_leg("A", "PTS"), _leg("B", "PRA"), _leg("C", "FG3M")]

    reason = composition_drop_reason_for_legs(legs, _cfg(), slate_games=2, n_legs=3)

    assert reason == ""


def test_non_two_game_slate_is_not_controlled_by_two_game_policy() -> None:
    legs = [_leg("A", "PTS"), _leg("B", "PRA"), _leg("C", "REB"), _leg("D", "RA")]

    reason = composition_drop_reason_for_legs(legs, _cfg(), slate_games=3, n_legs=4)

    assert reason == ""


def test_same_stat_cap_rejects_excess_concentration() -> None:
    legs = [_leg("A", "PTS"), _leg("B", "PTS"), _leg("C", "PTS"), _leg("D", "RA")]

    reason = composition_drop_reason_for_legs(legs, _cfg(), slate_games=2, n_legs=4)

    assert reason == "two_game_composition_same_stat_count_gt_2"


def test_leg_parts_from_slip_row_feeds_item_policy() -> None:
    row = pd.Series(
        {
            "n_legs": 4,
            "legs": (
                "Player A OVER PTS 10.5 (GOBLIN) [id:1] | "
                "Player B UNDER PRA 20.5 (STANDARD) [id:2] | "
                "Player C OVER REB 5.5 (GOBLIN) [id:3] | "
                "Player D OVER RA 7.5 (STANDARD) [id:4]"
            ),
        }
    )
    item = {
        "n_legs": int(row["n_legs"]),
        "leg_parts": leg_parts_from_slip_row(row),
    }

    reason = composition_drop_reason_for_item(item, _cfg(), slate_games=2)

    assert reason == "two_game_composition_pra_count_gt_0"


def test_direct_section_config_is_accepted() -> None:
    section = _cfg()["public_slip_quality"]
    parts = [_leg("A", "PTS"), _leg("B", "RA"), _leg("C", "REB"), _leg("D", "PR")]

    reason = composition_drop_reason_for_leg_parts(parts, section, slate_games=2, n_legs=4)

    assert reason == ""


def test_system_builder_generates_replacement_after_rejecting_bad_two_game_composition() -> None:
    cfg = _cfg()
    cfg["slip_build"] = {
        "target_pool_mult": 20,
        "phase1_frac": 1.0,
        "phase1_pool_frac": 0.5,
        "beam_width": 50,
        "max_slips_per_player": 2,
        "require_healthy_data": False,
    }
    rows = [
        _row(1, "G1", "GOBLIN", "PTS", 0.90, "A", "B", "g1"),
        _row(2, "G2", "GOBLIN", "REB", 0.88, "C", "D", "g2"),
        _row(3, "Sbad", "STANDARD", "PRA", 0.99, "A", "B", "g1"),
        _row(4, "S1", "STANDARD", "RA", 0.75, "C", "D", "g2"),
        _row(5, "S2", "STANDARD", "PR", 0.70, "A", "B", "g1"),
    ]

    out = build_slips_by_tier_buckets(
        legs_df=pd.DataFrame(rows),
        n_legs=4,
        top_n=1,
        payout_power_mult=10,
        payout_flex=None,
        pricing_engine="atlas",
        cfg=cfg,
        seed=3,
        per_tier=10,
        max_attempts=500,
        sort_mode="hit",
        mixes={4: {"GOBLIN": 2, "STANDARD": 2}},
        required_tiers=["GOBLIN", "STANDARD"],
        mix_ok_fn=lambda *_: True,
    )

    assert len(out) == 1
    assert "PRA" not in out.loc[0, "legs"]
    assert "S1 OVER RA" in out.loc[0, "legs"]
    assert "S2 OVER PR" in out.loc[0, "legs"]


def _row(
    projection_id: int,
    player: str,
    tier: str,
    stat: str,
    p_cal: float,
    team: str,
    opp: str,
    game_id: str,
) -> dict:
    return {
        "projection_id": projection_id,
        "player": player,
        "tier": tier,
        "stat": stat,
        "direction": "OVER",
        "line": 10.5,
        "p_cal": p_cal,
        "team": team,
        "opp": opp,
        "game_id": game_id,
    }

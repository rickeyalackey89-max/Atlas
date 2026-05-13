from __future__ import annotations

import pandas as pd

from Atlas.core.single_game_script import (
    apply_single_game_script_annotations,
    apply_single_game_selection_surface,
    single_game_slip_rule_status,
)


def _cfg() -> dict:
    return {
        "single_game_mode": {
            "enabled": "auto",
            "trigger_max_games": 1,
            "primary_script": "close_spurs_efficiency_wolves_glass",
            "selection_surface": {"enabled": True, "script_fit_weight": 1.0},
            "slip_rules": {
                "enabled": True,
                "max_role_shooter_overs": 1,
                "max_fg3m_overs": 1,
                "max_low_minute_bench_overs": 0,
                "require_non_shooting_volume_min_legs": 4,
                "require_one_stable_anchor": True,
                "min_avg_script_fit_by_legs": {5: 0.0},
            },
        }
    }


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "projection_id": "1",
                "game_id": "g1",
                "player": "Julius Randle",
                "team": "MIN",
                "opp": "SAS",
                "stat": "REB",
                "direction": "OVER",
                "modeled_minutes": 34.0,
                "p_eff": 0.66,
            },
            {
                "projection_id": "2",
                "game_id": "g1",
                "player": "Naz Reid",
                "team": "MIN",
                "opp": "SAS",
                "stat": "PR",
                "direction": "OVER",
                "modeled_minutes": 29.0,
                "p_eff": 0.64,
            },
            {
                "projection_id": "3",
                "game_id": "g1",
                "player": "Dylan Harper",
                "team": "SAS",
                "opp": "MIN",
                "stat": "REB",
                "direction": "OVER",
                "modeled_minutes": 25.0,
                "p_eff": 0.63,
            },
            {
                "projection_id": "4",
                "game_id": "g1",
                "player": "Julian Champagnie",
                "team": "SAS",
                "opp": "MIN",
                "stat": "PRA",
                "direction": "OVER",
                "modeled_minutes": 28.5,
                "p_eff": 0.62,
            },
            {
                "projection_id": "5",
                "game_id": "g1",
                "player": "Terrence Shannon",
                "team": "MIN",
                "opp": "SAS",
                "stat": "PA",
                "direction": "OVER",
                "modeled_minutes": 26.0,
                "p_eff": 0.61,
            },
        ]
    )


def test_single_game_annotations_score_script_fit() -> None:
    out = apply_single_game_script_annotations(_rows(), _cfg())

    assert bool(out["single_game_slate"].iloc[0]) is True

    randle = out[out["player"] == "Julius Randle"].iloc[0]
    assert randle["single_game_anchor_flag"] == 1
    assert randle["single_game_min_glass_flag"] == 1
    assert round(float(randle["single_game_script_fit"]), 2) == 0.13

    harper = out[out["player"] == "Dylan Harper"].iloc[0]
    assert harper["single_game_sas_core_flag"] == 1
    assert round(float(harper["single_game_script_fit"]), 2) == 0.05


def test_single_game_ra_uses_rebound_led_profile_when_share_missing() -> None:
    df = _rows()
    df.loc[0, "stat"] = "RA"

    out = apply_single_game_script_annotations(df, _cfg())
    randle = out[out["player"] == "Julius Randle"].iloc[0]

    assert "rebound_led_ra_profile" in str(randle["single_game_script_reasons"])
    assert round(float(randle["single_game_script_fit"]), 2) == 0.17


def test_script_volume_flags_apply_to_overs_only() -> None:
    df = _rows()
    df.loc[0, ["stat", "direction"]] = ["RA", "UNDER"]

    out = apply_single_game_script_annotations(df, _cfg())
    randle = out[out["player"] == "Julius Randle"].iloc[0]

    assert int(randle["single_game_min_glass_flag"]) == 0
    assert int(randle["single_game_non_shooting_volume_flag"]) == 0
    assert "min_glass_counterpunch" not in str(randle["single_game_script_reasons"])


def test_single_game_injury_branch_penalizes_uncertain_guard_and_boosts_creation() -> None:
    df = pd.DataFrame(
        [
            {"game_id": "g1", "player": "De'Aaron Fox", "team": "SAS", "opp": "MIN", "stat": "PR", "direction": "OVER", "modeled_minutes": 32.0, "is_questionable": 1},
            {"game_id": "g1", "player": "Stephon Castle", "team": "SAS", "opp": "MIN", "stat": "PA", "direction": "OVER", "modeled_minutes": 33.0, "is_questionable": 0},
            {"game_id": "g1", "player": "Victor Wembanyama", "team": "SAS", "opp": "MIN", "stat": "PRA", "direction": "OVER", "modeled_minutes": 35.0, "is_questionable": 0},
        ]
    )

    out = apply_single_game_script_annotations(df, _cfg())

    assert str(out["single_game_branch_label"].iloc[0]) == "fox_uncertain"
    fox = out[out["player"] == "De'Aaron Fox"].iloc[0]
    castle = out[out["player"] == "Stephon Castle"].iloc[0]
    wemby = out[out["player"] == "Victor Wembanyama"].iloc[0]

    assert "fox_questionable_penalty" in str(fox["single_game_script_reasons"])
    assert "fox_questionable_castle_creation" in str(castle["single_game_script_reasons"])
    assert "fox_questionable_wemby_touch" in str(wemby["single_game_script_reasons"])
    assert float(castle["single_game_script_fit"]) > float(fox["single_game_script_fit"])


def test_single_game_selection_surface_adjusts_selection_only_score() -> None:
    out = apply_single_game_selection_surface(_rows(), _cfg(), score_col="p_eff", clip_score=True)

    randle = out[out["player"] == "Julius Randle"].iloc[0]
    assert round(float(randle["p_eff_pre_single_game"]), 2) == 0.66
    assert round(float(randle["single_game_selection_delta"]), 2) == 0.13
    assert round(float(randle["p_eff"]), 2) == 0.79


def test_single_game_rules_do_not_block_five_leg_by_size() -> None:
    out = apply_single_game_script_annotations(_rows(), _cfg())
    rows = [r for _, r in out.iterrows()]

    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=5)

    assert ok is True
    assert reasons == []
    assert metrics["single_game_anchor_legs"] >= 1


def test_single_game_rules_reject_shooter_stacks_not_slip_size() -> None:
    df = _rows()
    df.loc[0, ["player", "stat"]] = ["Ayo Dosunmu", "FG3M"]
    df.loc[1, ["player", "stat"]] = ["Jaden McDaniels", "FG3M"]
    out = apply_single_game_script_annotations(df, _cfg())
    rows = [r for _, r in out.iterrows()]

    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=5)

    assert ok is False
    assert "max_fg3m_overs_exceeded" in reasons
    assert metrics["single_game_fg3m_overs"] == 2


def test_single_game_rules_require_non_shooting_volume_for_larger_slips() -> None:
    df = pd.DataFrame(
        [
            {"game_id": "g1", "player": "Anthony Edwards", "team": "MIN", "opp": "SAS", "stat": "PTS", "direction": "OVER", "modeled_minutes": 34.0},
            {"game_id": "g1", "player": "Victor Wembanyama", "team": "SAS", "opp": "MIN", "stat": "PTS", "direction": "OVER", "modeled_minutes": 35.0},
            {"game_id": "g1", "player": "Stephon Castle", "team": "SAS", "opp": "MIN", "stat": "AST", "direction": "OVER", "modeled_minutes": 33.0},
            {"game_id": "g1", "player": "Devin Vassell", "team": "SAS", "opp": "MIN", "stat": "PTS", "direction": "OVER", "modeled_minutes": 30.0},
        ]
    )
    out = apply_single_game_script_annotations(df, _cfg())
    rows = [r for _, r in out.iterrows()]

    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=4)

    assert ok is False
    assert "missing_non_shooting_volume_leg" in reasons
    assert metrics["single_game_non_shooting_volume_legs"] == 0


def test_profile_specific_rules_do_not_fire_for_other_single_game() -> None:
    df = _rows()
    df["team"] = ["BOS", "BOS", "NYK", "NYK", "BOS"]
    df["opp"] = ["NYK", "NYK", "BOS", "BOS", "NYK"]

    out = apply_single_game_script_annotations(df, _cfg())
    rows = [r for _, r in out.iterrows()]
    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=5)

    assert bool(out["single_game_slate"].iloc[0]) is True
    assert bool(out["single_game_profile_active"].iloc[0]) is False
    assert ok is True
    assert reasons == []
    assert metrics == {}

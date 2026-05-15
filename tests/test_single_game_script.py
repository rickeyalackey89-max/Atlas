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
            "selection_surface": {"enabled": True, "robustness_weight": 1.0},
            "slip_rules": {
                "enabled": True,
                "max_role_shooter_overs": 1,
                "max_fg3m_overs": 1,
                "max_low_minute_bench_overs": 0,
                "max_low_line_noise_legs_by_legs": {2: 0, 3: 1, 4: 1},
                "min_non_shooting_volume_legs_by_legs": {2: 1, 3: 1, 4: 2},
                "require_one_stable_anchor": True,
                "min_multi_script_survival_legs_by_legs": {2: 1, 3: 1, 4: 2},
                "min_avg_robustness_by_legs": {2: -0.01, 3: -0.02, 4: -0.01},
            },
        }
    }


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "projection_id": "1",
                "game_id": "g1",
                "player": "Core Rebounder",
                "team": "MIN",
                "opp": "SAS",
                "stat": "REB",
                "direction": "OVER",
                "line": 7.5,
                "modeled_minutes": 34.0,
                "p_eff": 0.66,
            },
            {
                "projection_id": "2",
                "game_id": "g1",
                "player": "Core Creator",
                "team": "MIN",
                "opp": "SAS",
                "stat": "PA",
                "direction": "OVER",
                "line": 19.5,
                "modeled_minutes": 31.0,
                "p_eff": 0.64,
            },
            {
                "projection_id": "3",
                "game_id": "g1",
                "player": "Bench Shooter",
                "team": "SAS",
                "opp": "MIN",
                "stat": "FG3M",
                "direction": "OVER",
                "line": 0.5,
                "modeled_minutes": 16.0,
                "p_eff": 0.63,
            },
            {
                "projection_id": "4",
                "game_id": "g1",
                "player": "Core Scorer",
                "team": "SAS",
                "opp": "MIN",
                "stat": "PTS",
                "direction": "OVER",
                "line": 18.5,
                "modeled_minutes": 32.0,
                "p_eff": 0.62,
            },
            {
                "projection_id": "5",
                "game_id": "g1",
                "player": "Low Line Scorer",
                "team": "MIN",
                "opp": "SAS",
                "stat": "PTS",
                "direction": "OVER",
                "line": 5.5,
                "modeled_minutes": 22.0,
                "p_eff": 0.61,
            },
        ]
    )


def test_single_game_annotations_score_generic_robustness() -> None:
    out = apply_single_game_script_annotations(_rows(), _cfg())

    assert bool(out["single_game_slate"].iloc[0]) is True
    assert str(out["single_game_script_label"].iloc[0]) == "single_game_robust_mode"

    core = out[out["player"] == "Core Rebounder"].iloc[0]
    assert core["single_game_anchor_flag"] == 1
    assert core["single_game_multi_script_survival_flag"] == 1
    assert "multi_script_survival" in str(core["single_game_script_reasons"])
    assert round(float(core["single_game_script_fit"]), 2) == 0.07

    shooter = out[out["player"] == "Bench Shooter"].iloc[0]
    assert shooter["single_game_role_shooter_over_flag"] == 1
    assert shooter["single_game_fg3m_over_flag"] == 1
    assert shooter["single_game_low_minute_bench_over_flag"] == 1
    assert shooter["single_game_low_line_noise_flag"] == 1
    assert float(shooter["single_game_script_fit"]) < 0


def test_single_game_robustness_has_no_team_specific_script_reasons() -> None:
    out = apply_single_game_script_annotations(_rows(), _cfg())
    reasons = ";".join(out["single_game_script_reasons"].astype(str).tolist())

    assert "min_glass_counterpunch" not in reasons
    assert "sas_core_efficiency" not in reasons
    assert "fox_" not in reasons
    assert "harper_" not in reasons


def test_low_line_noise_applies_to_overs_only() -> None:
    df = _rows()
    df.loc[df["player"] == "Low Line Scorer", "direction"] = "UNDER"

    out = apply_single_game_script_annotations(df, _cfg())
    low_line = out[out["player"] == "Low Line Scorer"].iloc[0]

    assert int(low_line["single_game_low_line_noise_flag"]) == 0
    assert "low_line_noise" not in str(low_line["single_game_script_reasons"])


def test_injury_uncertainty_penalizes_selection_only() -> None:
    df = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "player": "Questionable Core",
                "team": "SAS",
                "opp": "MIN",
                "stat": "PA",
                "direction": "OVER",
                "line": 19.5,
                "modeled_minutes": 33.0,
                "p_eff": 0.70,
                "is_questionable": 1,
            },
            {
                "game_id": "g1",
                "player": "Clean Core",
                "team": "MIN",
                "opp": "SAS",
                "stat": "PA",
                "direction": "OVER",
                "line": 19.5,
                "modeled_minutes": 33.0,
                "p_eff": 0.70,
                "is_questionable": 0,
            },
        ]
    )

    out = apply_single_game_script_annotations(df, _cfg())

    questionable = out[out["player"] == "Questionable Core"].iloc[0]
    clean = out[out["player"] == "Clean Core"].iloc[0]
    assert "injury_uncertainty" in str(questionable["single_game_script_reasons"])
    assert float(questionable["single_game_script_fit"]) < float(clean["single_game_script_fit"])


def test_single_game_selection_surface_adjusts_selection_only_score() -> None:
    out = apply_single_game_selection_surface(_rows(), _cfg(), score_col="p_eff", clip_score=True)

    core = out[out["player"] == "Core Rebounder"].iloc[0]
    assert round(float(core["p_eff_pre_single_game"]), 2) == 0.66
    assert round(float(core["single_game_selection_delta"]), 2) == 0.07
    assert round(float(core["p_eff"]), 2) == 0.73


def test_single_game_rules_reject_low_minute_fragility_not_size() -> None:
    out = apply_single_game_script_annotations(_rows(), _cfg())
    rows = [r for _, r in out.iterrows()]

    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=5)

    assert ok is False
    assert "max_low_minute_bench_overs_exceeded" in reasons
    assert metrics["single_game_anchor_legs"] >= 1


def test_single_game_rules_reject_shooter_stacks() -> None:
    df = _rows()
    df.loc[0, ["player", "stat", "modeled_minutes", "line"]] = ["Shooter One", "FG3M", 20.0, 0.5]
    df.loc[1, ["player", "stat", "modeled_minutes", "line"]] = ["Shooter Two", "FG3M", 21.0, 0.5]
    out = apply_single_game_script_annotations(df, _cfg())
    rows = [r for _, r in out.iterrows()]

    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=5)

    assert ok is False
    assert "max_fg3m_overs_exceeded" in reasons
    assert metrics["single_game_fg3m_overs"] == 3


def test_single_game_rules_require_non_shooting_volume_for_larger_slips() -> None:
    df = pd.DataFrame(
        [
            {"game_id": "g1", "player": "Alpha", "team": "MIN", "opp": "SAS", "stat": "PTS", "direction": "OVER", "line": 14.5, "modeled_minutes": 34.0},
            {"game_id": "g1", "player": "Beta", "team": "SAS", "opp": "MIN", "stat": "PTS", "direction": "OVER", "line": 16.5, "modeled_minutes": 35.0},
            {"game_id": "g1", "player": "Gamma", "team": "SAS", "opp": "MIN", "stat": "PTS", "direction": "OVER", "line": 12.5, "modeled_minutes": 33.0},
            {"game_id": "g1", "player": "Delta", "team": "MIN", "opp": "SAS", "stat": "PTS", "direction": "OVER", "line": 10.5, "modeled_minutes": 30.0},
        ]
    )
    out = apply_single_game_script_annotations(df, _cfg())
    rows = [r for _, r in out.iterrows()]

    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=4)

    assert ok is False
    assert "missing_non_shooting_volume_leg" in reasons
    assert metrics["single_game_non_shooting_volume_legs"] == 0


def test_rules_apply_to_any_single_game_matchup() -> None:
    df = _rows()
    df["team"] = ["BOS", "BOS", "NYK", "NYK", "BOS"]
    df["opp"] = ["NYK", "NYK", "BOS", "BOS", "NYK"]

    out = apply_single_game_script_annotations(df, _cfg())
    rows = [r for _, r in out.iterrows()]
    ok, reasons, metrics = single_game_slip_rule_status(rows, _cfg(), n_legs=5)

    assert bool(out["single_game_slate"].iloc[0]) is True
    assert bool(out["single_game_profile_active"].iloc[0]) is True
    assert ok is False
    assert "max_low_minute_bench_overs_exceeded" in reasons
    assert metrics["single_game_anchor_legs"] >= 1

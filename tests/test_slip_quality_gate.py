from __future__ import annotations

import pandas as pd

from Atlas.core.slip_quality_gate import (
    apply_public_portfolio_exposure,
    build_slip_consensus_counts,
    filter_marketed_slips,
    filter_slip_frame,
)


def _cfg() -> dict:
    return {
        "public_slip_quality": {
            "enabled": True,
            "score": {
                "consensus_bonus_per_leg": 0.02,
                "avg_fragility_penalty_w": 0.20,
                "pen_total_w": 0.20,
                "minute_risk_penalty": 0.05,
                "q_leg_penalty": 0.04,
                "single_game_robustness_w": 0.05,
                "single_game_dependency_w": 0.05,
            },
            "min_survival_score_by_legs": {2: 0.56, 3: 0.56},
            "single_game_min_survival_score_by_legs": {2: 0.57, 3: 0.59},
            "single_game_min_hit_prob_by_legs": {2: 0.40, 3: 0.35},
            "max_minute_risk_legs_by_legs": {2: 0, 3: 0},
            "max_q_legs_by_legs": {2: 0, 3: 0},
            "exposure": {
                "enabled": True,
                "max_exact_prop_repeats_across_public": 1,
                "max_player_repeats_across_public": 1,
                "max_rows_per_public_output": 1,
                "priority": ["Marketed", "System", "Windfall", "DemonHunter"],
            },
        }
    }


def test_filter_slip_frame_drops_low_survival_score() -> None:
    frame = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "avg_fragility": 0.20,
                "pen_total": 0.0,
            },
            {
                "n_legs": 2,
                "legs": "Player C OVER PTS 10.5 (GOBLIN) [id:3] | Player D OVER REB 5.5 (STANDARD) [id:4]",
                "hit_prob": 0.25,
                "avg_p": 0.51,
                "min_p": 0.48,
                "avg_fragility": 0.45,
                "pen_total": 0.05,
            },
        ]
    )

    out = filter_slip_frame(frame, _cfg(), family="System")

    assert len(out) == 1
    assert bool(out.loc[0, "public_quality_pass"]) is True
    assert out.loc[0, "public_survival_score"] > 0.56


def test_consensus_counts_exact_props_across_families() -> None:
    system = pd.DataFrame(
        [{"legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1]", "n_legs": 1, "avg_p": 0.7, "min_p": 0.7}]
    )
    windfall = pd.DataFrame(
        [{"legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1]", "n_legs": 1, "avg_p": 0.7, "min_p": 0.7}]
    )

    counts = build_slip_consensus_counts({"System": [system], "Windfall": [windfall]})

    assert counts["player a|OVER|PTS|10.5"] == 2


def test_portfolio_exposure_prefers_marketed_then_drops_duplicate_frame_slip() -> None:
    cfg = _cfg()
    system = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "public_quality_pass": True,
                "public_survival_score": 0.66,
            }
        ]
    )
    marketed = [
        {
            "label": "2-leg",
            "n_legs": 2,
            "hit_prob": 0.46,
            "legs": [
                {"player": "Player A", "direction": "OVER", "stat": "PTS", "line": 10.5, "tier": "GOBLIN", "p_cal": 0.70},
                {"player": "Player C", "direction": "OVER", "stat": "AST", "line": 4.5, "tier": "STANDARD", "p_cal": 0.68},
            ],
        }
    ]

    result = apply_public_portfolio_exposure({"System_2leg": system}, marketed, cfg)

    assert len(result.marketed_slips) == 1
    assert result.frames["System_2leg"].empty
    assert result.manifest["dropped_count"] == 1
    assert result.manifest["drops"][0]["reason"] == "exact_prop_exposure_cap"


def test_portfolio_exposure_drops_same_player_different_prop() -> None:
    cfg = _cfg()
    system = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PR 16.5 (STANDARD) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "public_quality_pass": True,
                "public_survival_score": 0.66,
            }
        ]
    )
    marketed = [
        {
            "label": "2-leg",
            "n_legs": 2,
            "hit_prob": 0.46,
            "legs": [
                {"player": "Player A", "direction": "OVER", "stat": "PTS", "line": 10.5, "tier": "GOBLIN", "p_cal": 0.70},
                {"player": "Player C", "direction": "OVER", "stat": "AST", "line": 4.5, "tier": "STANDARD", "p_cal": 0.68},
            ],
        }
    ]

    result = apply_public_portfolio_exposure({"System_2leg": system}, marketed, cfg)

    assert len(result.marketed_slips) == 1
    assert result.frames["System_2leg"].empty
    assert result.manifest["drops"][0]["reason"] == "player_exposure_cap"
    assert result.manifest["drops"][0]["player_keys"] == ["player a", "player b"]


def test_portfolio_exposure_uses_alternate_candidate_for_filled_output() -> None:
    cfg = _cfg()
    system = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PR 16.5 (STANDARD) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "public_quality_pass": True,
                "public_survival_score": 0.90,
            },
            {
                "n_legs": 2,
                "legs": "Player D OVER PTS 10.5 (GOBLIN) [id:3] | Player E OVER AST 4.5 (STANDARD) [id:4]",
                "hit_prob": 0.44,
                "avg_p": 0.66,
                "min_p": 0.64,
                "public_quality_pass": True,
                "public_survival_score": 0.70,
            },
            {
                "n_legs": 2,
                "legs": "Player F OVER PTS 10.5 (GOBLIN) [id:5] | Player G OVER AST 4.5 (STANDARD) [id:6]",
                "hit_prob": 0.43,
                "avg_p": 0.65,
                "min_p": 0.63,
                "public_quality_pass": True,
                "public_survival_score": 0.69,
            },
        ]
    )
    marketed = [
        {
            "label": "2-leg",
            "n_legs": 2,
            "hit_prob": 0.46,
            "legs": [
                {"player": "Player A", "direction": "OVER", "stat": "PTS", "line": 10.5, "tier": "GOBLIN", "p_cal": 0.70},
                {"player": "Player C", "direction": "OVER", "stat": "AST", "line": 4.5, "tier": "STANDARD", "p_cal": 0.68},
            ],
        }
    ]

    result = apply_public_portfolio_exposure({"System_2leg": system}, marketed, cfg)

    assert len(result.marketed_slips) == 1
    assert len(result.frames["System_2leg"]) == 1
    assert "Player D" in result.frames["System_2leg"].loc[0, "legs"]
    reasons = [drop["reason"] for drop in result.manifest["drops"]]
    assert "player_exposure_cap" in reasons
    assert "public_output_slot_filled" in reasons


def test_portfolio_exposure_uses_single_game_player_cap_override() -> None:
    cfg = _cfg()
    cfg["public_slip_quality"]["exposure"]["max_player_repeats_across_public_by_slate_games"] = {1: 2}
    system = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PR 16.5 (STANDARD) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "public_quality_pass": True,
                "public_survival_score": 0.66,
            }
        ]
    )
    marketed = [
        {
            "label": "2-leg",
            "n_legs": 2,
            "hit_prob": 0.46,
            "legs": [
                {"player": "Player A", "direction": "OVER", "stat": "PTS", "line": 10.5, "tier": "GOBLIN", "p_cal": 0.70},
                {"player": "Player C", "direction": "OVER", "stat": "AST", "line": 4.5, "tier": "STANDARD", "p_cal": 0.68},
            ],
        }
    ]
    slate_source = pd.DataFrame({"single_game_games": [1, 1]})

    result = apply_public_portfolio_exposure({"System_2leg": system}, marketed, cfg, slate_source=slate_source)

    assert len(result.marketed_slips) == 1
    assert len(result.frames["System_2leg"]) == 1
    assert result.manifest["max_player_repeats_across_public"] == 2


def test_portfolio_exposure_prefers_system_before_windfall_duplicate() -> None:
    cfg = _cfg()
    system = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "public_quality_pass": True,
                "public_survival_score": 0.62,
            }
        ]
    )
    windfall = pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1] | Player C OVER AST 4.5 (STANDARD) [id:3]",
                "hit_prob": 0.46,
                "avg_p": 0.70,
                "min_p": 0.68,
                "public_quality_pass": True,
                "public_survival_score": 0.80,
            }
        ]
    )

    result = apply_public_portfolio_exposure(
        {"System_2leg": system, "Windfall_2leg": windfall},
        marketed_slips=[],
        cfg=cfg,
    )

    assert len(result.frames["System_2leg"]) == 1
    assert result.frames["Windfall_2leg"].empty
    assert result.manifest["drops"][0]["family"] == "Windfall"
    assert result.manifest["priority"] == ["Marketed", "System", "Windfall", "DemonHunter"]


def test_portfolio_exposure_can_disable_demonhunter_by_slate_games() -> None:
    cfg = _cfg()
    cfg["public_slip_quality"]["include_demonhunter_by_slate_games"] = {2: False}
    demonhunter = pd.DataFrame(
        [
            {
                "n_legs": 3,
                "legs": "Player A OVER PTS 10.5 (DEMON) [id:1] | Player B OVER REB 5.5 (DEMON) [id:2]",
                "hit_prob": 0.46,
                "avg_p": 0.68,
                "min_p": 0.66,
                "public_quality_pass": True,
                "public_survival_score": 0.66,
            }
        ]
    )
    slate_source = pd.DataFrame({"single_game_games": [2, 2, 2]})

    result = apply_public_portfolio_exposure(
        {"DemonHunter": demonhunter},
        marketed_slips=[],
        cfg=cfg,
        slate_source=slate_source,
    )

    assert result.frames["DemonHunter"].empty
    assert result.manifest["slate_games"] == 2
    assert result.manifest["drops"][0]["reason"] == "family_disabled_for_slate"


def test_two_game_composition_gate_drops_fragile_4_and_5_leg_stats_only() -> None:
    cfg = _cfg()
    cfg["public_slip_quality"]["two_game_4_5_composition"] = {
        "enabled": True,
        "apply_to_slate_games": 2,
        "apply_to_legs": [4, 5],
        "max_stat_counts_by_legs": {
            4: {"PRA": 0, "FG3M": 0},
            5: {"PRA": 0, "FG3M": 0},
        },
        "max_same_stat_by_legs": {4: 2, 5: 2},
    }
    fragile_4 = pd.DataFrame(
        [
            {
                "n_legs": 4,
                "legs": (
                    "Player A OVER PTS 10.5 (GOBLIN) [id:1] | "
                    "Player B OVER PRA 20.5 (STANDARD) [id:2] | "
                    "Player C OVER REB 5.5 (GOBLIN) [id:3] | "
                    "Player D OVER PR 15.5 (STANDARD) [id:4]"
                ),
                "hit_prob": 0.35,
                "avg_p": 0.72,
                "min_p": 0.68,
                "public_quality_pass": True,
                "public_survival_score": 0.70,
            }
        ]
    )
    clean_4 = pd.DataFrame(
        [
            {
                "n_legs": 4,
                "legs": (
                    "Player E OVER PTS 10.5 (GOBLIN) [id:5] | "
                    "Player F OVER RA 7.5 (STANDARD) [id:6] | "
                    "Player G OVER REB 5.5 (GOBLIN) [id:7] | "
                    "Player H OVER PR 15.5 (STANDARD) [id:8]"
                ),
                "hit_prob": 0.35,
                "avg_p": 0.72,
                "min_p": 0.68,
                "public_quality_pass": True,
                "public_survival_score": 0.70,
            }
        ]
    )
    three_leg_is_untouched = pd.DataFrame(
        [
            {
                "n_legs": 3,
                "legs": (
                    "Player I OVER PTS 10.5 (GOBLIN) [id:9] | "
                    "Player J OVER PRA 20.5 (STANDARD) [id:10] | "
                    "Player K OVER REB 5.5 (GOBLIN) [id:11]"
                ),
                "hit_prob": 0.35,
                "avg_p": 0.72,
                "min_p": 0.68,
                "public_quality_pass": True,
                "public_survival_score": 0.70,
            }
        ]
    )
    slate_source = pd.DataFrame({"game_id": ["A", "A", "B", "B"]})

    result = apply_public_portfolio_exposure(
        {
            "System_4leg_fragile": fragile_4,
            "System_4leg_clean": clean_4,
            "System_3leg": three_leg_is_untouched,
        },
        marketed_slips=[],
        cfg=cfg,
        slate_source=slate_source,
    )

    assert result.frames["System_4leg_fragile"].empty
    assert len(result.frames["System_4leg_clean"]) == 1
    assert len(result.frames["System_3leg"]) == 1
    assert result.manifest["drops"][0]["reason"] == "two_game_composition_pra_count_gt_0"


def test_filter_marketed_slips_respects_single_game_quality_floor() -> None:
    cfg = _cfg()
    slips = [
        {
            "label": "2-leg",
            "n_legs": 2,
            "hit_prob": 0.50,
            "single_game_avg_robustness_score": 0.60,
            "single_game_avg_script_dependency_score": 0.0,
            "legs": [
                {"player": "Player A", "direction": "OVER", "stat": "PTS", "line": 10.5, "tier": "GOBLIN", "p_cal": 0.70},
                {"player": "Player B", "direction": "OVER", "stat": "REB", "line": 5.5, "tier": "GOBLIN", "p_cal": 0.69},
            ],
        },
        {
            "label": "2-leg",
            "n_legs": 2,
            "hit_prob": 0.20,
            "single_game_avg_robustness_score": 0.30,
            "single_game_avg_script_dependency_score": 0.20,
            "legs": [
                {"player": "Player C", "direction": "OVER", "stat": "PTS", "line": 10.5, "tier": "GOBLIN", "p_cal": 0.50},
                {"player": "Player D", "direction": "OVER", "stat": "FG3M", "line": 0.5, "tier": "GOBLIN", "p_cal": 0.49},
            ],
        },
    ]

    out = filter_marketed_slips(slips, cfg)

    assert len(out) == 1
    assert out[0]["label"] == "2-leg"
    assert out[0]["public_survival_score"] > 0.57

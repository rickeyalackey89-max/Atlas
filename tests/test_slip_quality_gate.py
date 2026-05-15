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
                "priority": ["Marketed", "Windfall", "System", "DemonHunter"],
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

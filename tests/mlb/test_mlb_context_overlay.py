from __future__ import annotations

import json

from mlb.context.baseball_context import build_context_packet
from mlb.contracts.mlb_context_contract import GATE_CAUTION, GATE_OK, GATE_SUPPRESS
from mlb.overlays.mlb_publication_overlay import write_baseball_context_artifacts


def test_unknown_hitter_lineup_suppresses_publication():
    packet = build_context_packet(
        _leg(
            market="hits",
            market_group="hitter",
            lineup_context_available=False,
            lineup_confirmed=False,
            lineup_probability=0.0,
            batting_order_slot=0,
            feature_context_joined=True,
            matchup_context_available=True,
        )
    )

    assert packet["lineup_status"] == "unknown"
    assert packet["gate_level"] == GATE_SUPPRESS
    assert packet["public_publish_ok"] is False
    assert "unknown_lineup" in packet["tags"]
    assert "unknown_hitter_lineup" in packet["gate_reasons"]


def test_confirmed_top_order_hitter_gets_volume_tag_without_probability_mutation():
    row = _leg(
        market="hits",
        market_group="hitter",
        batting_order_slot=2,
        lineup_probability=1.0,
        lineup_confirmed=True,
        feature_context_joined=True,
        matchup_context_available=True,
        model_probability=0.72,
        p_cal=0.71,
    )
    before = dict(row)

    packet = build_context_packet(row)

    assert row == before
    assert packet["lineup_status"] == "confirmed"
    assert packet["batting_order_bucket"] == "premium_top_order"
    assert packet["gate_level"] == GATE_OK
    assert packet["model_probability"] == 0.72
    assert packet["p_cal"] == 0.71
    assert "top_order_volume" in packet["tags"]


def test_unknown_pitcher_starter_suppresses_pitcher_props():
    packet = build_context_packet(
        _leg(
            market="pitching_outs",
            market_group="pitcher",
            probable_pitcher_context_available=False,
            feature_context_joined=True,
            matchup_context_available=True,
        )
    )

    assert packet["pitcher_status"] == "unknown"
    assert packet["gate_level"] == GATE_SUPPRESS
    assert "unknown_starter_status" in packet["tags"]
    assert "unknown_pitcher_starter_status" in packet["gate_reasons"]


def test_power_prop_in_hostile_environment_is_caution_not_probability_change():
    packet = build_context_packet(
        _leg(
            market="home_runs",
            market_group="hitter",
            side="over",
            batting_order_slot=3,
            lineup_probability=1.0,
            lineup_confirmed=True,
            feature_context_joined=True,
            matchup_context_available=True,
            weather_context_available=True,
            environment_score=-0.15,
            model_probability=0.18,
        )
    )

    assert packet["gate_level"] == GATE_CAUTION
    assert packet["model_probability"] == 0.18
    assert "hostile_power_environment" in packet["tags"]
    assert "high_variance_prop" in packet["tags"]


def test_baseball_context_artifact_writer_emits_gate_report(tmp_path):
    run_dir = tmp_path / "data" / "mlb" / "live_runs" / "live_test"
    run_dir.mkdir(parents=True)
    rows = [
        _leg(
            source_projection_id="ok_hitter",
            market="hits",
            market_group="hitter",
            batting_order_slot=1,
            lineup_probability=1.0,
            lineup_confirmed=True,
            feature_context_joined=True,
            matchup_context_available=True,
        ),
        _leg(
            source_projection_id="bad_pitcher",
            market="pitching_outs",
            market_group="pitcher",
            probable_pitcher_context_available=False,
            feature_context_joined=True,
            matchup_context_available=True,
        ),
    ]
    (run_dir / "scored_legs.json").write_text(json.dumps({"run_id": "live_test", "scored_legs": rows}), encoding="utf-8")

    manifest = write_baseball_context_artifacts(run_dir=run_dir, run_id="live_test", mirror_latest=False)

    assert manifest["row_count"] == 2
    assert manifest["summary"]["ok_count"] == 1
    assert manifest["summary"]["suppressed_count"] == 1
    assert (run_dir / "mlb_scored_legs_context.csv").exists()
    assert (run_dir / "mlb_publication_gate_report.json").exists()
    assert (run_dir / "mlb_pick_context_packets.json").exists()


def _leg(**overrides):
    row = {
        "source_projection_id": "proj_1",
        "player_name": "Sample Player",
        "player_id": "1",
        "player_team": "NYY",
        "opponent": "BOS",
        "event_id": "event_1",
        "game_date": "2026-05-22",
        "start_time_utc": "2026-05-22T23:00:00Z",
        "market": "hits",
        "source_market": "Hits",
        "market_group": "hitter",
        "side": "over",
        "line": 0.5,
        "tier": "STANDARD",
        "model_probability": 0.6,
        "p_cal": 0.6,
        "lineup_context_available": True,
        "lineup_confirmed": True,
        "lineup_probability": 1.0,
        "batting_order_slot": 1,
        "probable_pitcher_context_available": True,
        "weather_context_available": True,
        "park_factor_confidence": 0.8,
        "matchup_context_available": True,
        "feature_context_joined": True,
        "external_market_context_available": True,
        "prizepicks_line_only_market_context": False,
        "environment_score": 0.0,
        "flags": [],
    }
    row.update(overrides)
    return row

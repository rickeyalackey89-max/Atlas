from mlb.contracts.engine import EngineBoardRow
from mlb.modeling.opportunity import estimate_opportunity


def test_batter_opportunity_uses_plate_appearance_proxy():
    row = EngineBoardRow.from_mapping(_row(market="hits", line=0.5, position="OF"), run_id="run")

    opportunity = estimate_opportunity(row)

    assert opportunity.market_group == "batter"
    assert opportunity.opportunity_type == "plate_appearances_proxy"
    assert opportunity.projected_opportunity > 0
    assert opportunity.opportunity_model_version == "baseline_opportunity_v0"


def test_pitcher_outs_market_uses_line_as_opportunity():
    row = EngineBoardRow.from_mapping(_row(market="pitching_outs", line=17.5, position="P"), run_id="run")

    opportunity = estimate_opportunity(row)

    assert opportunity.market_group == "pitcher"
    assert opportunity.opportunity_type == "pitching_outs"
    assert opportunity.projected_opportunity == 17.5
    assert opportunity.opportunity_floor < opportunity.projected_opportunity < opportunity.opportunity_ceiling


def test_uncertain_status_reduces_confidence_and_adds_flag():
    active = estimate_opportunity(EngineBoardRow.from_mapping(_row(status="pre_game"), run_id="run"))
    questionable = estimate_opportunity(EngineBoardRow.from_mapping(_row(status="questionable"), run_id="run"))

    assert questionable.opportunity_confidence < active.opportunity_confidence
    assert questionable.opportunity_fragility_score > active.opportunity_fragility_score
    assert "status_questionable" in questionable.flags


def _row(*, market: str = "hits", line: float = 0.5, position: str = "IF", status: str = "pre_game") -> dict:
    return {
        "snapshot_id": "snap",
        "source_projection_id": "proj",
        "event_id": "game",
        "league": "MLB",
        "game_date": "2026-05-11",
        "start_time_utc": "2026-05-11T23:10:00Z",
        "player_id": "player",
        "player_name": "Sample Player",
        "player_team": "BOS",
        "opponent": "NYY",
        "market": market,
        "source_market": market,
        "line": line,
        "tier": "STANDARD",
        "status": status,
        "player_position": position,
    }

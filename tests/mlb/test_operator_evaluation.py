from mlb.evaluation.anomaly_checks import run_deterministic_anomaly_checks
from mlb.evaluation.artifacts import write_operator_artifacts
from mlb.evaluation.openai_evaluator import build_openai_review_packet, evaluate_with_openai
from mlb.evaluation.operator_report import build_operator_report
from mlb.evaluation.publish_decision import build_publish_decision
from mlb.evaluation.schemas import OPENAI_EVALUATOR_RESPONSE_FORMAT
from mlb.runtime.inspection import run_inspection_command


def test_deterministic_checks_block_empty_live_board():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 0,
    }
    anomalies = run_deterministic_anomaly_checks(packet)
    decision = build_publish_decision(packet, anomalies)
    assert decision.publish_allowed is False
    assert decision.severity == "hard_stop"
    assert anomalies[0].type == "empty_board"


def test_ai_cannot_override_deterministic_hard_stop():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 0,
        "ai_status": "completed",
        "ai_model": "test-model",
    }
    anomalies = run_deterministic_anomaly_checks(packet)
    ai_decision = {
        "publish_allowed": True,
        "severity": "info",
        "summary": "Looks fine.",
        "anomalies": [],
        "operator_notes": [],
        "recommended_next_actions": [],
    }
    decision = build_publish_decision(packet, anomalies, ai_decision=ai_decision)
    assert decision.publish_allowed is False
    assert decision.recommended_next_actions[0] == "Resolve deterministic hard-stop anomalies before publishing."


def test_replay_runs_cannot_publish_even_without_anomalies():
    packet = {
        "run_id": "test_replay",
        "run_mode": "replay_single",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
    }

    decision = build_publish_decision(packet, run_deterministic_anomaly_checks(packet))

    assert decision.publish_allowed is False
    assert "replay runs are isolated" in decision.summary


def test_deterministic_checks_warn_on_live_pitcher_neutral_matrix():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
        "pitcher_prop_count": 12,
        "pitcher_prop_matchup_neutral_count": 12,
        "matchup_context_available_by_market_group": {"batter": 0.80, "pitcher": 0.0},
    }

    anomalies = run_deterministic_anomaly_checks(packet)

    assert any(anomaly.type == "pitcher_prop_matchup_neutral" for anomaly in anomalies)


def test_deterministic_checks_allow_tiny_pitcher_neutral_residual():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
        "pitcher_prop_count": 336,
        "pitcher_prop_matchup_neutral_count": 4,
        "matchup_context_available_by_market_group": {"batter": 0.80, "pitcher": 0.98},
    }

    anomalies = run_deterministic_anomaly_checks(packet)

    assert not any(anomaly.type == "pitcher_prop_matchup_neutral" for anomaly in anomalies)


def test_deterministic_checks_allow_readiness_gate_rounding_tolerance():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
        "source_completeness": {"external_market_context_available": 0.7491},
        "readiness_gates": {"market_context_min_coverage": 0.75},
    }

    anomalies = run_deterministic_anomaly_checks(packet)

    assert not any(anomaly.type == "market_context_below_gate" for anomaly in anomalies)


def test_deterministic_checks_block_true_readiness_gate_failure():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
        "source_completeness": {"external_market_context_available": 0.70},
        "readiness_gates": {"market_context_min_coverage": 0.75},
    }

    anomalies = run_deterministic_anomaly_checks(packet)

    assert any(anomaly.type == "market_context_below_gate" for anomaly in anomalies)


def test_deterministic_checks_block_low_live_batter_matchup_context():
    packet = {
        "run_id": "test_live",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
        "matchup_context_available_by_market_group": {"batter": 0.20},
    }

    anomalies = run_deterministic_anomaly_checks(packet)

    low_context = [anomaly for anomaly in anomalies if anomaly.type == "low_batter_matchup_context"]
    assert low_context
    assert low_context[0].severity == "hard_stop"


def test_openai_review_packet_is_compact_and_schema_backed(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    packet = build_openai_review_packet(
        run_id="run_1",
        run_mode="live",
        run_summary={"board_count": 100, "scored_candidate_count": 95},
        deterministic_anomalies=[],
    )
    result = evaluate_with_openai(packet, model="test-model")
    assert packet["instructions"]["do_not_mutate_model_outputs"] is True
    assert result["ai_status"] == "skipped"
    assert OPENAI_EVALUATOR_RESPONSE_FORMAT["type"] == "json_schema"


def test_operator_report_and_inspection_surface():
    packet = {
        "run_id": "run_1",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
    }
    decision = build_publish_decision(packet, run_deterministic_anomaly_checks(packet))
    report = build_operator_report(packet, decision)
    inspection = run_inspection_command("operator")
    assert "Atlas MLB Operator Report" in report
    assert "run_openai_operator_evaluation" in inspection.payload["stages"]


def test_operator_artifact_writer(tmp_path):
    packet = {
        "run_id": "run_1",
        "run_mode": "live",
        "board_count": 100,
        "scored_candidate_count": 100,
        "slip_count": 3,
    }
    anomalies = run_deterministic_anomaly_checks(packet)
    decision = build_publish_decision(packet, anomalies)
    paths = write_operator_artifacts(tmp_path, run_packet=packet, anomalies=anomalies, decision=decision)
    assert paths["ai_evaluation"].exists()
    assert paths["anomalies"].exists()
    assert paths["operator_report"].read_text(encoding="utf-8").startswith("# Atlas MLB Operator Report")
    assert '"publish_allowed": true' in paths["publish_decision"].read_text(encoding="utf-8")

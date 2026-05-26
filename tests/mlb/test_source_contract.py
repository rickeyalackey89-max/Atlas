import json

import pytest

from mlb.runtime.source_contract import (
    enforce_corpus_source_contracts,
    enforce_replay_source_contract,
    replay_single_preflight_warnings,
)


def test_corpus_source_contract_guard_rejects_failed_member(tmp_path):
    corpus_dir = tmp_path / "data" / "mlb" / "eval" / "corpus"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "replay_single_20260519_bad.run.json").write_text(
        json.dumps(
            {
                "run_id": "replay_single_20260519_bad",
                "source_selection": {
                    "run_id": "replay_single_20260519_bad",
                    "run_mode": "replay_single",
                    "contract_status": "fail",
                    "warnings": [
                        {
                            "code": "zero_context_completeness",
                            "severity": "failure",
                            "source": "external_market_context_available",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="strict replay fidelity source contract"):
        enforce_corpus_source_contracts(corpus_dir, root=tmp_path)


def test_corpus_source_contract_guard_allows_passed_member(tmp_path):
    corpus_dir = tmp_path / "data" / "mlb" / "eval" / "corpus"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "replay_single_20260519_good.run.json").write_text(
        json.dumps(
            {
                "run_id": "replay_single_20260519_good",
                "source_selection": {
                    "run_id": "replay_single_20260519_good",
                    "run_mode": "replay_single",
                    "contract_status": "pass",
                    "warnings": [],
                    "source_completeness": {
                        "external_market_context_available": 1.0,
                        "prizepicks_line_only_market_context": 0.0,
                        "lineup_context_available": 1.0,
                        "probable_pitcher_context_available": 1.0,
                        "weather_context_available": 1.0,
                        "roster_context_available": 1.0,
                        "player_history_context_available": 1.0,
                        "advanced_context_available": 1.0,
                        "statsapi_context_available": 1.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    enforce_corpus_source_contracts(corpus_dir, root=tmp_path)


def test_single_replay_preflight_rejects_thin_context():
    manifest = {
        "run_id": "replay_single_20260523_bad_context",
        "run_mode": "replay_single",
        "contract_status": "pass",
        "warnings": [],
        "source_completeness": {
            "external_market_context_available": 0.560295,
            "prizepicks_line_only_market_context": 0.439705,
            "lineup_context_available": 0.149497,
            "probable_pitcher_context_available": 0.20632,
            "weather_context_available": 0.20632,
            "roster_context_available": 1.0,
            "player_history_context_available": 1.0,
            "advanced_context_available": 1.0,
            "statsapi_context_available": 1.0,
        },
    }

    failures = replay_single_preflight_warnings(manifest)

    assert {failure["source"] for failure in failures} >= {
        "external_market_context_available",
        "lineup_context_available",
        "probable_pitcher_context_available",
        "weather_context_available",
        "prizepicks_line_only_market_context",
    }
    with pytest.raises(RuntimeError, match="single_replay_preflight_context_below_minimum"):
        enforce_replay_source_contract(manifest, context="unit")


def test_single_replay_preflight_allows_ready_context():
    manifest = {
        "run_id": "replay_single_20260520_ready_context",
        "run_mode": "replay_single",
        "contract_status": "pass",
        "warnings": [],
        "source_completeness": {
            "external_market_context_available": 0.845157,
            "prizepicks_line_only_market_context": 0.154843,
            "lineup_context_available": 0.744439,
            "probable_pitcher_context_available": 0.998424,
            "weather_context_available": 0.998424,
            "roster_context_available": 0.99,
            "player_history_context_available": 0.99,
            "advanced_context_available": 0.99,
            "statsapi_context_available": 0.99,
        },
    }

    assert replay_single_preflight_warnings(manifest) == []
    enforce_replay_source_contract(manifest, context="unit")

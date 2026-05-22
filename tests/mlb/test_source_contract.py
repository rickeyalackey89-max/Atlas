import json

import pytest

from mlb.runtime.source_contract import enforce_corpus_source_contracts


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
                },
            }
        ),
        encoding="utf-8",
    )

    enforce_corpus_source_contracts(corpus_dir, root=tmp_path)

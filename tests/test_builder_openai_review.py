from __future__ import annotations

import json

import pandas as pd

from Atlas.core.builder_openai_review import build_builder_candidate_manifest, write_builder_openai_review


def test_builder_manifest_reads_published_slips(tmp_path) -> None:
    run_dir = tmp_path / "data" / "output" / "runs" / "20260515_120000"
    (run_dir / "System").mkdir(parents=True)
    (run_dir / "Windfall").mkdir()

    pd.DataFrame(
        [
            {
                "player": "A",
                "team": "CLE",
                "game_id": "CLE-DET",
                "direction": "OVER",
                "tier": "STANDARD",
                "stat": "PTS",
                "is_questionable": 0,
            }
        ]
    ).to_csv(run_dir / "scored_legs_deduped.csv", index=False)
    pd.DataFrame(
        [
            {
                "n_legs": 4,
                "legs": "A OVER PTS 10.5 (STANDARD) | B OVER REB 5.5 (STANDARD) | C UNDER AST 4.5 (STANDARD) | D OVER PR 12.5 (STANDARD)",
                "hit_prob": 0.42,
                "ev_mult": 1.25,
                "payout_mult_eff": 3.0,
                "public_survival_score": 0.66,
            }
        ]
    ).to_csv(run_dir / "System" / "recommended_4leg.csv", index=False)
    pd.DataFrame(
        [
            {
                "slip": "3-leg",
                "hit_prob": 0.6,
                "payout_mult": 2.0,
                "ev": 1.2,
                "player": "A",
                "team": "CLE",
                "opp": "DET",
                "stat": "PTS",
                "direction": "OVER",
                "tier": "STANDARD",
                "line": 10.5,
                "p_cal": 0.75,
                "is_questionable": 0,
                "public_survival_score": 0.7,
            },
            {
                "slip": "3-leg",
                "hit_prob": 0.6,
                "payout_mult": 2.0,
                "ev": 1.2,
                "player": "B",
                "team": "DET",
                "opp": "CLE",
                "stat": "REB",
                "direction": "OVER",
                "tier": "STANDARD",
                "line": 5.5,
                "p_cal": 0.72,
                "is_questionable": 0,
                "public_survival_score": 0.7,
            },
        ]
    ).to_csv(run_dir / "marketed_slips.csv", index=False)
    (run_dir / "public_slip_quality_manifest.json").write_text(
        json.dumps({"enabled": True, "priority": ["Marketed", "System", "Windfall"], "kept_counts": {"Marketed": 1}, "drops": []}),
        encoding="utf-8",
    )

    manifest = build_builder_candidate_manifest(run_dir, {"public_slip_quality": {}})

    assert manifest["selected_counts"] == {"Marketed": 1, "System": 1}
    assert manifest["slate"]["games"] == 1
    assert manifest["selected_slips"][0]["family"] == "Marketed"
    assert manifest["selected_slips"][0]["n_legs"] == 2


def test_openai_review_skips_without_key(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "data" / "output" / "runs" / "20260515_120000"
    run_dir.mkdir(parents=True)
    pd.DataFrame([{"player": "A", "game_id": "1", "stat": "PTS", "direction": "OVER", "tier": "STANDARD"}]).to_csv(
        run_dir / "scored_legs_deduped.csv",
        index=False,
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ATLAS_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ATLAS_OPENAI_API_KEY_PATH", raising=False)

    paths = write_builder_openai_review(
        run_dir,
        {
            "builder_openai_review": {
                "enabled": True,
                "call_openai": True,
                "key_path": "missing.txt",
            },
            "public_slip_quality": {},
        },
    )

    review = json.loads(paths["openai_review"].read_text(encoding="utf-8"))
    assert review["status"] == "skipped"
    assert review["reason"] == "missing_api_key"
    assert paths["candidate_manifest"].exists()

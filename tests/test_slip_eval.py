from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Atlas.runtime.slip_eval import write_eval_slips_for_run  # noqa: E402


def test_write_eval_slips_scores_recommended_and_marketed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    system_dir = run_dir / "System"
    system_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "source_projection_id": "1",
                "projection_id": "1|Player A|PTS|GOBLIN|10.5|OVER",
                "player": "Player A",
                "stat": "PTS",
                "direction": "OVER",
                "tier": "GOBLIN",
                "line": 10.5,
                "actual": 12,
                "hit": 1,
            },
            {
                "source_projection_id": "2",
                "projection_id": "2|Player B|REB|STANDARD|5.5|OVER",
                "player": "Player B",
                "stat": "REB",
                "direction": "OVER",
                "tier": "STANDARD",
                "line": 5.5,
                "actual": 7,
                "hit": 1,
            },
            {
                "source_projection_id": "3",
                "projection_id": "3|Player C|AST|STANDARD|4.5|OVER",
                "player": "Player C",
                "stat": "AST",
                "direction": "OVER",
                "tier": "STANDARD",
                "line": 4.5,
                "actual": 3,
                "hit": 0,
            },
        ]
    ).to_csv(run_dir / "eval_legs.csv", index=False)

    pd.DataFrame(
        [
            {
                "n_legs": 2,
                "legs": "Player A OVER PTS 10.5 (GOBLIN) [id:1] | Player B OVER REB 5.5 (STANDARD) [id:2]",
                "hit_prob": 0.72,
                "payout_mult": 3.0,
                "ev_mult": 2.16,
            }
        ]
    ).to_csv(system_dir / "recommended_2leg.csv", index=False)

    pd.DataFrame(
        [
            {
                "slip": "2-leg",
                "hit_prob": 0.50,
                "payout_mult": 3.0,
                "ev": 1.5,
                "player": "Player A",
                "stat": "PTS",
                "direction": "OVER",
                "tier": "GOBLIN",
                "line": 10.5,
            },
            {
                "slip": "2-leg",
                "hit_prob": 0.50,
                "payout_mult": 3.0,
                "ev": 1.5,
                "player": "Player C",
                "stat": "AST",
                "direction": "OVER",
                "tier": "STANDARD",
                "line": 4.5,
            },
        ]
    ).to_csv(run_dir / "marketed_slips.csv", index=False)

    csv_path, json_path = write_eval_slips_for_run(run_dir)

    out = pd.read_csv(csv_path)
    assert out["status"].tolist() == ["win", "loss"]
    assert out["family"].tolist() == ["System", "Marketed"]

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["wins"] == 1
    assert payload["summary"]["losses"] == 1
    assert payload["winners"][0]["family"] == "System"
    assert payload["winners"][0]["hit_count"] == 2


def test_write_eval_slips_matches_duplicate_source_ids_by_direction(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    system_dir = run_dir / "System"
    system_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "source_projection_id": "42",
                "projection_id": "42|Player A|PTS|STANDARD|10.5|OVER",
                "player": "Player A",
                "stat": "PTS",
                "direction": "OVER",
                "tier": "STANDARD",
                "line": 10.5,
                "actual": 8,
                "hit": 0,
            },
            {
                "source_projection_id": "42",
                "projection_id": "42|Player A|PTS|STANDARD|10.5|UNDER",
                "player": "Player A",
                "stat": "PTS",
                "direction": "UNDER",
                "tier": "STANDARD",
                "line": 10.5,
                "actual": 8,
                "hit": 1,
            },
        ]
    ).to_csv(run_dir / "eval_legs.csv", index=False)

    pd.DataFrame(
        [
            {
                "n_legs": 1,
                "legs": "Player A OVER PTS 10.5 (STANDARD) [id:42]",
                "hit_prob": 0.51,
                "payout_mult": 1.0,
                "ev_mult": 0.51,
            }
        ]
    ).to_csv(system_dir / "recommended_1leg.csv", index=False)

    csv_path, _ = write_eval_slips_for_run(run_dir)
    out = pd.read_csv(csv_path)

    assert out.loc[0, "status"] == "loss"
    assert out.loc[0, "hit_count"] == 0

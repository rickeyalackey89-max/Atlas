import csv
import json
from pathlib import Path

from mlb.runtime.runtime_state import publish_run_runtime_state


def test_publish_run_runtime_state_keeps_market_and_source_running_files(tmp_path):
    run_dir = tmp_path / "data" / "mlb" / "test_runs" / "state_run"
    market_dir = tmp_path / "data" / "mlb" / "features" / "market_context" / "state_run"
    run_dir.mkdir(parents=True)
    market_dir.mkdir(parents=True)

    market_csv = market_dir / "market_context.csv"
    _write_csv(
        market_csv,
        [
            {
                "run_id": "state_run",
                "source_projection_id": "p1",
                "event_id": "g1",
                "player_name": "Sample Hitter",
                "market": "hits",
                "line": "0.5",
                "tier": "STANDARD",
                "market_context_available": "True",
            }
        ],
    )
    source_manifest = run_dir / "source_selection_manifest.json"
    source_manifest.write_text(
        json.dumps(
            {
                "run_id": "state_run",
                "run_mode": "live",
                "game_date": "2026-05-20",
                "contract_status": "pass",
                "warning_count": 0,
                "market_sources": {},
                "context_sources": {},
                "source_completeness": {"market_context_available": 1.0},
            }
        ),
        encoding="utf-8",
    )
    run_manifest = {
        "run_id": "state_run",
        "run_mode": "live",
        "game_date_filter": "2026-05-20",
        "score": {"row_count": 1},
        "slips": {"slip_count": 1},
        "features": {"source_completeness": {"market_context_available": 1.0}},
        "source_selection": {"manifest_path": str(source_manifest)},
        "market_context": {"csv_path": str(market_csv)},
        "operator": {"publish_allowed": True, "severity": "pass"},
        "manifest_path": str(run_dir / "run_manifest.json"),
    }

    first = publish_run_runtime_state(run_manifest=run_manifest, root=tmp_path)
    second = publish_run_runtime_state(run_manifest=run_manifest, root=tmp_path)

    market_running = tmp_path / "data" / "mlb" / "runtime_state" / "market_priors" / "market_priors_running.csv"
    source_running = (
        tmp_path / "data" / "mlb" / "runtime_state" / "source_manifests" / "source_manifests_running.jsonl"
    )
    assert Path(first["manifest_path"]).exists()
    assert Path(second["manifest_path"]).exists()
    assert len(_read_csv(market_running)) == 1
    assert len(source_running.read_text(encoding="utf-8").splitlines()) == 1


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

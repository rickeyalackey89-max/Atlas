from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_6am_eval_backfill import backfill_eval_legs, discover_run_dirs  # noqa: E402


def test_discover_run_dirs_finds_output_and_telemetry_prefixes(tmp_path):
    atlas_root = tmp_path
    output_run = atlas_root / "data" / "output" / "runs" / "20260511_173253"
    telemetry_run = atlas_root / "data" / "telemetry" / "live_runs" / "20260511_530pm"
    old_run = atlas_root / "data" / "output" / "runs" / "20260510_173253"
    for path in (output_run, telemetry_run, old_run):
        path.mkdir(parents=True)

    discovered = discover_run_dirs(atlas_root=atlas_root, game_date=date(2026, 5, 11))

    assert [(root_name, path.name) for root_name, path in discovered] == [
        ("output_runs", "20260511_173253"),
        ("telemetry_live_runs", "20260511_530pm"),
    ]


def test_backfill_eval_legs_skips_existing_eval_file(tmp_path):
    atlas_root = tmp_path
    run_dir = atlas_root / "data" / "output" / "runs" / "20260511_173253"
    run_dir.mkdir(parents=True)
    (run_dir / "scored_legs_deduped.csv").write_text("game_date,player\n2026-05-11,Sample Player\n", encoding="utf-8")
    (run_dir / "eval_legs.csv").write_text("game_date,player,hit\n2026-05-11,Sample Player,1\n", encoding="utf-8")
    gamelogs = atlas_root / "data" / "gamelogs" / "nba_gamelogs.csv"
    gamelogs.parent.mkdir(parents=True)
    gamelogs.write_text(
        "game_date,player,team,opp,pts,reb,ast\n2026-05-11,Sample Player,BOS,NYK,10,5,4\n",
        encoding="utf-8",
    )

    payload = backfill_eval_legs(atlas_root=atlas_root, game_date=date(2026, 5, 11), gamelogs_path=gamelogs)

    assert payload["discovered_count"] == 1
    assert payload["written_count"] == 0
    assert payload["skipped_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["items"][0]["reason"] == "eval_exists"

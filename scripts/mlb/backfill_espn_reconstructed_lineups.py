"""Stage ESPN historical starters as reconstructed pregame lineup context.

This is a fallback for replay dates where Baseball Reference starting-lineup
pages are unavailable or rate limited. It carries only identity/order/starter
fields from ESPN boxscore context and labels the output as reconstructed
starting-lineup context so replay manifests can distinguish it from live
snapshots and postgame stats.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CONTEXT_TIMING = "historical_pregame_lineup_backfill"
LINEUP_CONTENT_TIMING = "pregame_starting_lineup"
SOURCE = "espn_game_context"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-prefix", default="espn_reconstructed_lineups")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    staged_root = root / "data" / "mlb" / "staged" / "espn_game_context"
    output_rows = []
    for game_date in _date_range(date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)):
        manifest_path = _latest_source_manifest(staged_root, game_date.isoformat())
        if manifest_path is None:
            output_rows.append({"game_date": game_date.isoformat(), "status": "missing_espn_source"})
            continue
        output_rows.append(
            _write_reconstructed_date(
                staged_root=staged_root,
                source_manifest_path=manifest_path,
                game_date=game_date.isoformat(),
                run_prefix=args.run_prefix,
            )
        )

    payload = {
        "source": SOURCE,
        "context_timing": CONTEXT_TIMING,
        "lineup_content_timing": LINEUP_CONTENT_TIMING,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "date_count": len(output_rows),
        "successful_date_count": sum(1 for row in output_rows if row.get("status") == "ok"),
        "rows": output_rows,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for row in output_rows:
            print(
                f"{row['game_date']}: {row.get('status')} "
                f"batting={row.get('batting_orders', 0)} pitchers={row.get('pitchers', 0)}"
            )
    return 0


def _latest_source_manifest(staged_root: Path, game_date: str) -> Path | None:
    candidates = []
    for manifest_path in staged_root.glob("*/normalize_manifest.json"):
        manifest = _load_json(manifest_path)
        if str(manifest.get("game_date") or "") != game_date:
            continue
        if manifest.get("context_timing") == CONTEXT_TIMING:
            continue
        counts = manifest.get("row_counts") if isinstance(manifest.get("row_counts"), dict) else {}
        if int(counts.get("batting_orders") or 0) <= 0 and int(counts.get("pitchers") or 0) <= 0:
            continue
        candidates.append(manifest_path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, path.parent.name))[-1]


def _write_reconstructed_date(
    *,
    staged_root: Path,
    source_manifest_path: Path,
    game_date: str,
    run_prefix: str,
) -> dict[str, Any]:
    source_dir = source_manifest_path.parent
    source_manifest = _load_json(source_manifest_path)
    run_id = f"{run_prefix}_{game_date.replace('-', '')}_v1"
    output_dir = staged_root / run_id
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    batting_orders = [_replay_lineup_row(row, source_manifest=source_manifest) for row in _load_jsonl(source_dir / "batting_orders.jsonl")]
    pitchers = [_replay_pitcher_row(row, source_manifest=source_manifest) for row in _load_jsonl(source_dir / "pitchers.jsonl")]
    batting_orders = [row for row in batting_orders if row]
    pitchers = [row for row in pitchers if row]

    artifacts = {
        "raw_events": _write_jsonl(output_dir / "raw_events.jsonl", []),
        "daily_lineups": _write_jsonl(output_dir / "daily_lineups.jsonl", batting_orders),
        "batting_orders": _write_jsonl(output_dir / "batting_orders.jsonl", batting_orders),
        "pitchers": _write_jsonl(output_dir / "pitchers.jsonl", pitchers),
        "bullpens": _write_jsonl(output_dir / "bullpens.jsonl", []),
        "hitter_context": _write_jsonl(output_dir / "hitter_context.jsonl", []),
        "environment": _write_jsonl(output_dir / "environment.jsonl", []),
    }
    out = {
        "run_id": run_id,
        "snapshot_id": run_id,
        "source": SOURCE,
        "context_timing": CONTEXT_TIMING,
        "lineup_content_timing": LINEUP_CONTENT_TIMING,
        "historical_reconstructed_lineup_context": True,
        "game_date": game_date,
        "output_dir": str(output_dir),
        "source_manifest_path": str(source_manifest_path),
        "source_run_id": str(source_manifest.get("run_id") or source_dir.name),
        "row_counts": {
            "raw_events": 0,
            "daily_lineups": len(batting_orders),
            "batting_orders": len(batting_orders),
            "pitchers": len(pitchers),
            "bullpens": 0,
            "hitter_context": 0,
            "environment": 0,
        },
        "artifacts": artifacts,
        "parser_status": {
            "batting_orders": "reconstructed_from_espn_boxscore_starters" if batting_orders else "empty",
            "pitchers": "reconstructed_from_espn_boxscore_starters" if pitchers else "empty",
        },
        "parse_warnings": [],
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "game_date": game_date,
        "status": "ok",
        "run_id": run_id,
        "source_run_id": out["source_run_id"],
        "batting_orders": len(batting_orders),
        "pitchers": len(pitchers),
    }


def _replay_lineup_row(row: dict[str, Any], *, source_manifest: dict[str, Any]) -> dict[str, Any]:
    player_name = _str(row.get("player_name") or row.get("display_name"))
    team = _str(row.get("team_abbr"))
    opponent = _str(row.get("opponent_abbr"))
    game_date = _str(row.get("game_date"))
    if not (player_name and team and opponent and game_date):
        return {}
    return {
        **_base_replay_fields(row, source_manifest=source_manifest),
        "player_name": player_name,
        "display_name": _str(row.get("display_name")) or player_name,
        "batting_order": _int(row.get("batting_order")),
        "position": _str(row.get("position")),
        "bats": "",
        "opposing_pitcher": "",
        "opposing_pitcher_throws": "",
        "lineup_status": "Confirmed Starting Lineup",
        "lineup_status_key": "confirmed_starting_lineup",
        "flags": ["espn_historical_starting_lineup_backfill"],
    }


def _replay_pitcher_row(row: dict[str, Any], *, source_manifest: dict[str, Any]) -> dict[str, Any]:
    pitcher_name = _str(row.get("pitcher_name") or row.get("player_name"))
    team = _str(row.get("team_abbr"))
    opponent = _str(row.get("opponent_abbr"))
    game_date = _str(row.get("game_date"))
    if not (pitcher_name and team and opponent and game_date):
        return {}
    return {
        **_base_replay_fields(row, source_manifest=source_manifest),
        "pitcher_name": pitcher_name,
        "throws": _str(row.get("throws")),
        "pitcher_stats": "",
        "is_probable_starter": True,
        "lineup_status": "Confirmed Starting Pitcher",
        "lineup_status_key": "confirmed_starting_pitcher",
        "flags": ["espn_historical_starting_pitcher_backfill"],
    }


def _base_replay_fields(row: dict[str, Any], *, source_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "snapshot_id": str(source_manifest.get("run_id") or source_manifest.get("snapshot_id") or ""),
        "reconstructed_snapshot_id": str(source_manifest.get("run_id") or ""),
        "context_timing": CONTEXT_TIMING,
        "lineup_content_timing": LINEUP_CONTENT_TIMING,
        "historical_reconstructed_lineup_context": True,
        "game_date": _str(row.get("game_date")),
        "game_id": _str(row.get("game_id") or row.get("event_id")),
        "event_id": _str(row.get("event_id") or row.get("game_id")),
        "team_abbr": _str(row.get("team_abbr")),
        "team_name": _str(row.get("team_name")),
        "opponent_abbr": _str(row.get("opponent_abbr")),
        "opponent_name": _str(row.get("opponent_name")),
        "rotowire_player_id": _str(row.get("rotowire_player_id") or row.get("espn_player_id")),
        "espn_player_id": _str(row.get("espn_player_id") or row.get("rotowire_player_id")),
        "game_time_et": "",
        "game_started": False,
        "raw_game_started": True,
        "slate_status": CONTEXT_TIMING,
        "raw_slate_status": _str(row.get("slate_status")),
    }


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return str(path)


def _str(value: Any) -> str:
    return " ".join(str(value or "").split())


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())

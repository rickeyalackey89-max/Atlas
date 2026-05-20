"""Normalize ESPN MLB athlete game-log payloads into season game-log rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload


def normalize_espn_player_gamelog(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize one ESPN athlete gamelog payload."""

    fetch = payload.get("_atlas_fetch") if isinstance(payload.get("_atlas_fetch"), dict) else {}
    context = fetch.get("player_context") if isinstance(fetch.get("player_context"), dict) else {}
    names = [str(value) for value in payload.get("names", []) if value is not None]
    group = _group_from_names(names)
    season = _int(fetch.get("season") or _selected_filter(payload, "season"))
    espn_player_id = _clean_str(fetch.get("athlete_id") or context.get("espn_player_id"))
    player_name = _clean_str(context.get("player_name"))
    events = payload.get("events") if isinstance(payload.get("events"), dict) else {}

    rows: list[dict[str, Any]] = []
    for season_type in payload.get("seasonTypes", []) or []:
        if not isinstance(season_type, dict):
            continue
        for category in season_type.get("categories", []) or []:
            if not isinstance(category, dict):
                continue
            for item in category.get("events", []) or []:
                if not isinstance(item, dict):
                    continue
                event_id = _clean_str(item.get("eventId"))
                stats = _stats_by_name(names, item.get("stats"))
                event = events.get(event_id) if isinstance(events.get(event_id), dict) else {}
                team = event.get("team") if isinstance(event.get("team"), dict) else {}
                opponent = event.get("opponent") if isinstance(event.get("opponent"), dict) else {}
                team_abbr = canonical_team_abbr(team.get("abbreviation") or context.get("team_abbreviation"))
                opponent_abbr = canonical_team_abbr(opponent.get("abbreviation"))
                game_date = _date_only(event.get("gameDate"))
                stat = _stat_contract(stats, group=group)
                rows.append(
                    {
                        "source": "espn_player_gamelog",
                        "season": season,
                        "group": group,
                        "game_pk": 0,
                        "game_id": event_id,
                        "espn_event_id": event_id,
                        "game_date": game_date,
                        "person_id": 0,
                        "espn_player_id": espn_player_id,
                        "player_name": player_name,
                        "player_team": team_abbr,
                        "player_position": _clean_str(context.get("position")),
                        "team_id": _int(team.get("id")),
                        "team_name": _clean_str(team.get("displayName") or team.get("name")),
                        "team_abbreviation": team_abbr,
                        "opponent_id": _int(opponent.get("id")),
                        "opponent_name": _clean_str(opponent.get("displayName") or opponent.get("name")),
                        "opponent_abbreviation": opponent_abbr,
                        "is_home": _clean_str(event.get("atVs")) != "@",
                        "game_result": _clean_str(event.get("gameResult")),
                        "stat": stat,
                        "batting_stats": stat if group == "hitting" else {},
                        "pitching_stats": stat if group == "pitching" else {},
                        "is_pitching_starter": False,
                        "raw_stats": stats,
                    }
                )
    return [row for row in rows if row["game_date"] and row["group"] in {"hitting", "pitching"}]


def normalize_espn_player_gamelogs_bulk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a combined ESPN player game-log snapshot."""

    rows: list[dict[str, Any]] = []
    for item in payload.get("payloads", []) or []:
        if not isinstance(item, dict) or item.get("error"):
            continue
        gamelog_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if not gamelog_payload:
            continue
        if "_atlas_fetch" not in gamelog_payload:
            gamelog_payload["_atlas_fetch"] = {
                "source": "espn_player_gamelog",
                "athlete_id": _clean_str(item.get("athlete_id")),
                "season": _int(payload.get("season")),
                "player_context": item.get("player_context") if isinstance(item.get("player_context"), dict) else {},
            }
        rows.extend(normalize_espn_player_gamelog(gamelog_payload))
    return rows


def write_espn_gamelogs_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Stage normalized ESPN game-log rows."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    source = _clean_str(payload.get("source") or manifest.get("source") or "espn_player_gamelogs_bulk")
    kind = "espn_player_gamelog" if source == "espn_player_gamelog" else "espn_player_gamelogs_bulk"
    rows = normalize_espn_player_gamelog(payload) if kind == "espn_player_gamelog" else normalize_espn_player_gamelogs_bulk(payload)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or kind)
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / kind / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / f"{kind}.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    out = {
        "run_id": resolved_run_id,
        "snapshot_id": manifest.get("snapshot_id", ""),
        "source": kind,
        "row_count": len(rows),
        "rows_path": str(rows_path),
        "output_dir": str(output_dir),
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def normalize_espn_gamelogs_payload(*, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if kind == "espn_player_gamelog":
        return normalize_espn_player_gamelog(payload)
    if kind == "espn_player_gamelogs_bulk":
        return normalize_espn_player_gamelogs_bulk(payload)
    raise ValueError(f"Unsupported ESPN gamelog kind: {kind}")


def _group_from_names(names: list[str]) -> str:
    lowered = {name.lower() for name in names}
    if "innings" in lowered or "earnedruns" in lowered or "battersfaced" in lowered:
        return "pitching"
    return "hitting"


def _stat_contract(stats: dict[str, str], *, group: str) -> dict[str, Any]:
    if group == "pitching":
        innings = _clean_str(stats.get("innings"))
        outs = _outs_from_innings(innings)
        return {
            "inningsPitched": innings,
            "outs": outs,
            "hits": _int(stats.get("hits")),
            "runs": _int(stats.get("runs")),
            "earnedRuns": _int(stats.get("earnedRuns")),
            "homeRuns": _int(stats.get("homeRuns")),
            "baseOnBalls": _int(stats.get("walks")),
            "strikeOuts": _int(stats.get("strikeouts")),
            "pitchesThrown": _int(stats.get("pitches")),
            "numberOfPitches": _int(stats.get("pitches")),
            "battersFaced": _int(stats.get("battersFaced")),
            "wins": 1 if _clean_str(stats.get("wins-losses")).upper().startswith("W") else 0,
            "losses": 1 if _clean_str(stats.get("wins-losses")).upper().startswith("L") else 0,
        }

    hits = _int(stats.get("hits"))
    doubles = _int(stats.get("doubles"))
    triples = _int(stats.get("triples"))
    home_runs = _int(stats.get("homeRuns"))
    walks = _int(stats.get("walks"))
    hbp = _int(stats.get("hitByPitch"))
    at_bats = _int(stats.get("atBats"))
    return {
        "atBats": at_bats,
        "runs": _int(stats.get("runs")),
        "hits": hits,
        "doubles": doubles,
        "triples": triples,
        "homeRuns": home_runs,
        "rbi": _int(stats.get("RBIs")),
        "baseOnBalls": walks,
        "hitByPitch": hbp,
        "strikeOuts": _int(stats.get("strikeouts")),
        "stolenBases": _int(stats.get("stolenBases")),
        "caughtStealing": _int(stats.get("caughtStealing")),
        "plateAppearances": at_bats + walks + hbp,
        "totalBases": max(0, hits - doubles - triples - home_runs) + doubles * 2 + triples * 3 + home_runs * 4,
    }


def _stats_by_name(names: list[str], stats: Any) -> dict[str, str]:
    if not isinstance(stats, list):
        return {}
    return {name: _clean_str(value) for name, value in zip(names, stats, strict=False)}


def _selected_filter(payload: dict[str, Any], name: str) -> str:
    for item in payload.get("filters", []) or []:
        if isinstance(item, dict) and _clean_str(item.get("name")) == name:
            return _clean_str(item.get("value"))
    return ""


def _outs_from_innings(value: Any) -> int:
    text = _clean_str(value)
    if not text:
        return 0
    if "." not in text:
        return _int(text) * 3
    whole, partial = text.split(".", 1)
    return _int(whole) * 3 + _int(partial[:1])


def _date_only(value: Any) -> str:
    text = _clean_str(value)
    return text[:10] if len(text) >= 10 else ""


def _int(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _clean_str(value: Any) -> str:
    return str(value or "").strip()

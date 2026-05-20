"""Normalize DraftKings Sportsbook MLB milestone props into market context rows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mlb.fetchers.draftkings import DRAFTKINGS_MLB_SPORTSBOOK_SOURCE
from mlb.normalizers.prizepicks import normalize_player_name
from mlb.normalizers.slate_dates import local_slate_date
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload


def normalize_draftkings_sportsbook_props(
    payload: dict[str, Any],
    *,
    snapshot_id: str = "",
    pulled_at_utc: str = "",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for response in payload.get("responses", []) or []:
        if not isinstance(response, dict):
            continue
        market = str(response.get("market") or "")
        subcategory_id = str(response.get("subcategory_id") or "")
        body = response.get("response") if isinstance(response.get("response"), dict) else {}
        events_by_id = {_str_id(event.get("id")): event for event in body.get("events", []) or [] if isinstance(event, dict)}
        markets_by_id = {
            _str_id(item.get("id")): item for item in body.get("markets", []) or [] if isinstance(item, dict)
        }
        for selection in body.get("selections", []) or []:
            if not isinstance(selection, dict):
                continue
            market_id = _str_id(selection.get("marketId"))
            market_payload = markets_by_id.get(market_id, {})
            event = events_by_id.get(_str_id(market_payload.get("eventId")), {})
            player = _selection_player(selection)
            player_name = normalize_player_name(str(player.get("name") or player.get("seoIdentifier") or ""))
            line = _selection_line(selection)
            over_probability = _selection_probability(selection)
            if not player_name or line is None or over_probability is None or not event:
                rejects.append(_reject(snapshot_id, market, selection, "missing_player_line_probability_or_event"))
                continue
            start_time = str(event.get("startEventDate") or "")
            home_team, away_team, player_team, opponent = _team_context(event, player)
            key = (
                event.get("id"),
                market_id,
                selection.get("id"),
                player_name.lower(),
                market,
                line,
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
                    "event_id": f"draftkings_sportsbook_{event.get('id') or ''}",
                    "source_event_id": str(event.get("id") or ""),
                    "sport_key": "baseball_mlb",
                    "league": "MLB",
                    "game_date": local_slate_date(start_time, fallback=start_time[:10]),
                    "commence_time": start_time,
                    "home_team": home_team,
                    "away_team": away_team,
                    "player_id": str(player.get("id") or ""),
                    "player_name": player_name,
                    "player_norm": player_name.lower(),
                    "player_team": player_team,
                    "opponent": opponent,
                    "market": market,
                    "source_market": str(market_payload.get("name") or market),
                    "source_market_id": subcategory_id,
                    "line": line,
                    "over_prob": round(over_probability, 6),
                    "under_prob": round(max(0.0, 1.0 - over_probability), 6),
                    "n_books": 1,
                    "books": [
                        {
                            "book_id": 12,
                            "book_key": "draftkings",
                            "book_title": "DraftKings Sportsbook",
                            "book_last_update": pulled_at_utc,
                            "source_market": str(market_payload.get("name") or market),
                            "over_price": _american_odds(selection),
                            "under_price": 0,
                            "over_prob": round(over_probability, 6),
                            "under_prob": round(max(0.0, 1.0 - over_probability), 6),
                            "line": line,
                            "price_model": "one_sided_milestone",
                        }
                    ],
                    "pulled_at_utc": pulled_at_utc,
                    "snapshot_timestamp": pulled_at_utc,
                    "draftkings_sportsbook": {
                        "selection_id": selection.get("id"),
                        "market_id": market_id,
                        "subcategory_id": subcategory_id,
                        "label": str(selection.get("label") or ""),
                        "milestone_value": selection.get("milestoneValue"),
                        "one_sided_milestone": True,
                    },
                }
            )

    return {
        "snapshot_id": snapshot_id,
        "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
        "row_count": len(rows),
        "rejected_count": len(rejects),
        "rows": sorted(rows, key=lambda row: (row["game_date"], row["player_name"], row["market"], row["line"])),
        "rejects": rejects,
    }


def write_draftkings_sportsbook_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or DRAFTKINGS_MLB_SPORTSBOOK_SOURCE)
    normalized = normalize_draftkings_sportsbook_props(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or ""),
        pulled_at_utc=str(manifest.get("pulled_at_utc") or ""),
    )
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "draftkings_mlb_sportsbook" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "oddsapi_props.jsonl"
    rejects_path = output_dir / "draftkings_sportsbook_rejected.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    _write_jsonl(rows_path, normalized["rows"])
    _write_jsonl(rejects_path, normalized["rejects"])
    written = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
        "row_count": normalized["row_count"],
        "compatible_row_count": normalized["row_count"],
        "rejected_count": normalized["rejected_count"],
        "rows_path": str(rows_path),
        "compatible_rows_path": str(rows_path),
        "rejects_path": str(rejects_path),
        "output_dir": str(output_dir),
        "compatible_artifact": "oddsapi_props.jsonl",
    }
    manifest_path.write_text(json.dumps(written, indent=2, sort_keys=True), encoding="utf-8")
    return written


def _selection_player(selection: dict[str, Any]) -> dict[str, Any]:
    for participant in selection.get("participants", []) or []:
        if isinstance(participant, dict) and str(participant.get("type") or "").lower() == "player":
            return participant
    participants = selection.get("participants") if isinstance(selection.get("participants"), list) else []
    return participants[0] if participants and isinstance(participants[0], dict) else {}


def _selection_line(selection: dict[str, Any]) -> float | None:
    milestone = _to_float(selection.get("milestoneValue"))
    if milestone is not None:
        return max(0.0, milestone - 0.5)
    label = str(selection.get("label") or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*\+", label)
    if match:
        return max(0.0, float(match.group(1)) - 0.5)
    return _to_float(selection.get("line"))


def _selection_probability(selection: dict[str, Any]) -> float | None:
    american = _american_odds(selection)
    if american is not None:
        return _american_to_probability(american)
    true_odds = _to_float(selection.get("trueOdds"))
    if true_odds and true_odds > 1.0:
        return 1.0 / true_odds
    return None


def _american_odds(selection: dict[str, Any]) -> int | None:
    display = selection.get("displayOdds") if isinstance(selection.get("displayOdds"), dict) else {}
    value = str(display.get("american") or "").replace("\u2212", "-").replace("+", "").strip()
    try:
        return int(value)
    except ValueError:
        return None


def _american_to_probability(value: int) -> float:
    if value < 0:
        return abs(value) / (abs(value) + 100.0)
    return 100.0 / (value + 100.0)


def _team_context(event: dict[str, Any], player: dict[str, Any]) -> tuple[str, str, str, str]:
    home = ""
    away = ""
    for participant in event.get("participants", []) or []:
        if not isinstance(participant, dict):
            continue
        role = str(participant.get("venueRole") or "").lower()
        if role == "home":
            home = _team_label(participant)
        elif role == "away":
            away = _team_label(participant)
    player_role = str(player.get("venueRole") or "").lower()
    if player_role.startswith("home"):
        return home, away, home, away
    if player_role.startswith("away"):
        return home, away, away, home
    return home, away, "", ""


def _team_label(participant: dict[str, Any]) -> str:
    metadata = participant.get("metadata") if isinstance(participant.get("metadata"), dict) else {}
    return str(metadata.get("shortName") or participant.get("name") or "")


def _reject(snapshot_id: str, market: str, selection: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "market": market,
        "selection_id": selection.get("id"),
        "market_id": selection.get("marketId"),
        "label": selection.get("label"),
        "reason": reason,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _str_id(value: Any) -> str:
    return str(value or "")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

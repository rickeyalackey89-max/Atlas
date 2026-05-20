"""Normalize ParlayAPI MLB historical closing-prop rows."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from mlb.fetchers.historical_backfill.parlayapi import (
    PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE,
    PARLAYAPI_MLB_MARKET_ALIASES,
)
from mlb.normalizers.oddsapi import devig_over_under
from mlb.normalizers.prizepicks import normalize_player_name
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload


def normalize_parlayapi_mlb_closing_props(
    payload: dict[str, Any],
    *,
    snapshot_id: str = "",
    source: str = PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE,
    pulled_at_utc: str = "",
) -> dict[str, Any]:
    fetch = payload.get("_atlas_fetch") or {}
    grouped: dict[tuple[str, str, str, float], list[dict[str, Any]]] = {}
    rejects: list[dict[str, Any]] = []

    for response_entry in payload.get("responses", []) or []:
        response_payload = ((response_entry.get("response") or {}).get("payload")) or []
        rows = _rows_from_payload(response_payload)
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            source_market = str(raw_row.get("market_key") or response_entry.get("market") or "")
            market = PARLAYAPI_MLB_MARKET_ALIASES.get(source_market)
            if not market:
                rejects.append(_reject(snapshot_id, source, raw_row, "unsupported_market"))
                continue

            player_name = normalize_player_name(str(raw_row.get("player") or ""))
            if not _valid_player_name(player_name):
                rejects.append(_reject(snapshot_id, source, raw_row, "invalid_player"))
                continue

            line = _to_float(raw_row.get("line"))
            over_price = _to_float(raw_row.get("over_odds"))
            under_price = _to_float(raw_row.get("under_odds"))
            if line is None or over_price is None or under_price is None:
                rejects.append(_reject(snapshot_id, source, raw_row, "missing_line_or_price"))
                continue

            game_date = str(raw_row.get("game_date") or "")[:10]
            home_team = str(raw_row.get("home_team") or "")
            away_team = str(raw_row.get("away_team") or "")
            if not game_date or not home_team or not away_team:
                rejects.append(_reject(snapshot_id, source, raw_row, "missing_game_context"))
                continue

            over_prob, under_prob = devig_over_under(over_price, under_price)
            event_id = _event_id(game_date=game_date, home_team=home_team, away_team=away_team)
            key = (event_id, normalize_player_name(player_name), market, float(line))
            grouped.setdefault(key, []).append(
                {
                    "event_id": event_id,
                    "sport_key": str(raw_row.get("sport_key") or fetch.get("sport_key") or "baseball_mlb"),
                    "commence_time": str(raw_row.get("commence_time") or ""),
                    "game_date": game_date,
                    "home_team": home_team,
                    "away_team": away_team,
                    "book_key": str(raw_row.get("bookmaker") or ""),
                    "book_title": str(raw_row.get("bookmaker_title") or raw_row.get("bookmaker") or ""),
                    "book_last_update": str(raw_row.get("last_update") or ""),
                    "source_market": source_market,
                    "market_label": str(raw_row.get("market_label") or ""),
                    "over_price": over_price,
                    "under_price": under_price,
                    "over_prob": round(over_prob, 6),
                    "under_prob": round(under_prob, 6),
                }
            )

    rows = []
    for (event_id, player_name, market, line), observations in sorted(grouped.items()):
        avg_over = sum(float(obs["over_prob"]) for obs in observations) / len(observations)
        avg_under = sum(float(obs["under_prob"]) for obs in observations) / len(observations)
        first = observations[0]
        rows.append(
            {
                "snapshot_id": snapshot_id,
                "source": source,
                "event_id": event_id,
                "sport_key": first["sport_key"],
                "league": "MLB",
                "game_date": first["game_date"],
                "commence_time": first["commence_time"],
                "home_team": first["home_team"],
                "away_team": first["away_team"],
                "player_name": player_name,
                "player_norm": player_name.lower(),
                "market": market,
                "source_market": first["source_market"],
                "line": line,
                "over_prob": round(avg_over, 6),
                "under_prob": round(avg_under, 6),
                "n_books": len(observations),
                "books": observations,
                "pulled_at_utc": pulled_at_utc,
                "snapshot_timestamp": fetch.get("snapshot_timestamp", ""),
            }
        )

    return {
        "snapshot_id": snapshot_id,
        "source": source,
        "row_count": len(rows),
        "rejected_count": len(rejects),
        "rows": rows,
        "rejects": rejects,
    }


def write_parlayapi_mlb_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    source = str(manifest.get("source") or payload.get("_atlas_fetch", {}).get("source") or PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or source)
    normalized = normalize_parlayapi_mlb_closing_props(
        payload,
        snapshot_id=str(manifest.get("snapshot_id") or ""),
        source=source,
        pulled_at_utc=str(manifest.get("pulled_at_utc") or ""),
    )

    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "oddsapi" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "oddsapi_props.jsonl"
    rejects_path = output_dir / "oddsapi_rejected.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    _write_jsonl(rows_path, normalized["rows"])
    _write_jsonl(rejects_path, normalized["rejects"])
    written_manifest = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": source,
        "row_count": normalized["row_count"],
        "rejected_count": normalized["rejected_count"],
        "rows_path": str(rows_path),
        "rejects_path": str(rejects_path),
        "output_dir": str(output_dir),
        "compatible_artifact": "oddsapi_props.jsonl",
    }
    manifest_path.write_text(json.dumps(written_manifest, indent=2, sort_keys=True), encoding="utf-8")
    return written_manifest


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _valid_player_name(player_name: str) -> bool:
    if not player_name or "{" in player_name or "}" in player_name:
        return False
    if re.search(r"\b(optiontypeabbr|value)\b", player_name, flags=re.IGNORECASE):
        return False
    return True


def _event_id(*, game_date: str, home_team: str, away_team: str) -> str:
    raw = "|".join((game_date, home_team.lower().strip(), away_team.lower().strip()))
    digest = hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"parlayapi_{digest}"


def _reject(snapshot_id: str, source: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "source": source,
        "source_market": str(row.get("market_key") or ""),
        "player": str(row.get("player") or ""),
        "bookmaker": str(row.get("bookmaker") or ""),
        "reason": reason,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

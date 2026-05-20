"""Normalize The Odds API MLB prop snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.normalizers.prizepicks import normalize_player_name
from mlb.normalizers.slate_dates import local_slate_date
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.catalog import ODDSAPI_MLB_BOOKMAKERS
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

ODDSAPI_MARKET_ALIASES = {
    "batter_hits": "hits",
    "batter_total_bases": "total_bases",
    "batter_rbis": "rbis",
    "batter_runs_scored": "runs",
    "batter_hits_runs_rbis": "hits_runs_rbis",
    "batter_singles": "singles",
    "batter_doubles": "doubles",
    "batter_triples": "triples",
    "batter_walks": "walks",
    "batter_strikeouts": "hitter_strikeouts",
    "batter_stolen_bases": "stolen_bases",
    "batter_home_runs": "home_runs",
    "batter_fantasy_score": "hitter_fantasy_score",
    "pitcher_strikeouts": "pitcher_strikeouts",
    "pitcher_hits_allowed": "hits_allowed",
    "pitcher_walks": "walks_allowed",
    "pitcher_earned_runs": "earned_runs_allowed",
}


def normalize_oddsapi_mlb_props(
    payload: dict[str, Any],
    *,
    snapshot_id: str = "",
    source: str = "oddsapi_mlb_live",
    pulled_at_utc: str = "",
    trusted_bookmakers: tuple[str, ...] = ODDSAPI_MLB_BOOKMAKERS,
) -> dict[str, Any]:
    """Convert raw OddsAPI event odds into consensus prop rows."""

    fetch = payload.get("_atlas_fetch") or {}
    grouped: dict[tuple[str, str, str, float], list[dict[str, Any]]] = {}
    rejects: list[dict[str, Any]] = []

    for entry in payload.get("event_odds", []) or []:
        response_payload = ((entry.get("response") or {}).get("payload")) or {}
        event = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else response_payload
        if not isinstance(event, dict):
            continue
        event_id = str(entry.get("event_id") or event.get("id") or "")
        commence_time = str(event.get("commence_time") or "")
        event_context = {
            "event_id": event_id,
            "sport_key": event.get("sport_key") or fetch.get("sport_key") or "baseball_mlb",
            "commence_time": commence_time,
            "game_date": local_slate_date(commence_time, fallback=commence_time[:10]),
            "home_team": event.get("home_team") or "",
            "away_team": event.get("away_team") or "",
        }
        for bookmaker in event.get("bookmakers", []) or []:
            book_key = str(bookmaker.get("key") or "")
            if trusted_bookmakers and book_key not in trusted_bookmakers:
                continue
            book_title = str(bookmaker.get("title") or book_key)
            book_last_update = str(bookmaker.get("last_update") or "")
            for market_payload in bookmaker.get("markets", []) or []:
                source_market = str(market_payload.get("key") or "")
                market = ODDSAPI_MARKET_ALIASES.get(source_market)
                if not market:
                    rejects.append(
                        {
                            "snapshot_id": snapshot_id,
                            "source": source,
                            "event_id": event_id,
                            "source_market": source_market,
                            "reason": "unsupported_market",
                        }
                    )
                    continue
                for player_line, sides in _paired_player_lines(market_payload).items():
                    player_name, line = player_line
                    if "Over" not in sides or "Under" not in sides:
                        continue
                    over_price = _to_float(sides["Over"])
                    under_price = _to_float(sides["Under"])
                    if over_price is None or under_price is None:
                        continue
                    over_prob, under_prob = devig_over_under(over_price, under_price)
                    key = (event_id, normalize_player_name(player_name), market, float(line))
                    grouped.setdefault(key, []).append(
                        {
                            **event_context,
                            "book_key": book_key,
                            "book_title": book_title,
                            "book_last_update": book_last_update,
                            "source_market": source_market,
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


def write_oddsapi_mlb_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    source = str(manifest.get("source") or payload.get("_atlas_fetch", {}).get("source") or "oddsapi_mlb_live")
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or source)
    normalized = normalize_oddsapi_mlb_props(
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
    }
    manifest_path.write_text(json.dumps(written_manifest, indent=2, sort_keys=True), encoding="utf-8")
    return written_manifest


def devig_over_under(over_price: float, under_price: float) -> tuple[float, float]:
    over_implied = american_to_implied(over_price)
    under_implied = american_to_implied(under_price)
    total = over_implied + under_implied
    if total <= 0:
        return 0.5, 0.5
    return over_implied / total, under_implied / total


def american_to_implied(price: float) -> float:
    if price >= 100:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def _paired_player_lines(market_payload: dict[str, Any]) -> dict[tuple[str, float], dict[str, Any]]:
    paired: dict[tuple[str, float], dict[str, Any]] = {}
    for outcome in market_payload.get("outcomes", []) or []:
        side = str(outcome.get("name") or "")
        if side not in {"Over", "Under"}:
            continue
        player = normalize_player_name(str(outcome.get("description") or ""))
        line = _to_float(outcome.get("point"))
        price = _to_float(outcome.get("price"))
        if not player or line is None or price is None:
            continue
        paired.setdefault((player, line), {})[side] = price
    return paired


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

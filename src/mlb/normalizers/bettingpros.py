"""Normalize BettingPros MLB props into Atlas market-context artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.fetchers.bettingpros import BETTINGPROS_MLB_MARKET_ALIASES, BETTINGPROS_MLB_PROPS_SOURCE
from mlb.normalizers.oddsapi import devig_over_under
from mlb.normalizers.prizepicks import normalize_player_name
from mlb.normalizers.slate_dates import local_slate_date
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload


def normalize_bettingpros_mlb_props(
    payload: dict[str, Any],
    *,
    snapshot_id: str = "",
    source: str = BETTINGPROS_MLB_PROPS_SOURCE,
    pulled_at_utc: str = "",
) -> dict[str, Any]:
    """Convert BettingPros consensus/offer rows into OddsAPI-compatible market rows."""

    fetch = payload.get("_atlas_fetch") or {}
    books_by_id = {_str_id(book.get("id")): book for book in payload.get("books", []) or [] if isinstance(book, dict)}
    events_by_id = {_str_id(event.get("id")): event for event in payload.get("events", []) or [] if isinstance(event, dict)}
    markets_by_id = {_str_id(market.get("id")): market for market in payload.get("markets", []) or [] if isinstance(market, dict)}
    offers_index = _index_offers(payload.get("offers", []) or [])
    consensus_book_count = sum(1 for book_id in books_by_id if book_id and book_id != "0")

    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for prop in payload.get("props", []) or []:
        if not isinstance(prop, dict):
            continue
        market_id = _to_int(prop.get("market_id"))
        market = BETTINGPROS_MLB_MARKET_ALIASES.get(market_id or -1)
        if not market:
            rejects.append(_reject(snapshot_id, source, prop, "unsupported_market"))
            continue

        participant = prop.get("participant") if isinstance(prop.get("participant"), dict) else {}
        player_name = normalize_player_name(str(participant.get("name") or ""))
        if not player_name:
            rejects.append(_reject(snapshot_id, source, prop, "missing_player"))
            continue

        over = prop.get("over") if isinstance(prop.get("over"), dict) else {}
        under = prop.get("under") if isinstance(prop.get("under"), dict) else {}
        line = _paired_line(over, under)
        if line is None:
            rejects.append(_reject(snapshot_id, source, prop, "missing_or_mismatched_line"))
            continue

        event_id = _str_id(prop.get("event_id"))
        event = events_by_id.get(event_id, {})
        if not event:
            rejects.append(_reject(snapshot_id, source, prop, "missing_event_context"))
            continue

        player_id = _str_id(participant.get("id"))
        source_market = _source_market(market_id, markets_by_id)
        observations = _offer_observations(
            offers_index.get((event_id, player_id, market_id), []),
            target_line=line,
            books_by_id=books_by_id,
            source_market=source_market,
        )
        if not observations:
            consensus = _consensus_observation(
                over=over,
                under=under,
                source_market=source_market,
                books_by_id=books_by_id,
            )
            if consensus:
                observations = [consensus]
        if not observations:
            rejects.append(_reject(snapshot_id, source, prop, "missing_price_pair"))
            continue

        avg_over = sum(float(obs["over_prob"]) for obs in observations) / len(observations)
        avg_under = sum(float(obs["under_prob"]) for obs in observations) / len(observations)
        n_books = len(observations)
        if len(observations) == 1 and int(observations[0].get("book_id") or 0) == 0:
            n_books = max(n_books, consensus_book_count)
        scheduled = str(event.get("scheduled") or "")
        commence_time = _scheduled_to_utc(scheduled)
        player_payload = participant.get("player") if isinstance(participant.get("player"), dict) else {}
        rows.append(
            {
                "snapshot_id": snapshot_id,
                "source": source,
                "event_id": f"bettingpros_{event_id}",
                "source_event_id": event_id,
                "sport_key": "baseball_mlb",
                "league": "MLB",
                "game_date": local_slate_date(commence_time, fallback=scheduled[:10]),
                "commence_time": commence_time,
                "home_team": str(event.get("home") or ""),
                "away_team": str(event.get("visitor") or ""),
                "player_id": player_id,
                "player_name": player_name,
                "player_norm": player_name.lower(),
                "player_team": str(player_payload.get("team") or ""),
                "market": market,
                "source_market": source_market,
                "source_market_id": market_id,
                "line": line,
                "over_prob": round(avg_over, 6),
                "under_prob": round(avg_under, 6),
                "n_books": n_books,
                "books": observations,
                "pulled_at_utc": pulled_at_utc,
                "snapshot_timestamp": fetch.get("snapshot_timestamp", "") or fetch.get("game_date", ""),
                "bettingpros_projection": _projection_payload(prop),
                "bettingpros_performance": _performance_payload(prop),
            }
        )

    return {
        "snapshot_id": snapshot_id,
        "source": source,
        "row_count": len(rows),
        "rejected_count": len(rejects),
        "rows": sorted(rows, key=lambda row: (row["game_date"], row["player_name"], row["market"], row["line"])),
        "rejects": rejects,
    }


def write_bettingpros_mlb_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    source = str(manifest.get("source") or payload.get("_atlas_fetch", {}).get("source") or BETTINGPROS_MLB_PROPS_SOURCE)
    snapshot_id = str(manifest.get("snapshot_id") or "")
    game_date = str((payload.get("_atlas_fetch") or {}).get("game_date") or "").replace("-", "")
    resolved_run_id = run_id or f"{snapshot_id}_{game_date}" if game_date and game_date not in snapshot_id else run_id or snapshot_id or source
    normalized = normalize_bettingpros_mlb_props(
        payload,
        snapshot_id=snapshot_id,
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


def _index_offers(offers: list[Any]) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    index: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        event_id = _str_id(offer.get("event_id"))
        market_id = _to_int(offer.get("market_id")) or -1
        player_id = _str_id(offer.get("player_id"))
        if not player_id:
            participants = offer.get("participants") if isinstance(offer.get("participants"), list) else []
            if participants and isinstance(participants[0], dict):
                player_id = _str_id(participants[0].get("id"))
        if event_id and player_id and market_id > 0:
            index.setdefault((event_id, player_id, market_id), []).append(offer)
    return index


def _offer_observations(
    offers: list[dict[str, Any]],
    *,
    target_line: float,
    books_by_id: dict[str, dict[str, Any]],
    source_market: str,
) -> list[dict[str, Any]]:
    by_book: dict[str, dict[str, dict[str, Any]]] = {}
    for offer in offers:
        for selection in offer.get("selections", []) or []:
            if not isinstance(selection, dict):
                continue
            side = str(selection.get("selection") or selection.get("label") or "").lower()
            if side not in {"over", "under"}:
                continue
            for book in selection.get("books", []) or []:
                if not isinstance(book, dict):
                    continue
                book_id = _str_id(book.get("id"))
                if not book_id or book_id == "0":
                    continue
                line_payload = _matching_line(book.get("lines") or [], target_line=target_line)
                if line_payload:
                    by_book.setdefault(book_id, {})[side] = line_payload

    observations: list[dict[str, Any]] = []
    for book_id, sides in sorted(by_book.items(), key=lambda item: int(item[0])):
        if "over" not in sides or "under" not in sides:
            continue
        over_price = _to_float(sides["over"].get("cost"))
        under_price = _to_float(sides["under"].get("cost"))
        if over_price is None or under_price is None:
            continue
        over_prob, under_prob = devig_over_under(over_price, under_price)
        book = books_by_id.get(book_id, {})
        observations.append(
            {
                "book_id": int(book_id),
                "book_key": str(book.get("slug") or book.get("short_name") or book_id).lower(),
                "book_title": str(book.get("display_name") or book.get("name") or book_id),
                "book_last_update": str(sides["over"].get("updated") or sides["under"].get("updated") or ""),
                "source_market": source_market,
                "over_price": over_price,
                "under_price": under_price,
                "over_prob": round(over_prob, 6),
                "under_prob": round(under_prob, 6),
                "line": target_line,
            }
        )
    return observations


def _consensus_observation(
    *,
    over: dict[str, Any],
    under: dict[str, Any],
    source_market: str,
    books_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    over_price = _to_float(over.get("consensus_odds"))
    under_price = _to_float(under.get("consensus_odds"))
    book_id = 0
    if over_price is None or under_price is None:
        over_price = _to_float(over.get("odds"))
        under_price = _to_float(under.get("odds"))
        book_id = _to_int(over.get("book")) or _to_int(under.get("book")) or 0
    if over_price is None or under_price is None:
        return None
    over_prob, under_prob = devig_over_under(over_price, under_price)
    book = books_by_id.get(str(book_id), {})
    return {
        "book_id": book_id,
        "book_key": str(book.get("slug") or "bettingpros_consensus").lower(),
        "book_title": str(book.get("display_name") or book.get("name") or "BettingPros Consensus"),
        "book_last_update": "",
        "source_market": source_market,
        "over_price": over_price,
        "under_price": under_price,
        "over_prob": round(over_prob, 6),
        "under_prob": round(under_prob, 6),
        "line": _paired_line(over, under) or 0.0,
    }


def _matching_line(lines: list[Any], *, target_line: float) -> dict[str, Any] | None:
    candidates = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        if line.get("active") is False or line.get("is_off") is True:
            continue
        value = _to_float(line.get("line"))
        if value is None or abs(value - target_line) > 0.0001:
            continue
        candidates.append(line)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (not bool(item.get("main")), not bool(item.get("best"))))[0]


def _paired_line(over: dict[str, Any], under: dict[str, Any]) -> float | None:
    over_line = _to_float(over.get("consensus_line"))
    under_line = _to_float(under.get("consensus_line"))
    if over_line is None:
        over_line = _to_float(over.get("line"))
    if under_line is None:
        under_line = _to_float(under.get("line"))
    if over_line is None or under_line is None:
        return None
    if abs(over_line - under_line) > 0.0001:
        return None
    return float(over_line)


def _source_market(market_id: int | None, markets_by_id: dict[str, dict[str, Any]]) -> str:
    market = markets_by_id.get(str(market_id or ""))
    return str((market or {}).get("slug") or market_id or "")


def _projection_payload(prop: dict[str, Any]) -> dict[str, Any]:
    projection = prop.get("projection") if isinstance(prop.get("projection"), dict) else {}
    over = prop.get("over") if isinstance(prop.get("over"), dict) else {}
    under = prop.get("under") if isinstance(prop.get("under"), dict) else {}
    return {
        "recommended_side": str(projection.get("recommended_side") or ""),
        "projection_value": _to_float(projection.get("value")),
        "projection_probability": _to_float(projection.get("probability")),
        "projection_expected_value": _to_float(projection.get("expected_value")),
        "projection_diff": _to_float(projection.get("diff")),
        "over_provider_probability": _to_float(over.get("probability")),
        "under_provider_probability": _to_float(under.get("probability")),
    }


def _performance_payload(prop: dict[str, Any]) -> dict[str, Any]:
    performance = prop.get("performance") if isinstance(prop.get("performance"), dict) else {}
    return {
        "streak": _to_int(performance.get("streak")) or 0,
        "streak_type": str(performance.get("streak_type") or ""),
        "last_5_over_rate": _side_rate(performance.get("last_5"), side="over"),
        "last_5_under_rate": _side_rate(performance.get("last_5"), side="under"),
        "last_10_over_rate": _side_rate(performance.get("last_10"), side="over"),
        "last_10_under_rate": _side_rate(performance.get("last_10"), side="under"),
        "last_20_over_rate": _side_rate(performance.get("last_20"), side="over"),
        "last_20_under_rate": _side_rate(performance.get("last_20"), side="under"),
        "season_over_rate": _side_rate(performance.get("season"), side="over"),
        "season_under_rate": _side_rate(performance.get("season"), side="under"),
        "prior_season_over_rate": _side_rate(performance.get("prior_season"), side="over"),
        "prior_season_under_rate": _side_rate(performance.get("prior_season"), side="under"),
    }


def _side_rate(value: Any, *, side: str) -> float:
    if not isinstance(value, dict):
        return 0.0
    over = _to_int(value.get("over")) or 0
    under = _to_int(value.get("under")) or 0
    push = _to_int(value.get("push")) or 0
    total = over + under + push
    if total <= 0:
        return 0.0
    hits = over if side == "over" else under
    return round(hits / total, 6)


def _scheduled_to_utc(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "T" in text:
        return text if text.endswith("Z") else f"{text}Z"
    return text.replace(" ", "T") + "Z"


def _reject(snapshot_id: str, source: str, prop: dict[str, Any], reason: str) -> dict[str, Any]:
    participant = prop.get("participant") if isinstance(prop.get("participant"), dict) else {}
    return {
        "snapshot_id": snapshot_id,
        "source": source,
        "event_id": _str_id(prop.get("event_id")),
        "source_market": _str_id(prop.get("market_id")),
        "player": str(participant.get("name") or ""),
        "reason": reason,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _str_id(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

#!/usr/bin/env python3
"""Import public GitHub NBA player-prop odds snapshots into external_priors CSV.

The childersjac-max/Line-Tracker-Model snapshots are side-level JSON rows:

    player, market, side, line, price_american, book_key, event_id, ...

This converter pairs Over/Under rows by player/stat/line/book/event and writes
Atlas external_priors rows with exact market probabilities. It does not fetch
live sportsbook data and it does not invent missing sides.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CSV_FIELDS = [
    "source",
    "league",
    "player",
    "stat",
    "line",
    "asof_ts",
    "projection",
    "confidence",
    "over_prob",
    "under_prob",
    "over_rating",
    "under_rating",
    "opp_rank",
    "notes",
]


MARKET_TO_STAT = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "FG3M",
    "player_threes_made": "FG3M",
    "player_3_pointers_made": "FG3M",
    "player_blocks": "BLK",
    "player_steals": "STL",
    "player_turnovers": "TOV",
    "player_points_rebounds_assists": "PRA",
    "player_points_rebounds": "PR",
    "player_points_assists": "PA",
    "player_rebounds_assists": "RA",
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace("+", "").strip())
    except Exception:
        return None


def _american_to_implied(price: Any) -> float | None:
    value = _safe_float(price)
    if value is None or value == 0:
        return None
    if value >= 100:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def _source_text(path_or_url: str) -> str:
    if re.match(r"^https?://", path_or_url, flags=re.I):
        req = urllib.request.Request(
            path_or_url,
            headers={
                "User-Agent": "AtlasSportsAI replay-recovery/1.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    return Path(path_or_url).expanduser().read_text(encoding="utf-8")


def _infer_asof(source: str, payload: list[dict[str, Any]]) -> str:
    for row in payload:
        for key in ("asof_ts", "timestamp", "pulled_at", "created_at"):
            raw = row.get(key)
            if raw:
                return str(raw)
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})", source)
    if m:
        return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}Z"
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _market_to_stat(market: str) -> str:
    key = str(market or "").strip().lower()
    if key in MARKET_TO_STAT:
        return MARKET_TO_STAT[key]
    compact = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return MARKET_TO_STAT.get(compact, compact.upper())


def convert_rows(payload: list[dict[str, Any]], *, source_name: str, asof_ts: str) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, float, str, str], dict[str, Any]] = defaultdict(dict)
    meta: dict[tuple[str, str, float, str, str], dict[str, Any]] = {}

    for row in payload:
        player = str(row.get("player") or row.get("player_name") or "").strip()
        stat = _market_to_stat(str(row.get("market") or row.get("stat") or ""))
        line = _safe_float(row.get("line"))
        side = str(row.get("side") or row.get("label") or "").strip().lower()
        book = str(row.get("book_key") or row.get("book") or row.get("book_title") or "").strip().lower()
        event_id = str(row.get("event_id") or row.get("game_id") or "").strip()
        price = _safe_float(row.get("price_american") or row.get("price") or row.get("odds"))
        if not player or not stat or line is None or price is None or side not in {"over", "under"}:
            continue
        key = (player, stat, round(line, 4), book, event_id)
        grouped[key][side] = price
        meta[key] = row

    out: list[dict[str, str]] = []
    for key, sides in sorted(grouped.items()):
        player, stat, line, book, event_id = key
        over_raw = _american_to_implied(sides.get("over"))
        under_raw = _american_to_implied(sides.get("under"))
        if over_raw is None and under_raw is None:
            continue
        over_prob = ""
        under_prob = ""
        confidence = "0.88"
        if over_raw is not None and under_raw is not None and (over_raw + under_raw) > 0:
            denom = over_raw + under_raw
            over_prob = f"{over_raw / denom:.6f}"
            under_prob = f"{under_raw / denom:.6f}"
            confidence = "0.95"
        elif over_raw is not None:
            over_prob = f"{over_raw:.6f}"
            confidence = "0.70"
        elif under_raw is not None:
            under_prob = f"{under_raw:.6f}"
            confidence = "0.70"

        source_row = meta.get(key, {})
        notes = [
            f"book={book or 'unknown'}",
            f"event_id={event_id or 'unknown'}",
            f"market={source_row.get('market', '')}",
            f"away={source_row.get('away_team', '')}",
            f"home={source_row.get('home_team', '')}",
            f"over_price={sides.get('over', '')}",
            f"under_price={sides.get('under', '')}",
        ]
        out.append(
            {
                "source": source_name,
                "league": "NBA",
                "player": player,
                "stat": stat,
                "line": f"{line:g}",
                "asof_ts": asof_ts,
                "projection": "",
                "confidence": confidence,
                "over_prob": over_prob,
                "under_prob": under_prob,
                "over_rating": "",
                "under_rating": "",
                "opp_rank": "",
                "notes": "; ".join(notes),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert GitHub NBA prop odds JSON to Atlas external priors CSV.")
    ap.add_argument("input", help="Local JSON path or raw GitHub URL.")
    ap.add_argument("--out", required=True, help="Output CSV path.")
    ap.add_argument("--source-name", default="github_childersjac_props")
    ap.add_argument("--asof-ts", default="", help="Override as-of timestamp.")
    ns = ap.parse_args()

    raw = _source_text(ns.input)
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise SystemExit("Expected a JSON list of prop rows.")
    asof_ts = ns.asof_ts.strip() or _infer_asof(ns.input, payload)
    rows = convert_rows(payload, source_name=ns.source_name, asof_ts=asof_ts)

    out = Path(ns.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"[GITHUB_PROP_ODDS] input_rows={len(payload)} converted_rows={len(rows)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Fetch OddsAPI NBA player props and merge into external_priors_today.csv.

Called every LIVE run by the orchestrator (stage 2c-oddsapi).
In strict-replay mode the orchestrator skips this tool; the pinned CSV is used.

ENV:
  ODDSAPI_KEY               (required) API key for the-odds-api.com
  ODDSAPI_GAME_DATE         (optional) YYYY-MM-DD label; defaults to today
  ODDSAPI_OUT_PATH          (optional) override oddsapi-specific CSV path
  ODDSAPI_ARCHIVE_DIR       (optional) override archive directory
  ODDSAPI_REGIONS           (optional) comma-separated regions; default "us"
  ODDSAPI_MARKETS           (optional) override markets to fetch

Outputs:
  data/input/oddsapi_props_today.csv               (latest fetch, overwritten)
  data/input/external_priors_today.csv              (merged: rotowire + bp + oddsapi)
  data/archives/oddsapi/oddsapi_props_<date>.csv    (immutable per-date archive)

Free tier: 500 credits/month.  Budget per call:
  /events (FREE) + /events/{id}/odds = 1 credit per unique market per region.
  4 markets x N games x 1 region = 4N credits.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_out_path() -> Path:
    return _repo_root() / "data" / "input" / "oddsapi_props_today.csv"


def _default_merged_path() -> Path:
    return _repo_root() / "data" / "input" / "external_priors_today.csv"


def _default_archive_dir() -> Path:
    return _repo_root() / "data" / "archives" / "oddsapi"


# ---------------------------------------------------------------------------
# OddsAPI market key → Atlas stat name
# ---------------------------------------------------------------------------

MARKET_TO_STAT: Dict[str, str] = {
    "player_points":                    "PTS",
    "player_rebounds":                  "REB",
    "player_assists":                   "AST",
    "player_threes":                    "FG3M",
    "player_blocks":                    "BLK",
    "player_steals":                    "STL",
    "player_turnovers":                 "TOV",
    "player_points_rebounds_assists":    "PRA",
    "player_points_rebounds":           "PR",
    "player_points_assists":            "PA",
    "player_rebounds_assists":          "RA",
    "player_blocks_steals":             "BS",
}

# Default: the 4 highest-coverage prop markets (conserves free-tier budget)
DEFAULT_MARKETS = "player_points,player_rebounds,player_assists,player_threes"

BASE_URL = "https://api.the-odds-api.com/v4"

# ---------------------------------------------------------------------------
# Odds math
# ---------------------------------------------------------------------------

def american_to_implied(price: float) -> float:
    """Convert American odds to implied probability (no-vig)."""
    if price >= 100:
        return 100.0 / (price + 100.0)
    else:
        return abs(price) / (abs(price) + 100.0)


def devig_over_under(over_price: float, under_price: float) -> tuple[float, float]:
    """Remove vig from an over/under pair → fair probabilities."""
    imp_over = american_to_implied(over_price)
    imp_under = american_to_implied(under_price)
    total = imp_over + imp_under
    if total <= 0:
        return 0.5, 0.5
    return imp_over / total, imp_under / total


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def fetch_events(api_key: str) -> List[Dict[str, Any]]:
    """GET /v4/sports/basketball_nba/events (FREE — no quota cost)."""
    url = f"{BASE_URL}/sports/basketball_nba/events"
    r = requests.get(url, params={"apiKey": api_key}, timeout=15)
    r.raise_for_status()
    remaining = r.headers.get("x-requests-remaining", "?")
    events = r.json()
    print(f"[OddsAPI] {len(events)} NBA events found  (credits remaining: {remaining})")
    return events


def fetch_event_props(
    api_key: str,
    event_id: str,
    regions: str,
    markets: str,
) -> Dict[str, Any]:
    """GET /events/{eventId}/odds — costs 1 per unique market returned per region."""
    url = f"{BASE_URL}/sports/basketball_nba/events/{event_id}/odds"
    r = requests.get(
        url,
        params={
            "apiKey": api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "american",
        },
        timeout=20,
    )
    r.raise_for_status()
    last_cost = r.headers.get("x-requests-last", "?")
    remaining = r.headers.get("x-requests-remaining", "?")
    data = r.json()
    n_bm = len(data.get("bookmakers", []))
    print(f"  event {event_id[:12]}...  {n_bm} bookmakers  cost={last_cost}  remaining={remaining}")
    return data


# ---------------------------------------------------------------------------
# Parse props into external-prior rows
# ---------------------------------------------------------------------------

def _parse_event_props(event: Dict[str, Any], asof: str) -> List[Dict[str, str]]:
    """Parse one event's bookmaker odds into external-prior CSV rows.

    Strategy: for each (player, stat, line) we collect over/under prices
    across bookmakers, average the de-vigged probabilities, and emit one row
    with the consensus over_prob.
    """
    rows_by_key: Dict[tuple, list] = {}  # (player, stat, line) → list of (over_prob, under_prob)

    for bm in event.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            stat = MARKET_TO_STAT.get(mkt["key"])
            if not stat:
                continue

            # Group outcomes by player+line to pair Over/Under
            player_lines: Dict[tuple, Dict[str, float]] = {}
            for outcome in mkt.get("outcomes", []):
                player = outcome.get("description", "").strip()
                line = outcome.get("point")
                if not player or line is None:
                    continue
                key = (player, float(line))
                if key not in player_lines:
                    player_lines[key] = {}
                player_lines[key][outcome["name"]] = outcome["price"]

            for (player, line), sides in player_lines.items():
                if "Over" in sides and "Under" in sides:
                    o_prob, u_prob = devig_over_under(sides["Over"], sides["Under"])
                    rk = (player, stat, line)
                    if rk not in rows_by_key:
                        rows_by_key[rk] = []
                    rows_by_key[rk].append((o_prob, u_prob))

    # Consensus: average de-vigged probs across bookmakers
    result = []
    for (player, stat, line), probs in rows_by_key.items():
        avg_over = sum(p[0] for p in probs) / len(probs)
        avg_under = sum(p[1] for p in probs) / len(probs)
        n_books = len(probs)

        result.append({
            "source": "oddsapi",
            "league": "NBA",
            "player": player,
            "stat": stat,
            "asof_ts": asof,
            "projection": str(line),       # the sportsbook line IS the projection
            "confidence": str(round(n_books / 10.0, 2)),  # scale by num bookmakers
            "over_prob": str(round(avg_over, 4)),
            "under_prob": str(round(avg_under, 4)),
            "over_rating": "",
            "under_rating": "",
            "opp_rank": "",
            "notes": f"n_books={n_books}",
        })

    return result


# ---------------------------------------------------------------------------
# Write / merge
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "source", "league", "player", "stat", "asof_ts", "projection",
    "confidence", "over_prob", "under_prob", "over_rating", "under_rating",
    "opp_rank", "notes",
]


def _write_csv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OddsAPI] Wrote {len(rows)} rows -> {path}")


def _merge_into_external_priors(oa_rows: List[Dict[str, str]], merged_path: Path) -> None:
    """Merge oddsapi rows into external_priors_today.csv, replacing old OA rows."""
    existing_rows: List[Dict[str, str]] = []
    if merged_path.exists():
        try:
            with merged_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("source", "").strip().lower() != "oddsapi":
                        existing_rows.append(row)
        except Exception as e:
            print(f"[OddsAPI] Warning: could not read existing external priors: {e}", file=sys.stderr)

    all_rows = existing_rows + oa_rows

    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            safe_row = {k: row.get(k, "") for k in CSV_FIELDS}
            writer.writerow(safe_row)
    print(f"[OddsAPI] Merged: {len(existing_rows)} existing + {len(oa_rows)} oddsapi = {len(all_rows)} total -> {merged_path}")


def _archive_snapshot(csv_path: Path, game_date: str, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"oddsapi_props_{game_date}.csv"
    shutil.copy2(str(csv_path), str(dest))
    print(f"[OddsAPI] Archived -> {dest}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ.get("ODDSAPI_KEY", "").strip()
    if not api_key:
        print("[OddsAPI] ERROR: ODDSAPI_KEY env var not set. Skipping.", file=sys.stderr)
        sys.exit(1)

    game_date = os.environ.get("ODDSAPI_GAME_DATE", "").strip()
    if not game_date:
        game_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    regions = os.environ.get("ODDSAPI_REGIONS", "us").strip()
    markets = os.environ.get("ODDSAPI_MARKETS", DEFAULT_MARKETS).strip()

    out_path = Path(os.environ.get("ODDSAPI_OUT_PATH", str(_default_out_path())))
    merged_path = Path(os.environ.get("ODDSAPI_MERGED_PATH", str(_default_merged_path())))
    archive_dir = Path(os.environ.get("ODDSAPI_ARCHIVE_DIR", str(_default_archive_dir())))

    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[OddsAPI] Fetching NBA player props for {game_date}  markets={markets}  regions={regions}")

    # Step 1: Get events (free)
    events = fetch_events(api_key)
    if not events:
        print("[OddsAPI] No upcoming NBA events. Writing empty output.")
        _write_csv([], out_path)
        return

    # Step 2: Fetch props per event
    all_rows: List[Dict[str, str]] = []
    for ev in events:
        try:
            data = fetch_event_props(api_key, ev["id"], regions, markets)
            rows = _parse_event_props(data, asof)
            all_rows.extend(rows)
        except requests.HTTPError as e:
            print(f"  WARNING: event {ev['id'][:12]}... failed: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  WARNING: event {ev['id'][:12]}... error: {e}", file=sys.stderr)

    # Deduplicate: keep one row per (player, stat) — prefer the one with more bookmakers
    seen: Dict[tuple, Dict[str, str]] = {}
    for row in all_rows:
        key = (row["player"], row["stat"])
        if key not in seen:
            seen[key] = row
        else:
            # Keep the one with higher confidence (more bookmakers)
            if float(row.get("confidence", 0)) > float(seen[key].get("confidence", 0)):
                seen[key] = row
    deduped = list(seen.values())

    print(f"[OddsAPI] Total: {len(all_rows)} raw -> {len(deduped)} unique (player, stat) pairs")

    # Step 3: Write outputs
    _write_csv(deduped, out_path)
    _merge_into_external_priors(deduped, merged_path)
    _archive_snapshot(out_path, game_date, archive_dir)

    print(f"[OddsAPI] Done. {len(deduped)} props fetched for {game_date}.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Historical OddsAPI NBA player props backfiller.

For each specified date, fetches historical event IDs and player prop odds
from the-odds-api.com's historical endpoints, then saves a CSV of
de-vigged consensus probabilities that can be joined to the resim cache.

Usage:
  python tools/backfill_oddsapi_historical.py --dates 2026-03-16,2026-04-03 --api-key <KEY>
  python tools/backfill_oddsapi_historical.py --all-cache-dates --api-key <KEY>

ENV:
  ODDSAPI_KEY   (fallback for --api-key)

Outputs per date:
  data/archives/oddsapi/historical/oddsapi_props_<YYYY-MM-DD>.csv

Merged output:
  data/model/oddsapi_historical_props.csv  (all dates concatenated)

Cost per date (estimate):
  1 credit for /historical/events
  + 10 credits × N_markets × N_games for /historical/events/{id}/odds
  Typical: 1 + (10 × 4 × 6 games) = ~241 credits per date
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


ARCHIVE_DIR = _repo_root() / "data" / "archives" / "oddsapi" / "historical"
MERGED_OUTPUT = _repo_root() / "data" / "model" / "oddsapi_historical_props.csv"

# ---------------------------------------------------------------------------
# Market mapping (same as live fetcher)
# ---------------------------------------------------------------------------

MARKET_TO_STAT: Dict[str, str] = {
    "player_points":                 "PTS",
    "player_rebounds":               "REB",
    "player_assists":                "AST",
    "player_threes":                 "FG3M",
    "player_blocks":                 "BLK",
    "player_steals":                 "STL",
    "player_turnovers":              "TOV",
    "player_points_rebounds_assists": "PRA",
    "player_points_rebounds":        "PR",
    "player_points_assists":         "PA",
    "player_rebounds_assists":       "RA",
}

DEFAULT_MARKETS = "player_points,player_rebounds,player_assists,player_threes"
BASE_URL = "https://api.the-odds-api.com/v4"

# ---------------------------------------------------------------------------
# Odds math
# ---------------------------------------------------------------------------

def american_to_implied(price: float) -> float:
    if price >= 100:
        return 100.0 / (price + 100.0)
    else:
        return abs(price) / (abs(price) + 100.0)


def devig(over_price: float, under_price: float) -> tuple[float, float]:
    imp_o = american_to_implied(over_price)
    imp_u = american_to_implied(under_price)
    total = imp_o + imp_u
    if total <= 0:
        return 0.5, 0.5
    return imp_o / total, imp_u / total


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _get(url: str, params: dict, label: str = "") -> dict:
    """GET with retry on 429."""
    for attempt in range(3):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            wait = 2 ** (attempt + 1)
            print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        remaining = r.headers.get("x-requests-remaining", "?")
        cost = r.headers.get("x-requests-last", "?")
        if label:
            print(f"  {label}  cost={cost}  remaining={remaining}")
        return r.json()
    raise RuntimeError(f"Rate limited 3 times for {url}")


def fetch_historical_events(api_key: str, date: str) -> List[Dict[str, Any]]:
    """Get NBA events at a historical timestamp.  Cost: 1 credit."""
    # Use 6pm UTC (early afternoon ET) — props should be posted by then
    timestamp = f"{date}T18:00:00Z"
    url = f"{BASE_URL}/historical/sports/basketball_nba/events"
    data = _get(url, {
        "apiKey": api_key,
        "date": timestamp,
    }, label=f"events for {date}")

    events = data.get("data", [])
    snap_ts = data.get("timestamp", "")
    print(f"  snapshot: {snap_ts}  events: {len(events)}")
    return events


def fetch_historical_event_props(
    api_key: str,
    event_id: str,
    date: str,
    markets: str,
    regions: str = "us",
) -> Dict[str, Any]:
    """Get player props for a historical event.  Cost: 10 × N_markets_returned."""
    timestamp = f"{date}T18:00:00Z"
    url = f"{BASE_URL}/historical/sports/basketball_nba/events/{event_id}/odds"
    data = _get(url, {
        "apiKey": api_key,
        "date": timestamp,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
    }, label=f"  props {event_id[:12]}...")

    return data.get("data", {})


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "game_date", "player", "stat", "line", "over_prob", "under_prob",
    "n_books", "home_team", "away_team",
]


def parse_event_props(event_data: dict, game_date: str) -> List[Dict[str, str]]:
    """Parse historical event odds into rows."""
    home = event_data.get("home_team", "")
    away = event_data.get("away_team", "")

    # Collect (player, stat, line) → list of (over_prob, under_prob)
    agg: Dict[tuple, list] = {}

    for bm in event_data.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            stat = MARKET_TO_STAT.get(mkt.get("key", ""))
            if not stat:
                continue

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
                    o_prob, u_prob = devig(sides["Over"], sides["Under"])
                    rk = (player, stat, line)
                    if rk not in agg:
                        agg[rk] = []
                    agg[rk].append((o_prob, u_prob))

    rows = []
    for (player, stat, line), probs in agg.items():
        avg_over = sum(p[0] for p in probs) / len(probs)
        avg_under = sum(p[1] for p in probs) / len(probs)
        rows.append({
            "game_date": game_date,
            "player": player,
            "stat": stat,
            "line": str(line),
            "over_prob": str(round(avg_over, 4)),
            "under_prob": str(round(avg_under, 4)),
            "n_books": str(len(probs)),
            "home_team": home,
            "away_team": away,
        })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def backfill_date(api_key: str, date: str, markets: str, regions: str = "us") -> List[Dict[str, str]]:
    """Backfill a single date.  Returns rows and saves per-date CSV."""
    print(f"\n{'='*60}")
    print(f"Backfilling {date}")
    print(f"{'='*60}")

    events = fetch_historical_events(api_key, date)
    if not events:
        print(f"  No events found for {date}")
        return []

    all_rows: List[Dict[str, str]] = []
    for ev in events:
        eid = ev["id"]
        try:
            data = fetch_historical_event_props(api_key, eid, date, markets, regions=regions)
            rows = parse_event_props(data, date)
            all_rows.extend(rows)
        except requests.HTTPError as e:
            print(f"  WARNING: {eid[:12]}... failed: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  WARNING: {eid[:12]}... error: {e}", file=sys.stderr)
        # Small delay to avoid rate limiting
        time.sleep(0.3)

    # Deduplicate: keep best (most bookmakers) per (player, stat, line)
    seen: Dict[tuple, Dict[str, str]] = {}
    for row in all_rows:
        key = (row["player"], row["stat"], row["line"])
        if key not in seen or int(row["n_books"]) > int(seen[key]["n_books"]):
            seen[key] = row
    deduped = list(seen.values())

    print(f"  {date}: {len(all_rows)} raw -> {len(deduped)} unique (player, stat)")

    # Save per-date archive
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARCHIVE_DIR / f"oddsapi_props_{date}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(deduped)
    print(f"  Saved -> {out_path}")

    return deduped


def merge_all_dates(archive_dir: Path, output_path: Path) -> int:
    """Concatenate all per-date CSVs into one merged file."""
    all_rows = []
    for csv_file in sorted(archive_dir.glob("oddsapi_props_*.csv")):
        with csv_file.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_rows.extend(list(reader))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nMerged {len(all_rows)} rows across {len(list(archive_dir.glob('oddsapi_props_*.csv')))} dates -> {output_path}")
    return len(all_rows)


def main():
    parser = argparse.ArgumentParser(description="Backfill historical OddsAPI NBA player props")
    parser.add_argument("--dates", type=str, help="Comma-separated YYYY-MM-DD dates")
    parser.add_argument("--all-cache-dates", action="store_true", help="Backfill all resim cache dates")
    parser.add_argument("--api-key", type=str, default=os.environ.get("ODDSAPI_KEY", ""))
    parser.add_argument("--markets", type=str, default=DEFAULT_MARKETS)
    parser.add_argument("--regions", type=str, default="us",
                        help="Comma-separated region keys (e.g. us,us_dfs)")
    parser.add_argument("--force", action="store_true", help="Re-fetch dates with existing archives")
    parser.add_argument("--dry-run", action="store_true", help="Just estimate costs, don't fetch")
    args = parser.parse_args()

    api_key = args.api_key.strip()
    if not api_key:
        print("ERROR: --api-key or ODDSAPI_KEY required", file=sys.stderr)
        sys.exit(1)

    # Determine dates
    if args.dates:
        dates = [d.strip() for d in args.dates.split(",")]
    elif args.all_cache_dates:
        import pickle
        cache_path = _repo_root() / "data" / "model" / "_v13_resim_cache.pkl"
        cache = pickle.load(open(cache_path, "rb"))
        dates = sorted(cache["dates"])
        # Skip dates that already have archives (unless --force)
        if not args.force:
            existing = {f.stem.replace("oddsapi_props_", "") for f in ARCHIVE_DIR.glob("oddsapi_props_*.csv")}
            dates = [d for d in dates if d not in existing]
            print(f"Cache has {len(cache['dates'])} dates, {len(existing)} already backfilled, {len(dates)} to fetch")
        else:
            print(f"Cache has {len(cache['dates'])} dates, --force: re-fetching all")
    else:
        print("ERROR: specify --dates or --all-cache-dates", file=sys.stderr)
        sys.exit(1)

    # Cost estimate
    n_regions = len(args.regions.split(","))
    est_per_date = 1 + 10 * len(args.markets.split(",")) * n_regions * 6  # ~6 games avg
    est_total = est_per_date * len(dates)
    print(f"\nEstimated cost: ~{est_per_date} credits/date × {len(dates)} dates = ~{est_total} credits")

    if args.dry_run:
        print("Dry run — not fetching.")
        return

    # Backfill
    total_rows = 0
    for date in dates:
        rows = backfill_date(api_key, date, args.markets, regions=args.regions)
        total_rows += len(rows)

    # Merge all
    merge_all_dates(ARCHIVE_DIR, MERGED_OUTPUT)

    print(f"\nDone. {total_rows} props across {len(dates)} dates.")


if __name__ == "__main__":
    main()

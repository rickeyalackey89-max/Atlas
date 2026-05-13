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
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


ARCHIVE_DIR = _repo_root() / "data" / "archives" / "oddsapi" / "historical"
RAW_ARCHIVE_DIR = ARCHIVE_DIR / "raw"
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
    "player_blocks_steals":          "BS",
}

DEFAULT_MARKETS = (
    "player_points,player_rebounds,player_assists,player_threes,"
    "player_blocks,player_steals,player_turnovers,"
    "player_points_rebounds_assists,player_points_rebounds,"
    "player_points_assists,player_rebounds_assists,player_blocks_steals"
)
BASE_URL = "https://api.the-odds-api.com/v4"
LAST_REMAINING: Optional[int] = None

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
    global LAST_REMAINING
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
        try:
            LAST_REMAINING = int(remaining)
        except Exception:
            LAST_REMAINING = None
        if label:
            print(f"  {label}  cost={cost}  remaining={remaining}")
        return r.json()
    raise RuntimeError(f"Rate limited 3 times for {url}")


def _snapshot_timestamp(date: str, snapshot_time_utc: str) -> str:
    hhmmss = snapshot_time_utc.strip()
    if len(hhmmss.split(":")) == 2:
        hhmmss = f"{hhmmss}:00"
    return f"{date}T{hhmmss}Z"


def _safe_name(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)


def _norm_name(name: str) -> str:
    import unicodedata

    return (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
        .lower()
    )


def fetch_historical_events(
    api_key: str,
    date: str,
    *,
    snapshot_time_utc: str,
    raw_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Get NBA events at a historical timestamp.  Cost: 1 credit."""
    timestamp = _snapshot_timestamp(date, snapshot_time_utc)
    url = f"{BASE_URL}/historical/sports/basketball_nba/events"
    data = _get(url, {
        "apiKey": api_key,
        "date": timestamp,
    }, label=f"events for {date}")
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "events.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

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
    bookmakers: str = "",
    snapshot_time_utc: str = "22:30:00",
    raw_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Get player props for a historical event.  Cost: 10 × N_markets_returned."""
    timestamp = _snapshot_timestamp(date, snapshot_time_utc)
    url = f"{BASE_URL}/historical/sports/basketball_nba/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "date": timestamp,
        "markets": markets,
        "oddsFormat": "american",
    }
    if bookmakers.strip():
        params["bookmakers"] = bookmakers.strip()
    else:
        params["regions"] = regions
    data = _get(url, params, label=f"  props {event_id[:12]}...")
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"event_{_safe_name(event_id)}.json").write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    return data.get("data", {})


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "source", "league", "game_date", "player", "player_norm", "stat", "line",
    "asof_ts", "projection", "confidence", "over_prob", "under_prob",
    "over_rating", "under_rating", "opp_rank", "notes",
    "n_books", "home_team", "away_team",
]


def parse_event_props(event_data: dict, game_date: str, asof_ts: str) -> List[Dict[str, str]]:
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
            "source": "oddsapi",
            "league": "NBA",
            "game_date": game_date,
            "player": player,
            "player_norm": _norm_name(player),
            "stat": stat,
            "line": str(line),
            "asof_ts": asof_ts,
            "projection": str(line),
            "confidence": str(round(len(probs) / 10.0, 2)),
            "over_prob": str(round(avg_over, 4)),
            "under_prob": str(round(avg_under, 4)),
            "over_rating": "",
            "under_rating": "",
            "opp_rank": "",
            "notes": f"n_books={len(probs)};home={home};away={away}",
            "n_books": str(len(probs)),
            "home_team": home,
            "away_team": away,
        })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def backfill_date(
    api_key: str,
    date: str,
    markets: str,
    regions: str = "us",
    *,
    bookmakers: str = "",
    snapshot_time_utc: str = "22:30:00",
    max_estimated_credits: int = 3000,
    min_remaining_credits: int = 2000,
    historical_cost_multiplier: int = 10,
) -> List[Dict[str, str]]:
    """Backfill a single date.  Returns rows and saves per-date CSV."""
    print(f"\n{'='*60}")
    print(f"Backfilling {date}")
    print(f"{'='*60}")

    raw_dir = RAW_ARCHIVE_DIR / date
    events = fetch_historical_events(
        api_key,
        date,
        snapshot_time_utc=snapshot_time_utc,
        raw_dir=raw_dir,
    )
    if not events:
        print(f"  No events found for {date}")
        return []

    selector_count = len([x for x in (bookmakers or regions).split(",") if x.strip()])
    market_count = len([x for x in markets.split(",") if x.strip()])
    estimated_credits = 1 + historical_cost_multiplier * market_count * selector_count * len(events)
    estimated_props_credits = historical_cost_multiplier * market_count * selector_count * len(events)
    print(
        f"  Estimated date cost: ~{estimated_credits} credits "
        f"({len(events)} events x {market_count} markets x {selector_count} selectors x {historical_cost_multiplier})"
    )
    if max_estimated_credits > 0 and estimated_credits > max_estimated_credits:
        raise RuntimeError(
            f"Estimated cost {estimated_credits} exceeds --max-estimated-credits {max_estimated_credits}"
        )
    if (
        min_remaining_credits > 0
        and LAST_REMAINING is not None
        and LAST_REMAINING - estimated_props_credits < min_remaining_credits
    ):
        raise RuntimeError(
            f"Aborting before prop calls: remaining={LAST_REMAINING}, "
            f"estimated_props_cost={estimated_props_credits}, "
            f"min_remaining={min_remaining_credits}"
        )

    all_rows: List[Dict[str, str]] = []
    asof_ts = _snapshot_timestamp(date, snapshot_time_utc)
    estimated_event_cost = historical_cost_multiplier * market_count * selector_count
    for ev in events:
        eid = ev["id"]
        try:
            if (
                min_remaining_credits > 0
                and LAST_REMAINING is not None
                and LAST_REMAINING - estimated_event_cost < min_remaining_credits
            ):
                raise RuntimeError(
                    f"Credit reserve guard tripped before event {eid[:12]}: "
                    f"remaining={LAST_REMAINING}, estimated_next_cost={estimated_event_cost}, "
                    f"min_remaining={min_remaining_credits}"
                )
            data = fetch_historical_event_props(
                api_key,
                eid,
                date,
                markets,
                regions=regions,
                bookmakers=bookmakers,
                snapshot_time_utc=snapshot_time_utc,
                raw_dir=raw_dir,
            )
            rows = parse_event_props(data, date, asof_ts)
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
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
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
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
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
    parser.add_argument("--bookmakers", type=str, default="",
                        help="Comma-separated bookmaker keys. Use prizepicks for PP-only. Overrides --regions.")
    parser.add_argument("--snapshot-time-utc", type=str, default="22:30:00",
                        help="Historical snapshot time in UTC, default 22:30:00 (5:30pm Central during DST).")
    parser.add_argument("--max-estimated-credits", type=int, default=3000,
                        help="Abort before prop calls if one date is estimated above this credit count. Set 0 to disable.")
    parser.add_argument("--min-remaining-credits", type=int, default=2000,
                        help="Abort before prop calls if projected remaining credits would fall below this reserve.")
    parser.add_argument("--current-remaining-credits", type=int, default=0,
                        help="Optional known current remaining credits; if set, guard total estimate before any API calls.")
    parser.add_argument("--historical-cost-multiplier", type=int, default=10,
                        help="Conservative historical endpoint credit multiplier per event/market/selector.")
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
    selector_count = len([x for x in (args.bookmakers or args.regions).split(",") if x.strip()])
    est_per_date = (
        1
        + args.historical_cost_multiplier
        * len([x for x in args.markets.split(",") if x.strip()])
        * selector_count
        * 6
    )  # ~6 games avg
    est_total = est_per_date * len(dates)
    print(f"\nEstimated cost: ~{est_per_date} credits/date × {len(dates)} dates = ~{est_total} credits")
    if args.bookmakers:
        print(f"Bookmaker filter: {args.bookmakers}")
    print(f"Snapshot UTC: {args.snapshot_time_utc}")
    print(f"Credit reserve guard: keep >= {args.min_remaining_credits} credits")
    if args.current_remaining_credits:
        projected = args.current_remaining_credits - est_total
        print(f"Known remaining: {args.current_remaining_credits}; projected after estimate: {projected}")
        if args.min_remaining_credits > 0 and projected < args.min_remaining_credits:
            raise SystemExit(
                f"ABORT: estimated run would leave {projected} credits, below reserve "
                f"{args.min_remaining_credits}"
            )

    if args.dry_run:
        print("Dry run — not fetching.")
        return

    # Backfill
    total_rows = 0
    for date in dates:
        rows = backfill_date(
            api_key,
            date,
            args.markets,
            regions=args.regions,
            bookmakers=args.bookmakers,
            snapshot_time_utc=args.snapshot_time_utc,
            max_estimated_credits=args.max_estimated_credits,
            min_remaining_credits=args.min_remaining_credits,
            historical_cost_multiplier=args.historical_cost_multiplier,
        )
        total_rows += len(rows)

    # Merge all
    merge_all_dates(ARCHIVE_DIR, MERGED_OUTPUT)

    print(f"\nDone. {total_rows} props across {len(dates)} dates.")


if __name__ == "__main__":
    main()

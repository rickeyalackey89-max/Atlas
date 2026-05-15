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


def _default_market_json_path() -> Path:
    return _repo_root() / "data" / "input" / "odds_market_today.json"


def _default_token_path() -> Path:
    return _repo_root().parent / "OddAPItoken.txt"


def _load_api_key() -> tuple[str, str]:
    """Load OddsAPI key without relying on stale shell environment values.

    The live operator workflow keeps the current token outside the repo in
    OddAPItoken.txt. Prefer that file when present so an already-open terminal
    cannot accidentally keep using an old ODDSAPI_KEY.
    """
    explicit_path = os.environ.get("ODDSAPI_KEY_FILE", "").strip()
    candidates = [Path(explicit_path)] if explicit_path else []
    candidates.append(_default_token_path())

    for path in candidates:
        try:
            if path.exists() and path.is_file():
                token = path.read_text(encoding="utf-8").strip()
                if token:
                    return token, f"file:{path.name}"
        except OSError:
            continue

    for name in ("ODDSAPI_KEY", "ODDS_API_KEY"):
        token = os.environ.get(name, "").strip()
        if token:
            return token, f"env:{name}"

    return "", "missing"


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

# All 12 supported prop markets — requires Developer plan
DEFAULT_MARKETS = "player_points,player_rebounds,player_assists,player_threes,player_blocks,player_steals,player_turnovers,player_points_rebounds_assists,player_points_rebounds,player_points_assists,player_rebounds_assists,player_blocks_steals"

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
    _raise_for_status_redacted(r, "events")
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
    _raise_for_status_redacted(r, f"event odds {event_id[:12]}...")
    last_cost = r.headers.get("x-requests-last", "?")
    remaining = r.headers.get("x-requests-remaining", "?")
    data = r.json()
    n_bm = len(data.get("bookmakers", []))
    print(f"  event {event_id[:12]}...  {n_bm} bookmakers  cost={last_cost}  remaining={remaining}")
    return data


def _raise_for_status_redacted(response: requests.Response, context: str) -> None:
    """Raise an HTTP error without leaking apiKey in the request URL."""
    if response.status_code < 400:
        return

    detail = response.text.strip().replace("\r", " ").replace("\n", " ")
    if len(detail) > 240:
        detail = detail[:237] + "..."
    if not detail:
        detail = response.reason or "request failed"
    raise RuntimeError(f"OddsAPI {context} failed HTTP {response.status_code}: {detail}")


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


def _parse_event_props_per_book(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse one event's odds preserving per-bookmaker (DK/FD) raw American lines.

    Returns list of {player, player_norm, stat, line, dk_over, dk_under,
    fd_over, fd_under, dk_imp_over, fd_imp_over}.
    """
    import unicodedata

    def _norm(name: str) -> str:
        return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").strip().lower()

    # (player, stat, line) -> {bm_key: {over: price, under: price}}
    agg: Dict[tuple, Dict[str, Dict[str, float]]] = {}

    for bm in event.get("bookmakers", []):
        bm_key = bm.get("key", "")
        if bm_key not in ("draftkings", "fanduel"):
            continue
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
                if "Over" not in sides or "Under" not in sides:
                    continue
                rk = (player, stat, line)
                if rk not in agg:
                    agg[rk] = {}
                agg[rk][bm_key] = {"over": sides["Over"], "under": sides["Under"]}

    rows: List[Dict[str, Any]] = []
    for (player, stat, line), books in agg.items():
        row: Dict[str, Any] = {
            "player":       player,
            "player_norm":  _norm(player),
            "stat":         stat,
            "line":         line,
            "dk_over":      None,
            "dk_under":     None,
            "fd_over":      None,
            "fd_under":     None,
            "dk_imp_over":  None,
            "fd_imp_over":  None,
        }
        if "draftkings" in books:
            dk = books["draftkings"]
            imp_o, _ = devig_over_under(dk["over"], dk["under"])
            row["dk_over"]   = int(round(dk["over"]))
            row["dk_under"]  = int(round(dk["under"]))
            row["dk_imp_over"] = round(imp_o, 4)
        if "fanduel" in books:
            fd = books["fanduel"]
            imp_o, _ = devig_over_under(fd["over"], fd["under"])
            row["fd_over"]   = int(round(fd["over"]))
            row["fd_under"]  = int(round(fd["under"]))
            row["fd_imp_over"] = round(imp_o, 4)
        rows.append(row)
    return rows


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
    api_key, api_key_source = _load_api_key()
    if not api_key:
        print(
            "[OddsAPI] ERROR: no OddsAPI key found. Expected OddAPItoken.txt or ODDSAPI_KEY.",
            file=sys.stderr,
        )
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
    print(f"[OddsAPI] API key source: {api_key_source}  length={len(api_key)}")

    # Step 1: Get events (free)
    events = fetch_events(api_key)
    if not events:
        print("[OddsAPI] No upcoming NBA events. Writing empty output.")
        _write_csv([], out_path)
        return

    # Step 2: Fetch props per event — cache raw responses for both parsers
    all_rows: List[Dict[str, str]] = []
    raw_event_data: List[Dict[str, Any]] = []
    for ev in events:
        try:
            data = fetch_event_props(api_key, ev["id"], regions, markets)
            raw_event_data.append(data)
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

    # Step 4: Write per-bookmaker JSON for Market tab (DK + FD raw American odds)
    market_json_path = _default_market_json_path()
    market_rows: List[Dict[str, Any]] = []
    for data in raw_event_data:
        market_rows.extend(_parse_event_props_per_book(data))
    # Dedupe: keep entry with most bookmaker coverage
    mkt_seen: Dict[tuple, Dict[str, Any]] = {}
    for r in market_rows:
        k = (r["player_norm"], r["stat"], r["line"])
        if k not in mkt_seen:
            mkt_seen[k] = r
        else:
            existing = mkt_seen[k]
            score_new = (r["dk_over"] is not None) + (r["fd_over"] is not None)
            score_old = (existing["dk_over"] is not None) + (existing["fd_over"] is not None)
            if score_new > score_old:
                mkt_seen[k] = r
    market_json_path.parent.mkdir(parents=True, exist_ok=True)
    market_json_path.write_text(json.dumps(list(mkt_seen.values()), indent=2), encoding="utf-8")
    print(f"[OddsAPI] Market JSON -> {market_json_path}  ({len(mkt_seen)} entries)")

    print(f"[OddsAPI] Done. {len(deduped)} props fetched for {game_date}.")


if __name__ == "__main__":
    main()

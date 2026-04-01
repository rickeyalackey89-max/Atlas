#!/usr/bin/env python3
"""
Fetch BettingPros NBA player props and write to external_priors_today.csv.

Called every LIVE run by the orchestrator (stage 2c).
In strict-replay mode the orchestrator skips this tool; the pinned CSV is used instead.

ENV:
  BETTINGPROS_GAME_DATE     (optional) YYYY-MM-DD for labelling
  BETTINGPROS_TIMEOUT_S     (optional) per-page timeout, default 20
  BETTINGPROS_OUT_PATH      (optional) override output csv path
  BETTINGPROS_ARCHIVE_DIR   (optional) override archive directory
  BETTINGPROS_MAX_PAGES     (optional) safety cap on pagination, default 20
  BETTINGPROS_DEBUG_DIR     (optional) where to dump raw JSON pages
  BETTINGPROS_BASE_URL      (optional) API base URL override

Outputs:
  data/input/bettingpros_props_today.csv          (latest fetch, overwritten each run)
  data/input/external_priors_today.csv             (merged: rotowire + bettingpros rows)
  data/archives/bettingpros/bettingpros_props_<date>.csv  (immutable per-date archive)
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
    return _repo_root() / "data" / "input" / "bettingpros_props_today.csv"


def _default_merged_path() -> Path:
    return _repo_root() / "data" / "input" / "external_priors_today.csv"


def _default_archive_dir() -> Path:
    return _repo_root() / "data" / "archives" / "bettingpros"


def _debug_dir() -> Path:
    p = Path(os.getenv("BETTINGPROS_DEBUG_DIR", str(_repo_root() / "data" / "output" / "debug")))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# BettingPros market_id → Atlas stat name
# ---------------------------------------------------------------------------

MARKET_ID_TO_STAT: Dict[int, str] = {
    156: "PTS",
    157: "REB",
    151: "AST",
    152: "BLK",
    160: "STL",
    162: "FG3M",
    142: "TOV",
    136: "FG3M",   # alternate 3pt market id
    335: "PA",     # Points + Assists
    336: "PR",     # Points + Rebounds
    337: "RA",     # Rebounds + Assists
    338: "PRA",    # Points + Rebounds + Assists
}

# Only fetch markets Atlas cares about
MARKET_IDS = sorted(MARKET_ID_TO_STAT.keys())

BASE_URL = "https://api.bettingpros.com/v3/props"

# Request parameters (derived from the cached JSON)
DEFAULT_PARAMS: Dict[str, Any] = {
    "sport": "NBA",
    "market_id": ":".join(str(m) for m in MARKET_IDS),
    "event_status": "upcoming",
    "limit": "25",
    "sort": "diff",
    "sort_direction": "desc",
    "ev_threshold": "true",
    "ev_threshold_min": "-0.4",
    "ev_threshold_max": "0.4",
    "min_odds": "-1000",
    "max_odds": "1000",
    "include_markets": "true",
    "include_selections": "false",
    "include_injured": "false",
    "include_books": "false",
    "include_events": "false",
    "include_correlated_picks": "false",
    "include_counts": "false",
    "include_filter_graphs": "false",
    "performance_type_sort": "last_15",
    "performance_type_filter": "last_15",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.bettingpros.com/nba/props/",
}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_page(session: requests.Session, page: int, timeout: int) -> dict:
    params = {**DEFAULT_PARAMS, "page": str(page)}
    base = os.getenv("BETTINGPROS_BASE_URL", BASE_URL).strip()
    resp = session.get(base, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_all_props(timeout: int = 20, max_pages: int = 20) -> List[dict]:
    """Paginate through all BettingPros NBA props. Returns list of raw prop dicts."""
    session = requests.Session()
    all_props: List[dict] = []

    # First page to determine pagination
    data = _fetch_page(session, page=1, timeout=timeout)
    pagination = data.get("_pagination", {})
    total_pages = min(pagination.get("total_pages", 1), max_pages)
    total_items = pagination.get("total_items", 0)
    props = data.get("props", [])
    all_props.extend(props)

    print(f"[BP] Page 1/{total_pages} fetched ({len(props)} props, {total_items} total)")

    # Save debug page
    try:
        (_debug_dir() / "bettingpros_page_1.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    for page in range(2, total_pages + 1):
        try:
            data = _fetch_page(session, page=page, timeout=timeout)
            props = data.get("props", [])
            all_props.extend(props)
            print(f"[BP] Page {page}/{total_pages} fetched ({len(props)} props)")

            try:
                (_debug_dir() / f"bettingpros_page_{page}.json").write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
            except Exception:
                pass
        except Exception as e:
            print(f"[BP] Page {page} failed: {e}", file=sys.stderr)
            break

    return all_props


# ---------------------------------------------------------------------------
# Transform to external_priors CSV format
# ---------------------------------------------------------------------------

def _prop_to_row(prop: dict, asof_ts: str) -> Optional[Dict[str, str]]:
    """Convert a single BettingPros prop JSON to an external_priors CSV row."""
    market_id = prop.get("market_id")
    stat = MARKET_ID_TO_STAT.get(int(market_id)) if market_id is not None else None
    if not stat:
        return None

    participant = prop.get("participant", {})
    player_name = participant.get("name", "").strip()
    if not player_name:
        return None

    projection = prop.get("projection", {})
    proj_value = projection.get("value")
    if proj_value is None:
        return None

    bet_rating = projection.get("bet_rating") or 0
    recommended_side = projection.get("recommended_side", "")
    diff = projection.get("diff") or 0

    # Build confidence from bet_rating (1-5 scale → 0.2-1.0)
    confidence = round(max(0.2, min(1.0, bet_rating / 5.0)), 4)

    # Performance data for notes
    perf = prop.get("performance") or {}
    last_10 = perf.get("last_10") or {}
    over_10 = last_10.get("over", 0)
    under_10 = last_10.get("under", 0)
    total_10 = over_10 + under_10 + last_10.get("push", 0)
    streak = perf.get("streak", 0)
    streak_type = perf.get("streak_type", "")

    opp_rank = ""
    extra = prop.get("extra", {})
    opp = extra.get("opposition_rank", {})
    if opp:
        opp_rank = f"opp_rank={opp.get('rank', '?')}"

    over_info = prop.get("over", {})
    under_info = prop.get("under", {})
    line = over_info.get("consensus_line") or over_info.get("line", "")

    notes_parts = [
        f"side={recommended_side}",
        f"rating={bet_rating}",
        f"diff={diff}",
        f"line={line}",
        f"L10={over_10}o/{under_10}u/{total_10}g",
        f"streak={streak}{streak_type[0] if streak_type else ''}",
    ]
    if opp_rank:
        notes_parts.append(opp_rank)

    return {
        "source": "bettingpros",
        "league": "NBA",
        "player": player_name,
        "stat": stat,
        "asof_ts": asof_ts,
        "projection": str(proj_value),
        "confidence": str(confidence),
        "notes": "; ".join(notes_parts),
    }


def _props_to_csv_rows(props: List[dict], asof_ts: str) -> List[Dict[str, str]]:
    rows = []
    seen = set()
    for prop in props:
        row = _prop_to_row(prop, asof_ts)
        if row is None:
            continue
        key = (row["player"], row["stat"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Write / merge
# ---------------------------------------------------------------------------

CSV_FIELDS = ["source", "league", "player", "stat", "asof_ts", "projection", "confidence", "notes"]


def _write_bp_csv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[BP] Wrote {len(rows)} rows → {path}")


def _merge_into_external_priors(bp_rows: List[Dict[str, str]], merged_path: Path) -> None:
    """Merge bettingpros rows into external_priors_today.csv, replacing old BP rows."""
    existing_rows: List[Dict[str, str]] = []
    if merged_path.exists():
        try:
            with merged_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("source", "").strip().lower() != "bettingpros":
                        existing_rows.append(row)
        except Exception as e:
            print(f"[BP] Warning: could not read existing external priors: {e}", file=sys.stderr)

    all_rows = existing_rows + bp_rows

    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"[BP] Merged external priors: {len(existing_rows)} existing + {len(bp_rows)} bettingpros = {len(all_rows)} total → {merged_path}")


def _archive_snapshot(bp_csv_path: Path, game_date: str, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"bettingpros_props_{game_date}.csv"
    dest = archive_dir / archive_name
    shutil.copy2(str(bp_csv_path), str(dest))
    print(f"[BP] Archived → {dest}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    game_date = (os.getenv("BETTINGPROS_GAME_DATE") or os.getenv("ATLAS_GAME_DATE") or "").strip()
    if not game_date:
        game_date = datetime.now().strftime("%Y-%m-%d")

    timeout = int(os.getenv("BETTINGPROS_TIMEOUT_S", "20"))
    max_pages = int(os.getenv("BETTINGPROS_MAX_PAGES", "20"))
    out_path = Path(os.getenv("BETTINGPROS_OUT_PATH", "").strip() or str(_default_out_path()))
    merged_path = Path(os.getenv("BETTINGPROS_MERGED_PATH", "").strip() or str(_default_merged_path()))
    archive_dir = Path(os.getenv("BETTINGPROS_ARCHIVE_DIR", "").strip() or str(_default_archive_dir()))

    print(f"[BP] Fetching BettingPros NBA props for {game_date} ...")

    try:
        all_props = _fetch_all_props(timeout=timeout, max_pages=max_pages)
    except Exception as e:
        print(f"[BP] Fetch FAILED: {e}", file=sys.stderr)
        print("[BP] Continuing without BettingPros data (non-fatal).")
        return 0  # non-fatal: model can run without external priors

    if not all_props:
        print("[BP] No props returned (0 items). Skipping.")
        return 0

    asof_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = _props_to_csv_rows(all_props, asof_ts)
    print(f"[BP] Converted {len(all_props)} raw props → {len(rows)} unique CSV rows")

    if not rows:
        print("[BP] 0 usable rows after conversion. Skipping.")
        return 0

    # Write standalone BP CSV
    _write_bp_csv(rows, out_path)

    # Merge into external_priors_today.csv
    _merge_into_external_priors(rows, merged_path)

    # Archive for replay
    _archive_snapshot(out_path, game_date, archive_dir)

    # Write summary
    stat_counts = {}
    for r in rows:
        stat_counts[r["stat"]] = stat_counts.get(r["stat"], 0) + 1
    print(f"[BP] Stats breakdown: {dict(sorted(stat_counts.items()))}")
    print(f"[BP] Done. {len(rows)} props ready for external priors.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

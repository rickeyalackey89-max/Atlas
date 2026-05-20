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
  data/input/odds_market_today.json                (DraftKings/FanDuel market odds package)
  data/archives/bettingpros/bettingpros_props_<date>.csv  (immutable per-date archive)
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import unicodedata
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


def _default_market_json_path() -> Path:
    return _repo_root() / "data" / "input" / "odds_market_today.json"


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

BOOK_ID_TO_MARKET_PREFIX = {
    12: "dk",  # DraftKings
    10: "fd",  # FanDuel
}

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

def _fetch_page(
    session: requests.Session,
    page: int,
    timeout: int,
    param_overrides: Optional[Dict[str, Any]] = None,
) -> dict:
    params = {**DEFAULT_PARAMS, **(param_overrides or {}), "page": str(page)}
    base = os.getenv("BETTINGPROS_BASE_URL", BASE_URL).strip()
    resp = session.get(base, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_all_props(
    timeout: int = 20,
    max_pages: int = 20,
    param_overrides: Optional[Dict[str, Any]] = None,
    label: str = "BP",
) -> List[dict]:
    """Paginate through all BettingPros NBA props. Returns list of raw prop dicts."""
    session = requests.Session()
    all_props: List[dict] = []

    # First page to determine pagination
    data = _fetch_page(session, page=1, timeout=timeout, param_overrides=param_overrides)
    pagination = data.get("_pagination", {})
    total_pages = min(pagination.get("total_pages", 1), max_pages)
    total_items = pagination.get("total_items", 0)
    props = data.get("props", [])
    all_props.extend(props)

    print(f"[{label}] Page 1/{total_pages} fetched ({len(props)} props, {total_items} total)")

    if label == "BP":
        # Save debug page for the primary all-books fetch.
        try:
            (_debug_dir() / "bettingpros_page_1.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    for page in range(2, total_pages + 1):
        try:
            data = _fetch_page(session, page=page, timeout=timeout, param_overrides=param_overrides)
            props = data.get("props", [])
            all_props.extend(props)
            print(f"[{label}] Page {page}/{total_pages} fetched ({len(props)} props)")

            if label == "BP":
                try:
                    (_debug_dir() / f"bettingpros_page_{page}.json").write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"[{label}] Page {page} failed: {e}", file=sys.stderr)
            break

    return all_props


# ---------------------------------------------------------------------------
# Transform to external_priors CSV format
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").strip().lower()


def _american_to_implied(price: float) -> float:
    if price >= 100:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def _devig_over_under(over_price: float, under_price: float) -> tuple[float, float]:
    imp_over = _american_to_implied(over_price)
    imp_under = _american_to_implied(under_price)
    total = imp_over + imp_under
    if total <= 0:
        return 0.5, 0.5
    return imp_over / total, imp_under / total

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

    # Market-implied probabilities per side
    over_info = prop.get("over", {})
    under_info = prop.get("under", {})
    over_prob = over_info.get("probability", "")
    under_prob = under_info.get("probability", "")
    over_rating = over_info.get("bet_rating", "")
    under_rating = under_info.get("bet_rating", "")
    line = over_info.get("consensus_line") or over_info.get("line", "")

    # Opposition rank
    extra = prop.get("extra", {})
    opp = extra.get("opposition_rank", {})
    opp_rank_val = opp.get("rank", "") if opp else ""

    # Performance data for notes
    perf = prop.get("performance") or {}
    last_5 = perf.get("last_5") or {}
    last_10 = perf.get("last_10") or {}
    last_20 = perf.get("last_20") or {}
    season = perf.get("season") or {}
    over_10 = last_10.get("over", 0)
    under_10 = last_10.get("under", 0)
    total_10 = over_10 + under_10 + last_10.get("push", 0)
    streak = perf.get("streak", 0)
    streak_type = perf.get("streak_type", "")

    notes_parts = [
        f"side={recommended_side}",
        f"rating={bet_rating}",
        f"diff={diff}",
        f"line={line}",
        f"L10={over_10}o/{under_10}u/{total_10}g",
        f"streak={streak}{streak_type[0] if streak_type else ''}",
    ]
    if opp_rank_val:
        notes_parts.append(f"opp_rank={opp_rank_val}")

    return {
        "source": "bettingpros",
        "league": "NBA",
        "player": player_name,
        "stat": stat,
        "line": str(line) if line != "" else "",
        "asof_ts": asof_ts,
        "projection": str(proj_value),
        "confidence": str(confidence),
        "over_prob": str(over_prob) if over_prob != "" else "",
        "under_prob": str(under_prob) if under_prob != "" else "",
        "over_rating": str(over_rating) if over_rating != "" else "",
        "under_rating": str(under_rating) if under_rating != "" else "",
        "opp_rank": str(opp_rank_val),
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


def _prop_to_market_row(prop: dict, book_prefix: str) -> Optional[Dict[str, Any]]:
    market_id = prop.get("market_id")
    stat = MARKET_ID_TO_STAT.get(int(market_id)) if market_id is not None else None
    if not stat:
        return None

    participant = prop.get("participant", {})
    player_name = str(participant.get("name") or "").strip()
    if not player_name:
        return None

    over_info = prop.get("over") or {}
    under_info = prop.get("under") or {}
    line = over_info.get("line")
    if line is None:
        line = over_info.get("consensus_line")
    if line is None:
        line = under_info.get("line")
    if line is None:
        line = under_info.get("consensus_line")

    over_odds = over_info.get("odds")
    under_odds = under_info.get("odds")
    if line is None or over_odds is None or under_odds is None:
        return None

    try:
        line_f = float(line)
        over_price = float(over_odds)
        under_price = float(under_odds)
    except (TypeError, ValueError):
        return None

    imp_over, _ = _devig_over_under(over_price, under_price)
    row: Dict[str, Any] = {
        "player": player_name,
        "player_norm": _norm_name(player_name),
        "stat": stat,
        "line": line_f,
        "dk_over": None,
        "dk_under": None,
        "fd_over": None,
        "fd_under": None,
        "dk_imp_over": None,
        "fd_imp_over": None,
    }
    row[f"{book_prefix}_over"] = int(round(over_price))
    row[f"{book_prefix}_under"] = int(round(under_price))
    row[f"{book_prefix}_imp_over"] = round(imp_over, 4)
    return row


def _merge_market_rows(book_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[tuple, Dict[str, Any]] = {}
    for row in book_rows:
        key = (row["player_norm"], row["stat"], row["line"])
        if key not in merged:
            merged[key] = {
                "player": row["player"],
                "player_norm": row["player_norm"],
                "stat": row["stat"],
                "line": row["line"],
                "dk_over": None,
                "dk_under": None,
                "fd_over": None,
                "fd_under": None,
                "dk_imp_over": None,
                "fd_imp_over": None,
            }
        target = merged[key]
        for field in ("dk_over", "dk_under", "fd_over", "fd_under", "dk_imp_over", "fd_imp_over"):
            if row.get(field) is not None:
                target[field] = row[field]
    return list(merged.values())


def _avg_present(values: List[Any]) -> Optional[float]:
    nums: List[float] = []
    for value in values:
        if value is None:
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    return sum(nums) / len(nums)


def _market_rows_to_external_prior_rows(
    market_rows: List[Dict[str, Any]],
    asof_ts: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for row in market_rows:
        over_prob = _avg_present([row.get("dk_imp_over"), row.get("fd_imp_over")])
        if over_prob is None:
            continue
        try:
            line = float(row.get("line"))
        except (TypeError, ValueError):
            continue

        book_count = int(row.get("dk_imp_over") is not None) + int(row.get("fd_imp_over") is not None)
        confidence = 1.0 if book_count >= 2 else 0.75
        under_prob = 1.0 - over_prob
        notes = [
            "type=exact_market",
            f"books={book_count}",
            f"dk_over={row.get('dk_over')}",
            f"dk_under={row.get('dk_under')}",
            f"fd_over={row.get('fd_over')}",
            f"fd_under={row.get('fd_under')}",
        ]
        rows.append(
            {
                "source": "bettingpros_market",
                "league": "NBA",
                "player": str(row.get("player") or "").strip(),
                "stat": str(row.get("stat") or "").strip().upper(),
                "line": str(line),
                "asof_ts": asof_ts,
                # Neutral projection: exact market rows are consumed by line
                # match + over/under probabilities, not by projection edge.
                "projection": str(line),
                "confidence": str(confidence),
                "over_prob": str(round(over_prob, 4)),
                "under_prob": str(round(under_prob, 4)),
                "over_rating": "",
                "under_rating": "",
                "opp_rank": "",
                "notes": "; ".join(notes),
            }
        )
    return rows


def _fetch_market_rows(timeout: int, max_pages: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for book_id, prefix in BOOK_ID_TO_MARKET_PREFIX.items():
        label = f"BP-{prefix.upper()}"
        props = _fetch_all_props(
            timeout=timeout,
            max_pages=max_pages,
            param_overrides={
                "book_id": str(book_id),
                "ev_threshold": "false",
            },
            label=label,
        )
        for prop in props:
            row = _prop_to_market_row(prop, prefix)
            if row is not None:
                rows.append(row)
    return _merge_market_rows(rows)


# ---------------------------------------------------------------------------
# Write / merge
# ---------------------------------------------------------------------------

CSV_FIELDS = ["source", "league", "player", "stat", "line", "asof_ts", "projection", "confidence", "over_prob", "under_prob", "over_rating", "under_rating", "opp_rank", "notes"]


def _write_bp_csv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[BP] Wrote {len(rows)} rows -> {path}")


def _merge_into_external_priors(bp_rows: List[Dict[str, str]], merged_path: Path) -> None:
    """Merge bettingpros rows into external_priors_today.csv.

    A BettingPros live fetch is now the primary odds source. Purge stale
    OddsAPI rows by default so an expired or skipped ODDSAPI fetch cannot leave
    yesterday's market priors in the model input. If OddsAPI is explicitly
    enabled, the orchestrator runs that tool after this one and adds fresh rows.
    """
    stale_sources = {"bettingpros", "bettingpros_market"}
    keep_oddsapi = os.getenv("BETTINGPROS_KEEP_ODDSAPI_PRIORS", "").strip().lower() in {"1", "true", "yes", "y"}
    if not keep_oddsapi:
        stale_sources.add("oddsapi")

    existing_rows: List[Dict[str, str]] = []
    if merged_path.exists():
        try:
            with merged_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("source", "").strip().lower() not in stale_sources:
                        existing_rows.append(row)
        except Exception as e:
            print(f"[BP] Warning: could not read existing external priors: {e}", file=sys.stderr)

    all_rows = existing_rows + bp_rows

    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            # Ensure all fields present (non-BP rows won't have new columns)
            safe_row = {k: row.get(k, "") for k in CSV_FIELDS}
            writer.writerow(safe_row)
    print(f"[BP] Merged external priors: {len(existing_rows)} existing + {len(bp_rows)} bettingpros = {len(all_rows)} total -> {merged_path}")


def _archive_snapshot(bp_csv_path: Path, game_date: str, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"bettingpros_props_{game_date}.csv"
    dest = archive_dir / archive_name
    shutil.copy2(str(bp_csv_path), str(dest))
    print(f"[BP] Archived -> {dest}")


def _write_market_json(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"[BP] Market JSON -> {path}  ({len(rows)} entries)")


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
    market_json_path = Path(os.getenv("BETTINGPROS_MARKET_JSON_PATH", "").strip() or str(_default_market_json_path()))

    print(f"[BP] Fetching BettingPros NBA props for {game_date} ...")

    try:
        all_props = _fetch_all_props(timeout=timeout, max_pages=max_pages)
    except Exception as e:
        print(f"[BP] Fetch FAILED: {e}", file=sys.stderr)
        print("[BP] Clearing stale BettingPros/OddsAPI rows and continuing without BettingPros data (non-fatal).")
        _merge_into_external_priors([], merged_path)
        _write_market_json([], market_json_path)
        return 0  # non-fatal: model can run without external priors

    if not all_props:
        print("[BP] No props returned (0 items). Skipping.")
        _merge_into_external_priors([], merged_path)
        _write_market_json([], market_json_path)
        return 0

    asof_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = _props_to_csv_rows(all_props, asof_ts)
    print(f"[BP] Converted {len(all_props)} raw props -> {len(rows)} unique CSV rows")

    if not rows:
        print("[BP] 0 usable rows after conversion. Skipping.")
        _merge_into_external_priors([], merged_path)
        _write_market_json([], market_json_path)
        return 0

    # Write the market odds package consumed by the website/API payload. This
    # replaces the old OddsAPI-only source and keeps the downstream contract.
    market_rows: List[Dict[str, Any]] = []
    try:
        market_rows = _fetch_market_rows(timeout=timeout, max_pages=max_pages)
        _write_market_json(market_rows, market_json_path)
    except Exception as e:
        print(f"[BP] Market JSON fetch failed: {e}", file=sys.stderr)
        _write_market_json([], market_json_path)

    market_prior_rows = _market_rows_to_external_prior_rows(market_rows, asof_ts)
    if market_prior_rows:
        print(f"[BP] Converted {len(market_prior_rows)} exact market rows into external priors")
    all_prior_rows = rows + market_prior_rows

    # Write standalone BP CSV
    _write_bp_csv(all_prior_rows, out_path)

    # Merge into external_priors_today.csv
    _merge_into_external_priors(all_prior_rows, merged_path)

    # Archive for replay
    _archive_snapshot(out_path, game_date, archive_dir)

    # Write summary
    stat_counts = {}
    for r in all_prior_rows:
        stat_counts[r["stat"]] = stat_counts.get(r["stat"], 0) + 1
    print(f"[BP] Stats breakdown: {dict(sorted(stat_counts.items()))}")
    print(f"[BP] Done. {len(all_prior_rows)} props ready for external priors.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

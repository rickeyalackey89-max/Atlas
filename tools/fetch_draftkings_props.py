#!/usr/bin/env python3
"""
Fetch direct DraftKings NBA milestone props and merge exact threshold rows into
external_priors_today.csv.

DraftKings NBA exposes many player props as one-sided milestone ladders
(`10+ points`, `8+ rebounds`, etc.), not a full two-sided O/U board. Those rows
are still useful when they exactly match a PrizePicks threshold:

  DK 10+ PTS -> PP over 9.5 PTS

This tool only writes exact over-probability rows. It deliberately does not
invent under probabilities or projection anchors from milestone thresholds.

ENV:
  DRAFTKINGS_GAME_DATE       YYYY-MM-DD slate date; defaults to ATLAS_GAME_DATE/today
  DRAFTKINGS_SITE            default US-MO-SB
  DRAFTKINGS_TIMEOUT_S       default 20
  DRAFTKINGS_OUT_PATH        default data/input/draftkings_props_today.csv
  DRAFTKINGS_ARCHIVE_DIR     default data/archives/draftkings
  DRAFTKINGS_MARKET_JSON_PATH default data/input/odds_market_today.json
  DRAFTKINGS_MERGED_PATH     default data/input/external_priors_today.csv
  DRAFTKINGS_DEBUG_DIR       optional raw response dump directory
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests


DRAFTKINGS_SITE = "US-MO-SB"
DRAFTKINGS_EVENT_GROUP_ID = "42648"
DRAFTKINGS_URL = (
    "https://sportsbook-nash.draftkings.com/sites/{site}/api/sportscontent/"
    "controldata/league/leagueSubcategory/v1/markets"
)

DRAFTKINGS_SUBCATEGORIES: Dict[str, str] = {
    "PTS": "16477",
    "FG3M": "16480",
    "REB": "16479",
    "AST": "16478",
    "PRA": "16483",
}

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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_out_path() -> Path:
    return _repo_root() / "data" / "input" / "draftkings_props_today.csv"


def _default_merged_path() -> Path:
    return _repo_root() / "data" / "input" / "external_priors_today.csv"


def _default_archive_dir() -> Path:
    return _repo_root() / "data" / "archives" / "draftkings"


def _default_market_json_path() -> Path:
    return _repo_root() / "data" / "input" / "odds_market_today.json"


def _debug_dir() -> Optional[Path]:
    raw = os.getenv("DRAFTKINGS_DEBUG_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://sportsbook.draftkings.com",
        "Referer": "https://sportsbook.draftkings.com/leagues/basketball/nba?category=player-props",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
        "x-client-feature": "league-page",
        "x-client-name": "web",
    }


def _subcategory_url(*, site: str, subcategory_id: str) -> str:
    base = DRAFTKINGS_URL.format(site=site)
    params = {
        "isBatchable": "false",
        "templateVars": DRAFTKINGS_EVENT_GROUP_ID,
        "eventsQuery": (
            f"$filter=leagueId eq '{DRAFTKINGS_EVENT_GROUP_ID}' "
            f"AND clientMetadata/Subcategories/any(s: s/Id eq '{subcategory_id}')"
        ),
        "marketsQuery": (
            f"$filter=clientMetadata/subCategoryId eq '{subcategory_id}' "
            "AND tags/all(t: t ne 'SportcastBetBuilder')"
        ),
        "include": "Events",
        "entity": "events",
    }
    query = urlencode(params, safe="$',() /:")
    return f"{base}?{query}"


def _get_json(url: str, *, timeout: int) -> dict[str, Any]:
    resp = requests.get(url, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def _norm_name(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").strip().lower()


def _american_to_implied(price: int | float) -> float:
    value = float(price)
    if value >= 100:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def _american_odds(selection: dict[str, Any]) -> Optional[int]:
    display = selection.get("displayOdds") if isinstance(selection.get("displayOdds"), dict) else {}
    raw = str(display.get("american") or "").replace("\u2212", "-").replace("+", "").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _selection_player(selection: dict[str, Any]) -> dict[str, Any]:
    participants = selection.get("participants") if isinstance(selection.get("participants"), list) else []
    for participant in participants:
        if isinstance(participant, dict) and str(participant.get("type") or "").lower() == "player":
            return participant
    return participants[0] if participants and isinstance(participants[0], dict) else {}


def _milestone_line(selection: dict[str, Any]) -> Optional[float]:
    value = selection.get("milestoneValue")
    if value is None:
        label = str(selection.get("label") or "")
        if label.endswith("+"):
            value = label[:-1]
    try:
        return max(0.0, float(value) - 0.5)
    except (TypeError, ValueError):
        return None


def _local_slate_date(start_event_date: str) -> str:
    if not start_event_date:
        return ""
    raw = start_event_date.replace("Z", "+00:00")
    raw = re.sub(r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r"\1", raw)
    try:
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    except Exception:
        return start_event_date[:10]


def _team_label(participant: dict[str, Any]) -> str:
    metadata = participant.get("metadata") if isinstance(participant.get("metadata"), dict) else {}
    return str(metadata.get("shortName") or participant.get("name") or "")


def _event_matchup(event: dict[str, Any]) -> tuple[str, str]:
    home = ""
    away = ""
    for participant in event.get("participants", []) or []:
        if not isinstance(participant, dict):
            continue
        role = str(participant.get("venueRole") or "").lower()
        if role == "home":
            home = _team_label(participant)
        elif role == "away":
            away = _team_label(participant)
    return home, away


def _fetch_rows(*, game_date: str, site: str, timeout: int) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    market_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    asof_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    debug_path = _debug_dir()

    for stat, subcategory_id in DRAFTKINGS_SUBCATEGORIES.items():
        url = _subcategory_url(site=site, subcategory_id=subcategory_id)
        payload = _get_json(url, timeout=timeout)
        if debug_path is not None:
            (debug_path / f"draftkings_{stat.lower()}_{subcategory_id}.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )

        events_by_id = {
            str(event.get("id") or ""): event
            for event in payload.get("events", []) or []
            if isinstance(event, dict)
        }
        markets_by_id = {
            str(market.get("id") or ""): market
            for market in payload.get("markets", []) or []
            if isinstance(market, dict)
        }

        added = 0
        skipped_date = 0
        for selection in payload.get("selections", []) or []:
            if not isinstance(selection, dict):
                continue
            market_id = str(selection.get("marketId") or "")
            market = markets_by_id.get(market_id, {})
            event = events_by_id.get(str(market.get("eventId") or ""), {})
            start_time = str(event.get("startEventDate") or "")
            slate_date = _local_slate_date(start_time)
            if game_date and slate_date and slate_date != game_date:
                skipped_date += 1
                continue

            player = _selection_player(selection)
            player_name = str(player.get("name") or player.get("seoIdentifier") or "").strip()
            line = _milestone_line(selection)
            odds = _american_odds(selection)
            if not player_name or line is None or odds is None:
                continue

            key = (_norm_name(player_name), stat, round(line, 4))
            if key in seen:
                continue
            seen.add(key)

            over_prob = round(_american_to_implied(odds), 4)
            home_team, away_team = _event_matchup(event)
            source_market = str(market.get("name") or f"{player_name} {stat}")
            notes = (
                "type=dk_direct_milestone; side=over_only; "
                f"label={selection.get('label')}; odds={odds}; "
                f"subcategory={subcategory_id}; event={away_team}@{home_team}; "
                "no_under_probability_invented"
            )

            rows.append(
                {
                    "source": "draftkings_direct_market",
                    "league": "NBA",
                    "player": player_name,
                    "stat": stat,
                    "line": str(line),
                    "asof_ts": asof_ts,
                    "projection": str(line),
                    "confidence": "0.55",
                    "over_prob": str(over_prob),
                    "under_prob": "",
                    "over_rating": "",
                    "under_rating": "",
                    "opp_rank": "",
                    "notes": notes,
                }
            )
            market_rows.append(
                {
                    "player": player_name,
                    "player_norm": _norm_name(player_name),
                    "stat": stat,
                    "line": line,
                    "dk_over": odds,
                    "dk_under": None,
                    "fd_over": None,
                    "fd_under": None,
                    "dk_imp_over": over_prob,
                    "fd_imp_over": None,
                    "source": "draftkings_direct",
                    "source_market": source_market,
                    "slate_date": slate_date,
                    "start_time": start_time,
                }
            )
            added += 1
        print(
            f"[DK] {stat}: events={len(events_by_id)} markets={len(markets_by_id)} "
            f"rows={added} skipped_other_date={skipped_date}"
        )

    return rows, market_rows


def _write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    print(f"[DK] Wrote {len(rows)} rows -> {path}")


def _merge_into_external_priors(rows: list[dict[str, str]], merged_path: Path) -> None:
    stale_sources = {"draftkings_direct_market"}
    existing: list[dict[str, str]] = []
    if merged_path.exists():
        try:
            with merged_path.open("r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if str(row.get("source") or "").strip().lower() not in stale_sources:
                        existing.append(row)
        except Exception as e:
            print(f"[DK] Warning: could not read existing external priors: {e}", file=sys.stderr)

    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in existing + rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    print(
        f"[DK] Merged external priors: {len(existing)} existing + {len(rows)} "
        f"draftkings = {len(existing) + len(rows)} total -> {merged_path}"
    )


def _market_key(row: dict[str, Any]) -> tuple[str, str, float]:
    try:
        line = round(float(row.get("line")), 4)
    except (TypeError, ValueError):
        line = -9999.0
    return (str(row.get("player_norm") or _norm_name(str(row.get("player") or ""))), str(row.get("stat") or ""), line)


def _merge_market_json(dk_rows: Iterable[dict[str, Any]], path: Path) -> None:
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [row for row in loaded if isinstance(row, dict)]
        except Exception as e:
            print(f"[DK] Warning: could not read odds market JSON: {e}", file=sys.stderr)

    merged: dict[tuple[str, str, float], dict[str, Any]] = {}
    for row in existing:
        merged[_market_key(row)] = row

    added = 0
    updated = 0
    for row in dk_rows:
        key = _market_key(row)
        target = merged.get(key)
        if target is None:
            merged[key] = {
                "player": row.get("player"),
                "player_norm": row.get("player_norm"),
                "stat": row.get("stat"),
                "line": row.get("line"),
                "dk_over": row.get("dk_over"),
                "dk_under": row.get("dk_under"),
                "fd_over": row.get("fd_over"),
                "fd_under": row.get("fd_under"),
                "dk_imp_over": row.get("dk_imp_over"),
                "fd_imp_over": row.get("fd_imp_over"),
                "dk_direct_source": True,
            }
            added += 1
            continue
        if target.get("dk_over") in (None, ""):
            target["dk_over"] = row.get("dk_over")
            target["dk_imp_over"] = row.get("dk_imp_over")
            target["dk_direct_source"] = True
            updated += 1

    out = sorted(merged.values(), key=lambda r: (str(r.get("player_norm") or ""), str(r.get("stat") or ""), float(r.get("line") or 0)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[DK] Market JSON merged -> {path}  existing={len(existing)} added={added} updated={updated} total={len(out)}")


def _archive_snapshot(csv_path: Path, game_date: str, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"draftkings_props_{game_date}.csv"
    shutil.copy2(str(csv_path), str(dest))
    print(f"[DK] Archived -> {dest}")


def main() -> int:
    game_date = (
        os.getenv("DRAFTKINGS_GAME_DATE")
        or os.getenv("ATLAS_GAME_DATE")
        or datetime.now().strftime("%Y-%m-%d")
    ).strip()
    site = os.getenv("DRAFTKINGS_SITE", DRAFTKINGS_SITE).strip() or DRAFTKINGS_SITE
    timeout = int(os.getenv("DRAFTKINGS_TIMEOUT_S", "20"))
    out_path = Path(os.getenv("DRAFTKINGS_OUT_PATH", "").strip() or str(_default_out_path()))
    merged_path = Path(os.getenv("DRAFTKINGS_MERGED_PATH", "").strip() or str(_default_merged_path()))
    archive_dir = Path(os.getenv("DRAFTKINGS_ARCHIVE_DIR", "").strip() or str(_default_archive_dir()))
    market_json_path = Path(os.getenv("DRAFTKINGS_MARKET_JSON_PATH", "").strip() or str(_default_market_json_path()))

    print(f"[DK] Fetching DraftKings NBA milestone props for {game_date} site={site} ...")
    try:
        rows, market_rows = _fetch_rows(game_date=game_date, site=site, timeout=timeout)
    except Exception as e:
        print(f"[DK] Fetch FAILED: {e}", file=sys.stderr)
        print("[DK] Clearing stale DraftKings direct rows and continuing without direct DK data (non-fatal).")
        _merge_into_external_priors([], merged_path)
        return 0

    _write_csv(rows, out_path)
    _merge_into_external_priors(rows, merged_path)
    _merge_market_json(market_rows, market_json_path)
    _archive_snapshot(out_path, game_date, archive_dir)

    stat_counts: dict[str, int] = {}
    for row in rows:
        stat_counts[row["stat"]] = stat_counts.get(row["stat"], 0) + 1
    print(f"[DK] Stats breakdown: {dict(sorted(stat_counts.items()))}")
    print(f"[DK] Done. {len(rows)} direct DK milestone rows ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

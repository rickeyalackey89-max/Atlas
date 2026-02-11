#!/usr/bin/env python3
from __future__ import annotations

"""PrizePicks board snapshotter (schema-robust, read-only).

Fixes:
- Resolves player names via relationships -> included (new_player)
- Supports combo markets (PRA / PA / PR / RA)
- Never silently writes 0 rows; prints debug stats if it would
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
PROJECT_ROOT = find_repo_root(Path(__file__))
LEAGUE_ID_NBA = 7

STAT_MAP = {
    "Points": "PTS",
    "Rebounds": "REB",
    "Assists": "AST",
    "Steals": "STL",
    "Blocks": "BLK",
    "3-PT Made": "FG3M",
    "3-Pointers Made": "FG3M",
    "Pts+Asts": "PA",
    "Pts+Ast": "PA",
    "Points+Assists": "PA",
    "Points + Assists": "PA",
    "Pts+Rebs": "PR",
    "Pts+Reb": "PR",
    "Points+Rebounds": "PR",
    "Points + Rebounds": "PR",
    "Rebs+Asts": "RA",
    "Reb+Ast": "RA",
    "Rebounds+Assists": "RA",
    "Rebounds + Assists": "RA",
    "Pts+Rebs+Asts": "PRA",
    "PRA": "PRA",
    "Points+Rebounds+Assists": "PRA",
    "Points + Rebounds + Assists": "PRA",
}

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://app.prizepicks.com/",
    "User-Agent": "Mozilla/5.0",
}

def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _api_url(league_id: int, per_page: int, single_stat: bool, in_game: bool, state_code: str, game_mode: str) -> str:
    return (
        "https://api.prizepicks.com/projections"
        f"?league_id={league_id}"
        f"&per_page={per_page}"
        f"&single_stat={'true' if single_stat else 'false'}"
        f"&in_game={'true' if in_game else 'false'}"
        f"&state_code={state_code}"
        f"&game_mode={game_mode}"
    )

def _fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def _build_player_map(included: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {}
    for obj in included or []:
        if obj.get("type") == "new_player":
            pid = str(obj.get("id"))
            name = (obj.get("attributes") or {}).get("name")
            if pid and name:
                out[pid] = name
    return out

def _is_combo_player(name: str) -> bool:
    return " + " in (name or "")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league_id", type=int, default=LEAGUE_ID_NBA)
    ap.add_argument("--state", default="MO")
    ap.add_argument("--per_page", type=int, default=250)
    ap.add_argument("--single_stat", action="store_true")
    ap.add_argument("--in_game", action="store_true")
    ap.add_argument("--game_mode", default="prizepools")
    ap.add_argument("--write_latest", action="store_true")
    args = ap.parse_args()

    url = _api_url(
        args.league_id,
        args.per_page,
        args.single_stat,
        args.in_game,
        args.state,
        args.game_mode,
    )

    payload = _fetch_json(url)
    included = payload.get("included") or []
    player_map = _build_player_map(included)

    rows = []
    dropped_combo_players = 0
    dropped_unknown = 0

    for item in payload.get("data") or []:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes") or {}
        rel = item.get("relationships") or {}
        pid_rel = (((rel.get("new_player") or {}).get("data") or {}).get("id"))
        player = player_map.get(str(pid_rel), "")

        if not player:
            continue
        if _is_combo_player(player):
            dropped_combo_players += 1
            continue

        stat_name = attr.get("stat_type") or attr.get("stat_display_name") or ""
        stat = STAT_MAP.get(stat_name) or STAT_MAP.get(stat_name.replace(" ", ""))
        if not stat:
            dropped_unknown += 1
            continue

        line = attr.get("line_score") or attr.get("line")
        try:
            line = float(line)
        except Exception:
            continue

        tier = (attr.get("odds_type") or "").upper()
        start_time = attr.get("start_time") or ""

        rows.append({
            "projection_id": item.get("id"),
            "player": player,
            "stat": stat,
            "line": line,
            "tier": tier,
            "start_time": start_time,
            "more_allowed": attr.get("more_allowed"),
            "less_allowed": attr.get("less_allowed"),
        })

    df = pd.DataFrame(rows)

    tag = _now_tag()
    raw_dir = PROJECT_ROOT / "data" / "raw"
    snap_dir = PROJECT_ROOT / "data" / "board" / "snapshots"
    raw_dir.mkdir(parents=True, exist_ok=True)
    snap_dir.mkdir(parents=True, exist_ok=True)

    (raw_dir / f"prizepicks_snapshot_{tag}.json").write_text(json.dumps(payload), encoding="utf-8")
    out_csv = snap_dir / f"board_{tag}.csv"
    df.to_csv(out_csv, index=False)

    if args.write_latest:
        (PROJECT_ROOT / "data" / "board" / "today.csv").to_csv(index=False)

    print(f"Wrote snapshot: {out_csv} (rows={len(df)})")
    print(f"Dropped combo players (A+B): {dropped_combo_players}")
    print(f"Dropped unknown stats: {dropped_unknown}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())


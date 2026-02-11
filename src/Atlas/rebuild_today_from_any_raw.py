from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import Any

import pandas as pd


# File path: <repo>/src/Atlas/rebuild_today_from_any_raw.py
# parents[0] -> <repo>/src/Atlas
# parents[1] -> <repo>/src
# parents[2] -> <repo>   ✅
PROJECT_ROOT = find_repo_root(Path(__file__))
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_PATH = PROJECT_ROOT / "data" / "board" / "today.csv"

# Canonical stats used by the model
SUPPORTED_STATS = {
    "PTS",
    "REB",
    "AST",
    "FG3M",
    "PR",   # Pts+Rebs
    "PA",   # Pts+Asts
    "RA",   # Rebs+Asts
    "PRA",  # Pts+Rebs+Asts
}

# Map PrizePicks stat labels -> canonical codes
STAT_MAP = {
    "POINTS": "PTS",
    "PTS": "PTS",
    "REBOUNDS": "REB",
    "REBS": "REB",
    "REB": "REB",
    "ASSISTS": "AST",
    "ASTS": "AST",
    "AST": "AST",
    "3-PT MADE": "FG3M",
    "3-POINTERS MADE": "FG3M",
    "3PM": "FG3M",
    "FG3M": "FG3M",
    "PTS+REBS": "PR",
    "PTS+ASTS": "PA",
    "REBS+ASTS": "RA",
    "PTS+REBS+ASTS": "PRA",
    "BLKS+STLS": "BS",
}

# Map odds_type -> tier used elsewhere in the project
ODDS_TYPE_TO_TIER = {
    "standard": "STANDARD",
    "goblin": "GOBLIN",
    "demon": "DEMON",
}


def _clean_str(x: Any) -> str:
    return "" if x is None else str(x).strip()


def _parse_iso_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s2 = str(s).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _is_combo_player_name(name: str) -> bool:
    """
    Detect multi-player combo props like:
    - "A + B"
    - "A & B"
    - "A / B"
    These are NEVER allowed in Atlas.
    """
    n = _clean_str(name)
    if not n:
        return False

    for sep in [" + ", " & ", " / "]:
        if sep in n:
            return True

    if re.search(r"[A-Za-z]\s*[\+&/]\s*[A-Za-z]", n):
        return True

    return False


def _norm_stat(raw: Any) -> str:
    s = _clean_str(raw).upper()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return STAT_MAP.get(s, "")


def _load_latest_raw() -> Path:
    """
    Atlas 2.0 rule:
    1) Prefer prizepicks_*.json (live fetches)
    2) Choose newest by filesystem mtime
    3) Fall back to prizepicks_snapshot_*.json only if no prizepicks_*.json exist
    """
    live = sorted(RAW_DIR.glob("prizepicks_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if live:
        return live[0]

    snaps = sorted(RAW_DIR.glob("prizepicks_snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if snaps:
        return snaps[0]

    raise FileNotFoundError(f"No PrizePicks raw JSON files found in {RAW_DIR}")


def _build_player_map(payload: dict) -> dict[str, dict[str, str]]:
    """
    Build {player_id: {"name":..., "team":...}} from `included`.
    """
    mp: dict[str, dict[str, str]] = {}
    for inc in payload.get("included", []) or []:
        if inc.get("type") not in ("new_player", "player"):
            continue
        pid = _clean_str(inc.get("id"))
        attr = inc.get("attributes", {}) or {}
        name = _clean_str(attr.get("name"))
        team = _clean_str(attr.get("team"))
        if pid:
            mp[pid] = {"name": name, "team": team}
    return mp


def _get_player_id(item: dict) -> str:
    rel = item.get("relationships", {}) or {}
    return _clean_str(
        (((rel.get("new_player") or {}).get("data") or {}).get("id"))
        or (((rel.get("player") or {}).get("data") or {}).get("id"))
    )


def _pick_main_line(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep one line per (player, stat, tier). Prefer:
    - non-alternate (alt_line False)
    - is_main True
    - most recently updated
    - stable tiebreaker by projection_id
    Never return empty.
    """
    if df.empty:
        return df

    sort_cols: list[str] = []
    ascending: list[bool] = []

    for col, asc in [
        ("alt_line", True),      # False first
        ("is_main", False),      # True first
        ("updated_at", False),   # newest first
        ("projection_id", True),
    ]:
        if col in df.columns:
            sort_cols.append(col)
            ascending.append(asc)

    df2 = df.sort_values(sort_cols, ascending=ascending, kind="mergesort")
    out = df2.drop_duplicates(subset=["player", "stat", "tier"], keep="first").copy()
    if out.empty:
        return df2.head(1).copy()
    return out


def main() -> None:
    raw_path = _load_latest_raw()
    payload = json.loads(raw_path.read_text(encoding="utf-8"))

    players = _build_player_map(payload)
    now_utc = datetime.now(timezone.utc)

    dropped_unknown_stat = 0
    dropped_combo_players = 0
    dropped_started_games = 0
    dropped_missing_player = 0
    dropped_bad_rows = 0

    base_rows: list[dict[str, Any]] = []

    for item in payload.get("data", []) or []:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes", {}) or {}

        proj_id = _clean_str(item.get("id"))
        player_id = _get_player_id(item)

        p = players.get(player_id, {}) if player_id else {}
        player_name = _clean_str(p.get("name"))
        team = _clean_str(p.get("team"))

        if not player_name:
            player_name = _clean_str(attr.get("description") or attr.get("player_name") or attr.get("name"))

        if not player_name:
            dropped_missing_player += 1
            continue

        if _is_combo_player_name(player_name):
            dropped_combo_players += 1
            continue

        stat = _norm_stat(attr.get("stat_type") or attr.get("stat_type_display") or attr.get("stat_display_name"))
        if not stat or stat not in SUPPORTED_STATS:
            dropped_unknown_stat += 1
            continue

        start_dt = _parse_iso_datetime(_clean_str(attr.get("start_time")))
        if start_dt is not None and start_dt < now_utc:
            dropped_started_games += 1
            continue

        line = attr.get("line_score")
        if line is None:
            line = attr.get("flash_sale_line_score")

        if line is None:
            dropped_bad_rows += 1
            continue

        odds_type = _clean_str(attr.get("odds_type")).lower()
        tier = ODDS_TYPE_TO_TIER.get(odds_type, "STANDARD")

        updated_dt = _parse_iso_datetime(_clean_str(attr.get("updated_at")))
        updated_at = updated_dt.isoformat() if updated_dt else _clean_str(attr.get("updated_at"))

        alt_line = bool(attr.get("is_alternate") or attr.get("alt_line") or attr.get("is_alternate_line") or False)
        is_main = bool(attr.get("is_main") or attr.get("isMain") or False)

        base_rows.append(
            {
                "projection_id": proj_id,
                "player": player_name,
                "stat": stat,
                "line": line,
                "tier": tier,
                "team": team,
                "start_time": _clean_str(attr.get("start_time")),
                "updated_at": updated_at,
                "alt_line": int(alt_line),
                "is_main": int(is_main),
                "odds_type": odds_type,
            }
        )

    base = pd.DataFrame(base_rows)
    if base.empty:
        raise RuntimeError(f"Rebuild parsed zero usable rows from {raw_path.name}")

    base["line"] = pd.to_numeric(base["line"], errors="coerce")
    base = base.dropna(subset=["line"]).copy()

    before = len(base)
    base = _pick_main_line(base)
    dropped_alt_lines = before - len(base)

    base["main_line"] = base["line"]

    # Atlas 2.0 baseline playability (per-row intent):
    # - STANDARD: OVER + UNDER allowed
    # - GOBLIN/DEMON: OVER only
    expanded_rows: list[dict[str, Any]] = []
    for d in base.to_dict("records"):
        tier = _clean_str(d.get("tier"))

        # OVER row always present
        r = dict(d)
        r["direction"] = "OVER"
        r["more_allowed"] = 1
        r["less_allowed"] = 0
        expanded_rows.append(r)

        # UNDER row only for STANDARD
        if tier == "STANDARD":
            r = dict(d)
            r["direction"] = "UNDER"
            r["more_allowed"] = 0
            r["less_allowed"] = 1
            expanded_rows.append(r)

    out = pd.DataFrame(expanded_rows)
    if out.empty:
        raise RuntimeError("Rebuild produced zero rows after expanding directions")

    cols = [
        "projection_id",
        "player",
        "stat",
        "line",
        "direction",
        "tier",
        "more_allowed",
        "less_allowed",
        "main_line",
        "start_time",
        "updated_at",
        "alt_line",
        "is_main",
        "odds_type",
        "team",
    ]
    out = out[[c for c in cols if c in out.columns]].copy()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)

    print(f"Rebuilt today.csv from: {raw_path}")
    print(f"Rows: {len(out)}")
    print("Stat counts:")
    print(out["stat"].value_counts())
    print(f"Dropped unsupported/unknown stat: {dropped_unknown_stat}")
    print(f"Dropped combo players (multi-player props): {dropped_combo_players}")
    print(f"Dropped missing player: {dropped_missing_player}")
    print(f"Dropped games already started: {dropped_started_games}")
    print(f"Dropped blank player/stat/line rows (guard): {dropped_bad_rows}")
    print(f"Dropped alt lines (kept 1 main line per player+stat+tier): {dropped_alt_lines}")


if __name__ == "__main__":
    main()

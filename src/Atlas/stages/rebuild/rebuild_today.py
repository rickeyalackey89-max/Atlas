from __future__ import annotations

"""
Atlas Stage: Rebuild

Phase 6: stage-owned deterministic rebuild logic extracted from
src/Atlas/rebuild_today_from_any_raw.py.

Contract:
- No argparse
- No environment reads
- No file I/O
- No printing
"""

import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import pandas as pd

from Atlas.core.share_name_key import share_name_key



def _player_key(x: str) -> str:
    """Canonical player key used for joins across IAEL / gamelogs / share_matrix.
    Mirrors team_share_reallocator._player_key behavior (lowercased, stripped, basic suffix cleanup).
    """
    return share_name_key(x)


# =========================
# Stat normalization (copied to preserve behavior)
# =========================

CANONICAL_STATS = {
    # Singles
    "PTS",
    "REB",
    "AST",
    "BLK",
    "STL",
    "TOV",
    "FG3M",   # 3PT made
    "FGM",
    "FGA",
    "FTM",
    "FTA",
    # Combos
    "PR",     # Pts+Rebs
    "PA",     # Pts+Asts
    "RA",     # Rebs+Asts
    "PRA",    # Pts+Rebs+Asts
    "BS",     # Blks+Stls
}

STAT_MAP: dict[str, str] = {
    # Points
    "POINTS": "PTS",
    "PTS": "PTS",

    # Rebounds
    "REBOUNDS": "REB",
    "REBS": "REB",
    "REB": "REB",

    # Assists
    "ASSISTS": "AST",
    "ASTS": "AST",
    "AST": "AST",

    # 3PT Made
    "3-PT MADE": "FG3M",
    "3-POINTERS MADE": "FG3M",
    "3PM": "FG3M",
    "3PTM": "FG3M",
    "FG3M": "FG3M",

    # Steals / Blocks / Turnovers
    "STEALS": "STL",
    "STLS": "STL",
    "STL": "STL",
    "BLOCKS": "BLK",
    "BLKS": "BLK",
    "BLK": "BLK",
    "TURNOVERS": "TOV",
    "TOS": "TOV",
    "TOV": "TOV",

    # Combos
    "PTS+REBS": "PR",
    "POINTS+REBOUNDS": "PR",

    "PTS+ASTS": "PA",
    "POINTS+ASSISTS": "PA",

    "REBS+ASTS": "RA",
    "REBOUNDS+ASSISTS": "RA",

    "PTS+REBS+ASTS": "PRA",
    "POINTS+REBOUNDS+ASSISTS": "PRA",

    "BLKS+STLS": "BS",
    "BLOCKS+STEALS": "BS",
}

ODDS_TYPE_TO_TIER = {
    "standard": "STANDARD",
    "goblin": "GOBLIN",
    "demon": "DEMON",
}


# =========================
# Helpers (copied to preserve behavior)
# =========================

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
    Detect multi-player combo props like "A + B", "A & B", "A / B".
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

def _norm_stat(raw: Any) -> tuple[str, str, int]:
    """
    Returns (stat_canon, stat_raw_clean, is_canonical)
    """
    s = _clean_str(raw).upper()
    if not s:
        return "", "", 0

    s = re.sub(r"\s+", " ", s).strip()
    canon = STAT_MAP.get(s, s)

    is_canon = 1 if canon in CANONICAL_STATS else 0
    return canon, s, is_canon

def _build_player_map(payload: dict) -> dict[str, dict[str, str]]:
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



def _build_game_map(payload: dict) -> dict[str, dict[str, Any]]:
    gm: dict[str, dict[str, Any]] = {}
    for inc in payload.get("included", []) or []:
        if inc.get("type") != "game":
            continue
        gid = _clean_str(inc.get("id"))
        attr = inc.get("attributes", {}) or {}
        if gid:
            gm[gid] = attr
    return gm

def _get_game_id(item: dict) -> str:
    rel = item.get("relationships", {}) or {}
    return _clean_str((((rel.get("game") or {}).get("data") or {}).get("id")))
def _get_player_id(item: dict) -> str:
    rel = item.get("relationships", {}) or {}
    return _clean_str(
        (((rel.get("new_player") or {}).get("data") or {}).get("id"))
        or (((rel.get("player") or {}).get("data") or {}).get("id"))
    )

def _dedupe_exact_props(base: pd.DataFrame) -> pd.DataFrame:
    """
    Only remove true duplicates where identity is the same:
      player + stat + tier + line + odds_type + start_time
    Prefer newest updated_at, then stable by source_projection_id.
    """
    if base.empty:
        return base

    df = base.copy()

    # Sort: newest first
    sort_cols: list[str] = []
    ascending: list[bool] = []
    for col, asc in [("updated_at", False), ("source_projection_id", True)]:
        if col in df.columns:
            sort_cols.append(col)
            ascending.append(asc)

    if sort_cols:
        df = df.sort_values(sort_cols, ascending=ascending, kind="mergesort")

    subset = [c for c in ["player", "stat", "tier", "line", "odds_type", "start_time"] if c in df.columns]
    if not subset:
        return df

    return df.drop_duplicates(subset=subset, keep="first").copy()

def _make_projection_id(source_projection_id: str, player: str, stat: str, tier: str, line: float, direction: str) -> str:
    src = _clean_str(source_projection_id) or "no_src"
    ply = _clean_str(player).replace("|", " ")
    st = _clean_str(stat)
    tr = _clean_str(tier)
    dr = _clean_str(direction)
    ln = f"{float(line):g}"
    return f"{src}|{ply}|{st}|{tr}|{ln}|{dr}"


# =========================
# Stage Entry Point
# =========================

def run_rebuild(*, payload: dict[str, Any], is_replay: bool) -> pd.DataFrame:
    """
    Deterministic rebuild of today board from PrizePicks payload.

    Returns a DataFrame equivalent to what the legacy rebuild script writes to today.csv,
    but performs no IO and prints nothing.
    """

    players = _build_player_map(payload)
    games = _build_game_map(payload)
    now_utc = datetime.min.replace(tzinfo=timezone.utc) if is_replay else datetime.now(timezone.utc)

    TZ_CT = ZoneInfo("America/Chicago")

    now_utc = None
    now_ct = None
    today_ct = None
    if not is_replay:
        now_utc = datetime.now(timezone.utc)
        now_ct = now_utc.astimezone(TZ_CT)
        today_ct = now_ct.date()


    base_rows: list[dict[str, Any]] = []
    unknown_stat_rows = 0

    # dropped counters retained for wrapper to optionally print later;
    # stage returns data only (wrapper can recompute counters if needed later).
    for item in payload.get("data", []) or []:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes", {}) or {}

        source_proj_id = _clean_str(item.get("id"))
        player_id = _get_player_id(item)

        p = players.get(player_id, {}) if player_id else {}
        player_name = _clean_str(p.get("name"))
        team = _clean_str(p.get("team"))

        if not player_name:
            player_name = _clean_str(attr.get("description") or attr.get("player_name") or attr.get("name"))

        if not player_name:
            continue

        if _is_combo_player_name(player_name):
            continue

        stat_canon, stat_raw, is_canon = _norm_stat(
            attr.get("stat_type") or attr.get("stat_type_display") or attr.get("stat_display_name")
        )
        if not stat_canon:
            continue
        if not is_canon:
            unknown_stat_rows += 1  # retained for parity; not printed here

        # Strict slate gate for LIVE runs:
        #  - require resolvable game start_time (prefer included game.start_time)
        #  - keep only games that start today (CT) and have not started yet
        game_id = _get_game_id(item)
        start_iso = ""
        if game_id and game_id in games:
            start_iso = _clean_str((games.get(game_id) or {}).get("start_time"))
        if not start_iso:
            # fallback to projection attr if game relationship missing
            start_iso = _clean_str(attr.get("start_time"))

        start_dt = _parse_iso_datetime(start_iso)
        if start_dt is None:
            continue

        start_ct = start_dt.astimezone(TZ_CT)

        if not is_replay:
            if start_ct.date() != today_ct:
                continue
            if now_ct is not None and start_ct < now_ct:
                continue
        else:
            # Replay mode: rebuild the board represented by the raw payload.
            # Do not apply any "current time" filter here.
            pass


        # derive matchup context (required for team share + role_ctx joins)
        game_date = ""
        home = 0
        opp = ""
        game_date = start_ct.date().isoformat()

        if game_id and game_id in games:
            gi = games.get(game_id) or {}
            teams = (((gi.get("metadata") or {}).get("game_info") or {}).get("teams") or {})
            home_abbrev = _clean_str(((teams.get("home") or {}).get("abbreviation")))
            away_abbrev = _clean_str(((teams.get("away") or {}).get("abbreviation")))
            if home_abbrev and away_abbrev:
                if team == home_abbrev:
                    home = 1
                    opp = away_abbrev
                elif team == away_abbrev:
                    home = 0
                    opp = home_abbrev

        player_key = _player_key(player_name)

        line = attr.get("line_score") or attr.get("line") or 0.0
        odds_type_raw = _clean_str(attr.get("odds_type") or "")
        odds_type = ODDS_TYPE_TO_TIER.get(odds_type_raw.lower(), _clean_str(attr.get("tier") or ""))
        main_line = attr.get("main_line") if "main_line" in attr else None
        alt_line = attr.get("alt_line") if "alt_line" in attr else None
        is_main = 1 if attr.get("is_main") else 0
        updated_at = _parse_iso_datetime(_clean_str(attr.get("updated_at") or attr.get("updatedAt")))

        base_rows.append({
            "source_projection_id": source_proj_id,
            "game_id": game_id,
            "game_date": game_date,
            "home": int(home),
            "opp": opp,
            "player_key": player_key,
            "player": player_name,
            "team": team,
            "stat": stat_canon,
            "stat_raw": stat_raw,
            "stat_is_canonical": is_canon,
            "line": float(line) if line is not None else 0.0,
            "tier": odds_type or _clean_str(attr.get("tier") or ""),
            "main_line": main_line,
            "alt_line": alt_line,
            "is_main": is_main,
            "odds_type": odds_type_raw or "",
            "start_time": start_iso,
            "updated_at": updated_at,
        })

    base = pd.DataFrame(base_rows)
    expanded_rows: list[dict[str, Any]] = []
    for d in base.to_dict("records"):
        # ensure keys are strings (pandas records can be typed as dict[Hashable, Any])
        row: dict[str, Any] = {str(k): v for k, v in d.items()}
        tier = _clean_str(row.get("tier"))

        # OVER row always present
        r_over = row.copy()
        r_over["direction"] = "OVER"
        r_over["more_allowed"] = 1
        r_over["less_allowed"] = 0
        r_over["projection_id"] = _make_projection_id(
            r_over.get("source_projection_id", ""),
            r_over.get("player", ""),
            r_over.get("stat", ""),
            r_over.get("tier", ""),
            float(r_over.get("line", 0.0)),
            "OVER",
        )
        expanded_rows.append(r_over)

        # UNDER row only for STANDARD
        if tier == "STANDARD":
            r_under = row.copy()
            r_under["direction"] = "UNDER"
            r_under["more_allowed"] = 0
            r_under["less_allowed"] = 1
            r_under["projection_id"] = _make_projection_id(
                r_under.get("source_projection_id", ""),
                r_under.get("player", ""),
                r_under.get("stat", ""),
                r_under.get("tier", ""),
                float(r_under.get("line", 0.0)),
                "UNDER",
            )
            expanded_rows.append(r_under)

    out = pd.DataFrame(expanded_rows)
    if out.empty:
        raise RuntimeError("Rebuild produced zero rows after expanding directions")

    cols = [
        "projection_id",
        "source_projection_id",
        "game_id",
        "game_date",
        "home",
        "opp",
        "player_key",
        "player",
        "team",
        "stat",
        "stat_raw",
        "stat_is_canonical",
        "line",
        "direction",
        "tier",
        "more_allowed",
        "less_allowed",
        "main_line",
        "alt_line",
        "is_main",
        "odds_type",
        "start_time",
        "updated_at",
    ]
    out = out[[c for c in cols if c in out.columns]].copy()

    return out
from __future__ import annotations
from zoneinfo import ZoneInfo

"""
Atlas Stage: Fetch

Phase 6: stage-owned deterministic logic extracted from tools/fetch_apis.py.

Contract:
- No argparse
- No environment reads
- No HTTP calls
- No file I/O
- No printing
"""

import re
from datetime import date, datetime, timezone
from typing import Any, Optional

import pandas as pd

SUPPORTED_STATS = {
    "PTS", "REB", "AST", "FG3M",
    "PR", "PA", "RA", "PRA",
}


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _clean_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x).strip()
    except Exception:
        return ""

def _parse_iso_datetime(s: Any) -> Optional[datetime]:
    s2 = _clean_str(s).replace("Z", "+00:00")
    if not s2:
        return None
    try:
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def _resolve_replay_now(payload: dict[str, Any]) -> datetime:
    updated_candidates: list[datetime] = []
    start_candidates: list[datetime] = []

    for item in payload.get("data", []) or []:
        attr = item.get("attributes", {}) or {}

        updated_at = _parse_iso_datetime(attr.get("updated_at"))
        if updated_at is not None:
            updated_candidates.append(updated_at)

        start_time = _parse_iso_datetime(attr.get("start_time"))
        if start_time is not None:
            start_candidates.append(start_time)

    if updated_candidates:
        return max(updated_candidates)

    if start_candidates:
        return min(start_candidates)

    return datetime.now(timezone.utc)

def _infer_tag(odds_type: Any) -> str:
    t = _clean_str(odds_type).upper()
    if "GOBLIN" in t:
        return "GOBLIN"
    if "DEMON" in t:
        return "DEMON"
    return ""

def _is_combo_player_name(name: str) -> bool:
    n = _clean_str(name)
    if not n:
        return False
    # "A + B", "A & B", "A / B"
    return bool(re.search(r"[A-Za-z]\s*[\+&/]\s*[A-Za-z]", n))

def _is_combo_team(team: str) -> bool:
    t = _clean_str(team)
    return ("/" in t) if t else False

def _norm_stat(stat_raw: Any) -> str:
    s = _clean_str(stat_raw)
    s2 = s.replace(" ", "")

    mapping = {
        "Points": "PTS", "Pts": "PTS",
        "Rebounds": "REB", "Rebs": "REB",
        "Assists": "AST", "Asts": "AST",
        "3PTMade": "FG3M", "3PTM": "FG3M",

        "Pts+Rebs": "PR", "Pts+Asts": "PA",
        "Rebs+Asts": "RA", "Pts+Rebs+Asts": "PRA",

        "PRA": "PRA", "PR": "PR", "PA": "PA", "RA": "RA",
    }

    return mapping.get(s) or mapping.get(s2) or ""


# ---------------------------------------------------------------
# Stage Entry Point
# ---------------------------------------------------------------

def run_fetch(*, payload: dict[str, Any], is_replay: bool) -> pd.DataFrame:
    """
    Deterministic transformation of PrizePicks payload into the board dataframe.

    Input:
      - payload: raw JSON dict as returned by PrizePicks endpoint or replay file
      - is_replay: True if loaded from disk/env (replay), False if live

    Output:
      - Empty DataFrame if no qualifying projections
      - Otherwise expanded DataFrame with direction in {"OVER","UNDER"}
    """
    data = payload.get("data", []) or []
    included = payload.get("included", []) or []

    # Build included maps we can join against.
    players_by_id: dict[str, dict[str, Any]] = {}
    games_by_id: dict[str, dict[str, Any]] = {}

    for inc in included:
        itype = inc.get("type")
        iid = _clean_str(inc.get("id"))
        attr = inc.get("attributes", {}) or {}

        if not iid:
            continue

        if itype in ("new_player", "player"):
            players_by_id[iid] = {
                "name": attr.get("name"),
                "team": attr.get("team"),
            }
        elif itype == "game":
            games_by_id[iid] = attr

    rows: list[dict[str, Any]] = []
    now_utc = _resolve_replay_now(payload) if is_replay else datetime.now(timezone.utc)
    TZ_CT = ZoneInfo("America/Chicago")
    now_ct = now_utc.astimezone(TZ_CT)
    today_ct = now_ct.date()

    # In replay mode, if the board was captured the evening before the slate,
    # derive today_ct from the earliest game start instead of the payload timestamp.
    if is_replay:
        game_dates: set[date] = set()
        for gattr in games_by_id.values():
            st = _parse_iso_datetime(gattr.get("start_time"))
            if st:
                game_dates.add(st.astimezone(TZ_CT).date())
        if game_dates and today_ct not in game_dates:
            today_ct = min(game_dates)

    kept_today_upcoming = 0
    dropped_no_start = 0
    dropped_future_date = 0
    dropped_past = 0
    
    for item in data:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes", {}) or {}
        rel = item.get("relationships", {}) or {}
        
        # --- Slate gate: keep only today's CT slate AND only games that haven't started yet (CT) ---
        game_id = ((rel.get("game") or {}).get("data") or {}).get("id")
        if not game_id or game_id not in games_by_id:
            dropped_no_start += 1
            continue

        start_iso = (games_by_id.get(game_id) or {}).get("start_time")
        dt_start = _parse_iso_datetime(start_iso)
        if dt_start is None:
            dropped_no_start += 1
            continue

        dt_start_ct = dt_start.astimezone(TZ_CT)

        # drop if not on today's CT date (prevents "tomorrow popular" leaks)
        if dt_start_ct.date() != today_ct:
            dropped_future_date += 1
            continue

        # drop if already started (skip in replay — we need the full historical board)
        if not is_replay and dt_start_ct < now_ct:
            dropped_past += 1
            continue

        kept_today_upcoming += 1

        # Player join (required)
        
        player_id = _clean_str(
            ((rel.get("new_player") or {}).get("data") or {}).get("id")
            or ((rel.get("player") or {}).get("data") or {}).get("id")
        )
        pinfo = players_by_id.get(player_id, {})
        player_name = _clean_str(pinfo.get("name"))
        team = _clean_str(pinfo.get("team"))
        
        if not player_name:
            continue

        # Drop combo players entirely (you will never play them)
        if _is_combo_player_name(player_name) or _is_combo_team(team):
            continue

        # Stat normalization (required)
        stat = _norm_stat(
            attr.get("stat_type")
            or attr.get("stat_type_display")
            or attr.get("stat_display_name")
        )

        if not stat or stat not in SUPPORTED_STATS:
            continue

        # Line (required)
        raw_line = attr.get("line_score")
        if raw_line is None:
            continue
        if not isinstance(raw_line, (int, float, str)):
            continue
        try:
            line = float(raw_line)
        except (TypeError, ValueError):
            continue

        # Game join (for opp + game_date + start_time gating)
        game_id = _clean_str(((rel.get("game") or {}).get("data") or {}).get("id"))
        gattr = games_by_id.get(game_id, {}) if game_id else {}

        start_time = gattr.get("start_time")
        dt = _parse_iso_datetime(start_time)
        if not is_replay and dt and dt < now_utc:
            continue

        game_date = ""
        if isinstance(start_time, str) and len(start_time) >= 10:
            game_date = start_time[:10]

        # Derive opponent + home via game metadata teams
        md = (gattr.get("metadata") or {}).get("game_info", {}).get("teams", {})
        home_abbr = (md.get("home") or {}).get("abbreviation")
        away_abbr = (md.get("away") or {}).get("abbreviation")

        opp = "UNK"
        home = 0
        if team and home_abbr and away_abbr:
            if team == home_abbr:
                home = 1
                opp = away_abbr
            elif team == away_abbr:
                home = 0
                opp = home_abbr
            else:
                # team mismatch vs game teams → skip to avoid poisoning opp/matrix/teamshare
                continue

        rows.append(
            {
                "projection_id": _clean_str(item.get("id")),
                "player": player_name,
                "stat": stat,
                "line": line,
                "tag": _infer_tag(attr.get("odds_type")),
                "team": team,
                "opp": _clean_str(opp),
                "home": int(home),
                "game_date": _clean_str(game_date),
            }
        )

    
    # one-line slate gate summary (only prints if anything was dropped)
    if dropped_no_start or dropped_future_date or dropped_past:
        print(
            f"prizepicks gate: kept_today_upcoming={kept_today_upcoming} "
            f"dropped_no_start={dropped_no_start} dropped_future_date={dropped_future_date} dropped_past={dropped_past}"
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    
    bad = {}
    for c in ("projection_id","player","stat","tag","team","opp","game_date"):
        if c in df.columns:
            s = df[c]
            mask = s.apply(lambda v: isinstance(v, (dict, list, set, tuple)))
            if mask.any():
                bad[c] = (int(mask.sum()), type(s[mask].iloc[0]).__name__)
    if bad:
        raise ValueError(f"Non-scalar values in board columns: {bad}")
    
    # Ensure contract column types are stable (prevents opp/game_date becoming float due to NaN)
    for c in ("projection_id", "player", "stat", "tag", "team", "opp", "game_date"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)

    if "home" in df.columns:
        df["home"] = pd.to_numeric(df["home"], errors="coerce").fillna(0).astype(int)

    if "line" in df.columns:
        df["line"] = pd.to_numeric(df["line"], errors="coerce")
        df = df[df["line"].notna()]
        df["line"] = df["line"].astype(float)

    # Expand directions
    expanded: list[dict[str, Any]] = []
    for rec in df.to_dict("records"):
        # ensure keys are str to satisfy type checkers (dict[str, Any])
        rec_str_keys = {str(k): v for k, v in rec.items()}
        for direction in ("OVER", "UNDER"):
            expanded.append({**rec_str_keys, "direction": direction})

    out = pd.DataFrame(expanded)
    # Final dtype hardening
    if "direction" in out.columns:
        out["direction"] = out["direction"].fillna("").astype(str)

    return out
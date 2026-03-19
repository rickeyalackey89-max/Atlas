import os
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

import pandas as pd


# -----------------------------
# Helpers
# -----------------------------
def _clean_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


def _norm_player_name(name: str) -> str:
    s = _clean_str(name).lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    parts = [p for p in s.split() if p not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(parts).strip()


def _norm_date_str(s: str) -> str:
    """
    Normalize to YYYY-MM-DD. Returns "" if not parseable.
    Accepts:
      - YYYY-MM-DD
      - M/D/YYYY, MM/DD/YYYY
      - M/D/YY
      - YYYY/MM/DD
    """
    s = _clean_str(s)
    if not s:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    fmts = ["%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""


def _utc_date_from_epoch(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d")


def _ensure_cols(df: pd.DataFrame, cols: List[str], fill_value=pd.NA) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = fill_value
    return df


# -----------------------------
# Rotowire attach (game spreads)
# -----------------------------
def attach_rotowire_game_spreads(df: pd.DataFrame, rotowire_path: str) -> pd.DataFrame:
    """
    Attach Rotowire *game* spreads (event-level) onto prop rows.

    Requires df columns: team, opp (may be blank), game_date
    Adds columns:
      home_team, away_team, home_spread, away_spread, game_spread,
      spread_source, spread_ok, spread_reason

    Behavior:
      - If opp present: match by (date, team, opp) order-agnostic.
      - If opp missing: match by (date, team) ONLY if exactly one game for that team/date,
        then infer opp and spreads.
    """
    out = df.copy()

    out = _ensure_cols(
        out,
        [
            "home_team",
            "away_team",
            "home_spread",
            "away_spread",
            "game_spread",
            "spread_source",
            "spread_ok",
            "spread_reason",
        ],
        fill_value=pd.NA,
    )

    # Validate join inputs
    for required in ("team", "opp", "game_date"):
        if required not in out.columns:
            out["spread_ok"] = False
            out["spread_reason"] = "missing_join_cols"
            out["spread_source"] = "rotowire"
            return out

    team_s = out["team"].astype(str).str.strip()
    opp_s = out["opp"].astype(str).str.strip()
    date_s = out["game_date"].astype(str).map(_norm_date_str).fillna("")

    # Load Rotowire JSON
    try:
        with open(rotowire_path, "r", encoding="utf-8") as f:
            rw = json.load(f)
    except Exception as e:
        out["spread_ok"] = False
        out["spread_reason"] = f"rotowire_load_failed:{type(e).__name__}"
        out["spread_source"] = "rotowire"
        return out

    # Locate events list
    events = None
    if isinstance(rw, dict):
        if isinstance(rw.get("lines"), dict) and isinstance(rw["lines"].get("events"), list):
            events = rw["lines"]["events"]
        elif isinstance(rw.get("events"), list):
            events = rw["events"]

    if not isinstance(events, list):
        out["spread_ok"] = False
        out["spread_reason"] = "rotowire_events_missing"
        out["spread_source"] = "rotowire"
        return out

    # Build lookup: (game_date, home, away) -> (home_spread, away_spread)
    # IMPORTANT:
    #   Rotowire's payload includes both:
    #     - game_date: "YYYY-MM-DD" (authoritative for joining)
    #     - eventTime: epoch seconds (can drift a day vs local timezones for late games)
    #   We prefer game_date when present, and fall back to eventTime->UTC date.
    lookup: Dict[Tuple[str, str, str], Tuple[float, float]] = {}
    for ev in events:
        try:
            home = _clean_str(ev.get("homeTeam", ""))
            away = _clean_str(ev.get("awayTeam", ""))
            et = ev.get("eventTime", None)
            gd = _norm_date_str(ev.get("game_date", ""))
            sp = ev.get("spread", {}) or {}
            hs = sp.get("home", None)
            aws = sp.get("away", None)

            if not home or not away:
                continue
            if hs is None or aws is None:
                continue

            # Prefer explicit game_date when available.
            # Otherwise, fall back to UTC date derived from eventTime.
            if gd:
                d = gd
            else:
                if et is None:
                    continue
                d = _utc_date_from_epoch(et)
            hs_f = float(hs)
            aws_f = float(aws)

            lookup[(d, home, away)] = (hs_f, aws_f)
        except Exception:
            continue

    if not lookup:
        out["spread_ok"] = False
        out["spread_reason"] = "rotowire_no_spreads_found"
        out["spread_source"] = "rotowire"
        return out

    # Build reverse index: (utc_date, team) -> list of games containing team
    # store as (home, away, home_spread, away_spread)
    team_index: Dict[Tuple[str, str], List[Tuple[str, str, float, float]]] = {}
    for (d, home, away), (hs, aws) in lookup.items():
        team_index.setdefault((d, home), []).append((home, away, hs, aws))
        team_index.setdefault((d, away), []).append((home, away, hs, aws))

    def _row_attach(team: str, opp: str, d: str):
        team = _clean_str(team)
        opp = _clean_str(opp)
        d = _clean_str(d)

        if not team or not d:
            return (pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, "missing_team_or_date")

        # Strict match when opp is present
        if opp:
            key1 = (d, team, opp)  # team as home
            key2 = (d, opp, team)  # team as away
            if key1 in lookup:
                hs, aws = lookup[key1]
                return (team, opp, hs, aws, hs, "ok")
            if key2 in lookup:
                hs, aws = lookup[key2]
                return (opp, team, hs, aws, aws, "ok")

        def _shift_date(d: str, delta_days: int) -> str:
            try:
                dt = datetime.strptime(d, "%Y-%m-%d") + timedelta(days=delta_days)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return d

        # 2) fallback: infer opp by unique game for (date, team) with UTC day shift tolerance
        candidate_dates = [d, _shift_date(d, +1), _shift_date(d, -1)]

        picked = None  # (used_date, game_tuple)
        for d2 in candidate_dates:
            games2 = team_index.get((d2, team), [])
            if len(games2) == 1:
                picked = (d2, games2[0])
                break

        if picked is not None:
            used_date, (home, away, hs, aws) = picked
            inferred_opp = away if team == home else home
            team_spread = hs if team == home else aws
            reason = "ok_inferred_opp" if used_date == d else f"ok_inferred_opp_date_shift_{used_date}"
            return (home, away, hs, aws, team_spread, reason)

        # If still no match, report the best reason
        games0 = team_index.get((d, team), [])
        if len(games0) == 0:
            return (pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, "no_game_for_team_date")
        return (pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, "ambiguous_team_date")

    attached = [
        _row_attach(t, o, d)
        for t, o, d in zip(team_s.tolist(), opp_s.tolist(), date_s.tolist())
    ]

    out["home_team"] = [a[0] for a in attached]
    out["away_team"] = [a[1] for a in attached]
    out["home_spread"] = [a[2] for a in attached]
    out["away_spread"] = [a[3] for a in attached]
    out["game_spread"] = [a[4] for a in attached]

    out["spread_source"] = "rotowire"
    out["spread_ok"] = out["game_spread"].notna()
    out["spread_reason"] = [a[5] for a in attached]

    return out


# -----------------------------
# Main enrichment
# -----------------------------
def enrich_with_matchups(
    projections: pd.DataFrame,
    roster_map_path: str,
    slate_path: str,
    default_game_date: str,
    rotowire_lines_path: str = r"C:\Users\rick\projects\Atlas\data\input\rotowire_lines.json",
) -> pd.DataFrame:
    rotowire_lines_path = (os.environ.get("ATLAS_ROTOWIRE_LINES_PATH") or rotowire_lines_path or "").strip()
    """
    Adds team/opp/home/game_date and game spreads to projections using:
      - roster_map.csv: player -> team abbreviation
      - slate.csv: game_date, home_team, away_team (matchups only; may NOT include spreads)
      - rotowire_lines.json: event spreads (home/away spreads) for game_spread enrichment

    SEMANTICS:
      - 'line' in projections is the PROP line (bet target). We DO NOT touch it.
      - 'game_spread' is the GAME-level spread used only for blowout/fragility.
      - 'spread' is kept for backward compatibility and mirrors 'game_spread'.
    """
    df = projections.copy()

    # Ensure required cols exist (do NOT touch 'line')
    def _ensure_cols(df: pd.DataFrame, cols, fill_value):
        for c in cols:
            if c not in df.columns:
                df[c] = fill_value
        return df

    # Backward compat: downstream expects 'spread'
    if "spread" not in df.columns:
        df["spread"] = ""

    if "player" not in df.columns:
        raise ValueError("enrich_with_matchups: projections is missing required column 'player'")

    # Ensure these columns always exist even if input board doesn't include them
    for c in ["team", "opp", "home", "game_date"]:
        if c not in df.columns:
            df[c] = ""
    # Clean strings
    df["player"] = df["player"].apply(_clean_str)
    df["team"] = df["team"].apply(_clean_str)
    df["opp"] = df["opp"].apply(_clean_str)

    # Normalize date fields
    default_iso = _norm_date_str(default_game_date)
    if not default_iso:
        raise ValueError(f"enrich_with_matchups: default_game_date not parseable: {default_game_date!r}")

    df["game_date"] = df["game_date"].apply(_norm_date_str)
    df.loc[df["game_date"] == "", "game_date"] = default_iso

    # Home numeric safe
    df["home"] = pd.to_numeric(df["home"], errors="coerce").fillna(0).astype(int)

    # ---- Load roster map (player -> team) ----
    roster = pd.read_csv(roster_map_path)
    if "player" not in roster.columns or "team" not in roster.columns:
        raise ValueError("roster_map.csv must contain columns: player, team")

    roster["player"] = roster["player"].apply(_clean_str)
    roster["team"] = roster["team"].apply(_clean_str)

    exact_team_map = dict(zip(roster["player"], roster["team"]))

    norm_team_map: Dict[str, str] = {}
    for p, t in zip(roster["player"], roster["team"]):
        if t:
            norm_team_map[_norm_player_name(p)] = t

    # Fill missing team (exact then normalized)
    missing_team = df["team"] == ""
    if missing_team.any():
        df.loc[missing_team, "team"] = df.loc[missing_team, "player"].map(exact_team_map).fillna("")

    missing_team = df["team"] == ""
    if missing_team.any():
        df.loc[missing_team, "team"] = df.loc[missing_team, "player"].apply(
            lambda p: norm_team_map.get(_norm_player_name(p), "")
        )

    # ---- Load slate (matchups only) ----
    # If slate date doesn't match today (as in your screenshot), this won't fill opp/home.
    # That's OK because Rotowire attachment can infer opp by team+date.
    try:
        slate = pd.read_csv(slate_path)
        need_cols = {"game_date", "home_team", "away_team"}
        if need_cols.issubset(set(slate.columns)):
            slate["game_date"] = slate["game_date"].apply(_norm_date_str)
            slate["home_team"] = slate["home_team"].apply(_clean_str)
            slate["away_team"] = slate["away_team"].apply(_clean_str)

            slate_day = slate[slate["game_date"] == default_iso].copy()

            mapping: Dict[str, List[Tuple[str, int]]] = {}
            for _, r in slate_day.iterrows():
                h = _clean_str(r["home_team"])
                a = _clean_str(r["away_team"])
                if not (h and a):
                    continue
                mapping.setdefault(h, []).append((a, 1))
                mapping.setdefault(a, []).append((h, 0))

            def infer_opp_home(team: str) -> Tuple[str, int]:
                team = _clean_str(team)
                if not team:
                    return ("", 0)
                games = mapping.get(team, [])
                if len(games) != 1:
                    return ("", 0)
                opp, home_flag = games[0]
                return (opp, int(home_flag))

            need = df["opp"] == ""
            if need.any():
                inferred = df.loc[need, "team"].apply(infer_opp_home)
                df.loc[need, "opp"] = [x[0] for x in inferred]
                df.loc[need, "home"] = [x[1] for x in inferred]
    except Exception:
        # Slate is optional for spreads; don't fail enrichment because slate is stale/bad.
        pass

    # Normalize final matchup columns
    df["team"] = df["team"].apply(_clean_str)
    df["opp"] = df["opp"].apply(_clean_str)
    df["home"] = pd.to_numeric(df["home"], errors="coerce").fillna(0).astype(int)
    df["game_date"] = df["game_date"].apply(_norm_date_str)

    # ---- Attach Rotowire game spreads (critical) ----
    df = attach_rotowire_game_spreads(df, rotowire_lines_path)

    # Backward compatibility: keep 'spread' aligned to game_spread
    if "game_spread" in df.columns:
        df["spread"] = pd.to_numeric(df["game_spread"], errors="coerce")

    return df
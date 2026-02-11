# C:\Users\rick\pp_model\src\matchup_enricher.py

import re
from datetime import datetime

import pandas as pd


def _clean_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


def _norm_player_name(name: str) -> str:
    """
    Normalizes player names to improve roster matching.
    Examples:
      "Kelly Oubre Jr." -> "kelly oubre"
      "Trey Murphy III" -> "trey murphy"
      "D'Angelo Russell" -> "dangelo russell"
    """
    s = _clean_str(name).lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)  # remove punctuation
    parts = [p for p in s.split() if p not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(parts).strip()


def _norm_date_str(s: str) -> str:
    """
    Normalize a date string into YYYY-MM-DD.

    Accepts common formats we see:
      - "2026-01-30"
      - "1/30/2026"
      - "01/30/2026"
      - "2026/01/30"
    Returns "" if it can't parse.
    """
    s = _clean_str(s)
    if not s:
        return ""

    # Already ISO-ish
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    # Try a few common formats
    fmts = ["%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass

    return ""


def enrich_with_matchups(
    projections: pd.DataFrame,
    roster_map_path: str,
    slate_path: str,
    default_game_date: str,
) -> pd.DataFrame:
    """
    Adds team/opp/home/game_date to projections using:
      - roster_map.csv: player -> team abbreviation
      - slate.csv: game_date, home_team, away_team

    Key robustness:
      - Normalizes player names (handles Jr/III/punctuation)
      - Normalizes game_date (handles YYYY-MM-DD and M/D/YYYY)
      - Keeps home as int (0/1) to avoid pandas dtype errors
    """
    df = projections.copy()

    # Ensure needed columns exist
    for col in ["team", "opp", "home", "game_date"]:
        if col not in df.columns:
            df[col] = ""

    # Validate required
    if "player" not in df.columns:
        raise ValueError("enrich_with_matchups: projections is missing required column 'player'")

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

    # Make sure home is numeric-safe before any assignment
    df["home"] = pd.to_numeric(df["home"], errors="coerce").fillna(0).astype(int)

    # ---- Load roster map (player -> team) ----
    roster = pd.read_csv(roster_map_path)
    if "player" not in roster.columns or "team" not in roster.columns:
        raise ValueError("roster_map.csv must contain columns: player, team")

    roster["player"] = roster["player"].apply(_clean_str)
    roster["team"] = roster["team"].apply(_clean_str)

    exact_team_map = dict(zip(roster["player"], roster["team"]))

    norm_team_map = {}
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

    # ---- Load slate (games) ----
    slate = pd.read_csv(slate_path)
    need_cols = {"game_date", "home_team", "away_team"}
    if not need_cols.issubset(set(slate.columns)):
        raise ValueError("slate.csv must contain columns: game_date, home_team, away_team")

    slate["game_date"] = slate["game_date"].apply(_norm_date_str)
    slate["home_team"] = slate["home_team"].apply(_clean_str)
    slate["away_team"] = slate["away_team"].apply(_clean_str)

    # Filter slate to the iso date we are modeling
    slate = slate[slate["game_date"] == default_iso].copy()

    # Build mapping: team -> list of (opp, home_flag)
    mapping: dict[str, list[tuple[str, int]]] = {}
    for _, r in slate.iterrows():
        h = _clean_str(r["home_team"])
        a = _clean_str(r["away_team"])
        if h and a:
            mapping.setdefault(h, []).append((a, 1))
            mapping.setdefault(a, []).append((h, 0))

    def infer_opp_home(team: str) -> tuple[str, int]:
        team = _clean_str(team)
        if team == "":
            return ("", 0)
        games = mapping.get(team, [])
        # infer only if exactly one game for that team (unambiguous)
        if len(games) != 1:
            return ("", 0)
        opp, home_flag = games[0]
        return (opp, int(home_flag))

    # Infer opp/home for rows where opp is missing
    need = df["opp"] == ""
    if need.any():
        inferred = df.loc[need, "team"].apply(infer_opp_home)
        df.loc[need, "opp"] = [x[0] for x in inferred]
        df.loc[need, "home"] = [x[1] for x in inferred]

    # Final normalize
    df["team"] = df["team"].apply(_clean_str)
    df["opp"] = df["opp"].apply(_clean_str)
    df["home"] = pd.to_numeric(df["home"], errors="coerce").fillna(0).astype(int)
    df["game_date"] = df["game_date"].apply(_norm_date_str)

    return df
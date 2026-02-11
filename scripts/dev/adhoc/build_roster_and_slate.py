import os
import re
import sys
from datetime import datetime

import pandas as pd
from nba_api.stats.endpoints import CommonAllPlayers, LeagueGameFinder
from nba_api.stats.static import teams


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _norm_date(s: str) -> str:
    # expects YYYY-MM-DD
    datetime.strptime(s, "%Y-%m-%d")
    return s


def build_roster_map(output_path: str) -> pd.DataFrame:
    """
    Builds player -> team abbreviation for current players using:
      - CommonAllPlayers (current season players)
      - static teams list to map TEAM_ID -> abbreviation
    """
    team_id_to_abbr = {t["id"]: t["abbreviation"] for t in teams.get_teams()}

    cap = CommonAllPlayers(is_only_current_season=1)
    df = cap.get_data_frames()[0].copy()

    # columns include: DISPLAY_FIRST_LAST, TEAM_ID, ...
    df["player"] = df["DISPLAY_FIRST_LAST"].astype(str).str.strip()
    df["team"] = df["TEAM_ID"].map(team_id_to_abbr).fillna("").astype(str).str.strip()

    out = df.loc[df["team"] != "", ["player", "team"]].drop_duplicates().sort_values(["team", "player"])
    out.to_csv(output_path, index=False)
    return out


def build_slate(game_date: str, output_path: str) -> pd.DataFrame:
    """
    Builds a slate for a specific date using LeagueGameFinder.
    LeagueGameFinder returns one row per team per game; we dedupe by GAME_ID
    and parse MATCHUP like:
      'BOS vs LAL' -> home=BOS away=LAL
      'BOS @ LAL'  -> away=BOS home=LAL
    """
    # nba_api expects MM/DD/YYYY for date filters
    dt = datetime.strptime(game_date, "%Y-%m-%d")
    mmddyyyy = dt.strftime("%m/%d/%Y")

    lgf = LeagueGameFinder(date_from_nullable=mmddyyyy, date_to_nullable=mmddyyyy)
    df = lgf.get_data_frames()[0].copy()

    if df.empty:
        out = pd.DataFrame(columns=["game_date", "home_team", "away_team"])
        out.to_csv(output_path, index=False)
        return out

    # Keep one row per game id (matchup text is enough to parse home/away)
    games = df.drop_duplicates(subset=["GAME_ID"])[["GAME_ID", "MATCHUP"]].copy()

    def parse_matchup(m: str):
        m = str(m).strip()
        # examples: "BOS vs LAL", "BOS @ LAL"
        if " vs " in m:
            a, b = m.split(" vs ")
            home = a.strip()
            away = b.strip()
            return home, away
        if " @ " in m:
            away, home = m.split(" @ ")
            return home.strip(), away.strip()
        return "", ""

    parsed = games["MATCHUP"].apply(parse_matchup)
    games["home_team"] = [x[0] for x in parsed]
    games["away_team"] = [x[1] for x in parsed]
    games["game_date"] = game_date

    out = games.loc[(games["home_team"] != "") & (games["away_team"] != ""), ["game_date", "home_team", "away_team"]]
    out = out.drop_duplicates().sort_values(["home_team", "away_team"])
    out.to_csv(output_path, index=False)
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools\\build_roster_and_slate.py YYYY-MM-DD")
        sys.exit(1)

    game_date = _norm_date(sys.argv[1])

    out_dir = os.path.join("data", "input")
    _ensure_dir(out_dir)

    roster_path = os.path.join(out_dir, "roster_map.csv")
    slate_path = os.path.join(out_dir, "slate.csv")

    roster_df = build_roster_map(roster_path)
    slate_df = build_slate(game_date, slate_path)

    print(f"Wrote: {roster_path}  (rows={len(roster_df)})")
    print(f"Wrote: {slate_path}  (rows={len(slate_df)})")
    if len(slate_df) == 0:
        print("WARNING: slate is empty for that date (no games found).")


if __name__ == "__main__":
    main()
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import pandas as pd
from nba_api.stats.endpoints import leaguegamelog
PROJECT_ROOT = find_repo_root(Path(__file__))
OUT_PATH = PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"

def current_season_string() -> str:
    today = pd.Timestamp.today()
    year = int(today.year)
    month = int(today.month)
    start = year if month >= 7 else year - 1
    end_short = str(start + 1)[-2:]
    return f"{start}-{end_short}"

def parse_opp(matchup: str) -> str:
    if not isinstance(matchup, str):
        return ""
    parts = matchup.replace("  ", " ").split()
    return parts[2] if len(parts) >= 3 else ""

def main():
    season = current_season_string()
    print(f"Season: {season}")

    lg = leaguegamelog.LeagueGameLog(season=season, player_or_team_abbreviation="P")
    raw = lg.get_data_frames()[0].copy()

    df = pd.DataFrame({
        "game_date": pd.to_datetime(raw.get("GAME_DATE"), errors="coerce").dt.date.astype(str),
        "player": raw.get("PLAYER_NAME", ""),
        "team": raw.get("TEAM_ABBREVIATION", ""),
        "opp": raw.get("MATCHUP", "").apply(parse_opp),

        "minutes": pd.to_numeric(raw.get("MIN", 0), errors="coerce").fillna(0),

        "pts": pd.to_numeric(raw.get("PTS", 0), errors="coerce").fillna(0),
        "reb": pd.to_numeric(raw.get("REB", 0), errors="coerce").fillna(0),
        "ast": pd.to_numeric(raw.get("AST", 0), errors="coerce").fillna(0),
        "fg3m": pd.to_numeric(raw.get("FG3M", 0), errors="coerce").fillna(0),

        # Usage inputs
        "fga": pd.to_numeric(raw.get("FGA", 0), errors="coerce").fillna(0),
        "fta": pd.to_numeric(raw.get("FTA", 0), errors="coerce").fillna(0),
        "tov": pd.to_numeric(raw.get("TOV", 0), errors="coerce").fillna(0),
    })

    # usage proxy per minute (avoid divide-by-zero)
    mins = df["minutes"].replace(0, pd.NA)
    df["usg_proxy"] = ((df["fga"] + 0.44 * df["fta"] + df["tov"]) / mins).fillna(0)

    df["player"] = df["player"].astype(str).str.strip()
    df = df[df["player"] != ""]
    df = df.dropna(subset=["game_date"])

    df = df.drop_duplicates(subset=["game_date", "player", "team", "opp"], keep="last")
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df = df.sort_values(["player", "game_date"])
    df["game_date"] = df["game_date"].dt.date.astype(str)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote: {OUT_PATH} | rows={len(df):,}")

if __name__ == "__main__":
    main()

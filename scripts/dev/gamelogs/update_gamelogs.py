import time
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import pandas as pd
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players as nba_players
PROJECT_ROOT = find_repo_root(Path(__file__))
BOARD_PATH = PROJECT_ROOT / "data" / "board" / "today.csv"
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


def find_player_id(name: str):
    name = str(name).strip()
    if not name:
        return None

    matches = nba_players.find_players_by_full_name(name)
    if not matches:
        matches = nba_players.find_players_by_full_name(name.split()[-1])

    if not matches:
        return None

    active = [m for m in matches if m.get("is_active")]
    chosen = active[0] if active else matches[0]
    return int(chosen["id"])


def fetch_player_gamelogs(player_id: int, season: str, player_name: str) -> pd.DataFrame:
    gl = playergamelog.PlayerGameLog(player_id=player_id, season=season)
    raw = gl.get_data_frames()[0]

    rows = []
    for _, r in raw.iterrows():
        rows.append({
            "game_date": str(pd.to_datetime(r.get("GAME_DATE")).date()),
            "player": player_name,
            "team": r.get("TEAM_ABBREVIATION", ""),
            "opp": parse_opp(r.get("MATCHUP", "")),
            "minutes": float(r.get("MIN", 0) or 0),
            "pts": float(r.get("PTS", 0) or 0),
            "reb": float(r.get("REB", 0) or 0),
            "ast": float(r.get("AST", 0) or 0),
            "fg3m": float(r.get("FG3M", 0) or 0),
        })

    return pd.DataFrame(rows)


def main():
    if not BOARD_PATH.exists():
        raise FileNotFoundError(f"Missing {BOARD_PATH}")

    board = pd.read_csv(BOARD_PATH)
    if "player" not in board.columns:
        raise ValueError("today.csv must contain a 'player' column")

    players = sorted(set(str(p).strip() for p in board["player"] if str(p).strip()))
    if not players:
        print("No players found on board")
        return

    season = current_season_string()
    print(f"Season: {season}")
    print(f"Players on board: {len(players)}")

    all_logs = []
    unresolved = []

    for i, name in enumerate(players, 1):
        pid = find_player_id(name)
        if pid is None:
            unresolved.append(name)
            print(f"[{i}/{len(players)}] UNRESOLVED: {name}")
            continue

        try:
            df = fetch_player_gamelogs(pid, season, name)
            all_logs.append(df)
            print(f"[{i}/{len(players)}] OK: {name} ({len(df)} games)")
        except Exception as e:
            unresolved.append(name)
            print(f"[{i}/{len(players)}] ERROR: {name} -> {e}")

        time.sleep(0.6)

    if not all_logs:
        print("No gamelogs fetched. Nothing written.")
        return

    new_data = pd.concat(all_logs, ignore_index=True)

    if OUT_PATH.exists():
        old = pd.read_csv(OUT_PATH)
        combined = pd.concat([old, new_data], ignore_index=True)
    else:
        combined = new_data

    combined = combined.drop_duplicates(subset=["game_date", "player", "team", "opp"], keep="last")

    combined["game_date"] = pd.to_datetime(combined["game_date"])
    combined = combined.sort_values(["player", "game_date"])
    combined["game_date"] = combined["game_date"].dt.date.astype(str)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT_PATH, index=False)

    print(f"\nWrote: {OUT_PATH}")

    if unresolved:
        print("\nUnresolved players (name mismatch):")
        for n in unresolved:
            print(" -", n)


if __name__ == "__main__":
    main()

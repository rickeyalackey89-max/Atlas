from __future__ import annotations

"""
tools/refresh_nba_gamelogs.py

Daily gamelog refresh + human-auditable "last 5" report.

Design goals:
- Update data/gamelogs/nba_gamelogs.csv up through yesterday (America/Chicago).
- Never silently "succeed" while stale; enforce max-stale-days.
- Produce reference artifacts:
    - data/gamelogs/gamelogs_status.json
    - data/gamelogs/audit_last5_board.csv

Notes:
- Requires nba_api: pip install nba_api
- Isolated tooling only (no optimizer/model logic).
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime, timedelta, date
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
GAMELOGS_PATH = PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
STATUS_PATH = PROJECT_ROOT / "data" / "gamelogs" / "gamelogs_status.json"
AUDIT_PATH = PROJECT_ROOT / "data" / "gamelogs" / "audit_last5_board.csv"

BOARD_TODAY_PATH = PROJECT_ROOT / "data" / "board" / "today.csv"
BOARD_FETCH_PATH = PROJECT_ROOT / "data" / "board" / "fetch_board.csv"


# -------------------------
# Strategy B name resolution
# -------------------------

ALIASES: Dict[str, str] = {
    "Derrick Jones": "Derrick Jones Jr.",
    "Jaime Jaquez": "Jaime Jaquez Jr.",
}


def _canonical_name(name: str) -> str:
    """
    Canonicalize a player name for robust matching across sources:
      - Unicode NFKD normalize + strip diacritics
      - lower-case
      - remove punctuation
      - strip common suffix tokens (jr/sr/ii/iii/iv/v)
      - collapse whitespace

    This is intended to fix *name mismatches only* (e.g., "Jokić" vs "Jokic",
    "Tim Hardaway" vs "Tim Hardaway Jr.") while avoiding unsafe fuzzy matching.
    """
    s = (name or "").strip()
    if not s:
        return ""

    # Strip diacritics (e.g., Jokić -> Jokic)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    s = s.lower()

    # Replace punctuation with spaces, then collapse
    s = re.sub(r"[^a-z0-9\s]", " ", s)

    # Tokenize and remove suffixes
    toks = [t for t in re.split(r"\s+", s) if t]
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    toks = [t for t in toks if t not in suffixes]

    return " ".join(toks)


def resolve_player_name(board_player: str, gamelog_players: Iterable[str]) -> Tuple[Optional[str], str]:
    """
    Strategy B (with robust canonical fallback):
      1) exact match
      2) alias match (board -> gamelog)
      3) canonical unique match (diacritics/suffix/punctuation insensitive)
      4) unique contains match (case-insensitive), only if exactly 1 hit

    Canonical matching is only accepted if it maps to exactly ONE gamelog player,
    to avoid accidental collisions.
    """
    bp = (board_player or "").strip()
    if not bp:
        return None, "unresolved"

    players = [str(p) for p in gamelog_players if str(p).strip()]

    # 1) exact match
    if bp in players:
        return bp, "exact"

    # 2) explicit aliases
    if bp in ALIASES and ALIASES[bp] in players:
        return ALIASES[bp], "alias"

    # 3) canonical unique match (suffix/diacritic/punctuation insensitive)
    bp_key = _canonical_name(bp)
    if bp_key:
        canon_to_players: Dict[str, list[str]] = {}
        for p in players:
            k = _canonical_name(p)
            if not k:
                continue
            canon_to_players.setdefault(k, [])
            if p not in canon_to_players[k]:
                canon_to_players[k].append(p)

        hits = canon_to_players.get(bp_key, [])
        if len(hits) == 1:
            return hits[0], "canonical_unique"
        if len(hits) > 1:
            return None, "canonical_ambiguous"

    # 4) unique contains match (case-insensitive)
    q = bp.lower()
    hits = [p for p in players if q in p.lower()]
    hits = list(dict.fromkeys(hits))  # preserve order, unique
    if len(hits) == 1:
        return hits[0], "contains_unique"
    if len(hits) > 1:
        return None, "ambiguous"

    return None, "unresolved"


# -------------------------
# nba_api fetch
# -------------------------

def _import_nba_api():
    try:
        from nba_api.stats.endpoints import LeagueGameFinder
        return LeagueGameFinder
    except Exception as e:
        raise RuntimeError(
            "nba_api is required but could not be imported. Install via: pip install nba_api\n"
            f"Import error: {e}"
        )


def _mmddyyyy(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}/{d.year:04d}"


def _season_for_date(d: date) -> str:
    # NBA season labels like "2025-26"
    start_year = d.year if d.month >= 7 else d.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def fetch_player_gamelogs_range(date_from: date, date_to: date, season: Optional[str] = None) -> pd.DataFrame:
    LeagueGameFinder = _import_nba_api()
    if season is None:
        season = _season_for_date(date_to)

    lgf = LeagueGameFinder(
        season_nullable=season,
        league_id_nullable="00",
        player_or_team_abbreviation="P",  # CRITICAL: player-level logs, not team logs
        date_from_nullable=_mmddyyyy(date_from),
        date_to_nullable=_mmddyyyy(date_to),
    )
    dfs = lgf.get_data_frames()
    if not dfs:
        return pd.DataFrame()
    return dfs[0].copy()


def normalize_lgf_to_atlas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert LeagueGameFinder output -> Atlas schema:
      game_date, player, team, opp, minutes, pts, reb, ast, fg3m, fga, fta, tov, usg_proxy
    """
    cols_out = [
        "game_date", "player", "team", "opp",
        "minutes", "pts", "reb", "ast", "fg3m",
        "fga", "fta", "tov", "usg_proxy",
    ]

    if df is None or df.empty:
        return pd.DataFrame(columns=cols_out)

    colmap = {
        "GAME_DATE": "game_date",
        "PLAYER_NAME": "player",
        "TEAM_ABBREVIATION": "team",
        "MATCHUP": "matchup",
        "MIN": "minutes",
        "PTS": "pts",
        "REB": "reb",
        "AST": "ast",
        "FG3M": "fg3m",
        "FGA": "fga",
        "FTA": "fta",
        "TOV": "tov",
    }

    out = df.rename(columns={k: v for k, v in colmap.items() if k in df.columns}).copy()

    # Ensure player column exists (fail loudly if not)
    if "player" not in out.columns:
        for alt in ["PLAYER_NAME", "PlayerName", "PLAYER", "player_name", "name"]:
            if alt in df.columns:
                out["player"] = df[alt].astype(str)
                break
    if "player" not in out.columns:
        raise KeyError(f"normalize_lgf_to_atlas: missing player column. cols={list(df.columns)}")

    # game_date normalization to yyyy-mm-dd
    if "game_date" in out.columns:
        out["game_date"] = pd.to_datetime(out["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    else:
        out["game_date"] = pd.NA

    # opponent parsing from matchup (e.g., "BOS vs. NYK" or "BOS @ NYK")
    if "matchup" in out.columns:
        def _opp(m: str, team: str) -> str:
            m = str(m or "")
            team = str(team or "").upper()
            toks = [t for t in m.replace("vs.", "vs").split() if t.isalpha() and len(t) == 3]
            toks = [t.upper() for t in toks]
            if len(toks) == 0:
                return ""
            if len(toks) == 1:
                return toks[0] if toks[0] != team else ""
            if toks[0] == team:
                return toks[1]
            if toks[1] == team:
                return toks[0]
            return toks[-1]

        out["opp"] = [_opp(m, t) for m, t in zip(out["matchup"], out.get("team", ""))]
        out.drop(columns=["matchup"], inplace=True, errors="ignore")
    else:
        out["opp"] = ""

    # numeric columns: ensure present + numeric
    for c in ["minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]:
        if c not in out.columns:
            out[c] = 0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

    # usage proxy
    def _usg(fga: float, fta: float, tov: float, minutes: float) -> float:
        if float(minutes) <= 0:
            return 0.0
        return float(fga + 0.44 * fta + tov) / float(minutes)

    out["usg_proxy"] = [
        _usg(fga, fta, tov, minutes)
        for fga, fta, tov, minutes in zip(out["fga"], out["fta"], out["tov"], out["minutes"])
    ]

    out = out[cols_out].copy()
    out = out[out["game_date"].notna() & (out["game_date"].astype(str) != "NaT")].copy()

    # enforce string types for join safety
    out["player"] = out["player"].astype(str)
    out["team"] = out["team"].astype(str)
    out["opp"] = out["opp"].astype(str)

    return out


# -------------------------
# Daily audit (last5 board)
# -------------------------

def load_board_players() -> pd.DataFrame:
    p = BOARD_TODAY_PATH if BOARD_TODAY_PATH.exists() else BOARD_FETCH_PATH
    if not p.exists():
        raise FileNotFoundError(f"Board file not found at {p} (and no fallback). Run fetch first.")

    df = pd.read_csv(p)
    cols = {c.lower(): c for c in df.columns}

    player_col = cols.get("player")
    team_col = cols.get("team")

    if not player_col:
        raise RuntimeError(f"Board file {p} missing 'player' column. Columns={df.columns.tolist()}")

    out = df[[player_col] + ([team_col] if team_col else [])].copy()
    out.rename(columns={player_col: "player"}, inplace=True)
    if team_col:
        out.rename(columns={team_col: "team"}, inplace=True)
    else:
        out["team"] = ""

    out["player"] = out["player"].astype(str)
    out["team"] = out["team"].astype(str)

    return out.drop_duplicates(subset=["player", "team"])


def write_audit_last5_board(gamelogs: pd.DataFrame, board_players: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    gl = gamelogs.copy()
    gl["game_date"] = pd.to_datetime(gl["game_date"], errors="coerce")
    gl = gl.sort_values("game_date", ascending=False)

    universe = list(gl["player"].astype(str).unique()) if not gl.empty else []

    rows = []
    for _, r in board_players.iterrows():
        bp = str(r.get("player", "")).strip()
        team = str(r.get("team", "")).strip()

        resolved, method = resolve_player_name(bp, universe)
        if not resolved:
            rows.append({
                "board_player": bp,
                "resolved_player": "",
                "resolution_method": method,
                "team": team,
                "latest_game_date": "",
                "last5_minutes": "",
                "last5_pts": "",
                "last5_reb": "",
                "last5_ast": "",
                "last5_fg3m": "",
                "note": "UNRESOLVED",
            })
            continue

        w = gl[gl["player"] == resolved].head(int(lookback)).copy()
        if w.empty:
            rows.append({
                "board_player": bp,
                "resolved_player": resolved,
                "resolution_method": method,
                "team": team,
                "latest_game_date": "",
                "last5_minutes": "",
                "last5_pts": "",
                "last5_reb": "",
                "last5_ast": "",
                "last5_fg3m": "",
                "note": "NO_ROWS",
            })
            continue

        def pack(col: str) -> str:
            vals = w[col].tolist() if col in w.columns else []
            outv = []
            for v in vals:
                try:
                    fv = float(v)
                    outv.append(str(int(fv)) if fv.is_integer() else str(fv))
                except Exception:
                    outv.append(str(v))
            return " | ".join(outv)

        latest = w["game_date"].max()
        rows.append({
            "board_player": bp,
            "resolved_player": resolved,
            "resolution_method": method,
            "team": team,
            "latest_game_date": latest.strftime("%Y-%m-%d") if pd.notna(latest) else "",
            "last5_minutes": pack("minutes"),
            "last5_pts": pack("pts"),
            "last5_reb": pack("reb"),
            "last5_ast": pack("ast"),
            "last5_fg3m": pack("fg3m"),
            "note": "OK",
        })

    out = pd.DataFrame(rows)
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(AUDIT_PATH, index=False)
    return out


# -------------------------
# Main / status
# -------------------------

def read_existing_gamelogs() -> pd.DataFrame:
    cols_out = [
        "game_date", "player", "team", "opp",
        "minutes", "pts", "reb", "ast", "fg3m",
        "fga", "fta", "tov", "usg_proxy",
    ]
    if not GAMELOGS_PATH.exists():
        return pd.DataFrame(columns=cols_out)

    df = pd.read_csv(GAMELOGS_PATH)
    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def max_game_date(df: pd.DataFrame) -> Optional[date]:
    if df is None or df.empty or "game_date" not in df.columns:
        return None
    s = pd.to_datetime(df["game_date"], errors="coerce")
    mx = s.max()
    if pd.isna(mx):
        return None
    return mx.date()


def write_status(
    df: pd.DataFrame,
    refreshed: bool,
    old_max: Optional[date],
    new_max: Optional[date],
    added_rows: int,
    season: str,
) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "gamelogs_path": str(GAMELOGS_PATH),
        "rows": int(len(df)),
        "old_max_game_date": old_max.isoformat() if old_max else None,
        "new_max_game_date": new_max.isoformat() if new_max else None,
        "added_rows": int(added_rows),
        "season": season,
        "refreshed": bool(refreshed),
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=5)
    ap.add_argument("--max-stale-days", type=int, default=2)
    ap.add_argument("--force-season", type=str, default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    existing = read_existing_gamelogs()
    old_max = max_game_date(existing)

    season = args.force_season.strip() if args.force_season.strip() else _season_for_date(yesterday)

    if old_max is None:
        # If no file exists, start at an early season date to build a base.
        start_year = int(season.split("-")[0])
        date_from = date(start_year, 10, 1)
    else:
        date_from = old_max + timedelta(days=1)

    date_to = yesterday

    refreshed = False
    added_rows = 0
    combined = existing.copy()

    if date_from <= date_to:
        raw = fetch_player_gamelogs_range(date_from=date_from, date_to=date_to, season=season)
        new_part = normalize_lgf_to_atlas(raw)

        if not new_part.empty:
            refreshed = True
            before = len(combined)
            combined = pd.concat([combined, new_part], ignore_index=True)
            combined = combined.drop_duplicates(subset=["game_date", "player", "team", "opp"], keep="last")
            after = len(combined)
            added_rows = max(0, after - before)

    if not args.dry_run:
        GAMELOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(GAMELOGS_PATH, index=False)

    new_max = max_game_date(combined)
    if new_max is None:
        write_status(combined, refreshed, old_max, new_max, added_rows, season)
        raise SystemExit("Gamelog refresh FAILED: no max game_date available after refresh.")

    stale_days = (today - new_max).days
    if stale_days > int(args.max_stale_days):
        write_status(combined, refreshed, old_max, new_max, added_rows, season)
        raise SystemExit(
            f"Gamelogs are stale: max_game_date={new_max.isoformat()} (stale by {stale_days} days) "
            f"threshold={args.max_stale_days}."
        )

    board = load_board_players()
    write_audit_last5_board(combined, board_players=board, lookback=int(args.lookback))
    write_status(combined, refreshed, old_max, new_max, added_rows, season)

    print("OK refresh_nba_gamelogs")
    print(f"  old_max_game_date: {old_max}")
    print(f"  new_max_game_date: {new_max}")
    print(f"  added_rows: {added_rows}")
    print(f"  status: {STATUS_PATH}")
    print(f"  audit:  {AUDIT_PATH}")


if __name__ == "__main__":
    main()

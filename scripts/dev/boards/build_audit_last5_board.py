from __future__ import annotations

import re
import unicodedata
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
GAMELOGS_CSV = PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
BOARD_CSV    = PROJECT_ROOT / "data" / "board" / "fetch_board.csv"
OUT_CSV      = PROJECT_ROOT / "data" / "gamelogs" / "audit_last5_board.csv"

N_LAST = 5


# -----------------------------
# Name normalization (stable key)
# -----------------------------
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def player_key(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = _strip_diacritics(name).lower()
    s = re.sub(r"[^a-z0-9\s\.\-']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # drop suffix tokens
    parts = [p for p in s.split(" ") if p not in _SUFFIXES]
    return " ".join(parts).strip()


def parse_pipe_seq(s: str) -> list[int]:
    if not isinstance(s, str) or not s.strip():
        return []
    parts = [p.strip() for p in s.split("|")]
    out = []
    for p in parts:
        if not p:
            continue
        try:
            out.append(int(float(p)))
        except Exception:
            # ignore non-numeric
            pass
    return out


def seq_to_pipe(seq: list[int]) -> str:
    return " | ".join(str(int(x)) for x in seq)


def mean_or_blank(seq: list[int]) -> float | None:
    if not seq:
        return None
    return float(sum(seq)) / float(len(seq))


# -----------------------------
# Resolution: board name -> gamelog player
# -----------------------------
def resolve_player(board_name: str, players: pd.Series, key_map: dict[str, list[str]]) -> tuple[str | None, str, str]:
    """
    Returns (resolved_player, resolution_method, unmatched_reason)
    """
    if not isinstance(board_name, str) or not board_name.strip():
        return None, "missing", "blank_board_player"

    # exact match first
    if (players == board_name).any():
        return board_name, "exact", ""

    bk = player_key(board_name)
    if not bk:
        return None, "missing", "blank_player_key"

    # normalized exact
    if bk in key_map:
        cands = key_map[bk]
        if len(cands) == 1:
            return cands[0], "norm_unique", ""
        else:
            # deterministic pick: shortest name (usually base), then alpha
            cands_sorted = sorted(cands, key=lambda x: (len(x), x))
            return cands_sorted[0], "norm_multi_pick", f"multiple_matches:{len(cands)}"

    return None, "unmatched", "no_name_match"


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    if not GAMELOGS_CSV.exists():
        raise SystemExit(f"Missing gamelogs CSV: {GAMELOGS_CSV}")

    g = pd.read_csv(GAMELOGS_CSV)

    required_cols = {"game_date","player","minutes","pts","reb","ast","fg3m"}
    missing = required_cols - set(g.columns)
    if missing:
        raise SystemExit(f"nba_gamelogs.csv missing columns: {sorted(missing)}")

    # parse dates
    g["game_date"] = pd.to_datetime(g["game_date"], errors="coerce")
    g = g.dropna(subset=["game_date"])

    # played games only (this is the injury/rest/trade fix)
    g["minutes"] = pd.to_numeric(g["minutes"], errors="coerce").fillna(0)
    g_played = g[g["minutes"] > 0].copy()

    # numeric stats
    for c in ["pts","reb","ast","fg3m"]:
        g_played[c] = pd.to_numeric(g_played[c], errors="coerce")

    # board player list
    if not BOARD_CSV.exists():
        raise SystemExit(f"Missing board CSV: {BOARD_CSV} (expected it to list today's board players)")

    b = pd.read_csv(BOARD_CSV)
    if "player" not in b.columns:
        raise SystemExit(f"{BOARD_CSV} missing required column: player")

    board_players = sorted(set(str(x).strip() for x in b["player"].dropna().tolist() if str(x).strip()))

    # build key map over gamelog players
    unique_players = pd.Series(sorted(set(g_played["player"].dropna().astype(str).tolist())))
    key_map: dict[str, list[str]] = {}
    for p in unique_players:
        k = player_key(p)
        if not k:
            continue
        key_map.setdefault(k, []).append(p)

    out_rows = []

    for bp in board_players:
        resolved, method, reason = resolve_player(bp, unique_players, key_map)

        row = {
            "board_player": bp,
            "resolved_player": resolved if resolved is not None else "",
            "resolution_method": method,
            "team": "",  # optional metadata; DO NOT use as join key
            "latest_game_date": "",
            "last5_n_games": 0,
            "last5_minutes": "",
            "last5_pts": "",
            "last5_reb": "",
            "last5_ast": "",
            "last5_fg3m": "",
            "last5_pts_avg": "",
            "last5_reb_avg": "",
            "last5_ast_avg": "",
            "last5_fg3m_avg": "",
            "last5_pr_avg": "",
            "last5_pa_avg": "",
            "last5_ra_avg": "",
            "last5_pra_avg": "",
            "note": "",
            "unmatched_reason": reason,
        }

        if resolved is None:
            row["note"] = "UNMATCHED"
            out_rows.append(row)
            continue

        gp = g_played[g_played["player"] == resolved].sort_values("game_date", ascending=False).head(N_LAST)

        n = int(len(gp))
        row["last5_n_games"] = n

        if n == 0:
            row["note"] = "NO_PLAYED_GAMES"
            out_rows.append(row)
            continue

        row["latest_game_date"] = gp["game_date"].iloc[0].date().isoformat()

        mins = gp["minutes"].fillna(0).astype(int).tolist()
        pts  = gp["pts"].fillna(0).astype(int).tolist()
        reb  = gp["reb"].fillna(0).astype(int).tolist()
        ast  = gp["ast"].fillna(0).astype(int).tolist()
        fg3  = gp["fg3m"].fillna(0).astype(int).tolist()

        row["last5_minutes"] = seq_to_pipe(mins)
        row["last5_pts"]     = seq_to_pipe(pts)
        row["last5_reb"]     = seq_to_pipe(reb)
        row["last5_ast"]     = seq_to_pipe(ast)
        row["last5_fg3m"]    = seq_to_pipe(fg3)

        # averages (blank if missing)
        pts_avg  = mean_or_blank(pts)
        reb_avg  = mean_or_blank(reb)
        ast_avg  = mean_or_blank(ast)
        fg3_avg  = mean_or_blank(fg3)

        def fmt(x):
            return "" if x is None else round(x, 3)

        row["last5_pts_avg"]  = fmt(pts_avg)
        row["last5_reb_avg"]  = fmt(reb_avg)
        row["last5_ast_avg"]  = fmt(ast_avg)
        row["last5_fg3m_avg"] = fmt(fg3_avg)

        # combos (only if components exist)
        if pts_avg is not None and reb_avg is not None:
            row["last5_pr_avg"] = fmt(pts_avg + reb_avg)
        if pts_avg is not None and ast_avg is not None:
            row["last5_pa_avg"] = fmt(pts_avg + ast_avg)
        if reb_avg is not None and ast_avg is not None:
            row["last5_ra_avg"] = fmt(reb_avg + ast_avg)
        if pts_avg is not None and reb_avg is not None and ast_avg is not None:
            row["last5_pra_avg"] = fmt(pts_avg + reb_avg + ast_avg)

        row["note"] = "OK"
        out_rows.append(row)

    out = pd.DataFrame(out_rows)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    print(f"Wrote: {OUT_CSV} (rows={len(out)})")
    print("Coverage:")
    print(out["note"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()

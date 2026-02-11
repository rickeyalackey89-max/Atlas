from __future__ import annotations

"""
src/features.py

Chokepoint for:
- Strategy B name resolution (board player names -> gamelog player names)
- Basic stat summarization utilities used by src/probability.py

Key invariants:
- Never silently pick an ambiguous match (2+ contains hits).
- Unresolved => empty window (games_used becomes 0 downstream), but this should be rare
  and auditable via gamelog audit outputs.

CONTRACT (IMPORTANT):
- summarize_stat(window, stat) must return a dict-like object (pd.Series is fine) with:
    - min_mean
    - min_std
    - rate_mean
    - rate_std
    - games
  because src/probability.py indexes these keys directly.
"""

from typing import Dict, Iterable, Optional, Tuple
import unicodedata as ud

import pandas as pd


# PrizePicks / model stat codes -> gamelog column(s) to sum
STAT_COLS: Dict[str, Iterable[str]] = {
    "PTS": ("pts",),
    "REB": ("reb",),
    "AST": ("ast",),
    "FG3M": ("fg3m",),
    # combos
    "PR": ("pts", "reb"),
    "PA": ("pts", "ast"),
    "RA": ("reb", "ast"),
    "PRA": ("pts", "reb", "ast"),
}

# Strategy B aliases (board -> gamelog)
ALIASES: Dict[str, str] = {
    "Derrick Jones": "Derrick Jones Jr.",
    "Jaime Jaquez": "Jaime Jaquez Jr.",
    # Add more explicit mappings over time if needed
}


def _norm_key(s: str) -> str:
    """
    Normalize for robust contains matching:
      - Unicode NFKD
      - strip diacritics (combining marks)
      - lowercase
      - collapse whitespace
    """
    s = (s or "").strip()
    if not s:
        return ""
    s = ud.normalize("NFKD", s)
    s = "".join(ch for ch in s if not ud.combining(ch))
    s = " ".join(s.lower().split())
    return s


def resolve_player_name(board_player: str, gamelog_players: Iterable[str]) -> Tuple[Optional[str], str]:
    """
    Strategy B:
      1) exact match
      2) alias match (board -> gamelog)
      3) unique contains match (diacritic-safe), only if 1 unique hit

    Returns: (resolved_name or None, method)
      method in: exact, alias, contains_unique, unresolved, ambiguous
    """
    board_player = (board_player or "").strip()
    if not board_player:
        return None, "unresolved"

    players = [str(p) for p in gamelog_players if isinstance(p, str) and str(p).strip()]
    if board_player in players:
        return board_player, "exact"

    if board_player in ALIASES:
        target = ALIASES[board_player]
        if target in players:
            return target, "alias"

    q = _norm_key(board_player)
    if not q:
        return None, "unresolved"

    # diacritic-safe contains matching
    hits = [p for p in players if q in _norm_key(p)]
    hits = list(dict.fromkeys(hits))  # preserve order, unique

    if len(hits) == 1:
        return hits[0], "contains_unique"
    if len(hits) > 1:
        return None, "ambiguous"
    return None, "unresolved"


def get_player_window(gamelogs: pd.DataFrame, player: str, lookback: int) -> pd.DataFrame:
    """
    Return the most recent `lookback` rows for a player from gamelogs.

    Expects a 'game_date' column in gamelogs.
    Applies Strategy B name resolution so board names map to gamelog identities.

    If unresolved/ambiguous, returns empty df.
    """
    if gamelogs is None or gamelogs.empty:
        return gamelogs.iloc[0:0].copy()

    g = gamelogs.copy()

    if "game_date" in g.columns:
        g["game_date"] = pd.to_datetime(g["game_date"], errors="coerce")

    if "player" not in g.columns:
        return g.iloc[0:0].copy()

    resolved, _method = resolve_player_name(player, g["player"].astype(str).unique().tolist())
    if not resolved:
        return g.iloc[0:0].copy()

    gg = g[g["player"] == resolved].copy()
    if "game_date" in gg.columns:
        gg = gg.sort_values("game_date", ascending=False)

    return gg.head(int(lookback)).copy()


def validate_gamelog_columns_for_stat(gamelogs: pd.DataFrame, stat: str) -> None:
    stat = (stat or "").upper().strip()
    needed = list(STAT_COLS.get(stat, ()))
    if not needed:
        return
    missing = [c for c in needed if c not in gamelogs.columns]
    if missing:
        raise ValueError(f"Missing required columns in gamelogs for stat={stat}: {missing}")


def _empty_summary() -> pd.Series:
    # Must satisfy src/probability.py indexing contract
    return pd.Series(
        {
            "min_mean": 0.0,
            "min_std": 0.0,
            "rate_mean": 0.0,
            "rate_std": 0.0,
            "games": 0,
        }
    )


def summarize_stat(window: pd.DataFrame, stat: str) -> pd.Series:
    """
    CONTRACT RESTORE: Return aggregated summary stats required by src/probability.py.

    Expected keys:
      - min_mean: mean minutes over window
      - min_std:  std minutes (ddof=0)
      - rate_mean: mean(stat/minute) over games with minutes>0
      - rate_std:  std(stat/minute) (ddof=0)
      - games: count of games in the window

    Notes:
      - If window empty or required columns missing => return zeros + games=0.
      - This function does NOT apply any modeling/tuning; it only computes summaries.
    """
    if window is None or window.empty:
        return _empty_summary()

    stat = (stat or "").upper().strip()
    cols = STAT_COLS.get(stat)
    if not cols:
        return _empty_summary()

    # Minutes series (robust)
    if "minutes" in window.columns:
        mins = pd.to_numeric(window["minutes"], errors="coerce")
    else:
        # No minutes column => cannot compute rates; return zeros
        return _empty_summary()

    # Stat totals per game
    total = None
    for c in cols:
        if c not in window.columns:
            return _empty_summary()
        s = pd.to_numeric(window[c], errors="coerce").fillna(0.0)
        total = s if total is None else (total + s)

    if total is None:
        return _empty_summary()

    games = int(len(total))

    # Stat-per-minute rates (only where minutes > 0)
    valid = mins.gt(0) & mins.notna()
    if valid.any():
        rates = (total[valid] / mins[valid]).astype("float64")
    else:
        rates = pd.Series(dtype="float64")

    # Aggregates (ddof=0 to keep stable for small samples)
    min_mean = float(mins.mean()) if len(mins) > 0 else 0.0
    min_std = float(mins.std(ddof=0)) if len(mins) > 1 else 0.0

    rate_mean = float(rates.mean()) if len(rates) > 0 else 0.0
    rate_std = float(rates.std(ddof=0)) if len(rates) > 1 else 0.0

    return pd.Series(
        {
            "min_mean": min_mean,
            "min_std": min_std,
            "rate_mean": rate_mean,
            "rate_std": rate_std,
            "games": games,
        }
    )


def blowout_probability(*args, **kwargs) -> float:
    """
    Compatibility shim.

    Some versions of the pipeline import blowout_probability from features.
    Blowout modeling lives elsewhere (minutes/matchup enrichment). We keep this
    function so src/probability.py can import it without breaking.

    Returns:
      float in [0, 1]. Default 0.0 => no blowout adjustment from this shim.
    """
    return 0.0
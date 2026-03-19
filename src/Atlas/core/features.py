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

import numpy as np
import pandas as pd

# PrizePicks / model stat codes -> gamelog column(s) to sum
STAT_COLS: Dict[str, tuple[str, ...]] = {
    "PTS": ("pts",),
    "REB": ("reb",),
    "AST": ("ast",),
    "FG3M": ("fg3m",),
    "3PM": ("fg3m",),  # alias
    # combos
    "PR": ("pts", "reb"),
    "PA": ("pts", "ast"),
    "RA": ("reb", "ast"),
    "PRA": ("pts", "reb", "ast"),
    # pipeline-specific combos used elsewhere in your codebase
    "PTS_AST": ("pts", "ast"),
    "PTS_REB": ("pts", "reb"),
    "REB_AST": ("reb", "ast"),
    "BLKS_STLS": ("blk", "stl"),
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
    return " ".join(s.lower().split())


def resolve_player_name(board_player: str, gamelog_players: Iterable[object]) -> Tuple[Optional[str], str]:
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

    # robust list of names (do not drop numpy.str_ / non-str objects)
    players: list[str] = []
    for p in gamelog_players or []:
        if p is None:
            continue
        s = str(p).strip()
        if s:
            players.append(s)

    if not players:
        return None, "unresolved"

    # exact
    if board_player in players:
        return board_player, "exact"

    # alias
    target = ALIASES.get(board_player)
    if target and target in players:
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

    Performance notes:
    - Do NOT copy the full gamelogs dataframe (too expensive in tight loops).
    - Cache the gamelog player list on `gamelogs.attrs` so we don't rebuild it per call.
    - Only copy the final small window we return.
    """
    if gamelogs is None or gamelogs.empty:
        return gamelogs.iloc[0:0].copy()

    if "player" not in gamelogs.columns:
        return gamelogs.iloc[0:0].copy()

    lookback = int(max(0, lookback))

    # Cache the unique player list once per gamelogs instance
    players = gamelogs.attrs.get("_atlas_players_unique")
    if players is None:
        players = gamelogs["player"].astype(str).dropna().unique().tolist()
        gamelogs.attrs["_atlas_players_unique"] = players

    resolved, _method = resolve_player_name(player, players)
    if not resolved:
        return gamelogs.iloc[0:0].copy()

    # Filter first (cheap)
    gg = gamelogs.loc[gamelogs["player"] == resolved]
    if gg.empty:
        return gg.copy()

    # Sort on subset only
    if "game_date" in gg.columns:
        game_date = pd.to_datetime(gg["game_date"], errors="coerce")
        gg = gg.assign(game_date=game_date).sort_values("game_date", ascending=False)

    return gg.head(lookback).copy()


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
    CONTRACT: Return aggregated summary stats required by src/probability.py.

    Keys:
      - min_mean: mean minutes over window
      - min_std:  std minutes (ddof=0)
      - rate_mean: mean(stat/minute) over games with minutes>0
      - rate_std:  std(stat/minute) (ddof=0)
      - games: count of games in the window
    """
    if window is None or window.empty:
        return _empty_summary()

    stat = (stat or "").upper().strip()
    cols = STAT_COLS.get(stat)
    if not cols:
        return _empty_summary()

    if "minutes" not in window.columns:
        return _empty_summary()

    mins = pd.to_numeric(window["minutes"], errors="coerce")
    if mins.isna().all():
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

    games = int(len(window))

    valid = mins.notna() & mins.gt(0)
    rates = (total[valid] / mins[valid]).astype("float64") if valid.any() else pd.Series(dtype="float64")

    # Use numpy to avoid pandas corner cases; ddof=0 per your contract
    min_vals = mins.dropna().to_numpy(dtype=float)
    min_mean = float(np.mean(min_vals)) if min_vals.size else 0.0
    min_std = float(np.std(min_vals, ddof=0)) if min_vals.size > 1 else 0.0

    rate_vals = rates.dropna().to_numpy(dtype=float)
    rate_mean = float(np.mean(rate_vals)) if rate_vals.size else 0.0
    rate_std = float(np.std(rate_vals, ddof=0)) if rate_vals.size > 1 else 0.0

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
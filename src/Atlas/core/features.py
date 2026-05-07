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
    "FTA": ("fta",),
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


def summarize_stat(window: pd.DataFrame, stat: str, *, recency_halflife: float | None = None) -> pd.Series:
    """
    CONTRACT: Return aggregated summary stats required by src/probability.py.

    Keys:
      - min_mean: mean minutes over window
      - min_std:  std minutes (ddof=0)
      - rate_mean: mean(stat/minute) over games with minutes>0
      - rate_std:  std(stat/minute) (ddof=0)
      - games: count of games in the window

    If recency_halflife is set (in games), exponential decay weighting is
    applied so recent games matter more.  halflife=10 means the weight of
    a game 10 games ago is 0.5× the most-recent game.
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
    rate_vals = rates.dropna().to_numpy(dtype=float)

    if recency_halflife is not None and recency_halflife > 0:
        # Window is already sorted descending by date (index 0 = most recent).
        # Build exponential decay weights: w_i = exp(-ln2 * i / halflife)
        hl = float(recency_halflife)
        min_w = np.exp(-np.log(2) * np.arange(len(min_vals)) / hl) if min_vals.size else np.array([])
        rate_w = np.exp(-np.log(2) * np.arange(len(rate_vals)) / hl) if rate_vals.size else np.array([])

        def _wmean(v, w):
            return float(np.average(v, weights=w)) if v.size else 0.0

        def _wstd(v, w):
            if v.size < 2:
                return 0.0
            mu = np.average(v, weights=w)
            return float(np.sqrt(np.average((v - mu) ** 2, weights=w)))

        min_mean = _wmean(min_vals, min_w)
        min_std = _wstd(min_vals, min_w)
        rate_mean = _wmean(rate_vals, rate_w)
        rate_std = _wstd(rate_vals, rate_w)
    else:
        min_mean = float(np.mean(min_vals)) if min_vals.size else 0.0
        min_std = float(np.std(min_vals, ddof=0)) if min_vals.size > 1 else 0.0
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


def compute_recent_form(window: pd.DataFrame, stat: str, recent_n: int = 10) -> dict:
    """
    Compute rolling recent-form rate from the player's game window.

    Returns dict with:
      - recent_rate_mean: per-minute rate over last `recent_n` games
      - recent_games: how many games were used
    """
    if window is None or window.empty:
        return {"recent_rate_mean": None, "recent_games": 0}

    stat = (stat or "").upper().strip()
    cols = STAT_COLS.get(stat)
    if not cols:
        return {"recent_rate_mean": None, "recent_games": 0}

    if "minutes" not in window.columns:
        return {"recent_rate_mean": None, "recent_games": 0}

    # Window is already sorted descending by date (head = most recent)
    recent = window.head(recent_n)
    mins = pd.to_numeric(recent["minutes"], errors="coerce")

    total = None
    for c in cols:
        if c not in recent.columns:
            return {"recent_rate_mean": None, "recent_games": 0}
        s = pd.to_numeric(recent[c], errors="coerce").fillna(0.0)
        total = s if total is None else (total + s)

    valid = mins.notna() & mins.gt(0)
    if not valid.any() or total is None:
        return {"recent_rate_mean": None, "recent_games": 0}

    rates = (total[valid] / mins[valid]).to_numpy(dtype=float)
    return {
        "recent_rate_mean": float(np.mean(rates)) if rates.size else None,
        "recent_games": int(valid.sum()),
    }


def compute_opp_defense_factor(
    gamelogs: pd.DataFrame,
    opp_team: str,
    stat: str,
    *,
    lookback: int = 10,
) -> float:
    """
    Compute how much a given opponent allows relative to league average
    for the given stat (per-minute rate).

    Returns a multiplicative factor: >1.0 means opponent is soft (allows more),
    <1.0 means tough defense. Returns 1.0 if insufficient data.

    Uses a cache on gamelogs.attrs to avoid recomputing for every leg.
    """
    stat = (stat or "").upper().strip()
    cols = STAT_COLS.get(stat)
    if not cols or gamelogs is None or gamelogs.empty:
        return 1.0

    opp_team = (opp_team or "").upper().strip()
    if not opp_team or "opp" not in gamelogs.columns or "minutes" not in gamelogs.columns:
        return 1.0

    for c in cols:
        if c not in gamelogs.columns:
            return 1.0

    # Use cache to avoid recomputing per-stat league & opp stats each call
    cache_key = "_atlas_opp_defense_cache"
    cache = gamelogs.attrs.get(cache_key)
    if cache is None:
        cache = {}
        gamelogs.attrs[cache_key] = cache

    lookup_key = (opp_team, stat)
    if lookup_key in cache:
        return cache[lookup_key]

    # Compute league-mean rate for this stat (cached per stat)
    league_key = ("_league", stat)
    if league_key not in cache:
        mins = pd.to_numeric(gamelogs["minutes"], errors="coerce")
        valid_mins = mins.notna() & mins.gt(0)
        total = None
        for c in cols:
            s = pd.to_numeric(gamelogs[c], errors="coerce").fillna(0.0)
            total = s if total is None else (total + s)
        if total is None or not valid_mins.any():
            cache[lookup_key] = 1.0
            return 1.0
        rates = (total[valid_mins] / mins[valid_mins]).astype(float)
        cache[league_key] = float(rates.mean()) if rates.size else 0.0
        # Also store pre-computed arrays for reuse
        cache[("_mins", stat)] = mins
        cache[("_valid", stat)] = valid_mins
        cache[("_total", stat)] = total

    league_mean = cache[league_key]
    if league_mean <= 0:
        cache[lookup_key] = 1.0
        return 1.0

    mins = cache[("_mins", stat)]
    valid_mins = cache[("_valid", stat)]
    total = cache[("_total", stat)]

    # Filter to games against this opponent
    opp_col = gamelogs["opp"].astype(str).str.upper().str.strip()
    opp_mask = (opp_col == opp_team) & valid_mins
    if opp_mask.sum() < 3:
        cache[lookup_key] = 1.0
        return 1.0

    opp_rates = (total[opp_mask] / mins[opp_mask]).astype(float)
    opp_mean = float(opp_rates.mean())

    if opp_mean <= 0:
        cache[lookup_key] = 1.0
        return 1.0

    result = float(opp_mean / league_mean)
    cache[lookup_key] = result
    return result


def compute_pace_factor(
    gamelogs: pd.DataFrame,
    team: str,
    opp_team: str,
    *,
    lookback: int = 10,
) -> float:
    """
    Compute the expected game pace relative to league average.

    Pace proxy = (FGA + 0.44*FTA + TOV) per 240 team-minutes.
    Game pace is the average of both teams' recent paces.
    Returns a factor centered at 0: positive means faster than average.
    Returns 0.0 if insufficient data.
    """
    if gamelogs is None or gamelogs.empty:
        return 0.0

    for c in ("fga", "fta", "tov", "minutes", "team"):
        if c not in gamelogs.columns:
            return 0.0

    team = (team or "").upper().strip()
    opp_team = (opp_team or "").upper().strip()
    if not team or not opp_team:
        return 0.0

    cache_key = "_atlas_pace_cache"
    cache = gamelogs.attrs.get(cache_key)
    if cache is None:
        cache = {}
        gamelogs.attrs[cache_key] = cache

    lookup_key = (team, opp_team)
    if lookup_key in cache:
        return cache[lookup_key]

    # Build team-game pace table (cached once per gamelogs df)
    if "_team_pace" not in cache:
        gl = gamelogs.copy()
        gl["_fga"] = pd.to_numeric(gl["fga"], errors="coerce").fillna(0)
        gl["_fta"] = pd.to_numeric(gl["fta"], errors="coerce").fillna(0)
        gl["_tov"] = pd.to_numeric(gl["tov"], errors="coerce").fillna(0)
        gl["_min"] = pd.to_numeric(gl["minutes"], errors="coerce").fillna(0)
        gl["_team"] = gl["team"].astype(str).str.upper().str.strip()
        gl["_gd"] = pd.to_datetime(gl.get("game_date", pd.Series(dtype="object")), errors="coerce")

        tg = gl.groupby(["_team", "_gd"]).agg(
            fga=("_fga", "sum"), fta=("_fta", "sum"),
            tov=("_tov", "sum"), mins=("_min", "sum"),
        ).reset_index()
        tg = tg[tg["mins"] > 100]  # at least ~half a game of data
        tg["pace"] = (tg["fga"] + 0.44 * tg["fta"] + tg["tov"]) / np.maximum(1, tg["mins"]) * 240
        tg = tg.sort_values(["_team", "_gd"])

        league_pace = float(tg["pace"].mean()) if len(tg) else 112.0

        # Rolling lookback-game average per team (most recent N games)
        team_rolling = {}
        for t, grp in tg.groupby("_team"):
            recent = grp.tail(lookback)
            if len(recent) >= 3:
                team_rolling[t] = float(recent["pace"].mean())

        cache["_team_pace"] = team_rolling
        cache["_league_pace"] = league_pace

    team_rolling = cache["_team_pace"]
    league_pace = cache["_league_pace"]

    team_pace = team_rolling.get(team)
    opp_pace = team_rolling.get(opp_team)

    if team_pace is None or opp_pace is None:
        cache[lookup_key] = 0.0
        return 0.0

    game_pace = (team_pace + opp_pace) / 2.0
    result = float(game_pace / league_pace - 1.0)
    cache[lookup_key] = result
    return result


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
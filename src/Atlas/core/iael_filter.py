"""IAEL hard filter (Phase 7B extraction)

This module is the NewEngine authority for applying the IAEL invalidations list
as a HARD removal filter over leg rows.

Extracted from: LegacyEngine.main.apply_iael_hard_filter (kept 1:1).
"""

from __future__ import annotations

from typing import Any
import re

import pandas as pd


_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.IGNORECASE)


def normalize_person_name(name: Any) -> str:
    """Order-insensitive name normalization for robust IAEL matching."""
    s = "" if name is None else str(name)
    s = s.strip().lower()

    # critical: 'Last,First' -> 'Last First'
    s = s.replace(",", " ")

    s = s.replace("’", "'")
    s = s.replace(".", " ")
    s = s.replace("-", " ")

    # keep letters/numbers/apostrophes/spaces only
    s = re.sub(r"[^\w\s']", " ", s)

    # drop suffixes
    s = _SUFFIX_RE.sub("", s)

    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""

    # critical: order-insensitive match
    tokens = [t for t in s.split(" ") if t]
    tokens.sort()
    return " ".join(tokens)


def normalize_team_token(team: Any) -> str:
    return ("" if team is None else str(team)).strip().upper()


def apply_iael_hard_filter(
    legs_df: pd.DataFrame,
    iael_df: pd.DataFrame,
    *,
    hard_statuses: set[str] | None = None,
    require_team_match: bool = False,
) -> pd.DataFrame:
    """
    HARD FILTER: remove legs whose player is invalidated (OUT/DOUBTFUL/QUESTIONABLE).

    - If require_team_match=False (default), match by player only (safer if your legs don't have team).
    - If require_team_match=True, will match by (team, player) when legs_df has a usable team column.
    """
    if legs_df is None or legs_df.empty:
        return legs_df
    if iael_df is None or iael_df.empty:
        print("[IAEL][WARN] IAEL invalidations empty -> no injury filtering applied.")
        return legs_df

    hard_statuses = hard_statuses or {"OUT", "DOUBTFUL", "QUESTIONABLE"}
    iael = iael_df.copy()
    iael = iael[iael["status"].isin(set(s.upper() for s in hard_statuses))].copy()
    if iael.empty:
        print("[IAEL][DEBUG] IAEL present but no rows in hard statuses; no filtering applied.")
        return legs_df

    df = legs_df.copy()
    df["player_norm"] = df.get("player", pd.Series("", index=df.index)).apply(normalize_person_name)

    # Attempt team mapping if requested and possible
    team_col = None
    if require_team_match:
        for c in ["team", "team_abbrev", "team_code", "home_team", "away_team", "opponent_team", "opp_team"]:
            if c in df.columns:
                team_col = c
                break

    before = len(df)

    if require_team_match and team_col is not None:
        df["team_norm"] = df[team_col].apply(normalize_team_token)
        bad = iael[["team_norm", "player_norm"]].drop_duplicates()
        merged = df.merge(bad, on=["team_norm", "player_norm"], how="left", indicator=True)
        removed = int((merged["_merge"] == "both").sum())
        out = merged[merged["_merge"] == "left_only"].copy()
        out.drop(columns=["_merge", "player_norm", "team_norm"], errors="ignore", inplace=True)
    else:
        bad_players = set(iael["player_norm"].astype(str))
        mask_bad = df["player_norm"].astype(str).isin(bad_players)
        removed = int(mask_bad.sum())
        out = df[~mask_bad].copy()
        out.drop(columns=["player_norm"], errors="ignore", inplace=True)

    print(f"[IAEL] Removed {removed} legs out of {before} (statuses={sorted(hard_statuses)})")
    if removed > 0:
        # quick sample
        try:
            sample_players = (
                df[df["player_norm"].isin(set(iael["player_norm"]))][["player"]]
                .drop_duplicates()
                .head(12)
            )
            print("[IAEL] Sample removed:\n" + sample_players.to_string(index=False))
        except Exception:
            pass

    return out.reset_index(drop=True)

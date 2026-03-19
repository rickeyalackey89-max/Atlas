from __future__ import annotations

import pandas as pd


def dedupe_over_under(scored: pd.DataFrame) -> pd.DataFrame:
    """
    Dedupe identical rows, but DO NOT collapse OVER vs UNDER.
    Key fix: include direction in prop_key.

    IMPORTANT:
    - Do not use DataFrame.get(..., "") for columns that will be .astype()'d.
      If the column is missing, .get returns a scalar (""), which has no .astype.
    - Always ensure required columns exist as Series before casting.
    """
    out = scored.copy()

    # Ensure required columns exist (avoid scalar defaults from .get)
    if "player" not in out.columns:
        out["player"] = ""
    if "stat" not in out.columns:
        out["stat"] = ""
    if "tier" not in out.columns:
        out["tier"] = "STANDARD"
    if "direction" not in out.columns:
        out["direction"] = ""
    if "line" not in out.columns:
        out["line"] = pd.NA

    # Canonicalize types/format
    out["player"] = out["player"].fillna("").astype(str).str.strip()
    out["stat"] = out["stat"].fillna("").astype(str).str.upper().str.strip()
    out["tier"] = out["tier"].fillna("STANDARD").astype(str).str.upper().str.strip()
    out["direction"] = out["direction"].fillna("").astype(str).str.upper().str.strip()

    out["line"] = pd.to_numeric(out["line"], errors="coerce")

    # Build stable key (direction included; line coerced to string)
    out["prop_key"] = (
        out["player"]
        + "|"
        + out["stat"]
        + "|"
        + out["direction"]
        + "|"
        + out["line"].astype(str)
        + "|"
        + out["tier"]
    )

    if "p_adj" in out.columns:
        base_raw = out["p_adj"]
    elif "p" in out.columns:
        base_raw = out["p"]
    else:
        base_raw = pd.Series(0.50, index=out.index)

    out["p_adj"] = pd.to_numeric(base_raw, errors="coerce").fillna(0.50).clip(0, 1)

    out = out.sort_values(by=["prop_key", "p_adj"], ascending=[True, False], na_position="last")
    return out.drop_duplicates(subset=["prop_key"], keep="first").reset_index(drop=True)
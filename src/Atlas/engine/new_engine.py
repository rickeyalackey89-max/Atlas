from __future__ import annotations

"""
New engine scoring kernel (v18).

Scores each board row through simulate_leg_probability_new, then applies
calibration and the Phase 7A-2 / 7A-3 post-processing pipeline.

Entry point used by main.py:  _run_score_board_new()
"""

from typing import Any, Optional
from pathlib import Path
import builtins as _b  # prevents shadowed int/float/str from breaking static analysis

import numpy as np
import pandas as pd

from Atlas.core.share_name_key import share_name_key

__all__ = ["_run_score_board_new"]


def _player_key(name: Any) -> str:
    """Local alias for the shared canonical player join key."""
    return share_name_key(name)

def _normalize_iael_for_kernel(iael_df: pd.DataFrame | None) -> pd.DataFrame:
    """
    Kernel expects columns like: team, out_player, status (case-insensitive).
    Your invalidations often look like: team_norm, player_norm, status.
    Return a DataFrame in the kernel format (or empty DF).
    """
    if iael_df is None or not isinstance(iael_df, pd.DataFrame) or iael_df.empty:
        return pd.DataFrame()

    cols = {c.lower(): c for c in iael_df.columns}

    # Already in expected-ish format?
    if "team" in cols and ("out_player" in cols or "player" in cols) and "status" in cols:
        out = iael_df.copy()
        if "out_player" not in cols and "player" in cols:
            out = out.rename(columns={cols["player"]: "out_player"})
        else:
            out = out.rename(columns={cols["team"]: "team", cols["status"]: "status", cols["out_player"]: "out_player"})
        if "player_key" in cols:
            out = out.rename(columns={cols["player_key"]: "player_key"})
        elif "out_player" in out.columns:
            out["player_key"] = out["out_player"].astype(str).map(_player_key)
        return out[["team", "out_player", "player_key", "status"]].copy()

    # Normalize from invalidations schema
    if "team_norm" in cols and "player_norm" in cols and "status" in cols:
        # Prefer the original player name (Last, First format) over the pre-sorted player_norm.
        # share_name_key() correctly handles "Last, First" -> "first last" canonical form,
        # but if we pass the already-sorted player_norm it can't recover the right order
        # (e.g. "divincenzo donte" vs the correct "donte divincenzo" from share_name_key).
        player_col = cols.get("player") or cols.get("player_norm")
        out = iael_df.rename(
            columns={
                cols["team_norm"]: "team",
                player_col: "out_player",
                cols["status"]: "status",
            }
        ).copy()
        if "player_key" in cols:
            out = out.rename(columns={cols["player_key"]: "player_key"})
        else:
            out["player_key"] = out["out_player"].astype(str).map(_player_key)
        out["team"] = out["team"].astype(str).str.upper().str.strip()
        out["out_player"] = out["out_player"].astype(str).str.strip()
        out["player_key"] = out["player_key"].astype(str).str.strip()
        out["status"] = out["status"].astype(str).str.upper().str.strip()
        return out[["team", "out_player", "player_key", "status"]].copy()

    return pd.DataFrame()

def _run_score_board_new(
    *,
    board: pd.DataFrame,
    logs: pd.DataFrame,
    cfg: dict[str, Any],
    iael_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Strict-parity clone of Atlas.stages.score.score_board.run_score_board, but
    calling the relocated kernel in Atlas.engine.new_probability.

    Pylance-safe:
      - Iterate via board.to_dict(orient="records") to avoid itertuples/_asdict typing weirdness.
      - Force dict keys to str before unpacking.
    """
    from Atlas.core.minutes import minutes_sensitivity
    from Atlas.engine.new_probability import simulate_leg_probability_new

    if board is None or not isinstance(board, pd.DataFrame):
        raise TypeError(f"board must be a pandas DataFrame, got: {type(board)!r}")
    if logs is None or not isinstance(logs, pd.DataFrame):
        raise TypeError(f"logs must be a pandas DataFrame, got: {type(logs)!r}")

    lookback = _b.int(cfg.get("lookback_games", 50))
    sims = _b.int(cfg.get("simulations", 10000))

    blow = cfg.get("blowout", {}) or {}
    spread_sd = _b.float(blow.get("spread_sd", 9.5))
    threshold = _b.float(blow.get("threshold_margin", 15))
    star_drop = _b.float(blow.get("star_minute_drop", 0.12))
    role_drop = _b.float(blow.get("role_minute_drop", 0.20))

    # Minimal wiring only: pull role_ctx config once, pass-through to kernel.
    role_cfg = cfg.get("role_ctx") or None

    # Build team/matchup blowout stats once for enriched q
    from Atlas.engine.new_probability import _build_blowout_team_stats
    _blowout_team_stats = _build_blowout_team_stats(logs, threshold=threshold)
    if _blowout_team_stats:
        blow["_blowout_team_stats"] = _blowout_team_stats

    # Series game lookup: playoff game number for each (team_pair, game_date).
    _series_cfg = blow.get("series_multiplier", {}) or {}
    if _series_cfg.get("enabled", False):
        _series_start = str(_series_cfg.get("start_date", "2026-04-30"))
        _series_lookup: dict[tuple, int] = {}
        try:
            _gl = logs.copy()
            _gl["game_date"] = pd.to_datetime(_gl["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            _po_gl = _gl[_gl["game_date"] >= _series_start]
            if not _po_gl.empty and {"team", "opp"}.issubset(_po_gl.columns):
                _pairs = _po_gl[["team", "opp", "game_date"]].dropna().drop_duplicates()
                _pairs["pair"] = _pairs.apply(
                    lambda r: tuple(sorted([str(r["team"]).upper(), str(r["opp"]).upper()])), axis=1
                )
                for _pair, _grp in _pairs.groupby("pair"):
                    _dates = sorted(_grp["game_date"].unique())
                    for _gn, _gd in enumerate(_dates, start=1):
                        _series_lookup[(_pair, _gd)] = _gn
        except Exception:
            pass
        blow["_series_game_lookup"] = _series_lookup

    rows: list[dict[str, Any]] = []

    iael_df_kernel = _normalize_iael_for_kernel(iael_df)

    for rec in board.to_dict(orient="records"):
        # Enforce string keys (prevents Pylance complaining about Hashable/Unknown keys)
        row_dict: dict[str, Any] = {str(k): v for k, v in rec.items()}

        if "minutes_s" not in row_dict:
            stat = _b.str(row_dict.get("stat", "")).upper()
            row_dict["minutes_s"] = _b.float(minutes_sensitivity(stat))

        # Kernel expects a Series-like row
        row_series = pd.Series(row_dict)

        info = simulate_leg_probability_new(
            gamelogs=logs,
            row=row_series,
            lookback=lookback,
            sims=sims,
            spread_sd=spread_sd,
            blowout_threshold=threshold,
            star_minute_drop=star_drop,
            role_minute_drop=role_drop,
            iael_df=iael_df_kernel,
            role_cfg=role_cfg,
            blowout_cfg=blow,
        ) or {}

        # Enforce string keys in kernel output too
        info2: dict[str, Any] = {str(k): v for k, v in info.items()}

        # Ensure p_adj exists at scoring time (prevents downstream fallbacks masking issues)
        if "p" in info2 and "p_adj" not in info2:
            info2["p_adj"] = info2.get("p")

        games_used = _b.int(info2.get("games_used", 0) or 0)
        data_health_flag = "OK" if games_used > 0 else "DATA_MISSING"

        rows.append({**row_dict, **info2, "data_health_flag": data_health_flag})

    return pd.DataFrame(rows)
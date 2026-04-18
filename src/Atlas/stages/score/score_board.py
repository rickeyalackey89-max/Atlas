from __future__ import annotations

from typing import Any

import pandas as pd

from Atlas.core.minutes import minutes_sensitivity
from Atlas.engine.new_probability import simulate_leg_probability_new


def run_score_board(
    board: pd.DataFrame,
    logs: pd.DataFrame,
    cfg: dict[str, Any],
    iael_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Deterministic Score Stage.

    Pure transform:
        board + logs + cfg + iael_df -> scored DataFrame

    No IO.
    No printing.
    No side effects.
    """

    lookback = int(cfg.get("lookback_games", 50))
    sims = int(cfg.get("simulations", 10000))

    blow = cfg.get("blowout", {}) or {}
    spread_sd = float(blow.get("spread_sd", 9.5))
    threshold = float(blow.get("threshold_margin", 15))

    star_drop = float(blow.get("star_minute_drop", 0.12))
    role_drop = float(blow.get("role_minute_drop", 0.20))

    # Build team/matchup blowout stats once for enriched q
    from Atlas.engine.new_probability import _build_blowout_team_stats
    _blowout_team_stats = _build_blowout_team_stats(logs, threshold=threshold)
    if _blowout_team_stats:
        blow["_blowout_team_stats"] = _blowout_team_stats

    rows: list[dict[str, Any]] = []

    for r in board.itertuples(index=False):
        # avoid calling r._asdict() (type-checkers may treat various fields as non-callable)
        fields = getattr(r, "_fields", None)
        if fields:
            row: pd.Series[Any] = pd.Series(dict(zip(fields, tuple(r))))
        else:
            # runtime fallback if not a namedtuple
            row: pd.Series[Any] = pd.Series(tuple(r))

        if "minutes_s" not in row.index:
            row["minutes_s"] = float(
                minutes_sensitivity(str(row.get("stat", "")).upper())
            )

        info = simulate_leg_probability_new(
            gamelogs=logs,
            row=row,
            lookback=lookback,
            sims=sims,
            spread_sd=spread_sd,
            blowout_threshold=threshold,
            star_minute_drop=star_drop,
            role_minute_drop=role_drop,
            iael_df=iael_df,
            blowout_cfg=blow,
        )

        games_used = int((info or {}).get("games_used", 0) or 0)
        data_health_flag = "OK" if games_used > 0 else "DATA_MISSING"

        # normalize keys to str to satisfy typing: row.to_dict() may have Hashable keys
        row_dict = {str(k): v for k, v in row.to_dict().items()}
        info_dict = {str(k): v for k, v in (info or {}).items()}
        rows.append(
            {
                **row_dict,
                **info_dict,
                "data_health_flag": data_health_flag,
            }
        )

    return pd.DataFrame(rows)
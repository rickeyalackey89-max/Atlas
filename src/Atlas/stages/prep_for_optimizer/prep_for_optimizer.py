from __future__ import annotations

from typing import Any, Tuple

import pandas as pd

from Atlas.core.external_priors import apply_external_priors
from Atlas.core.iael_soft_risk import apply_iael_soft_risk


def _external_prior_probability_already_applied(df: pd.DataFrame) -> bool:
    if "external_prior_probability_applied" not in df.columns:
        return False
    applied = pd.to_numeric(df["external_prior_probability_applied"], errors="coerce")
    if not isinstance(applied, pd.Series):
        applied = pd.Series(applied, index=df.index)
    return bool(applied.fillna(0).astype(bool).any())


def run_prep_for_optimizer(
    scored: pd.DataFrame,
    cfg: dict[str, Any],
    iael_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Deterministic stage: prepare scored legs for optimizer.

    Behavior must remain 1:1 with legacy main():
      - dedupe_over_under for optimizer frame
      - apply_external_priors to both
      - apply_iael_hard_filter to optimizer frame only
      - enforce HARD INVARIANT on scored (p_adj==0 illegal unless DATA_MISSING)
    """
    # Local import to avoid circular dependency with Atlas.core (extracted)
    from Atlas.core.dedupe import dedupe_over_under
    from Atlas.core.iael_filter import apply_iael_hard_filter

    # optimizer uses deduped version
    scored_for_optimizer = dedupe_over_under(scored)

    # External priors are now applied before CAT so the calibrator sees the same
    # p_for_cal/features used by the replay cache. Avoid double-nudging in this
    # optimizer prep stage; only attach them here for older/manual paths that
    # did not already run the pre-CAT prior pass.
    scored_prior_applied = _external_prior_probability_already_applied(scored)
    optimizer_prior_applied = _external_prior_probability_already_applied(scored_for_optimizer)
    if not scored_prior_applied:
        scored = apply_external_priors(scored, cfg, apply_probability=False)
    if optimizer_prior_applied:
        print("[EXTERNAL_PRIORS] Optimizer prep: using pre-CAT prior surface; no second nudge")
    else:
        scored_for_optimizer = apply_external_priors(scored_for_optimizer, cfg, apply_probability=True)

    # IAEL SOFT RISK (QUESTIONABLE) — NO DROPS, NO MATH CHANGES.
    scored_for_optimizer = apply_iael_soft_risk(scored_for_optimizer, iael_df)

    # IAEL HARD FILTER (OUT/DOUBTFUL) — QUESTIONABLE stays visible as a soft flag
    scored_for_optimizer = apply_iael_hard_filter(
        scored_for_optimizer,
        iael_df,
        hard_statuses={"OUT", "DOUBTFUL"},
        require_team_match=False,
    )

    if "game_spread" in scored_for_optimizer.columns and "rotowire_game_spread" not in scored_for_optimizer.columns:
        scored_for_optimizer["rotowire_game_spread"] = pd.to_numeric(scored_for_optimizer["game_spread"], errors="coerce")
    if "game_spread" in scored.columns and "rotowire_game_spread" not in scored.columns:
        scored["rotowire_game_spread"] = pd.to_numeric(scored["game_spread"], errors="coerce")

    # HARD INVARIANT: p_adj == 0 is illegal unless explicitly DATA_MISSING
    if "p_adj" in scored.columns:
        scored["p_adj"] = pd.to_numeric(scored["p_adj"], errors="coerce").fillna(0.0)
        if "data_health_flag" in scored.columns:
            scored["data_health_flag"] = scored["data_health_flag"].astype(str)
        else:
            scored["data_health_flag"] = "OK"
        illegal = scored[(scored["p_adj"] == 0.0) & (scored["data_health_flag"] != "DATA_MISSING")]
        if not illegal.empty:
            cols = [
                c
                for c in [
                    "player",
                    "stat",
                    "direction",
                    "line",
                    "tier",
                    "games_used",
                    "p",
                    "p_adj",
                    "data_health_flag",
                    "projection_id",
                ]
                if c in illegal.columns
            ]
            sample = illegal[cols].head(25)
            raise RuntimeError(
                "HARD INVARIANT VIOLATION: p_adj == 0.0 for non-DATA_MISSING rows.\n"
                + sample.to_string(index=False)
            )

    return scored, scored_for_optimizer

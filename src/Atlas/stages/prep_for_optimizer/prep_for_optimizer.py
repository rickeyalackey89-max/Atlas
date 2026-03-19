from __future__ import annotations

from typing import Any, Tuple

import pandas as pd

from Atlas.core.external_priors import apply_external_priors


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

    # apply priors (both)
    scored = apply_external_priors(scored, cfg)
    scored_for_optimizer = apply_external_priors(scored_for_optimizer, cfg)

    # -------------------------------
    # IAEL SOFT RISK (QUESTIONABLE) — NO DROPS, NO MATH CHANGES
    # -------------------------------
    try:
        from Atlas.core.iael_filter import normalize_person_name
        _ia = iael_df.copy()
        _ia["status"] = _ia["status"].astype(str).str.upper() if "status" in _ia.columns else ""
        _q = _ia[_ia["status"] == "QUESTIONABLE"].copy()

        if not _q.empty and "player" in scored_for_optimizer.columns:
            q_players = set(_q["player"].apply(normalize_person_name).astype(str)) if "player" in _q.columns else set()
            s_norm = scored_for_optimizer["player"].apply(normalize_person_name).astype(str) if "player" in scored_for_optimizer.columns else pd.Series()

            scored_for_optimizer["is_questionable"] = s_norm.isin(q_players).astype(int)

            # optional: carry some IAEL context for inspection (still no math usage)
            # Keep it simple / safe: just status + out_frac if present
            if "out_frac" in _q.columns:
                _q["_pn"] = _q["player"].apply(normalize_person_name).astype(str)
                q_map = _q.groupby("_pn")["out_frac"].max().to_dict()
                scored_for_optimizer["q_out_frac"] = s_norm.map(q_map).fillna(0.0)
            else:
                scored_for_optimizer["q_out_frac"] = 0.0

            q_legs = int(scored_for_optimizer["is_questionable"].sum())
            if q_legs > 0:
                top = (
                    scored_for_optimizer[scored_for_optimizer["is_questionable"] == 1]
                    .groupby("player")
                    .size()
                    .sort_values(ascending=False)
                    .head(10)
                )
                print(f"[IAEL][SOFT] QUESTIONABLE legs={q_legs} players={len(top)} (top10 by leg count):")
                print(top.to_string())
        else:
            scored_for_optimizer["is_questionable"] = 0
            scored_for_optimizer["q_out_frac"] = 0.0
    except Exception as e:
        # never fail the run for soft-risk tagging
        scored_for_optimizer["is_questionable"] = 0
        scored_for_optimizer["q_out_frac"] = 0.0
        print(f"[IAEL][SOFT][WARN] soft-risk tagging skipped: {e}")

    # IAEL HARD FILTER (OUT/D/DQ/Q) — filter BEFORE building slips
    scored_for_optimizer = apply_iael_hard_filter(
        scored_for_optimizer,
        iael_df,
        hard_statuses={"OUT", "DOUBTFUL"},
        require_team_match=False,
    )

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
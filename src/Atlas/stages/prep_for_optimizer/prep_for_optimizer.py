from __future__ import annotations

import ast
from pathlib import Path
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

    # Keep the scored surface calibrated; only the optimizer copy gets the
    # probability nudge. The scored copy still carries audit columns when priors
    # are enabled, but its probabilities remain unchanged.
    scored = apply_external_priors(scored, cfg, apply_probability=False)
    scored_for_optimizer = apply_external_priors(scored_for_optimizer, cfg, apply_probability=True)

    # -------------------------------
    # IAEL SOFT RISK (QUESTIONABLE) — NO DROPS, NO MATH CHANGES
    # -------------------------------
    try:
        from Atlas.core.iael_filter import normalize_person_name
        _ia = iael_df.copy()
        _ia["status"] = _ia["status"].astype(str).str.upper() if "status" in _ia.columns else ""
        _q = _ia[_ia["status"] == "QUESTIONABLE"].copy()

        def _norm_name(value: object) -> str:
            return str(normalize_person_name(value)).strip().lower()

        def _parse_name_list(value: object) -> list[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return [str(item) for item in value if str(item).strip()]

            text = str(value).strip()
            if not text or text in {"[]", "nan", "None"}:
                return []

            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = text

            if isinstance(parsed, (list, tuple, set)):
                return [str(item) for item in parsed if str(item).strip()]
            if isinstance(parsed, str):
                raw = parsed.strip()
                if not raw:
                    return []
                for sep in ("|", ";", ","):
                    if sep in raw:
                        return [part.strip() for part in raw.split(sep) if part.strip()]
                return [raw]
            return [str(parsed)]

        if not _q.empty and "player" in scored_for_optimizer.columns:
            q_players = set(_q["player"].apply(_norm_name).astype(str)) if "player" in _q.columns else set()

            q_map: dict[str, float] = {}
            if "player" in _q.columns:
                _q["_pn"] = _q["player"].apply(_norm_name).astype(str)
                if "out_frac" in _q.columns:
                    q_out_frac = pd.to_numeric(_q["out_frac"], errors="coerce").fillna(0.0).astype(float)
                    _q["_q_soft"] = q_out_frac.where(q_out_frac > 0.0, 0.5)
                    q_map.update({str(k): float(v) for k, v in _q.groupby("_pn")["_q_soft"].max().astype(float).to_dict().items()})
                for pn in _q["_pn"].dropna().astype(str):
                    q_map.setdefault(pn, 0.5)

            q_beneficiary_keys: set[tuple[str, str, str]] = set()
            share_matrix_path = Path("data") / "model" / "share_matrix.csv"
            if share_matrix_path.exists():
                try:
                    share_matrix = pd.read_csv(share_matrix_path, low_memory=False)
                    if not share_matrix.empty and {"team", "out_player", "beneficiary_player", "stat"}.issubset(share_matrix.columns):
                        sm = share_matrix.copy()
                        sm["team_u"] = sm["team"].astype(str).str.upper().str.strip()
                        sm["out_canon"] = sm["out_player"].apply(_norm_name)
                        sm["ben_canon"] = sm["beneficiary_player"].apply(_norm_name)
                        sm["stat_u"] = sm["stat"].astype(str).str.upper().str.strip()
                        impacted = sm[sm["out_canon"].isin(q_players)].copy()
                        if not impacted.empty:
                            q_beneficiary_keys = set(zip(impacted["team_u"], impacted["stat_u"], impacted["ben_canon"]))
                except Exception:
                    q_beneficiary_keys = set()

            has_role_outs = "role_ctx_outs" in scored_for_optimizer.columns
            candidate_col = "role_ctx_outs" if has_role_outs else "player"

            q_flags: list[int] = []
            q_fracs: list[float] = []
            for _, row in scored_for_optimizer.iterrows():
                names = _parse_name_list(row.get(candidate_col))
                if not names and candidate_col != "player":
                    names = _parse_name_list(row.get("player"))

                matched = [_norm_name(name) for name in names if _norm_name(name) in q_players]
                row_team = str(row.get("team", "")).upper().strip()
                row_stat = str(row.get("stat", row.get("stat_raw", ""))).upper().strip()
                row_player = _norm_name(row.get("player", ""))
                beneficiary_hit = (row_team, row_stat, row_player) in q_beneficiary_keys

                if matched or beneficiary_hit:
                    q_flags.append(1)
                    if matched:
                        q_fracs.append(max(float(q_map.get(name, 0.5)) for name in set(matched)))
                    else:
                        q_fracs.append(0.5)
                else:
                    q_flags.append(0)
                    q_fracs.append(0.0)

            scored_for_optimizer["is_questionable"] = pd.Series(q_flags, index=scored_for_optimizer.index).astype(int)
            scored_for_optimizer["q_out_frac"] = pd.Series(q_fracs, index=scored_for_optimizer.index).astype(float)

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
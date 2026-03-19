from __future__ import annotations

"""
New engine (Phase 7A-2 calibration injection; legacy oracle retained).

Goal: relocate the legacy probability kernel behind the NewEngine seam WITHOUT
changing behavior.

Implementation strategy:
- Keep PREP + OPTIMIZE stages identical to legacy.
- Replace only the scoring kernel call inside the NewEngine path by using an
  inlined score_board wrapper that calls `simulate_leg_probability_new`.

No CLI changes. No publish changes. Legacy engine remains untouched.
"""

from typing import Any, Optional
from pathlib import Path
import builtins as _b  # prevents shadowed int/float/str from breaking static analysis

import numpy as np
import pandas as pd

from Atlas.engine.api import Engine, EngineOutputs

__all__ = ["NewEngine", "_run_score_board_new"]

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
        return out[["team", "out_player", "status"]].copy()

    # Normalize from invalidations schema
    if "team_norm" in cols and "player_norm" in cols and "status" in cols:
        out = iael_df.rename(
            columns={
                cols["team_norm"]: "team",
                cols["player_norm"]: "out_player",
                cols["status"]: "status",
            }
        ).copy()
        out["team"] = out["team"].astype(str).str.upper().str.strip()
        out["out_player"] = out["out_player"].astype(str).str.strip()
        out["status"] = out["status"].astype(str).str.upper().str.strip()
        return out[["team", "out_player", "status"]].copy()

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


class NewEngine(Engine):
    name = "new"

    def run(
        self,
        *,
        board: pd.DataFrame,
        logs: pd.DataFrame,
        cfg: dict[str, Any],
        iael_df: Optional[pd.DataFrame] = None,
    ) -> EngineOutputs:
        # Normalize Optional -> DataFrame for stages that are typed as requiring DataFrame
        iael_df_norm: pd.DataFrame = iael_df if iael_df is not None else pd.DataFrame()

        # SCORE (strict parity, relocated kernel)
        scored = _run_score_board_new(board=board, logs=logs, cfg=cfg, iael_df=iael_df_norm)

        # CALIBRATION (Phase 7A-2; post-simulation transform; NewEngine only)
        # Locked policy: calibration stays ON (cannot be disabled via config).
        cal = (cfg.get("calibration", {}) or {})
        k = _b.float(cal.get("k", 0.7) or 0.7)
        threshold = _b.float(cal.get("threshold", 0.80) or 0.80)

        if "p" in scored.columns:
            from Atlas.engine.calibration import apply_last10_bonus_logit

            # If missing, calibration is a no-op.
            if "rpd_last10_hitrate" in scored.columns:
                p_s = pd.to_numeric(scored["p"], errors="coerce")
                last10_s = pd.to_numeric(scored["rpd_last10_hitrate"], errors="coerce")

                # Force clean numpy float arrays (fixes ExtensionArray/Categorical typing)
                p = np.asarray(p_s, dtype=float)
                last10 = np.asarray(last10_s, dtype=float)

                p_cal = apply_last10_bonus_logit(p, last10, k, threshold=threshold)

                # Preserve NaN positions from original p
                m_nan = ~np.isfinite(p)
                if m_nan.any():
                    p_cal[m_nan] = p[m_nan]

                scored["p"] = p_cal
                if "p_adj" in scored.columns:
                    scored["p_adj"] = p_cal

        # If p_adj still isn't present, keep strict parity: p_adj := p
        if "p" in scored.columns and "p_adj" not in scored.columns:
            scored["p_adj"] = scored["p"]

        
        # CALIBRATION MAP (Phase 7A-3): emit p_for_cal / p_cal_src / p_cal (no overwrite)
        # Policy:
        #   - Healthy teams: calibrate from p_adj
        #   - Outs/injury context: calibrate from p_role
        # Map path is supplied via env ATLAS_CAL_MAP; if missing, p_cal := p_for_cal.
        try:
            from Atlas.engine.calibration_map import apply_calibration_column, get_calibration_path_from_env

            if "p_for_cal" not in scored.columns:
                # ensure we pass a Series (not None) into pd.to_numeric
                if "p_adj" in scored.columns:
                    base_raw = scored["p_adj"]
                elif "p" in scored.columns:
                    base_raw = scored["p"]
                else:
                    base_raw = pd.Series(np.nan, index=scored.index)
                base_p_adj = pd.to_numeric(base_raw, errors="coerce")

                if "p_role" in scored.columns and "role_ctx_outs_used" in scored.columns:
                    outs_used = pd.to_numeric(scored["role_ctx_outs_used"], errors="coerce").fillna(0.0)
                    use_role = outs_used > 0.0
                    p_role_raw = scored["p_role"]
                    p_role = pd.to_numeric(p_role_raw, errors="coerce")
                    scored["p_for_cal"] = np.where(use_role, p_role, base_p_adj)
                    scored["p_cal_src"] = np.where(use_role, "p_role", "p_adj")
                else:
                    scored["p_for_cal"] = base_p_adj
                    scored["p_cal_src"] = "p_adj"

            # Apply map if available; otherwise create identity p_cal
            map_path = get_calibration_path_from_env()
            scored = apply_calibration_column(
                scored,
                map_path=map_path,
                in_col="p_for_cal",
                out_col="p_cal",
                warn=False,
            )
            if "p_cal" not in scored.columns:
                scored["p_cal"] = scored["p_for_cal"]
        except Exception:
            # Never fail the run due to calibration mapping; fall back to identity columns.
            if "p_for_cal" not in scored.columns:
                # ensure we pass a Series (not None) into pd.to_numeric
                if "p_adj" in scored.columns:
                    base_raw = scored["p_adj"]
                elif "p" in scored.columns:
                    base_raw = scored["p"]
                else:
                    base_raw = pd.Series(np.nan, index=scored.index)
                scored["p_for_cal"] = pd.to_numeric(base_raw, errors="coerce")
            if "p_cal_src" not in scored.columns:
                scored["p_cal_src"] = "p_adj"
            if "p_cal" not in scored.columns:
                scored["p_cal"] = scored["p_for_cal"]

        # TELEMETRY CALIBRATION OVERLAY (late overlay on p_cal; additive only)
        try:
            from Atlas.runtime.telemetry_calibration import load_calibration, apply_calibration_to_column

            project_root = Path(__file__).resolve().parents[3]
            tele_cal = load_calibration(project_root)

            stat = scored["stat"].astype(str).str.upper().str.strip() if "stat" in scored.columns else pd.Series("", index=scored.index)
            direction = scored["direction"].astype(str).str.upper().str.strip() if "direction" in scored.columns else pd.Series("", index=scored.index)
            scored["telemetry_cal_key"] = (stat + "|" + direction).astype(str)
            scored["telemetry_k_shrink"] = 1.0
            scored["telemetry_under_penalty"] = 1.0
            scored["telemetry_mult"] = 1.0
            scored["telemetry_cal_applied"] = False

            if tele_cal is not None and "p_cal" in scored.columns:
                scored = apply_calibration_to_column(scored, tele_cal, source_col="p_cal", out_col="p_cal")
                if "p_cal_src" not in scored.columns:
                    scored["p_cal_src"] = "p_adj"
                applied_mask = scored["telemetry_cal_applied"].astype(bool)
                if applied_mask.any():
                    scored.loc[applied_mask, "p_cal_src"] = scored.loc[applied_mask, "p_cal_src"].astype(str) + "+telemetry"
        except Exception:
            pass

# PREP FOR OPTIMIZER (staged, unchanged)
        from Atlas.stages.prep_for_optimizer.prep_for_optimizer import run_prep_for_optimizer

        scored, scored_for_optimizer = run_prep_for_optimizer(
            scored=scored,
            cfg=cfg,
            iael_df=iael_df_norm,
        )

        # OPTIMIZER CFG
        optimizer_cfg = (cfg.get("optimizer", {}) or {})
        top_n = _b.int(optimizer_cfg.get("top_n_slips", 25))
        seed = _b.int(optimizer_cfg.get("seed", 7))

        pricing_engine = _b.str(cfg.get("pricing_engine", "atlas") or "atlas")

        # BUILD SLIPS (staged, unchanged)
        from Atlas.stages.optimize.build_slips_today import run_build_slips

        slips = run_build_slips(
            scored_for_optimizer=scored_for_optimizer,
            top_n=top_n,
            seed=seed,
            pricing_engine=pricing_engine,
            cfg=cfg,
        )

        return EngineOutputs(
            scored=scored,
            scored_for_optimizer=scored_for_optimizer,
            sys3=slips.sys3,
            sys4=slips.sys4,
            sys5=slips.sys5,
            wind3=slips.wind3,
            wind4=slips.wind4,
            wind5=slips.wind5,
        )
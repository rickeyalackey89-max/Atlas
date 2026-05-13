from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_RAW_SLATE_FRAGILITY_GUARD: dict[str, Any] = {
    "enabled": False,
    "max_games": 2,
    "min_q_out_frac_mean": 0.10,
    "min_q_blowout_p90": 0.50,
    "high_prob_threshold": 0.55,
    "logit_shift": -0.10,
    "over_logit_shift": -0.15,
    "under_logit_shift": 0.10,
}


def apply_raw_slate_fragility_guard(scored: pd.DataFrame, cfg: dict[str, Any] | None) -> pd.DataFrame:
    """Apply a narrow pre-CAT probability guard for thin, injury-fragile slates.

    The guard adjusts `p_for_cal` only, leaving `p_adj` intact for auditability.
    It must run after `p_for_cal` is assigned and before CAT/GBM builders consume it.
    """

    out = scored.copy()
    guard_cfg = _guard_cfg(cfg)
    metrics = _slate_metrics(out)
    enabled = bool(guard_cfg.get("enabled", False))

    out["raw_slate_fragility_guard_enabled"] = enabled
    out["raw_slate_fragility_guard_triggered"] = False
    out["raw_slate_fragility_guard_shifted"] = False
    out["raw_slate_fragility_guard_reasons"] = ""
    out["raw_slate_fragility_guard_logit_shift"] = 0.0
    out["raw_slate_fragility_guard_over_logit_shift"] = 0.0
    out["raw_slate_fragility_guard_under_logit_shift"] = 0.0
    out["raw_slate_fragility_guard_shifted_count"] = 0
    out["raw_slate_fragility_guard_over_shifted_count"] = 0
    out["raw_slate_fragility_guard_under_shifted_count"] = 0
    out["raw_slate_fragility_guard_games"] = metrics["games"]
    out["raw_slate_fragility_guard_q_out_frac_mean"] = metrics["q_out_frac_mean"]
    out["raw_slate_fragility_guard_q_blowout_p90"] = metrics["q_blowout_p90"]

    if out.empty or "p_for_cal" not in out.columns:
        return out

    reasons = _trigger_reasons(metrics, guard_cfg) if enabled else []
    if not enabled:
        return out

    p = pd.to_numeric(out["p_for_cal"], errors="coerce").fillna(0.5).clip(0.0, 1.0)
    high_prob_threshold = float(guard_cfg["high_prob_threshold"])
    q_out = _numeric(out, "q_out_frac", default=0.0)
    leg_mask = (q_out > 0.0) | (p >= high_prob_threshold)
    direction = out["direction"].astype(str).str.upper().str.strip() if "direction" in out.columns else pd.Series("", index=out.index)
    over_mask = leg_mask & direction.eq("OVER")
    under_mask = leg_mask & direction.eq("UNDER")

    if not reasons:
        print(
            "[RAW_SLATE_GUARD] inactive -- "
            "harmful_raw_slate_indicator=false, "
            f"games={metrics['games']}, "
            f"q_out_frac_mean={metrics['q_out_frac_mean']:.4f}, "
            f"q_blowout_p90={metrics['q_blowout_p90']:.4f}, "
            f"high_prob_threshold={high_prob_threshold:.2f}"
        )
        return out

    shift = float(guard_cfg["logit_shift"])
    over_shift = float(guard_cfg.get("over_logit_shift", shift))
    under_shift = float(guard_cfg.get("under_logit_shift", 0.0))
    shifted = p.copy()
    if over_mask.any():
        shifted = _logit_shift(shifted, over_shift, over_mask)
    if under_mask.any() and under_shift != 0.0:
        shifted = _logit_shift(shifted, under_shift, under_mask)

    out["p_for_cal_pre_raw_slate_guard"] = p
    out["p_for_cal"] = shifted
    out["p_cal"] = shifted
    out["raw_slate_fragility_guard_triggered"] = True
    out["raw_slate_fragility_guard_shifted"] = leg_mask
    out["raw_slate_fragility_guard_reasons"] = ",".join(reasons)
    out["raw_slate_fragility_guard_logit_shift"] = shift
    out["raw_slate_fragility_guard_over_logit_shift"] = over_shift
    out["raw_slate_fragility_guard_under_logit_shift"] = under_shift
    out["raw_slate_fragility_guard_shifted_count"] = int(leg_mask.sum())
    out["raw_slate_fragility_guard_over_shifted_count"] = int(over_mask.sum())
    out["raw_slate_fragility_guard_under_shifted_count"] = int(under_mask.sum())

    print(
        "[RAW_SLATE_GUARD] ACTIVE -- "
        "harmful_raw_slate_indicator=true, "
        f"over_logit_shift={over_shift:+.3f}, "
        f"under_logit_shift={under_shift:+.3f}, "
        f"shifted_legs={int(leg_mask.sum())}/{len(out)}, "
        f"over_shifted={int(over_mask.sum())}, "
        f"under_shifted={int(under_mask.sum())}, "
        f"reasons={','.join(reasons)}, "
        f"games={metrics['games']}, "
        f"q_out_frac_mean={metrics['q_out_frac_mean']:.4f}, "
        f"q_blowout_p90={metrics['q_blowout_p90']:.4f}, "
        f"high_prob_threshold={high_prob_threshold:.2f}"
    )
    return out


def _guard_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_RAW_SLATE_FRAGILITY_GUARD)
    if isinstance(cfg, dict):
        user_cfg = cfg.get("raw_slate_fragility_guard")
        if isinstance(user_cfg, dict):
            out.update(user_cfg)
    out["enabled"] = bool(out.get("enabled", False))
    out["max_games"] = int(out["max_games"])
    for key in [
        "min_q_out_frac_mean",
        "min_q_blowout_p90",
        "high_prob_threshold",
        "logit_shift",
        "over_logit_shift",
        "under_logit_shift",
    ]:
        out[key] = float(out[key])
    return out


def _slate_metrics(scored: pd.DataFrame) -> dict[str, float | int]:
    games = int(scored["game_id"].nunique()) if "game_id" in scored.columns and not scored.empty else 0
    q_out = _numeric(scored, "q_out_frac", default=0.0)
    q_blowout = _numeric(scored, "q_blowout", default=0.0)
    return {
        "games": games,
        "q_out_frac_mean": float(q_out.mean()) if len(q_out) else 0.0,
        "q_blowout_p90": float(q_blowout.quantile(0.90)) if len(q_blowout) else 0.0,
    }


def _trigger_reasons(metrics: dict[str, float | int], guard_cfg: dict[str, Any]) -> list[str]:
    reasons = []
    if (
        int(metrics["games"]) <= int(guard_cfg["max_games"])
        and float(metrics["q_out_frac_mean"]) >= float(guard_cfg["min_q_out_frac_mean"])
        and float(metrics["q_blowout_p90"]) >= float(guard_cfg["min_q_blowout_p90"])
    ):
        reasons.append("thin_qout_blowout")
    return reasons


def _numeric(scored: pd.DataFrame, col: str, *, default: float) -> pd.Series:
    if col not in scored.columns:
        return pd.Series(np.full(len(scored), default, dtype="float64"), index=scored.index)
    values = pd.to_numeric(scored[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=scored.index)
    return values.fillna(default)


def _logit_shift(p: pd.Series, delta: float, mask: pd.Series) -> pd.Series:
    out = p.copy()
    safe = out.clip(1e-5, 1.0 - 1e-5)
    shifted = 1.0 / (1.0 + np.exp(-(np.log(safe / (1.0 - safe)) + delta)))
    out.loc[mask] = shifted.loc[mask]
    return out.clip(0.0, 1.0)

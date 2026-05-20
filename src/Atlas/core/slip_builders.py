"""
Slip builders (SYSTEM/WINDFALL) extracted from LegacyEngine.main during Phase 7B.

Non-negotiables:
- Preserve behavior 1:1 (deterministic, seed-driven).
- Preserve tier/direction/line identity (no collapsing).
- Preserve POWER payout logic + optional PP kernel adjustment.
"""

from __future__ import annotations

import ast
import os
import random
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from .payout_tables import FLEX_2, FLEX_3, FLEX_4, FLEX_5, POWER_MULT
from .team_aliases import normalize_team_abbr
from .minute_risk_guard import apply_minute_risk_guard
from .single_game_script import (
    apply_single_game_script_annotations,
    apply_single_game_selection_surface,
    is_single_game_slate,
    single_game_slip_rule_status,
)
from .slip_composition_policy import (
    composition_drop_reason_for_legs,
    infer_slate_game_count,
)
from .slip_family_diversity import prop_key_from_mapping
from .slip_scoring import _score_slip
from .under_visibility_gate import apply_under_visibility_gate


# -----------------------------
# Robust helpers (NO fillna / NO astype)
# -----------------------------

def _series_to_str(s: Any, *, index: pd.Index, default: str = "") -> pd.Series:
    """
    Robust conversion to string Series without using .astype().
    """
    if isinstance(s, pd.Series):
        arr = s.to_numpy(copy=False)
    else:
        arr = np.asarray(s, dtype=object)

    out = np.empty(len(index), dtype=object)
    for i in range(len(index)):
        v = arr[i] if i < len(arr) else None
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out[i] = default
        else:
            out[i] = str(v)
    return pd.Series(out, index=index, dtype=object)


def _to_float_series(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    """
    Robust numeric conversion without .fillna()/.astype().
    Returns float64 Series aligned to df.index.
    """
    if col not in df.columns:
        arr = np.full(len(df.index), float(default), dtype="float64")
        return pd.Series(arr, index=df.index)

    s = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(s, pd.Series):
        s = pd.Series(s, index=df.index)

    # NOTE: we do NOT mutate this array directly, so copy=False is fine here.
    # When you need to mutate, ALWAYS take copy=True at the mutation site.
    arr = np.asarray(s.to_numpy(copy=False), dtype="float64")
    return pd.Series(arr, index=df.index)


def _nan_to_value(s: pd.Series, value: float) -> pd.Series:
    """
    Replace NaNs using numpy masking (no .fillna()).
    """
    arr = np.asarray(s.to_numpy(copy=True), dtype="float64")  # writable
    arr[np.isnan(arr)] = float(value)
    return pd.Series(arr, index=s.index)


def _clip01(s: pd.Series) -> pd.Series:
    """
    Clip to [0,1] using numpy (no .clip()).
    """
    arr = np.asarray(s.to_numpy(copy=True), dtype="float64")  # writable
    np.clip(arr, 0.0, 1.0, out=arr)
    return pd.Series(arr, index=s.index)


def _single_game_soft_exposure_mask(df: pd.DataFrame, cfg: dict[str, Any] | None) -> pd.Series:
    sg = (cfg or {}).get("single_game_mode", {}) if isinstance(cfg, dict) else {}
    if not isinstance(sg, dict) or not bool(sg.get("soft_injury_exposure_not_hard_exclude", False)):
        return pd.Series(False, index=df.index)
    if not is_single_game_slate(df, cfg):
        return pd.Series(False, index=df.index)
    if "role_ctx_outs" not in df.columns:
        return pd.Series(False, index=df.index)
    role_outs = df["role_ctx_outs"].map(lambda x: "" if x is None else str(x).strip().lower())
    return role_outs.ne("") & role_outs.ne("[]") & role_outs.ne("nan")


def _pick_best_prob_column(df: pd.DataFrame, *, prefer_calibrated_prob: bool = False) -> str:
    """
    Probability preference order (best -> fallback).

    1) p_cal       (calibrated probability)
    2) p_for_cal   (upstream probability fed into calibration)
    3) p_role      (role-context probability)
    4) p           (raw probability)
    5) p_adj       (blowout / minutes adjusted probability)
    6) p_eff       (legacy effective probability)
    """
    if prefer_calibrated_prob:
        order = ("p_cal", "p_for_cal", "p_role", "p", "p_adj", "p_eff")
    else:
        order = ("p_for_cal", "p_cal", "p_role", "p", "p_adj", "p_eff")
    for c in order:
        if c in df.columns:
            return c
    return ""


# -----------------------------
# Public helpers
# -----------------------------

def expand_legs(df: pd.DataFrame, max_legs: int) -> pd.DataFrame:
    out = df.copy()
    if "legs" not in out.columns:
        return out

    def to_list(x: Any) -> list[str]:
        if isinstance(x, list):
            return [str(i).strip() for i in x]
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    v = ast.literal_eval(s)
                    if isinstance(v, list):
                        return [str(i).strip() for i in v]
                except Exception:
                    pass
            if " | " in s:
                return [p.strip() for p in s.split(" | ") if p.strip()]
            return [s] if s else []
        return []

    legs_list = out["legs"].apply(to_list)
    for i in range(max_legs):
        out[f"leg_{i+1}"] = legs_list.apply(lambda lst: lst[i] if i < len(lst) else "")
    return out


def dedupe_slips_by_key(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0 or "legs" not in df.columns:
        return df
    out = df.copy()
    out["slip_key"] = _series_to_str(out["legs"], index=out.index, default="")
    out = out.drop_duplicates(subset=["slip_key"], keep="first")
    return out

# -------------------------------------------------------------------
# Tier mix contracts
# -------------------------------------------------------------------

def _tier_counts_from_legs(x: Any) -> dict[str, int]:
    if x is None:
        return {"STANDARD": 0, "GOBLIN": 0, "DEMON": 0}
    s = str(x).upper()
    return {"STANDARD": s.count("(STANDARD)"), "GOBLIN": s.count("(GOBLIN)"), "DEMON": s.count("(DEMON)")}


def _windfall_mix_ok(n_legs: int, legs: Any) -> bool:
    c = _tier_counts_from_legs(legs)
    if n_legs == 2:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 0 and c["DEMON"] == 1
    if n_legs == 3:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 1 and c["DEMON"] == 1
    if n_legs == 4:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 2 and c["DEMON"] == 1
    if n_legs == 5:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 2 and c["DEMON"] == 1
    return True


def _single_game_windfall_mix_ok(n_legs: int, legs: Any) -> bool:
    c = _tier_counts_from_legs(legs)
    if n_legs == 2:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 0 and c["DEMON"] == 0
    if n_legs == 3:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 1 and c["DEMON"] == 0
    if n_legs == 4:
        return c["GOBLIN"] == 3 and c["STANDARD"] == 1 and c["DEMON"] == 0
    return _windfall_mix_ok(n_legs, legs)


def _system_mix_ok(n_legs: int, legs: Any) -> bool:
    c = _tier_counts_from_legs(legs)
    if n_legs == 2:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 1 and c["DEMON"] == 0
    if n_legs == 3:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 2 and c["DEMON"] == 0
    if n_legs == 4:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 2 and c["DEMON"] == 0
    if n_legs == 5:
        return c["GOBLIN"] == 3 and c["STANDARD"] == 2 and c["DEMON"] == 0
    return True


# -------------------------------------------------------------------
# Builders
# -------------------------------------------------------------------

_EMPTY_SLIPS_COLS = ["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"]


def build_slips_by_tier_buckets(
    *,
    legs_df: pd.DataFrame,
    n_legs: int,
    top_n: int,
    payout_power_mult: Any,
    payout_flex: Any,
    pricing_engine: str,
    cfg: dict[str, Any],
    seed: int = 7,
    per_tier: int = 500,
    max_attempts: int = 400000,
    sort_mode: str = "ev",
    mixes: dict[int, dict[str, int]],
    required_tiers: list[str],
    mix_ok_fn,
) -> pd.DataFrame:
    
    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
        print(f"[BUILDER][DEBUG] ENTER build_slips_by_tier_buckets top_n={top_n} per_tier={per_tier} max_attempts={max_attempts} "
            f"target_pool_mult={sb.get('target_pool_mult','NA')} phase1_frac={sb.get('phase1_frac','NA')} phase1_pool_frac={sb.get('phase1_pool_frac','NA')}")

    if legs_df is None or len(legs_df) == 0:
        return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    if n_legs not in mixes:
        return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)
    mix = mixes[n_legs]
    slate_games = infer_slate_game_count(legs_df)

    df = legs_df.copy().reset_index(drop=True)
    sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
    legacy_selector_scoring = bool(sb.get("legacy_selector_scoring", False))
    prefer_calibrated_prob = bool(sb.get("prefer_calibrated_prob", False))

    if "projection_id" not in df.columns and "id" in df.columns:
        df = df.rename(columns={"id": "projection_id"})

    pid_series: pd.Series | None = None
    if "projection_id" in df.columns:
        pid_series = df["projection_id"]
    elif "source_projection_id" in df.columns:
        pid_series = df["source_projection_id"]

    if pid_series is None:
        df["projection_id"] = ""
    else:
        if "source_projection_id" in df.columns:
            num = pd.to_numeric(pid_series, errors="coerce")
            if float(num.isna().mean()) > 0.50:
                pid_series = df["source_projection_id"]

        df["projection_id"] = _series_to_str(pid_series, index=df.index, default="").map(lambda x: str(x).strip())

    if "tier" in df.columns:
        df["tier"] = _series_to_str(df["tier"], index=df.index, default="STANDARD").map(
            lambda x: str(x).upper().strip() if x else "STANDARD"
        )
    else:
        df["tier"] = pd.Series(["STANDARD"] * len(df), index=df.index, dtype=object)

    # ---- p_eff selection ----
    if legacy_selector_scoring:
        best_prob_col = ""
        for c in ("p_cal_role", "p_cal", "p_adj_role", "p_adj", "p"):
            if c in df.columns:
                best_prob_col = c
                break
    else:
        best_prob_col = _pick_best_prob_column(df, prefer_calibrated_prob=prefer_calibrated_prob)

    if legacy_selector_scoring and "p_eff" in df.columns:
        base = _to_float_series(df, "p_eff", default=np.nan)
        if best_prob_col:
            fb = _to_float_series(df, best_prob_col, default=0.50)
        else:
            fb = _to_float_series(df, "p_adj", default=0.50)
        base_arr = base.to_numpy(copy=True)
        fb_arr = fb.to_numpy(copy=False)
        mask = np.isnan(base_arr)
        base_arr[mask] = fb_arr[mask]
        df["p_eff"] = _clip01(pd.Series(base_arr, index=df.index))
    elif best_prob_col:
        source = _to_float_series(df, best_prob_col, default=np.nan)
        source = _nan_to_value(source, 0.50)
        df["p_eff"] = _clip01(source)
    elif "p_eff" in df.columns:
        df["p_eff"] = _clip01(_to_float_series(df, "p_eff", default=0.50).pipe(lambda s: _nan_to_value(s, 0.50)))
    else:
        df["p_eff"] = pd.Series(np.full(len(df), 0.50, dtype="float64"), index=df.index)

    df = apply_single_game_script_annotations(df, cfg)

    role_on_mask = pd.Series(np.zeros(len(df), dtype=bool), index=df.index)
    if (not legacy_selector_scoring) and "role_ctx_outs_used" in df.columns:
        role_on_mask = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce").fillna(0.0) > 0.0
        if role_on_mask.any():
            role_surface: pd.Series | None = None
            # Prefer the upstream probability surface first for role-on rows.
            role_surface_order = ("p_cal", "p_for_cal", "p_close_adj", "p_close_role", "p_role") if prefer_calibrated_prob else ("p_for_cal", "p_cal", "p_close_adj", "p_close_role", "p_role")
            for candidate_col in role_surface_order:
                if candidate_col in df.columns:
                    role_surface = _clip01(_to_float_series(df, candidate_col, default=0.50).pipe(lambda s: _nan_to_value(s, 0.50)))
                    break
            if role_surface is not None:
                df.loc[role_on_mask, "p_eff"] = role_surface.loc[role_on_mask]

    # --- Trained leg adjustments: correct calibration biases per stat/direction/tier ---
    leg_adj = sb.get("leg_adjustments") if isinstance(sb, dict) else None
    if isinstance(leg_adj, dict):
        adj_arr = np.zeros(len(df), dtype="float64")

        # by_direction: e.g. {"under": -0.08, "over": 0.0}
        by_dir = leg_adj.get("by_direction")
        if isinstance(by_dir, dict) and "direction" in df.columns:
            dir_col = df["direction"].astype(str).str.strip().str.lower()
            for d_key, d_val in by_dir.items():
                d_val = float(d_val or 0.0)
                if d_val != 0.0:
                    mask = dir_col == str(d_key).strip().lower()
                    adj_arr[mask.to_numpy()] += d_val

        # by_tier: e.g. {"GOBLIN": 0.05, "DEMON": -0.03}
        by_tier = leg_adj.get("by_tier")
        if isinstance(by_tier, dict) and "tier" in df.columns:
            tier_col = df["tier"].astype(str).str.strip().str.upper()
            for t_key, t_val in by_tier.items():
                t_val = float(t_val or 0.0)
                if t_val != 0.0:
                    mask = tier_col == str(t_key).strip().upper()
                    adj_arr[mask.to_numpy()] += t_val

        # by_stat_direction: e.g. {"REB_under": -0.10, "AST_under": -0.12}
        by_sd = leg_adj.get("by_stat_direction")
        if isinstance(by_sd, dict) and "stat" in df.columns and "direction" in df.columns:
            stat_col = df["stat"].astype(str).str.strip().str.upper()
            dir_col = df["direction"].astype(str).str.strip().str.lower()
            sd_key_col = stat_col + "_" + dir_col
            for sd_key, sd_val in by_sd.items():
                sd_val = float(sd_val or 0.0)
                if sd_val != 0.0:
                    mask = sd_key_col == str(sd_key).strip().upper()
                    adj_arr[mask.to_numpy()] += sd_val

        if np.any(adj_arr != 0.0):
            before_mean = float(df["p_eff"].mean())
            df["p_eff"] = _clip01(df["p_eff"] + pd.Series(adj_arr, index=df.index))
            if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
                after_mean = float(df["p_eff"].mean())
                n_adj = int(np.sum(adj_arr != 0.0))
                print(f"[BUILDER][DEBUG] leg_adjustments: {n_adj} legs adjusted, p_eff mean {before_mean:.3f} -> {after_mean:.3f}")

    # --- p_eff ceiling: CLAMP overconfident legs BEFORE edge_score ---
    # Trainer optimized max_leg_prob as a clamp (clip), not a filter.
    # Clamping preserves the leg in the pool at the cap value;
    # filtering removes it entirely and starves the beam search.
    # Keep unclamped p_eff_raw so hit_prob reflects actual probability.
    max_leg_prob = float(sb.get("max_leg_prob", 0.0) or 0.0)
    df["p_eff_raw"] = df["p_eff"].copy()
    if max_leg_prob > 0.0:
        df["p_eff"] = df["p_eff"].clip(upper=max_leg_prob)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] max_leg_prob={max_leg_prob:.3f} clamp applied")

    # Selection-only minutes risk guard. p_eff_raw remains the calibrated model
    # probability used for hit_prob; p_eff/p_select is lowered for fragile legs.
    df = apply_minute_risk_guard(df, cfg, section="slip_build", score_col="p_eff")
    df = apply_single_game_selection_surface(df, cfg, score_col="p_eff", clip_score=True)
    df = apply_under_visibility_gate(df, cfg, section="slip_build", probability_col="p_eff")
    if df.empty:
        return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # edge_score fallback = p_eff - 0.5 (keep exact math)
    edge_cap = (max_leg_prob - 0.5) if max_leg_prob > 0.0 else None
    if "edge_score" in df.columns:
        es = pd.to_numeric(df["edge_score"], errors="coerce")
        if not isinstance(es, pd.Series):
            es = pd.Series(es, index=df.index)

        # FIX: copy=True because we mutate es_arr in-place
        es_arr = np.asarray(es.to_numpy(copy=True), dtype="float64")  # writable
        pe_arr = np.asarray(df["p_eff"].to_numpy(copy=False), dtype="float64")
        mask = np.isnan(es_arr)
        es_arr[mask] = pe_arr[mask] - 0.5
        if "minute_risk_penalty" in df.columns:
            pen_arr = np.asarray(pd.to_numeric(df["minute_risk_penalty"], errors="coerce").to_numpy(copy=True), dtype="float64")
            pen_arr[np.isnan(pen_arr)] = 0.0
            es_arr = es_arr - pen_arr
        if edge_cap is not None:
            np.clip(es_arr, None, edge_cap, out=es_arr)
        df["edge_score"] = pd.Series(es_arr, index=df.index)
    else:
        pe_arr = np.asarray(df["p_eff"].to_numpy(copy=False), dtype="float64")
        df["edge_score"] = pd.Series(pe_arr - 0.5, index=df.index)

    role_bonus = pd.Series(np.zeros(len(df), dtype="float64"), index=df.index)
    role_priority = pd.Series(np.zeros(len(df), dtype="float64"), index=df.index)
    if (not legacy_selector_scoring) and "role_ctx_outs_used" in df.columns:
        role_cfg = sb.get("role_ctx", {}) if isinstance(sb, dict) else {}

        role_on_w = float(role_cfg.get("on_w", 0.0) or 0.0)
        role_outs_w = float(role_cfg.get("outs_w", 0.0) or 0.0)
        role_mult_w = float(role_cfg.get("mult_w", 0.0) or 0.0)
        role_minutes_w = float(role_cfg.get("minutes_w", 0.0) or 0.0)
        role_usage_w = float(role_cfg.get("usage_w", 0.0) or 0.0)
        role_bonus_cap = float(role_cfg.get("bonus_cap", 0.0) or 0.0)
        role_minutes_ref = float(role_cfg.get("minutes_ref", 0.50) or 0.50)
        role_usage_ref = float(role_cfg.get("usage_ref", 1.00) or 1.00)

        outs_used = _to_float_series(df, "role_ctx_outs_used", default=0.0)
        role_on_mask = np.asarray(outs_used.to_numpy(copy=False), dtype="float64") > 0.0
        if role_on_mask.any() and (role_on_w > 0.0 or role_outs_w > 0.0 or role_mult_w > 0.0 or role_minutes_w > 0.0 or role_usage_w > 0.0):
            role_mult = _to_float_series(df, "role_ctx_mult", default=1.0)

            if "minutes_s" in df.columns:
                minutes_s = _to_float_series(df, "minutes_s", default=role_minutes_ref)
            else:
                minutes_s = pd.Series(np.full(len(df), role_minutes_ref, dtype="float64"), index=df.index)

            if "usage_dep_eff" in df.columns:
                usage_eff = _to_float_series(df, "usage_dep_eff", default=role_usage_ref)
            elif "usage_dep" in df.columns:
                usage_eff = _to_float_series(df, "usage_dep", default=role_usage_ref)
            else:
                usage_eff = pd.Series(np.full(len(df), role_usage_ref, dtype="float64"), index=df.index)

            outs_arr = np.asarray(outs_used.to_numpy(copy=True), dtype="float64")
            role_mult_arr = np.asarray(role_mult.to_numpy(copy=True), dtype="float64")
            minutes_arr = np.asarray(minutes_s.to_numpy(copy=True), dtype="float64")
            usage_arr = np.asarray(usage_eff.to_numpy(copy=True), dtype="float64")

            outs_term = np.clip(outs_arr / 3.0, 0.0, 1.0)
            mult_term = np.clip(role_mult_arr - 1.0, -0.20, 0.20) / 0.20
            minutes_term = np.clip(minutes_arr - role_minutes_ref, -0.50, 0.50) / 0.50
            usage_term = np.clip(usage_arr - role_usage_ref, -0.20, 0.20) / 0.20

            bonus_arr = (
                (role_on_w * 1.0)
                + (role_outs_w * outs_term)
                + (role_mult_w * mult_term)
                + (role_minutes_w * minutes_term)
                + (role_usage_w * usage_term)
            )
            bonus_arr = np.where(role_on_mask, bonus_arr, 0.0)
            if role_bonus_cap > 0.0:
                np.clip(bonus_arr, -role_bonus_cap, role_bonus_cap, out=bonus_arr)

            role_bonus = pd.Series(bonus_arr, index=df.index)
            role_priority_arr = np.where(role_on_mask, np.clip(np.maximum(bonus_arr, 0.0), 0.0, role_bonus_cap), 0.0)
            role_priority = pd.Series(role_priority_arr, index=df.index)

    df["role_ctx_allocator_bonus"] = role_bonus
    df["role_ctx_allocator_priority"] = role_priority

    edge_arr = np.asarray(df["edge_score"].to_numpy(copy=False), dtype="float64")
    role_bonus_arr = np.asarray(role_bonus.to_numpy(copy=False), dtype="float64")
    role_priority_arr = np.asarray(role_priority.to_numpy(copy=False), dtype="float64")
    tier_arr = np.asarray(df["tier"].to_numpy(copy=False), dtype=object)
    _any_role_w = (role_bonus.abs().sum() > 0.0) or (role_priority.abs().sum() > 0.0)
    role_presence_arr = np.where(role_on_mask, np.where(tier_arr == "STANDARD", 0.75, 0.35), 0.0) if _any_role_w else np.zeros(len(df), dtype="float64")
    role_lift_arr = np.ones(len(df), dtype="float64")
    if role_priority_arr.any():
        if role_bonus_cap > 0.0:
            lift_scale = np.clip(role_priority_arr / role_bonus_cap, 0.0, 1.0)
        else:
            lift_scale = np.zeros(len(df), dtype="float64")
        role_lift_arr = np.where(role_priority_arr > 0.0, 1.0 + (0.75 * lift_scale), 1.0)

    if legacy_selector_scoring:
        df["allocator_score"] = pd.Series(edge_arr, index=df.index)
    else:
        df["allocator_score"] = pd.Series(
            (edge_arr * role_lift_arr) + role_bonus_arr + role_presence_arr,
            index=df.index,
        )

    # --- Min leg probability filter ---
    min_leg_prob = float(sb.get("min_leg_prob", 0.0) or 0.0)
    if min_leg_prob > 0.0:
        before_len = len(df)
        df = df[df["p_eff"] >= min_leg_prob].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] min_leg_prob={min_leg_prob:.3f} filter: {before_len} -> {len(df)} legs")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- UNDER probability window: hard-exclude UNDER legs outside calibrated range ---
    # Playoff regime analysis (May 8 eval, 1036 UNDER legs):
    #   0.50-0.60: actual=0.38-0.39, gap=+0.14 to +0.19 — underperforming, exclude
    #   0.60-0.70: actual=0.69-0.76, gap=-0.06 to -0.08 — well-calibrated, keep
    #   0.70+:     actual=0.43-0.53, gap=+0.20 to +0.38 — overconfident, exclude
    # Config keys: slip_build.min_under_prob, slip_build.max_under_prob
    min_under_prob = float(sb.get("min_under_prob", 0.0) or 0.0)
    max_under_prob = float(sb.get("max_under_prob", 0.0) or 0.0)
    if (min_under_prob > 0.0 or max_under_prob > 0.0) and "direction" in df.columns:
        before_len = len(df)
        under_mask = df["direction"].astype(str).str.strip().str.upper() == "UNDER"
        drop_mask = pd.Series(False, index=df.index)
        if min_under_prob > 0.0:
            drop_mask = drop_mask | (under_mask & (df["p_eff"] < min_under_prob))
        if max_under_prob > 0.0:
            drop_mask = drop_mask | (under_mask & (df["p_eff"] > max_under_prob))
        df = df[~drop_mask].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] UNDER window [{min_under_prob:.2f}, {max_under_prob:.2f}] filter: {before_len} -> {len(df)} legs (dropped {before_len - len(df)} UNDER legs)")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Injury uncertainty filter: optional hard exclusion.
    # QUESTIONABLE/q_out is normally report-only. OUT/DOUBTFUL is handled upstream
    # by IAEL hard invalidation, so these toggles should remain off unless an
    # explicit audit says soft injury uncertainty should block public output.
    exclude_questionable = bool(sb.get("exclude_questionable", False))
    q_out_threshold_raw = sb.get("exclude_q_out_frac_gt") if isinstance(sb, dict) else None
    has_q_out_threshold = q_out_threshold_raw not in (None, "")
    if exclude_questionable or has_q_out_threshold:
        before_len = len(df)
        drop_mask = pd.Series(False, index=df.index)
        soft_exposure_mask = _single_game_soft_exposure_mask(df, cfg)
        if exclude_questionable and "is_questionable" in df.columns:
            q_vals = pd.to_numeric(df["is_questionable"], errors="coerce").fillna(0.0)
            drop_mask = drop_mask | ((q_vals > 0.0) & ~soft_exposure_mask)
        if has_q_out_threshold and "q_out_frac" in df.columns:
            threshold = float(q_out_threshold_raw)
            q_out_vals = pd.to_numeric(df["q_out_frac"], errors="coerce").fillna(0.0)
            drop_mask = drop_mask | ((q_out_vals > threshold) & ~soft_exposure_mask)
        df = df[~drop_mask].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] injury uncertainty filter: {before_len} -> {len(df)} legs")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Min edge filter: exclude legs below edge threshold ---
    min_edge = float(sb.get("min_edge", 0.0) or 0.0)
    if min_edge > 0.0 and "edge_score" in df.columns:
        before_len = len(df)
        df = df[df["edge_score"] >= min_edge].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] min_edge={min_edge:.3f} filter: {before_len} -> {len(df)} legs")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Leg quality filters: per-tier signal thresholds ---
    # Use player_dir_te to filter STANDARD legs and l20_edge to filter GOBLIN legs.
    # These signals are the strongest predictors of actual leg hit rate and are what
    # the marketed builder uses to achieve its observed ~39.5% slip win rate.
    # Config key: slip_build.leg_quality_filters.{min_standard_player_dir_te, min_goblin_l20_edge}
    lqf = sb.get("leg_quality_filters") if isinstance(sb, dict) else None
    if isinstance(lqf, dict) and "tier" in df.columns:
        min_std_pdte = float(lqf.get("min_standard_player_dir_te", 0.0) or 0.0)
        min_gob_l20  = float(lqf.get("min_goblin_l20_edge", 0.0) or 0.0)

        if min_std_pdte != 0.0 and "player_dir_te" in df.columns:
            before_len = len(df)
            std_mask  = df["tier"].str.upper() == "STANDARD"
            pdte_vals = pd.to_numeric(df["player_dir_te"], errors="coerce")
            # Only apply filter to STANDARD legs; leave GOBLIN/DEMON untouched
            drop_mask = std_mask & (pdte_vals < min_std_pdte)
            df = df[~drop_mask].reset_index(drop=True)
            if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
                print(f"[BUILDER][DEBUG] leg_quality_filters STANDARD player_dir_te>={min_std_pdte}: {before_len} -> {len(df)} legs")

        if min_gob_l20 != 0.0 and "l20_edge" in df.columns:
            before_len = len(df)
            gob_mask  = df["tier"].str.upper() == "GOBLIN"
            l20_vals  = pd.to_numeric(df["l20_edge"], errors="coerce")
            drop_mask = gob_mask & (l20_vals < min_gob_l20)
            df = df[~drop_mask].reset_index(drop=True)
            if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
                print(f"[BUILDER][DEBUG] leg_quality_filters GOBLIN l20_edge>={min_gob_l20}: {before_len} -> {len(df)} legs")

        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Stat+direction exclusion filter ---
    exclude_sd = sb.get("exclude_stat_directions")
    if isinstance(exclude_sd, (list, tuple)) and len(exclude_sd) > 0 and "stat" in df.columns and "direction" in df.columns:
        before_len = len(df)
        sd_key_col = df["stat"].astype(str).str.strip().str.upper() + "_" + df["direction"].astype(str).str.strip().str.lower()
        exclude_set = {str(x).strip().upper() for x in exclude_sd}
        keep_mask = ~sd_key_col.str.upper().isin(exclude_set)
        df = df[keep_mask].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] exclude_stat_directions filter: {before_len} -> {len(df)} legs (excluded {exclude_set})")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Data health filter: exclude legs with missing/bad data ---
    require_healthy_data = bool(sb.get("require_healthy_data", True))
    if require_healthy_data and "data_health_flag" in df.columns:
        before_len = len(df)
        df = df[df["data_health_flag"] == "OK"].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] data_health filter: {before_len} -> {len(df)} legs")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Minimum games filter: exclude G-League callups / thin-sample players ---
    min_nba_games = int(sb.get("min_nba_games", 0))
    if min_nba_games > 0 and "games_used" in df.columns:
        before_len = len(df)
        games_col = pd.to_numeric(df["games_used"], errors="coerce").fillna(0)
        df = df[games_col >= min_nba_games].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] min_nba_games filter ({min_nba_games}): {before_len} -> {len(df)} legs")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    # --- Allowed stats whitelist (e.g. restrict DH to PRA+PTS only) ---
    allowed_stats = sb.get("allowed_stats")
    if isinstance(allowed_stats, (list, tuple)) and len(allowed_stats) > 0 and "stat" in df.columns:
        before_len = len(df)
        allowed_set = {str(s).strip().upper() for s in allowed_stats}
        df = df[df["stat"].astype(str).str.strip().str.upper().isin(allowed_set)].reset_index(drop=True)
        if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
            print(f"[BUILDER][DEBUG] allowed_stats filter {allowed_set}: {before_len} -> {len(df)} legs")
        if df.empty:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    tier_counts = df["tier"].value_counts(dropna=False).to_dict()

    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        print(f"[BUILDER][DEBUG] leg_df tier counts: {tier_counts}")
        print(f"[BUILDER][DEBUG] p_eff source: {best_prob_col if best_prob_col else 'NONE'}")

    for needed in required_tiers:
        if tier_counts.get(needed, 0) == 0:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    if legacy_selector_scoring:
        df = df.sort_values(["tier", "edge_score", "p_eff"], ascending=[True, False, False]).reset_index(drop=True)
    elif "role_ctx_outs_used" in df.columns:
        role_sort = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce")
        if not isinstance(role_sort, pd.Series):
            role_sort = pd.Series(role_sort, index=df.index)
        role_sort_arr = np.asarray(role_sort.to_numpy(copy=True), dtype="float64")
        role_sort_arr[np.isnan(role_sort_arr)] = 0.0
        df["role_ctx_outs_used_sort"] = pd.Series(role_sort_arr, index=df.index)
        # Sort by allocator_score first, then role context as a tiebreaker.
        # Sorting role_ctx_outs_used as primary key concentrates top legs
        # in too few teams, making no_same_team_within_slip impossible for
        # 4-leg and 5-leg slips.
        df = df.sort_values(["tier", "allocator_score", "role_ctx_outs_used_sort", "role_ctx_allocator_priority", "p_eff"], ascending=[True, False, False, False, False]).reset_index(drop=True)
    else:
        df = df.sort_values(["tier", "allocator_score", "role_ctx_allocator_priority", "p_eff"], ascending=[True, False, False, False]).reset_index(drop=True)

    buckets: dict[str, list[pd.Series]] = {}
    for t in required_tiers:
        sub = df[df["tier"] == t].head(int(per_tier)).reset_index(drop=True)
        buckets[t] = [sub.iloc[i] for i in range(len(sub))]

    for t, need in mix.items():
        if len(buckets.get(t, [])) < int(need):
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)


    # -----------------------------
    # A4: temperature / exploration
    # -----------------------------
    # Read builder knobs from cfg (safe defaults).
    sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
    target_pool_mult = int(sb.get("target_pool_mult", 10))
    phase1_frac = float(sb.get("phase1_frac", 0.30))
    phase1_pool_frac = float(sb.get("phase1_pool_frac", 0.60))
    max_players_per_team = int(sb.get("max_players_per_team", 2))  # 2 = allow pairs (production default)

    # Single-game slate detection (2026-05-10): when board only has 1 game on it,
    # override max_players_per_team by leg count. 3-leg stays tight at 2 to force
    # cross-team diversification, 4-leg/5-leg relax to 3 since the slate has only
    # 2 teams to draw from. Falls back to default cap if no override configured.
    sg_caps = sb.get("single_game_caps_by_legs", {}) or {}
    if sg_caps and "team" in df.columns and "opp" in df.columns:
        try:
            unique_games = set()
            for t, o in zip(df["team"].astype(str), df["opp"].astype(str)):
                unique_games.add(tuple(sorted([t, o])))
            if len(unique_games) == 1:
                sg_override = sg_caps.get(int(n_legs)) or sg_caps.get(str(n_legs))
                if sg_override is not None:
                    max_players_per_team = int(sg_override)
                    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
                        print(f"[BUILDER][DEBUG] single-game slate detected: n_legs={n_legs} max_per_team={max_players_per_team}")
        except Exception:
            pass

    no_same_game_within_slip = bool(sb.get("no_same_game_within_slip", False))
    reserved_prop_keys = {str(x) for x in (sb.get("_reserved_prop_keys") or []) if str(x)}

    # Clamp to safe ranges (prevents config typos from breaking sampling).
    if phase1_frac < 0.05:
        phase1_frac = 0.05
    if phase1_frac > 1.0:
        phase1_frac = 1.0
    if phase1_pool_frac < 0.05:
        phase1_pool_frac = 0.05
    if phase1_pool_frac > 0.95:
        phase1_pool_frac = 0.95

    rng = random.Random(int(seed))
    slips: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempts = 0

    target_pool = max(int(top_n) * int(target_pool_mult), int(top_n))
    target_p1 = int(target_pool * float(phase1_pool_frac))

    # Build phase buckets: Phase 1 uses only top `phase1_frac` slice of each tier bucket
    buckets_p1: dict[str, list[pd.Series]] = {}
    buckets_p2: dict[str, list[pd.Series]] = {}

    for t in required_tiers:
        full = buckets[t]
        n_full = len(full)

        # ceil(n_full * phase1_frac) without importing math
        n_p1 = int((n_full * float(phase1_frac)) + 0.999999)
        # Must be sample-able for this tier
        if n_p1 < int(mix.get(t, 0)):
            n_p1 = int(mix.get(t, 0))

        buckets_p1[t] = full[:n_p1]
        buckets_p2[t] = full  # phase 2 = full per_tier slice

    rej_composition = 0

    def _run_phase(phase_buckets: dict[str, list[pd.Series]], phase_target: int) -> None:
        nonlocal attempts, slips, seen, rej_composition

        # penalty knobs (Step 3)
        sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
        pen_cfg = sb.get("penalty", {}) if isinstance(sb, dict) else {}
        team_w = float(pen_cfg.get("team_w", 0.0) or 0.0)
        family_w = float(pen_cfg.get("family_w", 0.0) or 0.0)
        team_power = float(pen_cfg.get("team_power", 2.0) or 2.0)
        family_power = float(pen_cfg.get("family_power", 2.0) or 2.0)
        frag_power = float(pen_cfg.get("frag_power", 1.0) or 1.0)
        leg_norm = float(max(1, int(n_legs) - 1))

        def _team_key(r: pd.Series) -> str:
            for k in ("team", "team_abbrev", "player_team"):
                if k in r.index:
                    v = str(r[k]).strip()
                    if v and v.lower() != "nan":
                        return normalize_team_abbr(v)
            return ""

        _stat_family_mode = str(sb.get("stat_family_mode", "coarse") or "coarse").strip().lower()

        def _family_key(r: pd.Series) -> str:
            s = ""
            for k in ("stat", "stat_type", "market"):
                if k in r.index:
                    s = str(r[k]).strip()
                    if s and s.lower() != "nan":
                        break
            u = s.upper()

            # --- Fine mode: per-stat identity (PTS != AST != PRA) ---
            if _stat_family_mode == "fine":
                if u:
                    return u
                return "OTHER"

            # --- Coarse mode (legacy default): 5 buckets ---
            usage = {
                "PTS", "POINTS",
                "AST", "ASSISTS",
                "PRA", "PTS+REBS+ASTS", "PTS+REB+AST",
                "PR", "PTS+REBS", "PTS+REB",
                "PA", "PTS+ASTS", "PTS+AST",
                "RA", "REBS+ASTS", "REB+AST",
                "P+A", "PTS+AST",
                "P+R", "PTS+REB",
                "A+R", "REB+AST",
            }
            rebounds = {"REB", "REBS", "REBOUNDS", "OREB", "DREB"}
            threes = {"FG3M", "3PM", "3PTM", "3PT MADE", "THREES"}
            stocks = {"BLK", "BLOCKS", "STL", "STEALS", "BLK+STL", "STL+BLK", "BLOCKS+STEALS"}

            if u in usage or "+" in u:
                # treat any combo with '+' as usage/minutes-sensitive unless it matches a variance bucket below
                return "USAGE"
            if u in rebounds:
                return "REB"
            if u in threes:
                return "THREES"
            if u in stocks:
                return "STOCKS"
            return "OTHER"

        _dbg = (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1"
        if _dbg:
            print(f"[BUILDER][DEBUG] _run_phase: phase_target={phase_target}, attempts_so_far={attempts}, max_attempts={max_attempts}, bucket_sizes={{{', '.join(f'{t}: {len(b)}' for t, b in phase_buckets.items())}}}")

        while attempts < int(max_attempts) and len(slips) < phase_target:
            attempts += 1

            chosen: list[pd.Series] = []
            for t, need in mix.items():
                chosen.extend(rng.sample(phase_buckets[t], int(need)))

            pids: list[str] = []
            players: list[str] = []
            ok = True

            for r in chosen:
                if "projection_id" not in r.index:
                    ok = False
                    break

                pid = str(r["projection_id"]).strip()
                if not pid or pid.lower() == "nan":
                    ok = False
                    break
                pids.append(pid)

                player_name = str(r["player"]).strip().lower() if "player" in r.index else ""
                players.append(player_name)

            if not ok:
                continue

            # Hard constraint: no duplicate projection_id within slip
            if len(set(pids)) != len(pids):
                continue

            # Hard constraint: no duplicate player within slip (your requirement)
            if len(set(players)) != len(players):
                continue

            if reserved_prop_keys:
                if any(prop_key_from_mapping(r) in reserved_prop_keys for r in chosen):
                    continue

            # Optional hard constraint: max N players from the same team within a slip.
            if max_players_per_team > 0:
                chosen_teams: list[str] = []
                for r in chosen:
                    tk = _team_key(r)
                    if not tk:
                        continue
                    chosen_teams.append(tk)
                team_counts = Counter(chosen_teams)
                if team_counts and max(team_counts.values()) > max_players_per_team:
                    continue

            # Optional hard constraint: no two legs from the same game within a slip.
            if no_same_game_within_slip:
                chosen_games: list[str] = []
                for r in chosen:
                    gid = ""
                    for k in ("game_id", "gameId"):
                        if k in r.index:
                            v = str(r[k]).strip()
                            if v and v.lower() != "nan":
                                gid = v
                                break
                    if gid:
                        chosen_games.append(gid)
                if len(set(chosen_games)) != len(chosen_games):
                    continue

            # Optional hard constraint: max N legs of same stat type per slip
            max_same_stat = int(sb.get("max_same_stat", 0) or 0)
            if max_same_stat > 0:
                stat_counts: dict[str, int] = {}
                for r in chosen:
                    st = ""
                    for k in ("stat", "stat_type"):
                        if k in r.index:
                            v = str(r[k]).strip().upper()
                            if v and v.lower() != "nan":
                                st = v
                                break
                    if st:
                        stat_counts[st] = stat_counts.get(st, 0) + 1
                if stat_counts and max(stat_counts.values()) > max_same_stat:
                    continue

            # Optional hard constraint: max N legs of a given direction per slip
            max_dir_per_slip = sb.get("max_direction_per_slip")
            if isinstance(max_dir_per_slip, dict):
                dir_counts: dict[str, int] = {}
                for r in chosen:
                    d = ""
                    if "direction" in r.index:
                        d = str(r["direction"]).strip().lower()
                    if d and d != "nan":
                        dir_counts[d] = dir_counts.get(d, 0) + 1
                dir_ok = True
                for d_key, d_max in max_dir_per_slip.items():
                    d_max = int(d_max or n_legs)
                    if dir_counts.get(str(d_key).strip().lower(), 0) > d_max:
                        dir_ok = False
                        break
                if not dir_ok:
                    continue

            sg_ok, sg_reasons, sg_metrics = single_game_slip_rule_status(chosen, cfg, n_legs=n_legs)
            if not sg_ok:
                continue

            composition_reason = composition_drop_reason_for_legs(
                chosen,
                cfg,
                slate_games=slate_games,
                n_legs=n_legs,
            )
            if composition_reason:
                rej_composition += 1
                continue

            scored = _score_slip(
                chosen,
                n_legs,
                payout_power_mult,
                pricing_engine=str(pricing_engine or "atlas"),
                cfg=cfg,
            )

            role_bonus_total = 0.0
            role_on_count = 0
            if not legacy_selector_scoring:
                for r in chosen:
                    try:
                        role_bonus_total += float(r.get("role_ctx_allocator_bonus", 0.0) or 0.0)
                    except Exception:
                        pass
                    try:
                        if int(float(r.get("role_ctx_outs_used", 0) or 0)) > 0:
                            role_on_count += 1
                    except Exception:
                        pass

            legs_str = scored.get("legs", "")
            if not mix_ok_fn(n_legs, legs_str):
                continue

            key = scored.get("slip_key") or legs_str
            if key in seen:
                continue


            # ---------------------------
            # Step 3: diversification penalties
            # ---------------------------
            # TEAM penalty (quadratic overage)
            pen_team = 0.0
            if team_w > 0.0:
                team_counts: dict[str, int] = {}
                for r in chosen:
                    tk = _team_key(r)
                    if not tk:
                        continue
                    team_counts[tk] = team_counts.get(tk, 0) + 1

                for _, n in team_counts.items():
                    over = n - 1
                    if over > 0:
                        ratio = float(over) / leg_norm
                        pen_team += team_w * float(ratio ** team_power)

            # FAMILY penalty (quadratic overage)
            pen_family = 0.0
            if family_w > 0.0:
                fam_counts: dict[str, int] = {}
                for r in chosen:
                    fk = _family_key(r)
                    fam_counts[fk] = fam_counts.get(fk, 0) + 1

                for _, n in fam_counts.items():
                    over = n - 1
                    if over > 0:
                        ratio = float(over) / leg_norm
                        pen_family += family_w * float(ratio ** family_power)

            frag_w = float(pen_cfg.get("frag_w", 0.0))
            role_ctx_share_w = float(pen_cfg.get("role_ctx_share_w", 0.0) or 0.0)
            role_ctx_share_allow = float(pen_cfg.get("role_ctx_share_allow", 1.0) or 1.0)
            role_ctx_share_power = float(pen_cfg.get("role_ctx_share_power", 2.0) or 2.0)

            pen_frag = 0.0
            if frag_w > 0:
                # Mean-based fragility penalty (leg-count invariant)
                frags = []
                for rec in chosen:
                    try:
                        v = float(rec.get("fragility", 0.0))
                    except Exception:
                        v = 0.0
                    if v == v:  # not NaN
                        frags.append(v)
                if frags:
                    mean_frag = sum(frags) / float(len(frags))
                    pen_frag = frag_w * float(mean_frag ** frag_power)

            # Minutes volatility penalty (high min_std = unpredictable playing time)
            min_std_w = float(pen_cfg.get("min_std_w", 0.0) or 0.0)
            min_std_ref = float(pen_cfg.get("min_std_ref", 6.0) or 6.0)  # ~median
            pen_min_std = 0.0
            if min_std_w > 0:
                min_stds = []
                for rec in chosen:
                    try:
                        v = float(rec.get("min_std", 0.0))
                    except Exception:
                        v = 0.0
                    if v == v:  # not NaN
                        min_stds.append(v)
                if min_stds:
                    mean_min_std = sum(min_stds) / float(len(min_stds))
                    excess = max(mean_min_std - min_std_ref, 0.0) / min_std_ref
                    pen_min_std = min_std_w * excess

            pen_role_ctx = 0.0
            if role_ctx_share_w > 0.0 and chosen:
                role_ctx_share = float(role_on_count / len(chosen))
                over = max(role_ctx_share - role_ctx_share_allow, 0.0)
                if over > 0.0:
                    pen_role_ctx = role_ctx_share_w * float(over ** role_ctx_share_power)

            pen_minute_risk = 0.0
            if chosen and any("minute_risk_penalty" in rec.index for rec in chosen):
                vals = []
                for rec in chosen:
                    try:
                        v = float(rec.get("minute_risk_penalty", 0.0))
                    except Exception:
                        v = 0.0
                    if v == v:
                        vals.append(v)
                if vals:
                    pen_minute_risk = sum(vals) / float(len(vals))

            pen_total = pen_team + pen_family + pen_frag + pen_min_std + pen_role_ctx + pen_minute_risk

            # Compute base score for this candidate (depends on sort_mode)
            hit_prob = float(scored.get("hit_prob", 0.0) or 0.0)
            payout_mult = float(scored.get("payout_mult_eff", scored.get("payout_mult", 0.0)) or 0.0)

            mode = str(sort_mode or "").lower().strip()
            if mode in ("hit", "hit_prob", "win", "winprob"):
                base_score = hit_prob
            elif mode == "hybrid":
                k = float(((cfg or {}).get("slip_rank", {}) or {}).get("ev_payout_power", 1) or 1)
                hybrid_ev_weight = float(((cfg or {}).get("slip_rank", {}) or {}).get("hybrid_ev_weight", 0.35) or 0.35)
                hybrid_ev_weight = float(np.clip(hybrid_ev_weight, 0.0, 1.0))
                base_score = hit_prob * (payout_mult ** (k * hybrid_ev_weight))
            else:
                # EV board: rank_ev = hit_prob * payout_mult^k (k from slip_rank.ev_payout_power)
                k = float(((cfg or {}).get("slip_rank", {}) or {}).get("ev_payout_power", 1) or 1)
                base_score = hit_prob * (payout_mult ** k)

            scored["pen_team"] = pen_team
            scored["pen_family"] = pen_family
            scored["pen_frag"] = pen_frag
            scored["pen_min_std"] = pen_min_std
            scored["pen_role_ctx"] = pen_role_ctx
            scored["pen_minute_risk"] = pen_minute_risk
            scored["pen_total"] = pen_total
            scored["minute_risk_legs"] = int(
                sum(1 for rec in chosen if float(rec.get("minute_risk_penalty", 0.0) or 0.0) > 0.0)
            )
            scored["role_ctx_bonus"] = role_bonus_total
            scored["role_ctx_on_legs"] = int(role_on_count)
            scored["role_ctx_on_share"] = float(role_on_count / len(chosen)) if chosen else 0.0
            if sg_metrics:
                scored.update(sg_metrics)
                scored["single_game_rule_reasons"] = ",".join(sg_reasons)
            role_share_bonus_w = 0.15
            if isinstance(cfg, dict):
                role_share_bonus_w = float(((cfg.get("slip_rank", {}) or {}).get("role_ctx_share_bonus_w", 0.15)) or 0.0)
            role_share_bonus = 0.0 if legacy_selector_scoring else role_share_bonus_w * float(role_on_count)
            scored["score_adj"] = float(base_score - pen_total + role_bonus_total + role_share_bonus)
            scored["players"] = [p for p in players if p]

            # keep existing slip fields, just add penalties + adjusted score
            seen.add(key)
            slips.append(scored)


    # Phase 1: exploit (top slice) — cap at half the budget so phase 2 always runs
    phase1_attempt_cap = max_attempts // 2
    saved_max = max_attempts
    max_attempts = phase1_attempt_cap
    _run_phase(buckets_p1, target_p1)
    max_attempts = saved_max  # restore full budget for phase 2

    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        print(f"[BUILDER][DEBUG] After phase1: slips={len(slips)}, attempts={attempts}, counters=N/A")

    # Phase 2: explore (full bucket) until full target_pool reached
    _run_phase(buckets_p2, target_pool)

    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        print(f"[BUILDER][DEBUG] After phase2: slips={len(slips)}, attempts={attempts}")

    out = pd.DataFrame(slips)
    if out.empty:
        return out

    # hit_prob / ev_mult numeric sanitization (NO fillna) — use writable arrays
    hp = pd.to_numeric(out["hit_prob"] if "hit_prob" in out.columns else 0.0, errors="coerce")
    if not isinstance(hp, pd.Series):
        hp = pd.Series(hp, index=out.index)
    hp_arr = np.asarray(hp.to_numpy(copy=True), dtype="float64")  # writable
    hp_arr[np.isnan(hp_arr)] = 0.0
    out["hit_prob"] = pd.Series(hp_arr, index=out.index)

    ev = pd.to_numeric(out["ev_mult"] if "ev_mult" in out.columns else 0.0, errors="coerce")
    if not isinstance(ev, pd.Series):
        ev = pd.Series(ev, index=out.index)
    ev_arr = np.asarray(ev.to_numpy(copy=True), dtype="float64")  # writable
    ev_arr[np.isnan(ev_arr)] = 0.0
    out["ev_mult"] = pd.Series(ev_arr, index=out.index)

    pm = pd.to_numeric(out["payout_mult"] if "payout_mult" in out.columns else 0.0, errors="coerce")
    if not isinstance(pm, pd.Series):
        pm = pd.Series(pm, index=out.index)
    pm_arr = np.asarray(pm.to_numpy(copy=True), dtype="float64")  # writable
    pm_arr[np.isnan(pm_arr)] = 0.0
    out["payout_mult"] = pd.Series(pm_arr, index=out.index)

    pme = pd.to_numeric(out["payout_mult_eff"] if "payout_mult_eff" in out.columns else 0.0, errors="coerce")
    if not isinstance(pme, pd.Series):
        pme = pd.Series(pme, index=out.index)
    pme_arr = np.asarray(pme.to_numpy(copy=True), dtype="float64")  # writable
    pme_arr[np.isnan(pme_arr)] = 0.0
    out["payout_mult_eff"] = pd.Series(pme_arr, index=out.index)

    mode = str(sort_mode).lower().strip()
    winprob_mode = mode in ("hit", "hit_prob", "win", "winprob")
    hybrid_mode = mode == "hybrid"

    # Prefer score_adj if present (Step 3.5). Fallback to legacy behavior if absent.
    has_score_adj = "score_adj" in out.columns
    if has_score_adj:
        sa = pd.to_numeric(out["score_adj"], errors="coerce")
        if not isinstance(sa, pd.Series):
            sa = pd.Series(sa, index=out.index)
        sa_arr = np.asarray(sa.to_numpy(copy=True), dtype="float64")  # writable
        sa_arr[np.isnan(sa_arr)] = -1e9  # send bad rows to bottom
        out["score_adj"] = pd.Series(sa_arr, index=out.index)

    if mode in ("hit", "hit_prob", "win", "winprob"):
        use_score_adj_for_winprob = False
        if isinstance(cfg, dict):
            use_score_adj_for_winprob = bool(((cfg.get("slip_rank", {}) or {}).get("use_score_adj_for_winprob", False)))
        if has_score_adj and use_score_adj_for_winprob:
            out = out.sort_values(["score_adj", "hit_prob"], ascending=[False, False]).reset_index(drop=True)
        else:
            # WinProb = pure probability ordering (no payout/penalty noise)
            out = out.sort_values(["hit_prob"], ascending=[False]).reset_index(drop=True)

    elif hybrid_mode:
        k = float(cfg.get("slip_rank", {}).get("ev_payout_power", 1)) if isinstance(cfg, dict) else 1.0
        hybrid_ev_weight = float(((cfg or {}).get("slip_rank", {}) or {}).get("hybrid_ev_weight", 0.35) or 0.35) if isinstance(cfg, dict) else 0.35
        hybrid_ev_weight = float(np.clip(hybrid_ev_weight, 0.0, 1.0))
        pm_col = "payout_mult_eff" if "payout_mult_eff" in out.columns else "payout_mult"
        out["rank_hybrid"] = out["hit_prob"] * (out[pm_col] ** (k * hybrid_ev_weight))

        if has_score_adj:
            out = out.sort_values(["score_adj", "rank_hybrid", "hit_prob"], ascending=[False, False, False]).reset_index(drop=True)
        else:
            out = out.sort_values(["rank_hybrid", "hit_prob"], ascending=[False, False]).reset_index(drop=True)

    else:
        # EV board: keep rank_ev for transparency, but sort by score_adj if present
        k = float(cfg.get("slip_rank", {}).get("ev_payout_power", 1)) if isinstance(cfg, dict) else 1.0
        pm_col = "payout_mult_eff" if "payout_mult_eff" in out.columns else "payout_mult"
        out["rank_ev"] = out["hit_prob"] * (out[pm_col] ** k)

        if has_score_adj:
            out = out.sort_values(["score_adj", "rank_ev", "hit_prob"], ascending=[False, False, False]).reset_index(drop=True)
        else:
            out = out.sort_values(["rank_ev", "hit_prob"], ascending=[False, False]).reset_index(drop=True)

    out = dedupe_slips_by_key(out).reset_index(drop=True)
    if out.empty:
        return out
    candidate_pool = out.copy()
    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        role_dbg = pd.to_numeric(candidate_pool.get("role_ctx_on_legs", 0), errors="coerce")
        if not isinstance(role_dbg, pd.Series):
            role_dbg = pd.Series(role_dbg, index=candidate_pool.index)
        role_dbg_arr = np.asarray(role_dbg.to_numpy(copy=True), dtype="float64")
        role_dbg_arr[np.isnan(role_dbg_arr)] = 0.0
        role_dbg_nz = int((role_dbg_arr > 0).sum())
        role_dbg_max = float(role_dbg_arr.max()) if len(role_dbg_arr) else 0.0
        print(f"[BUILDER][DEBUG] candidate_pool rows={len(candidate_pool)} role_nz={role_dbg_nz} role_max={role_dbg_max}")
        if rej_composition:
            print(
                "[BUILDER][DEBUG] composition rejected candidate slips="
                f"{rej_composition} slate_games={slate_games} n_legs={n_legs}"
            )

    # -----------------------------
    # Step 4: Beam selection (C3) with portfolio exposure caps
    # -----------------------------
    sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
    beam_width = int(sb.get("beam_width", 100))
    max_slips_per_player = int(sb.get("max_slips_per_player", 5))
    greedy_top_off_enabled = bool(sb.get("greedy_top_off_enabled", True))
    debug_builder = (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1"
    rej_exposure_cap = 0
    rej_missing_players = 0
    beam_window_size = 0
    
    def _extract_player(leg: str) -> str:
        s = (leg or "").strip()
        if not s:
            return ""
        # prefer split on " OVER " / " UNDER " (your leg strings look like "Name OVER STAT ...")
        if " OVER " in s:
            return s.split(" OVER ", 1)[0].strip().lower()
        if " UNDER " in s:
            return s.split(" UNDER ", 1)[0].strip().lower()
        # fallback: whole string (still deterministic)
        return s.lower()

    # Determine which leg sources exist.
    # IMPORTANT: expand_legs() is applied later in the pipeline, so we cannot rely on leg_1..leg_5
    # being present here. We enforce portfolio caps primarily off the canonical `players` list.
    leg_cols = [c for c in ["leg_1", "leg_2", "leg_3", "leg_4", "leg_5"] if c in out.columns]

    # Fallback leg strings for parsing (only used when `players` is missing/unusable)
    # Expected format: single string with legs separated by " | "
    has_legs_str = "legs" in out.columns

    # Precompute per-row slip score used for beam selection
    if winprob_mode:
        scores = pd.to_numeric(out["hit_prob"], errors="coerce")
    else:
        scores = pd.to_numeric(
            out["score_adj"] if "score_adj" in out.columns else out.get("rank_ev", 0.0),
            errors="coerce",
        )

    if not isinstance(scores, pd.Series):
        scores = pd.Series(scores, index=out.index)

    score_arr = np.asarray(scores.to_numpy(copy=True), dtype="float64")  # writable
    score_arr[np.isnan(score_arr)] = -1e9  # send bad rows to bottom
    beam_role_bonus = float((((cfg or {}).get("slip_build", {}) or {}).get("role_ctx", {}) or {}).get("beam_bonus", 25.0))
    beam_score_arr = np.asarray(score_arr, dtype="float64").copy()
    role_leg_counts = np.zeros(len(out), dtype=int)
    if "role_ctx_on_legs" in out.columns:
        role_leg_counts = np.asarray(pd.to_numeric(out["role_ctx_on_legs"], errors="coerce").fillna(0.0).to_numpy(copy=False), dtype="float64")
        np.clip(role_leg_counts, 0.0, None, out=role_leg_counts)
        role_leg_counts = role_leg_counts.astype(int, copy=False)
    if role_leg_counts.any() and not winprob_mode:
        beam_score_arr = beam_score_arr + (role_leg_counts.astype("float64") * beam_role_bonus)
    role_ctx_cfg = ((cfg or {}).get("slip_build", {}) or {}).get("role_ctx", {}) if isinstance(cfg, dict) else {}
    role_quota_per_10 = int(role_ctx_cfg.get("target_role_slips_per_10", role_ctx_cfg.get("min_role_legs_per_10", 4)) or 4)
    role_target_slips = 0 if winprob_mode else max(0, int(np.ceil((float(top_n) * float(role_quota_per_10)) / 10.0)))

    row_players: list[list[str]] = []
    has_players_col = "players" in out.columns

    for i in range(len(out)):
        ps: list[str] = []

        if has_players_col:
            raw = out.at[i, "players"]

            # expected: list-like; but be defensive
            if isinstance(raw, (list, tuple)):
                ps = [str(x).strip().lower() for x in raw if str(x).strip()]
            else:
                ps = []

            # de-dupe while preserving order
            if ps:
                ps = list(dict.fromkeys(ps))

        # Fallback to leg parsing ONLY if we didn't get usable players
        if not ps:
            if leg_cols:
                for c in leg_cols:
                    v = out.at[i, c]
                    p = _extract_player(str(v) if pd.notna(v) else "")
                    if p:
                        ps.append(p)
            elif has_legs_str:
                # Parse from the pipe-delimited `legs` string
                slegs = out.at[i, "legs"]
                if pd.notna(slegs):
                    for part in str(slegs).split(" | "):
                        p = _extract_player(part)
                        if p:
                            ps.append(p)

            if ps:
                ps = list(dict.fromkeys(ps))

        # enforce within-slip uniqueness defensively
        ps = list(dict.fromkeys(ps))
        row_players.append(ps)

    # Limit beam expansion independently from the candidate-pool size.
    cand_order = list(np.argsort(-beam_score_arr))  # indices sorted by beam score desc
    legacy_tied_window_defaults = bool(sb.get("legacy_tied_window_defaults", False))
    if legacy_tied_window_defaults:
        default_window_mult = max(int(target_pool_mult), 12)
        default_window_max = max(default_window_mult, min(default_window_mult * 4, 48))
        default_window_min = max(int(top_n) * 8, beam_width * 2, int(target_pool))
    else:
        default_window_mult = max(12, min(int(top_n) * 2, 24))
        default_window_max = max(default_window_mult, min(default_window_mult * 2, 48))
        default_window_min = max(int(top_n) * 8, min(beam_width * 2, int(top_n) * 20))

    window_mult = int(sb.get("beam_window_mult", default_window_mult))
    if window_mult < 4:
        window_mult = 4

    window_max_mult = int(sb.get("beam_window_max_mult", default_window_max))
    if window_max_mult < window_mult:
        window_max_mult = window_mult

    window_min_size = int(sb.get("beam_window_min", default_window_min))
    if window_min_size < int(top_n):
        window_min_size = int(top_n)
    window_bumps = 0
    cand_cap = max(int(top_n) * window_mult, window_min_size)
    cand_cap = min(len(cand_order), cand_cap)
    cand_order = cand_order[:cand_cap]
    beam_window_size = len(cand_order)

    # Soft exposure penalty config (gated — defaults to OFF / hard cap only)
    _soft_exposure_cfg = sb.get("soft_exposure", {}) if isinstance(sb, dict) else {}
    _soft_exposure_enabled = bool(_soft_exposure_cfg.get("enabled", False))
    _soft_exposure_threshold = int(_soft_exposure_cfg.get("threshold", max(1, max_slips_per_player - 1)))
    _soft_exposure_penalty = float(_soft_exposure_cfg.get("penalty_per_extra", 0.05) or 0.05)
    # Hard cap stays at max_slips_per_player regardless of soft penalty mode
    _soft_hard_cap = int(_soft_exposure_cfg.get("hard_cap", max_slips_per_player + 1))

    def _can_add(counts: dict[str, int], players: list[str]) -> bool:
        cap = _soft_hard_cap if _soft_exposure_enabled else max_slips_per_player
        for p in players:
            if counts.get(p, 0) + 1 > cap:
                return False
        return True

    def _exposure_penalty(counts: dict[str, int], players: list[str]) -> float:
        if not _soft_exposure_enabled:
            return 0.0
        pen = 0.0
        for p in players:
            over = (counts.get(p, 0) + 1) - _soft_exposure_threshold
            if over > 0:
                pen += _soft_exposure_penalty * float(over * over)  # quadratic
        return pen

    def _add_counts(counts: dict[str, int], players: list[str]) -> dict[str, int]:
        nc = dict(counts)
        for p in players:
            nc[p] = nc.get(p, 0) + 1
        return nc

    seed_selected: list[int] = []
    seed_counts: dict[str, int] = {}
    seed_total = 0.0
    seed_role_count = 0
    if role_target_slips > 0 and role_leg_counts.any():
        for idx in np.argsort(-beam_score_arr):
            role_legs = int(role_leg_counts[idx])
            if role_legs <= 0:
                continue
            if seed_role_count >= role_target_slips:
                break
            keys = row_players[idx]
            if not keys:
                continue
            if not _can_add(seed_counts, keys):
                continue
            seed_selected.append(int(idx))
            seed_counts = _add_counts(seed_counts, keys)
            seed_total += float(beam_score_arr[idx])
            seed_role_count += 1

    if seed_selected:
        seed_set = set(seed_selected)
        cand_order = [idx for idx in cand_order if idx not in seed_set]
    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        print(f"[BUILDER][DEBUG] role seed count={len(seed_selected)} role_seed_slips={seed_role_count} quota={role_target_slips}")

    # Beam state: (total_score, selected_indices, exposure_counts_dict, role_active_slip_count)
    beam: list[tuple[float, list[int], dict[str, int], int]] = [(seed_total, list(seed_selected), dict(seed_counts), int(seed_role_count))]

    # Beam select top_n slips
    remaining_steps = max(0, int(top_n) - len(seed_selected))
    for _step in range(remaining_steps):
        next_beam: list[tuple[float, list[int], dict[str, int], int]] = []

        for total, sel, counts, role_count in beam:
            used = set(sel)
            for idx in cand_order:
                if idx in used:
                    continue
                keys = row_players[idx]  # canonical player identity keys
                if not keys:
                    rej_missing_players += 1
                    continue
                if not _can_add(counts, keys):
                    rej_exposure_cap += 1
                    continue

                new_role_count = role_count + (1 if int(role_leg_counts[idx]) > 0 else 0)

                exp_pen = _exposure_penalty(counts, keys)
                new_total = total + float(beam_score_arr[idx]) - exp_pen
                new_sel = sel + [idx]
                new_counts = _add_counts(counts, keys)
                next_beam.append((new_total, new_sel, new_counts, new_role_count))

        if not next_beam:
            # Beam stalled. Try widening candidate window (NO cap relaxation).
            beam_window_growth = float(sb.get("beam_window_growth", 2.0) or 2.0)
            if beam_window_growth < 1.1:
                beam_window_growth = 1.1
            if window_mult < window_max_mult:
                window_mult = min(window_max_mult, int(window_mult * beam_window_growth + 0.5))
                window_bumps += 1

                cand_cap = max(int(top_n) * window_mult, window_min_size)
                cand_order = list(np.argsort(-beam_score_arr))
                cand_cap = min(len(cand_order), cand_cap)
                cand_order = cand_order[:cand_cap]
                beam_window_size = len(cand_order)

                if debug_builder:
                    print(f"[BUILDER][DEBUG] beam stalled -> widen window | window_mult={window_mult} cap={cand_cap} window_size={beam_window_size}")

                # retry this beam depth with the widened window
                continue

            # No more widening allowed: stop expanding
            break

        # Keep best beam_width partial portfolios
        next_beam.sort(key=lambda x: (x[3], x[0]), reverse=True)
        beam = next_beam[:beam_width]

    # Choose best completed portfolio (prefer exact size = top_n)
    best = None
    for total, sel, counts, role_count in beam:
        if len(sel) == int(top_n) and role_count >= role_target_slips:
            best = (total, sel)
            break
    if best is None:
        # fallback: take the longest portfolio we could build
        beam.sort(key=lambda x: (len(x[1]), x[3], x[0]), reverse=True)
        best = (beam[0][0], beam[0][1])

    selected_positions = list(best[1])
    out = candidate_pool.iloc[selected_positions].reset_index(drop=True)

    if role_target_slips > 0:
        role_candidate_positions = [i for i in range(len(candidate_pool)) if int(role_leg_counts[i]) > 0]
        role_candidate_positions.sort(key=lambda i: float(beam_score_arr[i]), reverse=True)

        filler_candidates = list(range(len(candidate_pool)))
        filler_candidates.sort(key=lambda i: float(beam_score_arr[i]), reverse=True)

        forced_positions: list[int] = []
        forced_counts: dict[str, int] = {}
        forced_role_count = 0

        for cand_idx in role_candidate_positions:
            cand_role_legs = int(role_leg_counts[cand_idx])
            if cand_role_legs <= 0:
                continue
            if forced_role_count >= role_target_slips:
                break
            cand_players = row_players[cand_idx]
            if not cand_players:
                continue
            if not _can_add(forced_counts, cand_players):
                continue
            forced_positions.append(cand_idx)
            forced_counts = _add_counts(forced_counts, cand_players)
            forced_role_count += 1

        if forced_role_count == role_target_slips:
            combined_positions = list(forced_positions)
            combined_counts = dict(forced_counts)
            combined_set = set(combined_positions)

            for idx in filler_candidates:
                if len(combined_positions) >= int(top_n):
                    break
                if idx in combined_set:
                    continue
                if int(role_leg_counts[idx]) > 0:
                    continue
                if _can_add(combined_counts, row_players[idx]):
                    combined_positions.append(idx)
                    combined_set.add(idx)
                    combined_counts = _add_counts(combined_counts, row_players[idx])

            if len(combined_positions) == int(top_n):
                selected_positions = list(combined_positions)
                out = candidate_pool.iloc[selected_positions].reset_index(drop=True)
                if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
                    print(f"[BUILDER][DEBUG] greedy role rebuild applied | forced_role_slips={forced_role_count} combined_rows={len(combined_positions)}")

    if greedy_top_off_enabled and len(selected_positions) < int(top_n):
        selected_set = set(selected_positions)
        selected_counts: dict[str, int] = {}
        selected_role_count = 0

        for pos in selected_positions:
            selected_counts = _add_counts(selected_counts, row_players[pos])
            if int(role_leg_counts[pos]) > 0:
                selected_role_count += 1

        preferred_fillers = list(range(len(candidate_pool)))
        preferred_fillers.sort(
            key=lambda i: (
                1 if selected_role_count < role_target_slips and int(role_leg_counts[i]) > 0 else 0,
                float(beam_score_arr[i]),
            ),
            reverse=True,
        )

        for pos in preferred_fillers:
            if len(selected_positions) >= int(top_n):
                break
            if pos in selected_set:
                continue
            cand_players = row_players[pos]
            if not cand_players:
                continue
            if not _can_add(selected_counts, cand_players):
                continue
            selected_positions.append(pos)
            selected_set.add(pos)
            selected_counts = _add_counts(selected_counts, cand_players)
            if int(role_leg_counts[pos]) > 0:
                selected_role_count += 1

        out = candidate_pool.iloc[selected_positions].reset_index(drop=True)
        if debug_builder and len(selected_positions) >= int(top_n):
            print(
                f"[BUILDER][DEBUG] greedy top-off applied | selected={len(selected_positions)} "
                f"requested={int(top_n)} role_selected={selected_role_count}"
            )
    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        if len(out) and "role_ctx_on_legs" in out.columns:
            final_role_counts_arr = np.asarray(pd.to_numeric(out["role_ctx_on_legs"], errors="coerce"), dtype="float64")
            final_role_count_dbg = int((np.nan_to_num(final_role_counts_arr, nan=0.0) > 0.0).sum())
        else:
            final_role_count_dbg = 0
        print(f"[BUILDER][DEBUG] final selected role_active_slips={final_role_count_dbg} rows={len(out)}")

    out["beam_selected"] = 1

    if winprob_mode:
        out = out.sort_values(["hit_prob"], ascending=[False]).reset_index(drop=True)

    if len(out) < int(top_n):
        import warnings
        warnings.warn(
            "Beam could not assemble requested portfolio size without relaxing constraints: "
            f"selected={len(out)} requested={int(top_n)} "
            f"beam_window_size={beam_window_size} "
            f"rej_exposure_cap={rej_exposure_cap} rej_missing_players={rej_missing_players} "
            f"rej_composition={rej_composition} "
            f"window_mult={window_mult} window_bumps={window_bumps}",
            stacklevel=2,
        )
        if len(out) == 0:
            return out

    # HARD ASSERT: portfolio exposure must bind off canonical players list
    if "players" not in out.columns:
        raise RuntimeError(
            "Beam selection requires canonical 'players' column for exposure enforcement "
            "(do not parse from leg strings)."
        )

    counts: dict[str, int] = {}
    for i in range(len(out)):
        raw = out.at[i, "players"]

        if isinstance(raw, (list, tuple)):
            ps = [str(x).strip().lower() for x in raw if str(x).strip()]
        else:
            raise RuntimeError(
                f"Beam selection requires out['players'] to be list-like; row {i} has type={type(raw)} value={raw!r}"
            )

        # de-dupe per slip (belt + suspenders)
        ps = list(dict.fromkeys(ps))

        for p in ps:
            counts[p] = counts.get(p, 0) + 1

    offenders = sorted([(p, n) for p, n in counts.items() if n > max_slips_per_player], key=lambda x: (-x[1], x[0]))
    if offenders:
        top = ", ".join([f"{p}:{n}" for p, n in offenders[:20]])
        raise RuntimeError(
            f"Portfolio cap violated after beam selection: max_slips_per_player={max_slips_per_player}. "
            f"Offenders (top): {top}"
        )
    
    if debug_builder:
        max_exposure = max(counts.values()) if counts else 0
        top5 = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:5]
        top5_str = ", ".join([f"{p}:{n}" for p, n in top5]) if top5 else "(none)"
        print(
            "[BUILDER][DEBUG] beam summary | "
            f"selected_vs_requested={len(out)}/{int(top_n)} | "
            f"beam_window_size={beam_window_size} | "
            f"max_exposure={max_exposure} | "
            f"top5_exposure={top5_str} | "
            f"rej_exposure_cap={rej_exposure_cap} | "
            f"rej_missing_players={rej_missing_players} | "
            f"rej_composition={rej_composition}"
        )
    if debug_builder:
        try:
            import sys
            reconf = getattr(sys.stdout, "reconfigure", None)
            if callable(reconf):
                reconf(encoding="utf-8", errors="replace")
        except Exception:
            pass
    
    return out


def build_windfall_slips(
    legs_df: pd.DataFrame,
    n_legs: int,
    top_n: int,
    seed: int,
    *,
    pricing_engine: str,
    sort_mode: str = "ev",
    cfg: dict[str, Any],
    max_attempts: int = 400000,
) -> pd.DataFrame:
    single_game_active = False
    if "single_game_slate" in legs_df.columns:
        try:
            single_game_active = bool(pd.Series(legs_df["single_game_slate"]).map(bool).any())
        except Exception:
            single_game_active = False
    if single_game_active:
        mixes = {
            2: {"GOBLIN": 2},
            3: {"GOBLIN": 2, "STANDARD": 1},
            4: {"GOBLIN": 3, "STANDARD": 1},
        }
        mix_ok_fn = _single_game_windfall_mix_ok
    else:
        mixes = {
            2: {"GOBLIN": 1, "DEMON": 1},
            3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1},
            4: {"GOBLIN": 1, "STANDARD": 2, "DEMON": 1},
            5: {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1},
        }
        mix_ok_fn = _windfall_mix_ok
    flex_by_legs = {2: FLEX_2, 3: FLEX_3, 4: FLEX_4, 5: FLEX_5}
    return build_slips_by_tier_buckets(
        legs_df=legs_df,
        n_legs=n_legs,
        top_n=top_n,
        payout_power_mult=POWER_MULT[n_legs],
        payout_flex=flex_by_legs[n_legs],
        pricing_engine=pricing_engine,
        cfg=cfg,
        seed=seed,
        per_tier=400,
        max_attempts=max_attempts,
        sort_mode=sort_mode,
        mixes=mixes,
        required_tiers=list(mixes[n_legs].keys()),
        mix_ok_fn=mix_ok_fn,
    )


def build_system_slips(
    legs_df: pd.DataFrame,
    n_legs: int,
    top_n: int,
    seed: int,
    *,
    sort_mode: str = "ev",
    pricing_engine: str,
    cfg: dict[str, Any],
    max_attempts: int = 500000,
) -> pd.DataFrame:
    mixes = {
        2: {"GOBLIN": 1, "STANDARD": 1},
        3: {"GOBLIN": 1, "STANDARD": 2},
        4: {"GOBLIN": 2, "STANDARD": 2},
        5: {"GOBLIN": 3, "STANDARD": 2},
    }
    df = legs_df.copy()

    if "tier" in df.columns:
        df["tier"] = _series_to_str(df["tier"], index=df.index, default="STANDARD").map(
            lambda x: str(x).upper().strip() if x else "STANDARD"
        )
    else:
        df["tier"] = pd.Series(["STANDARD"] * len(df), index=df.index, dtype=object)

    df = df[df["tier"].isin(["GOBLIN", "STANDARD"])].reset_index(drop=True)

    flex_by_legs = {2: FLEX_2, 3: FLEX_3, 4: FLEX_4, 5: FLEX_5}
    out = build_slips_by_tier_buckets(
        legs_df=df,
        n_legs=n_legs,
        top_n=top_n,
        payout_power_mult=POWER_MULT[n_legs],
        payout_flex=flex_by_legs[n_legs],
        pricing_engine=pricing_engine,
        cfg=cfg,
        seed=seed,
        per_tier=650,
        max_attempts=max_attempts,
        sort_mode=sort_mode,
        mixes=mixes,
        required_tiers=list(mixes[n_legs].keys()),
        mix_ok_fn=_system_mix_ok,
    )
    out["beam_selected"] = 1
    return out


# -------------------------------------------------------------------
# DemonHunter – all-DEMON slips (best single 3/4/5-leg)
# -------------------------------------------------------------------

def _demon_mix_ok(n_legs: int, legs: Any) -> bool:
    """Every leg must be DEMON."""
    c = _tier_counts_from_legs(legs)
    return c["DEMON"] == n_legs and c["GOBLIN"] == 0 and c["STANDARD"] == 0


def build_demonhunter_slips(
    legs_df: pd.DataFrame,
    seed: int,
    *,
    pricing_engine: str,
    sort_mode: str = "hit",
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Return a single CSV-ready DataFrame with the best all-DEMON slips.
    all-DEMON slips (3 rows total).  Sorted by hit_prob so the best chance to
    actually cash is ranked first within each leg count.
    """
    demon_cfg = (cfg.get("demonhunter") or {}) if isinstance(cfg, dict) else {}
    demon_by_legs = demon_cfg.get("by_legs") or {}
    demon_default_per_tier = int(demon_cfg.get("per_tier", 400))

    single_game_active = False
    if "single_game_slate" in legs_df.columns:
        try:
            single_game_active = bool(pd.Series(legs_df["single_game_slate"]).map(bool).any())
        except Exception:
            single_game_active = False
    # Single-game slates should expose a smaller DemonHunter menu. The 4-leg
    # all-DEMON variant is too fragile for one-game boards and was not useful
    # in the dry-run audit; keep 2/3 available for upside shots.
    leg_counts = (2, 3) if single_game_active else (3, 4, 5)
    flex_by_legs = {2: FLEX_2, 3: FLEX_3, 4: FLEX_4, 5: FLEX_5}

    frames: list[pd.DataFrame] = []
    for n_legs in leg_counts:
        # Merge demonhunter per-leg overrides into slip_build
        leg_override_raw = demon_by_legs.get(str(n_legs)) or demon_by_legs.get(n_legs) or {}
        leg_override = dict(leg_override_raw)  # copy to avoid mutating config
        leg_per_tier = int(leg_override.pop("per_tier", demon_default_per_tier))
        leg_max_attempts = int(leg_override.pop("max_attempts", demon_cfg.get("max_attempts", 200000)) or 200000)
        if leg_override:
            merged_cfg = dict(cfg)
            sb = dict(merged_cfg.get("slip_build") or {})
            for k, v in leg_override.items():
                if isinstance(v, dict) and isinstance(sb.get(k), dict):
                    nested = dict(sb[k])
                    nested.update(v)
                    sb[k] = nested
                else:
                    sb[k] = v
            merged_cfg["slip_build"] = sb
        else:
            merged_cfg = cfg

        mixes = {n_legs: {"DEMON": n_legs}}
        df = build_slips_by_tier_buckets(
            legs_df=legs_df,
            n_legs=n_legs,
            top_n=1,
            payout_power_mult=POWER_MULT[n_legs],
            payout_flex=flex_by_legs[n_legs],
            pricing_engine=pricing_engine,
            cfg=merged_cfg,
            seed=seed,
            per_tier=leg_per_tier,
            max_attempts=leg_max_attempts,
            sort_mode=sort_mode,
            mixes=mixes,
            required_tiers=["DEMON"],
            mix_ok_fn=_demon_mix_ok,
        )
        if df is not None and len(df) > 0:
            df = expand_legs(df, n_legs)
            frames.append(df.head(1))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

from __future__ import annotations

"""
Slip builders (SYSTEM/WINDFALL) extracted from LegacyEngine.main during Phase 7B.

Non-negotiables:
- Preserve behavior 1:1 (deterministic, seed-driven).
- Preserve tier/direction/line identity (no collapsing).
- Preserve POWER payout logic + optional PP kernel adjustment.
"""

import ast
import os
import random
from typing import Any

import numpy as np
import pandas as pd

from .payout_tables import FLEX_3, FLEX_4, FLEX_5, POWER_MULT
from .slip_scoring import _score_slip


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


def _pick_best_prob_column(df: pd.DataFrame) -> str:
    """
    Probability preference order (best -> fallback).

    1) p_cal_role   (calibrated role-adjusted)
    2) p_cal        (calibrated base-adjusted)
    3) p_adj_role   (raw role-adjusted)
    4) p_adj        (raw base-adjusted; legacy)
    5) p            (raw)
    """
    for c in ("p_cal_role", "p_cal", "p_adj_role", "p_adj", "p"):
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
    if n_legs == 3:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 1 and c["DEMON"] == 1
    if n_legs == 4:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 2 and c["DEMON"] == 1
    if n_legs == 5:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 2 and c["DEMON"] == 1
    return True


def _system_mix_ok(n_legs: int, legs: Any) -> bool:
    c = _tier_counts_from_legs(legs)
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

    df = legs_df.copy().reset_index(drop=True)

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

        df["projection_id"] = _series_to_str(pid_series, index=df.index, default="").map(lambda x: x.strip())

    if "tier" in df.columns:
        df["tier"] = _series_to_str(df["tier"], index=df.index, default="STANDARD").map(
            lambda x: str(x).upper().strip() if x else "STANDARD"
        )
    else:
        df["tier"] = pd.Series(["STANDARD"] * len(df), index=df.index, dtype=object)

    # ---- p_eff selection ----
    best_prob_col = _pick_best_prob_column(df)

    if "p_eff" not in df.columns:
        if best_prob_col:
            s = _to_float_series(df, best_prob_col, default=np.nan)
            s = _nan_to_value(s, 0.50)
            df["p_eff"] = _clip01(s)
        else:
            df["p_eff"] = pd.Series(np.full(len(df), 0.50, dtype="float64"), index=df.index)
    else:
        base = _to_float_series(df, "p_eff", default=np.nan)

        if best_prob_col:
            fb = _to_float_series(df, best_prob_col, default=0.50)
        else:
            fb = _to_float_series(df, "p_adj", default=0.50)

        base_arr = base.to_numpy(copy=True)   # writable
        fb_arr = fb.to_numpy(copy=False)
        mask = np.isnan(base_arr)
        base_arr[mask] = fb_arr[mask]
        df["p_eff"] = _clip01(pd.Series(base_arr, index=df.index))

    # edge_score fallback = p_eff - 0.5 (keep exact math)
    if "edge_score" in df.columns:
        es = pd.to_numeric(df["edge_score"], errors="coerce")
        if not isinstance(es, pd.Series):
            es = pd.Series(es, index=df.index)

        # FIX: copy=True because we mutate es_arr in-place
        es_arr = np.asarray(es.to_numpy(copy=True), dtype="float64")  # writable
        pe_arr = np.asarray(df["p_eff"].to_numpy(copy=False), dtype="float64")
        mask = np.isnan(es_arr)
        es_arr[mask] = pe_arr[mask] - 0.5
        df["edge_score"] = pd.Series(es_arr, index=df.index)
    else:
        pe_arr = np.asarray(df["p_eff"].to_numpy(copy=False), dtype="float64")
        df["edge_score"] = pd.Series(pe_arr - 0.5, index=df.index)

    tier_counts = df["tier"].value_counts(dropna=False).to_dict()

    if (os.getenv("ATLAS_DEBUG_BUILDER") or "").strip() == "1":
        print(f"[BUILDER][DEBUG] leg_df tier counts: {tier_counts}")
        print(f"[BUILDER][DEBUG] p_eff source: {best_prob_col if best_prob_col else 'NONE'}")

    for needed in required_tiers:
        if tier_counts.get(needed, 0) == 0:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    df = df.sort_values(["tier", "edge_score", "p_eff"], ascending=[True, False, False]).reset_index(drop=True)

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

    def _run_phase(phase_buckets: dict[str, list[pd.Series]], phase_target: int) -> None:
        nonlocal attempts, slips, seen

        # penalty knobs (Step 3)
        sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
        pen_cfg = sb.get("penalty", {}) if isinstance(sb, dict) else {}
        team_w = float(pen_cfg.get("team_w", 0.0) or 0.0)
        family_w = float(pen_cfg.get("family_w", 0.0) or 0.0)

        def _team_key(r: pd.Series) -> str:
            for k in ("team", "team_abbrev", "player_team"):
                if k in r.index:
                    v = str(r[k]).strip()
                    if v and v.lower() != "nan":
                        return v
            return ""

        def _family_key(r: pd.Series) -> str:
            # usage/variance buckets (Decision B=3)
            s = ""
            for k in ("stat", "stat_type", "market"):
                if k in r.index:
                    s = str(r[k]).strip()
                    if s and s.lower() != "nan":
                        break
            u = s.upper()

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

            scored = _score_slip(
                chosen,
                n_legs,
                payout_power_mult,
                pricing_engine=str(pricing_engine or "atlas"),
                cfg=cfg,
            )

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
                        pen_team += team_w * float(over * over)

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
                        pen_family += family_w * float(over * over)

            frag_w = float(pen_cfg.get("frag_w", 0.0))

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
                    pen_frag = frag_w * (sum(frags) / float(len(frags)))

            pen_total = pen_team + pen_family + pen_frag

            # Compute base score for this candidate (depends on sort_mode)
            hit_prob = float(scored.get("hit_prob", 0.0) or 0.0)
            payout_mult = float(scored.get("payout_mult_eff", scored.get("payout_mult", 0.0)) or 0.0)

            if str(sort_mode or "").lower() == "winprob":
                base_score = hit_prob
            else:
                # EV board: rank_ev = hit_prob * payout_mult^k (k from slip_rank.ev_payout_power)
                k = float(((cfg or {}).get("slip_rank", {}) or {}).get("ev_payout_power", 1) or 1)
                base_score = hit_prob * (payout_mult ** k)

            scored["pen_team"] = pen_team
            scored["pen_family"] = pen_family
            scored["pen_frag"] = pen_frag
            scored["pen_total"] = pen_total
            scored["score_adj"] = float(base_score - pen_total)
            scored["players"] = [p for p in players if p]

            # keep existing slip fields, just add penalties + adjusted score
            seen.add(key)
            slips.append(scored)

    # Phase 1: exploit (top slice)
    _run_phase(buckets_p1, target_p1)

    # Phase 2: explore (full bucket) until full target_pool reached
    _run_phase(buckets_p2, target_pool)

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
        # WinProb = pure probability ordering (no payout/penalty noise)
        keys = ["hit_prob"]
        if "avg_p" in out.columns:
            keys.append("avg_p")
        out = out.sort_values(keys, ascending=[False] * len(keys)).reset_index(drop=True)

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

    # -----------------------------
    # Step 4: Beam selection (C3) with portfolio exposure caps
    # -----------------------------
    sb = cfg.get("slip_build", {}) if isinstance(cfg, dict) else {}
    beam_width = int(sb.get("beam_width", 100))
    max_slips_per_player = int(sb.get("max_slips_per_player", 5))
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
    if mode in ("hit", "hit_prob", "win", "winprob"):
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

    # Limit the candidate window for beam expansion to keep runtime sane
    # (If you want, we can expose this as a config knob later.)
    cand_order = list(np.argsort(-score_arr))  # indices sorted by score desc
    window_mult = 200          # starting window size factor
    window_max_mult = 800      # how far we're willing to widen before failing
    window_bumps = 0
    cand_cap = max(int(top_n) * window_mult, 2000)
    cand_order = cand_order[:cand_cap]
    beam_window_size = len(cand_order)

    # Beam state: (total_score, selected_indices, exposure_counts_dict)
    beam: list[tuple[float, list[int], dict[str, int]]] = [(0.0, [], {})]

    def _can_add(counts: dict[str, int], players: list[str]) -> bool:
        for p in players:
            if counts.get(p, 0) + 1 > max_slips_per_player:
                return False
        return True

    def _add_counts(counts: dict[str, int], players: list[str]) -> dict[str, int]:
        nc = dict(counts)
        for p in players:
            nc[p] = nc.get(p, 0) + 1
        return nc

    # Beam select top_n slips
    for _step in range(int(top_n)):
        next_beam: list[tuple[float, list[int], dict[str, int]]] = []

        for total, sel, counts in beam:
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

                new_total = total + float(score_arr[idx])
                new_sel = sel + [idx]
                new_counts = _add_counts(counts, keys)
                next_beam.append((new_total, new_sel, new_counts))

        if not next_beam:
            # Beam stalled. Try widening candidate window (NO cap relaxation).
            if window_mult < window_max_mult:
                window_mult = min(window_max_mult, window_mult * 2)
                window_bumps += 1

                cand_cap = max(int(top_n) * window_mult, 2000)
                cand_order = list(np.argsort(-score_arr))
                cand_order = cand_order[:cand_cap]
                beam_window_size = len(cand_order)

                if debug_builder:
                    print(f"[BUILDER][DEBUG] beam stalled -> widen window | window_mult={window_mult} cap={cand_cap} window_size={beam_window_size}")

                # retry this beam depth with the widened window
                continue

            # No more widening allowed: stop expanding
            break

        # Keep best beam_width partial portfolios
        next_beam.sort(key=lambda x: x[0], reverse=True)
        beam = next_beam[:beam_width]

    # Choose best completed portfolio (prefer exact size = top_n)
    best = None
    for total, sel, counts in beam:
        if len(sel) == int(top_n):
            best = (total, sel)
            break
    if best is None:
        # fallback: take the longest portfolio we could build
        beam.sort(key=lambda x: (len(x[1]), x[0]), reverse=True)
        best = (beam[0][0], beam[0][1])

    selected_idx = best[1]
    out = out.iloc[selected_idx].reset_index(drop=True)

    out["beam_selected"] = 1

    if mode in ("hit", "hit_prob", "win", "winprob"):
        keys = ["hit_prob"]
        if "avg_p" in out.columns:
            keys.append("avg_p")
        out = out.sort_values(keys, ascending=[False] * len(keys)).reset_index(drop=True)

    if len(out) < int(top_n):
        raise RuntimeError(
            "Beam could not assemble requested portfolio size without relaxing constraints: "
            f"selected={len(out)} requested={int(top_n)} "
            f"beam_window_size={beam_window_size} "
            f"rej_exposure_cap={rej_exposure_cap} rej_missing_players={rej_missing_players} "
            f"window_mult={window_mult} window_bumps={window_bumps}"
        )

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
            f"rej_missing_players={rej_missing_players}"
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
) -> pd.DataFrame:
    mixes = {
        3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1},
        4: {"GOBLIN": 1, "STANDARD": 2, "DEMON": 1},
        5: {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1},
    }
    return build_slips_by_tier_buckets(
        legs_df=legs_df,
        n_legs=n_legs,
        top_n=top_n,
        payout_power_mult=POWER_MULT[n_legs],
        payout_flex={3: FLEX_3, 4: FLEX_4, 5: FLEX_5}[n_legs],
        pricing_engine=pricing_engine,
        cfg=cfg,
        seed=seed,
        per_tier=400,
        max_attempts=400000,
        sort_mode=sort_mode,
        mixes=mixes,
        required_tiers=["GOBLIN", "STANDARD", "DEMON"],
        mix_ok_fn=_windfall_mix_ok,
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
) -> pd.DataFrame:
    mixes = {
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

    out = build_slips_by_tier_buckets(
        legs_df=df,
        n_legs=n_legs,
        top_n=top_n,
        payout_power_mult=POWER_MULT[n_legs],
        payout_flex={3: FLEX_3, 4: FLEX_4, 5: FLEX_5}[n_legs],
        pricing_engine=pricing_engine,
        cfg=cfg,
        seed=seed,
        per_tier=650,
        max_attempts=500000,
        sort_mode=sort_mode,
        mixes=mixes,
        required_tiers=["GOBLIN", "STANDARD"],
        mix_ok_fn=_system_mix_ok,
    )
    out["beam_selected"] = 1
    return out
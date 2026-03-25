from __future__ import annotations

"""
External priors (projection-first, CSV only)

Goal
- Never drop external information just because PrizePicks does not currently offer the exact line.
- Treat external sources as providing a projection (mu) for (player, stat).
- Translate that projection onto *each* PrizePicks offering in the scored legs dataframe:
    edge_at_pp_line = mu - line
    implied_direction = OVER if edge>0 else UNDER
  Apply only when the leg's direction matches implied_direction (direction gating).

Inputs
- CSV: data/input/external_priors_today.csv
  Required columns:
    source, asof_ts, league, player, stat, projection
  Optional:
    confidence (0-1), notes


Config (config.yaml) under optimizer.external_priors:
  enabled: true
  path: "data/input/external_priors_today.csv"   # optional; csv only
  cap: 0.03          # max abs probability nudge applied to p_adj per leg
  scale: 3.0         # points scale for tanh(edge/scale) mapping (larger = gentler)
  p_floor: 0.01
  p_ceil: 0.99
  sources:           # optional source weights (used for blending projections)
    rotowire: {weight: 1.0}
    bettingpros: {weight: 1.0}

Outputs
- Always adds/overwrites these columns:
    external_prior_score      float in [-1,1] (signed strength after tanh mapping)
    external_prior_n          int   number of contributing sources (for this leg, after gating)
    external_prior_sources    str   comma-separated unique sources used
    external_prior_epsilon    float legacy field (kept for compatibility; equals cap)

- If df has 'p_adj', we apply the bounded nudge directly to p_adj.
  (If p_adj is missing but 'p' exists, we nudge 'p'. Otherwise we only emit audit columns.)

Debug
- Writes: data/output/external_priors_resolved_<timestamp>.csv
  (best-effort; never fails the run)

Behavior
- CSV is the only accepted input mode.
- If the CSV is missing, unreadable, empty, or configured with a non-CSV path, we emit audit columns only and apply no prior nudge.
"""

import os
from pathlib import Path
from Atlas.runtime.paths import find_repo_root
from typing import Any, Dict, Optional

import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = find_repo_root(Path(__file__))
DEFAULT_PRIORS_CSV = PROJECT_ROOT / "data" / "input" / "external_priors_today.csv"


def _resolve_external_priors_source_path(pri_cfg: dict[str, Any]) -> Path:
    env_path = (os.environ.get("ATLAS_EXTERNAL_PRIORS_CSV_PATH") or "").strip()
    if env_path:
        try:
            return Path(env_path).expanduser().resolve()
        except Exception:
            pass

    path = pri_cfg.get("path", None)
    if isinstance(path, str) and path.strip():
        try:
            return Path(path).expanduser().resolve()
        except Exception:
            pass

    return DEFAULT_PRIORS_CSV


def _norm_path_str(p: Path) -> str:
    return str(p).replace("\\", "/").lower()


def _looks_like_backtest_output_dir(p: Path) -> bool:
    s = _norm_path_str(p)
    return (
        "/data/output/backtests/" in s
        or s.endswith("/data/output/backtests")
        or s.endswith("/outputtelem")
        or "/outputtelem/" in s
    )


def _resolve_external_priors_debug_out_dir() -> Path:
    """
    Routing policy:
    1) Explicit override wins:
         ATLAS_EXTERNAL_PRIORS_DEBUG_OUT_DIR
    2) If ATLAS_OUT_DIR points at a backtest/replay folder, use it
       (supports both data/output/backtests/... and C:/.../Atlas/outputtelem)
    3) Otherwise use the live default:
         data/output/externalpriors
    """
    live_default = (PROJECT_ROOT / "data" / "output" / "externalpriors").resolve()

    explicit = (os.environ.get("ATLAS_EXTERNAL_PRIORS_DEBUG_OUT_DIR") or "").strip()
    if explicit:
        try:
            return Path(explicit).expanduser().resolve()
        except Exception:
            return live_default

    atlas_out_dir = (os.environ.get("ATLAS_OUT_DIR") or "").strip()
    if atlas_out_dir:
        try:
            candidate = Path(atlas_out_dir).expanduser().resolve()
            if _looks_like_backtest_output_dir(candidate):
                return candidate
        except Exception:
            pass

    return live_default


OUT_DIR = _resolve_external_priors_debug_out_dir()

try:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

_DISABLE_DBG = (os.environ.get("ATLAS_DISABLE_EXTERNAL_PRIORS_DEBUG_WRITE") or "").strip().lower() in ("1", "true", "yes")
_DBG_WROTE = False

def _get_external_priors_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    opt = cfg.get("optimizer", {}) if isinstance(cfg, dict) else {}
    pri = opt.get("external_priors", {}) if isinstance(opt, dict) else {}
    return pri if isinstance(pri, dict) else {}


def _safe_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _load_csv_priors(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    # Ensure expected columns exist
    for col in ["source", "player", "stat", "league", "asof_ts", "notes"]:
        if col not in df.columns:
            df[col] = ""
    if "projection" not in df.columns:
        df["projection"] = np.nan
    if "confidence" not in df.columns:
        df["confidence"] = 1.0

    out = pd.DataFrame(
        {
            "source": df["source"].astype(str).str.strip().str.lower(),
            "asof_ts": df["asof_ts"].astype(str).str.strip(),
            "league": df["league"].astype(str).str.strip().str.upper(),
            "player": df["player"].astype(str).str.strip(),
            "stat": df["stat"].astype(str).str.strip().str.upper(),
            "projection": pd.to_numeric(df["projection"], errors="coerce"),
            "confidence": pd.to_numeric(df["confidence"], errors="coerce").fillna(1.0).clip(0.0, 1.0),
            "notes": df["notes"].astype(str),
        }
    )

    out = out.dropna(subset=["player", "stat", "projection"])
    out = out[(out["player"] != "") & (out["stat"] != "")]
    return out


def _source_weight_map(pri_cfg: dict[str, Any]) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    srcs = pri_cfg.get("sources", None)
    if isinstance(srcs, dict):
        for k, v in srcs.items():
            if not k:
                continue
            w = None
            if isinstance(v, dict):
                w = v.get("weight", None)
            w = _safe_float(w, None)
            if w is None:
                w = 1.0
            weights[str(k).strip().lower()] = float(w)
    return weights


def apply_external_priors(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    *,
    apply_probability: bool = True,
) -> pd.DataFrame:
    global _DBG_WROTE
    out = df.copy()

    pri_cfg = _get_external_priors_cfg(cfg)
    enabled = bool(pri_cfg.get("enabled", True))

    cap = float(pri_cfg.get("cap", 0.03))
    scale = float(pri_cfg.get("scale", 3.0))
    p_floor = float(pri_cfg.get("p_floor", 0.01))
    p_ceil = float(pri_cfg.get("p_ceil", 0.99))

    # Always present for stability
    out["external_prior_score"] = 0.0
    out["external_prior_n"] = 0
    out["external_prior_sources"] = ""
    out["external_prior_epsilon"] = cap  # legacy field; equals cap

    if (not enabled) or (len(out) == 0):
        return out

    # Choose path (CSV only; env override -> config path -> default)
    pri_path = _resolve_external_priors_source_path(pri_cfg)

    if pri_path.suffix.lower() != ".csv":
        return out

    pri_df: Optional[pd.DataFrame] = None
    mode: str = "none"

    if pri_path.exists():
        try:
            pri_df = _load_csv_priors(pri_path)
            mode = "csv_projection"
        except Exception:
            pri_df = None

    if pri_df is None or len(pri_df) == 0:
        return out

    # Need these to do anything meaningful
    required_cols = {"player", "stat", "line", "direction"}
    if not required_cols.issubset(set(out.columns)):
        return out

    # Normalized internal keys
    out["_ep_player"] = out["player"].astype(str).str.strip()
    out["_ep_stat"] = out["stat"].astype(str).str.strip().str.upper()
    out["_ep_line"] = pd.to_numeric(out["line"], errors="coerce")
    out["_ep_dir"] = out["direction"].astype(str).str.strip().str.upper()
    out["_ep_tier"] = out["tier"].astype(str).str.strip().str.upper() if "tier" in out.columns else "STANDARD"

    resolved_rows = pd.DataFrame()

    if mode == "csv_projection":
        # Blend multiple sources into a single mu per (player, stat)
        weights = _source_weight_map(pri_cfg)
        pri = pri_df.copy()
        pri["_w"] = pri["source"].map(lambda s: weights.get(str(s).lower(), 1.0)).astype(float)
        pri["_w_eff"] = pri["_w"] * pri["confidence"].astype(float)

        # Weighted mean per (player, stat)
        grouped = pri.groupby(["player", "stat"], dropna=False)
        num = (grouped.apply(lambda x: float((x["projection"] * x["_w_eff"]).sum()))).rename("num")
        den = (grouped.apply(lambda x: float(x["_w_eff"].sum()))).rename("den")
        blended = pd.concat([num, den], axis=1).reset_index()
        blended["mu"] = blended["num"] / blended["den"].clip(lower=1e-9)

        # sources/n_sources/max_conf
        agg = grouped.agg(
            sources=("source", lambda s: ",".join(sorted(set(map(str, s.tolist()))))),
            n_sources=("_w_eff", lambda w: int((pd.to_numeric(w, errors="coerce").fillna(0) > 0).sum())),
            max_conf=("confidence", "max"),
        ).reset_index()
        blended = blended.merge(agg, on=["player", "stat"], how="left")
        blended = blended[["player", "stat", "mu", "sources", "n_sources", "max_conf"]]

        merged = out.merge(
            blended,
            left_on=["_ep_player", "_ep_stat"],
            right_on=["player", "stat"],
            how="left",
            suffixes=("", "_pri"),
        )

        merged["edge_at_pp_line"] = merged["mu"] - merged["_ep_line"]

        # implied direction only when edge is known
        merged["implied_direction"] = np.where(
            merged["edge_at_pp_line"].notna() & (merged["edge_at_pp_line"] > 0),
            "OVER",
            np.where(merged["edge_at_pp_line"].notna(), "UNDER", ""),
        )

        merged["apply_prior"] = (
            (merged["_ep_dir"] == merged["implied_direction"])
            & merged["mu"].notna()
            & merged["_ep_line"].notna()
        )

        safe_scale = scale if scale > 1e-9 else 1.0

        # NA-safe tanh (vectorized). np.tanh(np.nan) -> nan, then we fill to 0 later.
        x = merged["edge_at_pp_line"] / safe_scale
        merged["external_prior_score"] = np.tanh(x).astype(float)  # nan ok

        merged["external_prior_score"] = (
            pd.to_numeric(merged["external_prior_score"], errors="coerce")
            .fillna(0.0)
            .clip(-1.0, 1.0)
        )

        # Gate: if not apply, zero it out
        merged.loc[~merged["apply_prior"], "external_prior_score"] = 0.0

        merged["external_prior_n"] = (
            merged["apply_prior"].astype(int) * merged["n_sources"].fillna(0).astype(int)
        )
        merged["external_prior_sources"] = merged["sources"].fillna("").astype(str)

        # Apply bounded nudge only when the caller wants the prior to affect the
        # probability surface. The scored surface can still carry audit columns
        # without being directly rewritten.
        target_col: Optional[str] = "p_adj" if "p_adj" in merged.columns else ("p" if "p" in merged.columns else None)
        if target_col is not None and apply_probability:
            merged["delta_p"] = (cap * merged["external_prior_score"]).clip(-abs(cap), abs(cap))
            merged[target_col] = (
                pd.to_numeric(merged[target_col], errors="coerce") + merged["delta_p"]
            ).clip(p_floor, p_ceil)
        else:
            merged["delta_p"] = 0.0

        # Debug rows
        dbg_cols = [
            "_ep_player",
            "_ep_stat",
            "_ep_tier",
            "_ep_dir",
            "_ep_line",
            "mu",
            "edge_at_pp_line",
            "implied_direction",
            "apply_prior",
            "external_prior_score",
            "external_prior_n",
            "external_prior_sources",
            "delta_p",
        ]
        resolved_rows = merged[dbg_cols].copy()

        # Write debug CSV (best-effort; never fails the run; only once per process)
        if not _DISABLE_DBG and not _DBG_WROTE:
            try:
                import datetime
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                debug_path = OUT_DIR / f"external_priors_resolved_{ts}.csv"
                resolved_rows.to_csv(debug_path, index=False)
                _DBG_WROTE = True
            except Exception:
                pass

        # Push back into out (same row order)
        out["external_prior_score"] = merged["external_prior_score"].values
        out["external_prior_n"] = merged["external_prior_n"].values
        out["external_prior_sources"] = merged["external_prior_sources"].values

        if "p_adj" in out.columns and "p_adj" in merged.columns:
            out["p_adj"] = merged["p_adj"].values
        elif "p" in out.columns and "p" in merged.columns:
            out["p"] = merged["p"].values

    # Clean up temp columns
    out = out.drop(columns=[c for c in out.columns if c.startswith("_ep_")], errors="ignore")

    return out
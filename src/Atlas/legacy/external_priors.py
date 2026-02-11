from __future__ import annotations

"""
External priors (projection-first)

Goal
- Never drop external information just because PrizePicks does not currently offer the exact line.
- Treat external sources as providing a projection (mu) for (player, stat).
- Translate that projection onto *each* PrizePicks offering in the scored legs dataframe:
    edge_at_pp_line = mu - line
    implied_direction = OVER if edge>0 else UNDER
  Apply only when the leg's direction matches implied_direction (direction gating).

Inputs
- CSV (preferred): data/input/external_priors_today.csv
  Required columns:
    source, asof_ts, league, player, stat, projection
  Optional:
    confidence (0-1), notes

- YAML (legacy / fallback): data/input/external_priors_today.yaml
  (the previous pick-list format). If configured path ends with .yaml/.yml and exists, we use it.

Config (config.yaml) under optimizer.external_priors:
  enabled: true
  path: "data/input/external_priors_today.csv"   # optional; csv preferred
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
"""

from pathlib import Path
from Atlas.runtime.paths import find_repo_root
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = find_repo_root(Path(__file__))
DEFAULT_PRIORS_CSV = PROJECT_ROOT / "data" / "input" / "external_priors_today.csv"
DEFAULT_PRIORS_YAML = PROJECT_ROOT / "data" / "input" / "external_priors_today.yaml"
OUT_DIR = PROJECT_ROOT / "data" / "output"


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


def _load_yaml_picklist(path: Path) -> pd.DataFrame:
    """Legacy support: old YAML pick list.

    Old YAML doesn't provide projections, so we keep it as a line-specific vote score only,
    and we DO NOT nudge p_adj in YAML mode.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
    except Exception:
        return pd.DataFrame()

    picks = y.get("picks", []) if isinstance(y, dict) else []
    if not isinstance(picks, list) or not picks:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for p in picks:
        if not isinstance(p, dict):
            continue
        player = str(p.get("player", "")).strip()
        stat = str(p.get("stat", "")).strip().upper()
        direction = str(p.get("direction", "")).strip().upper()
        source = str(p.get("source", "")).strip().lower()
        if not player or not stat or direction not in {"OVER", "UNDER"}:
            continue
        rows.append(
            {
                "source": source or "legacy_yaml",
                "player": player,
                "stat": stat,
                "direction": direction,
                "line": _safe_float(p.get("line", None), None),
                "tier": str(p.get("tier", "")).strip().upper(),
                "weight": _safe_float(p.get("weight", None), 1.0) or 1.0,
            }
        )
    return pd.DataFrame(rows)


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


def apply_external_priors(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
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
    out["external_prior_epsilon"] = cap  # legacy field; now equals cap

    if (not enabled) or (len(out) == 0):
        return out

    # Choose path (prefer CSV unless explicitly pointed to YAML)
    path = pri_cfg.get("path", None)
    pri_path = Path(path) if isinstance(path, str) and path.strip() else None

    cand_csv = pri_path if pri_path and pri_path.suffix.lower() == ".csv" else DEFAULT_PRIORS_CSV
    cand_yaml = pri_path if pri_path and pri_path.suffix.lower() in {".yaml", ".yml"} else DEFAULT_PRIORS_YAML

    pri_df: Optional[pd.DataFrame] = None
    mode: str = "none"

    if cand_csv.exists():
        try:
            pri_df = _load_csv_priors(cand_csv)
            mode = "csv_projection"
        except Exception:
            pri_df = None

    if (pri_df is None or len(pri_df) == 0) and cand_yaml.exists():
        pri_df = _load_yaml_picklist(cand_yaml)
        mode = "yaml_legacy"

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

        # Apply bounded nudge to p_adj (preferred) or p (fallback)
        target_col: Optional[str] = "p" if "p" in merged.columns else None
        if target_col is not None:
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

        # Push back into out (same row order)
        out["external_prior_score"] = merged["external_prior_score"].values
        out["external_prior_n"] = merged["external_prior_n"].values
        out["external_prior_sources"] = merged["external_prior_sources"].values

        if "p_adj" in out.columns and "p_adj" in merged.columns:
            out["p_adj"] = merged["p_adj"].values
        elif "p" in out.columns and "p" in merged.columns:
            out["p"] = merged["p"].values

    else:
        # YAML legacy: keep line-specific voting score; DO NOT touch p_adj
        pri = pri_df.copy()
        if len(pri) == 0:
            out = out.drop(columns=[c for c in out.columns if c.startswith("_ep_")], errors="ignore")
            return out

        pri["_line"] = pd.to_numeric(pri.get("line", pd.Series([np.nan] * len(pri))), errors="coerce")
        pri["_player"] = pri["player"].astype(str).str.strip()
        pri["_stat"] = pri["stat"].astype(str).str.strip().str.upper()
        pri["_dir"] = pri["direction"].astype(str).str.strip().str.upper()
        pri["_tier"] = pri.get("tier", "").astype(str).str.strip().str.upper()
        pri["_w"] = pd.to_numeric(pri.get("weight", 1.0), errors="coerce").fillna(1.0)

        merged = out.merge(
            pri[["_player", "_stat", "_line", "_dir", "_tier", "source", "_w"]],
            left_on=["_ep_player", "_ep_stat", "_ep_line"],
            right_on=["_player", "_stat", "_line"],
            how="left",
        )

        has_prior = merged["_dir"].notna()
        vote = (merged["_dir"] == merged["_ep_dir"]).astype(float) * 2.0 - 1.0
        vote = vote.where(has_prior, 0.0)

        tier_spec = merged["_tier"].fillna("").astype(str).str.strip()
        tier_ok = (tier_spec == "") | (tier_spec == merged["_ep_tier"])
        vote = vote.where(tier_ok, 0.0)

        contrib = merged["_w"].fillna(0.0) * vote
        score = contrib.clip(-1.0, 1.0)

        out["external_prior_score"] = score.fillna(0.0).values
        out["external_prior_n"] = (score != 0).astype(int).values
        out["external_prior_sources"] = merged["source"].fillna("").astype(str).values

        resolved_rows = pd.DataFrame(
            {
                "player": out["_ep_player"],
                "stat": out["_ep_stat"],
                "tier": out["_ep_tier"],
                "direction": out["_ep_dir"],
                "line": out["_ep_line"],
                "apply_prior": (score != 0).astype(int),
                "external_prior_score": out["external_prior_score"],
                "external_prior_sources": out["external_prior_sources"],
            }
        )

    # Write debug file (best-effort, but visible if it fails)
    try:
        if isinstance(resolved_rows, pd.DataFrame) and len(resolved_rows) > 0:
            dbg = resolved_rows.copy()

            # Cosmetic cleanup for readability
            for c in ["external_prior_sources", "implied_direction"]:
                if c in dbg.columns:
                    dbg[c] = dbg[c].fillna("")

            OUT_DIR.mkdir(parents=True, exist_ok=True)
            ts = pd.Timestamp.now(tz="America/Chicago").strftime("%Y%m%d_%H%M%S")
            dbg_path = OUT_DIR / f"external_priors_resolved_{ts}.csv"
            dbg.to_csv(dbg_path, index=False)
    except Exception as e:
        print(f"[WARN] external_priors debug write failed: {e}")

    # Cleanup internal cols
    out = out.drop(columns=[c for c in out.columns if c.startswith("_ep_")], errors="ignore")
    return out
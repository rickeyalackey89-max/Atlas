#!/usr/bin/env python
"""Audit pregame triggers for slate-aware CatBoost residual scale.

The input LODO report must contain at least two scale_results entries:
- aggressive scale, e.g. 0.55
- defensive scale, e.g. 0.10

This audit never uses leg outcomes to build slate metrics. Outcomes enter only
through the already-computed fold deltas used to score each trigger policy.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = (
    ROOT
    / "data/model/candidates/atlas_replay_minute_risk_canonical_12date_cat_off_20260512_090130/"
    / "_v1_playoff_resim_cache_12date_cat_off.pkl"
)
DEFAULT_LODO = (
    ROOT
    / "data/model/candidates/atlas_replay_minute_risk_canonical_12date_cat_off_20260512_090130/"
    / "catboost_playoff_v5cD_iter600_12date_residual_policy_055_regressions010.json"
)


EXCLUDE_SLATES = {"2026-05-01", "2026-05-02", "2026-05-04", "2026-05-06"}
LARGE_GATE_MB = 5.0
SMALL_GATE_MB = 10.0
SMALL_SLATE_N = 1000


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit pregame residual-scale trigger rules.")
    ap.add_argument("--cache-path", default=str(DEFAULT_CACHE), help="Input replay cache pickle.")
    ap.add_argument("--lodo-path", default=str(DEFAULT_LODO), help="Residual sweep LODO JSON.")
    ap.add_argument("--out-dir", default="logs/cat_residual_policy_trigger_audit_20260512", help="Output directory.")
    ap.add_argument("--dates", nargs="*", default=[], help="Optional YYYY-MM-DD dates to audit.")
    args = ap.parse_args()

    cache_path = _resolve(args.cache_path)
    lodo_path = _resolve(args.lodo_path)
    out_dir = _resolve(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = _load_pickle(cache_path)
    lodo = json.loads(lodo_path.read_text(encoding="utf-8"))

    slate = _build_slate_metrics(cache["cv"])
    aggressive, defensive = _scale_maps(lodo)
    slate = slate.merge(aggressive, on="date", how="left").merge(defensive, on="date", how="left")
    if args.dates:
        keep_dates = {str(x) for x in args.dates}
        slate = slate[slate["date"].isin(keep_dates)].copy()
        missing = sorted(keep_dates - set(slate["date"].astype(str)))
        if missing:
            raise SystemExit(f"Requested dates not found in cache/LODO: {missing}")
    slate["defensive_benefit_mB"] = slate["delta_aggressive_mB"] - slate["delta_defensive_mB"]

    rule_results = _evaluate_rules(slate)
    grid_results = _grid_search_rules(slate).head(25)

    slate_path = out_dir / "slate_pregame_metrics.csv"
    rules_path = out_dir / "rule_results.csv"
    grid_path = out_dir / "grid_search_top25.csv"
    summary_path = out_dir / "summary.json"
    slate.to_csv(slate_path, index=False)
    rule_results.to_csv(rules_path, index=False)
    grid_results.to_csv(grid_path, index=False)

    best_named = rule_results.sort_values(["verdict_rank", "agg_delta_mB", "flagged_dates"], ascending=[True, True, True]).head(1)
    best_grid = grid_results.head(1)
    summary = {
        "cache_path": _rel(cache_path),
        "lodo_path": _rel(lodo_path),
        "aggressive_scale": lodo["scale_results"][0]["residual_scale"],
        "defensive_scale": lodo["scale_results"][1]["residual_scale"],
        "dates": slate["date"].astype(str).tolist(),
        "best_named_rule": _records(best_named),
        "best_grid_rule": _records(best_grid),
        "artifacts": {
            "slate_pregame_metrics": _rel(slate_path),
            "rule_results": _rel(rules_path),
            "grid_search_top25": _rel(grid_path),
        },
    }
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")

    _print_report(slate, rule_results, grid_results, summary_path)
    return 0


def _build_slate_metrics(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["date"] = data["game_date"].astype(str).str[:10]
    rows: list[dict[str, Any]] = []
    for date, g in data.groupby("date", sort=True):
        row: dict[str, Any] = {
            "date": date,
            "n": int(len(g)),
            "games": int(g["game_id"].nunique()) if "game_id" in g.columns else None,
            "players": int(g["player"].nunique()) if "player" in g.columns else None,
            "teams": int(g["team"].nunique()) if "team" in g.columns else None,
        }
        row["props_per_game"] = _ratio(row["n"], row["games"])
        stat = g.get("stat", pd.Series("", index=g.index)).astype(str).str.upper()
        tier = g.get("tier", pd.Series("", index=g.index)).astype(str).str.upper()
        direction = g.get("direction", pd.Series("", index=g.index)).astype(str).str.upper()
        row["standard_share"] = float((tier == "STANDARD").mean())
        row["over_share"] = float((direction == "OVER").mean())
        row["fg3m_share"] = float((stat == "FG3M").mean())
        row["combo_share"] = float(stat.isin(["PRA", "PR", "PA", "RA"]).mean())

        for col in [
            "q_blowout",
            "rate_cv",
            "tail_risk",
            "line_tightness",
            "player_stat_te",
            "player_dir_te",
            "role_ctx_outs_used",
            "zero_dnp_mult",
            "is_questionable",
            "q_out_frac",
            "thin_flag",
            "bp_has",
            "bp_score_gated",
            "min_sensitivity",
            "game_total_norm",
            "games_norm",
            "usage_dep_eff",
            "min_mean",
            "line",
        ]:
            if col in g.columns:
                s = pd.to_numeric(g[col], errors="coerce")
                row[f"{col}_mean"] = _mean(s)
                row[f"{col}_p90"] = _quantile(s, 0.90)
                row[f"{col}_share_gt0"] = float((s.fillna(0.0) > 0.0).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _scale_maps(lodo: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    results = lodo.get("scale_results") or []
    if len(results) < 2:
        raise ValueError("LODO JSON must contain at least two scale_results entries.")

    def frame(result: dict[str, Any], suffix: str) -> pd.DataFrame:
        rows = []
        for fold in result.get("folds", []):
            rows.append(
                {
                    "date": fold["date"],
                    f"delta_{suffix}_mB": float(fold["delta_mB"]),
                    f"scale_{suffix}": float(result["residual_scale"]),
                }
            )
        return pd.DataFrame(rows)

    return frame(results[0], "aggressive"), frame(results[1], "defensive")


def _evaluate_rules(slate: pd.DataFrame) -> pd.DataFrame:
    rules: list[tuple[str, str, Callable[[pd.DataFrame], pd.Series]]] = [
        (
            "thin_injury_uncertainty",
            "games <= 2 and q_out_frac_mean >= 0.05 and q_blowout_p90 >= 0.45",
            lambda x: (x["games"] <= 2) & (x["q_out_frac_mean"] >= 0.05) & (x["q_blowout_p90"] >= 0.45),
        ),
        (
            "high_blowout_limited_role_context",
            "q_blowout_p90 >= 0.55 and role_ctx_outs_used_share_gt0 <= 0.30",
            lambda x: (x["q_blowout_p90"] >= 0.55) & (x["role_ctx_outs_used_share_gt0"] <= 0.30),
        ),
        (
            "no_role_low_external_prior",
            "role_ctx_outs_used_share_gt0 <= 0.01 and bp_has_mean <= 0.10",
            lambda x: (x["role_ctx_outs_used_share_gt0"] <= 0.01) & (x["bp_has_mean"] <= 0.10),
        ),
        (
            "composite_v1",
            "thin injury OR high blowout limited role OR no-role low external prior",
            lambda x: (
                ((x["games"] <= 2) & (x["q_out_frac_mean"] >= 0.05) & (x["q_blowout_p90"] >= 0.45))
                | ((x["q_blowout_p90"] >= 0.55) & (x["role_ctx_outs_used_share_gt0"] <= 0.30))
                | ((x["role_ctx_outs_used_share_gt0"] <= 0.01) & (x["bp_has_mean"] <= 0.10))
            ),
        ),
    ]

    rows = []
    for name, desc, fn in rules:
        flags = fn(slate).fillna(False)
        rows.append(_score_policy(slate, flags, name=name, description=desc))
    return pd.DataFrame(rows)


def _grid_search_rules(slate: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for games_max in [2, 3, 4]:
        for q_out_min in [0.01, 0.05, 0.10, 0.15, 0.20]:
            flags = (slate["games"] <= games_max) & (slate["q_out_frac_mean"] >= q_out_min) & (slate["q_blowout_p90"] >= 0.45)
            rows.append(_score_policy(slate, flags, name=f"thin_qout_g{games_max}_q{q_out_min}", description="grid thin injury"))

    for q_p90 in [0.45, 0.50, 0.55, 0.60, 0.65]:
        for role_max in [0.20, 0.25, 0.30, 0.35, 0.40]:
            flags = (slate["q_blowout_p90"] >= q_p90) & (slate["role_ctx_outs_used_share_gt0"] <= role_max)
            rows.append(_score_policy(slate, flags, name=f"blowout_role_q{q_p90}_r{role_max}", description="grid blowout limited role"))

    for role_max in [0.0, 0.01, 0.05, 0.10]:
        for bp_max in [0.05, 0.10, 0.15, 0.20]:
            flags = (slate["role_ctx_outs_used_share_gt0"] <= role_max) & (slate["bp_has_mean"] <= bp_max)
            rows.append(_score_policy(slate, flags, name=f"norole_bp_r{role_max}_b{bp_max}", description="grid no role low prior"))

    # A small composite grid with the three rule families.
    for q_p90 in [0.50, 0.55, 0.60]:
        for role_max in [0.25, 0.30, 0.35]:
            flags = (
                ((slate["games"] <= 2) & (slate["q_out_frac_mean"] >= 0.05) & (slate["q_blowout_p90"] >= 0.45))
                | ((slate["q_blowout_p90"] >= q_p90) & (slate["role_ctx_outs_used_share_gt0"] <= role_max))
                | ((slate["role_ctx_outs_used_share_gt0"] <= 0.01) & (slate["bp_has_mean"] <= 0.10))
            )
            rows.append(_score_policy(slate, flags, name=f"composite_q{q_p90}_r{role_max}", description="grid composite"))

    out = pd.DataFrame(rows)
    return out.sort_values(["verdict_rank", "agg_delta_mB", "clean_worst_slate_mB", "flagged_dates"], ascending=[True, True, True, True])


def _score_policy(slate: pd.DataFrame, flags: pd.Series, *, name: str, description: str) -> dict[str, Any]:
    work = slate.copy()
    work["use_defensive_scale"] = flags.astype(bool).to_numpy()
    work["policy_delta_mB"] = np.where(work["use_defensive_scale"], work["delta_defensive_mB"], work["delta_aggressive_mB"])
    agg = _weighted_delta(work, include_clean=False)
    clean_agg = _weighted_delta(work, include_clean=True)
    worst = float(work["policy_delta_mB"].max())
    clean = work[~work["date"].isin(EXCLUDE_SLATES)].copy()
    clean_worst = float(clean["policy_delta_mB"].max())
    clean_pass = bool(
        (
            clean["policy_delta_mB"]
            <= np.where(clean["n"] >= SMALL_SLATE_N, LARGE_GATE_MB, SMALL_GATE_MB)
        ).all()
    )
    verdict = "PROMOTE" if clean_agg < -0.5 and clean_pass else "REJECT"
    flagged = work[work["use_defensive_scale"]]
    return {
        "rule": name,
        "description": description,
        "verdict": verdict,
        "verdict_rank": 0 if verdict == "PROMOTE" else 1,
        "agg_delta_mB": agg,
        "clean_agg_delta_mB": clean_agg,
        "worst_slate_mB": worst,
        "clean_worst_slate_mB": clean_worst,
        "flagged_dates": int(len(flagged)),
        "flagged_date_list": ",".join(flagged["date"].astype(str).tolist()),
        "flagged_delta55_sum_mB": float(flagged["delta_aggressive_mB"].sum()) if not flagged.empty else 0.0,
        "flagged_delta10_sum_mB": float(flagged["delta_defensive_mB"].sum()) if not flagged.empty else 0.0,
    }


def _weighted_delta(work: pd.DataFrame, *, include_clean: bool) -> float:
    df = work[~work["date"].isin(EXCLUDE_SLATES)].copy() if include_clean else work
    weights = pd.to_numeric(df["n"], errors="coerce").fillna(0.0)
    if weights.sum() <= 0:
        return math.nan
    return float(np.average(pd.to_numeric(df["policy_delta_mB"], errors="coerce"), weights=weights))


def _print_report(slate: pd.DataFrame, rules: pd.DataFrame, grid: pd.DataFrame, summary_path: Path) -> None:
    cols = [
        "date",
        "n",
        "games",
        "q_out_frac_mean",
        "q_blowout_p90",
        "role_ctx_outs_used_share_gt0",
        "bp_has_mean",
        "delta_aggressive_mB",
        "delta_defensive_mB",
        "defensive_benefit_mB",
    ]
    print("\nSLATE PREGAME METRICS")
    print(slate[cols].to_string(index=False))

    print("\nNAMED TRIGGER RULES")
    show_cols = [
        "rule",
        "verdict",
        "agg_delta_mB",
        "clean_agg_delta_mB",
        "worst_slate_mB",
        "flagged_date_list",
    ]
    print(rules.sort_values(["verdict_rank", "agg_delta_mB"])[show_cols].to_string(index=False))

    print("\nTOP GRID RULES")
    print(grid[show_cols].head(10).to_string(index=False))
    print(f"\nsummary: {_rel(summary_path)}")


def _load_pickle(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return pickle.load(f)


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _mean(s: pd.Series) -> float | None:
    s = pd.to_numeric(s, errors="coerce")
    return None if s.notna().sum() == 0 else float(s.mean())


def _quantile(s: pd.Series, q: float) -> float | None:
    s = pd.to_numeric(s, errors="coerce")
    return None if s.notna().sum() == 0 else float(s.quantile(q))


def _ratio(num: Any, den: Any) -> float | None:
    try:
        den = float(den)
        return None if den == 0 else float(num) / den
    except Exception:
        return None


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [_jsonable(r) for r in df.to_dict(orient="records")]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if pd.isna(value):
        return None
    return value


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())

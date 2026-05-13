#!/usr/bin/env python
"""Audit pre-CAT raw Brier failures.

Focuses on `p_for_cal`, the probability surface before CatBoost modifies it.
The goal is to find upstream failure modes that CAT can only mitigate.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = (
    ROOT
    / "data/model/candidates/atlas_replay_minute_risk_canonical_12date_cat_off_20260512_090130/"
    / "_v1_playoff_resim_cache_12date_cat_off.pkl"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit raw p_for_cal Brier before CatBoost.")
    ap.add_argument("--cache-path", default=str(DEFAULT_CACHE), help="Replay cache pickle.")
    ap.add_argument("--target-date", default="2026-05-11", help="Date to diagnose.")
    ap.add_argument("--out-dir", default="logs/precat_raw_brier_audit_20260512", help="Output directory.")
    args = ap.parse_args()

    cache_path = _resolve(args.cache_path)
    out_dir = _resolve(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with cache_path.open("rb") as f:
        cache = pickle.load(f)
    df = cache["cv"].copy()
    df["date"] = df["game_date"].astype(str).str[:10]
    df = _prepare(df)

    target = df[df["date"] == args.target_date].copy()
    reference = df[df["date"] != args.target_date].copy()
    if target.empty:
        raise SystemExit(f"No rows for target date {args.target_date}")

    date_summary = _date_summary(df)
    segment_summary = _segment_gap_summary(target, reference)
    candidate_summary = _candidate_transforms(df, args.target_date)

    date_summary.to_csv(out_dir / "date_summary.csv", index=False)
    segment_summary.to_csv(out_dir / "target_segment_gaps.csv", index=False)
    candidate_summary.to_csv(out_dir / "candidate_transforms.csv", index=False)

    summary = {
        "cache_path": _rel(cache_path),
        "target_date": args.target_date,
        "target": _records(date_summary[date_summary["date"] == args.target_date]),
        "worst_segments": _records(segment_summary.head(25)),
        "candidate_transforms": _records(candidate_summary),
        "artifacts": {
            "date_summary": _rel(out_dir / "date_summary.csv"),
            "target_segment_gaps": _rel(out_dir / "target_segment_gaps.csv"),
            "candidate_transforms": _rel(out_dir / "candidate_transforms.csv"),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")

    _print_report(date_summary, segment_summary, candidate_summary, args.target_date, out_dir / "summary.json")
    return 0


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["hit"] = pd.to_numeric(out["hit"], errors="coerce")
    out["p_for_cal"] = pd.to_numeric(out.get("p_for_cal", out.get("p_adj")), errors="coerce").clip(0.0, 1.0)
    out["raw_sqerr"] = (out["p_for_cal"] - out["hit"]) ** 2
    out["prob_bucket"] = pd.cut(
        out["p_for_cal"],
        bins=[0.0, 0.35, 0.45, 0.55, 0.65, 0.75, 1.0],
        include_lowest=True,
        labels=["p00_35", "p35_45", "p45_55", "p55_65", "p65_75", "p75_100"],
    ).astype(str)
    out["q_blowout_bucket"] = pd.cut(
        pd.to_numeric(out.get("q_blowout"), errors="coerce"),
        bins=[-0.001, 0.20, 0.35, 0.50, 1.0],
        labels=["qbo_00_20", "qbo_20_35", "qbo_35_50", "qbo_50_100"],
    ).astype(str)
    out["q_out_bucket"] = pd.cut(
        pd.to_numeric(out.get("q_out_frac"), errors="coerce").fillna(0.0),
        bins=[-0.001, 0.0, 0.10, 0.25, 1.0],
        labels=["qout_0", "qout_00_10", "qout_10_25", "qout_25_100"],
    ).astype(str)
    out["role_ctx_bucket"] = np.where(
        pd.to_numeric(out.get("role_ctx_outs_used"), errors="coerce").fillna(0.0) > 0.0,
        "role_on",
        "role_off",
    )
    out["bp_bucket"] = np.where(pd.to_numeric(out.get("bp_has"), errors="coerce").fillna(0.0) > 0.0, "bp_on", "bp_off")
    out["stat_direction"] = out["stat"].astype(str).str.upper() + "_" + out["direction"].astype(str).str.upper()
    out["tier_direction"] = out["tier"].astype(str).str.upper() + "_" + out["direction"].astype(str).str.upper()
    out["line_bucket"] = out.apply(_line_bucket, axis=1)
    out = out[out["hit"].isin([0, 1, 0.0, 1.0]) & out["p_for_cal"].notna()].copy()
    return out


def _line_bucket(row: pd.Series) -> str:
    stat = str(row.get("stat", "")).upper()
    line = _float(row.get("line"))
    if line is None:
        return "line_unknown"
    thresholds = {
        "FG3M": 1.5,
        "PTS": 8.5,
        "REB": 3.5,
        "AST": 3.5,
        "PR": 12.5,
        "PA": 12.5,
        "RA": 8.5,
        "PRA": 16.5,
    }
    threshold = thresholds.get(stat)
    if threshold is None:
        return "line_other"
    return f"low_{stat}" if line <= threshold else f"normal_{stat}"


def _date_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, g in df.groupby("date", sort=True):
        rows.append(
            {
                "date": date,
                "n": int(len(g)),
                "brier_p_for_cal": _brier(g),
                "hit_rate": float(g["hit"].mean()),
                "mean_p_for_cal": float(g["p_for_cal"].mean()),
                "calibration_gap": float(g["p_for_cal"].mean() - g["hit"].mean()),
                "games": int(g["game_id"].nunique()) if "game_id" in g.columns else None,
                "q_out_frac_mean": _mean(g.get("q_out_frac")),
                "q_blowout_p90": _quantile(g.get("q_blowout"), 0.90),
                "role_ctx_share": float((pd.to_numeric(g.get("role_ctx_outs_used"), errors="coerce").fillna(0.0) > 0).mean()),
                "bp_has_mean": _mean(g.get("bp_has")),
            }
        )
    return pd.DataFrame(rows).sort_values("date")


def _segment_gap_summary(target: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    segment_cols = [
        "stat",
        "direction",
        "tier",
        "stat_direction",
        "tier_direction",
        "line_bucket",
        "prob_bucket",
        "q_blowout_bucket",
        "q_out_bucket",
        "role_ctx_bucket",
        "bp_bucket",
        "team",
        "opp",
    ]
    rows = []
    target_brier = _brier(target)
    for col in segment_cols:
        if col not in target.columns:
            continue
        for key, tg in target.groupby(col, dropna=False):
            if len(tg) < 20:
                continue
            rf = reference[reference[col].astype(str) == str(key)]
            if len(rf) < 50:
                continue
            tg_brier = _brier(tg)
            rf_brier = _brier(rf)
            rows.append(
                {
                    "segment_col": col,
                    "segment": str(key),
                    "target_n": int(len(tg)),
                    "reference_n": int(len(rf)),
                    "target_brier": tg_brier,
                    "reference_brier": rf_brier,
                    "brier_gap": tg_brier - rf_brier,
                    "target_hit_rate": float(tg["hit"].mean()),
                    "target_mean_p": float(tg["p_for_cal"].mean()),
                    "target_calibration_gap": float(tg["p_for_cal"].mean() - tg["hit"].mean()),
                    "target_brier_contribution": float((tg_brier - target_brier) * len(tg) / len(target)),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["target_brier_contribution", "brier_gap", "target_n"], ascending=[False, False, False])


def _candidate_transforms(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    candidates: list[tuple[str, pd.Series]] = []
    p = df["p_for_cal"].copy()

    # Candidate 1: slate-risk logit downshift, only for the known pregame risk signature.
    risk_mask = (
        ((df["game_id"].groupby(df["date"]).transform("nunique") <= 2) & (pd.to_numeric(df.get("q_out_frac"), errors="coerce").fillna(0.0).groupby(df["date"]).transform("mean") >= 0.05))
        | ((pd.to_numeric(df.get("q_blowout"), errors="coerce").fillna(0.0).groupby(df["date"]).transform(lambda x: x.quantile(0.90)) >= 0.55)
           & ((pd.to_numeric(df.get("role_ctx_outs_used"), errors="coerce").fillna(0.0) > 0.0).groupby(df["date"]).transform("mean") <= 0.30))
    )
    for delta in [-0.05, -0.10, -0.15, -0.20]:
        candidates.append((f"slate_risk_logit_shift_{delta:+.2f}", _logit_shift(p, delta, risk_mask)))

    # Candidate 2: high-prob shrink on risky slate; designed for overconfidence.
    for k in [0.80, 0.65, 0.50]:
        candidates.append((f"slate_risk_highprob_shrink_k{k:.2f}", _highprob_shrink(p, risk_mask, threshold=0.55, k=k)))

    # Candidate 3: q_out-specific downshift, leg-level.
    q_out_leg = pd.to_numeric(df.get("q_out_frac"), errors="coerce").fillna(0.0) > 0.0
    for delta in [-0.05, -0.10, -0.15]:
        candidates.append((f"q_out_leg_logit_shift_{delta:+.2f}", _logit_shift(p, delta, q_out_leg)))

    rows = []
    baseline = _date_metric_rows(df, p, "baseline", target_date)
    rows.extend(baseline)
    for name, p_new in candidates:
        rows.extend(_date_metric_rows(df, p_new, name, target_date))
    out = pd.DataFrame(rows)
    target = out[out["date"] == target_date].copy()
    base_target = float(target[target["candidate"] == "baseline"]["brier"].iloc[0])
    out["target_delta_mB"] = np.nan
    for candidate in out["candidate"].unique():
        cand_target = out[(out["candidate"] == candidate) & (out["date"] == target_date)]
        if not cand_target.empty:
            out.loc[out["candidate"] == candidate, "target_delta_mB"] = (float(cand_target["brier"].iloc[0]) - base_target) * 1000.0
    return out.sort_values(["target_delta_mB", "candidate", "date"], ascending=[True, True, True])


def _date_metric_rows(df: pd.DataFrame, p: pd.Series, candidate: str, target_date: str) -> list[dict[str, Any]]:
    rows = []
    for date, idx in df.groupby("date").groups.items():
        g = df.loc[idx]
        pp = pd.to_numeric(p.loc[idx], errors="coerce").clip(0.0, 1.0)
        y = g["hit"]
        rows.append(
            {
                "candidate": candidate,
                "date": date,
                "is_target": date == target_date,
                "n": int(len(g)),
                "brier": float(((pp - y) ** 2).mean()),
                "mean_p": float(pp.mean()),
                "hit_rate": float(y.mean()),
                "calibration_gap": float(pp.mean() - y.mean()),
            }
        )
    return rows


def _logit_shift(p: pd.Series, delta: float, mask: pd.Series) -> pd.Series:
    out = p.copy()
    safe = out.clip(1e-5, 1 - 1e-5)
    shifted = 1.0 / (1.0 + np.exp(-(np.log(safe / (1.0 - safe)) + delta)))
    out.loc[mask] = shifted.loc[mask]
    return out.clip(0.0, 1.0)


def _highprob_shrink(p: pd.Series, mask: pd.Series, *, threshold: float, k: float) -> pd.Series:
    out = p.copy()
    p_thr = float(threshold)
    safe = out.clip(1e-5, 1 - 1e-5)
    logit = np.log(safe / (1.0 - safe))
    thr_logit = math.log(p_thr / (1.0 - p_thr))
    shrunk_logit = np.where(out > p_thr, thr_logit + k * (logit - thr_logit), logit)
    shrunk = 1.0 / (1.0 + np.exp(-shrunk_logit))
    out.loc[mask] = pd.Series(shrunk, index=out.index).loc[mask]
    return out.clip(0.0, 1.0)


def _print_report(date_summary: pd.DataFrame, segment_summary: pd.DataFrame, candidates: pd.DataFrame, target_date: str, summary_path: Path) -> None:
    print("\nPRE-CAT RAW BRIER BY DATE")
    print(date_summary.to_string(index=False))
    print("\nTARGET WORST SEGMENTS")
    cols = [
        "segment_col",
        "segment",
        "target_n",
        "target_brier",
        "reference_brier",
        "brier_gap",
        "target_hit_rate",
        "target_mean_p",
        "target_calibration_gap",
        "target_brier_contribution",
    ]
    print(segment_summary[cols].head(25).to_string(index=False))
    print("\nCANDIDATE RAW-P SURFACES ON TARGET")
    target = candidates[candidates["date"] == target_date].copy()
    show = ["candidate", "brier", "target_delta_mB", "mean_p", "hit_rate", "calibration_gap"]
    print(target[show].drop_duplicates().head(20).to_string(index=False))
    print(f"\nsummary: {_rel(summary_path)}")


def _brier(df: pd.DataFrame) -> float:
    return float(((df["p_for_cal"] - df["hit"]) ** 2).mean())


def _mean(s: Any) -> float | None:
    if s is None:
        return None
    values = pd.to_numeric(s, errors="coerce")
    return None if values.notna().sum() == 0 else float(values.mean())


def _quantile(s: Any, q: float) -> float | None:
    if s is None:
        return None
    values = pd.to_numeric(s, errors="coerce")
    return None if values.notna().sum() == 0 else float(values.quantile(q))


def _float(x: Any) -> float | None:
    try:
        value = float(x)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [_jsonable(x) for x in df.to_dict(orient="records")]


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

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Any

import numpy as np
import pandas as pd


REQUIRED_RUN_FILES = ("eval_legs.csv", "scored_legs_deduped.csv")


def _find_run_dirs(corpus_root: Path) -> List[Path]:
    if not corpus_root.exists():
        raise FileNotFoundError(f"Corpus root does not exist: {corpus_root}")

    base = corpus_root / "runs" if (corpus_root / "runs").exists() else corpus_root
    candidates = [p for p in base.iterdir() if p.is_dir()]
    run_dirs: List[Path] = []
    for p in sorted(candidates):
        files = {f.name for f in p.iterdir() if f.is_file()}
        if all(name in files for name in REQUIRED_RUN_FILES):
            run_dirs.append(p)
    if not run_dirs:
        raise RuntimeError(f"No readable runs found under {corpus_root}")
    return run_dirs


def _safe_col(df: pd.DataFrame, name: str, default: Any = np.nan):
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)


def _normalize_string(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip()


def _bucketize(series: pd.Series) -> pd.Series:
    bins = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    labels = ["(0.0,0.5]", "(0.5,0.6]", "(0.6,0.7]", "(0.7,0.8]", "(0.8,0.9]", "(0.9,1.0]"]
    s = pd.to_numeric(series, errors="coerce").clip(lower=0.0, upper=1.0)
    return pd.cut(s, bins=bins, labels=labels, include_lowest=True)


def _games_bucket(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    bins = [-1, 4, 9, 19, 9999]
    labels = ["0to4", "5to9", "10to19", "20plus"]
    return pd.cut(s, bins=bins, labels=labels, include_lowest=True)


def _brier(p: pd.Series, y: pd.Series) -> float:
    p = pd.to_numeric(p, errors="coerce")
    y = pd.to_numeric(y, errors="coerce")
    mask = p.notna() & y.notna()
    if not mask.any():
        return float("nan")
    return float(np.mean((p[mask] - y[mask]) ** 2))


def _logloss(p: pd.Series, y: pd.Series) -> float:
    p = pd.to_numeric(p, errors="coerce").clip(1e-6, 1 - 1e-6)
    y = pd.to_numeric(y, errors="coerce")
    mask = p.notna() & y.notna()
    if not mask.any():
        return float("nan")
    p = p[mask]
    y = y[mask]
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _read_run(run_dir: Path) -> pd.DataFrame:
    eval_df = pd.read_csv(run_dir / "eval_legs.csv")
    scored_df = pd.read_csv(run_dir / "scored_legs_deduped.csv")
    eval_df.columns = [str(c) for c in eval_df.columns]
    scored_df.columns = [str(c) for c in scored_df.columns]

    key = ["player", "stat", "direction", "line"]
    for col in key:
        eval_df[col] = _normalize_string(_safe_col(eval_df, col, ""))
        scored_df[col] = _normalize_string(_safe_col(scored_df, col, ""))

    cols = [
        "player", "stat", "direction", "line", "team", "game_date", "p_adj", "p_cal", "p_for_cal",
        "p_cal_src", "games_used", "role_ctx_outs_used", "role_ctx_reason", "telemetry_cal_applied",
        "telemetry_cal_key", "telemetry_mult", "telemetry_under_penalty", "telemetry_bucket_mult",
        "is_questionable", "q_out_frac", "prop_key"
    ]
    use = [c for c in cols if c in scored_df.columns]
    merged = eval_df.merge(scored_df[use].drop_duplicates(key, keep="first"), on=key, how="left", suffixes=("", "_scored"))

    merged["run_id"] = run_dir.name
    merged["hit"] = pd.to_numeric(_safe_col(merged, "hit"), errors="coerce")
    merged["p_adj"] = pd.to_numeric(_safe_col(merged, "p_adj"), errors="coerce")
    merged["p_cal"] = pd.to_numeric(_safe_col(merged, "p_cal"), errors="coerce")
    merged["p_for_cal"] = pd.to_numeric(_safe_col(merged, "p_for_cal"), errors="coerce")
    merged["games_used"] = pd.to_numeric(_safe_col(merged, "games_used"), errors="coerce")
    merged["role_ctx_outs_used"] = pd.to_numeric(_safe_col(merged, "role_ctx_outs_used", 0), errors="coerce").fillna(0)
    merged["telemetry_cal_applied"] = _safe_col(merged, "telemetry_cal_applied", False).fillna(False).astype(bool)
    merged["is_questionable"] = _safe_col(merged, "is_questionable", False).fillna(False).astype(bool)
    merged["direction"] = _normalize_string(_safe_col(merged, "direction", ""))
    merged["stat"] = _normalize_string(_safe_col(merged, "stat", ""))
    merged["p_adj_bucket"] = _bucketize(merged["p_adj"])
    merged["p_cal_bucket"] = _bucketize(merged["p_cal"])
    merged["games_bucket"] = _games_bucket(merged["games_used"])
    merged["role_ctx_state"] = np.where(merged["role_ctx_outs_used"] > 0, "role_ctx_on", "role_ctx_off")
    merged["questionable_state"] = np.where(merged["is_questionable"], "questionable", "not_questionable")
    return merged


def _slice_table(df: pd.DataFrame, by: List[str], pred_col: str) -> pd.DataFrame:
    group = df.groupby(by, dropna=False)
    out = group.agg(
        rows=("hit", "size"),
        hit_rate=("hit", "mean"),
        mean_pred=(pred_col, "mean"),
        mean_p_adj=("p_adj", "mean"),
        mean_p_cal=("p_cal", "mean"),
    ).reset_index()
    out["gap"] = out["mean_pred"] - out["hit_rate"]
    out["abs_gap"] = out["gap"].abs()
    briers = []
    logs = []
    for _, sub in group:
        briers.append(_brier(sub[pred_col], sub["hit"]))
        logs.append(_logloss(sub[pred_col], sub["hit"]))
    out["brier"] = briers
    out["logloss"] = logs
    return out.sort_values(["abs_gap", "rows"], ascending=[False, False])


def _run_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for run_id, sub in df.groupby("run_id"):
        rows.append({
            "run_id": run_id,
            "rows": len(sub),
            "mean_hit": float(sub["hit"].mean()),
            "mean_p_adj": float(sub["p_adj"].mean()),
            "mean_p_cal": float(sub["p_cal"].mean()),
            "brier_p_adj": _brier(sub["p_adj"], sub["hit"]),
            "brier_p_cal": _brier(sub["p_cal"], sub["hit"]),
            "logloss_p_adj": _logloss(sub["p_adj"], sub["hit"]),
            "logloss_p_cal": _logloss(sub["p_cal"], sub["hit"]),
            "telemetry_applied_share": float(sub["telemetry_cal_applied"].mean()) if "telemetry_cal_applied" in sub else 0.0,
        })
    return pd.DataFrame(rows).sort_values("run_id")


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnostic calibration pass over replay corpus.")
    ap.add_argument("--corpus-input", required=True)
    ap.add_argument("--output-root", required=True)
    args = ap.parse_args()

    corpus_root = Path(args.corpus_input)
    output_root = Path(args.output_root)
    run_dirs = _find_run_dirs(corpus_root)
    frames = [_read_run(rd) for rd in run_dirs]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["hit"].notna()].copy()

    stamp = pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = output_root / ".atlas_audit" / "diagnostics" / "telemetry_calibration_diagnostic" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    per_run = _run_summary(df)
    bucket_adj = _slice_table(df, ["p_adj_bucket"], "p_adj")
    bucket_cal = _slice_table(df, ["p_cal_bucket"], "p_cal")
    by_stat_dir = _slice_table(df, ["stat", "direction"], "p_cal")
    by_games = _slice_table(df, ["games_bucket"], "p_cal")
    by_role = _slice_table(df, ["role_ctx_state"], "p_cal")
    by_q = _slice_table(df, ["questionable_state"], "p_cal")
    by_src = _slice_table(df, ["p_cal_src"], "p_cal") if "p_cal_src" in df.columns else pd.DataFrame()
    by_reason = _slice_table(df, ["role_ctx_reason"], "p_cal") if "role_ctx_reason" in df.columns else pd.DataFrame()

    top_over = by_stat_dir[by_stat_dir["gap"] > 0].sort_values(["gap", "rows"], ascending=[False, False]).head(25)
    top_under = by_stat_dir[by_stat_dir["gap"] < 0].sort_values(["gap", "rows"], ascending=[True, False]).head(25)

    overall = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "runs_read": int(df["run_id"].nunique()),
        "settled_rows": int(len(df)),
        "mean_hit": float(df["hit"].mean()),
        "mean_p_adj": float(df["p_adj"].mean()),
        "mean_p_cal": float(df["p_cal"].mean()),
        "brier_p_adj": _brier(df["p_adj"], df["hit"]),
        "brier_p_cal": _brier(df["p_cal"], df["hit"]),
        "logloss_p_adj": _logloss(df["p_adj"], df["hit"]),
        "logloss_p_cal": _logloss(df["p_cal"], df["hit"]),
        "telemetry_applied_share": float(df["telemetry_cal_applied"].mean()) if "telemetry_cal_applied" in df else 0.0,
    }

    # write csv outputs
    per_run.to_csv(out_dir / "per_run_diagnostics.csv", index=False)
    bucket_adj.to_csv(out_dir / "bucket_diagnostics_p_adj.csv", index=False)
    bucket_cal.to_csv(out_dir / "bucket_diagnostics_p_cal.csv", index=False)
    by_stat_dir.to_csv(out_dir / "slice_diagnostics_stat_direction.csv", index=False)
    by_games.to_csv(out_dir / "slice_diagnostics_games_used.csv", index=False)
    by_role.to_csv(out_dir / "slice_diagnostics_role_ctx.csv", index=False)
    by_q.to_csv(out_dir / "slice_diagnostics_questionable.csv", index=False)
    if not by_src.empty:
        by_src.to_csv(out_dir / "slice_diagnostics_p_cal_src.csv", index=False)
    if not by_reason.empty:
        by_reason.to_csv(out_dir / "slice_diagnostics_role_ctx_reason.csv", index=False)
    top_over.to_csv(out_dir / "top_overconfident_slices.csv", index=False)
    top_under.to_csv(out_dir / "top_underconfident_slices.csv", index=False)

    hints = {
        "diagnostic_mode": "no_promotion_no_patch",
        "overall": overall,
        "likely_error_sources": {
            "top_overconfident_buckets": bucket_cal.head(10).to_dict(orient="records"),
            "top_overconfident_stat_direction": top_over.to_dict(orient="records"),
            "top_underconfident_stat_direction": top_under.to_dict(orient="records"),
        },
        "next_action": "Use these diagnostics to target the next challenger; do not auto-promote any calibration from this report."
    }
    (out_dir / "diagnostic_summary.json").write_text(json.dumps(hints, indent=2), encoding="utf-8")

    md = []
    md.append("# Telemetry Calibration Diagnostic\n")
    md.append(f"- Runs read: {overall['runs_read']}")
    md.append(f"- Settled rows: {overall['settled_rows']}")
    md.append(f"- Mean hit: {overall['mean_hit']:.6f}")
    md.append(f"- Mean p_adj: {overall['mean_p_adj']:.6f}")
    md.append(f"- Mean p_cal: {overall['mean_p_cal']:.6f}")
    md.append(f"- Brier p_adj: {overall['brier_p_adj']:.6f}")
    md.append(f"- Brier p_cal: {overall['brier_p_cal']:.6f}")
    md.append(f"- Logloss p_adj: {overall['logloss_p_adj']:.6f}")
    md.append(f"- Logloss p_cal: {overall['logloss_p_cal']:.6f}")
    md.append(f"- Telemetry applied share: {overall['telemetry_applied_share']:.6f}\n")

    md.append("## Most overconfident p_cal buckets\n")
    for _, row in bucket_cal.head(10).iterrows():
        md.append(f"- {row['p_cal_bucket']}: rows={int(row['rows'])}, pred={row['mean_pred']:.4f}, hit={row['hit_rate']:.4f}, gap={row['gap']:.4f}")

    md.append("\n## Most overconfident stat-direction slices\n")
    for _, row in top_over.head(15).iterrows():
        md.append(f"- {row['stat']} {row['direction']}: rows={int(row['rows'])}, pred={row['mean_pred']:.4f}, hit={row['hit_rate']:.4f}, gap={row['gap']:.4f}")

    md.append("\n## Most underconfident stat-direction slices\n")
    for _, row in top_under.head(15).iterrows():
        md.append(f"- {row['stat']} {row['direction']}: rows={int(row['rows'])}, pred={row['mean_pred']:.4f}, hit={row['hit_rate']:.4f}, gap={row['gap']:.4f}")

    md.append("\n## Interpretation\n")
    md.append("- This diagnostic pass isolates where calibration error is concentrated.")
    md.append("- It does not recommend or promote a challenger by itself.")
    md.append("- Use the bucket and slice files to design the next targeted experiment.")
    (out_dir / "diagnostic_summary.md").write_text("\n".join(md), encoding="utf-8")

    print(str(out_dir))


if __name__ == "__main__":
    main()

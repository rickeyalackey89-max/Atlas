"""Calibrate external-prior probability cap/scale from resolved eval rows.

This audit is intentionally post-hoc. It uses historical ``eval_legs.csv``
files, reconstructs the pre-prior probability surface from ``p_for_cal``, and
simulates candidate external-prior caps/scales before CatBoost touches the row.

Older Atlas runs stored ``external_prior_score`` but not the newer
``external_prior_delta_p`` trace column. They also had an UNDER sign issue.
For calibration, rows with ``external_prior_n > 0`` are treated as
direction-supported and their signal strength is reconstructed from
``abs(external_prior_score)``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = ROOT / "data" / "output" / "runs"
DEFAULT_OUT_ROOT = ROOT / "logs" / "external_prior_calibration"


def _parse_float_list(raw: str) -> list[float]:
    out: list[float] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def _run_date_from_name(name: str) -> str:
    digits = "".join(ch for ch in name[:8] if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return ""


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.fillna(default).astype("float64")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _manifest_external_prior_scale(run_dir: Path, default: float) -> float:
    manifest = _load_json(run_dir / "run_manifest.json")
    cfg = manifest.get("full_config", {}) if isinstance(manifest, dict) else {}
    opt = cfg.get("optimizer", {}) if isinstance(cfg, dict) else {}
    pri = opt.get("external_priors", {}) if isinstance(opt, dict) else {}
    try:
        return float(pri.get("scale", default))
    except Exception:
        return default


def _iter_eval_files(
    runs_root: Path,
    *,
    start_date: str | None,
    end_date: str | None,
) -> list[Path]:
    if not runs_root.exists():
        raise FileNotFoundError(f"Runs root not found: {runs_root}")

    files: list[Path] = []
    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        run_date = _run_date_from_name(run_dir.name)
        if start_date and run_date and run_date < start_date:
            continue
        if end_date and run_date and run_date > end_date:
            continue
        eval_path = run_dir / "eval_legs.csv"
        if eval_path.exists():
            files.append(eval_path)
    return files


def _load_eval_rows(
    eval_files: list[Path],
    *,
    base_col: str,
    original_scale_default: float,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    keep_cols = [
        "game_date",
        "player",
        "team",
        "stat",
        "line",
        "direction",
        "tier",
        "hit",
        "push",
        base_col,
        "p_adj",
        "p_cal",
        "external_prior_score",
        "external_prior_n",
        "external_prior_sources",
    ]

    for eval_path in eval_files:
        run_dir = eval_path.parent
        try:
            df = pd.read_csv(eval_path, low_memory=False, usecols=lambda c: c in keep_cols)
        except Exception:
            continue
        if df.empty or base_col not in df.columns or "hit" not in df.columns:
            continue

        df = df.copy()
        df["run_id"] = run_dir.name
        df["run_date"] = _run_date_from_name(run_dir.name)
        if "game_date" in df.columns:
            parsed_game_date = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df["run_date"] = parsed_game_date.fillna(df["run_date"])
        df["source_eval_path"] = str(eval_path)
        df["original_external_prior_scale"] = _manifest_external_prior_scale(
            run_dir,
            original_scale_default,
        )
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["hit"] = pd.to_numeric(out["hit"], errors="coerce")
    push = _num(out, "push", default=0.0)
    out = out[(out["hit"].isin([0.0, 1.0])) & (push == 0.0)].copy()
    out["base_p"] = _num(out, base_col, default=np.nan)
    out = out[out["base_p"].notna()].copy()
    out["base_p"] = out["base_p"].clip(0.01, 0.99)
    out["p_adj"] = _num(out, "p_adj", default=np.nan)
    out["p_cal"] = _num(out, "p_cal", default=np.nan)
    out["external_prior_n"] = _num(out, "external_prior_n", default=0.0)
    out["external_prior_score"] = _num(out, "external_prior_score", default=0.0)
    out["direction"] = out.get("direction", "").astype(str).str.upper().str.strip()
    out["stat"] = out.get("stat", "").astype(str).str.upper().str.strip()
    out["tier"] = out.get("tier", "").astype(str).str.upper().str.strip()
    out["has_external_prior"] = out["external_prior_n"] > 0
    return out


def _brier(p: pd.Series | np.ndarray, y: pd.Series | np.ndarray) -> float:
    p_arr = np.asarray(p, dtype="float64")
    y_arr = np.asarray(y, dtype="float64")
    mask = np.isfinite(p_arr) & np.isfinite(y_arr)
    if not mask.any():
        return float("nan")
    return float(np.mean(np.square(p_arr[mask] - y_arr[mask])))


def _date_weighted_brier(df: pd.DataFrame, p_col: str) -> float:
    vals: list[float] = []
    for _, grp in df.groupby("run_date", dropna=False):
        vals.append(_brier(grp[p_col], grp["hit"]))
    vals = [v for v in vals if np.isfinite(v)]
    return float(np.mean(vals)) if vals else float("nan")


def _candidate_probability(
    df: pd.DataFrame,
    *,
    cap: float,
    scale: float,
    p_floor: float,
    p_ceil: float,
) -> pd.Series:
    strength = df["external_prior_score"].abs().clip(0.0, 0.999999)
    original_scale = pd.to_numeric(df["original_external_prior_scale"], errors="coerce").fillna(1.5)
    edge_abs = np.arctanh(strength) * original_scale
    safe_scale = scale if scale > 1e-9 else 1.0
    candidate_score = np.tanh(edge_abs / safe_scale)
    candidate_score = pd.Series(candidate_score, index=df.index).fillna(0.0).clip(0.0, 1.0)
    delta = np.where(df["has_external_prior"], float(cap) * candidate_score, 0.0)
    return (df["base_p"] + delta).clip(p_floor, p_ceil)


def _candidate_probability_directional(
    df: pd.DataFrame,
    *,
    over_cap: float,
    under_cap: float,
    scale: float,
    p_floor: float,
    p_ceil: float,
) -> pd.Series:
    strength = df["external_prior_score"].abs().clip(0.0, 0.999999)
    original_scale = pd.to_numeric(df["original_external_prior_scale"], errors="coerce").fillna(1.5)
    edge_abs = np.arctanh(strength) * original_scale
    safe_scale = scale if scale > 1e-9 else 1.0
    candidate_score = np.tanh(edge_abs / safe_scale)
    candidate_score = pd.Series(candidate_score, index=df.index).fillna(0.0).clip(0.0, 1.0)
    caps = np.where(df["direction"] == "UNDER", float(under_cap), float(over_cap))
    delta = np.where(df["has_external_prior"], caps * candidate_score, 0.0)
    return (df["base_p"] + delta).clip(p_floor, p_ceil)


def _summarize_candidate(
    df: pd.DataFrame,
    *,
    cap: float,
    scale: float,
    p_col: str,
) -> dict[str, Any]:
    supported = df[df["has_external_prior"]]
    unsupported = df[~df["has_external_prior"]]
    row_brier = _brier(df[p_col], df["hit"])
    supported_brier = _brier(supported[p_col], supported["hit"]) if not supported.empty else float("nan")
    unsupported_brier = _brier(unsupported[p_col], unsupported["hit"]) if not unsupported.empty else float("nan")
    return {
        "cap": cap,
        "scale": scale,
        "rows": int(len(df)),
        "supported_rows": int(len(supported)),
        "coverage": float(len(supported) / len(df)) if len(df) else 0.0,
        "row_brier": row_brier,
        "date_weighted_brier": _date_weighted_brier(df, p_col),
        "supported_row_brier": supported_brier,
        "unsupported_row_brier": unsupported_brier,
    }


def _score_bin_summary(df: pd.DataFrame) -> pd.DataFrame:
    supported = df[df["has_external_prior"]].copy()
    if supported.empty:
        return pd.DataFrame()
    supported["support_strength"] = supported["external_prior_score"].abs()
    bins = [0.0, 0.25, 0.50, 0.75, 0.90, 1.000001]
    labels = ["0-.25", ".25-.50", ".50-.75", ".75-.90", ".90-1"]
    supported["score_bin"] = pd.cut(
        supported["support_strength"],
        bins=bins,
        labels=labels,
        include_lowest=True,
        right=False,
    )
    rows = []
    for keys, grp in supported.groupby(["direction", "score_bin"], observed=True, dropna=False):
        direction, score_bin = keys
        rows.append(
            {
                "direction": direction,
                "score_bin": str(score_bin),
                "rows": int(len(grp)),
                "hit_rate": float(grp["hit"].mean()),
                "base_p_mean": float(grp["base_p"].mean()),
                "p_adj_mean": float(grp["p_adj"].mean()) if grp["p_adj"].notna().any() else None,
                "p_cal_mean": float(grp["p_cal"].mean()) if grp["p_cal"].notna().any() else None,
            }
        )
    return pd.DataFrame(rows)


def _group_summary(df: pd.DataFrame, best_p_col: str) -> pd.DataFrame:
    supported = df[df["has_external_prior"]].copy()
    if supported.empty:
        return pd.DataFrame()
    rows = []
    for keys, grp in supported.groupby(["direction", "stat", "tier"], dropna=False):
        direction, stat, tier = keys
        if len(grp) < 20:
            continue
        rows.append(
            {
                "direction": direction,
                "stat": stat,
                "tier": tier,
                "rows": int(len(grp)),
                "hit_rate": float(grp["hit"].mean()),
                "base_brier": _brier(grp["base_p"], grp["hit"]),
                "best_candidate_brier": _brier(grp[best_p_col], grp["hit"]),
                "p_adj_brier": _brier(grp["p_adj"], grp["hit"]),
                "p_cal_brier": _brier(grp["p_cal"], grp["hit"]),
                "base_p_mean": float(grp["base_p"].mean()),
                "best_p_mean": float(grp[best_p_col].mean()),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["candidate_vs_base_mb"] = (out["best_candidate_brier"] - out["base_brier"]) * 1000.0
        out = out.sort_values(["candidate_vs_base_mb", "rows"], ascending=[True, False])
    return out


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    eval_files = _iter_eval_files(
        Path(args.runs_root),
        start_date=args.start_date,
        end_date=args.end_date,
    )
    for raw_path in args.eval_file or []:
        path = Path(raw_path)
        if path.is_dir():
            path = path / "eval_legs.csv"
        if path.exists():
            eval_files.append(path)
    for raw_pattern in args.eval_glob or []:
        for matched in glob.glob(raw_pattern, recursive=True):
            path = Path(matched)
            if path.is_dir():
                path = path / "eval_legs.csv"
            if path.exists():
                eval_files.append(path)
    eval_files = sorted(set(eval_files))

    df = _load_eval_rows(
        eval_files,
        base_col=args.base_col,
        original_scale_default=args.original_scale_default,
    )
    if df.empty:
        raise RuntimeError("No usable eval rows found for external-prior calibration.")

    caps = _parse_float_list(args.caps)
    scales = _parse_float_list(args.scales)
    p_floor = float(args.p_floor)
    p_ceil = float(args.p_ceil)

    baseline = {
        "base_col": args.base_col,
        "row_brier": _brier(df["base_p"], df["hit"]),
        "date_weighted_brier": _date_weighted_brier(df, "base_p"),
        "p_adj_row_brier": _brier(df["p_adj"], df["hit"]),
        "p_cal_row_brier": _brier(df["p_cal"], df["hit"]),
        "rows": int(len(df)),
        "runs": int(df["run_id"].nunique()),
        "dates": int(df["run_date"].nunique()),
        "supported_rows": int(df["has_external_prior"].sum()),
        "coverage": float(df["has_external_prior"].mean()) if len(df) else 0.0,
    }

    candidate_rows: list[dict[str, Any]] = []
    for cap in caps:
        for scale in scales:
            p_col = f"candidate_cap_{cap:g}_scale_{scale:g}"
            df[p_col] = _candidate_probability(
                df,
                cap=cap,
                scale=scale,
                p_floor=p_floor,
                p_ceil=p_ceil,
            )
            candidate_rows.append(_summarize_candidate(df, cap=cap, scale=scale, p_col=p_col))

    candidates = pd.DataFrame(candidate_rows)
    candidates["row_vs_base_mb"] = (candidates["row_brier"] - baseline["row_brier"]) * 1000.0
    candidates["date_weighted_vs_base_mb"] = (
        candidates["date_weighted_brier"] - baseline["date_weighted_brier"]
    ) * 1000.0
    candidates["supported_vs_base_mb"] = (
        candidates["supported_row_brier"]
        - _brier(df.loc[df["has_external_prior"], "base_p"], df.loc[df["has_external_prior"], "hit"])
    ) * 1000.0
    candidates = candidates.sort_values(["date_weighted_brier", "row_brier"], ascending=True)

    best = candidates.iloc[0].to_dict()
    best_p_col = f"candidate_cap_{best['cap']:g}_scale_{best['scale']:g}"

    direction_rows: list[dict[str, Any]] = []
    for over_cap in caps:
        for under_cap in caps:
            for scale in scales:
                p_col = f"direction_candidate_over_{over_cap:g}_under_{under_cap:g}_scale_{scale:g}"
                df[p_col] = _candidate_probability_directional(
                    df,
                    over_cap=over_cap,
                    under_cap=under_cap,
                    scale=scale,
                    p_floor=p_floor,
                    p_ceil=p_ceil,
                )
                row = _summarize_candidate(df, cap=over_cap, scale=scale, p_col=p_col)
                row["over_cap"] = over_cap
                row["under_cap"] = under_cap
                direction_rows.append(row)
                del df[p_col]
    direction_candidates = pd.DataFrame(direction_rows)
    direction_candidates["row_vs_base_mb"] = (
        direction_candidates["row_brier"] - baseline["row_brier"]
    ) * 1000.0
    direction_candidates["date_weighted_vs_base_mb"] = (
        direction_candidates["date_weighted_brier"] - baseline["date_weighted_brier"]
    ) * 1000.0
    direction_candidates["supported_vs_base_mb"] = (
        direction_candidates["supported_row_brier"]
        - _brier(df.loc[df["has_external_prior"], "base_p"], df.loc[df["has_external_prior"], "hit"])
    ) * 1000.0
    direction_candidates = direction_candidates.sort_values(
        ["date_weighted_brier", "row_brier"],
        ascending=True,
    )
    best_direction = direction_candidates.iloc[0].to_dict()

    score_bins = _score_bin_summary(df)
    groups = _group_summary(df, best_p_col)

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates.to_csv(out_dir / "cap_scale_sweep.csv", index=False)
    direction_candidates.to_csv(out_dir / "direction_cap_sweep.csv", index=False)
    score_bins.to_csv(out_dir / "score_bin_calibration.csv", index=False)
    groups.to_csv(out_dir / "direction_stat_tier_groups.csv", index=False)

    summary = {
        "created_at": ts,
        "runs_root": str(Path(args.runs_root).resolve()),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "caps": caps,
        "scales": scales,
        "p_floor": p_floor,
        "p_ceil": p_ceil,
        "baseline": baseline,
        "best_candidate": best,
        "best_direction_candidate": best_direction,
        "artifacts": {
            "out_dir": str(out_dir),
            "cap_scale_sweep": str(out_dir / "cap_scale_sweep.csv"),
            "direction_cap_sweep": str(out_dir / "direction_cap_sweep.csv"),
            "score_bin_calibration": str(out_dir / "score_bin_calibration.csv"),
            "direction_stat_tier_groups": str(out_dir / "direction_stat_tier_groups.csv"),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("[EXTERNAL_PRIOR_CAL] rows={rows} runs={runs} dates={dates} supported={supported} coverage={coverage:.1%}".format(
        rows=baseline["rows"],
        runs=baseline["runs"],
        dates=baseline["dates"],
        supported=baseline["supported_rows"],
        coverage=baseline["coverage"],
    ))
    print(
        "[EXTERNAL_PRIOR_CAL] baseline {base_col} brier={row:.6f} date_weighted={date:.6f} "
        "p_adj={p_adj:.6f} p_cal={p_cal:.6f}".format(
            base_col=args.base_col,
            row=baseline["row_brier"],
            date=baseline["date_weighted_brier"],
            p_adj=baseline["p_adj_row_brier"],
            p_cal=baseline["p_cal_row_brier"],
        )
    )
    print(
        "[EXTERNAL_PRIOR_CAL] best cap={cap:g} scale={scale:g} row_brier={row:.6f} "
        "date_weighted={date:.6f} row_vs_base={row_delta:+.2f}mB date_vs_base={date_delta:+.2f}mB".format(
            cap=best["cap"],
            scale=best["scale"],
            row=best["row_brier"],
            date=best["date_weighted_brier"],
            row_delta=best["row_vs_base_mb"],
            date_delta=best["date_weighted_vs_base_mb"],
        )
    )
    print(
        "[EXTERNAL_PRIOR_CAL] best direction over_cap={over:g} under_cap={under:g} scale={scale:g} "
        "row_brier={row:.6f} date_weighted={date:.6f} row_vs_base={row_delta:+.2f}mB "
        "date_vs_base={date_delta:+.2f}mB".format(
            over=best_direction["over_cap"],
            under=best_direction["under_cap"],
            scale=best_direction["scale"],
            row=best_direction["row_brier"],
            date=best_direction["date_weighted_brier"],
            row_delta=best_direction["row_vs_base_mb"],
            date_delta=best_direction["date_weighted_vs_base_mb"],
        )
    )
    print("[EXTERNAL_PRIOR_CAL] wrote", out_dir)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--start-date", default="2026-04-30")
    parser.add_argument("--end-date", default="2026-05-11")
    parser.add_argument("--base-col", default="p_for_cal")
    parser.add_argument("--caps", default="0,0.01,0.02,0.03,0.04,0.05,0.06,0.07")
    parser.add_argument("--scales", default="0.75,1.0,1.5,2.0,3.0,4.0")
    parser.add_argument("--p-floor", default=0.02, type=float)
    parser.add_argument("--p-ceil", default=0.98, type=float)
    parser.add_argument("--original-scale-default", default=1.5, type=float)
    parser.add_argument("--out-dir", default="")
    parser.add_argument(
        "--eval-file",
        action="append",
        default=[],
        help="Additional eval_legs.csv file or run directory to include. Can be repeated.",
    )
    parser.add_argument(
        "--eval-glob",
        action="append",
        default=[],
        help="Glob pattern for additional eval_legs.csv files or run directories.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    run_audit(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

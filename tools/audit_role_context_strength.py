from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_PATTERN = (
    "data/telemetry/replay_runs/"
    "nba_live_fidelity_20260430_20260519_current_features_*/**/eval_legs.csv"
)


def _read_eval_files(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = pd.read_csv(path, low_memory=False).copy()
        except Exception as exc:
            print(f"[ROLE_CTX_AUDIT] read failed: {path} ({exc})")
            continue
        frame["source_file"] = str(path)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    if "projection_id" in out.columns:
        out = out.drop_duplicates(subset=["projection_id"], keep="last")
    return out


def _numeric(df: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")


def _bucket_mult(value: float) -> str:
    if pd.isna(value):
        return "missing"
    if value <= 1.00001:
        return "<=1.00"
    if value <= 1.02:
        return "1.00-1.02"
    if value <= 1.04:
        return "1.02-1.04"
    if value <= 1.06:
        return "1.04-1.06"
    if value <= 1.08:
        return "1.06-1.08"
    return ">1.08"


def _bucket_bump(value: float) -> str:
    if pd.isna(value):
        return "missing"
    if value <= 0.00001:
        return "<=0%"
    if value <= 0.02:
        return "0-2%"
    if value <= 0.04:
        return "2-4%"
    if value <= 0.06:
        return "4-6%"
    if value <= 0.08:
        return "6-8%"
    return ">8%"


def _summarize(group_cols: list[str], df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for key, group in df.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        if len(group) < min_rows:
            continue
        pred = group["p_cal"].mean()
        hit = group["hit"].mean()
        rows.append(
            {
                **{col: val for col, val in zip(group_cols, key)},
                "n": int(len(group)),
                "hit_rate": round(float(hit), 6),
                "avg_p_cal": round(float(pred), 6),
                "cal_gap_hit_minus_p": round(float(hit - pred), 6),
                "brier_p_cal": round(float(((group["p_cal"] - group["hit"]) ** 2).mean()), 6),
                "avg_role_ctx_mult": round(float(group["role_ctx_mult"].mean()), 6),
                "avg_role_rate_mult": round(float(group["role_ctx_rate_mult"].mean()), 6),
                "avg_role_metrics_mult": round(float(group["role_metrics_mult"].mean()), 6),
                "avg_role_ctx_bump": round(float(group["role_ctx_bump"].mean()), 6),
                "outs_used_rate": round(float((group["role_ctx_outs_used"].fillna(0) > 0).mean()), 6),
            }
        )
    return pd.DataFrame(rows)


def _parse_role_ctx_by_out(value: object) -> list[dict[str, object]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        parsed = value
    else:
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                return []
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, object]] = []
    for item in parsed:
        if isinstance(item, dict):
            out.append(item)
    return out


def _build_out_player_frame(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    base_columns = [
        "projection_id",
        "game_date",
        "player",
        "team",
        "stat",
        "direction",
        "tier",
        "hit",
        "p_cal",
        "p_adj",
        "role_ctx_mult",
        "role_ctx_rate_mult",
        "role_metrics_mult",
        "role_ctx_bump",
        "role_ctx_outs_used",
    ]
    for _, row in frame.iterrows():
        by_out = _parse_role_ctx_by_out(row.get("role_ctx_by_out"))
        if not by_out:
            continue
        grouped: dict[str, float] = {}
        for item in by_out:
            out_canon = str(item.get("out_canon", "")).strip()
            if not out_canon:
                continue
            try:
                weight = float(item.get("weight", 0.0) or 0.0)
            except Exception:
                weight = 0.0
            grouped[out_canon] = grouped.get(out_canon, 0.0) + weight
        for out_canon, out_weight in grouped.items():
            payload = {col: row.get(col) for col in base_columns}
            payload["out_canon"] = out_canon
            payload["out_weight"] = out_weight
            rows.append(payload)
    out = pd.DataFrame(rows)
    if not out.empty:
        _numeric(
            out,
            [
                "hit",
                "p_cal",
                "p_adj",
                "role_ctx_mult",
                "role_ctx_rate_mult",
                "role_metrics_mult",
                "role_ctx_bump",
                "role_ctx_outs_used",
                "out_weight",
            ],
        )
    return out


def _summarize_out(group_cols: list[str], df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if df.empty:
        return pd.DataFrame()
    for key, group in df.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        if len(group) < min_rows:
            continue
        pred = group["p_cal"].mean()
        hit = group["hit"].mean()
        rows.append(
            {
                **{col: val for col, val in zip(group_cols, key)},
                "n": int(len(group)),
                "hit_rate": round(float(hit), 6),
                "avg_p_cal": round(float(pred), 6),
                "cal_gap_hit_minus_p": round(float(hit - pred), 6),
                "brier_p_cal": round(float(((group["p_cal"] - group["hit"]) ** 2).mean()), 6),
                "avg_out_weight": round(float(group["out_weight"].mean()), 6),
                "p90_out_weight": round(float(group["out_weight"].quantile(0.90)), 6),
                "avg_role_ctx_bump": round(float(group["role_ctx_bump"].mean()), 6),
                "avg_role_ctx_mult": round(float(group["role_ctx_mult"].mean()), 6),
                "avg_role_rate_mult": round(float(group["role_ctx_rate_mult"].mean()), 6),
            }
        )
    return pd.DataFrame(rows)


def build_role_context_audit(
    repo_root: Path,
    pattern: str,
    out_dir: Path,
    min_rows: int,
) -> dict[str, object]:
    paths = sorted(repo_root.glob(pattern))
    frame = _read_eval_files(paths)
    if frame.empty:
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"source_eval_files": len(paths), "rows_after_dedupe_with_truth": 0, "outputs": {}}
        (out_dir / "role_context_strength_audit.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return payload

    numeric_columns = [
        "hit",
        "p_cal",
        "p_adj",
        "p_role",
        "role_ctx_mult",
        "role_ctx_rate_mult",
        "role_metrics_mult",
        "role_ctx_bump",
        "role_ctx_outs_used",
    ]
    _numeric(frame, numeric_columns)
    for column in ["direction", "stat", "tier", "player", "game_date"]:
        if column not in frame.columns:
            frame[column] = ""

    frame = frame[frame["hit"].notna() & frame["p_cal"].notna()].copy()
    frame["role_ctx_mult_bucket"] = frame["role_ctx_mult"].map(_bucket_mult)
    frame["role_rate_mult_bucket"] = frame["role_ctx_rate_mult"].map(_bucket_mult)
    frame["role_bump_bucket"] = frame["role_ctx_bump"].map(_bucket_bump)
    frame["role_any_active"] = (
        (frame["role_ctx_mult"].fillna(1) != 1)
        | (frame["role_ctx_rate_mult"].fillna(1) != 1)
        | (frame["role_metrics_mult"].fillna(1) != 1)
        | (frame["role_ctx_bump"].fillna(0) != 0)
        | (frame["role_ctx_outs_used"].fillna(0) > 0)
    )

    summaries = {
        "role_context_bucket_summary.csv": _summarize(
            ["role_bump_bucket", "role_ctx_mult_bucket", "role_rate_mult_bucket"], frame, min_rows
        ),
        "role_context_active_summary.csv": _summarize(["role_any_active"], frame, min_rows),
        "role_context_stat_summary.csv": _summarize(["stat", "role_bump_bucket"], frame, min_rows),
        "role_context_direction_summary.csv": _summarize(
            ["direction", "role_bump_bucket"], frame, min_rows
        ),
        "role_context_over_summary.csv": _summarize(
            ["role_bump_bucket"],
            frame[frame["direction"].astype(str).str.upper().eq("OVER")].copy(),
            min_rows,
        ),
        "role_context_over_stat_summary.csv": _summarize(
            ["stat", "role_bump_bucket"],
            frame[frame["direction"].astype(str).str.upper().eq("OVER")].copy(),
            min_rows,
        ),
    }

    out_player_frame = _build_out_player_frame(frame)
    out_summaries = {
        "role_context_out_player_summary.csv": _summarize_out(
            ["out_canon"], out_player_frame, min_rows
        ),
        "role_context_out_player_direction_summary.csv": _summarize_out(
            ["out_canon", "direction"], out_player_frame, min_rows
        ),
        "role_context_out_beneficiary_summary.csv": _summarize_out(
            ["out_canon", "player", "team"], out_player_frame, min_rows
        ),
        "role_context_out_beneficiary_stat_summary.csv": _summarize_out(
            ["out_canon", "player", "team", "stat", "direction"], out_player_frame, min_rows
        ),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for name, summary in summaries.items():
        path = out_dir / name
        summary.to_csv(path, index=False)
        outputs[name] = str(path)
    for name, summary in out_summaries.items():
        path = out_dir / name
        summary.to_csv(path, index=False)
        outputs[name] = str(path)

    payload = {
        "source_eval_files": len(paths),
        "rows_after_dedupe_with_truth": int(len(frame)),
        "unique_dates": sorted(str(x) for x in frame["game_date"].dropna().unique()),
        "role_any_active_rate": float(frame["role_any_active"].mean()) if len(frame) else None,
        "role_ctx_outs_used_rate": float((frame["role_ctx_outs_used"].fillna(0) > 0).mean())
        if len(frame)
        else None,
        "role_ctx_bump_nonzero_rate": float((frame["role_ctx_bump"].fillna(0) != 0).mean())
        if len(frame)
        else None,
        "role_ctx_mult_stats": frame["role_ctx_mult"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).to_dict(),
        "role_ctx_rate_mult_stats": frame["role_ctx_rate_mult"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).to_dict(),
        "role_metrics_mult_stats": frame["role_metrics_mult"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).to_dict(),
        "role_ctx_bump_stats": frame["role_ctx_bump"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).to_dict(),
        "out_player_rows": int(len(out_player_frame)),
        "unique_out_players": int(out_player_frame["out_canon"].nunique()) if not out_player_frame.empty else 0,
        "outputs": outputs,
    }
    (out_dir / "role_context_strength_audit.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit NBA role-context strength against eval truth.")
    parser.add_argument("--repo-root", default=".", help="NBA repo root.")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="Glob pattern under repo root.")
    parser.add_argument(
        "--out-dir",
        default="data/output/diagnostics/role_context_strength",
        help="Output directory under repo root unless absolute.",
    )
    parser.add_argument("--min-rows", type=int, default=5)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir
    payload = build_role_context_audit(repo_root, args.pattern, out_dir, args.min_rows)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

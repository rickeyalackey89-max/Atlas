#!/usr/bin/env python
"""Audit whether a low-line/playoff-volatility selection guard is justified.

This is not a calibration audit. It asks whether fragile low-line legs should be
soft-demoted in p_select while leaving p_cal untouched.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning


ROOT = Path(__file__).resolve().parents[2]
REPLAY_ROOT = ROOT / "data" / "telemetry" / "replay_runs"
RUNS_ROOT = ROOT / "data" / "output" / "runs"
GAMELOGS = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"

warnings.filterwarnings("ignore", category=PerformanceWarning)


LOW_LINE_THRESHOLDS = {
    "FG3M": 1.5,
    "PTS": 5.5,
    "REB": 2.5,
    "AST": 2.5,
    "PR": 7.5,
    "PA": 7.5,
    "RA": 7.5,
    "PRA": 9.5,
}


EXCESS_FRAGILITY_CANDIDATE_CONFIG = {
    "enabled": True,
    "max_total_penalty": 0.04,
    "min_excess_zero_rate": 0.12,
    "min_zero_rate": 0.35,
    "low_line_pts_threshold": 6.5,
    "low_line_fg3m_threshold": 0.5,
    "require_low_attempt_volume": True,
    "apply_to_p_select_only": True,
}


FRAGILITY_EXPOSURE_CANDIDATE_CONFIG = {
    "enabled": True,
    "max_low_line_fragile_legs_per_slip": 1,
    "max_fg3m_overs_per_slip": 1,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit low-line volatility risk for p_select.")
    parser.add_argument(
        "--prefix",
        default="atlas_replay_v5cD_12date_cat_off_20260512_065554_",
        help="Replay corpus prefix ending before YYYYMMDD.",
    )
    parser.add_argument(
        "--dates",
        nargs="*",
        default=[
            "20260430",
            "20260501",
            "20260502",
            "20260503",
            "20260504",
            "20260505",
            "20260506",
            "20260507",
            "20260508",
            "20260509",
            "20260510",
            "20260511",
        ],
        help="Replay dates to audit.",
    )
    parser.add_argument("--runs", nargs="*", default=[], help="Optional live/output run IDs to include.")
    parser.add_argument("--out-dir", default="logs/low_line_volatility_audit", help="Output directory.")
    args = parser.parse_args()

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    gamelogs = _load_gamelogs()
    frames = []
    source_rows: list[dict[str, Any]] = []

    for date in args.dates:
        run_dir = _latest_replay_run_dir(args.prefix, date)
        if run_dir is None:
            print(f"[SKIP] missing replay eval for {args.prefix}{date}")
            continue
        eval_path = run_dir / "eval_legs.csv"
        df = _load_eval(eval_path, source=f"{args.prefix}{date}", run_id=run_dir.name)
        frames.append(df)
        source_rows.append({"source": f"{args.prefix}{date}", "run_dir": _rel(run_dir), "rows": int(len(df))})

    for run_id in args.runs:
        eval_path = RUNS_ROOT / run_id / "eval_legs.csv"
        if not eval_path.exists():
            print(f"[SKIP] missing live eval for {run_id}")
            continue
        df = _load_eval(eval_path, source=run_id, run_id=run_id)
        frames.append(df)
        source_rows.append({"source": run_id, "run_dir": _rel(eval_path.parent), "rows": int(len(df))})

    if not frames:
        raise SystemExit("No eval_legs inputs found.")

    legs = pd.concat(frames, ignore_index=True)
    legs = _add_runtime_risk_features(legs)
    legs = _add_l10_context(legs, gamelogs)
    legs = _add_candidate_penalties(legs)
    legs = _add_excess_fragility_candidate(legs)

    selected = _load_selected_from_sources(legs, args.prefix, args.dates, args.runs)

    legs_out = out_dir / "board_rows.csv"
    selected_out = out_dir / "selected_rows.csv"
    legs.to_csv(legs_out, index=False)
    selected.to_csv(selected_out, index=False)

    summary = {
        "inputs": source_rows,
        "board_summary": _summary_tables(legs),
        "selected_summary": _selected_summary(selected),
        "risk_flag_summary": _records(_risk_flag_summary(legs)),
        "selected_risk_flag_summary": _records(_risk_flag_summary(selected)) if not selected.empty else [],
        "line_bucket_summary": _records(_line_bucket_summary(legs)),
        "selected_line_bucket_summary": _records(_line_bucket_summary(selected)) if not selected.empty else [],
        "excess_fragility_summary": {
            "board": _guard_summary(legs, "excess_fragility_flagged", "excess_fragility_penalty", "p_select_excess_fragility"),
            "selected": _guard_summary(selected, "excess_fragility_flagged", "excess_fragility_penalty", "p_select_excess_fragility") if not selected.empty else {},
            "decision": _excess_fragility_recommendation(legs, selected),
            "candidate_config": EXCESS_FRAGILITY_CANDIDATE_CONFIG,
        },
        "fragility_exposure_summary": _fragility_exposure_summary(selected),
        "recommendation": _recommendation(legs, selected),
        "artifacts": {
            "board_rows": _rel(legs_out),
            "selected_rows": _rel(selected_out),
        },
    }
    summary_out = out_dir / "summary.json"
    summary_out.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")

    _print_report(summary, summary_out)
    return 0


def _latest_replay_run_dir(prefix: str, date: str) -> Path | None:
    root = REPLAY_ROOT / f"{prefix}{date}"
    if not root.exists():
        return None
    evals = sorted(root.rglob("eval_legs.csv"))
    if not evals:
        return None
    return evals[-1].parent


def _load_eval(path: Path, *, source: str, run_id: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["source"] = source
    df["run_id"] = run_id
    for col in ["player", "stat", "direction", "tier", "rotation_tier"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    for col in ["stat", "direction", "tier", "rotation_tier"]:
        if col in df.columns:
            df[col] = df[col].str.upper()
    for col in [
        "line",
        "hit",
        "actual",
        "p_cal",
        "p_for_cal",
        "p_adj",
        "min_mean",
        "min_std",
        "rate_mean",
        "rate_std",
        "games_used",
        "q_blowout",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    return df


def _add_runtime_risk_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["line_bucket"] = out.apply(_line_bucket, axis=1)
    out["low_line"] = out["line_bucket"].str.startswith("low_")
    out["minutes_cv"] = np.where(
        pd.to_numeric(out.get("min_mean"), errors="coerce") > 0,
        (pd.to_numeric(out.get("min_std"), errors="coerce") / pd.to_numeric(out.get("min_mean"), errors="coerce")).clip(0, 5),
        np.nan,
    )
    out["rate_cv"] = np.where(
        pd.to_numeric(out.get("rate_mean"), errors="coerce").abs() > 1e-9,
        (pd.to_numeric(out.get("rate_std"), errors="coerce") / pd.to_numeric(out.get("rate_mean"), errors="coerce").abs()).clip(0, 10),
        np.nan,
    )
    min_mean = pd.to_numeric(out.get("min_mean"), errors="coerce")
    rotation = out.get("rotation_tier", pd.Series("", index=out.index)).astype(str).str.upper()
    out["rotation_under_18"] = (min_mean < 18.0) & rotation.isin(["BENCH", "ROTATION", ""])
    out["low_line_minutes_cv"] = out["low_line"] & (out["minutes_cv"] > 0.35)
    out["low_line_rate_cv"] = out["low_line"] & (out["rate_cv"] > 0.95)
    out["fg3m_low_line"] = (out["stat"] == "FG3M") & (pd.to_numeric(out["line"], errors="coerce") <= 1.5)
    return out


def _line_bucket(row: pd.Series) -> str:
    stat = str(row.get("stat", "")).upper()
    line = _float(row.get("line"))
    if line is None:
        return "unknown"
    threshold = LOW_LINE_THRESHOLDS.get(stat)
    if threshold is None:
        return "other"
    if line <= threshold:
        return f"low_{stat}"
    return f"normal_{stat}"


def _load_gamelogs() -> pd.DataFrame:
    df = pd.read_csv(GAMELOGS, low_memory=False)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df["player_key"] = df["player"].astype(str).str.strip().str.lower()
    for col in ["minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["game_date", "player_key"]).sort_values("game_date")


def _add_l10_context(df: pd.DataFrame, gamelogs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        game_date = row.get("game_date")
        player = str(row.get("player", "")).strip().lower()
        if pd.isna(game_date) or not player:
            rows.append({})
            continue
        prior = gamelogs[(gamelogs["player_key"] == player) & (gamelogs["game_date"] < game_date)].tail(10)
        if prior.empty:
            rows.append({"l10_n": 0})
            continue
        vals = _stat_values(prior, str(row.get("stat", "")).upper())
        line = _float(row.get("line"))
        direction = str(row.get("direction", "")).upper()
        if line is None:
            hits = pd.Series(dtype=float)
        elif direction == "OVER":
            hits = (vals > line).astype(float)
        else:
            hits = (vals < line).astype(float)
        rows.append(
            {
                "l10_n": int(len(prior)),
                "l10_hit_rate": _mean(hits),
                "l10_zero_rate": float((vals == 0).mean()) if len(vals) else None,
                "l10_stat_avg": _mean(vals),
                "l10_stat_std": _std(vals),
                "l10_fga_avg": _mean(prior.get("fga")),
                "l10_fta_avg": _mean(prior.get("fta")),
                "l10_minutes_avg": _mean(prior.get("minutes")),
                "l10_minutes_min": _min(prior.get("minutes")),
            }
        )
    ctx = pd.DataFrame(rows, index=df.index)
    return pd.concat([df.reset_index(drop=True), ctx.reset_index(drop=True)], axis=1)


def _stat_values(df: pd.DataFrame, stat: str) -> pd.Series:
    pts = pd.to_numeric(df.get("pts", 0), errors="coerce").fillna(0)
    reb = pd.to_numeric(df.get("reb", 0), errors="coerce").fillna(0)
    ast = pd.to_numeric(df.get("ast", 0), errors="coerce").fillna(0)
    if stat == "PTS":
        return pts
    if stat == "REB":
        return reb
    if stat == "AST":
        return ast
    if stat == "FG3M":
        return pd.to_numeric(df.get("fg3m", 0), errors="coerce").fillna(0)
    if stat == "FGA":
        return pd.to_numeric(df.get("fga", 0), errors="coerce").fillna(0)
    if stat == "FTA":
        return pd.to_numeric(df.get("fta", 0), errors="coerce").fillna(0)
    if stat == "TOV":
        return pd.to_numeric(df.get("tov", 0), errors="coerce").fillna(0)
    if stat == "PRA":
        return pts + reb + ast
    if stat == "PR":
        return pts + reb
    if stat == "PA":
        return pts + ast
    if stat == "RA":
        return reb + ast
    return pd.Series(np.nan, index=df.index)


def _add_candidate_penalties(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["low_line_zero_rate"] = out["low_line"] & (pd.to_numeric(out.get("l10_zero_rate"), errors="coerce") >= 0.25)

    penalty = np.zeros(len(out), dtype="float64")
    penalty += np.where(out["low_line_zero_rate"], 0.06, 0.0)
    penalty += np.where(out["low_line_minutes_cv"], 0.04, 0.0)
    penalty += np.where(out["low_line_rate_cv"], 0.04, 0.0)
    penalty += np.where(out["fg3m_low_line"], 0.04, 0.0)
    penalty += np.where(out["rotation_under_18"] & out["low_line"], 0.05, 0.0)
    out["volatility_guard_penalty"] = np.clip(penalty, 0.0, 0.12)
    out["p_select_volatility"] = np.clip(pd.to_numeric(out.get("p_cal"), errors="coerce").fillna(0.5) - out["volatility_guard_penalty"], 0.0, 1.0)

    flags: list[str] = []
    for _, row in out.iterrows():
        parts = []
        for col in ["low_line_zero_rate", "low_line_minutes_cv", "low_line_rate_cv", "fg3m_low_line", "rotation_under_18"]:
            if bool(row.get(col, False)) and (col != "rotation_under_18" or bool(row.get("low_line", False))):
                parts.append(col)
        flags.append(",".join(parts))
    out["volatility_guard_flags"] = flags
    out["volatility_guard_flagged"] = out["volatility_guard_penalty"] > 0.0
    return out


def _add_excess_fragility_candidate(df: pd.DataFrame) -> pd.DataFrame:
    """Add the narrower excess-zero-risk candidate the model may promote later.

    This intentionally differs from the broad volatility candidate above. It only
    targets OVER legs where recent zero rate is high relative to the same
    stat/direction/line bucket peer group.
    """

    out = df.copy()
    cfg = EXCESS_FRAGILITY_CANDIDATE_CONFIG
    zero = pd.to_numeric(out.get("l10_zero_rate"), errors="coerce")
    l10_n = pd.to_numeric(out.get("l10_n"), errors="coerce").fillna(0)

    peer_cols = ["stat", "direction", "line_bucket"]
    peer_input = out[l10_n >= 5].copy()
    if peer_input.empty:
        out["excess_zero_peer_rate"] = np.nan
    else:
        peer_rates = (
            peer_input.groupby(peer_cols, dropna=False)["l10_zero_rate"]
            .mean()
            .rename("excess_zero_peer_rate")
            .reset_index()
        )
        out = out.merge(peer_rates, on=peer_cols, how="left")

    out["excess_zero_rate"] = zero - pd.to_numeric(out.get("excess_zero_peer_rate"), errors="coerce")

    stat = out.get("stat", pd.Series("", index=out.index)).astype(str).str.upper()
    direction = out.get("direction", pd.Series("", index=out.index)).astype(str).str.upper()
    line = pd.to_numeric(out.get("line"), errors="coerce")

    pts_low = (stat == "PTS") & (line <= float(cfg["low_line_pts_threshold"]))
    fg3m_low = (stat == "FG3M") & (line <= float(cfg["low_line_fg3m_threshold"]))
    out["excess_fragility_low_line"] = pts_low | fg3m_low

    stat_avg = pd.to_numeric(out.get("l10_stat_avg"), errors="coerce")
    fga_avg = pd.to_numeric(out.get("l10_fga_avg"), errors="coerce")
    low_attempt = pd.Series(False, index=out.index)
    # For PTS, use low shot volume and low scoring average. For FG3M, use low
    # recent made-three volume because the game log source lacks 3PA.
    low_attempt |= pts_low & ((fga_avg <= 5.5) | (stat_avg <= (line + 2.0)))
    low_attempt |= fg3m_low & (stat_avg <= 0.7)
    out["excess_fragility_low_attempt_volume"] = low_attempt

    required_attempt = low_attempt if bool(cfg["require_low_attempt_volume"]) else pd.Series(True, index=out.index)
    out["excess_fragility_flagged"] = (
        (direction == "OVER")
        & out["excess_fragility_low_line"]
        & required_attempt
        & (l10_n >= 5)
        & (zero >= float(cfg["min_zero_rate"]))
        & (pd.to_numeric(out["excess_zero_rate"], errors="coerce") >= float(cfg["min_excess_zero_rate"]))
    )

    penalty = np.where(out["excess_fragility_flagged"], float(cfg["max_total_penalty"]), 0.0)
    out["excess_fragility_penalty"] = penalty
    out["p_select_excess_fragility"] = np.clip(
        pd.to_numeric(out.get("p_cal"), errors="coerce").fillna(0.5) - out["excess_fragility_penalty"],
        0.0,
        1.0,
    )
    out["excess_fragility_flags"] = np.where(out["excess_fragility_flagged"], "excess_zero_low_line_over", "")
    return out


def _load_selected_from_sources(
    board: pd.DataFrame,
    prefix: str,
    dates: list[str],
    runs: list[str],
) -> pd.DataFrame:
    selected_rows: list[pd.DataFrame] = []
    for date in dates:
        run_dir = _latest_replay_run_dir(prefix, date)
        if run_dir is None:
            continue
        selected_rows.append(_selected_for_dir(board, run_dir, f"{prefix}{date}"))
    for run_id in runs:
        run_dir = RUNS_ROOT / run_id
        if run_dir.is_dir():
            selected_rows.append(_selected_for_dir(board, run_dir, run_id))
    selected_rows = [x for x in selected_rows if not x.empty]
    if not selected_rows:
        return pd.DataFrame()
    return pd.concat(selected_rows, ignore_index=True)


def _selected_for_dir(board: pd.DataFrame, run_dir: Path, source: str) -> pd.DataFrame:
    leg_keys: list[dict[str, Any]] = []
    for path in _selected_files(run_dir):
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        selected_file = _rel(path)
        if path.name == "marketed_slips.csv" and {"player", "stat", "direction", "tier", "line"} <= set(df.columns):
            for _, row in df.iterrows():
                slip_label = str(row.get("slip", row.get("label", "unknown"))).strip() or "unknown"
                slip_id = f"{source}|{selected_file}|marketed|{slip_label}"
                leg_keys.append(_leg_key_dict(row, source, selected_file, "marketed", slip_id))
        else:
            for row_idx, row in df.head(1).iterrows():
                slip_id = f"{source}|{selected_file}|recommended|row:{row_idx}"
                for text in _leg_texts(row):
                    parsed = _parse_leg(text)
                    if parsed is not None:
                        player, direction, stat, line, tier, projection_id = parsed
                        leg_keys.append(
                            {
                                "source": source,
                                "selected_file": selected_file,
                                "selected_product": "recommended",
                                "slip_id": slip_id,
                                "player": player,
                                "stat": stat,
                                "direction": direction,
                                "tier": tier,
                                "line": line,
                                "projection_id": projection_id,
                            }
                        )
    if not leg_keys:
        return pd.DataFrame()
    keys = pd.DataFrame(leg_keys)
    src_board = board[board["source"] == source].copy()
    if src_board.empty:
        return pd.DataFrame()
    src_board["_match_player"] = src_board["player"].astype(str).str.lower().str.strip()
    keys["_match_player"] = keys["player"].astype(str).str.lower().str.strip()
    for frame in [src_board, keys]:
        frame["stat"] = frame["stat"].astype(str).str.upper().str.strip()
        frame["direction"] = frame["direction"].astype(str).str.upper().str.strip()
        frame["tier"] = frame["tier"].astype(str).str.upper().str.strip()
        frame["line"] = pd.to_numeric(frame["line"], errors="coerce")
    merged = keys.merge(
        src_board,
        on=["source", "_match_player", "stat", "direction", "tier", "line"],
        how="inner",
        suffixes=("_selected", ""),
    )
    return merged


def _selected_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in ["marketed_slips.csv", "recommended_3leg.csv", "recommended_4leg.csv", "recommended_5leg.csv"]:
        p = run_dir / name
        if p.exists():
            files.append(p)
    for sub in ["System", "Windfall"]:
        for name in ["recommended_3leg.csv", "recommended_4leg.csv", "recommended_5leg.csv"]:
            p = run_dir / sub / name
            if p.exists():
                files.append(p)
    return files


def _leg_key_dict(row: pd.Series, source: str, selected_file: str, product: str, slip_id: str) -> dict[str, Any]:
    return {
        "source": source,
        "selected_file": selected_file,
        "selected_product": product,
        "slip_id": slip_id,
        "player": str(row.get("player", "")).strip(),
        "stat": str(row.get("stat", "")).strip().upper(),
        "direction": str(row.get("direction", "")).strip().upper(),
        "tier": str(row.get("tier", "")).strip().upper(),
        "line": _float(row.get("line")),
        "projection_id": str(row.get("projection_id", "")).strip(),
    }


def _leg_texts(row: pd.Series) -> list[str]:
    leg_cols = [col for col in row.index if re.fullmatch(r"leg_\d+", str(col))]
    if leg_cols:
        return [str(row[col]) for col in sorted(leg_cols, key=lambda c: int(str(c).split("_")[1])) if str(row[col]).strip()]
    return [part.strip() for part in str(row.get("legs", "")).split(" | ") if part.strip()]


def _parse_leg(text: str) -> tuple[str, str, str, float, str, str] | None:
    match = re.match(r"^(.+?)\s+(OVER|UNDER)\s+([A-Z0-9+]+)\s+([\d.]+)\s+\((\w+)\)(?:\s+\[id:([^\]]+)\])?", text)
    if not match:
        return None
    player, direction, stat, line, tier, projection_id = match.groups()
    return player.strip(), direction.upper(), stat.upper(), float(line), tier.upper(), str(projection_id or "").strip()


def _summary_tables(df: pd.DataFrame) -> dict[str, Any]:
    settled = df[pd.to_numeric(df.get("hit"), errors="coerce").notna()].copy()
    flagged = settled[settled["volatility_guard_flagged"]]
    unflagged = settled[~settled["volatility_guard_flagged"]]
    return {
        "rows": int(len(settled)),
        "flagged_rows": int(len(flagged)),
        "flagged_share": _ratio(len(flagged), len(settled)),
        "flagged_hit_rate": _mean(flagged.get("hit")),
        "unflagged_hit_rate": _mean(unflagged.get("hit")),
        "flagged_p_cal_mean": _mean(flagged.get("p_cal")),
        "unflagged_p_cal_mean": _mean(unflagged.get("p_cal")),
        "p_cal_brier": _brier(settled, "p_cal"),
        "p_select_volatility_brier": _brier(settled, "p_select_volatility"),
        "delta_mB": _delta_mb(settled, "p_cal", "p_select_volatility"),
    }


def _selected_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    settled = df[pd.to_numeric(df.get("hit"), errors="coerce").notna()].copy()
    flagged = settled[settled["volatility_guard_flagged"]]
    unflagged = settled[~settled["volatility_guard_flagged"]]
    return {
        "rows": int(len(settled)),
        "flagged_rows": int(len(flagged)),
        "flagged_share": _ratio(len(flagged), len(settled)),
        "flagged_hit_rate": _mean(flagged.get("hit")),
        "unflagged_hit_rate": _mean(unflagged.get("hit")),
        "flagged_hits": int(pd.to_numeric(flagged.get("hit"), errors="coerce").sum()) if not flagged.empty else 0,
        "flagged_misses": int((pd.to_numeric(flagged.get("hit"), errors="coerce") == 0).sum()) if not flagged.empty else 0,
        "p_cal_brier": _brier(settled, "p_cal"),
        "p_select_volatility_brier": _brier(settled, "p_select_volatility"),
        "delta_mB": _delta_mb(settled, "p_cal", "p_select_volatility"),
    }


def _guard_summary(df: pd.DataFrame, flag_col: str, penalty_col: str, candidate_col: str) -> dict[str, Any]:
    if df.empty or flag_col not in df.columns:
        return {}
    settled = df[pd.to_numeric(df.get("hit"), errors="coerce").notna()].copy()
    if settled.empty:
        return {"rows": 0}
    flags = settled[flag_col].astype(bool)
    flagged = settled[flags]
    unflagged = settled[~flags]
    return {
        "rows": int(len(settled)),
        "flagged_rows": int(len(flagged)),
        "flagged_share": _ratio(len(flagged), len(settled)),
        "flagged_hit_rate": _mean(flagged.get("hit")),
        "unflagged_hit_rate": _mean(unflagged.get("hit")),
        "flagged_hits": int(pd.to_numeric(flagged.get("hit"), errors="coerce").sum()) if not flagged.empty else 0,
        "flagged_misses": int((pd.to_numeric(flagged.get("hit"), errors="coerce") == 0).sum()) if not flagged.empty else 0,
        "avg_penalty": _mean(settled.get(penalty_col)),
        "flagged_avg_penalty": _mean(flagged.get(penalty_col)),
        "p_cal_brier": _brier(settled, "p_cal"),
        "candidate_brier": _brier(settled, candidate_col),
        "delta_mB": _delta_mb(settled, "p_cal", candidate_col),
    }


def _excess_fragility_recommendation(board: pd.DataFrame, selected: pd.DataFrame) -> dict[str, Any]:
    selected_summary = _guard_summary(selected, "excess_fragility_flagged", "excess_fragility_penalty", "p_select_excess_fragility")
    board_summary = _guard_summary(board, "excess_fragility_flagged", "excess_fragility_penalty", "p_select_excess_fragility")
    selected_delta = selected_summary.get("delta_mB")
    selected_flagged_rows = int(selected_summary.get("flagged_rows") or 0)
    selected_flagged_hit = selected_summary.get("flagged_hit_rate")
    selected_unflagged_hit = selected_summary.get("unflagged_hit_rate")
    selected_misses = int(selected_summary.get("flagged_misses") or 0)
    selected_hits = int(selected_summary.get("flagged_hits") or 0)

    reasons: list[str] = []
    if selected_flagged_rows >= 8:
        reasons.append(f"selected excess-fragile sample is usable ({selected_flagged_rows})")
    else:
        reasons.append(f"selected excess-fragile sample is thin ({selected_flagged_rows})")
    if selected_delta is not None and selected_delta < -0.5:
        reasons.append(f"selected p_select brier improves {selected_delta:.2f} mB")
    else:
        reasons.append(f"selected p_select brier does not clear gate ({selected_delta})")
    if selected_flagged_hit is not None and selected_unflagged_hit is not None and selected_flagged_hit <= selected_unflagged_hit - 0.08:
        reasons.append("selected excess-fragile legs materially underperform")
    else:
        reasons.append("selected excess-fragile legs do not materially underperform")
    if selected_misses > selected_hits:
        reasons.append(f"selected excess-fragile misses exceed hits ({selected_misses}>{selected_hits})")
    else:
        reasons.append(f"selected excess-fragile hits are not outweighed by misses ({selected_hits} hits, {selected_misses} misses)")

    promote = (
        selected_flagged_rows >= 8
        and selected_delta is not None
        and selected_delta < -0.5
        and selected_flagged_hit is not None
        and selected_unflagged_hit is not None
        and selected_flagged_hit <= selected_unflagged_hit - 0.08
        and selected_misses > selected_hits
    )
    return {
        "decision": "PROMOTE" if promote else "DENY",
        "guard": "excess_fragility_guard",
        "reasons": reasons,
        "board_delta_mB": board_summary.get("delta_mB"),
        "selected_delta_mB": selected_delta,
    }


def _fragility_exposure_summary(selected: pd.DataFrame) -> dict[str, Any]:
    if selected.empty or "slip_id" not in selected.columns:
        return {}

    cfg = FRAGILITY_EXPOSURE_CANDIDATE_CONFIG
    work = selected[pd.to_numeric(selected.get("hit"), errors="coerce").notna()].copy()
    if work.empty:
        return {}

    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    work["fg3m_over"] = (
        work.get("stat", pd.Series("", index=work.index)).astype(str).str.upper().eq("FG3M")
        & work.get("direction", pd.Series("", index=work.index)).astype(str).str.upper().eq("OVER")
    )
    work["excess_fragility_flagged"] = work.get("excess_fragility_flagged", pd.Series(False, index=work.index)).astype(bool)

    slips = (
        work.groupby(["slip_id", "source", "selected_product"], dropna=False)
        .agg(
            legs=("hit", "count"),
            slip_hit=("hit", "min"),
            leg_hit_rate=("hit", "mean"),
            low_line_fragile_legs=("excess_fragility_flagged", "sum"),
            fg3m_overs=("fg3m_over", "sum"),
        )
        .reset_index()
    )

    low_cap = int(cfg["max_low_line_fragile_legs_per_slip"])
    fg3m_cap = int(cfg["max_fg3m_overs_per_slip"])
    slips["violates_low_line_fragile_cap"] = slips["low_line_fragile_legs"] > low_cap
    slips["violates_fg3m_over_cap"] = slips["fg3m_overs"] > fg3m_cap
    slips["violates_any_cap"] = slips["violates_low_line_fragile_cap"] | slips["violates_fg3m_over_cap"]

    return {
        "candidate_config": cfg,
        "slips": int(len(slips)),
        "violates_low_line_fragile_cap": _cap_group_summary(slips, "violates_low_line_fragile_cap"),
        "violates_fg3m_over_cap": _cap_group_summary(slips, "violates_fg3m_over_cap"),
        "violates_any_cap": _cap_group_summary(slips, "violates_any_cap"),
        "decision": _fragility_exposure_recommendation(slips),
    }


def _cap_group_summary(slips: pd.DataFrame, flag_col: str) -> dict[str, Any]:
    flagged = slips[slips[flag_col].astype(bool)]
    clean = slips[~slips[flag_col].astype(bool)]
    return {
        "violating_slips": int(len(flagged)),
        "clean_slips": int(len(clean)),
        "violating_slip_hit_rate": _mean(flagged.get("slip_hit")),
        "clean_slip_hit_rate": _mean(clean.get("slip_hit")),
        "violating_leg_hit_rate": _mean(flagged.get("leg_hit_rate")),
        "clean_leg_hit_rate": _mean(clean.get("leg_hit_rate")),
    }


def _fragility_exposure_recommendation(slips: pd.DataFrame) -> dict[str, Any]:
    if slips.empty:
        return {"decision": "DENY", "reason": "no selected slips available"}

    decisions = []
    for flag_col, label in [
        ("violates_low_line_fragile_cap", "max_low_line_fragile_legs_per_slip"),
        ("violates_fg3m_over_cap", "max_fg3m_overs_per_slip"),
        ("violates_any_cap", "combined_caps"),
    ]:
        flagged = slips[slips[flag_col].astype(bool)]
        clean = slips[~slips[flag_col].astype(bool)]
        flagged_rate = _mean(flagged.get("slip_hit"))
        clean_rate = _mean(clean.get("slip_hit"))
        promote = (
            len(flagged) >= 5
            and flagged_rate is not None
            and clean_rate is not None
            and flagged_rate <= clean_rate - 0.15
        )
        decisions.append(
            {
                "cap": label,
                "decision": "PROMOTE" if promote else "DENY",
                "violating_slips": int(len(flagged)),
                "violating_slip_hit_rate": flagged_rate,
                "clean_slip_hit_rate": clean_rate,
            }
        )

    return {"caps": decisions}


def _risk_flag_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    work["flag_group"] = np.where(work["volatility_guard_flagged"], work["volatility_guard_flags"].replace("", "flagged_unknown"), "unflagged")
    return (
        work.groupby("flag_group", dropna=False)
        .agg(
            legs=("hit", "count"),
            hit_rate=("hit", "mean"),
            avg_p_cal=("p_cal", "mean"),
            avg_penalty=("volatility_guard_penalty", "mean"),
            avg_minutes_cv=("minutes_cv", "mean"),
            avg_rate_cv=("rate_cv", "mean"),
            avg_l10_zero_rate=("l10_zero_rate", "mean"),
        )
        .reset_index()
        .sort_values(["legs", "avg_penalty"], ascending=[False, False])
    )


def _line_bucket_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    return (
        work.groupby(["line_bucket", "direction"], dropna=False)
        .agg(
            legs=("hit", "count"),
            hit_rate=("hit", "mean"),
            avg_p_cal=("p_cal", "mean"),
            avg_penalty=("volatility_guard_penalty", "mean"),
            flagged_share=("volatility_guard_flagged", "mean"),
        )
        .reset_index()
        .sort_values(["flagged_share", "legs"], ascending=[False, False])
    )


def _recommendation(board: pd.DataFrame, selected: pd.DataFrame) -> dict[str, Any]:
    board_summary = _summary_tables(board)
    selected_summary = _selected_summary(selected)
    selected_delta = selected_summary.get("delta_mB")
    selected_flagged_rows = int(selected_summary.get("flagged_rows") or 0)
    selected_flagged_hit = selected_summary.get("flagged_hit_rate")
    selected_unflagged_hit = selected_summary.get("unflagged_hit_rate")
    selected_misses = int(selected_summary.get("flagged_misses") or 0)
    selected_hits = int(selected_summary.get("flagged_hits") or 0)

    promote = False
    reasons: list[str] = []
    if selected_flagged_rows >= 8:
        reasons.append(f"selected flagged sample is usable ({selected_flagged_rows})")
    else:
        reasons.append(f"selected flagged sample is thin ({selected_flagged_rows})")
    if selected_delta is not None and selected_delta < -0.5:
        reasons.append(f"selected p_select brier improves {selected_delta:.2f} mB")
    else:
        reasons.append(f"selected p_select brier does not clear gate ({selected_delta})")
    if selected_flagged_hit is not None and selected_unflagged_hit is not None and selected_flagged_hit <= selected_unflagged_hit - 0.08:
        reasons.append("flagged selected legs materially underperform unflagged")
    else:
        reasons.append("flagged selected legs do not materially underperform unflagged")
    if selected_misses > selected_hits:
        reasons.append(f"flagged selected misses exceed hits ({selected_misses}>{selected_hits})")
    else:
        reasons.append(f"flagged selected hits are not outweighed by misses ({selected_hits} hits, {selected_misses} misses)")

    promote = (
        selected_flagged_rows >= 8
        and selected_delta is not None
        and selected_delta < -0.5
        and selected_flagged_hit is not None
        and selected_unflagged_hit is not None
        and selected_flagged_hit <= selected_unflagged_hit - 0.08
        and selected_misses > selected_hits
    )
    return {
        "decision": "PROMOTE" if promote else "DENY",
        "guard": "low_line_volatility_guard",
        "candidate_config": {
            "enabled": True,
            "max_total_penalty": 0.12,
            "low_line_zero_rate_penalty": 0.06,
            "low_line_minutes_cv_penalty": 0.04,
            "low_line_rate_cv_penalty": 0.04,
            "fg3m_low_line_penalty": 0.04,
            "rotation_under_18_low_line_penalty": 0.05,
        },
        "reasons": reasons,
        "board_delta_mB": board_summary.get("delta_mB"),
        "selected_delta_mB": selected_delta,
    }


def _print_report(summary: dict[str, Any], summary_out: Path) -> None:
    rec = summary["recommendation"]
    board = summary["board_summary"]
    selected = summary["selected_summary"]
    excess = summary.get("excess_fragility_summary", {})
    exposure = summary.get("fragility_exposure_summary", {})
    print("\nLOW-LINE VOLATILITY AUDIT")
    print(f"  decision: {rec['decision']}")
    print(f"  board rows: {board.get('rows')} | flagged: {board.get('flagged_rows')} ({board.get('flagged_share'):.3f})")
    print(f"  board hit: flagged={board.get('flagged_hit_rate')} unflagged={board.get('unflagged_hit_rate')}")
    print(f"  board p_select delta: {board.get('delta_mB')} mB")
    if selected:
        print(f"  selected rows: {selected.get('rows')} | flagged: {selected.get('flagged_rows')} ({selected.get('flagged_share'):.3f})")
        print(f"  selected hit: flagged={selected.get('flagged_hit_rate')} unflagged={selected.get('unflagged_hit_rate')}")
        print(f"  selected p_select delta: {selected.get('delta_mB')} mB")
        print(f"  selected flagged hits/misses: {selected.get('flagged_hits')}/{selected.get('flagged_misses')}")
    print("  reasons:")
    for reason in rec["reasons"]:
        print(f"    - {reason}")
    if excess:
        ex_rec = excess.get("decision", {})
        ex_board = excess.get("board", {})
        ex_selected = excess.get("selected", {})
        print("\nEXCESS-ZERO FRAGILITY CANDIDATE")
        print(f"  decision: {ex_rec.get('decision')}")
        print(f"  board flagged: {ex_board.get('flagged_rows')} ({ex_board.get('flagged_share')}) | delta: {ex_board.get('delta_mB')} mB")
        if ex_selected:
            print(f"  selected flagged: {ex_selected.get('flagged_rows')} ({ex_selected.get('flagged_share')}) | delta: {ex_selected.get('delta_mB')} mB")
            print(f"  selected hit: flagged={ex_selected.get('flagged_hit_rate')} unflagged={ex_selected.get('unflagged_hit_rate')}")
            print(f"  selected flagged hits/misses: {ex_selected.get('flagged_hits')}/{ex_selected.get('flagged_misses')}")
        for reason in ex_rec.get("reasons", []):
            print(f"    - {reason}")
    if exposure:
        print("\nFRAGILITY EXPOSURE CANDIDATE")
        print(f"  slips audited: {exposure.get('slips')}")
        for cap in (exposure.get("decision", {}) or {}).get("caps", []):
            print(
                "  "
                f"{cap.get('cap')}: {cap.get('decision')} | "
                f"violating={cap.get('violating_slips')} | "
                f"violating_hit={cap.get('violating_slip_hit_rate')} | "
                f"clean_hit={cap.get('clean_slip_hit_rate')}"
            )
    print(f"  summary: {_rel(summary_out)}")


def _brier(df: pd.DataFrame, p_col: str) -> float | None:
    if df.empty or p_col not in df.columns or "hit" not in df.columns:
        return None
    p = pd.to_numeric(df[p_col], errors="coerce")
    y = pd.to_numeric(df["hit"], errors="coerce")
    mask = p.notna() & y.notna()
    if not mask.any():
        return None
    return float(((p[mask] - y[mask]) ** 2).mean())


def _delta_mb(df: pd.DataFrame, base_col: str, cand_col: str) -> float | None:
    b0 = _brier(df, base_col)
    b1 = _brier(df, cand_col)
    if b0 is None or b1 is None:
        return None
    return float((b1 - b0) * 1000.0)


def _mean(x: Any) -> float | None:
    if x is None:
        return None
    s = pd.to_numeric(x, errors="coerce")
    if not isinstance(s, pd.Series):
        s = pd.Series(s)
    if s.notna().sum() == 0:
        return None
    return float(s.mean())


def _std(x: Any) -> float | None:
    if x is None:
        return None
    s = pd.to_numeric(x, errors="coerce")
    if not isinstance(s, pd.Series):
        s = pd.Series(s)
    if s.notna().sum() == 0:
        return None
    return float(s.std(ddof=0))


def _min(x: Any) -> float | None:
    if x is None:
        return None
    s = pd.to_numeric(x, errors="coerce")
    if not isinstance(s, pd.Series):
        s = pd.Series(s)
    if s.notna().sum() == 0:
        return None
    return float(s.min())


def _float(x: Any) -> float | None:
    try:
        if x is None or pd.isna(x):
            return None
        v = float(x)
        if not math.isfinite(v):
            return None
        return v
    except Exception:
        return None


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return float(num / den)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return [_jsonable(r) for r in df.to_dict(orient="records")]


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_jsonable(v) for v in x]
    if isinstance(x, tuple):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        v = float(x)
        return None if not math.isfinite(v) else v
    if isinstance(x, float):
        return None if not math.isfinite(x) else x
    if pd.isna(x):
        return None
    return x


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())

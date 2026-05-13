#!/usr/bin/env python3
"""Audit recent CAT gate failures against selected-leg process quality.

This report is intentionally narrower than a full trainer report. It asks:
- Did CAT improve or worsen the selected legs versus p_for_cal?
- Were misses concentrated in positive CAT residual buckets?
- Did selected misses have strong last-10 hit profiles?
- Did misses look like role/minute failure, injury uncertainty, or normal variance?
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "output" / "runs"
GAMELOGS = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"


@dataclass(frozen=True)
class SelectedLeg:
    run_id: str
    source_file: str
    product: str
    slip_label: str
    slip_rank: int
    n_legs: int
    player: str
    stat: str
    direction: str
    tier: str
    line: float
    projection_id: str
    slip_hit_prob: float | None
    slip_ev: float | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CAT gate selected-tail failures.")
    parser.add_argument(
        "--runs",
        nargs="+",
        default=["20260510_142919", "20260511_080241", "20260511_143242", "20260511_173253"],
        help="Run IDs to audit.",
    )
    parser.add_argument("--top-n", type=int, default=1, help="Top N recommended slips per leg-count file.")
    parser.add_argument("--out-dir", default="logs/cat_gate_tail_audit", help="Output directory.")
    args = parser.parse_args()

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    gamelogs = _load_gamelogs()
    selected_rows: list[dict[str, Any]] = []
    board_rows: list[dict[str, Any]] = []
    slip_rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for run_id in args.runs:
        run_dir = RUNS_DIR / run_id
        if not run_dir.is_dir():
            print(f"[SKIP] missing run dir: {run_dir}")
            continue
        eval_path = run_dir / "eval_legs.csv"
        scored_path = run_dir / "scored_legs_deduped.csv"
        if not eval_path.exists() or not scored_path.exists():
            print(f"[SKIP] missing eval/scored files: {run_id}")
            continue

        eval_df = _normalize_eval(pd.read_csv(eval_path, low_memory=False))
        selected = _load_selected_legs(run_dir, top_n=args.top_n)
        board_rows.append(_board_summary(run_id, eval_df))
        slip_rows.extend(_score_slips(selected, eval_df))

        for leg in selected:
            match = _match_leg(leg, eval_df)
            if match is None:
                unmatched.append(leg.__dict__.copy())
                continue
            row = _enrich_leg(leg, match, gamelogs)
            selected_rows.append(row)

    selected_df = pd.DataFrame(selected_rows)
    board_df = pd.DataFrame(board_rows)
    slip_df = pd.DataFrame(slip_rows)

    selected_csv = out_dir / "selected_legs.csv"
    board_csv = out_dir / "board_summary.csv"
    slip_csv = out_dir / "slip_summary.csv"
    selected_df.to_csv(selected_csv, index=False)
    board_df.to_csv(board_csv, index=False)
    slip_df.to_csv(slip_csv, index=False)

    payload = {
        "runs": args.runs,
        "top_n": args.top_n,
        "board_summary": _records(board_df),
        "selected_summary": _selected_summary(selected_df),
        "slip_summary": _records(_group_slips(slip_df)),
        "cat_delta_buckets": _records(_cat_delta_buckets(selected_df)),
        "miss_classification": _records(_miss_classification_summary(selected_df)),
        "player_exposure": _records(_player_exposure(selected_df).head(30)),
        "worst_misses": _records(_worst_misses(selected_df).head(40)),
        "strong_l10_misses": _records(_strong_l10_misses(selected_df).head(40)),
        "unmatched_count": len(unmatched),
    }

    json_out = out_dir / "summary.json"
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    _print_report(payload, selected_csv, board_csv, slip_csv, json_out)
    return 0


def _load_gamelogs() -> pd.DataFrame:
    df = pd.read_csv(GAMELOGS, low_memory=False)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df["player_key"] = df["player"].astype(str).str.strip().str.lower()
    for col in ["minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["game_date", "player_key"]).sort_values("game_date")


def _normalize_eval(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["player", "stat", "direction", "tier"]:
        if col in out.columns:
            out[col] = out[col].astype(str).str.strip()
    for col in ["stat", "direction", "tier"]:
        if col in out.columns:
            out[col] = out[col].str.upper()
    if "line" in out.columns:
        out["line"] = pd.to_numeric(out["line"], errors="coerce")
    for col in ["projection_id", "source_projection_id"]:
        if col in out.columns:
            out[f"{col}_str"] = out[col].astype(str).str.strip()
        else:
            out[f"{col}_str"] = ""
    return out


def _load_selected_legs(run_dir: Path, *, top_n: int) -> list[SelectedLeg]:
    legs: list[SelectedLeg] = []
    for path in _selected_files(run_dir):
        df = pd.read_csv(path, low_memory=False)
        if path.name == "marketed_slips.csv":
            legs.extend(_load_marketed(run_dir.name, path, df))
        else:
            legs.extend(_load_recommended(run_dir.name, path, df, top_n=top_n))
    return legs


def _selected_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    marketed = run_dir / "marketed_slips.csv"
    if marketed.exists():
        files.append(marketed)
    for n in [3, 4, 5]:
        p = run_dir / f"recommended_{n}leg.csv"
        if p.exists():
            files.append(p)
    for family in ["System", "Windfall"]:
        for n in [3, 4, 5]:
            p = run_dir / family / f"recommended_{n}leg.csv"
            if p.exists():
                files.append(p)
    return files


def _load_marketed(run_id: str, path: Path, df: pd.DataFrame) -> list[SelectedLeg]:
    required = {"slip", "player", "stat", "direction", "tier", "line"}
    if not required <= set(df.columns):
        return []
    legs: list[SelectedLeg] = []
    for rank, (slip_label, group) in enumerate(df.groupby("slip", sort=False), start=1):
        n_legs = len(group)
        for _, row in group.iterrows():
            legs.append(
                SelectedLeg(
                    run_id=run_id,
                    source_file=_rel(path),
                    product="marketed",
                    slip_label=str(slip_label),
                    slip_rank=rank,
                    n_legs=n_legs,
                    player=str(row["player"]).strip(),
                    stat=str(row["stat"]).strip().upper(),
                    direction=str(row["direction"]).strip().upper(),
                    tier=str(row["tier"]).strip().upper(),
                    line=float(row["line"]),
                    projection_id=str(row.get("source_projection_id") or row.get("projection_id") or "").strip(),
                    slip_hit_prob=_float(row.get("hit_prob")),
                    slip_ev=_float(row.get("ev")),
                )
            )
    return legs


def _load_recommended(run_id: str, path: Path, df: pd.DataFrame, *, top_n: int) -> list[SelectedLeg]:
    legs: list[SelectedLeg] = []
    n_match = re.search(r"recommended_(\d+)leg", path.name)
    n_legs = int(n_match.group(1)) if n_match else 0
    product = path.parent.name if path.parent.name in {"System", "Windfall"} else "recommended"
    for rank, (_, row) in enumerate(df.head(top_n).iterrows(), start=1):
        for text in _leg_texts(row):
            parsed = _parse_leg(text)
            if parsed is None:
                continue
            player, direction, stat, line, tier, projection_id = parsed
            legs.append(
                SelectedLeg(
                    run_id=run_id,
                    source_file=_rel(path),
                    product=product,
                    slip_label=f"{n_legs}-leg",
                    slip_rank=rank,
                    n_legs=n_legs,
                    player=player,
                    stat=stat,
                    direction=direction,
                    tier=tier,
                    line=line,
                    projection_id=projection_id,
                    slip_hit_prob=_float(row.get("hit_prob")),
                    slip_ev=_float(row.get("ev_mult") if "ev_mult" in row else row.get("ev")),
                )
            )
    return legs


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


def _match_leg(leg: SelectedLeg, eval_df: pd.DataFrame) -> pd.Series | None:
    if leg.projection_id:
        match = eval_df[
            (eval_df["projection_id_str"] == leg.projection_id)
            | (eval_df["source_projection_id_str"] == leg.projection_id)
        ]
        if len(match):
            return match.iloc[0]
    player_key = leg.player.strip().lower()
    match = eval_df[
        (eval_df["player"].astype(str).str.strip().str.lower() == player_key)
        & (eval_df["stat"] == leg.stat)
        & (eval_df["direction"] == leg.direction)
        & (eval_df["tier"] == leg.tier)
        & ((eval_df["line"] - leg.line).abs() < 1e-9)
    ]
    if len(match):
        return match.iloc[0]
    return None


def _enrich_leg(leg: SelectedLeg, match: pd.Series, gamelogs: pd.DataFrame) -> dict[str, Any]:
    row = leg.__dict__.copy()
    for col in [
        "team",
        "opp",
        "game_date",
        "actual",
        "hit",
        "minutes",
        "pts",
        "reb",
        "ast",
        "fg3m",
        "p",
        "p_adj",
        "p_for_cal",
        "p_cal",
        "p_catboost",
        "p_catboost_residual",
        "p_cal_marketed",
        "min_mean",
        "min_std",
        "rate_mean",
        "rate_std",
        "games_used",
        "q_blowout",
        "fragility",
        "role_ctx_outs_used",
        "role_ctx_reason",
        "role_ctx_bump",
        "role_ctx_mult",
        "zero_dnp_mult",
        "external_prior_score",
        "external_prior_n",
        "is_questionable",
        "q_out_frac",
        "actual_delta",
        "actual_abs_delta",
        "eval_match_quality",
    ]:
        row[col] = _jsonable(match.get(col))

    p_for_cal = _float(row.get("p_for_cal"))
    p_cal = _float(row.get("p_cal"))
    p_cat = _float(row.get("p_catboost"))
    row["cat_delta"] = (p_cat - p_for_cal) if p_cat is not None and p_for_cal is not None else None
    row["cal_delta"] = (p_cal - p_for_cal) if p_cal is not None and p_for_cal is not None else None
    row.update(_l10_context(row, gamelogs))
    row.update(_classify(row))
    return row


def _l10_context(row: dict[str, Any], gamelogs: pd.DataFrame) -> dict[str, Any]:
    game_date = pd.to_datetime(row.get("game_date"), errors="coerce")
    player = str(row.get("player", "")).strip().lower()
    if pd.isna(game_date) or not player:
        return {}
    prior = gamelogs[(gamelogs["player_key"] == player) & (gamelogs["game_date"] < game_date)].tail(10).copy()
    if prior.empty:
        return {"l10_n": 0}
    stat_values = _stat_values(prior, str(row.get("stat", "")).upper())
    line = _float(row.get("line"))
    direction = str(row.get("direction", "")).upper()
    hits = pd.Series(dtype=float)
    if line is not None:
        if direction == "OVER":
            hits = (stat_values > line).astype(float)
        elif direction == "UNDER":
            hits = (stat_values < line).astype(float)
    return {
        "l10_n": int(len(prior)),
        "l10_stat_avg": _series_float(stat_values.mean()),
        "l10_stat_median": _series_float(stat_values.median()),
        "l10_stat_min": _series_float(stat_values.min()),
        "l10_stat_max": _series_float(stat_values.max()),
        "l10_hit_rate": _series_float(hits.mean()) if not hits.empty else None,
        "l10_last3_hit_rate": _series_float(hits.tail(3).mean()) if not hits.empty else None,
        "l10_zero_count": int((stat_values == 0).sum()),
        "l10_minutes_avg": _series_float(prior["minutes"].mean()) if "minutes" in prior.columns else None,
        "l10_minutes_min": _series_float(prior["minutes"].min()) if "minutes" in prior.columns else None,
    }


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


def _classify(row: dict[str, Any]) -> dict[str, Any]:
    hit = _float(row.get("hit"))
    actual = _float(row.get("actual"))
    minutes = _float(row.get("minutes"))
    min_mean = _float(row.get("min_mean"))
    min_std = _float(row.get("min_std"))
    l10_hit = _float(row.get("l10_hit_rate"))
    l10_avg = _float(row.get("l10_stat_avg"))
    cat_delta = _float(row.get("cat_delta"))
    p_for_cal = _float(row.get("p_for_cal"))
    p_cal = _float(row.get("p_cal"))
    q_out_frac = _float(row.get("q_out_frac")) or 0.0
    is_questionable = (_float(row.get("is_questionable")) or 0.0) > 0.0

    minute_shortfall = (
        minutes is not None
        and min_mean is not None
        and min_std is not None
        and minutes < min_mean - max(3.0, min_std)
    )
    strong_l10 = l10_hit is not None and l10_hit >= 0.70
    l10_line_edge = l10_avg is not None and _float(row.get("line")) is not None and l10_avg > float(row["line"])
    cat_boosted = cat_delta is not None and cat_delta >= 0.03
    high_conf = p_cal is not None and p_cal >= 0.70
    pre_cat_high = p_for_cal is not None and p_for_cal >= 0.70
    zero_actual_over = str(row.get("direction", "")).upper() == "OVER" and actual == 0.0

    reason = "not_miss"
    if hit == 0.0:
        if is_questionable or q_out_frac > 0:
            reason = "injury_uncertainty"
        elif minute_shortfall:
            reason = "minute_shortfall"
        elif zero_actual_over and strong_l10:
            reason = "zero_output_variance"
        elif cat_boosted and not pre_cat_high:
            reason = "cat_boosted_into_tail"
        elif strong_l10 or l10_line_edge:
            reason = "solid_l10_bad_outcome"
        elif high_conf:
            reason = "high_confidence_miss"
        else:
            reason = "ordinary_miss"

    return {
        "minute_shortfall": bool(minute_shortfall),
        "strong_l10": bool(strong_l10),
        "l10_line_edge": bool(l10_line_edge),
        "cat_boosted": bool(cat_boosted),
        "high_confidence": bool(high_conf),
        "pre_cat_high": bool(pre_cat_high),
        "zero_actual_over": bool(zero_actual_over),
        "miss_reason": reason,
    }


def _board_summary(run_id: str, df: pd.DataFrame) -> dict[str, Any]:
    settled = df[pd.to_numeric(df.get("hit"), errors="coerce").notna()].copy()
    row: dict[str, Any] = {"run_id": run_id, "settled": int(len(settled)), "hit_rate": _mean(settled.get("hit"))}
    h = pd.to_numeric(settled.get("hit"), errors="coerce")
    for col in ["p", "p_adj", "p_for_cal", "p_catboost", "p_cal"]:
        if col not in settled.columns:
            continue
        p = pd.to_numeric(settled[col], errors="coerce")
        mask = p.notna() & h.notna()
        if mask.any():
            row[f"{col}_mean"] = float(p[mask].mean())
            row[f"{col}_brier"] = float(((p[mask] - h[mask]) ** 2).mean())
    return row


def _score_slips(selected: list[SelectedLeg], eval_df: pd.DataFrame) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int, int], list[SelectedLeg]] = {}
    for leg in selected:
        grouped.setdefault((leg.run_id, leg.source_file, leg.slip_rank, leg.n_legs), []).append(leg)
    rows: list[dict[str, Any]] = []
    for (run_id, source_file, slip_rank, n_legs), legs in grouped.items():
        hits = []
        p_vals = []
        cat_deltas = []
        for leg in legs:
            match = _match_leg(leg, eval_df)
            if match is None:
                continue
            hit = _float(match.get("hit"))
            if hit is not None:
                hits.append(hit)
            p = _float(match.get("p_cal"))
            pf = _float(match.get("p_for_cal"))
            pc = _float(match.get("p_catboost"))
            if p is not None:
                p_vals.append(p)
            if pf is not None and pc is not None:
                cat_deltas.append(pc - pf)
        rows.append(
            {
                "run_id": run_id,
                "source_file": source_file,
                "slip_rank": slip_rank,
                "n_legs": n_legs,
                "settled": len(hits),
                "hits": int(sum(hits)),
                "won": int(len(hits) == n_legs and sum(hits) == n_legs),
                "slip_hit_prob": legs[0].slip_hit_prob,
                "slip_ev": legs[0].slip_ev,
                "avg_p_cal": float(np.mean(p_vals)) if p_vals else None,
                "avg_cat_delta": float(np.mean(cat_deltas)) if cat_deltas else None,
            }
        )
    return rows


def _selected_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    hit = pd.to_numeric(df["hit"], errors="coerce")
    out: dict[str, Any] = {"legs": int(hit.notna().sum()), "hit_rate": _mean(hit)}
    for col in ["p_for_cal", "p_catboost", "p_cal"]:
        p = pd.to_numeric(df.get(col), errors="coerce")
        mask = p.notna() & hit.notna()
        if mask.any():
            out[f"{col}_mean"] = float(p[mask].mean())
            out[f"{col}_brier"] = float(((p[mask] - hit[mask]) ** 2).mean())
            out[f"{col}_gap"] = float(p[mask].mean() - hit[mask].mean())
    if "cat_delta" in df.columns:
        out["avg_cat_delta"] = _mean(df["cat_delta"])
        out["positive_cat_delta_share"] = _mean(pd.to_numeric(df["cat_delta"], errors="coerce") > 0)
    return out


def _group_slips(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    grouped = (
        df.groupby(["source_file", "n_legs"], dropna=False)
        .agg(
            slips=("won", "count"),
            wins=("won", "sum"),
            legs=("settled", "sum"),
            hits=("hits", "sum"),
            avg_p_cal=("avg_p_cal", "mean"),
            avg_cat_delta=("avg_cat_delta", "mean"),
        )
        .reset_index()
    )
    grouped["win_rate"] = grouped["wins"] / grouped["slips"]
    grouped["leg_hit_rate"] = grouped["hits"] / grouped["legs"]
    return grouped.sort_values(["source_file", "n_legs"])


def _cat_delta_buckets(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    work["cat_delta"] = pd.to_numeric(work["cat_delta"], errors="coerce")
    work["bucket"] = pd.cut(
        work["cat_delta"],
        bins=[-1.0, -0.08, -0.03, 0.0, 0.03, 0.08, 1.0],
        labels=["<=-0.08", "-0.08..-0.03", "-0.03..0", "0..0.03", "0.03..0.08", ">0.08"],
    )
    return (
        work.groupby(["bucket"], observed=False)
        .agg(legs=("hit", "count"), hit_rate=("hit", "mean"), avg_cat_delta=("cat_delta", "mean"))
        .reset_index()
    )


def _miss_classification_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    misses = df[pd.to_numeric(df["hit"], errors="coerce") == 0].copy()
    if misses.empty:
        return pd.DataFrame()
    return (
        misses.groupby("miss_reason", dropna=False)
        .agg(
            misses=("hit", "count"),
            avg_p_cal=("p_cal", "mean"),
            avg_p_for_cal=("p_for_cal", "mean"),
            avg_cat_delta=("cat_delta", "mean"),
            avg_l10_hit_rate=("l10_hit_rate", "mean"),
        )
        .reset_index()
        .sort_values("misses", ascending=False)
    )


def _player_exposure(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
    grouped = (
        work.groupby(["player", "stat", "direction", "tier", "line"], dropna=False)
        .agg(
            exposures=("hit", "count"),
            hits=("hit", "sum"),
            avg_p_cal=("p_cal", "mean"),
            avg_p_for_cal=("p_for_cal", "mean"),
            avg_cat_delta=("cat_delta", "mean"),
            avg_l10_hit_rate=("l10_hit_rate", "mean"),
            actuals=("actual", lambda s: sorted({str(x) for x in s if pd.notna(x)})),
            reasons=("miss_reason", lambda s: sorted({str(x) for x in s if str(x) != "not_miss"})),
        )
        .reset_index()
    )
    grouped["misses"] = grouped["exposures"] - grouped["hits"]
    grouped["hit_rate"] = grouped["hits"] / grouped["exposures"]
    return grouped.sort_values(["misses", "avg_p_cal"], ascending=[False, False])


def _worst_misses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    misses = df[pd.to_numeric(df["hit"], errors="coerce") == 0].copy()
    if misses.empty:
        return pd.DataFrame()
    cols = [
        "run_id",
        "source_file",
        "player",
        "stat",
        "direction",
        "tier",
        "line",
        "actual",
        "minutes",
        "p_for_cal",
        "p_catboost",
        "p_cal",
        "cat_delta",
        "l10_hit_rate",
        "l10_stat_avg",
        "l10_minutes_avg",
        "min_mean",
        "is_questionable",
        "q_out_frac",
        "role_ctx_outs_used",
        "role_ctx_reason",
        "miss_reason",
    ]
    return misses.sort_values("p_cal", ascending=False)[[c for c in cols if c in misses.columns]]


def _strong_l10_misses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    misses = df[(pd.to_numeric(df["hit"], errors="coerce") == 0) & (pd.to_numeric(df.get("l10_hit_rate"), errors="coerce") >= 0.70)]
    return _worst_misses(misses)


def _print_report(payload: dict[str, Any], selected_csv: Path, board_csv: Path, slip_csv: Path, json_out: Path) -> None:
    print("\n=== BOARD SUMMARY ===")
    print(pd.DataFrame(payload["board_summary"]).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\n=== SELECTED SUMMARY ===")
    print(json.dumps(payload["selected_summary"], indent=2, sort_keys=True))
    print("\n=== SLIP SUMMARY ===")
    print(pd.DataFrame(payload["slip_summary"]).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\n=== CAT DELTA BUCKETS ===")
    print(pd.DataFrame(payload["cat_delta_buckets"]).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\n=== MISS CLASSIFICATION ===")
    print(pd.DataFrame(payload["miss_classification"]).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\n=== TOP EXPOSURE MISSES ===")
    print(pd.DataFrame(payload["player_exposure"]).head(15).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\n=== STRONG L10 MISSES ===")
    print(pd.DataFrame(payload["strong_l10_misses"]).head(20).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\nWrote:")
    print(f"  {selected_csv}")
    print(f"  {board_csv}")
    print(f"  {slip_csv}")
    print(f"  {json_out}")


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out):
        return None
    return out


def _mean(value: Any) -> float | None:
    if value is None:
        return None
    numeric = pd.to_numeric(value, errors="coerce")
    if not numeric.notna().any():
        return None
    return float(numeric.mean())


def _series_float(value: Any) -> float | None:
    return _float(value)


def _jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records"))


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())

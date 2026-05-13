#!/usr/bin/env python3
"""Diagnose recent Atlas slip failures against truth-backed eval legs."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "output" / "runs"


@dataclass(frozen=True)
class SlipLeg:
    run_id: str
    date: str
    product: str
    family: str
    slip_label: str
    slip_rank: int
    n_legs: int
    player: str
    stat: str
    direction: str
    tier: str
    line: float
    projection_id: str
    displayed_p: float | None
    slip_hit_prob: float | None
    slip_ev: float | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose recent slip results")
    parser.add_argument("--dates", nargs="*", help="Dates as YYYY-MM-DD. Defaults to yesterday and day before.")
    parser.add_argument("--runs", nargs="*", help="Specific run IDs to analyze")
    parser.add_argument("--top-n", type=int, default=1, help="Top N recommended slips per family/leg count")
    parser.add_argument("--json-out", help="Optional JSON output path")
    args = parser.parse_args()

    dates = [date.fromisoformat(value) for value in args.dates] if args.dates else _default_dates()
    run_dirs = _resolve_runs(dates=dates, run_ids=args.runs or [])
    if not run_dirs:
        raise SystemExit("No runs with eval_legs.csv and scored_legs_deduped.csv found.")

    full_board_rows: list[dict[str, Any]] = []
    selected_legs: list[dict[str, Any]] = []
    slip_rows: list[dict[str, Any]] = []
    unmatched_legs: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        eval_df = pd.read_csv(run_dir / "eval_legs.csv", low_memory=False)
        scored_df = pd.read_csv(run_dir / "scored_legs_deduped.csv", low_memory=False)
        eval_df = _normalize_eval(eval_df)
        scored_df = _normalize_eval(scored_df)
        run_id = run_dir.name
        run_date = _run_date(run_id)
        full_board_rows.append(_full_board_summary(run_id, run_date, eval_df))

        legs = _load_selected_slip_legs(run_dir, top_n=args.top_n)
        for leg in legs:
            match = _match_eval_leg(leg, eval_df)
            if match is None:
                row = leg.__dict__.copy()
                row["reason"] = "no_eval_match"
                unmatched_legs.append(row)
                continue
            enriched = _selected_leg_row(leg, match)
            selected_legs.append(enriched)

        slip_rows.extend(_score_slips(run_id, run_date, legs, eval_df))

    board_df = pd.DataFrame(full_board_rows)
    leg_df = pd.DataFrame(selected_legs)
    slip_df = pd.DataFrame(slip_rows)
    unmatched_df = pd.DataFrame(unmatched_legs)

    payload = {
        "dates": [value.isoformat() for value in dates],
        "run_count": len(run_dirs),
        "runs": [run.name for run in run_dirs],
        "full_board": full_board_rows,
        "slip_summary": _df_records(_slip_summary(slip_df)),
        "selected_leg_summary": _selected_leg_summary(leg_df),
        "unmatched_leg_count": int(len(unmatched_df)),
        "worst_missed_legs": _df_records(_worst_missed_legs(leg_df)),
        "high_confidence_misses": _df_records(_high_confidence_misses(leg_df)),
        "by_stat_tier_direction": _df_records(_group_leg_performance(leg_df, ["stat", "tier", "direction"])),
        "by_product_family": _df_records(_group_slip_performance(slip_df, ["product", "family", "n_legs"])),
    }

    _print_report(board_df, leg_df, slip_df, payload)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nWrote JSON: {out_path}")

    return 0


def _default_dates() -> list[date]:
    today = date.today()
    return [today - timedelta(days=2), today - timedelta(days=1)]


def _resolve_runs(*, dates: list[date], run_ids: list[str]) -> list[Path]:
    runs: list[Path] = []
    if run_ids:
        candidates = [RUNS_DIR / run_id for run_id in run_ids]
    else:
        prefixes = {value.strftime("%Y%m%d") for value in dates}
        candidates = [path for path in RUNS_DIR.iterdir() if path.is_dir() and path.name[:8] in prefixes]

    for run_dir in sorted(candidates, key=lambda path: path.name):
        if (run_dir / "eval_legs.csv").exists() and (run_dir / "scored_legs_deduped.csv").exists():
            runs.append(run_dir)
    return runs


def _run_date(run_id: str) -> str:
    return f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"


def _normalize_eval(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("player", "stat", "direction", "tier"):
        if col in out.columns:
            out[col] = out[col].astype(str).str.strip()
    if "tier" in out.columns:
        out["tier"] = out["tier"].str.upper()
    if "direction" in out.columns:
        out["direction"] = out["direction"].str.upper()
    if "stat" in out.columns:
        out["stat"] = out["stat"].str.upper()
    if "line" in out.columns:
        out["line"] = pd.to_numeric(out["line"], errors="coerce")
    if "hit" in out.columns:
        out["hit"] = pd.to_numeric(out["hit"], errors="coerce")
    if "source_projection_id" in out.columns:
        out["source_projection_id_str"] = out["source_projection_id"].astype(str).str.strip()
    else:
        out["source_projection_id_str"] = ""
    if "projection_id" in out.columns:
        out["projection_id_str"] = out["projection_id"].astype(str).str.strip()
    else:
        out["projection_id_str"] = ""
    return out


def _full_board_summary(run_id: str, run_date: str, eval_df: pd.DataFrame) -> dict[str, Any]:
    settled = eval_df[pd.to_numeric(eval_df.get("hit"), errors="coerce").notna()].copy()
    row: dict[str, Any] = {
        "run_id": run_id,
        "date": run_date,
        "rows": int(len(eval_df)),
        "settled_rows": int(len(settled)),
        "hit_rate": _mean(settled.get("hit")),
    }
    for col in ("p", "p_adj", "p_for_cal", "p_cal", "p_catboost", "p_cal_marketed"):
        if col in settled.columns:
            p = pd.to_numeric(settled[col], errors="coerce")
            h = pd.to_numeric(settled["hit"], errors="coerce")
            mask = p.notna() & h.notna()
            if mask.any():
                row[f"{col}_mean"] = float(p[mask].mean())
                row[f"{col}_brier"] = float(((p[mask] - h[mask]) ** 2).mean())
    return row


def _load_selected_slip_legs(run_dir: Path, *, top_n: int) -> list[SlipLeg]:
    legs: list[SlipLeg] = []
    run_id = run_dir.name
    run_date = _run_date(run_id)
    legs.extend(_load_marketed_legs(run_dir, run_id, run_date))
    for family in ("System", "Windfall"):
        for n_legs in (3, 4, 5):
            legs.extend(_load_recommended_legs(run_dir, run_id, run_date, family, n_legs, top_n=top_n))
    return legs


def _load_marketed_legs(run_dir: Path, run_id: str, run_date: str) -> list[SlipLeg]:
    path = run_dir / "marketed_slips.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    required = {"slip", "player", "stat", "direction", "tier", "line"}
    if not required <= set(df.columns):
        return []
    legs: list[SlipLeg] = []
    for slip_index, (slip_label, group) in enumerate(df.groupby("slip", sort=False), start=1):
        n_legs = len(group)
        slip_hit_prob = _safe_float(group["hit_prob"].iloc[0]) if "hit_prob" in group.columns else None
        slip_ev = _safe_float(group["ev"].iloc[0]) if "ev" in group.columns else None
        for _, row in group.iterrows():
            legs.append(
                SlipLeg(
                    run_id=run_id,
                    date=run_date,
                    product="marketed",
                    family="Marketed",
                    slip_label=str(slip_label),
                    slip_rank=slip_index,
                    n_legs=n_legs,
                    player=str(row.get("player", "")).strip(),
                    stat=str(row.get("stat", "")).strip().upper(),
                    direction=str(row.get("direction", "")).strip().upper(),
                    tier=str(row.get("tier", "")).strip().upper(),
                    line=float(row.get("line")),
                    projection_id=str(row.get("source_projection_id") or row.get("projection_id") or "").strip(),
                    displayed_p=_safe_float(row.get("p_cal")),
                    slip_hit_prob=slip_hit_prob,
                    slip_ev=slip_ev,
                )
            )
    return legs


def _load_recommended_legs(
    run_dir: Path,
    run_id: str,
    run_date: str,
    family: str,
    n_legs: int,
    *,
    top_n: int,
) -> list[SlipLeg]:
    path = run_dir / family / f"recommended_{n_legs}leg.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    legs: list[SlipLeg] = []
    for rank, (_, row) in enumerate(df.head(top_n).iterrows(), start=1):
        slip_label = f"{n_legs}-leg"
        slip_hit_prob = _safe_float(row.get("hit_prob"))
        slip_ev = _safe_float(row.get("ev_mult"))
        for leg_text in _leg_texts(row):
            parsed = _parse_leg_text(leg_text)
            if parsed is None:
                continue
            player, direction, stat, line, tier, projection_id = parsed
            legs.append(
                SlipLeg(
                    run_id=run_id,
                    date=run_date,
                    product="recommended",
                    family=family,
                    slip_label=slip_label,
                    slip_rank=rank,
                    n_legs=n_legs,
                    player=player,
                    stat=stat,
                    direction=direction,
                    tier=tier,
                    line=line,
                    projection_id=projection_id,
                    displayed_p=None,
                    slip_hit_prob=slip_hit_prob,
                    slip_ev=slip_ev,
                )
            )
    return legs


def _leg_texts(row: pd.Series) -> list[str]:
    cols = [col for col in row.index if re.fullmatch(r"leg_\d+", str(col))]
    if cols:
        return [str(row[col]) for col in sorted(cols, key=lambda value: int(str(value).split("_")[1])) if str(row[col]).strip()]
    text = str(row.get("legs", ""))
    return [part.strip() for part in text.split(" | ") if part.strip()]


def _parse_leg_text(value: str) -> tuple[str, str, str, float, str, str] | None:
    match = re.match(r"^(.+?)\s+(OVER|UNDER)\s+([A-Z0-9+]+)\s+([\d.]+)\s+\((\w+)\)(?:\s+\[id:([^\]]+)\])?", value)
    if not match:
        return None
    player, direction, stat, line, tier, projection_id = match.groups()
    return player.strip(), direction.upper(), stat.upper(), float(line), tier.upper(), str(projection_id or "").strip()


def _match_eval_leg(leg: SlipLeg, eval_df: pd.DataFrame) -> pd.Series | None:
    if leg.projection_id:
        match = eval_df[
            (eval_df["source_projection_id_str"] == leg.projection_id)
            | (eval_df["projection_id_str"] == leg.projection_id)
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


def _selected_leg_row(leg: SlipLeg, match: pd.Series) -> dict[str, Any]:
    row = leg.__dict__.copy()
    row.update(
        {
            "hit": _safe_float(match.get("hit")),
            "actual": _safe_float(match.get("actual")),
            "p": _safe_float(match.get("p")),
            "p_adj": _safe_float(match.get("p_adj")),
            "p_for_cal": _safe_float(match.get("p_for_cal")),
            "p_cal": _safe_float(match.get("p_cal")),
            "p_catboost": _safe_float(match.get("p_catboost")),
            "p_cal_marketed": _safe_float(match.get("p_cal_marketed")),
            "is_questionable": _safe_float(match.get("is_questionable")),
            "q_out_frac": _safe_float(match.get("q_out_frac")),
            "fragility": _safe_float(match.get("fragility")),
            "minutes_s": _safe_float(match.get("minutes_s")),
            "min_std": _safe_float(match.get("min_std")),
            "zero_dnp_mult": _safe_float(match.get("zero_dnp_mult")),
            "external_prior_score": _safe_float(match.get("external_prior_score")),
            "external_prior_n": _safe_float(match.get("external_prior_n")),
            "eval_match_quality": match.get("eval_match_quality"),
        }
    )
    return row


def _score_slips(run_id: str, run_date: str, legs: list[SlipLeg], eval_df: pd.DataFrame) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int, int], list[SlipLeg]] = {}
    for leg in legs:
        key = (leg.product, leg.family, leg.slip_label, leg.slip_rank, leg.n_legs)
        grouped.setdefault(key, []).append(leg)

    rows: list[dict[str, Any]] = []
    for (product, family, slip_label, slip_rank, n_legs), slip_legs in grouped.items():
        hits: list[float] = []
        actuals: list[str] = []
        ps: list[float] = []
        for leg in slip_legs:
            match = _match_eval_leg(leg, eval_df)
            if match is None or pd.isna(match.get("hit")):
                continue
            hit = float(match.get("hit"))
            hits.append(hit)
            actuals.append(f"{leg.player} {leg.stat} {leg.direction} {leg.line}: hit={int(hit)} actual={match.get('actual')}")
            p = _safe_float(match.get("p_cal"))
            if p is not None:
                ps.append(p)
        settled = len(hits)
        rows.append(
            {
                "run_id": run_id,
                "date": run_date,
                "product": product,
                "family": family,
                "slip_label": slip_label,
                "slip_rank": slip_rank,
                "n_legs": n_legs,
                "settled_legs": settled,
                "hit_legs": int(sum(hits)),
                "slip_won": int(settled == n_legs and sum(hits) == n_legs),
                "slip_hit_prob": slip_legs[0].slip_hit_prob,
                "slip_ev": slip_legs[0].slip_ev,
                "avg_p_cal": float(sum(ps) / len(ps)) if ps else None,
                "legs": " | ".join(actuals),
            }
        )
    return rows


def _slip_summary(slip_df: pd.DataFrame) -> pd.DataFrame:
    if slip_df.empty:
        return pd.DataFrame()
    return (
        slip_df.groupby(["date", "product", "family", "n_legs"], dropna=False)
        .agg(
            slips=("slip_won", "count"),
            wins=("slip_won", "sum"),
            leg_hits=("hit_legs", "sum"),
            leg_count=("settled_legs", "sum"),
            avg_expected_slip_p=("slip_hit_prob", "mean"),
            avg_p_cal=("avg_p_cal", "mean"),
        )
        .reset_index()
        .assign(slip_win_rate=lambda df: df["wins"] / df["slips"], leg_hit_rate=lambda df: df["leg_hits"] / df["leg_count"])
        .sort_values(["date", "product", "family", "n_legs"])
    )


def _selected_leg_summary(leg_df: pd.DataFrame) -> dict[str, Any]:
    if leg_df.empty:
        return {}
    hit = pd.to_numeric(leg_df["hit"], errors="coerce")
    out = {
        "legs": int(hit.notna().sum()),
        "hit_rate": _mean(hit),
    }
    for col in ("displayed_p", "p_cal", "p_catboost", "p_cal_marketed", "p_for_cal"):
        if col in leg_df.columns:
            p = pd.to_numeric(leg_df[col], errors="coerce")
            mask = p.notna() & hit.notna()
            if mask.any():
                out[f"{col}_mean"] = float(p[mask].mean())
                out[f"{col}_brier"] = float(((p[mask] - hit[mask]) ** 2).mean())
                out[f"{col}_gap"] = float(p[mask].mean() - hit[mask].mean())
    return out


def _group_leg_performance(leg_df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if leg_df.empty:
        return pd.DataFrame()
    df = leg_df.copy()
    df["hit"] = pd.to_numeric(df["hit"], errors="coerce")
    for col in ("p_cal", "p_catboost", "p_cal_marketed"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    grouped = (
        df.groupby(keys, dropna=False)
        .agg(
            legs=("hit", "count"),
            hits=("hit", "sum"),
            hit_rate=("hit", "mean"),
            avg_p_cal=("p_cal", "mean"),
            avg_p_catboost=("p_catboost", "mean"),
            avg_p_cal_marketed=("p_cal_marketed", "mean"),
        )
        .reset_index()
    )
    grouped["gap_p_cal"] = grouped["avg_p_cal"] - grouped["hit_rate"]
    return grouped.sort_values(["legs", "gap_p_cal"], ascending=[False, False])


def _group_slip_performance(slip_df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if slip_df.empty:
        return pd.DataFrame()
    grouped = (
        slip_df.groupby(keys, dropna=False)
        .agg(
            slips=("slip_won", "count"),
            wins=("slip_won", "sum"),
            leg_hits=("hit_legs", "sum"),
            leg_count=("settled_legs", "sum"),
            avg_expected_slip_p=("slip_hit_prob", "mean"),
        )
        .reset_index()
    )
    grouped["slip_win_rate"] = grouped["wins"] / grouped["slips"]
    grouped["leg_hit_rate"] = grouped["leg_hits"] / grouped["leg_count"]
    return grouped.sort_values(keys)


def _worst_missed_legs(leg_df: pd.DataFrame) -> pd.DataFrame:
    if leg_df.empty:
        return pd.DataFrame()
    df = leg_df[pd.to_numeric(leg_df["hit"], errors="coerce") == 0].copy()
    if df.empty:
        return pd.DataFrame()
    df["sort_p"] = pd.to_numeric(df.get("p_cal"), errors="coerce")
    cols = [
        "date",
        "run_id",
        "product",
        "family",
        "slip_label",
        "player",
        "team",
        "stat",
        "direction",
        "tier",
        "line",
        "actual",
        "p_cal",
        "p_catboost",
        "p_cal_marketed",
        "is_questionable",
        "q_out_frac",
        "fragility",
        "zero_dnp_mult",
    ]
    return df.sort_values("sort_p", ascending=False)[[col for col in cols if col in df.columns]].head(30)


def _high_confidence_misses(leg_df: pd.DataFrame) -> pd.DataFrame:
    if leg_df.empty or "p_cal" not in leg_df.columns:
        return pd.DataFrame()
    df = leg_df[(pd.to_numeric(leg_df["p_cal"], errors="coerce") >= 0.70) & (pd.to_numeric(leg_df["hit"], errors="coerce") == 0)]
    return _worst_missed_legs(df).head(20)


def _print_report(board_df: pd.DataFrame, leg_df: pd.DataFrame, slip_df: pd.DataFrame, payload: dict[str, Any]) -> None:
    print("=== FULL BOARD BY RUN ===")
    if not board_df.empty:
        cols = [col for col in ["date", "run_id", "settled_rows", "hit_rate", "p_cal_mean", "p_cal_brier", "p_catboost_mean", "p_catboost_brier"] if col in board_df.columns]
        print(board_df[cols].to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    print("\n=== SELECTED SLIP LEG SUMMARY ===")
    print(json.dumps(payload["selected_leg_summary"], indent=2, sort_keys=True))

    print("\n=== SLIP SUMMARY ===")
    summary = _slip_summary(slip_df)
    if not summary.empty:
        print(summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    print("\n=== WORST HIGH-PROBABILITY MISSES ===")
    high_misses = _high_confidence_misses(leg_df)
    if high_misses.empty:
        print("No selected misses with p_cal >= 0.70.")
    else:
        print(high_misses.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    print("\n=== SELECTED LEGS BY STAT/TIER/DIRECTION ===")
    grouped = _group_leg_performance(leg_df, ["stat", "tier", "direction"])
    if not grouped.empty:
        print(grouped.head(30).to_string(index=False, float_format=lambda value: f"{value:.4f}"))


def _safe_float(value: Any) -> float | None:
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


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records"))


if __name__ == "__main__":
    raise SystemExit(main())

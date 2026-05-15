#!/usr/bin/env python3
"""Audit historical single-game slates against current robustness rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "output" / "runs"
sys.path.insert(0, str(ROOT / "src"))

from Atlas.core.single_game_script import (  # noqa: E402
    apply_single_game_selection_surface,
    apply_single_game_script_annotations,
    count_games,
    single_game_slip_rule_status,
)


ID_RE = re.compile(r"\[id:(?P<id>[^\]]+)\]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", help="Run IDs or absolute run folder paths.")
    parser.add_argument("--json-out", help="Optional JSON report path.")
    parser.add_argument("--csv-out", help="Optional selected-slip CSV report path.")
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    run_dirs = [_resolve_run(value) for value in args.runs]

    board_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    slip_rows: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        eval_path = run_dir / "eval_legs.csv"
        scored_path = run_dir / "scored_legs_deduped.csv"
        if not eval_path.exists() or not scored_path.exists():
            raise FileNotFoundError(f"{run_dir} needs eval_legs.csv and scored_legs_deduped.csv")

        eval_df = pd.read_csv(eval_path, low_memory=False)
        scored_df = pd.read_csv(scored_path, low_memory=False)
        annotated = apply_single_game_script_annotations(eval_df, cfg)
        score_col = _score_col(annotated)
        surfaced = apply_single_game_selection_surface(annotated, cfg, score_col=score_col, clip_score=True)
        annotated = annotated.copy()
        annotated["current_single_game_selection_delta"] = _num(surfaced[score_col]) - _num(annotated[score_col])

        board_rows.append(_board_summary(run_dir, scored_df, annotated, score_col))
        selected = _load_selected_rows(run_dir, annotated)
        selected_rows.extend(selected)
        slip_rows.extend(_slip_rows(run_dir, selected, cfg))

    payload = {
        "runs": [run.name for run in run_dirs],
        "board_summary": board_rows,
        "selected_leg_summary": _selected_summary(selected_rows),
        "slip_summary": _slip_summary(slip_rows),
        "risk_legs": _risk_legs(selected_rows),
    }

    _print_report(payload)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nWrote JSON: {out}")

    if args.csv_out:
        out = Path(args.csv_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(selected_rows).to_csv(out, index=False)
        print(f"Wrote CSV: {out}")

    return 0


def _resolve_run(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    path = RUNS_DIR / value
    if path.exists():
        return path
    raise FileNotFoundError(value)


def _score_col(df: pd.DataFrame) -> str:
    for col in ("p_cal", "p_adj", "p_eff", "p"):
        if col in df.columns:
            return col
    raise KeyError("No probability column found.")


def _num(series: pd.Series | Any, default: float = 0.0) -> pd.Series:
    if isinstance(series, pd.Series):
        return pd.to_numeric(series, errors="coerce").fillna(default)
    return pd.Series(dtype="float64")


def _board_summary(run_dir: Path, scored_df: pd.DataFrame, annotated: pd.DataFrame, score_col: str) -> dict[str, Any]:
    hit = _num(annotated.get("hit", pd.Series(dtype="float64")))
    directions = annotated.get("direction", pd.Series("", index=annotated.index)).astype(str).str.upper()
    under = directions == "UNDER"
    over = directions == "OVER"

    return {
        "run": run_dir.name,
        "games": int(count_games(scored_df)),
        "rows": int(len(annotated)),
        "score_col": score_col,
        "hit_rate": _mean(hit),
        "over_count": int(over.sum()),
        "over_hit_rate": _mean(hit[over]),
        "under_count": int(under.sum()),
        "under_hit_rate": _mean(hit[under]),
        "mean_current_delta": _mean(_num(annotated["current_single_game_selection_delta"])),
        "low_line_noise_legs": _sum_flag(annotated, "single_game_low_line_noise_flag"),
        "role_shooter_over_legs": _sum_flag(annotated, "single_game_role_shooter_over_flag"),
        "low_minute_bench_over_legs": _sum_flag(annotated, "single_game_low_minute_bench_over_flag"),
        "multi_script_survival_legs": _sum_flag(annotated, "single_game_multi_script_survival_flag"),
        "injury_uncertainty_legs": _sum_flag(annotated, "single_game_injury_uncertainty_flag"),
    }


def _load_selected_rows(run_dir: Path, annotated: pd.DataFrame) -> list[dict[str, Any]]:
    by_id = _id_lookup(annotated)

    selected: list[dict[str, Any]] = []
    for product, folder in _product_folders(run_dir):
        for path in sorted(folder.glob("recommended_*leg.csv")):
            if path.stat().st_size <= 20:
                continue
            try:
                slips = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                continue
            if slips.empty:
                continue
            n_legs = _n_legs_from_name(path.name)
            for slip_rank, slip in slips.reset_index(drop=True).iterrows():
                ids = _projection_ids(slip)
                if not ids:
                    continue
                for projection_id in ids:
                    leg = by_id.get(str(projection_id))
                    if leg is None:
                        continue
                    selected.append(_selected_leg_row(run_dir, product, path.name, slip_rank + 1, n_legs, leg))

    marketed = run_dir / "marketed_slips.csv"
    if marketed.exists() and marketed.stat().st_size > 20:
        selected.extend(_marketed_rows(run_dir, marketed, annotated))

    return selected


def _id_lookup(df: pd.DataFrame) -> dict[str, pd.Series]:
    lookup: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        for col in ("projection_id", "source_projection_id"):
            if col not in row.index:
                continue
            key = str(row.get(col, ""))
            if key and key.lower() != "nan" and key not in lookup:
                lookup[key] = row
    return lookup


def _product_folders(run_dir: Path) -> list[tuple[str, Path]]:
    folders = [("main", run_dir)]
    for name in ("System", "Windfall"):
        path = run_dir / name
        if path.exists():
            folders.append((name.lower(), path))
    return folders


def _n_legs_from_name(name: str) -> int:
    match = re.search(r"recommended_(\d+)leg", name)
    return int(match.group(1)) if match else 0


def _projection_ids(row: pd.Series) -> list[str]:
    leg_cols = sorted(
        [col for col in row.index if re.fullmatch(r"leg_\d+", str(col))],
        key=lambda col: int(str(col).split("_", 1)[1]),
    )
    if leg_cols:
        text = " | ".join(str(row.get(col, "")) for col in leg_cols)
    else:
        text = str(row.get("legs", ""))
    seen: set[str] = set()
    ids: list[str] = []
    for projection_id in ID_RE.findall(text):
        if projection_id in seen:
            continue
        seen.add(projection_id)
        ids.append(projection_id)
    return ids


def _selected_leg_row(
    run_dir: Path,
    product: str,
    family: str,
    slip_rank: int,
    n_legs: int,
    leg: pd.Series,
) -> dict[str, Any]:
    return {
        "run": run_dir.name,
        "product": product,
        "family": family,
        "slip_rank": int(slip_rank),
        "n_legs": int(n_legs),
        "projection_id": str(leg.get("projection_id", "")),
        "player": str(leg.get("player", "")),
        "team": str(leg.get("team", "")),
        "opp": str(leg.get("opp", "")),
        "stat": str(leg.get("stat", "")),
        "direction": str(leg.get("direction", "")),
        "tier": str(leg.get("tier", "")),
        "line": _float(leg.get("line")),
        "p_cal": _float(leg.get("p_cal")),
        "actual": _float(leg.get("actual")),
        "hit": _float(leg.get("hit")),
        "single_game_slate": _flag(leg.get("single_game_slate")),
        "single_game_profile_active": _flag(leg.get("single_game_profile_active")),
        "current_delta": _float(leg.get("current_single_game_selection_delta")),
        "robustness_score": _float(leg.get("single_game_robustness_score")),
        "dependency_score": _float(leg.get("single_game_script_dependency_score")),
        "reasons": str(leg.get("single_game_robustness_reasons", leg.get("single_game_script_reasons", ""))),
        "single_game_script_fit": _float(leg.get("single_game_script_fit")),
        "single_game_robustness_score": _float(leg.get("single_game_robustness_score")),
        "single_game_script_dependency_score": _float(leg.get("single_game_script_dependency_score")),
        "single_game_anchor_flag": _flag(leg.get("single_game_anchor_flag")),
        "single_game_role_shooter_over_flag": _flag(leg.get("single_game_role_shooter_over_flag")),
        "single_game_fg3m_over_flag": _flag(leg.get("single_game_fg3m_over_flag")),
        "single_game_non_shooting_volume_flag": _flag(leg.get("single_game_non_shooting_volume_flag")),
        "single_game_low_minute_bench_over_flag": _flag(leg.get("single_game_low_minute_bench_over_flag")),
        "single_game_low_line_noise_flag": _flag(leg.get("single_game_low_line_noise_flag")),
        "single_game_multi_script_survival_flag": _flag(leg.get("single_game_multi_script_survival_flag")),
        "low_line_noise": _flag(leg.get("single_game_low_line_noise_flag")),
        "role_shooter_over": _flag(leg.get("single_game_role_shooter_over_flag")),
        "fg3m_over": _flag(leg.get("single_game_fg3m_over_flag")),
        "non_shooting_volume": _flag(leg.get("single_game_non_shooting_volume_flag")),
        "low_minute_bench_over": _flag(leg.get("single_game_low_minute_bench_over_flag")),
        "multi_script_survival": _flag(leg.get("single_game_multi_script_survival_flag")),
        "injury_uncertainty": _flag(leg.get("single_game_injury_uncertainty_flag")),
    }


def _marketed_rows(run_dir: Path, path: Path, annotated: pd.DataFrame) -> list[dict[str, Any]]:
    marketed = pd.read_csv(path)
    out: list[dict[str, Any]] = []
    slip_ordinals: dict[str, int] = {}
    for idx, row in marketed.reset_index(drop=True).iterrows():
        match = _match_marketed(row, annotated)
        if match is None:
            continue
        slip_label = str(row.get("slip", "marketed"))
        if slip_label not in slip_ordinals:
            slip_ordinals[slip_label] = len(slip_ordinals) + 1
        n_legs = int(slip_label.split("-")[0]) if "-" in slip_label else 0
        selected = _selected_leg_row(run_dir, "marketed", "marketed_slips.csv", slip_ordinals[slip_label], n_legs, match)
        selected["marketed_slip"] = slip_label
        out.append(selected)
    return out


def _match_marketed(row: pd.Series, annotated: pd.DataFrame) -> pd.Series | None:
    mask = (
        annotated.get("player", pd.Series("", index=annotated.index)).astype(str).str.casefold().eq(str(row.get("player", "")).casefold())
        & annotated.get("stat", pd.Series("", index=annotated.index)).astype(str).str.upper().eq(str(row.get("stat", "")).upper())
        & annotated.get("direction", pd.Series("", index=annotated.index)).astype(str).str.upper().eq(str(row.get("direction", "")).upper())
        & (_num(annotated.get("line", pd.Series(dtype="float64"))) == _float(row.get("line")))
    )
    hits = annotated[mask]
    if hits.empty:
        return None
    return hits.iloc[0]


def _slip_rows(run_dir: Path, selected: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    df = pd.DataFrame(selected)
    if df.empty:
        return rows
    groups = df.groupby(["product", "family", "slip_rank", "n_legs"], dropna=False)
    for (product, family, slip_rank, n_legs), slip in groups:
        ok, reasons, metrics = single_game_slip_rule_status([row for _, row in slip.iterrows()], cfg, n_legs=int(n_legs))
        rows.append(
            {
                "run": run_dir.name,
                "product": product,
                "family": family,
                "slip_rank": int(slip_rank),
                "n_legs": int(n_legs),
                "legs": int(len(slip)),
                "hit_count": int(_num(slip["hit"]).sum()),
                "all_hit": bool((_num(slip["hit"]) >= 1.0).all()),
                "mean_p_cal": _mean(_num(slip["p_cal"])),
                "mean_current_delta": _mean(_num(slip["current_delta"])),
                "low_line_noise": int(_num(slip["low_line_noise"]).sum()),
                "role_shooter_overs": int(_num(slip["role_shooter_over"]).sum()),
                "fg3m_overs": int(_num(slip["fg3m_over"]).sum()),
                "low_minute_bench_overs": int(_num(slip["low_minute_bench_over"]).sum()),
                "multi_script_survival": int(_num(slip["multi_script_survival"]).sum()),
                "rules_pass_current": bool(ok),
                "rule_reasons_current": ";".join(reasons),
                "players": "; ".join(slip["player"].astype(str).tolist()),
                "stats": "; ".join((slip["direction"].astype(str) + " " + slip["stat"].astype(str)).tolist()),
                **{f"metric_{key}": value for key, value in metrics.items()},
            }
        )
    return rows


def _selected_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    return {
        "legs": int(len(df)),
        "hit_rate": _mean(_num(df["hit"])),
        "mean_current_delta": _mean(_num(df["current_delta"])),
        "low_line_noise": int(_num(df["low_line_noise"]).sum()),
        "role_shooter_overs": int(_num(df["role_shooter_over"]).sum()),
        "fg3m_overs": int(_num(df["fg3m_over"]).sum()),
        "low_minute_bench_overs": int(_num(df["low_minute_bench_over"]).sum()),
        "multi_script_survival": int(_num(df["multi_script_survival"]).sum()),
    }


def _slip_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    grouped = df.groupby(["run", "product", "n_legs"], dropna=False).agg(
        slips=("legs", "count"),
        all_hit=("all_hit", "sum"),
        avg_hit_count=("hit_count", "mean"),
        avg_current_delta=("mean_current_delta", "mean"),
        rule_pass_rate=("rules_pass_current", "mean"),
        low_line_noise=("low_line_noise", "sum"),
        role_shooter_overs=("role_shooter_overs", "sum"),
        low_minute_bench_overs=("low_minute_bench_overs", "sum"),
    )
    return _records(grouped.reset_index())


def _risk_legs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    risk = df[
        (_num(df["low_line_noise"]) > 0)
        | (_num(df["role_shooter_over"]) > 0)
        | (_num(df["low_minute_bench_over"]) > 0)
        | (_num(df["current_delta"]) < -0.04)
    ].copy()
    keep = [
        "run",
        "product",
        "family",
        "n_legs",
        "player",
        "stat",
        "direction",
        "tier",
        "line",
        "p_cal",
        "actual",
        "hit",
        "current_delta",
        "reasons",
    ]
    return _records(risk.sort_values(["run", "current_delta"]).head(30)[keep])


def _print_report(payload: dict[str, Any]) -> None:
    print("\n=== Single-Game Robustness Audit ===")
    print("\nBoard summary")
    print(pd.DataFrame(payload["board_summary"]).to_string(index=False))

    print("\nSelected leg summary")
    print(json.dumps(payload["selected_leg_summary"], indent=2, sort_keys=True))

    print("\nSlip summary")
    slip_df = pd.DataFrame(payload["slip_summary"])
    if slip_df.empty:
        print("(none)")
    else:
        print(slip_df.to_string(index=False))

    print("\nTop current-risk selected legs")
    risk_df = pd.DataFrame(payload["risk_legs"])
    if risk_df.empty:
        print("(none)")
    else:
        print(risk_df.to_string(index=False))


def _mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 6)


def _sum_flag(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    return int(_num(df[col]).sum())


def _float(value: Any) -> float | None:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(val):
        return None
    return val


def _flag(value: Any) -> int:
    val = _float(value)
    return int(bool(val and val > 0.0))


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = df.where(pd.notna(df), None).to_dict(orient="records")
    return [{str(k): _json_scalar(v) for k, v in row.items()} for row in rows]


def _json_scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


if __name__ == "__main__":
    raise SystemExit(main())

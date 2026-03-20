#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


STAT_ALIASES: Dict[str, str] = {
    "PTS": "pts",
    "POINTS": "pts",
    "REB": "reb",
    "REBOUNDS": "reb",
    "AST": "ast",
    "ASSISTS": "ast",
    "FG3M": "fg3m",
    "3PM": "fg3m",
    "THREES": "fg3m",
    "3-PT MADE": "fg3m",
    "FGA": "fga",
    "FTA": "fta",
    "TOV": "tov",
    "TO": "tov",
    "TURNOVERS": "tov",
    "MIN": "minutes",
    "MINUTES": "minutes",
    "PA": "pa",
    "PR": "pr",
    "RA": "ra",
    "PRA": "pra",
    "AR": "ar",
    "PTS+REB": "pr",
    "PTS+AST": "pa",
    "REB+AST": "ra",
    "PTS+REB+AST": "pra",
}


OUTPUT_APPEND_ORDER = [
    "source_projection_id",
    "player_key",
    "player_norm",
    "player_log",
    "team_log",
    "opp_log",
    "minutes",
    "pts",
    "reb",
    "ast",
    "fg3m",
    "fga",
    "fta",
    "tov",
    "usg_proxy",
    "actual",
    "hit",
    "push",
    "eval_reconstructed",
    "eval_match_quality",
    "eval_stat_source",
    "actual_delta",
    "actual_abs_delta",
    "brier_p",
    "brier_p_role",
    "brier_p_close",
    "brier_p_close_raw",
    "brier_p_close_role",
    "brier_p_adj_pre_under_relief",
    "brier_p_adj",
    "brier_p_for_cal",
    "brier_p_cal",
]


EVAL_PROBABILITY_COLUMNS = (
    "p",
    "p_role",
    "p_close",
    "p_close_raw",
    "p_close_role",
    "p_adj_pre_under_relief",
    "p_adj",
    "p_for_cal",
    "p_cal",
)


@dataclass
class RunResult:
    run_dir: str
    rows: int
    matched_rows: int
    unmatched_rows: int
    output_path: str
    report_path: str



def normalize_name(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).upper()
    text = text.replace("JR.", "JR").replace("SR.", "SR")
    text = text.replace("III", "3").replace("II", "2").replace("IV", "4")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text



def normalize_team(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).upper().strip()
    return re.sub(r"[^A-Z]", "", text)



def normalize_date(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", utc=False)
    return parsed.dt.strftime("%Y-%m-%d")



def canonical_stat(stat: object) -> str:
    if stat is None or (isinstance(stat, float) and math.isnan(stat)):
        return ""
    key = str(stat).upper().strip()
    return STAT_ALIASES.get(key, key.lower())



def derive_actual_row(row: pd.Series) -> Tuple[float, str]:
    stat_key = canonical_stat(row.get("stat"))
    pts = float(row.get("pts", 0) or 0)
    reb = float(row.get("reb", 0) or 0)
    ast = float(row.get("ast", 0) or 0)
    fg3m = float(row.get("fg3m", 0) or 0)
    fga = float(row.get("fga", 0) or 0)
    fta = float(row.get("fta", 0) or 0)
    tov = float(row.get("tov", 0) or 0)
    minutes = float(row.get("minutes", 0) or 0)

    if stat_key == "pts":
        return pts, "pts"
    if stat_key == "reb":
        return reb, "reb"
    if stat_key == "ast":
        return ast, "ast"
    if stat_key == "fg3m":
        return fg3m, "fg3m"
    if stat_key == "fga":
        return fga, "fga"
    if stat_key == "fta":
        return fta, "fta"
    if stat_key == "tov":
        return tov, "tov"
    if stat_key == "minutes":
        return minutes, "minutes"
    if stat_key == "pa":
        return pts + ast, "pts+ast"
    if stat_key == "pr":
        return pts + reb, "pts+reb"
    if stat_key == "ra":
        return reb + ast, "reb+ast"
    if stat_key == "pra":
        return pts + reb + ast, "pts+reb+ast"
    if stat_key == "ar":
        return ast + reb, "ast+reb"
    return math.nan, "unsupported"



def settle_leg(actual: float, line: object, direction: object) -> Tuple[float, float]:
    if actual is None or (isinstance(actual, float) and math.isnan(actual)):
        return math.nan, math.nan
    try:
        line_value = float(line)
    except Exception:
        return math.nan, math.nan
    direction_text = str(direction).upper().strip()
    if actual == line_value:
        return 0.0, 1.0
    if direction_text == "OVER":
        return (1.0, 0.0) if actual > line_value else (0.0, 0.0)
    if direction_text == "UNDER":
        return (1.0, 0.0) if actual < line_value else (0.0, 0.0)
    return math.nan, math.nan



def load_gamelogs(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"game_date", "player", "team", "opp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"gamelogs missing required columns: {sorted(missing)}")

    df = df.copy()
    df["game_date"] = normalize_date(df["game_date"])
    df["player_key"] = df["player"].map(normalize_name)
    df["team_log"] = df["team"].map(normalize_team)
    df["opp_log"] = df["opp"].map(normalize_team)

    for col in ["minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov", "usg_proxy"]:
        if col not in df.columns:
            df[col] = math.nan

    df = df.sort_values(["game_date", "player_key", "team_log", "opp_log"]).reset_index(drop=True)
    return df



def choose_match(candidates: pd.DataFrame, team: str, opp: str) -> Tuple[Optional[pd.Series], str]:
    if candidates.empty:
        return None, "no_player_date_match"
    if len(candidates) == 1:
        return candidates.iloc[0], "player_date"

    team = normalize_team(team)
    opp = normalize_team(opp)
    if team:
        team_matches = candidates[candidates["team_log"] == team]
        if len(team_matches) == 1:
            return team_matches.iloc[0], "player_date_team"
        if not team_matches.empty:
            candidates = team_matches
    if opp:
        opp_matches = candidates[candidates["opp_log"] == opp]
        if len(opp_matches) == 1:
            return opp_matches.iloc[0], "player_date_opp"
        if not opp_matches.empty:
            candidates = opp_matches
    return candidates.iloc[0], f"ambiguous_{len(candidates)}_picked_first"



def reconstruct_eval(scored: pd.DataFrame, gamelogs: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
    df = scored.copy()
    if "game_date" not in df.columns or "player" not in df.columns:
        raise ValueError("scored_legs_deduped.csv must include at least game_date and player columns")

    df["game_date"] = normalize_date(df["game_date"])
    df["player_key"] = df["player"].map(normalize_name)
    df["player_norm"] = df["player_key"]
    df["team_norm"] = df.get("team", pd.Series(index=df.index, dtype=object)).map(normalize_team)
    df["opp_norm"] = df.get("opp", pd.Series(index=df.index, dtype=object)).map(normalize_team)

    if "source_projection_id" not in df.columns:
        df["source_projection_id"] = df.get("projection_id")

    game_groups = {
        key: grp.reset_index(drop=True)
        for key, grp in gamelogs.groupby(["game_date", "player_key"], dropna=False)
    }

    results_rows: List[Dict[str, object]] = []
    matched = 0
    unmatched = 0
    quality_counts: Dict[str, int] = {}

    for _, row in df.iterrows():
        key = (row.get("game_date", ""), row.get("player_key", ""))
        candidates = game_groups.get(key)
        if candidates is None:
            selected = None
            quality = "no_player_date_match"
            unmatched += 1
        else:
            selected, quality = choose_match(candidates, row.get("team"), row.get("opp"))
            if selected is None:
                unmatched += 1
            else:
                matched += 1
        quality_counts[quality] = quality_counts.get(quality, 0) + 1

        out: Dict[str, object] = {}
        if selected is not None:
            for col in ["player", "team_log", "opp_log", "minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov", "usg_proxy"]:
                out[col] = selected.get(col)
            out["player_log"] = selected.get("player")
            actual, stat_src = derive_actual_row(pd.concat([row, selected]))
            hit, push = settle_leg(actual, row.get("line"), row.get("direction"))
        else:
            out.update({
                "player_log": pd.NA,
                "team_log": pd.NA,
                "opp_log": pd.NA,
                "minutes": pd.NA,
                "pts": pd.NA,
                "reb": pd.NA,
                "ast": pd.NA,
                "fg3m": pd.NA,
                "fga": pd.NA,
                "fta": pd.NA,
                "tov": pd.NA,
                "usg_proxy": pd.NA,
            })
            actual, stat_src, hit, push = (math.nan, "no_match", math.nan, math.nan)

        out["actual"] = actual
        out["hit"] = hit
        out["push"] = push
        out["eval_reconstructed"] = 1
        out["eval_match_quality"] = quality
        out["eval_stat_source"] = stat_src
        results_rows.append(out)

    add_df = pd.DataFrame(results_rows)
    add_df["actual_delta"] = pd.to_numeric(add_df.get("actual"), errors="coerce") - pd.to_numeric(df.get("line"), errors="coerce")
    add_df["actual_abs_delta"] = add_df["actual_delta"].abs()
    hit = pd.to_numeric(add_df.get("hit"), errors="coerce")
    for col in EVAL_PROBABILITY_COLUMNS:
        if col not in df.columns:
            continue
        pred = pd.to_numeric(df[col], errors="coerce").clip(0.0, 1.0)
        add_df[f"{col}_error"] = pred - hit
        add_df[f"brier_{col}"] = add_df[f"{col}_error"] ** 2

    for col in OUTPUT_APPEND_ORDER:
        if col in add_df.columns:
            df[col] = add_df[col]
        elif col not in df.columns:
            df[col] = pd.NA

    for col in OUTPUT_APPEND_ORDER:
        if col not in df.columns:
            df[col] = pd.NA

    ordered_cols = list(df.columns)
    report = {
        "rows": int(len(df)),
        "matched_rows": int(matched),
        "unmatched_rows": int(unmatched),
        "match_rate": float(matched / len(df)) if len(df) else 0.0,
        "quality_counts": quality_counts,
        "supported_stats": sorted(df.get("stat", pd.Series(dtype=object)).dropna().astype(str).str.upper().unique().tolist()),
    }
    return df[ordered_cols], report



def resolve_run_dirs(args: argparse.Namespace) -> List[Path]:
    runs: List[Path] = []
    for run_dir in args.run_dir:
        p = Path(run_dir)
        if not p.exists():
            raise FileNotFoundError(f"run dir not found: {p}")
        runs.append(p)
    if args.corpus_root:
        root = Path(args.corpus_root)
        corpus_runs = sorted([p for p in root.rglob("*") if p.is_dir() and (p / "scored_legs_deduped.csv").exists()])
        runs.extend(corpus_runs)
    deduped: List[Path] = []
    seen = set()
    for run in runs:
        key = str(run.resolve())
        if key not in seen:
            seen.add(key)
            deduped.append(run)
    if not deduped:
        raise ValueError("no run directories resolved")
    return deduped



def process_run(run_dir: Path, gamelogs: pd.DataFrame, write: bool, output_name: str) -> RunResult:
    scored_path = run_dir / "scored_legs_deduped.csv"
    if not scored_path.exists():
        raise FileNotFoundError(f"missing scored_legs_deduped.csv in {run_dir}")
    scored = pd.read_csv(scored_path)
    eval_df, report = reconstruct_eval(scored, gamelogs)

    output_path = run_dir / output_name
    report_path = run_dir / f"{Path(output_name).stem}_reconstruction_report.json"
    if write:
        eval_df.to_csv(output_path, index=False)
        report_payload = {
            "run_dir": str(run_dir),
            "source_scored_path": str(scored_path),
            "output_eval_path": str(output_path),
            "report": report,
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return RunResult(
        run_dir=str(run_dir),
        rows=report["rows"],
        matched_rows=report["matched_rows"],
        unmatched_rows=report["unmatched_rows"],
        output_path=str(output_path),
        report_path=str(report_path),
    )



def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy eval_legs.csv from scored_legs_deduped.csv + nba_gamelogs.csv")
    parser.add_argument("--run-dir", action="append", default=[], help="Run folder containing scored_legs_deduped.csv; can be repeated")
    parser.add_argument("--corpus-root", help="Corpus root; all nested run folders with scored_legs_deduped.csv will be processed")
    parser.add_argument("--gamelogs-path", required=True, help="Path to nba_gamelogs.csv")
    parser.add_argument("--output-name", default="eval_legs.csv", help="Output filename to write inside each run folder")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write files")
    args = parser.parse_args()

    gamelogs = load_gamelogs(Path(args.gamelogs_path))
    run_dirs = resolve_run_dirs(args)

    results = []
    for run_dir in run_dirs:
        result = process_run(run_dir, gamelogs, write=not args.dry_run, output_name=args.output_name)
        results.append(result)

    payload = {
        "runs_processed": len(results),
        "rows_total": sum(r.rows for r in results),
        "matched_rows_total": sum(r.matched_rows for r in results),
        "unmatched_rows_total": sum(r.unmatched_rows for r in results),
        "match_rate_total": (sum(r.matched_rows for r in results) / sum(r.rows for r in results)) if results else 0.0,
        "dry_run": bool(args.dry_run),
        "results": [r.__dict__ for r in results],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

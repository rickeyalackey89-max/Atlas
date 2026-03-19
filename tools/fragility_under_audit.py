from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

KEEP_STATS = {"PTS", "PRA", "PA", "PR", "RA", "REB"}
JOIN_KEYS = ["player", "stat", "direction", "line"]
VALUE_COLS = ["p_adj", "fragility", "q_blowout"]


def _norm_key_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in JOIN_KEYS:
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip()
    return out


def _find_run_dirs(corpus_input: Path) -> list[Path]:
    base = corpus_input / "runs" if (corpus_input / "runs").exists() else corpus_input
    return sorted(
        [
            p
            for p in base.iterdir()
            if p.is_dir() and (p / "eval_legs.csv").exists() and (p / "scored_legs_deduped.csv").exists()
        ],
        key=lambda p: p.name,
    )


def _coalesce_metric_cols(merged: pd.DataFrame) -> pd.DataFrame:
    out = merged.copy()
    for c in VALUE_COLS:
        if c in out.columns:
            continue
        left = f"{c}_x"
        right = f"{c}_y"
        if left in out.columns and right in out.columns:
            out[c] = out[left].combine_first(out[right])
        elif left in out.columns:
            out[c] = out[left]
        elif right in out.columns:
            out[c] = out[right]
        else:
            out[c] = pd.NA
    return out


def build_audit(corpus_input: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for run_dir in _find_run_dirs(corpus_input):
        eval_df = _norm_key_cols(pd.read_csv(run_dir / "eval_legs.csv"))
        scored_df = _norm_key_cols(pd.read_csv(run_dir / "scored_legs_deduped.csv"))

        cols = [c for c in JOIN_KEYS + VALUE_COLS if c in scored_df.columns]
        scored_small = scored_df[cols].drop_duplicates(JOIN_KEYS, keep="first")
        merged = eval_df.merge(scored_small, on=JOIN_KEYS, how="left")
        merged = _coalesce_metric_cols(merged)
        merged["run_id"] = run_dir.name
        frames.append(merged)

    if not frames:
        raise SystemExit(f"No valid run folders found under: {corpus_input}")

    df = pd.concat(frames, ignore_index=True)
    if "hit" not in df.columns:
        raise SystemExit("Merged corpus is missing required column: hit")
    if "stat" not in df.columns or "direction" not in df.columns:
        raise SystemExit("Merged corpus is missing required columns: stat and/or direction")

    df = df[df["hit"].notna()].copy()
    df = df[df["stat"].isin(KEEP_STATS)].copy()

    for c in VALUE_COLS + ["hit"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[
        df["p_adj"].notna() & df["fragility"].notna() & df["q_blowout"].notna() & df["hit"].notna()
    ].copy()

    df["fragility_bucket"] = pd.cut(
        df["fragility"],
        bins=[-1.0, 0.05, 0.10, 0.20, 999.0],
        labels=["0to05", "05to10", "10to20", "20plus"],
        include_lowest=True,
    )
    df["q_blowout_bucket"] = pd.cut(
        df["q_blowout"],
        bins=[-1.0, 0.10, 0.20, 0.35, 999.0],
        labels=["0to10", "10to20", "20to35", "35plus"],
        include_lowest=True,
    )

    grouped = (
        df.groupby(["stat", "direction", "fragility_bucket", "q_blowout_bucket"], dropna=False)
        .agg(rows=("hit", "size"), hit_rate=("hit", "mean"), mean_p_adj=("p_adj", "mean"))
        .reset_index()
    )
    grouped["gap"] = grouped["mean_p_adj"] - grouped["hit_rate"]
    grouped = grouped.sort_values(["stat", "direction", "fragility_bucket", "q_blowout_bucket"]).reset_index(drop=True)

    under_focus = grouped[
        (grouped["direction"].astype(str).str.upper() == "UNDER")
        & (grouped["fragility_bucket"].astype(str).isin(["10to20", "20plus"]))
        & (grouped["q_blowout_bucket"].astype(str).isin(["20to35", "35plus"]))
    ].copy()
    under_focus = under_focus.sort_values(["gap", "rows"]).reset_index(drop=True)

    return grouped, under_focus


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-input", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    corpus_input = Path(args.corpus_input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    grouped, under_focus = build_audit(corpus_input)

    grouped_path = output_dir / "fragility_qblowout_stat_direction.csv"
    under_path = output_dir / "fragility_under_focus.csv"
    grouped.to_csv(grouped_path, index=False)
    under_focus.to_csv(under_path, index=False)

    print(f"WROTE {grouped_path}")
    print(f"WROTE {under_path}")
    print(f"ROWS_ALL {len(grouped)}")
    print(f"ROWS_UNDER_FOCUS {len(under_focus)}")
    if not under_focus.empty:
        print(under_focus.head(20).to_string(index=False))


if __name__ == "__main__":
    main()

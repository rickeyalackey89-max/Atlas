"""
Share allocator accuracy diagnostic.

For every (team, out_player) the allocator has rows for, compare its predicted
redistribution weights against actual teammate production gains in historical
games when that player was missing.

Method
------
1. Load gamelogs.
2. For each (team, out_player) pair in the allocator output:
   a. Find game_dates where the out_player did NOT play (their team had a game
      but the player wasn't on the team's roster line for that date).
   b. Compute each teammate's per-game stat in those "without" games.
   c. Compute the same in "with" games.
   d. Delta = without - with (positive = teammate gained when player was out).
3. Normalize deltas by the out_player's actual avg stat (their absent share).
4. Compare to allocator-predicted weight.

Output
------
A long-form CSV with one row per (team, out_player, beneficiary, stat) and:
  predicted_weight, actual_lift, actual_share, n_with, n_without, bias

Bias = predicted_weight - actual_share. Positive means allocator over-predicts.

Aggregate metrics by class (star/core/role/bench) help decide whether to bump
transfer fractions up or down.

Usage
-----
    python tools/diagnose_share_allocator.py \
        --gamelogs data/gamelogs/nba_gamelogs.csv \
        --out data/output/diagnose/share_allocator_accuracy.csv \
        --min-with-games 8 --min-without-games 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add src to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from Atlas.model.team_share_allocator_v2 import (  # noqa: E402
    build_share_matrix_v2,
    _norm_team,
)
from Atlas.core.share_name_key import share_name_key  # noqa: E402


STAT_COLS = {"PTS": "pts", "REB": "reb", "AST": "ast"}


def _load_logs(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["team_u"] = df["team"].astype(str).map(_norm_team)
    df["player_key"] = df["player"].astype(str).map(share_name_key)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    for col in ("minutes", "pts", "reb", "ast"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df = df[df["game_date"].notna()].copy()
    return df


def _team_game_dates(logs: pd.DataFrame, team_u: str) -> pd.DatetimeIndex:
    """All game_dates the team played (any player row exists)."""
    return pd.DatetimeIndex(
        sorted(logs.loc[logs["team_u"] == team_u, "game_date"].unique())
    )


def diagnose(
    gamelogs_path: Path,
    out_path: Path,
    min_with_games: int = 8,
    min_without_games: int = 3,
    role_metrics_path: Path | None = None,
    iael_path: Path | None = None,
) -> pd.DataFrame:
    print(f"[diag] loading gamelogs from {gamelogs_path}")
    logs = _load_logs(gamelogs_path)
    print(f"[diag] {len(logs):,} rows, {logs['team_u'].nunique()} teams, "
          f"{logs['player_key'].nunique()} players, dates "
          f"{logs['game_date'].min().date()} -> {logs['game_date'].max().date()}")

    # Build a synthetic IAEL where every player who has >=10 games appears as
    # "OUT" so the allocator emits a row for them. We then compare to reality.
    print("[diag] building synthetic full-roster IAEL for allocator comparison")
    team_player = (
        logs[logs["minutes"] > 0]
        .groupby(["team_u", "player_key"], as_index=False)
        .agg(
            player=("player", "last"),
            games=("game_date", "nunique"),
        )
    )
    qualifying = team_player[team_player["games"] >= min_with_games].copy()
    print(f"[diag] {len(qualifying)} (team, player) pairs qualify (>={min_with_games} games)")

    # For each player, ask the allocator: "if this player were out today, how
    # would you redistribute their share?"
    # We do this by feeding the allocator one out at a time.
    role_metrics_df: pd.DataFrame | None = None
    if role_metrics_path and role_metrics_path.exists():
        try:
            role_metrics_df = pd.read_csv(role_metrics_path)
        except Exception:
            role_metrics_df = None

    diag_rows: list[dict] = []

    by_team = {t: g for t, g in logs.groupby("team_u")}

    for idx, row in qualifying.iterrows():
        team_u = str(row["team_u"])
        out_key = str(row["player_key"])
        out_display = str(row["player"])
        team_logs = by_team.get(team_u)
        if team_logs is None:
            continue

        # Identify with/without dates
        team_dates = _team_game_dates(team_logs, team_u)
        player_dates = pd.DatetimeIndex(
            sorted(team_logs.loc[team_logs["player_key"] == out_key, "game_date"].unique())
        )
        without_dates = team_dates.difference(player_dates)

        n_with = len(player_dates)
        n_without = len(without_dates)
        if n_with < min_with_games or n_without < min_without_games:
            continue

        # Out-player baseline (their actual avg stat when they played)
        out_avg = (
            team_logs.loc[team_logs["player_key"] == out_key]
            .groupby("player_key")
            .agg(avg_min=("minutes", "mean"), avg_pts=("pts", "mean"),
                 avg_reb=("reb", "mean"), avg_ast=("ast", "mean"))
        )
        if out_avg.empty:
            continue
        out_avg = out_avg.iloc[0].to_dict()

        # Synthetic IAEL: only this player out
        iael_df = pd.DataFrame([{
            "team": team_u, "player": out_display, "status": "OUT", "out_frac": 1.0,
        }])

        try:
            matrix = build_share_matrix_v2(
                logs[["game_date", "player", "team", "opp", "minutes", "pts", "reb", "ast", "usg_proxy"]],
                iael_df=iael_df,
                role_metrics_df=role_metrics_df,
                recent_days=140,
                min_pattern_games=1,
                keep_zero_weights=True,
            )
        except Exception as exc:
            print(f"[diag] allocator failed for {team_u}/{out_display}: {exc}")
            continue

        if matrix.empty:
            continue

        # For each beneficiary in the matrix, find their actual gain
        # Per-stat: actual_lift = (without_mean - with_mean) per game
        # actual_share = actual_lift / out_player's avg stat
        teammates = matrix["ben_canon"].unique().tolist()
        with_rows = team_logs[team_logs["game_date"].isin(player_dates)]
        without_rows = team_logs[team_logs["game_date"].isin(without_dates)]

        for stat_u, stat_col in STAT_COLS.items():
            out_stat = float(out_avg.get(f"avg_{stat_col}", 0.0))
            if out_stat <= 0.0:
                continue

            for ben_key in teammates:
                ben_with = with_rows[with_rows["player_key"] == ben_key]
                ben_without = without_rows[without_rows["player_key"] == ben_key]
                if len(ben_with) < min_with_games or len(ben_without) < min_without_games:
                    continue

                ben_with_mean = float(ben_with[stat_col].mean())
                ben_without_mean = float(ben_without[stat_col].mean())
                actual_lift = ben_without_mean - ben_with_mean
                actual_share = actual_lift / out_stat if out_stat > 0 else 0.0

                mr = matrix[(matrix["ben_canon"] == ben_key) & (matrix["stat_u"] == stat_u)]
                pred_weight = float(mr["weight"].sum()) if not mr.empty else 0.0

                diag_rows.append({
                    "team_u": team_u,
                    "out_player": out_display,
                    "out_key": out_key,
                    "ben_player": str(ben_with["player"].iloc[0]) if len(ben_with) else "",
                    "ben_key": ben_key,
                    "stat": stat_u,
                    "out_avg_stat": out_stat,
                    "out_avg_min": float(out_avg.get("avg_min", 0.0)),
                    "ben_with_mean": ben_with_mean,
                    "ben_without_mean": ben_without_mean,
                    "actual_lift": actual_lift,
                    "actual_share": actual_share,
                    "predicted_weight": pred_weight,
                    "bias": pred_weight - actual_share,
                    "n_with": int(len(ben_with)),
                    "n_without": int(len(ben_without)),
                })

        if idx % 25 == 0:
            print(f"[diag] processed {idx+1}/{len(qualifying)} ({team_u}/{out_display})")

    out_df = pd.DataFrame(diag_rows)
    if out_df.empty:
        print("[diag] no diagnostic rows produced")
        return out_df

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)
    print(f"[diag] wrote {len(out_df):,} rows to {out_path}")

    # Summary
    print("\n=== Allocator Accuracy Summary ===")
    print(f"Total comparisons: {len(out_df):,}")
    print(f"Mean predicted_weight: {out_df['predicted_weight'].mean():.4f}")
    print(f"Mean actual_share:     {out_df['actual_share'].mean():.4f}")
    print(f"Mean bias (pred-actual): {out_df['bias'].mean():+.4f}")
    print(f"Median bias:             {out_df['bias'].median():+.4f}")
    print(f"Bias stdev:              {out_df['bias'].std():.4f}")
    print()
    print("Per-stat breakdown:")
    for stat in ["PTS", "REB", "AST"]:
        sub = out_df[out_df["stat"] == stat]
        if len(sub) == 0:
            continue
        print(f"  {stat}: N={len(sub):,}  "
              f"pred={sub['predicted_weight'].mean():.4f}  "
              f"actual={sub['actual_share'].mean():.4f}  "
              f"bias={sub['bias'].mean():+.4f}")
    print()
    print("Bias by out-player avg minutes bucket (proxy for class):")
    out_df["min_bucket"] = pd.cut(
        out_df["out_avg_min"],
        bins=[0, 14, 24, 30, 100],
        labels=["bench", "role", "core", "star"],
    )
    for label in ["star", "core", "role", "bench"]:
        sub = out_df[out_df["min_bucket"] == label]
        if len(sub) == 0:
            continue
        print(f"  {label:6s}: N={len(sub):,}  "
              f"pred={sub['predicted_weight'].mean():.4f}  "
              f"actual={sub['actual_share'].mean():.4f}  "
              f"bias={sub['bias'].mean():+.4f}")

    # === SUM and MAX views ===
    # Per (team, out_player, stat) — total transfer (sum) and top beneficiary (max)
    print("\n=== Per-Outage Aggregates (per team/out/stat) ===")
    grp = out_df.groupby(["team_u", "out_player", "stat", "min_bucket"], observed=True).agg(
        sum_pred=("predicted_weight", "sum"),
        sum_actual=("actual_share", "sum"),
        max_pred=("predicted_weight", "max"),
        max_actual=("actual_share", "max"),
        n_ben=("predicted_weight", "size"),
    ).reset_index()

    print("\nTotal redistribution (sum across all beneficiaries) by class & stat:")
    print(f"  {'class':6s} {'stat':4s} {'N':>5s}  {'sum_pred':>10s}  {'sum_actual':>10s}  {'gap':>8s}")
    for label in ["star", "core", "role", "bench"]:
        for stat in ["PTS", "REB", "AST"]:
            sub = grp[(grp["min_bucket"] == label) & (grp["stat"] == stat)]
            if len(sub) == 0:
                continue
            sp = sub["sum_pred"].mean()
            sa = sub["sum_actual"].mean()
            print(f"  {label:6s} {stat:4s} {len(sub):>5d}  {sp:>10.4f}  {sa:>10.4f}  {sp - sa:>+8.4f}")

    print("\nTop beneficiary (max across beneficiaries) by class & stat:")
    print(f"  {'class':6s} {'stat':4s} {'N':>5s}  {'max_pred':>10s}  {'max_actual':>10s}  {'gap':>8s}")
    for label in ["star", "core", "role", "bench"]:
        for stat in ["PTS", "REB", "AST"]:
            sub = grp[(grp["min_bucket"] == label) & (grp["stat"] == stat)]
            if len(sub) == 0:
                continue
            mp = sub["max_pred"].mean()
            ma = sub["max_actual"].mean()
            print(f"  {label:6s} {stat:4s} {len(sub):>5d}  {mp:>10.4f}  {ma:>10.4f}  {mp - ma:>+8.4f}")

    return out_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gamelogs", type=Path, default=Path("data/gamelogs/nba_gamelogs.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/output/diagnose/share_allocator_accuracy.csv"))
    ap.add_argument("--min-with-games", type=int, default=8)
    ap.add_argument("--min-without-games", type=int, default=3)
    ap.add_argument("--role-metrics", type=Path, default=None)
    args = ap.parse_args()
    diagnose(args.gamelogs, args.out,
             min_with_games=args.min_with_games,
             min_without_games=args.min_without_games,
             role_metrics_path=args.role_metrics)


if __name__ == "__main__":
    main()

"""
A) Upstream kernel input investigation for MIN @ SAS on 2026-05-06.

Goal: determine whether the blowout / minutes-collapse signal was
   - PRESENT AND IGNORED  (kernel saw it but didn't bend probabilities)
   - ABSENT  (rotowire spread / IAEL didn't carry the signal)
   - PARTIAL (signal present but magnitude too small)

Compares:
  1. q_blowout, fragility, minutes_s, usage_dep, spread, game_total
     for the offenders (Dosunmu, Reid, Castle, Champagnie) on 05-06
     vs the same players' last 5 games and corpus median.
  2. Their actual gamelog row for 2026-05-06 (minutes played, points,
     rebounds, etc.) -- did they DNP, get blown out, or just regress?
  3. The full set of 05-06 OVER legs sorted by p_adj * (1-hit) to
     identify systemic over-projection.
"""
from __future__ import annotations

import pathlib
import pickle
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.options.display.float_format = "{:.4f}".format
pd.options.display.width = 220
pd.options.display.max_columns = 50

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_PATH    = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
GAMELOGS_PATH = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
TARGET_DATE   = "2026-05-06"
TARGET_TEAMS  = {"MIN", "SAS"}
OFFENDERS = ["Ayo Dosunmu", "Naz Reid", "Stephon Castle",
             "Julian Champagnie", "Dylan Harper", "Jaden McDaniels",
             "Devin Vassell", "Harrison Barnes"]


def load_cache():
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv["game_date"] = cv["game_date"].astype(str).str[:10]
    return cv


def load_gamelogs():
    if not GAMELOGS_PATH.exists():
        print(f"WARN: gamelogs not found at {GAMELOGS_PATH}")
        return None
    g = pd.read_csv(GAMELOGS_PATH, low_memory=False)
    # Normalize column names
    g.columns = [c.strip() for c in g.columns]
    return g


def main() -> int:
    print("=" * 90)
    print(f"Upstream kernel input investigation: MIN @ SAS on {TARGET_DATE}")
    print("=" * 90)

    cv = load_cache()
    target = cv[cv["game_date"] == TARGET_DATE].reset_index(drop=True)
    minsas = target[target["team"].isin(TARGET_TEAMS)].reset_index(drop=True)

    # ---------- 1. Game-level kernel inputs ----------
    print()
    print("=" * 90)
    print("1. Game-level kernel inputs (per team on 05-06)")
    print("=" * 90)
    gcols = ["spread", "game_total", "q_blowout", "margin"]
    gcols = [c for c in gcols if c in target.columns]
    by_team = (target.groupby("team")[gcols].agg(["mean", "min", "max"])
               .round(4))
    print(by_team.to_string())
    print()
    print("Compare to corpus medians:")
    others = cv[cv["game_date"] != TARGET_DATE]
    print(others[gcols].median().to_frame("corpus_median").T.to_string())
    print(others[gcols].quantile(0.95).to_frame("corpus_p95").T.to_string())
    print()

    # ---------- 2. Per-offender kernel state ----------
    print("=" * 90)
    print("2. Per-offender kernel state on 05-06 (one row per leg)")
    print("=" * 90)
    cols = ["player", "team", "stat", "line", "direction", "tier",
            "p", "p_role", "p_adj", "p_for_cal", "hit",
            "q_blowout", "fragility", "minutes_s", "usage_dep",
            "is_star", "spread", "game_total",
            "role_ctx_mult", "role_ctx_outs_used"]
    cols = [c for c in cols if c in target.columns]
    sub = minsas[minsas["player"].isin(OFFENDERS)].reset_index(drop=True)
    sub = sub.sort_values(["player", "stat"])
    # Show only one example per player+stat (representative)
    print(sub[cols].to_string(index=False))
    print()

    # ---------- 3. Per-offender summary ----------
    print("=" * 90)
    print("3. Offender summary (averaged per leg type)")
    print("=" * 90)
    summary_cols = [c for c in ["p_adj", "q_blowout", "fragility", "minutes_s",
                                 "usage_dep", "is_star", "spread", "game_total"]
                    if c in target.columns]
    rows = []
    for p in OFFENDERS:
        pl = minsas[minsas["player"] == p]
        if pl.empty:
            continue
        row = {"player": p, "n_legs": len(pl), "hit_rate": pl["hit"].mean()}
        for c in summary_cols:
            row[c] = pl[c].mean()
        rows.append(row)
    df_sum = pd.DataFrame(rows)
    print(df_sum.to_string(index=False))
    print()

    # ---------- 4. Compare to player history ----------
    print("=" * 90)
    print("4. Each offender's own kernel history (prior dates in cache)")
    print("=" * 90)
    for p in OFFENDERS:
        h = cv[(cv["player"] == p) & (cv["game_date"] < TARGET_DATE)]
        on506 = minsas[minsas["player"] == p]
        if h.empty or on506.empty:
            continue
        rec = {
            "player": p,
            "n_prior_dates": h["game_date"].nunique(),
            "p_adj_mean_prior": h["p_adj"].mean(),
            "p_adj_mean_05-06": on506["p_adj"].mean(),
            "minutes_s_prior": h["minutes_s"].mean() if "minutes_s" in h else np.nan,
            "minutes_s_05-06": on506["minutes_s"].mean() if "minutes_s" in on506 else np.nan,
            "q_blowout_prior": h["q_blowout"].mean() if "q_blowout" in h else np.nan,
            "q_blowout_05-06": on506["q_blowout"].mean() if "q_blowout" in on506 else np.nan,
            "fragility_prior": h["fragility"].mean() if "fragility" in h else np.nan,
            "fragility_05-06": on506["fragility"].mean() if "fragility" in on506 else np.nan,
            "hit_prior": h["hit"].mean(),
            "hit_05-06": on506["hit"].mean(),
        }
        print(f"  {p}")
        for k, v in rec.items():
            if k == "player":
                continue
            if isinstance(v, float):
                print(f"     {k:<22} {v:.4f}")
            else:
                print(f"     {k:<22} {v}")
        print()

    # ---------- 5. Actual game log results ----------
    print("=" * 90)
    print("5. Actual gamelog: did they DNP / get blown out / just regress?")
    print("=" * 90)
    g = load_gamelogs()
    if g is not None:
        # Find date column
        date_col = None
        for c in ["game_date", "GAME_DATE", "date", "Date"]:
            if c in g.columns:
                date_col = c
                break
        if date_col is None:
            print("WARN: could not find date column in gamelogs")
        else:
            g[date_col] = g[date_col].astype(str).str[:10]
            # find player column
            pcol = None
            for c in ["player", "PLAYER_NAME", "PLAYER", "Player"]:
                if c in g.columns:
                    pcol = c
                    break
            day = g[g[date_col] == TARGET_DATE]
            mask = day[pcol].isin(OFFENDERS) if pcol else None
            if mask is not None:
                day = day[mask]
            # show key stat columns
            keep = [c for c in [pcol, "team", "TEAM_ABBREVIATION", "matchup",
                                "MATCHUP", "MIN", "minutes", "PTS", "REB", "AST",
                                "FG3M", "PA", "PR", "PRA", "RA", "PLUS_MINUS",
                                "WL"] if c and c in day.columns]
            if not day.empty:
                print(day[keep].to_string(index=False))
            else:
                print(f"No gamelog rows for offenders on {TARGET_DATE}")
                # try a broader look
                print(f"All gamelog rows on {TARGET_DATE} for MIN/SAS:")
                team_col = "TEAM_ABBREVIATION" if "TEAM_ABBREVIATION" in g.columns else (
                    "team" if "team" in g.columns else None)
                if team_col:
                    sl = g[(g[date_col] == TARGET_DATE) &
                           (g[team_col].isin(["MIN", "SAS"]))]
                    keep2 = [c for c in [pcol, team_col, "MATCHUP", "matchup",
                                          "MIN", "minutes", "PTS", "PLUS_MINUS",
                                          "WL"] if c and c in sl.columns]
                    print(sl[keep2].to_string(index=False))
    print()

    # ---------- 6. Universal 05-06 OVER overprojection ----------
    print("=" * 90)
    print("6. Top 30 OVER legs on 05-06 by 'overconfidence damage' = p_adj * (1 - hit)")
    print("=" * 90)
    over = target[target["direction"] == "OVER"].copy()
    over["damage"] = over["p_adj"] * (1 - over["hit"])
    cols2 = ["player", "team", "stat", "line", "tier", "p_adj", "hit",
             "q_blowout", "fragility", "minutes_s", "spread"]
    cols2 = [c for c in cols2 if c in over.columns]
    print(over.sort_values("damage", ascending=False).head(30)[cols2].to_string(index=False))
    print()

    # ---------- 7. Verdict ----------
    print("=" * 90)
    print("7. Aggregated kernel signal: was the blowout signal present?")
    print("=" * 90)
    if "q_blowout" in target.columns:
        for team in ["MIN", "SAS"]:
            t = target[target["team"] == team]
            o = others[others["team"] == team] if "team" in others.columns else others
            print(f"  {team}: q_blowout mean 05-06 = {t['q_blowout'].mean():.4f}  | "
                  f"player corpus mean = {o['q_blowout'].mean():.4f}  | "
                  f"delta = {(t['q_blowout'].mean() - o['q_blowout'].mean())*1000:+.2f} mU")
    if "spread" in target.columns:
        for team in ["MIN", "SAS"]:
            t = target[target["team"] == team]
            print(f"  {team}: spread on 05-06 = {t['spread'].mean():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

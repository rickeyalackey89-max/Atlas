"""
cache_eval_optimizer_criteria.py

Apply the improved_slip_optimizer filtering criteria directly to cache truth data.
This tells us exactly what hit rates those filters produce on our own historical data.
"""

import pickle
import numpy as np
import pandas as pd
from pathlib import Path

CACHE_PATH = Path("data/model/_v17_resim_cache.pkl")

GOOD_STANDARD_STATS = {"PTS", "PA", "PRA", "PR", "REB", "AST"}
RISKY_STANDARD_STATS = {"RA", "STL", "BLK", "FG3M", "TO"}


def load_cache():
    print(f"Loading cache: {CACHE_PATH}")
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    df = cache["cv"]
    print(f"  {len(df):,} legs across {len(cache['dates'])} dates ({min(cache['dates'])} - {max(cache['dates'])})")
    return df


def apply_improved_filters(df):
    """Apply the same filters the improved_slip_optimizer uses."""

    # --- GOBLIN legs ---
    goblin = df[df["tier"] == "GOBLIN"].copy()
    goblin_filtered = goblin[goblin["p_cal"] >= 0.55]

    # --- STANDARD legs (improved criteria) ---
    standard = df[df["tier"] == "STANDARD"].copy()
    standard["good_stat"] = standard["stat"].isin(GOOD_STANDARD_STATS)
    standard["risky_stat"] = standard["stat"].isin(RISKY_STANDARD_STATS)
    standard["is_under"] = standard["direction"] == "UNDER"

    # Improved filter: p_cal >= 0.55, good stat, prefer UNDER
    std_filtered = standard[
        (standard["p_cal"] >= 0.55) &
        (standard["good_stat"]) &
        (~standard["risky_stat"])
    ]

    std_filtered_under = std_filtered[std_filtered["is_under"]]
    std_filtered_over  = std_filtered[~std_filtered["is_under"]]

    return goblin, goblin_filtered, standard, std_filtered, std_filtered_under, std_filtered_over


def print_section(title):
    print(f"\n{'='*60}")
    print(title)
    print(f"{'='*60}")


def hit_summary(label, subset):
    n = len(subset)
    if n == 0:
        print(f"  {label}: 0 legs (no data)")
        return 0.0
    hr = subset["hit"].mean()
    print(f"  {label}: {hr:.1%} hit rate  (N={n:,})")
    return hr


def main():
    df = load_cache()

    # require truth label
    if "hit" not in df.columns:
        print("ERROR: 'hit' column missing from cache — cannot evaluate.")
        return

    df = df[df["hit"].notna()].copy()
    print(f"  Legs with truth labels: {len(df):,}")

    goblin, goblin_filtered, standard, std_filtered, std_filtered_under, std_filtered_over = apply_improved_filters(df)

    # ----------------------------------------------------------------
    print_section("GOBLIN LEGS")
    hr_gob_all      = hit_summary("All GOBLIN (baseline)",      goblin)
    hr_gob_filtered = hit_summary("GOBLIN  p_cal >= 55% only",  goblin_filtered)

    # ----------------------------------------------------------------
    print_section("STANDARD LEGS")
    hr_std_all    = hit_summary("All STANDARD (baseline)",                    standard)
    hr_std_filt   = hit_summary("Improved filter (p_cal>=55%, good stat)",    std_filtered)
    hr_std_under  = hit_summary("Improved filter + UNDER only",               std_filtered_under)
    hr_std_over   = hit_summary("Improved filter + OVER  only",               std_filtered_over)

    # --- by stat for filtered standard ---
    print(f"\n  Improved-filtered STANDARD hit rate by stat:")
    for stat, grp in std_filtered.groupby("stat"):
        n = len(grp)
        hr = grp["hit"].mean()
        arrow = "✅" if hr >= 0.52 else "⚠️"
        print(f"    {arrow} {stat:8s}  {hr:.1%}  (N={n:,})")

    # --- by direction for filtered standard ---
    print(f"\n  Improved-filtered STANDARD hit rate by direction:")
    for dir_, grp in std_filtered.groupby("direction"):
        n = len(grp)
        hr = grp["hit"].mean()
        print(f"    {dir_:6s}  {hr:.1%}  (N={n:,})")

    # ----------------------------------------------------------------
    print_section("SIMULATED SLIP WIN RATES (cache-based)")

    # For each date simulate picking top-3/4/5 GOBLIN + improved STANDARD
    dates = sorted(df["game_date"].unique())
    print(f"  Simulating slips across {len(dates)} dates...")

    results_3 = []
    results_4 = []
    results_5 = []

    for date in dates:
        day = df[df["game_date"] == date]

        g = day[(day["tier"] == "GOBLIN") & (day["p_cal"] >= 0.55)].sort_values("p_cal", ascending=False)
        s = day[
            (day["tier"] == "STANDARD") &
            (day["p_cal"] >= 0.55) &
            (day["stat"].isin(GOOD_STANDARD_STATS)) &
            (~day["stat"].isin(RISKY_STANDARD_STATS)) &
            (day["direction"] == "UNDER")
        ].sort_values("p_cal", ascending=False)

        # Fallback: include OVER standard if not enough UNDER
        s_all = day[
            (day["tier"] == "STANDARD") &
            (day["p_cal"] >= 0.55) &
            (day["stat"].isin(GOOD_STANDARD_STATS)) &
            (~day["stat"].isin(RISKY_STANDARD_STATS))
        ].sort_values("p_cal", ascending=False)

        gob_legs = g.head(3)
        std_legs = s.head(2)
        if len(std_legs) < 2:
            std_legs = s_all.head(2)

        # --- 3-leg: 2 GOBLIN + 1 STANDARD ---
        if len(gob_legs) >= 2 and len(std_legs) >= 1:
            legs = pd.concat([gob_legs.head(2), std_legs.head(1)])
            win = int(legs["hit"].all())
            results_3.append({"date": date, "win": win, "n_legs": len(legs)})

        # --- 4-leg: 2 GOBLIN + 2 STANDARD ---
        if len(gob_legs) >= 2 and len(std_legs) >= 2:
            legs = pd.concat([gob_legs.head(2), std_legs.head(2)])
            win = int(legs["hit"].all())
            results_4.append({"date": date, "win": win, "n_legs": len(legs)})

        # --- 5-leg: 3 GOBLIN + 2 STANDARD ---
        if len(gob_legs) >= 3 and len(std_legs) >= 2:
            legs = pd.concat([gob_legs.head(3), std_legs.head(2)])
            win = int(legs["hit"].all())
            results_5.append({"date": date, "win": win, "n_legs": len(legs)})

    def report(label, results, payout):
        if not results:
            print(f"  {label}: no data")
            return
        df_r = pd.DataFrame(results)
        wins  = df_r["win"].sum()
        total = len(df_r)
        win_rate = wins / total
        ev = win_rate * payout
        print(f"\n  {label} ({payout}x payout)")
        print(f"    Dates simulated : {total}")
        print(f"    Slips won       : {wins}/{total}  ({win_rate:.1%})")
        print(f"    EV              : {ev:.2f}x  ({'✅ PROFITABLE' if ev > 1.0 else '❌ LOSING'})")

    report("3-leg slip (2G+1S)",  results_3, 3.5)
    report("4-leg slip (2G+2S)",  results_4, 10.0)
    report("5-leg slip (3G+2S)",  results_5, 20.0)

    # ----------------------------------------------------------------
    print_section("BASELINE COMPARISON (unfiltered slips)")

    base_3 = []
    base_4 = []
    base_5 = []

    for date in dates:
        day = df[df["game_date"] == date]
        g_any = day[(day["tier"] == "GOBLIN")].sort_values("p_cal", ascending=False)
        s_any = day[(day["tier"] == "STANDARD")].sort_values("p_cal", ascending=False)

        if len(g_any) >= 2 and len(s_any) >= 1:
            legs = pd.concat([g_any.head(2), s_any.head(1)])
            base_3.append({"win": int(legs["hit"].all())})

        if len(g_any) >= 2 and len(s_any) >= 2:
            legs = pd.concat([g_any.head(2), s_any.head(2)])
            base_4.append({"win": int(legs["hit"].all())})

        if len(g_any) >= 3 and len(s_any) >= 2:
            legs = pd.concat([g_any.head(3), s_any.head(2)])
            base_5.append({"win": int(legs["hit"].all())})

    def report_base(label, results, payout):
        if not results:
            return
        df_r = pd.DataFrame(results)
        wins  = df_r["win"].sum()
        total = len(df_r)
        win_rate = wins / total
        ev = win_rate * payout
        print(f"  {label} ({payout}x): {wins}/{total} ({win_rate:.1%})  EV={ev:.2f}x")

    report_base("3-leg baseline", base_3, 3.5)
    report_base("4-leg baseline", base_4, 10.0)
    report_base("5-leg baseline", base_5, 20.0)

    print(f"\n{'='*60}")
    print("DONE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

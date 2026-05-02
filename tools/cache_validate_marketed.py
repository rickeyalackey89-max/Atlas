"""
cache_validate_marketed.py

Full cache validation of marketed slip builder across all available dates.
Uses the actual MarketedSlipBuilder class from src/ for production fidelity.

Results show:
  - Per-template win rates (actual vs predicted)
  - Per-stat calibration gaps across all qualified legs
  - Calibration gaps by p_cal_marketed tier bucket
  - Recommended threshold and calibration adjustments
"""

import sys
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# ------------------------------------------------------------------ #
#  CONFIG TO TEST -- mirror of config.yaml marketed_slips section
# ------------------------------------------------------------------ #
TEST_CONFIG = {
    "marketed_slips": {
        "enabled": True,
        "calibration_path": "data/model/marketed_calibration.json",
        "excluded_stats": ["BLK", "STL", "TO"],
        "min_thresholds": {
            "GOBLIN":   0.60,
            "STANDARD": 0.40,
            "DEMON":    0.45,
        },
        "direction_filters": {},
        "correlation": {
            "same_team_penalty": 0.03,
            "hedge_bonus": 0.015,
            "blowout_penalty": 0.02,
        },
    }
}


def load_cache():
    p = Path("data/model/_v17_resim_cache.pkl")
    with open(p, "rb") as f:
        cache = pickle.load(f)
    return cache["cv"], sorted(cache["dates"])


def run_validation(config, dates_to_test=None):
    cv, all_dates = load_cache()
    dates = dates_to_test or all_dates

    builder = MarketedSlipBuilder(config)

    slip_results = []          # per slip
    leg_results  = []          # per qualified leg (for calibration diagnostics)

    print(f"Testing on {len(dates)} dates ...\n")

    for date in dates:
        df_date = cv[cv["game_date"] == date].copy()
        if len(df_date) == 0:
            continue

        # Apply calibration (adds p_cal_marketed column)
        df_cal = builder._apply_stat_calibration(df_date)

        # Qualify legs
        pool = builder._qualify_legs(df_cal)
        if pool.empty:
            continue

        # Collect individual leg truth data
        for _, leg in pool.iterrows():
            leg_results.append({
                "date":             date,
                "player":           leg["player"],
                "stat":             leg["stat"],
                "tier":             leg["tier"],
                "direction":        leg["direction"],
                "p_cal":            leg["p_cal"],
                "p_cal_marketed":   leg["p_cal_marketed"],
                "marketed_score":   leg.get("marketed_score", float("nan")),
                "hit":              int(leg["hit"]),
            })

        # Build slips (uses global player/team constraints)
        slips = builder.build_slips(df_date)

        for slip in slips:
            # Actual outcome: all legs must hit
            all_hit = all(
                int(cv.loc[
                    (cv["game_date"] == date) &
                    (cv["player"]    == leg["player"]) &
                    (cv["stat"]      == leg["stat"]) &
                    (cv["direction"] == leg["direction"]),
                    "hit"
                ].iloc[0])
                if len(cv.loc[
                    (cv["game_date"] == date) &
                    (cv["player"]    == leg["player"]) &
                    (cv["stat"]      == leg["stat"]) &
                    (cv["direction"] == leg["direction"]),
                    "hit"
                ]) > 0
                else 0
                for leg in slip["legs"]
            )

            slip_results.append({
                "date":         date,
                "label":        slip["label"],
                "n_legs":       slip["n_legs"],
                "pred_prob":    slip["hit_prob"],
                "payout_mult":  slip["payout_mult"],
                "ev":           slip["ev"],
                "won":          int(all_hit),
            })

    return pd.DataFrame(leg_results), pd.DataFrame(slip_results)


def print_report(leg_df, slip_df):
    print("=" * 60)
    print("MARKETED SLIPS CACHE VALIDATION")
    print(f"Dates: {slip_df['date'].nunique()}  |  Total slips: {len(slip_df)}")
    print("=" * 60)

    # Slip win rates by template
    print("\n[SLIP WIN RATES BY TEMPLATE]")
    print(f"{'Template':<18} {'N':>4} {'Won':>4} {'Actual':>8} {'Pred':>8} {'CalGap':>8} {'AvgPayout':>10}")
    print("-" * 62)

    for label, g in slip_df.groupby("label"):
        n       = len(g)
        won     = g["won"].sum()
        actual  = won / n
        pred    = g["pred_prob"].mean()
        cal_gap = actual - pred
        avg_pay = g["payout_mult"].mean()
        print(f"  {label:<16} {n:>4} {won:>4} {actual:>8.1%} {pred:>8.1%} {cal_gap:>+8.1%} {avg_pay:>10.2f}x")

    # Overall
    n   = len(slip_df)
    won = slip_df["won"].sum()
    print("-" * 62)
    print(f"  {'OVERALL':<16} {n:>4} {won:>4} {won/n:>8.1%} {slip_df['pred_prob'].mean():>8.1%} {won/n - slip_df['pred_prob'].mean():>+8.1%}")

    # Individual leg calibration
    print("\n[INDIVIDUAL LEG CALIBRATION BY TIER]")
    print(f"{'Tier':<10} {'N':>5} {'Actual':>8} {'PredRaw':>8} {'PredAdj':>8} {'GapRaw':>8} {'GapAdj':>8}")
    print("-" * 57)
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        g = leg_df[leg_df["tier"] == tier]
        if len(g) < 5:
            continue
        actual   = g["hit"].mean()
        pred_raw = g["p_cal"].mean()
        pred_adj = g["p_cal_marketed"].mean()
        print(f"  {tier:<8} {len(g):>5} {actual:>8.1%} {pred_raw:>8.1%} {pred_adj:>8.1%} "
              f"{actual - pred_raw:>+8.1%} {actual - pred_adj:>+8.1%}")

    # Calibration by stat
    print("\n[INDIVIDUAL LEG CALIBRATION BY STAT (N>=20)]")
    print(f"{'Stat':<6} {'N':>5} {'Actual':>8} {'PredAdj':>8} {'GapAdj':>8}  Status")
    print("-" * 50)
    for stat, g in leg_df.groupby("stat"):
        if len(g) < 20:
            continue
        actual   = g["hit"].mean()
        pred_adj = g["p_cal_marketed"].mean()
        gap      = actual - pred_adj
        status   = "[ok]" if abs(gap) < 0.03 else ("[over]" if gap < 0 else "[under]")
        print(f"  {stat:<4} {len(g):>5} {actual:>8.1%} {pred_adj:>8.1%} {gap:>+8.1%}  {status}")

    # p_cal_marketed bucket calibration
    print("\n[LEG CALIBRATION BY p_cal_marketed BUCKET]")
    print(f"{'Bucket':<12} {'N':>5} {'Actual':>8} {'PredAdj':>8} {'GapAdj':>8}")
    print("-" * 45)
    bins   = [0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
    labels = ["<0.50","0.50-0.55","0.55-0.60","0.60-0.65","0.65-0.70","0.70-0.75","0.75-0.80",">=0.80"]
    leg_df["bucket"] = pd.cut(leg_df["p_cal_marketed"], bins=bins, labels=labels)
    for bucket, g in leg_df.groupby("bucket", observed=True):
        if len(g) < 10:
            continue
        actual   = g["hit"].mean()
        pred_adj = g["p_cal_marketed"].mean()
        print(f"  {str(bucket):<10} {len(g):>5} {actual:>8.1%} {pred_adj:>8.1%} {actual-pred_adj:>+8.1%}")

    # Daily win summary
    print("\n[DAILY DETAIL (slips built / won)]")
    print(f"{'Date':<12} {'Built':>6} {'Won':>4}  Templates")
    print("-" * 50)
    for date, g in slip_df.groupby("date"):
        won_labels = " ".join(r["label"] for _, r in g[g["won"] == 1].iterrows())
        labels_str = " | ".join(r["label"] for _, r in g.iterrows())
        print(f"  {date}  {len(g):>4}  {g['won'].sum():>3}  {won_labels or '--'}  [{labels_str}]")

    # Recommendations
    print("\n[CALIBRATION RECOMMENDATIONS]")
    for stat, g in leg_df.groupby("stat"):
        if len(g) < 20:
            continue
        for tier in ["GOBLIN", "STANDARD", "DEMON"]:
            tg = g[g["tier"] == tier]
            if len(tg) < 10:
                continue
            actual   = tg["hit"].mean()
            pred_adj = tg["p_cal_marketed"].mean()
            gap      = actual - pred_adj
            if abs(gap) > 0.04:
                current_mult = tg["p_cal_marketed"].mean() / tg["p_cal"].mean() if tg["p_cal"].mean() > 0 else 1.0
                suggested    = current_mult * (actual / pred_adj) if pred_adj > 0 else current_mult
                print(f"  {stat}/{tier}: gap={gap:+.3f} -> suggested multiplier {current_mult:.3f} -> {suggested:.3f}")


if __name__ == "__main__":
    leg_df, slip_df = run_validation(TEST_CONFIG)

    if slip_df.empty:
        print("No slips built -- check thresholds or direction_filters")
        sys.exit(1)

    print_report(leg_df, slip_df)

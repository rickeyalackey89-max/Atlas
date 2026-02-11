import os
from itertools import combinations

import pandas as pd
import matplotlib.pyplot as plt
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMPARE_PATH = os.path.join(ROOT, "data", "output", "scored_legs_compare.csv")

OUT_DIR = os.path.join(ROOT, "data", "output", "latest", "all")
OUT_PNG = os.path.join(OUT_DIR, "top3_parlays_hitprob_ev.png")
OUT_CSV = os.path.join(OUT_DIR, "top3_parlays_details.csv")
OUT_XLSX = os.path.join(OUT_DIR, "report_top3_parlays.xlsx")

N_LEGS = 3
ALLOWED_TIERS = {"STRONG", "GOOD"}
POOL_SIZE = 50

# --- Your 3-pick payout assumption (edit if needed)
# If PrizePicks 3-pick power pays 5x (common), profit on win = +4 units (stake returned separately).
# We compute EV in "net units" per 1 unit stake:
# EV = p_win * profit_on_win + (1 - p_win) * (-1)
PROFIT_ON_WIN = 4.0  # 5x total return => +4 profit per 1 stake


DEFINITIONS = pd.DataFrame(
    [
        ["p_adj", "Simulated hit probability after blowout/minutes adjustment"],
        ["p_eff", "Optimizer 'effective' probability used for ranking/edges (post-feature adjustments)"],
        ["p_combo", "Combined score from p_adj + p_eff, penalized when they disagree"],
        ["agreement_gap", "|p_eff - p_adj| (disagreement magnitude)"],
        ["agreement_tier", "STRONG/GOOD/MIXED/DISAGREE/NO_EFF based on value + agreement"],
        ["parlay_p_hit", "Approx parlay hit probability = product of p_combo across legs"],
        ["parlay_ev", "Expected value (net units per 1 unit stake), using PROFIT_ON_WIN"],
    ],
    columns=["field", "meaning"],
)


def fmt_leg_short(l: dict) -> str:
    return f"{l['player']} {l['direction']} {l['stat']} {l['line']}"


def compute_ev(p_win: float) -> float:
    # Net EV per 1 unit stake
    return p_win * PROFIT_ON_WIN + (1.0 - p_win) * (-1.0)


def main():
    if not os.path.exists(COMPARE_PATH):
        raise FileNotFoundError(f"Missing {COMPARE_PATH}. Run python run_today.py first.")

    df = pd.read_csv(COMPARE_PATH)

    for c in ["player", "stat", "direction", "line", "p_combo", "p_adj"]:
        if c not in df.columns:
            raise ValueError(f"compare file missing required column: {c}")

    if "p_eff" not in df.columns:
        df["p_eff"] = pd.NA
    if "agreement_tier" not in df.columns:
        df["agreement_tier"] = "UNKNOWN"

    # numeric conversions
    df["p_combo"] = pd.to_numeric(df["p_combo"], errors="coerce")
    df["p_adj"] = pd.to_numeric(df["p_adj"], errors="coerce")
    df["p_eff"] = pd.to_numeric(df["p_eff"], errors="coerce")

    df = df[df["p_combo"].notna()].copy()

    # tier filter
    df = df[df["agreement_tier"].isin(ALLOWED_TIERS)].copy()
    if df.empty:
        print("No rows left after tier filtering. Loosen ALLOWED_TIERS in the script.")
        return

    # reduce search space
    df = df.sort_values("p_combo", ascending=False).head(POOL_SIZE).copy()

    df["leg_str"] = (
        df["player"].astype(str).str.strip()
        + " "
        + df["direction"].astype(str).str.upper().str.strip()
        + " "
        + df["stat"].astype(str).str.upper().str.strip()
        + " "
        + df["line"].astype(str)
    )

    rows = df.to_dict("records")

    # enumerate parlays
    best = []
    for idxs in combinations(range(len(rows)), N_LEGS):
        legs = [rows[i] for i in idxs]

        # unique players
        players = [l["player"] for l in legs]
        if len(set(players)) != len(players):
            continue

        p_hit = 1.0
        for l in legs:
            p_hit *= float(l["p_combo"])

        ev = compute_ev(p_hit)
        best.append((ev, p_hit, legs))

    if not best:
        print("No valid parlays found (increase POOL_SIZE or loosen tier filter).")
        return

    # choose top 3 by EV (money), not by hit prob
    best.sort(key=lambda x: x[0], reverse=True)
    top3 = best[:3]

    # build details table
    os.makedirs(OUT_DIR, exist_ok=True)

    detail_rows = []
    parlay_rows = []

    for rank, (ev, p_hit, legs) in enumerate(top3, start=1):
        parlay_rows.append({
            "parlay_rank": rank,
            "parlay_p_hit(product of p_combo)": p_hit,
            "parlay_ev(net units per 1 stake)": ev,
            "profit_on_win_assumption": PROFIT_ON_WIN,
            "slip": " | ".join([l["leg_str"] for l in legs]),
        })

        for li, l in enumerate(legs, start=1):
            detail_rows.append({
                "parlay_rank": rank,
                "parlay_p_hit": p_hit,
                "parlay_ev": ev,
                "leg_num": li,
                "leg": l["leg_str"],
                "p_combo": float(l["p_combo"]),
                "p_adj": float(l["p_adj"]) if pd.notna(l["p_adj"]) else None,
                "p_eff": float(l["p_eff"]) if pd.notna(l["p_eff"]) else None,
                "tier": l.get("agreement_tier", ""),
            })

    detail_df = pd.DataFrame(detail_rows)
    parlay_df = pd.DataFrame(parlay_rows)

    detail_df.to_csv(OUT_CSV, index=False)
    print(f"Saved details CSV: {OUT_CSV}")

    # ---------------- CLEAN CHART: Hit Prob bars + EV dots ----------------
    labels = [f"Parlay #{i}" for i in range(1, 4)]
    p_vals = [top3[i-1][1] for i in range(1, 4)]
    ev_vals = [top3[i-1][0] for i in range(1, 4)]

    # Best EV index
    best_i = max(range(3), key=lambda i: ev_vals[i])

    fig, ax1 = plt.subplots(figsize=(12, 6))
    bars = ax1.bar(labels, p_vals)
    ax1.set_title(f"Top 3 Parlays ({N_LEGS}-leg): Hit Probability vs Expected Value")
    ax1.set_ylabel("Approx Hit Probability (product of p_combo)")
    ax1.set_ylim(0, max(p_vals) * 1.25)

    # Highlight highest EV bar
    for i, b in enumerate(bars):
        if i == best_i:
            b.set_hatch("//")  # visual highlight without relying on color

        # annotate hit prob on bar
        ax1.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"p={p_vals[i]:.3f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    # EV axis
    ax2 = ax1.twinx()
    ax2.plot(labels, ev_vals, marker="o")
    ax2.set_ylabel(f"EV (net units per 1 stake, PROFIT_ON_WIN={PROFIT_ON_WIN})")

    # annotate EV points
    for i, ev in enumerate(ev_vals):
        ax2.text(i, ev, f"EV={ev:.2f}", ha="center", va="bottom", fontsize=10)

    # Footer note + best bet callout
    best_ev = ev_vals[best_i]
    best_slip = parlay_df.loc[parlay_df["parlay_rank"] == (best_i + 1), "slip"].iloc[0]

    footer = (
        "Legend:\n"
        "Bars = hit probability (product of p_combo)\n"
        "Dots = EV (net units per 1 unit stake)\n"
        "Hatched bar = highest EV parlay\n"
        f"Best EV Parlay: #{best_i+1} (EV={best_ev:.2f})"
    )

    fig.text(
        0.02, 0.02, footer,
        ha="left", va="bottom",
        fontsize=10,
        bbox=dict(boxstyle="round", alpha=0.15),
    )

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=150)
    plt.close()

    print(f"Saved chart: {OUT_PNG}")

    # ---------------- Excel workbook with tabs ----------------
    wb = Workbook()
    # remove default sheet
    wb.remove(wb.active)

    def add_sheet(name: str, frame: pd.DataFrame):
        ws = wb.create_sheet(title=name)
        for r in dataframe_to_rows(frame, index=False, header=True):
            ws.append(r)
        # basic column width
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                v = "" if cell.value is None else str(cell.value)
                max_len = max(max_len, len(v))
            ws.column_dimensions[col_letter].width = min(60, max(12, max_len + 2))

    add_sheet("Top3_Parlays", parlay_df)
    add_sheet("Parlay_Legs", detail_df)
    add_sheet("Definitions", DEFINITIONS)

    wb.save(OUT_XLSX)
    print(f"Saved Excel workbook: {OUT_XLSX}")

    # Print best slip plainly in terminal
    print("\n=== BEST EV SLIP (for most money) ===")
    print(best_slip)
    print(f"EV={best_ev:.2f}  |  HitProb={p_vals[best_i]:.3f}")
    print("\n(Adjust PROFIT_ON_WIN at top of script if your 3-pick payout differs.)\n")


if __name__ == "__main__":
    main()
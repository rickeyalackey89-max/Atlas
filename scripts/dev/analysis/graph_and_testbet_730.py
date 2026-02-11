import os
from zoneinfo import ZoneInfo

import pandas as pd
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_TZ = ZoneInfo("America/Chicago")

SCORED_PATH = os.path.join(
    ROOT, "data", "output", "latest", "all", "scored_legs_deduped.csv"
)
OUT_PNG = os.path.join(
    ROOT, "data", "output", "latest", "all", "slate_730_graph.png"
)

# 7:30 slate = 7:00–8:00pm local
START_HOUR = 19
END_HOUR = 20


def to_local_dt(series: pd.Series) -> pd.Series:
    st = pd.to_datetime(series, errors="coerce", utc=True)
    return st.dt.tz_convert(LOCAL_TZ)


def choose_score_column(df: pd.DataFrame) -> str:
    """
    Pick the best available probability column.
    Priority order matters.
    """
    for col in ["p_eff_biased", "p_adj", "p"]:
        if col in df.columns:
            return col
    raise ValueError(
        "No usable probability column found. "
        "Expected one of: p_eff_biased, p_adj, p"
    )


def main():
    if not os.path.exists(SCORED_PATH):
        raise FileNotFoundError(f"Missing: {SCORED_PATH}. Run python run_today.py first.")

    df = pd.read_csv(SCORED_PATH)

    if "start_time" not in df.columns:
        raise ValueError("scored legs missing start_time column.")

    # Convert to local time
    df["_local_dt"] = to_local_dt(df["start_time"])
    df = df[df["_local_dt"].notna()].copy()

    # Filter 7–8pm slate
    df = df[
        (df["_local_dt"].dt.hour >= START_HOUR)
        & (df["_local_dt"].dt.hour <= END_HOUR)
    ].copy()

    if df.empty:
        print("No legs found in the 7:00–8:00pm local window.")
        return

    # Pick score column safely
    score_col = choose_score_column(df)
    print(f"[INFO] Using score column: {score_col}")

    df[score_col] = pd.to_numeric(df[score_col], errors="coerce")
    df = df[df[score_col].notna()].copy()

    # ---------------- Graph ----------------
    plt.figure()
    plt.hist(df[score_col].values, bins=20)
    plt.title(f"7:00–8:00pm Slate Distribution: {score_col}")
    plt.xlabel(score_col)
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=150)
    plt.close()

    print(f"Saved graph: {OUT_PNG}")

    # ---------------- Test Bet (2-leg) ----------------
    df_sorted = df.sort_values(score_col, ascending=False)

    picks = []
    used_players = set()

    for _, r in df_sorted.iterrows():
        player = str(r.get("player", "")).strip()
        if not player or player in used_players:
            continue

        direction = str(r.get("direction", "")).strip().upper()
        if direction not in ("OVER", "UNDER"):
            continue

        picks.append(r)
        used_players.add(player)

        if len(picks) == 2:
            break

    print("\n=== 7:30 Slate Test Slip (2 legs) ===")

    if len(picks) < 2:
        print("Could not find 2 unique-player legs in this window.")
        return

    for i, r in enumerate(picks, start=1):
        print(
            f"{i}) {r['player']} {r['direction']} {r['stat']} {r['line']}  |  "
            f"{score_col}={float(r[score_col]):.3f}  |  "
            f"start={r['_local_dt']}"
        )

    print("\nSuggested use: SMALL test slip (workflow validation).")
    print("Not betting advice.\n")


if __name__ == "__main__":
    main()
"""
audit_slip_wins.py

Evaluates slip-level win rates for picks published to Cloudflare over the last N eval dates.
A slip WINS only when ALL legs hit. Includes payout multiples for EV analysis.

Usage:
    python tools/audit_slip_wins.py [--days 10]
"""

import argparse
import subprocess
import json
import pandas as pd
from pathlib import Path
from collections import defaultdict

ATLAS_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ATLAS_DIR.parent / "atlas-dashboard"
CORPUS_DIR = ATLAS_DIR / "data" / "telemetry" / "v17_corpus"
OUTPUT_DIR = ATLAS_DIR / "data" / "output" / "graphics"


def get_commits_for_date(date_str: str):
    year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
    date_label = f"{year}-{month}-{day}"
    result = subprocess.run(
        ["git", "log", "--format=%H %ai", f"--after={date_label}T00:00:00", f"--before={date_label}T23:59:59"],
        cwd=str(DASHBOARD_DIR), capture_output=True, text=True
    )
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    return [l.split()[0] for l in lines if l]


def get_payload_from_commit(commit_hash: str):
    result = subprocess.run(
        ["git", "show", f"{commit_hash}:public/data/cloudflare_payload.json"],
        cwd=str(DASHBOARD_DIR), capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def load_eval_for_date(date_str: str):
    path = CORPUS_DIR / date_str / "eval_legs.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["direction"] = df["direction"].str.upper().str.strip()
    df["player"] = df["player"].str.strip()
    df["stat"] = df["stat"].str.strip()
    df["line"] = df["line"].astype(float)
    # Build a lookup dict: (player, stat, line, direction) -> hit
    lookup = {}
    for _, row in df.iterrows():
        key = (row["player"], row["stat"], row["line"], row["direction"])
        lookup[key] = int(row["hit"])
    return lookup


def score_slip(slip: dict, hit_lookup: dict):
    """Determine if a slip won (all legs hit). Returns (won, legs_hit, legs_total, n_unmatched)."""
    legs = slip.get("legs_detail") or slip.get("legs", [])
    hits = []
    unmatched = 0
    for leg in legs:
        player = leg.get("player", "").strip()
        stat = leg.get("stat", "").strip()
        line = float(leg.get("line", 0))
        direction = leg.get("dir", "").strip().upper()
        key = (player, stat, line, direction)
        if key in hit_lookup:
            hits.append(hit_lookup[key])
        else:
            unmatched += 1
    if unmatched > 0 or not hits:
        return None, len(hits), len(legs), unmatched
    won = 1 if all(h == 1 for h in hits) else 0
    return won, sum(hits), len(legs), 0


def extract_tiers(slip: dict):
    """Summarize tier composition of a slip."""
    tiers = [l.get("tier", "?").upper() for l in (slip.get("legs_detail") or slip.get("legs", []))]
    counts = defaultdict(int)
    for t in tiers:
        counts[t] += 1
    return dict(counts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=10)
    args = parser.parse_args()

    eval_dates = sorted([d.name for d in CORPUS_DIR.iterdir() if d.is_dir()], reverse=True)
    target_dates = eval_dates[:args.days]

    slip_rows = []
    summary_rows = []

    print(f"\n{'='*70}")
    print(f"ATLAS SLIP WIN RATE AUDIT — Last {args.days} eval dates")
    print(f"{'='*70}\n")

    for date_str in target_dates:
        commits = get_commits_for_date(date_str)
        if not commits:
            print(f"  {date_str}: No Cloudflare commits — skipping")
            continue

        # Use earliest commit of the day (morning slate picks)
        payload = None
        for c in reversed(commits):
            payload = get_payload_from_commit(c)
            if payload:
                break

        if payload is None:
            print(f"  {date_str}: Could not load payload — skipping")
            continue

        hit_lookup = load_eval_for_date(date_str)
        if hit_lookup is None:
            print(f"  {date_str}: No eval data — skipping")
            continue

        date_slip_count = 0
        date_won = 0
        by_feed = defaultdict(lambda: defaultdict(lambda: {"n": 0, "won": 0, "ev": 0.0}))

        for feed in ["system", "windfall", "demonhunter", "marketed_slips"]:
            for slip in payload.get(feed, []):
                n_legs = slip.get("n_legs", len(slip.get("legs_detail", [])))
                payout = slip.get("payout_mult", 1.0)
                hit_prob = slip.get("hit_prob", None)
                tiers = extract_tiers(slip)
                tier_str = "/".join(f"{k}:{v}" for k, v in sorted(tiers.items()))

                won, legs_hit, legs_total, unmatched = score_slip(slip, hit_lookup)

                if won is None:
                    # Skip unmatched slips
                    continue

                # EV = payout * win_rate - (1 - win_rate) [unit stake = 1]
                ev = payout * won - 1  # realized EV for this specific slip

                date_slip_count += 1
                date_won += won

                by_feed[feed][n_legs]["n"] += 1
                by_feed[feed][n_legs]["won"] += won
                by_feed[feed][n_legs]["ev"] += ev

                slip_rows.append({
                    "date": date_str,
                    "feed": feed,
                    "n_legs": n_legs,
                    "payout_mult": payout,
                    "model_hit_prob": round(hit_prob, 4) if hit_prob else None,
                    "legs_hit": legs_hit,
                    "won": won,
                    "realized_ev": round(ev, 2),
                    "tier_mix": tier_str,
                    "legs_str": slip.get("legs", "")[:120],
                })

        win_rate = date_won / date_slip_count if date_slip_count > 0 else None
        wr_str = f"{win_rate:.1%}" if win_rate is not None else "N/A"
        print(f"  {date_str}  |  {date_slip_count} slips  |  {date_won} won  |  Win Rate: {wr_str}")

        for feed in ["system", "windfall", "demonhunter", "marketed_slips"]:
            if feed not in by_feed:
                continue
            for n_legs in sorted(by_feed[feed].keys()):
                stats = by_feed[feed][n_legs]
                wr = stats["won"] / stats["n"] if stats["n"] > 0 else 0
                ev_total = stats["ev"]
                print(f"    {feed:14s} {n_legs}-leg:  {stats['won']}/{stats['n']} won ({wr:.1%})  |  EV total: {ev_total:+.1f}x")

        summary_rows.append({
            "date": date_str,
            "total_slips": date_slip_count,
            "total_won": date_won,
            "win_rate": round(win_rate, 4) if win_rate else None,
        })

    if not slip_rows:
        print("No slip data found.")
        return

    df = pd.DataFrame(slip_rows)
    summary_df = pd.DataFrame(summary_rows)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = OUTPUT_DIR / "slip_wins_detail.csv"
    summary_path = OUTPUT_DIR / "slip_wins_summary.csv"
    df.to_csv(detail_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    # ── AGGREGATE RESULTS ────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("AGGREGATE RESULTS")
    print(f"{'='*70}")

    total_slips = len(df)
    total_won = df["won"].sum()
    total_wr = total_won / total_slips
    total_ev = df["realized_ev"].sum()
    print(f"\nAll slips: {total_won}/{total_slips} won = {total_wr:.1%} | Cumulative EV: {total_ev:+.1f}x units\n")

    # By feed
    print("By Feed:")
    for feed, grp in df.groupby("feed"):
        wr = grp["won"].mean()
        ev = grp["realized_ev"].sum()
        print(f"  {feed:14s}  {grp['won'].sum():.0f}/{len(grp)} won = {wr:.1%}  |  EV: {ev:+.1f}x")

    # By n_legs
    print("\nBy Slip Size:")
    for n, grp in df.groupby("n_legs"):
        wr = grp["won"].mean()
        ev = grp["realized_ev"].sum()
        payout = grp["payout_mult"].iloc[0]
        breakeven = 1 / payout
        print(f"  {n}-leg (pays {payout:.0f}x):  {grp['won'].sum():.0f}/{len(grp)} won = {wr:.1%}  |  breakeven={breakeven:.1%}  |  EV: {ev:+.1f}x")

    # By feed x n_legs
    print("\nBy Feed x Slip Size:")
    pivot = df.groupby(["feed", "n_legs"]).agg(
        n=("won", "count"),
        wins=("won", "sum"),
        win_rate=("won", "mean"),
        ev=("realized_ev", "sum")
    ).reset_index()
    for _, row in pivot.iterrows():
        breakeven = 1 / df[(df["feed"] == row["feed"]) & (df["n_legs"] == row["n_legs"])]["payout_mult"].iloc[0]
        flag = " [+EV]" if row["win_rate"] > breakeven else " [-EV]"
        print(f"  {row['feed']:14s} {int(row['n_legs'])}-leg:  {row['wins']:.0f}/{row['n']} = {row['win_rate']:.1%} (breakeven {breakeven:.1%}){flag}  |  EV {row['ev']:+.1f}x")

    # Best performing slip (for market strategy)
    print(f"\n{'='*70}")
    print("MARKET STRATEGY INSIGHT")
    print(f"{'='*70}")
    best = pivot[pivot["win_rate"] == pivot["win_rate"].max()].iloc[0]
    worst = pivot[pivot["win_rate"] == pivot["win_rate"].min()].iloc[0]
    print(f"  Strongest: {best['feed']} {int(best['n_legs'])}-leg  ({best['win_rate']:.1%} win rate, {best['wins']:.0f}/{best['n']} won)")
    print(f"  Weakest:   {worst['feed']} {int(worst['n_legs'])}-leg  ({worst['win_rate']:.1%} win rate, {worst['wins']:.0f}/{worst['n']} won)")

    # Positive EV plays
    pos_ev = pivot[pivot["ev"] > 0]
    if len(pos_ev) > 0:
        print(f"\n  [+EV] Positive EV slip types ({len(pos_ev)}):")
        for _, row in pos_ev.iterrows():
            print(f"     {row['feed']} {int(row['n_legs'])}-leg: EV {row['ev']:+.1f}x over {row['n']:.0f} slips")
    else:
        print("\n  [!] No slip type was net positive EV in this window.")

    print(f"\nDetail CSV:  {detail_path}")
    print(f"Summary CSV: {summary_path}\n")


if __name__ == "__main__":
    main()

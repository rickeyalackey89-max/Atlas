"""
audit_cloudflare_hits.py

Cross-references picks published to Cloudflare (via atlas-dashboard git history)
against eval_legs.csv truth labels to compute actual hit rates per day.
"""

import subprocess
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

ATLAS_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ATLAS_DIR.parent / "atlas-dashboard"
CORPUS_DIR = ATLAS_DIR / "data" / "telemetry" / "v18_corpus"
OUTPUT_PATH = ATLAS_DIR / "data" / "output" / "graphics" / "cloudflare_hits_audit.csv"

# Dates with eval data (from v18_corpus), most recent first
EVAL_DATES = sorted([d.name for d in CORPUS_DIR.iterdir() if d.is_dir()], reverse=True)


def get_commits_for_date(date_str: str):
    """Get all git commits for a given date (YYYYMMDD) from atlas-dashboard."""
    year = date_str[:4]
    month = date_str[4:6]
    day = date_str[6:8]
    date_label = f"{year}-{month}-{day}"

    result = subprocess.run(
        ["git", "log", "--oneline", "--format=%H %ai %s",
         f"--after={date_label}T00:00:00",
         f"--before={date_label}T23:59:59"],
        cwd=str(DASHBOARD_DIR),
        capture_output=True, text=True
    )
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    # Return just the commit hashes, most recent first
    return [l.split()[0] for l in lines if l]


def get_payload_from_commit(commit_hash: str):
    """Extract cloudflare_payload.json from a specific git commit."""
    result = subprocess.run(
        ["git", "show", f"{commit_hash}:public/data/cloudflare_payload.json"],
        cwd=str(DASHBOARD_DIR),
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def extract_legs_from_payload(payload: dict):
    """Pull individual legs out of cloudflare_payload system slips."""
    legs = []
    for slip in payload.get("system", []) + payload.get("windfall", []):
        for leg in slip.get("legs_detail", []):
            legs.append({
                "player": leg.get("player", "").strip(),
                "stat": leg.get("stat", "").strip(),
                "line": float(leg.get("line", 0)),
                "direction": leg.get("dir", "").strip().upper(),
                "tier": leg.get("tier", "").strip().upper(),
                "n_legs": slip.get("n_legs"),
                "product": slip.get("product"),
            })
    # Dedupe legs (same player/stat/line/direction can appear in multiple slips)
    seen = set()
    unique = []
    for l in legs:
        key = (l["player"], l["stat"], l["line"], l["direction"])
        if key not in seen:
            seen.add(key)
            unique.append(l)
    return unique


def load_eval_for_date(date_str: str):
    """Load eval_legs.csv for a given date."""
    path = CORPUS_DIR / date_str / "eval_legs.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["direction"] = df["direction"].str.upper().str.strip()
    df["player"] = df["player"].str.strip()
    df["stat"] = df["stat"].str.strip()
    df["line"] = df["line"].astype(float)
    return df


def match_legs(cf_legs: list, eval_df: pd.DataFrame):
    """Match cloudflare legs to eval truth by (player, stat, line, direction)."""
    results = []
    for leg in cf_legs:
        match = eval_df[
            (eval_df["player"] == leg["player"]) &
            (eval_df["stat"] == leg["stat"]) &
            (eval_df["line"] == leg["line"]) &
            (eval_df["direction"] == leg["direction"])
        ]
        if len(match) > 0:
            row = match.iloc[0]
            results.append({
                **leg,
                "hit": int(row["hit"]),
                "p_cal": round(row["p_cal"], 4),
                "matched": True,
            })
        else:
            results.append({**leg, "hit": None, "p_cal": None, "matched": False})
    return results


def main():
    print(f"Atlas dashboard: {DASHBOARD_DIR}")
    print(f"Corpus dir:      {CORPUS_DIR}")
    print(f"Eval dates available: {len(EVAL_DATES)}")
    print()

    all_rows = []
    summary_rows = []

    # Use the 10 most recent dates with eval data
    target_dates = EVAL_DATES[:10]

    for date_str in target_dates:
        commits = get_commits_for_date(date_str)
        if not commits:
            print(f"  {date_str}: No Cloudflare commits found — skipping")
            continue

        # Use the FIRST commit of the day (earliest = morning picks for that slate)
        first_commit = commits[-1]
        payload = get_payload_from_commit(first_commit)
        if payload is None:
            # Try other commits if first doesn't have a valid payload
            for c in reversed(commits):
                payload = get_payload_from_commit(c)
                if payload:
                    first_commit = c
                    break

        if payload is None:
            print(f"  {date_str}: Could not load payload from any commit — skipping")
            continue

        cf_legs = extract_legs_from_payload(payload)
        eval_df = load_eval_for_date(date_str)

        if eval_df is None:
            print(f"  {date_str}: No eval data — skipping")
            continue

        matched = match_legs(cf_legs, eval_df)
        matched_only = [r for r in matched if r["matched"]]

        n_total = len(cf_legs)
        n_matched = len(matched_only)
        n_hit = sum(r["hit"] for r in matched_only)
        hit_rate = n_hit / n_matched if n_matched > 0 else None

        hr_str = f"{hit_rate:.1%}" if hit_rate is not None else "N/A"
        print(f"  {date_str}: {n_matched}/{n_total} legs matched | Hit: {n_hit}/{n_matched} ({hr_str})")

        # Per-tier breakdown
        tier_stats = {}
        for r in matched_only:
            t = r.get("tier", "UNKNOWN")
            tier_stats.setdefault(t, {"n": 0, "hits": 0})
            tier_stats[t]["n"] += 1
            tier_stats[t]["hits"] += r["hit"]

        for tier, stats in sorted(tier_stats.items()):
            tier_hr = stats["hits"] / stats["n"] if stats["n"] > 0 else None
            print(f"    {tier:10s}: {stats['hits']}/{stats['n']} = {tier_hr:.1%}" if tier_hr is not None else f"    {tier}: N/A")

        for r in matched_only:
            all_rows.append({
                "date": date_str,
                "player": r["player"],
                "stat": r["stat"],
                "line": r["line"],
                "direction": r["direction"],
                "tier": r.get("tier", ""),
                "hit": r["hit"],
                "p_cal": r["p_cal"],
                "product": r.get("product", ""),
                "n_legs": r.get("n_legs", ""),
            })

        summary_rows.append({
            "date": date_str,
            "n_legs_published": n_total,
            "n_legs_matched": n_matched,
            "n_hits": n_hit,
            "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            **{f"hit_rate_{t}": round(v["hits"] / v["n"], 4) if v["n"] > 0 else None
               for t, v in tier_stats.items()},
        })

    if not all_rows:
        print("\nNo data found.")
        return

    detail_df = pd.DataFrame(all_rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    detail_df.to_csv(OUTPUT_PATH, index=False)

    summary_df = pd.DataFrame(summary_rows)
    summary_path = OUTPUT_PATH.parent / "cloudflare_hits_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    print(f"\n{'='*60}")
    print("SUMMARY — Cloudflare Published Picks vs Actual Results")
    print(f"{'='*60}")
    print(summary_df.to_string(index=False))
    print(f"\nDetail CSV:  {OUTPUT_PATH}")
    print(f"Summary CSV: {summary_path}")

    # Overall
    n_total_hits = detail_df["hit"].sum()
    n_total_legs = len(detail_df)
    overall_hr = n_total_hits / n_total_legs
    print(f"\nOVERALL: {n_total_hits}/{n_total_legs} legs hit = {overall_hr:.1%}")

    print("\nBy Tier:")
    for tier, grp in detail_df.groupby("tier"):
        hr = grp["hit"].mean()
        print(f"  {tier:12s}: {grp['hit'].sum():.0f}/{len(grp)} = {hr:.1%}")


if __name__ == "__main__":
    main()

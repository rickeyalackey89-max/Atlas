#!/usr/bin/env python3
"""Quick slip hit-rate eval for May 4, 2026."""
import csv, re
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path("data")
RUNS_DIR = DATA_DIR / "output" / "runs"
TARGET_DATE = "2026-05-04"

# Build hit lookup
hit_lookup = {}
for run_dir in sorted(RUNS_DIR.iterdir()):
    if not run_dir.name.startswith("20260504"):
        continue
    eval_path = run_dir / "eval_legs.csv"
    if not eval_path.exists():
        continue
    with open(eval_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            if (row.get("game_date") or "")[:10] != TARGET_DATE:
                continue
            hit_val = row.get("hit", "")
            if hit_val not in ("0", "1", "0.0", "1.0"):
                continue
            key = (
                row.get("player", "").strip(),
                row.get("stat", "").strip(),
                str(row.get("line", "")).strip(),
                row.get("direction", "").strip().upper(),
            )
            hit_lookup[key] = int(float(hit_val))

print(f"Hit lookup: {len(hit_lookup)} unique scored legs")

LEG_RE = re.compile(r"([^|]+?)\s+(OVER|UNDER)\s+(\S+)\s+([\d.]+)\s+\(\w+\)", re.IGNORECASE)

def parse_legs(slip_key_str):
    legs = []
    for part in slip_key_str.split("|"):
        m = LEG_RE.search(part.strip())
        if m:
            player = m.group(1).strip()
            direction = m.group(2).upper()
            stat = m.group(3).upper()
            line = m.group(4)
            legs.append((player, stat, line, direction))
    return legs

SLIP_FILES = {
    "3leg": "recommended_3leg.csv",
    "4leg": "recommended_4leg.csv",
    "5leg": "recommended_5leg.csv",
    "3leg_wp": "recommended_3leg_winprob.csv",
    "4leg_wp": "recommended_4leg_winprob.csv",
    "5leg_wp": "recommended_5leg_winprob.csv",
    "demon": "demonhunter.csv",
}

CANON_RUNS = ["20260504_110613", "20260504_143431", "20260504_173457"]

for run_name in CANON_RUNS:
    run_dir = RUNS_DIR / run_name
    if not run_dir.exists():
        continue
    print(f"\n{'='*60}")
    print(f"Run: {run_name}")
    print(f"{'='*60}")
    for label, fname in SLIP_FILES.items():
        fp = run_dir / fname
        if not fp.exists():
            continue
        with open(fp, newline="", encoding="utf-8-sig") as f:
            slips = list(csv.DictReader(f))
        if not slips:
            continue

        wins = 0
        total_scored = 0
        for rank, s in enumerate(slips[:10]):
            leg_str = s.get("slip_key", "") or s.get("legs", "")
            legs = parse_legs(leg_str)
            if not legs:
                continue
            leg_hits = [hit_lookup.get(lk) for lk in legs]
            scored = [h for h in leg_hits if h is not None]
            if len(scored) < len(legs):
                continue
            all_win = all(h == 1 for h in scored)
            hits_count = sum(h == 1 for h in scored)
            total_scored += 1
            if all_win:
                wins += 1
            if all_win:
                hp = s.get("hit_prob", "")[:6]
                print(f"  {label:10s} WIN #{rank+1}: hit_prob={hp}  {leg_str}")
            elif rank == 0:
                status = f"MISS ({hits_count}/{len(legs)} legs)"
                hp = s.get("hit_prob", "")[:6]
                print(f"  {label:10s} #1: {status:<18s} hit_prob={hp}  {leg_str[:75]}")

        if total_scored > 0:
            pct = wins / total_scored * 100
            print(f"  {label:10s} top-10 win rate: {wins}/{total_scored} ({pct:.0f}%)")

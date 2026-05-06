#!/usr/bin/env python3
import csv
from pathlib import Path
from collections import defaultdict

RUNS_DIR = Path("data/output/runs")
TARGET_DATE = "2026-05-04"

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
            key = (row.get("player","").strip(), row.get("stat","").strip(),
                   str(row.get("line","")).strip(), row.get("direction","").strip().upper())
            hit_lookup[key] = int(float(hit_val))

CANON_RUNS = ["20260504_110613", "20260504_143431", "20260504_173457"]
RUN_LABELS = {"20260504_110613": "11am", "20260504_143431": "2:30pm", "20260504_173457": "5:30pm"}

for run_name in CANON_RUNS:
    fp = RUNS_DIR / run_name / "marketed_slips.csv"
    if not fp.exists():
        continue
    with open(fp, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    slips = defaultdict(list)
    for r in rows:
        slips[r["slip"]].append(r)

    print(f"\n=== {RUN_LABELS[run_name]} Run ({run_name}) ===")
    for slip_name, legs in slips.items():
        leg_results = []
        for leg in legs:
            key = (leg["player"].strip(), leg["stat"].strip(),
                   str(leg["line"]).strip(), leg["direction"].strip().upper())
            leg_results.append((leg, hit_lookup.get(key)))

        scored = [(l, h) for l, h in leg_results if h is not None]
        if len(scored) < len(legs):
            status = "UNSCORED"
        elif all(h == 1 for _, h in scored):
            status = "WIN"
        else:
            hits = sum(h == 1 for _, h in scored)
            status = f"MISS ({hits}/{len(legs)})"

        hp = float(legs[0].get("hit_prob", 0))
        leg_summary = " | ".join(
            f"{l['player']} {l['direction']} {l['stat']} {l['line']} ({l['tier']})"
            for l in legs
        )
        icon = "✅" if status == "WIN" else ("❓" if status == "UNSCORED" else "❌")
        print(f"  {icon} {slip_name:12s} [{status}]  hit_prob={hp:.1%}")
        print(f"     {leg_summary}")

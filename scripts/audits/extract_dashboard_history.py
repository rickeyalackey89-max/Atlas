"""
Extract all dashboard pick history from atlas-dashboard git commits.
Output: data/archives/dashboard_pick_history.csv
"""
import subprocess, json, csv
from pathlib import Path

REPO = r"c:\Users\13142\Atlas\atlas-dashboard"
OUT = Path(r"c:\Users\13142\Atlas\NBA\data\archives\dashboard_pick_history.csv")
OUT.parent.mkdir(parents=True, exist_ok=True)

result = subprocess.run(
    ["git", "-C", REPO, "log", "--format=%H %ad", "--date=iso"],
    capture_output=True, text=True
)
commits = []
for line in result.stdout.strip().split("\n"):
    parts = line.split()
    if len(parts) >= 2:
        h = parts[0]
        d = parts[1][:10]
        t = parts[2][:8] if len(parts) >= 3 else ""
        commits.append((h, d, t))

print(f"Total commits: {len(commits)}")

rows = []
seen_run_ids = set()

for h, d, t in commits:
    r = subprocess.run(
        ["git", "-C", REPO, "show", h + ":public/data/cloudflare_payload.json"],
        capture_output=True, text=True, errors="replace"
    )
    if r.returncode != 0:
        continue
    try:
        data = json.loads(r.stdout)
    except Exception:
        continue

    generated_at = data.get("generated_at", "")
    run_id = data.get("run_id", "")

    # Skip duplicate run_ids (multiple commits from same pipeline run)
    if run_id and run_id in seen_run_ids:
        continue
    if run_id:
        seen_run_ids.add(run_id)

    for slip_type in ["system", "windfall", "demonhunter", "gamescript"]:
        slips = data.get(slip_type, [])
        if not isinstance(slips, list):
            continue
        for slip in slips:
            n_legs = slip.get("n_legs", "")
            hit_prob = slip.get("hit_prob", "")
            ev_mult = slip.get("ev_mult", "")
            payout_mult = slip.get("payout_mult", "")
            avg_frag = slip.get("avg_fragility", "")
            legs_detail = slip.get("legs_detail", [])
            for leg in legs_detail:
                rows.append({
                    "date": d,
                    "time": t,
                    "generated_at": generated_at,
                    "run_id": run_id,
                    "commit": h[:10],
                    "slip_type": slip_type,
                    "n_legs": n_legs,
                    "slip_hit_prob": hit_prob,
                    "slip_ev_mult": ev_mult,
                    "slip_payout_mult": payout_mult,
                    "slip_avg_fragility": avg_frag,
                    "player": leg.get("player", ""),
                    "dir": leg.get("dir", ""),
                    "stat": leg.get("stat", ""),
                    "line": leg.get("line", ""),
                    "tier": leg.get("tier", ""),
                    "prop_id": leg.get("id", ""),
                })

print(f"Total leg rows: {len(rows)}")
dates_seen = sorted(set(r["date"] for r in rows))
print(f"Unique dates: {len(dates_seen)}")
if dates_seen:
    print(f"Range: {dates_seen[0]} -- {dates_seen[-1]}")

if rows:
    fieldnames = list(rows[0].keys())
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {OUT}  ({OUT.stat().st_size:,} bytes)")
else:
    print("No rows extracted.")

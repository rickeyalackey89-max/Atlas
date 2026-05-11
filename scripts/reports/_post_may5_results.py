"""Post May 5 results to Discord — matches May 4 embed format exactly."""
import os, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from discord_post import post_to_discord, TIER_EMOJI

POWER_PAYOUTS = {3: 5, 4: 10, 5: 20}
STAKE = 20

def payout_str(n):
    mult = POWER_PAYOUTS.get(n, n)
    return f"${STAKE} bet → ${STAKE * mult} ({mult}x payout)"

sl = pd.read_csv(PROJECT_ROOT / "data/output/runs/20260505_173532/scored_legs_deduped.csv")

def get_tier(player, stat, line, direction):
    row = sl[(sl["player"]==player) & (sl["stat"]==stat) & (sl["line"]==line) & (sl["direction"]==direction)]
    if row.empty:
        return "STANDARD"
    return str(row.iloc[0].get("tier", "STANDARD"))

winning_slips = [
    {
        "label": "9:10am — 3-leg WIN",
        "legs": [
            ("Jaxson Hayes",           "PTS", 1.5,  "OVER"),
            ("Ajay Mitchell",          "RA",  7.5,  "UNDER"),
            ("Austin Reaves",          "PTS", 20.5, "UNDER"),
        ]
    },
    {
        "label": "2:09pm — 3-leg WIN",
        "legs": [
            ("Jaxson Hayes",           "PTS", 1.5,  "OVER"),
            ("Ajay Mitchell",          "REB", 3.5,  "UNDER"),
            ("Austin Reaves",          "PR",  24.5, "UNDER"),
        ]
    },
    {
        "label": "5:17pm — 4-leg WIN",
        "legs": [
            ("Isaiah Joe",             "PTS", 4.5,  "OVER"),
            ("Duncan Robinson",        "PTS", 11.0, "OVER"),
            ("Chet Holmgren",          "PRA", 26.5, "OVER"),
            ("Daniss Jenkins",         "PRA", 15.5, "OVER"),
        ]
    },
    {
        "label": "5:35pm — 3-leg WIN",
        "legs": [
            ("Isaiah Joe",             "PR",  7.5,  "OVER"),
            ("Shai Gilgeous-Alexander","RA",  11.5, "UNDER"),
            ("Daniss Jenkins",         "PRA", 15.5, "OVER"),
        ]
    },
]

fields = []
for slip in winning_slips:
    n = len(slip["legs"])
    leg_lines = []
    for player, stat, line, direction in slip["legs"]:
        emoji = TIER_EMOJI.get(get_tier(player, stat, line, direction), "🔵")
        leg_lines.append(f"{emoji} {player} **{direction} {stat} {line}**")
    leg_lines.append(f"💰 {payout_str(n)}")
    fields.append({"name": f"✅ {slip['label']}", "value": "\n".join(leg_lines), "inline": False})

fields.append({
    "name": "Today's Picks",
    "value": "Full slips + rankings at **[atlassports.ai/dashboard](https://atlassports.ai/dashboard/)** — Premium members get all 3 daily slips.",
    "inline": False,
})

embed = {
    "title": "🏀 Atlas Premium Slips — Tuesday, May 5 Results",
    "description": (
        "**4/12 slips hit** — Tuesday, May 5\n\n"
        "We target 1 in 3. Yesterday we went **4 for 12**. Here's what cashed 👇\n\n"
        "Jarrett Allen and Jake LaRavia having off nights really put a damper on our slip % — but WE KEEP ROLLING. Today's board is locked and loaded."
    ),
    "color": 0x4ADE80,
    "fields": fields,
    "footer": {"text": "Atlas Sports AI • atlassports.ai • Past results do not guarantee future performance"},
    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
}

webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
if not webhook_url:
    print("[ERROR] DISCORD_WEBHOOK_URL not set")
    sys.exit(1)

ok = post_to_discord(webhook_url=webhook_url, embed=embed, dry_run="--dry-run" in sys.argv)
sys.exit(0 if ok else 1)


# Look up tiers from scored legs
sl = pd.read_csv(PROJECT_ROOT / "data/output/runs/20260505_173532/scored_legs_deduped.csv")

def get_tier(player, stat, line, direction):
    row = sl[
        (sl["player"] == player) & (sl["stat"] == stat) &
        (sl["line"] == line) & (sl["direction"] == direction)
    ]
    if row.empty:
        return "STANDARD"
    return str(row.iloc[0].get("tier", "STANDARD"))

POWER_PAYOUTS = {3: 5, 4: 10, 5: 20}
STAKE = 20

def payout_str(n):
    mult = POWER_PAYOUTS.get(n, n)
    return f"${STAKE} bet → ${STAKE * mult} ({mult}x payout)"

# The 4 winning slips
winning_slips = [
    {
        "time": "9:10am",
        "name": "3-leg",
        "legs": [
            ("Jaxson Hayes",  "PTS", 1.5,  "OVER"),
            ("Ajay Mitchell", "RA",  7.5,  "UNDER"),
            ("Austin Reaves", "PTS", 20.5, "UNDER"),
        ]
    },
    {
        "time": "2:09pm",
        "name": "3-leg",
        "legs": [
            ("Jaxson Hayes",  "PTS", 1.5,  "OVER"),
            ("Ajay Mitchell", "REB", 3.5,  "UNDER"),
            ("Austin Reaves", "PR",  24.5, "UNDER"),
        ]
    },
    {
        "time": "5:17pm Windfall",
        "name": "4-leg",
        "legs": [
            ("Isaiah Joe",                   "PTS", 4.5,  "OVER"),
            ("Duncan Robinson",              "PTS", 11.0, "OVER"),
            ("Chet Holmgren",                "PRA", 26.5, "OVER"),
            ("Daniss Jenkins",               "PRA", 15.5, "OVER"),
        ]
    },
    {
        "time": "5:35pm Windfall",
        "name": "3-leg",
        "legs": [
            ("Isaiah Joe",                    "PR",  7.5,  "OVER"),
            ("Shai Gilgeous-Alexander",       "RA",  11.5, "UNDER"),
            ("Daniss Jenkins",                "PRA", 15.5, "OVER"),
        ]
    },
]

date_label = "Tuesday, May 5"
wins = len(winning_slips)
total = 12
note = "Jarrett Allen and Jake LaRavia having off nights really put a damper on our slip % — but WE KEEP ROLLING. Today's board is locked and loaded."

description = (
    f"**{wins}/{total} slips hit** — {date_label}\n\n"
    f"We target 1 in 3. Yesterday we went **{wins} for {total}**. Here's what cashed 👇\n\n"
    f"{note}"
)

fields = []
for slip in winning_slips:
    n = len(slip["legs"])
    leg_lines = []
    for player, stat, line, direction in slip["legs"]:
        tier = get_tier(player, stat, line, direction)
        emoji = TIER_EMOJI.get(tier, "🔵")
        leg_lines.append(f"{emoji} {player} **{direction} {stat} {line}**")
    leg_lines.append(f"💰 {payout_str(n)}")
    fields.append({
        "name": f"✅ {slip['time']} — {slip['name']} WIN",
        "value": "\n".join(leg_lines),
        "inline": False,
    })

fields.append({
    "name": "Today's Picks",
    "value": "Full slips + rankings at **[atlassports.ai/dashboard](https://atlassports.ai/dashboard/)** — Premium members get all 3 daily slips.",
    "inline": False,
})

embed = {
    "title": f"🏀 Atlas Premium Slips — {date_label} Results",
    "description": description,
    "color": 0x4ADE80,
    "fields": fields,
    "footer": {"text": "Atlas Sports AI • atlassports.ai • Past results do not guarantee future performance"},
    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
}

payload = json.dumps({"embeds": [embed]}).encode("utf-8")

print("[DISCORD] Posting May 5 results with slip details...")
req = urllib.request.Request(
    WEBHOOK_URL,
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    print(f"[DISCORD] HTTP {resp.status}")

print("Done.")

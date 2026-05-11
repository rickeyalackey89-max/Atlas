"""
discord_freebie_post.py — Daily 4:30pm freebie post to public Discord channel.

Posts:
  1. Today's top 3 picks (from top_hit_list in cloudflare_payload.json)
  2. The best System 3-leg slip (from most recent run's marketed_slips.csv)

Webhook URL read from ATLAS_DISCORD_FREEBIE_WEBHOOK env var.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "data" / "output" / "dashboard"
RUNS_DIR = REPO_ROOT / "data" / "output" / "runs"

_TIER = {"DEMON": "🔴", "GOBLIN": "🟢", "STANDARD": "⚪", "BELOW_ALTS": "🔵"}
_STAT_SHORT = {
    "POINTS": "PTS", "REBOUNDS": "REB", "ASSISTS": "AST",
    "THREES": "3PM", "FG3M": "3PM",
}

def _stat(s: str) -> str:
    return _STAT_SHORT.get(str(s).upper().strip(), str(s).upper().strip())


def _send(url: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/Atlas, 1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[FREEBIE] HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
        return False
    except Exception as e:
        print(f"[FREEBIE] Error: {e!r}")
        return False


def _latest_run_dir() -> Path | None:
    today = datetime.now().strftime("%Y%m%d")
    dirs = sorted(
        [d for d in RUNS_DIR.iterdir()
         if d.is_dir() and d.name.startswith(today) and len(d.name) == 15],
        reverse=True,
    )
    return dirs[0] if dirs else None


def _top_picks(n: int = 3) -> list[dict]:
    payload_path = DASHBOARD_DIR / "cloudflare_payload.json"
    if not payload_path.exists():
        return []
    try:
        with open(payload_path, encoding="utf-8") as f:
            d = json.load(f)
        return (d.get("top_hit_list") or [])[:n]
    except Exception:
        return []


def _parse_leg_str(s: str) -> dict:
    """Parse 'Player OVER STAT 13.5 (TIER) [id:...]' into a dict."""
    import re
    m = re.match(r'(.+?)\s+(OVER|UNDER)\s+(\S+)\s+([\d.]+)\s+\((\w+)\)', s.strip())
    if m:
        return {"player": m.group(1), "direction": m.group(2),
                "stat": m.group(3), "line": m.group(4), "tier": m.group(5)}
    return {"player": s, "direction": "", "stat": "", "line": "", "tier": ""}


def _system_3leg_slip(run_dir: Path) -> dict | None:
    """Return the top System 3-leg slip from System/recommended_3leg.csv."""
    csv_path = run_dir / "System" / "recommended_3leg.csv"
    if not csv_path.exists():
        return None
    try:
        import csv
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        row = rows[0]
        legs = [_parse_leg_str(row[k]) for k in ("leg_1", "leg_2", "leg_3") if row.get(k)]
        return {"hit_prob": row.get("hit_prob"), "payout_mult": row.get("payout_mult"), "legs": legs}
    except Exception:
        return None


def main() -> None:
    webhook_url = os.environ.get("ATLAS_DISCORD_FREEBIE_WEBHOOK", "").strip()
    if not webhook_url:
        print("[FREEBIE] ATLAS_DISCORD_FREEBIE_WEBHOOK not set — skipping.")
        sys.exit(0)

    game_date = datetime.now().strftime("%B %#d, %Y") if os.name == "nt" else datetime.now().strftime("%B %-d, %Y")

    # ── Top 3 picks block ─────────────────────────────────────────────
    picks = _top_picks(3)
    picks_lines = []
    for p in picks:
        player = str(p.get("player", "")).split(",")[0].strip()
        stat = _stat(p.get("stat", ""))
        direction = str(p.get("dir", "")).upper()
        line = p.get("line", "")
        l10_hr = p.get("l10_hr")
        l10_n = p.get("l10_n")
        l10_str = f"  {int(round(l10_hr * l10_n))}/{l10_n} L10" if l10_hr is not None and l10_n else ""
        arrow = "↑" if direction == "OVER" else "↓"
        picks_lines.append(f"🔥 **{player}** {stat} {arrow}{line}{l10_str}")

    picks_block = "\n".join(picks_lines) if picks_lines else "_No picks available._"

    # ── System 3-leg slip block ───────────────────────────────────────
    run_dir = _latest_run_dir()
    slip_block = "_No slip available._"
    slip_meta = ""
    if run_dir:
        slip_data = _system_3leg_slip(run_dir)
        if slip_data:
            hit_prob = slip_data.get("hit_prob")
            payout = slip_data.get("payout_mult")
            meta_parts = []
            if hit_prob:
                meta_parts.append(f"Win: **{float(hit_prob):.0%}**")
            if payout:
                meta_parts.append(f"{float(payout):.1f}x payout")
            slip_meta = "  |  ".join(meta_parts)
            leg_lines = []
            for r in slip_data.get("legs", []):
                tier_em = _TIER.get(str(r.get("tier", "")).upper(), "⚪")
                player = str(r.get("player", "")).split(",")[0].strip()
                stat = _stat(r.get("stat", ""))
                direction = str(r.get("direction", "")).upper()
                line = r.get("line", "")
                arrow = "↑" if direction == "OVER" else "↓"
                leg_lines.append(f"{tier_em} {player} {stat} {arrow}{line}")
            slip_block = "\n".join(leg_lines)

    description = (
        f"**🏆 Top Picks — {game_date}**\n"
        f"{picks_block}\n\n"
        f"**📋 Free Slip of the Day** (3-leg System)"
        + (f"\n{slip_meta}" if slip_meta else "") + "\n"
        f"{slip_block}\n\n"
        f"*Full edge rankings & premium slips at [atlassports.ai](https://atlassports.ai)*"
    )

    embed = {
        "description": description,
        "color": 0xF5A623,  # gold
        "footer": {"text": "Atlas Sports AI • Free daily pick"},
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    success = _send(webhook_url, {"embeds": [embed]})
    if success:
        print(f"[FREEBIE] Posted to Discord — {len(picks)} picks + 3-leg slip.")
    else:
        print("[FREEBIE] Post failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()

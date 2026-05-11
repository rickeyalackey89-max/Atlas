#!/usr/bin/env python3
"""
Discord Post Tool
==================
Two modes:

  Results mode (default — run by 6am eval script):
    Posts yesterday's marketed slip outcomes to DISCORD_WEBHOOK_URL
    Shows wins/misses + payout math. No premium picks revealed.

  Picks-today mode (--picks-today — run by live pipeline):
    Posts today's marketed premium slips to DISCORD_PICKS_WEBHOOK_URL
    Shows today's 3-leg, 4-leg, 5-leg picks with CTA to dashboard.

Env vars:
  DISCORD_WEBHOOK_URL        — results channel webhook
  DISCORD_PICKS_WEBHOOK_URL  — picks-today channel webhook
  ATLAS_DATA_DIR             — optional, defaults to data/

Usage:
    python tools/discord_post.py                          # yesterday results
    python tools/discord_post.py --date 2026-05-04        # specific date results
    python tools/discord_post.py --date 2026-05-04 --run-dir data/output/runs/20260504_173000
    python tools/discord_post.py --picks-today            # today's picks
    python tools/discord_post.py --picks-today --dry-run  # preview picks
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", PROJECT_ROOT / "data"))
RUNS_DIR = DATA_DIR / "output" / "runs"

_DISCORD_UA = "DiscordBot (https://github.com/Atlas, 1.0)"


def _get_env(name: str) -> str:
    """Read env var from process env, falling back to Windows User env."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        v, _ = winreg.QueryValueEx(key, name)
        return str(v).strip()
    except Exception:
        return ""


# PrizePicks Power Play standard payouts
POWER_PAYOUTS = {3: 5, 4: 10, 5: 20}
EXAMPLE_STAKE = 20
RUN_LABELS = ["11am", "2:30pm", "5:30pm"]
TIER_EMOJI = {"GOBLIN": "🟢", "STANDARD": "🔵", "DEMON": "🔴"}  # dots only — tier names never shown publicly



def _find_run_dirs(target_date: str) -> list:
    """Return timestamped run dirs for the target date, sorted by time."""
    prefix = target_date.replace("-", "")
    dirs = sorted(
        [d for d in RUNS_DIR.iterdir() if d.is_dir() and d.name.startswith(prefix)],
        key=lambda d: d.name,
    )
    # Skip alias dirs like 20260504_11am — keep only timestamp dirs (20260504_110613)
    return [d for d in dirs if len(d.name) == 15 and d.name[8] == "_"]


def _run_label(run_dir_name: str) -> str:
    """Map timestamp dir name to friendly time label."""
    try:
        time_part = run_dir_name[9:]  # e.g. "110613"
        hour = int(time_part[:2])
        minute = int(time_part[2:4])
        if hour < 12:
            return f"{hour}am" if minute == 0 else f"{hour}:{time_part[2:4]}am"
        elif hour == 12:
            return f"12:{time_part[2:4]}pm"
        else:
            h12 = hour - 12
            return f"{h12}pm" if minute == 0 else f"{h12}:{time_part[2:4]}pm"
    except Exception:
        return run_dir_name[9:]


def _build_hit_lookup(run_dirs: list, target_date: str) -> dict:
    lookup = {}
    for run_dir in run_dirs:
        ep = run_dir / "eval_legs.csv"
        if not ep.exists():
            continue
        with open(ep, newline="", encoding="utf-8-sig", errors="replace") as f:
            for row in csv.DictReader(f):
                if (row.get("game_date") or "")[:10] != target_date:
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
                lookup[key] = int(float(hit_val))
    return lookup


def _load_slip_results(run_dirs: list, hit_lookup: dict) -> list:
    results = []
    for i, run_dir in enumerate(run_dirs):
        label = _run_label(run_dir.name)
        mp = run_dir / "marketed_slips.csv"
        if not mp.exists():
            continue
        with open(mp, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        slips = defaultdict(list)
        for r in rows:
            slips[r["slip"]].append(r)

        for slip_name, leg_rows in slips.items():
            leg_info = []
            for lr in leg_rows:
                key = (
                    lr["player"].strip(),
                    lr["stat"].strip(),
                    str(lr["line"]).strip(),
                    lr["direction"].strip().upper(),
                )
                leg_info.append({
                    "player": lr["player"].strip(),
                    "stat": lr["stat"].strip(),
                    "line": lr["line"].strip(),
                    "direction": lr["direction"].strip().upper(),
                    "tier": lr.get("tier", "").upper(),
                    "hit": hit_lookup.get(key),
                })

            scored = [l for l in leg_info if l["hit"] is not None]
            if len(scored) < len(leg_info):
                continue  # skip unscored slips

            won = all(l["hit"] == 1 for l in scored)
            try:
                n_legs = int(float(leg_rows[0].get("n_legs", len(leg_rows))))
            except Exception:
                n_legs = len(leg_rows)
            try:
                hit_prob = float(leg_rows[0].get("hit_prob", 0))
            except Exception:
                hit_prob = 0.0

            results.append({
                "run_label": label,
                "slip_name": slip_name,
                "n_legs": n_legs,
                "won": won,
                "legs": leg_info,
                "hit_prob": hit_prob,
            })
    return results


def _payout_str(n_legs: int) -> str:
    mult = POWER_PAYOUTS.get(n_legs, n_legs * 2)
    total = EXAMPLE_STAKE * mult
    return f"${EXAMPLE_STAKE} bet → **${total}** ({mult}x payout)"


def _build_embed_manual(wins: int, total: int, target_date: str, note: str = None, slip_fields: list = None) -> dict:
    """Build a results embed with manually supplied win/total counts and optional slip detail fields."""
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d")
        date_label = d.strftime("%A, %B %d").replace(" 0", " ")
    except Exception:
        date_label = target_date

    color = 0x4ADE80 if wins >= total / 2 else 0xF5A623 if wins > 0 else 0xF87171
    description = (
        f"**{wins}/{total} slips hit** — {date_label}\n\n"
        f"We target 1 in 3. Yesterday we went **{wins} for {total}**."
        + (" Here's what cashed 👇" if wins > 0 else " Tough slate — the model stays disciplined.")
    )
    if note:
        description += f"\n\n{note}"

    fields = list(slip_fields) if slip_fields else []
    fields.append({
        "name": "Today's Picks",
        "value": "Full slips + rankings at **[atlassports.ai/dashboard](https://atlassports.ai/dashboard/)** — Premium members get all 3 daily slips.",
        "inline": False,
    })
    return {
        "title": f"🏀 Atlas Premium Slips — {date_label} Results",
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "Atlas Sports AI • atlassports.ai • Past results do not guarantee future performance"},
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _build_embed(slip_results: list, target_date: str, note: str = None) -> dict:
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d")
        date_label = d.strftime("%A, %B %d").replace(" 0", " ")
    except Exception:
        date_label = target_date

    if not slip_results:
        return {
            "title": f"🏀 Atlas Premium Slips — {date_label}",
            "description": "No marketed slip results available for this date.",
            "color": 0x444444,
        }

    total = len(slip_results)
    wins = [r for r in slip_results if r["won"]]
    n_wins = len(wins)
    color = 0x4ADE80 if n_wins >= total / 2 else 0xF5A623 if n_wins > 0 else 0xF87171

    description = (
        f"**{n_wins}/{total} premium slips hit** — {date_label}\n\n"
        f"We target 1 in 3. Yesterday we went **{n_wins} for {total}**."
        + (" Here's what cashed 👇" if wins else " Tough slate — the model stays disciplined.")
    )
    if note:
        description += f"\n\n{note}"

    fields = []
    seen_win_keys = set()
    for w in wins:
        # Dedupe identical slip compositions shown in different runs
        win_key = frozenset(
            (l["player"], l["stat"], l["line"], l["direction"]) for l in w["legs"]
        )
        if win_key in seen_win_keys:
            continue
        seen_win_keys.add(win_key)
        leg_lines = []
        for l in w["legs"]:
            emoji = TIER_EMOJI.get(l["tier"], "🔵")
            leg_lines.append(f"{emoji} {l['player']} **{l['direction']} {l['stat']} {l['line']}**")
        leg_lines.append(f"💰 {_payout_str(w['n_legs'])}")
        fields.append({
            "name": f"✅ {w['run_label']} — {w['slip_name']} WIN",
            "value": "\n".join(leg_lines),
            "inline": False,
        })

    if not wins:
        fields.append({
            "name": "Result",
            "value": "0 slips hit yesterday. Today's board is live with fresh picks.",
            "inline": False,
        })

    fields.append({
        "name": "Today's Picks",
        "value": "Full slips + rankings at **[atlassports.ai/dashboard](https://atlassports.ai/dashboard/)** — Premium members get all 3 daily slips.",
        "inline": False,
    })

    return {
        "title": f"🏀 Atlas Premium Slips — {date_label} Results",
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "Atlas Sports AI • atlassports.ai • Past results do not guarantee future performance"},
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def post_to_discord(embed: dict, dry_run: bool = False,
                    webhook_url: str = "") -> bool:
    """Send an embed via bot token (preferred) or webhook (fallback)."""
    payload = {"embeds": [embed]}
    if dry_run:
        print("[DISCORD] DRY RUN -- payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return True

    bot_token = _get_env("ATLAS_DISCORD_BOT_TOKEN")
    channel_id = _get_env("ATLAS_DISCORD_CHANNEL_ID")

    if bot_token and channel_id:
        try:
            import urllib.request, urllib.error
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bot {bot_token}",
                    "User-Agent": _DISCORD_UA,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok = resp.status in (200, 204)
            if ok:
                print("[DISCORD] OK Posted via bot")
            else:
                print("[DISCORD] Bot post returned unexpected status")
            return ok
        except Exception as e:
            print(f"[DISCORD] Bot post error: {e}")
            # Fall through to webhook

    if not webhook_url:
        print("[DISCORD] No bot token/channel or webhook URL set")
        return False

    try:
        import requests
    except ImportError:
        print("[DISCORD] ERROR 'requests' not installed.")
        return False
    try:
        resp = requests.post(webhook_url, json=payload, timeout=30)
        if resp.status_code in (200, 204):
            print(f"[DISCORD] OK Posted via webhook ({resp.status_code})")
            return True
        print(f"[DISCORD] FAIL HTTP {resp.status_code}: {resp.text[:300]}")
        return False
    except Exception as e:
        print(f"[DISCORD] ERROR {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas Discord poster — results or picks-today")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", type=str, default=None, help="Game date YYYY-MM-DD (results mode only, default: yesterday)")
    parser.add_argument("--picks-today", action="store_true", help="Post today's premium picks instead of yesterday's results")
    parser.add_argument("--run-dir", type=str, default=None, help="Specific run dir to score in results mode")
    parser.add_argument("--wins", type=int, default=None, help="Override win count (skips auto-compute from run dirs)")
    parser.add_argument("--total", type=int, default=None, help="Override total slip count")
    parser.add_argument("--note", type=str, default=None, help="Custom note appended to the embed description")
    args = parser.parse_args()

    if args.picks_today:
        return _main_picks_today(args)
    return _main_results(args)


def _main_results(args) -> int:
    webhook_url = _get_env("DISCORD_WEBHOOK_URL")
    bot_ready = bool(_get_env("ATLAS_DISCORD_BOT_TOKEN") and _get_env("ATLAS_DISCORD_CHANNEL_ID"))
    if not webhook_url and not bot_ready and not args.dry_run:
        print("[DISCORD] SKIP No ATLAS_DISCORD_BOT_TOKEN/CHANNEL_ID or DISCORD_WEBHOOK_URL set")
        return 0

    target_date = args.date or (date.today() - timedelta(days=1)).isoformat()

    # Manual override mode — skip auto-compute from run dirs
    wins_override = getattr(args, "wins", None)
    total_override = getattr(args, "total", None)
    note_override = getattr(args, "note", None)
    if wins_override is not None and total_override is not None:
        print(f"[DISCORD] Manual override: {wins_override}/{total_override} for {target_date}")
        embed = _build_embed_manual(wins_override, total_override, target_date, note=note_override)
        return 0 if post_to_discord(embed=embed, dry_run=args.dry_run, webhook_url=webhook_url) else 1

    print(f"[DISCORD] Loading marketed slip results for {target_date}...")

    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.is_absolute():
            run_dir = RUNS_DIR / args.run_dir
        expected_prefix = target_date.replace("-", "")
        if not run_dir.is_dir() or not run_dir.name.startswith(expected_prefix):
            print(f"[DISCORD] FAIL selected run dir does not match {target_date}: {run_dir}")
            return 1
        run_dirs = [run_dir]
        print(f"[DISCORD] Using selected report run: {run_dir.name}")
    else:
        run_dirs = _find_run_dirs(target_date)
    if not run_dirs:
        print(f"[DISCORD] SKIP No run dirs found for {target_date}")
        return 0

    print(f"[DISCORD] Found {len(run_dirs)} runs")
    hit_lookup = _build_hit_lookup(run_dirs, target_date)
    print(f"[DISCORD] Hit lookup: {len(hit_lookup)} scored legs")

    slip_results = _load_slip_results(run_dirs, hit_lookup)
    if not slip_results:
        print(f"[DISCORD] SKIP No scored marketed slips found for {target_date}")
        return 0

    wins = sum(1 for r in slip_results if r["won"])
    print(f"[DISCORD] {wins}/{len(slip_results)} slips hit")
    for r in slip_results:
        print(f"  {r['run_label']:8s} {r['slip_name']:6s}: {'WIN' if r['won'] else 'MISS'}")

    embed = _build_embed(slip_results, target_date, note=note_override)
    return 0 if post_to_discord(embed=embed, dry_run=args.dry_run, webhook_url=webhook_url) else 1


def _load_todays_picks() -> list:
    """Load marketed_slips.csv from the most recent run dir for today."""
    today_str = date.today().strftime("%Y%m%d")
    run_dirs = _find_run_dirs(date.today().isoformat())
    if not run_dirs:
        return []
    # Use the latest run
    latest = run_dirs[-1]
    mp = latest / "marketed_slips.csv"
    if not mp.exists():
        # Also check the output/runs latest symlink area
        latest_mp = DATA_DIR / "output" / "latest" / "marketed_slips.csv"
        if latest_mp.exists():
            mp = latest_mp
        else:
            return []
    slips = defaultdict(list)
    with open(mp, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            slips[row["slip"]].append(row)
    result = []
    for slip_name, legs in slips.items():
        try:
            hit_prob = float(legs[0].get("hit_prob", 0))
        except Exception:
            hit_prob = 0.0
        result.append({
            "slip_name": slip_name,
            "n_legs": len(legs),
            "hit_prob": hit_prob,
            "legs": [{
                "player": l["player"].strip(),
                "stat": l["stat"].strip(),
                "line": l["line"].strip(),
                "direction": l["direction"].strip().upper(),
                "tier": l.get("tier", "").upper(),
            } for l in legs],
        })
    return result


def _build_picks_embed(picks: list) -> dict:
    today_label = datetime.now().strftime("%A, %B %d").replace(" 0", " ")
    if not picks:
        return {
            "title": f"🏀 Atlas Premium Picks — {today_label}",
            "description": "No picks available yet. Check back after 11am ET.",
            "color": 0x444444,
        }

    mult_map = {3: "5x", 4: "10x", 5: "20x"}
    fields = []
    for p in picks:
        leg_lines = []
        for l in p["legs"]:
            emoji = TIER_EMOJI.get(l["tier"], "🔵")
            leg_lines.append(f"{emoji} {l['player']} **{l['direction']} {l['stat']} {l['line']}**")
        mult = mult_map.get(p["n_legs"], f"{p['n_legs']}x")
        hp = p["hit_prob"]
        leg_lines.append(f"📊 Win probability: **{hp:.1%}** | Payout: **{mult}**")
        fields.append({
            "name": f"🎯 {p['slip_name']}",
            "value": "\n".join(leg_lines),
            "inline": False,
        })

    fields.append({
        "name": "Full Rankings + Injury Report",
        "value": "All slips, confidence scores, and injury context at **[atlassports.ai/dashboard](https://atlassports.ai/dashboard/)**",
        "inline": False,
    })

    return {
        "title": f"🏀 Atlas Premium Picks — {today_label}",
        "description": f"**{len(picks)} slips** locked in for today. Model updated as of this run.",
        "color": 0x60A5FA,
        "fields": fields,
        "footer": {"text": "Atlas Sports AI • atlassports.ai • Not financial advice"},
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _main_picks_today(args) -> int:
    webhook_url = _get_env("DISCORD_PICKS_WEBHOOK_URL")
    bot_ready = bool(_get_env("ATLAS_DISCORD_BOT_TOKEN") and _get_env("ATLAS_DISCORD_CHANNEL_ID"))
    if not webhook_url and not bot_ready and not args.dry_run:
        print("[DISCORD-PICKS] SKIP No ATLAS_DISCORD_BOT_TOKEN/CHANNEL_ID or DISCORD_PICKS_WEBHOOK_URL set")
        return 0

    picks = _load_todays_picks()
    if not picks:
        print("[DISCORD-PICKS] SKIP No marketed_slips found for today")
        return 0

    print(f"[DISCORD-PICKS] Posting {len(picks)} slips for today")
    embed = _build_picks_embed(picks)
    return 0 if post_to_discord(embed=embed, dry_run=args.dry_run, webhook_url=webhook_url) else 1


if __name__ == "__main__":
    sys.exit(main())

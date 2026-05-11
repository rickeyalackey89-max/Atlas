#!/usr/bin/env python3
"""
Twitter Post Tool
==================
Two modes:

  Results mode (default — run by 6am eval script):
    Posts yesterday's marketed slip outcomes as a tweet.

  Picks-today mode (--picks-today — run by live pipeline):
    Posts today's top slip with player legs and a dashboard link.

Env vars (all stored in Windows User registry):
  ATLAS_TWITTER_API_KEY        — Consumer Key (OAuth 1.0a)
  ATLAS_TWITTER_API_SECRET     — Consumer Secret (OAuth 1.0a)
  ATLAS_TWITTER_ACCESS_TOKEN   — Access Token (for @AtlasSportsAI account)
  ATLAS_TWITTER_ACCESS_SECRET  — Access Token Secret
  ATLAS_DATA_DIR               — optional, defaults to data/

Usage:
    python tools/twitter_post.py                         # yesterday results
    python tools/twitter_post.py --date 2026-05-04       # specific date results
    python tools/twitter_post.py --picks-today           # today's top picks
    python tools/twitter_post.py --picks-today --dry-run # preview tweet text
"""

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", PROJECT_ROOT / "data"))
RUNS_DIR = DATA_DIR / "output" / "runs"

TWITTER_API_URL = "https://api.twitter.com/2/tweets"
POWER_PAYOUTS = {3: 5, 4: 10, 5: 20}
TIER_EMOJI = {"GOBLIN": "\U0001f7e2", "STANDARD": "\U0001f535", "DEMON": "\U0001f534"}


def _get_env(name: str) -> str:
    """Read env var from process env, falling back to Windows User registry."""
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


def _oauth1_auth_header(method: str, url: str,
                         api_key: str, api_secret: str,
                         access_token: str, access_secret: str) -> str:
    """
    Build an OAuth 1.0a Authorization header for a JSON-body POST.
    JSON body params are NOT included in the signature base string per the spec.
    """
    nonce = "".join(random.choices(string.ascii_letters + string.digits, k=32))
    ts = str(int(time.time()))

    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts,
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    # Percent-encode each key/value for the parameter string
    encoded = sorted(
        (urllib.parse.quote(k, safe=""), urllib.parse.quote(str(v), safe=""))
        for k, v in oauth_params.items()
    )
    param_str = "&".join(f"{k}={v}" for k, v in encoded)

    # Signature base string: METHOD & encoded_url & encoded_param_str
    base_str = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_str, safe=""),
    ])

    # Signing key: encoded_consumer_secret & encoded_token_secret
    signing_key = (
        urllib.parse.quote(api_secret, safe="")
        + "&"
        + urllib.parse.quote(access_secret, safe="")
    )

    sig_bytes = hmac.new(
        signing_key.encode("utf-8"),
        base_str.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = base64.b64encode(sig_bytes).decode("ascii")

    oauth_params["oauth_signature"] = signature

    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return header


def post_tweet(text: str, dry_run: bool = False) -> bool:
    """Post a tweet to @AtlasSportsAI. Returns True on success."""
    if dry_run:
        print("[TWITTER] DRY RUN — tweet text:")
        print("-" * 60)
        print(text)
        print("-" * 60)
        print(f"[TWITTER] Length: {len(text)} chars")
        return True

    api_key = _get_env("ATLAS_TWITTER_API_KEY")
    api_secret = _get_env("ATLAS_TWITTER_API_SECRET")
    access_token = _get_env("ATLAS_TWITTER_ACCESS_TOKEN")
    access_secret = _get_env("ATLAS_TWITTER_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        missing = [n for n, v in [
            ("ATLAS_TWITTER_API_KEY", api_key),
            ("ATLAS_TWITTER_API_SECRET", api_secret),
            ("ATLAS_TWITTER_ACCESS_TOKEN", access_token),
            ("ATLAS_TWITTER_ACCESS_SECRET", access_secret),
        ] if not v]
        print(f"[TWITTER] SKIP Missing env vars: {', '.join(missing)}")
        return False

    auth_header = _oauth1_auth_header(
        "POST", TWITTER_API_URL,
        api_key, api_secret, access_token, access_secret,
    )

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        TWITTER_API_URL,
        data=payload,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "User-Agent": "AtlasPropsBot/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            tweet_id = result.get("data", {}).get("id", "unknown")
            print(f"[TWITTER] OK Tweet posted — id={tweet_id}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[TWITTER] FAIL HTTP {e.code}: {body[:300]}")
        return False
    except Exception as exc:
        print(f"[TWITTER] ERROR {exc}")
        return False


# ---------------------------------------------------------------------------
# Data loading — mirrors discord_post.py helpers
# ---------------------------------------------------------------------------

def _find_run_dirs(target_date: str) -> list:
    prefix = target_date.replace("-", "")
    if not RUNS_DIR.exists():
        return []
    dirs = sorted(
        [d for d in RUNS_DIR.iterdir() if d.is_dir() and d.name.startswith(prefix)],
        key=lambda d: d.name,
    )
    return [d for d in dirs if len(d.name) == 15 and d.name[8] == "_"]


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


def _load_todays_picks() -> list:
    """Load marketed_slips.csv from the most recent run dir for today."""
    run_dirs = _find_run_dirs(date.today().isoformat())
    if not run_dirs:
        latest_mp = DATA_DIR / "output" / "latest" / "marketed_slips.csv"
        if not latest_mp.exists():
            return []
        source = latest_mp
    else:
        latest = run_dirs[-1]
        source = latest / "marketed_slips.csv"
        if not source.exists():
            latest_mp = DATA_DIR / "output" / "latest" / "marketed_slips.csv"
            source = latest_mp if latest_mp.exists() else None
        if source is None:
            return []

    slips = defaultdict(list)
    with open(source, newline="", encoding="utf-8-sig") as f:
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
    # Sort by hit_prob descending — post best slip first
    result.sort(key=lambda x: x["hit_prob"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Tweet text builders
# ---------------------------------------------------------------------------

def _build_picks_tweet(picks: list) -> str:
    today_label = datetime.now().strftime("%B %d").lstrip("0")
    mult_map = {3: "5\u00d7", 4: "10\u00d7", 5: "20\u00d7"}

    if not picks:
        return (
            f"\U0001f3c0 Atlas Picks — {today_label}\n\n"
            "No slips locked yet. Check back after 11am ET.\n\n"
            "atlassports.ai/dashboard"
        )

    # Use the top slip (highest hit_prob)
    top = picks[0]
    n = top["n_legs"]
    mult = mult_map.get(n, f"{n}\u00d7")
    hp = top["hit_prob"]

    lines = [f"\U0001f3c0 Atlas {n}-Leg System Slip — {today_label}\n"]
    for leg in top["legs"]:
        emoji = TIER_EMOJI.get(leg["tier"], "\U0001f535")
        lines.append(f"{emoji} {leg['player']} {leg['direction']} {leg['stat']} {leg['line']}")

    lines.append(f"\n{hp:.1%} hit prob \u00b7 {mult} payout")
    lines.append("\nFull picks \u2192 atlassports.ai/dashboard")
    lines.append("#AtlasProps #NBAProps #PrizePicks")

    tweet = "\n".join(lines)

    # Hard trim to 280 chars — remove hashtags first if needed
    if len(tweet) > 280:
        lines_no_tags = lines[:-1]
        tweet = "\n".join(lines_no_tags)
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    return tweet


def _build_results_tweet(target_date: str, wins: int, total: int) -> str:
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d")
        date_label = d.strftime("%B %d").lstrip("0")
    except Exception:
        date_label = target_date

    if wins == 0:
        verdict = "Miss \u2014 tough slate. Model stays disciplined."
        emoji = "\U0001f534"
    elif wins >= total:
        verdict = f"All {total} slips HIT \U0001f4b0"
        emoji = "\u2705"
    else:
        payout_str = f"{POWER_PAYOUTS.get(4, 10)}\u00d7" if wins > 0 else ""
        verdict = f"{wins}/{total} slips hit {payout_str}"
        emoji = "\u2705" if wins > 0 else "\U0001f534"

    return (
        f"\U0001f3c0 Atlas Results \u2014 {date_label}\n\n"
        f"{emoji} {verdict}\n\n"
        f"Full track record \u2192 atlassports.ai\n"
        f"#AtlasProps #NBAProps"
    )


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def _main_picks_today(args) -> int:
    picks = _load_todays_picks()
    if not picks:
        print("[TWITTER-PICKS] SKIP No marketed_slips found for today")
        return 0
    print(f"[TWITTER-PICKS] Found {len(picks)} slips, posting top slip")
    tweet = _build_picks_tweet(picks)
    return 0 if post_tweet(tweet, dry_run=args.dry_run) else 1


def _main_results(args) -> int:
    target_date = args.date or (date.today() - timedelta(days=1)).isoformat()

    wins_override = getattr(args, "wins", None)
    total_override = getattr(args, "total", None)

    if wins_override is not None and total_override is not None:
        tweet = _build_results_tweet(target_date, wins_override, total_override)
        return 0 if post_tweet(tweet, dry_run=args.dry_run) else 1

    print(f"[TWITTER] Loading results for {target_date}...")
    run_dirs = _find_run_dirs(target_date)
    if not run_dirs:
        print(f"[TWITTER] SKIP No run dirs found for {target_date}")
        return 0

    hit_lookup = _build_hit_lookup(run_dirs, target_date)
    # Count slips from marketed_slips.csv
    total = 0
    wins = 0
    for run_dir in run_dirs:
        mp = run_dir / "marketed_slips.csv"
        if not mp.exists():
            continue
        slips = defaultdict(list)
        with open(mp, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                slips[row["slip"]].append(row)
        for slip_name, leg_rows in slips.items():
            leg_keys = [
                (lr["player"].strip(), lr["stat"].strip(),
                 str(lr["line"]).strip(), lr["direction"].strip().upper())
                for lr in leg_rows
            ]
            hits = [hit_lookup.get(k) for k in leg_keys]
            if any(h is None for h in hits):
                continue
            total += 1
            if all(h == 1 for h in hits):
                wins += 1

    if total == 0:
        print(f"[TWITTER] SKIP No scored slips for {target_date}")
        return 0

    print(f"[TWITTER] {wins}/{total} slips hit for {target_date}")
    tweet = _build_results_tweet(target_date, wins, total)
    return 0 if post_tweet(tweet, dry_run=args.dry_run) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas Twitter poster — results or picks-today")
    parser.add_argument("--dry-run", action="store_true", help="Print tweet without posting")
    parser.add_argument("--date", type=str, default=None, help="Game date YYYY-MM-DD (results mode)")
    parser.add_argument("--picks-today", action="store_true", help="Post today's top slip instead of results")
    parser.add_argument("--wins", type=int, default=None, help="Override win count")
    parser.add_argument("--total", type=int, default=None, help="Override total slip count")
    args = parser.parse_args()

    if args.picks_today:
        return _main_picks_today(args)
    return _main_results(args)


if __name__ == "__main__":
    sys.exit(main())

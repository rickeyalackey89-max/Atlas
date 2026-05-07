"""
Discord slip notification for Atlas live runs.

Reads ATLAS_DISCORD_WEBHOOK from environment (never from config or source).
Falls back gracefully — a Discord failure never crashes the pipeline.

Message format: one embed per slip family (System, Windfall, DemonHunter),
top-N slips each, formatted as clean leg lists with tier emoji and p_cal.
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

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

# Tier emojis
_TIER = {"DEMON": "🔴", "GOBLIN": "🟢", "STANDARD": "⚪"}
_STAT_SHORT = {
    "POINTS": "PTS", "REBOUNDS": "REB", "ASSISTS": "AST",
    "THREES": "3PM", "FG3M": "3PM", "PRA": "PRA", "PR": "PR",
    "PA": "PA", "RA": "RA",
}


def _stat(s: str) -> str:
    return _STAT_SHORT.get(str(s).upper().strip(), str(s).upper().strip())


def _fmt_leg(row: dict) -> str:
    tier_em = _TIER.get(str(row.get("tier", "STANDARD")).upper(), "⚪")
    player = str(row.get("player", "?")).split(",")[0].strip()
    stat = _stat(row.get("stat", "?"))
    direction = str(row.get("direction", "")).upper()
    line = row.get("line", "?")
    p = row.get("p_cal", row.get("p", None))
    p_str = f" ({float(p):.0%})" if p is not None else ""
    dir_arrow = "↑" if direction == "OVER" else "↓"
    return f"{tier_em} {player} {stat} {dir_arrow}{line}{p_str}"


def _slip_to_embed_field(slip_df: pd.DataFrame, slip_idx: int, family: str) -> str:
    """Format one slip (group of rows) as a Discord field value."""
    legs = []
    for _, row in slip_df.iterrows():
        legs.append(_fmt_leg(row.to_dict()))
    hit_prob = slip_df.iloc[0].get("hit_prob", slip_df.get("win_prob", pd.Series([None])).iloc[0]) if "hit_prob" in slip_df.columns else None
    prob_str = f"  Win prob: **{float(hit_prob):.0%}**" if hit_prob is not None else ""
    n = len(legs)
    header = f"**{family} Slip #{slip_idx + 1}** ({n}-leg){prob_str}"
    body = "\n".join(legs)
    return f"{header}\n{body}"


def _build_slip_blocks(df: pd.DataFrame, family: str, top_n: int = 3) -> list[str]:
    """Return list of formatted slip strings from a slip CSV dataframe."""
    if df is None or len(df) == 0:
        return []
    # Detect slip grouping column
    group_col = next((c for c in ("slip_id", "slip_label", "label", "slip") if c in df.columns), None)
    if group_col:
        groups = [grp for _, grp in df.groupby(group_col, sort=False)]
    else:
        # Fall back: group by n-leg chunks if no id column
        n_legs = int(df.iloc[0].get("n_legs", 3)) if "n_legs" in df.columns else 3
        groups = [df.iloc[i:i+n_legs] for i in range(0, len(df), n_legs)]

    blocks = []
    for i, grp in enumerate(groups[:top_n]):
        blocks.append(_slip_to_embed_field(grp, i, family))
    return blocks


def _read_slip_csv(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        try:
            return pd.read_csv(path)
        except Exception:
            return None
    return None


def _send_bot_message(payload: dict) -> bool:
    """POST JSON payload to Discord via bot token + channel ID. Returns True on success."""
    import time
    token = _get_env("ATLAS_DISCORD_BOT_TOKEN")
    channel_id = _get_env("ATLAS_DISCORD_CHANNEL_ID")
    if not token or not channel_id:
        return False
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {token}",
            "User-Agent": _DISCORD_UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        if e.code == 429:
            try:
                retry_after = json.loads(body).get("retry_after", 2)
            except Exception:
                retry_after = 2
            print(f"[DISCORD] Rate limited, retrying after {retry_after}s")
            time.sleep(float(retry_after) + 0.5)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp2:
                    return resp2.status in (200, 204)
            except Exception as e2:
                print(f"[DISCORD] Retry failed: {e2!r}")
                return False
        print(f"[DISCORD] FAIL HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[DISCORD] Send error: {e!r}")
        return False


def _send_webhook(webhook_url: str, payload: dict) -> bool:
    """POST JSON payload to a Discord webhook. Returns True on success. (Legacy fallback)"""
    import time
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; AtlasSports/1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        if e.code == 429:
            try:
                retry_after = json.loads(body).get("retry_after", 2)
            except Exception:
                retry_after = 2
            print(f"[DISCORD] Rate limited, retrying after {retry_after}s")
            time.sleep(float(retry_after) + 0.5)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp2:
                    return resp2.status in (200, 204)
            except Exception as e2:
                print(f"[DISCORD] Retry failed: {e2!r}")
                return False
        print(f"[DISCORD] FAIL HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[DISCORD] Send error: {e!r}")
        return False


def _fmt_marketed_slips(df: pd.DataFrame) -> list[str]:
    """Format marketed_slips.csv into Discord slip blocks, one block per slip size."""
    blocks = []
    for slip_label, grp in df.groupby("slip", sort=False):
        hit_prob = grp.iloc[0].get("hit_prob", None)
        payout = grp.iloc[0].get("payout_mult", None)
        ev = grp.iloc[0].get("ev", None)
        n = len(grp)
        parts = [f"**{slip_label}**"]
        if hit_prob is not None:
            parts.append(f"Win: **{float(hit_prob):.0%}**")
        if payout is not None:
            parts.append(f"{float(payout):.2f}x")
        if ev is not None:
            parts.append(f"EV: {float(ev):+.2f}")
        header = "  |  ".join(parts)
        legs = [_fmt_leg(row.to_dict()) for _, row in grp.iterrows()]
        blocks.append(header + "\n" + "\n".join(legs))
    return blocks


def notify_discord(run_dir: Path, cfg: Optional[dict] = None) -> None:
    """
    Post today's marketed slip picks to Discord.
    Prefers ATLAS_DISCORD_BOT_TOKEN + ATLAS_DISCORD_CHANNEL_ID (bot API).
    Falls back to ATLAS_DISCORD_WEBHOOK if bot vars not set.
    No-ops silently if neither is configured.
    """
    bot_token = _get_env("ATLAS_DISCORD_BOT_TOKEN")
    channel_id = _get_env("ATLAS_DISCORD_CHANNEL_ID")
    webhook_url = _get_env("ATLAS_DISCORD_WEBHOOK")

    use_bot = bool(bot_token and channel_id)
    use_webhook = bool(webhook_url)
    if not use_bot and not use_webhook:
        return

    # Also respect config opt-out
    discord_cfg = (cfg or {}).get("discord", {}) or {}
    if not discord_cfg.get("enabled", True):
        print("[DISCORD] Disabled via config, skipping.")
        return

    run_dir = Path(run_dir)
    game_date = datetime.now().strftime("%B %#d, %Y") if os.name == "nt" else datetime.now().strftime("%B %-d, %Y")

    # ── Primary source: marketed_slips.csv ────────────────────────────
    marketed_path = run_dir / "marketed_slips.csv"
    df = _read_slip_csv(marketed_path)

    if df is None or len(df) == 0:
        print("[DISCORD] No marketed_slips.csv found — skipping.")
        return

    blocks = _fmt_marketed_slips(df)

    if not blocks:
        print("[DISCORD] No slip data to post.")
        return

    # ── Build Discord embed ───────────────────────────────────────────
    description = "\n\n".join(blocks)
    if len(description) > 3900:
        description = description[:3900] + "\n…"

    embed = {
        "title": f"🏀 Atlas Picks — {game_date}",
        "description": description,
        "color": 0x00CFFF,
        "footer": {"text": "Atlas Sports AI • atlassports.ai"},
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    payload = {"embeds": [embed]}

    # Try bot first, fall back to webhook
    if use_bot:
        success = _send_bot_message(payload)
        method = "bot"
    else:
        thread_id = discord_cfg.get("thread_id", "")
        url = f"{webhook_url}?thread_id={thread_id}" if thread_id else webhook_url
        success = _send_webhook(url, payload)
        method = "webhook"

    if success:
        print(f"[DISCORD] Posted {len(blocks)} slip(s) via {method}.")
    else:
        print(f"[DISCORD] Post failed via {method}.")

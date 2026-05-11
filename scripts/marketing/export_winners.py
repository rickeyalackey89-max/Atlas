"""
export_winners.py — Daily winner graphic generator for Atlas.

Reads marketed_slips.csv + eval_legs.csv from the previous day's production runs,
identifies winning slips, builds an HTML graphic, and exports it to PNG via headless Chrome.

Usage:
    python scripts/marketing/export_winners.py                    # auto: yesterday's best winning slip
    python scripts/marketing/export_winners.py --date 20260507   # specific date
    python scripts/marketing/export_winners.py --run data/output/runs/20260507_143551  # specific run dir
    python scripts/marketing/export_winners.py --no-export       # HTML only, skip PNG render

Outputs (in scripts/marketing/):
    winners_YYYYMMDD.html
    winners_YYYYMMDD.png
"""
import argparse
import io
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import date, timedelta

# Ensure UTF-8 output on Windows (avoids cp1252 errors for → ✓ etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

SCRIPT_DIR = pathlib.Path(__file__).parent
WORKSPACE = SCRIPT_DIR.parent.parent          # Atlas root
RUNS_DIR  = WORKSPACE / "data" / "output" / "runs"
LOGO_REL  = "../../data/output/graphics/AtlasLogo.jpg"

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\13142\AppData\Local\Google\Chrome\Application\chrome.exe",
]
WIDTH, HEIGHT = 1080, 1080

# Stat code → display label
STAT_LABELS = {
    "PTS": "Points",
    "REB": "Rebounds",
    "AST": "Assists",
    "PRA": "Pts + Reb + Ast",
    "PR":  "Points + Rebounds",
    "PA":  "Points + Assists",
    "RA":  "Rebounds + Assists",
    "FTA": "Free Throw Attempts",
    "STL": "Steals",
    "BLK": "Blocks",
    "TOV": "Turnovers",
    "3PM": "3-Pointers Made",
    "BLST": "Blocks + Steals",
}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def find_chrome():
    for p in CHROME_PATHS:
        if pathlib.Path(p).exists():
            return p
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    raise FileNotFoundError("Chrome not found. Check CHROME_PATHS in this script.")


def stat_label(code: str) -> str:
    return STAT_LABELS.get(code.upper(), code)


def find_runs_for_date(date_str: str) -> list[pathlib.Path]:
    """Return all production run dirs for a given YYYYMMDD date, sorted by time."""
    dirs = sorted(
        [d for d in RUNS_DIR.iterdir() if d.name.startswith(date_str) and "test" not in d.name.lower()],
        key=lambda d: d.name,
    )
    return dirs


def check_slip_wins(run_dir: pathlib.Path):
    """
    Returns dict keyed by slip-size label ('3-leg', '4-leg', '5-leg') ->
    {'legs': [...leg dicts...], 'all_hit': bool, 'n_hit': int, 'hit_prob': float, 'payout_mult': float, 'ev': float}
    Returns None if data missing.
    """
    ef = run_dir / "eval_legs.csv"
    sf = run_dir / "marketed_slips.csv"
    if not ef.exists() or not sf.exists():
        return None

    ev = pd.read_csv(ef)
    sl = pd.read_csv(sf)
    if "hit" not in ev.columns:
        return None

    ev["_key"] = ev["player"].str.strip() + "|" + ev["stat"].str.strip() + "|" + ev["direction"].str.strip() + "|" + ev["line"].astype(str)
    hit_map = dict(zip(ev["_key"], ev["hit"]))

    results = {}
    for slip_name, grp in sl.groupby("slip"):
        grp = grp.copy()
        grp["_key"] = grp["player"].str.strip() + "|" + grp["stat"].str.strip() + "|" + grp["direction"].str.strip() + "|" + grp["line"].astype(str)
        grp["leg_hit"] = grp["_key"].map(hit_map)
        all_hit = bool(grp["leg_hit"].fillna(0).astype(bool).all())
        n_hit = int(grp["leg_hit"].fillna(0).sum())
        legs = []
        for _, row in grp.iterrows():
            legs.append({
                "player":    row["player"],
                "stat":      row["stat"],
                "direction": row["direction"],
                "line":      row["line"],
                "tier":      row["tier"],
                "p_cal":     row.get("p_cal", None),
                "hit":       row["leg_hit"],
            })
        results[slip_name] = {
            "legs":       legs,
            "all_hit":    all_hit,
            "n_hit":      n_hit,
            "hit_prob":   float(grp["hit_prob"].iloc[0]) if "hit_prob" in grp.columns else None,
            "payout_mult":float(grp["payout_mult"].iloc[0]) if "payout_mult" in grp.columns else None,
            "ev":         float(grp["ev"].iloc[0]) if "ev" in grp.columns else None,
        }
    return results


def pick_best_winning_slip(all_runs: list[pathlib.Path]):
    """
    Find the best (largest winning) slip from the given run dirs.
    Preference: 4-leg win > 3-leg win > 5-leg win (more credible to post).
    Returns (run_dir, slip_name, slip_data) or None.
    """
    preference = ["4-leg", "5-leg", "3-leg"]
    for size in preference:
        # Prefer the latest run that has a win for this size
        for run_dir in reversed(all_runs):
            wins = check_slip_wins(run_dir)
            if wins and size in wins and wins[size]["all_hit"]:
                return run_dir, size, wins[size]
    return None


def featured_player(slip_data: dict) -> dict:
    """Return the featured leg — first GOBLIN, else first leg."""
    legs = slip_data["legs"]
    for lg in legs:
        if str(lg["tier"]).upper() == "GOBLIN":
            return lg
    return legs[0]


def find_player_image(player_name: str) -> str | None:
    """Look for a local jpg/png matching the player name in marketing dir."""
    name_slug = player_name.lower().replace(" ", "_")
    for ext in (".jpg", ".jpeg", ".png"):
        p = SCRIPT_DIR / (name_slug + ext)
        if p.exists():
            return f"./{p.name}"
    return None


def avg_confidence(slip_data: dict) -> float | None:
    vals = [lg["p_cal"] for lg in slip_data["legs"] if lg["p_cal"] is not None and not pd.isna(lg["p_cal"])]
    return round(sum(vals) / len(vals) * 100, 1) if vals else None


def tier_css(tier: str) -> str:
    t = str(tier).upper()
    if t == "GOBLIN":
        return "tier-goblin"
    if t == "DEMON":
        return "tier-demon"
    return "tier-standard"


def dir_css(direction: str) -> str:
    return "leg-over" if direction.upper() == "OVER" else "leg-under"


def dir_class(direction: str) -> str:
    return "over" if direction.upper() == "OVER" else "under"


# ─────────────────────────────────────────────
# HTML builder
# ─────────────────────────────────────────────

def build_html(slip_name: str, slip_data: dict, game_date: str, player_img: str | None, fallback_num: str = "#31") -> str:
    feat = featured_player(slip_data)
    feat_name = feat["player"]
    feat_parts = feat_name.split()
    feat_first = feat_parts[0] if feat_parts else ""
    feat_last  = " ".join(feat_parts[1:]) if len(feat_parts) > 1 else ""

    img_html = ""
    if player_img:
        img_html = f'<img src="{player_img}" onerror="this.style.display=\'none\'; document.getElementById(\'fb\').style.display=\'flex\';" alt="{feat_name}" />'
    else:
        img_html = '<img src="" onerror="this.style.display=\'none\'; document.getElementById(\'fb\').style.display=\'flex\';" alt="" />'

    legs_html = ""
    for i, lg in enumerate(slip_data["legs"], 1):
        d_css  = dir_css(lg["direction"])
        d_cls  = dir_class(lg["direction"])
        t_css  = tier_css(lg["tier"])
        line_v = lg["line"]
        slab   = stat_label(lg["stat"])
        name   = lg["player"]
        tier   = str(lg["tier"]).upper()
        direction = lg["direction"].upper()
        legs_html += f"""
      <div class="leg-row {d_css}">
        <span class="leg-check">✅</span>
        <div class="leg-player">
          <div class="leg-name">{name}</div>
          <div class="leg-stat-line">{lg['stat']} — {slab}</div>
        </div>
        <div class="leg-pick">
          <span class="leg-direction {d_cls}">{direction}</span>
          <span class="leg-line">{line_v}</span>
        </div>
        <span class="leg-tier {t_css}">{tier}</span>
      </div>"""

    n_legs   = len(slip_data["legs"])
    n_hit    = slip_data["n_hit"]
    # PrizePicks standard Power Play payouts by leg count
    PP_PAYOUTS = {3: "3×", 4: "10×", 5: "20×"}
    payout = PP_PAYOUTS.get(n_legs, f"{slip_data['payout_mult']:.1f}×" if slip_data["payout_mult"] else "—")
    avg_conf = avg_confidence(slip_data)
    avg_conf_str = f"{avg_conf:.0f}%" if avg_conf else "—"
    ev_str   = f"{slip_data['ev']:.2f}×" if slip_data["ev"] else "—"

    # Pretty date: 20260507 -> MAY 7, 2026
    try:
        d = date(int(game_date[:4]), int(game_date[4:6]), int(game_date[6:8]))
        pretty_date = d.strftime("%B %-d, %Y") if sys.platform != "win32" else d.strftime("%B %#d, %Y")
    except Exception:
        pretty_date = game_date

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080" />
<title>Atlas — WINNERS · {pretty_date}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;900&family=Space+Grotesk:wght@400;500;600;700&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    width: 1080px;
    height: 1080px;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Space Grotesk', sans-serif;
    overflow: hidden;
  }}

  .card {{
    width: 1080px;
    height: 1080px;
    position: relative;
    overflow: hidden;
    background: #000000;
  }}

  .grid-bg {{
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,212,255,0.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,212,255,0.022) 1px, transparent 1px);
    background-size: 80px 80px;
    pointer-events: none;
    z-index: 0;
  }}

  .glow-tr {{
    position: absolute;
    top: -200px; right: -200px;
    width: 650px; height: 650px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0,230,118,0.10) 0%, transparent 65%);
    pointer-events: none;
    z-index: 0;
  }}
  .glow-bl {{
    position: absolute;
    bottom: -150px; left: -150px;
    width: 500px; height: 500px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0,212,255,0.08) 0%, transparent 65%);
    pointer-events: none;
    z-index: 0;
  }}

  .okc-bar {{
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
    background: linear-gradient(180deg, #00e676 0%, rgba(0,230,118,0.3) 60%, transparent 100%);
    z-index: 20;
  }}

  .top-bar {{
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 70px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 48px;
    border-bottom: 1px solid rgba(0,230,118,0.15);
    z-index: 30;
    background: rgba(0,0,0,0.88);
    backdrop-filter: blur(10px);
  }}
  .logo .a {{ color: #fff; font-family: 'Barlow Condensed', sans-serif; font-size: 22px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; }}
  .logo .p {{ color: #00d4ff; font-family: 'Barlow Condensed', sans-serif; font-size: 22px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; }}

  .winners-badge {{
    display: flex;
    align-items: center;
    gap: 9px;
    background: rgba(0,230,118,0.10);
    border: 1px solid rgba(0,230,118,0.40);
    border-radius: 100px;
    padding: 7px 22px;
  }}
  .badge-text {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.20em;
    text-transform: uppercase;
    color: #00e676;
  }}
  .top-date {{
    font-size: 13px;
    font-weight: 500;
    color: rgba(255,255,255,0.38);
    letter-spacing: 0.07em;
  }}

  .photo-hero {{
    position: absolute;
    top: 70px; left: 0; right: 0;
    height: 475px;
    z-index: 1;
    overflow: hidden;
  }}
  .photo-hero img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 15%;
    filter: saturate(1.05) contrast(1.05);
  }}
  .photo-hero::after {{
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(180deg,
      transparent 0%, transparent 30%,
      rgba(0,0,0,0.55) 60%, rgba(0,0,0,0.92) 85%, #000000 100%
    );
  }}
  .photo-hero::before {{
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg,
      rgba(0,0,0,0.45) 0%, transparent 20%,
      transparent 80%, rgba(0,0,0,0.45) 100%
    );
    z-index: 1;
  }}
  .photo-fallback {{
    width: 100%;
    height: 100%;
    background: linear-gradient(160deg, #001020 0%, #001830 40%, #000000 100%);
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .fallback-number {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 280px;
    font-weight: 900;
    color: rgba(0,212,255,0.10);
    line-height: 1;
    user-select: none;
  }}

  .player-overlay {{
    position: absolute;
    top: 70px; left: 0; right: 0;
    height: 475px;
    z-index: 5;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    padding: 0 52px 28px 52px;
    pointer-events: none;
  }}
  .hero-eyebrow {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: #00e676;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .hero-eyebrow::before {{
    content: '';
    display: block;
    width: 22px; height: 2px;
    background: #00e676;
    border-radius: 1px;
  }}
  .hero-name {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 72px;
    font-weight: 900;
    line-height: 0.88;
    color: #fff;
    letter-spacing: -0.01em;
    text-transform: uppercase;
    text-shadow: 0 2px 20px rgba(0,0,0,0.8);
    margin-bottom: 10px;
  }}
  .hero-sub {{
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.38);
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .hero-sub .dot {{
    width: 5px; height: 5px;
    border-radius: 50%;
    background: #00e676;
  }}

  .content {{
    position: absolute;
    left: 0; right: 0;
    top: 550px;
    bottom: 78px;
    padding: 16px 52px 14px 52px;
    display: flex;
    flex-direction: column;
    z-index: 10;
  }}

  .winners-headline {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 52px;
    font-weight: 900;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #00e676;
    line-height: 1;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 14px;
    text-shadow: 0 0 40px rgba(0,230,118,0.35);
  }}
  .winners-sub {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.20em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.28);
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .winners-sub::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(0,230,118,0.15);
  }}

  .section-title {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.28);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .section-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.07);
  }}

  .legs {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 18px;
  }}
  .leg-row {{
    background: rgba(0,230,118,0.05);
    border: 1px solid rgba(0,230,118,0.20);
    border-radius: 13px;
    padding: 11px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    position: relative;
    overflow: hidden;
  }}
  .leg-row::before {{
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 3px;
    border-radius: 13px 0 0 13px;
  }}
  .leg-row.leg-over::before  {{ background: #00e676; }}
  .leg-row.leg-under::before {{ background: #f87171; }}

  .leg-check {{ font-size: 16px; line-height: 1; min-width: 20px; text-align: center; }}
  .leg-player {{ flex: 1; }}
  .leg-name {{ font-size: 14px; font-weight: 700; color: #fff; line-height: 1.1; margin-bottom: 2px; }}
  .leg-stat-line {{ font-size: 11px; color: rgba(255,255,255,0.35); font-weight: 500; }}
  .leg-pick {{ display: flex; align-items: center; gap: 7px; }}
  .leg-direction {{ font-family: 'Barlow Condensed', sans-serif; font-size: 18px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.04em; }}
  .leg-direction.over  {{ color: #00e676; }}
  .leg-direction.under {{ color: #f87171; }}
  .leg-line {{ font-family: 'Barlow Condensed', sans-serif; font-size: 22px; font-weight: 900; color: #fff; line-height: 1; }}
  .leg-tier {{ padding: 3px 9px; border-radius: 100px; font-size: 9px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; white-space: nowrap; }}
  .tier-goblin   {{ background: rgba(74,222,128,0.08);  color: #4ade80; border: 1px solid rgba(74,222,128,0.35); }}
  .tier-standard {{ background: rgba(96,165,250,0.08);  color: #60a5fa; border: 1px solid rgba(96,165,250,0.35); }}
  .tier-demon    {{ background: rgba(248,113,113,0.08); color: #f87171; border: 1px solid rgba(248,113,113,0.35); }}

  .stats-bar-wrap {{
    display: flex;
    gap: 10px;
    margin-top: auto;
  }}
  .stat-block {{
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 13px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
  }}
  .stat-block.hl {{ border-color: rgba(0,230,118,0.22); background: rgba(0,230,118,0.05); }}
  .stat-num {{ font-family: 'Barlow Condensed', sans-serif; font-size: 28px; font-weight: 900; line-height: 1; color: #00e676; }}
  .stat-num.gold {{ color: #f5a623; }}
  .stat-label {{ font-size: 9px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(255,255,255,0.65); text-align: center; }}

  .footer {{
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 48px;
    border-top: 1px solid rgba(0,230,118,0.09);
    z-index: 30;
    background: rgba(0,0,0,0.92);
    backdrop-filter: blur(10px);
  }}
  .footer-brand {{ font-family: 'Barlow Condensed', sans-serif; font-size: 17px; font-weight: 900; letter-spacing: 0.07em; text-transform: uppercase; color: rgba(255,255,255,0.45); }}
  .footer-handle {{ font-size: 14px; font-weight: 700; color: #00d4ff; letter-spacing: 0.04em; }}
  .footer-disc {{ font-size: 10px; color: rgba(255,255,255,0.18); letter-spacing: 0.04em; }}
</style>
</head>
<body>
<div class="card">

  <div class="grid-bg"></div>
  <div class="glow-tr"></div>
  <div class="glow-bl"></div>
  <div class="okc-bar"></div>

  <div class="top-bar">
    <div class="logo"><span class="a">AtlasSports</span><span class="p">.Ai</span></div>
    <div class="winners-badge">
      <span class="badge-text">✅ Winners</span>
    </div>
    <div class="top-date">{pretty_date.upper()}</div>
  </div>

  <div class="photo-hero">
    {img_html}
    <div id="fb" class="photo-fallback" style="display:none;">
      <div class="fallback-number">{fallback_num}</div>
    </div>
  </div>

  <div class="player-overlay">
    <div class="hero-eyebrow">{n_legs}-Leg System — All Hit</div>
    <div class="hero-name">{feat_first}<br>{feat_last}</div>
    <div class="hero-sub">
      <div class="dot"></div>
      Featured Leg
    </div>
  </div>

  <div class="content">

    <div class="winners-headline">✅ Winner</div>
    <div class="winners-sub">{n_legs}-Leg <span style="color:#f5a623;font-weight:700;">Premium</span> Slip · {pretty_date}</div>

    <div class="section-title">All Legs Hit</div>
    <div class="legs">
{legs_html}
    </div>

    <div class="stats-bar-wrap">
      <div class="stat-block hl">
        <span class="stat-num">{n_hit} / {n_legs}</span>
        <span class="stat-label">Legs Hit</span>
      </div>
      <div class="stat-block hl">
        <span class="stat-num gold">{payout}</span>
        <span class="stat-label">Payout</span>
      </div>
      <div class="stat-block hl">
        <span class="stat-num">{avg_conf_str}</span>
        <span class="stat-label">Avg Confidence</span>
      </div>
      <div class="stat-block">
        <span class="stat-num gold">{ev_str}</span>
        <span class="stat-label">EV Mult</span>
      </div>
    </div>

  </div>

  <div class="footer">
    <div class="footer-brand">Atlas Props</div>
    <div class="footer-handle">@AtlasSportsAI</div>
    <div class="footer-disc">For entertainment only · Not financial advice</div>
  </div>

</div>
</body>
</html>"""


# ─────────────────────────────────────────────
# Export PNG
# ─────────────────────────────────────────────

def export_png(html_path: pathlib.Path, out_path: pathlib.Path):
    chrome = find_chrome()
    file_url = html_path.resolve().as_uri()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={WIDTH},{HEIGHT}",
        f"--screenshot={out_path.resolve()}",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        file_url,
    ]
    print(f"Rendering: {html_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out_path.exists() and out_path.stat().st_size > 10_000:
        print(f"✓ Exported {out_path.stat().st_size // 1024}KB → {out_path}")
        return True
    print("Export may have failed. Chrome stderr:")
    print(result.stderr[-2000:] if result.stderr else "(no stderr)")
    return False


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate daily winners graphic")
    parser.add_argument("--date", default=None, help="YYYYMMDD date (default: yesterday)")
    parser.add_argument("--run",  default=None, help="Specific run dir path (overrides --date)")
    parser.add_argument("--slip", default=None, help="Slip size to use: 3-leg / 4-leg / 5-leg (default: auto-pick)")
    parser.add_argument("--player-img", default=None, help="Path to player image (default: auto-detect from marketing dir)")
    parser.add_argument("--no-export", action="store_true", help="Skip PNG render (HTML only)")
    args = parser.parse_args()

    # Determine date
    if args.date:
        game_date = args.date
    else:
        yesterday = date.today() - timedelta(days=1)
        game_date = yesterday.strftime("%Y%m%d")

    print(f"[winners] Game date: {game_date}")

    # Find runs
    if args.run:
        run_dirs = [pathlib.Path(args.run)]
    else:
        run_dirs = find_runs_for_date(game_date)
        if not run_dirs:
            print(f"[ERROR] No run dirs found for {game_date} in {RUNS_DIR}")
            sys.exit(1)
        print(f"[winners] Found {len(run_dirs)} run(s): {[d.name for d in run_dirs]}")

    # Find best winning slip
    if args.slip:
        # User specified a slip size — just grab the first run that has a win for it
        result = None
        for run_dir in reversed(run_dirs):
            wins = check_slip_wins(run_dir)
            if wins and args.slip in wins and wins[args.slip]["all_hit"]:
                result = (run_dir, args.slip, wins[args.slip])
                break
        if not result:
            print(f"[WARN] No winning {args.slip} found. Searching for any winner...")
            result = pick_best_winning_slip(run_dirs)
    else:
        result = pick_best_winning_slip(run_dirs)

    if not result:
        print(f"[ERROR] No winning slips found for {game_date}. Cannot generate graphic.")
        sys.exit(1)

    run_dir, slip_name, slip_data = result
    print(f"[winners] Using: {slip_name} WIN from {run_dir.name} ({slip_data['n_hit']}/{len(slip_data['legs'])} hit)")

    # Player image
    feat = featured_player(slip_data)
    if args.player_img:
        player_img = args.player_img
    else:
        player_img = find_player_image(feat["player"])
        if player_img:
            print(f"[winners] Player image: {player_img}")
        else:
            print(f"[WARN] No image found for {feat['player']} in {SCRIPT_DIR}")
            print(f"       Drop a file named {feat['player'].lower().replace(' ', '_')}.jpg there to use it.")

    # Build HTML
    html_content = build_html(slip_name, slip_data, game_date, player_img)
    html_path = SCRIPT_DIR / f"winners_{game_date}.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"[winners] HTML → {html_path}")

    # Export PNG
    if not args.no_export:
        png_path = SCRIPT_DIR / f"winners_{game_date}.png"
        ok = export_png(html_path, png_path)
        if not ok:
            sys.exit(1)
    else:
        print("[winners] Skipping PNG render (--no-export)")

    print("\n[winners] Done.")


if __name__ == "__main__":
    main()

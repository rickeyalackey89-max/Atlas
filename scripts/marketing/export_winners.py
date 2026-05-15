#!/usr/bin/env python3
"""Daily winner graphic generator for Atlas.

Preferred source:
    eval_slips.csv generated during previous-day eval.

Usage:
    python scripts/marketing/export_winners.py --date 20260512 --run data/output/runs/20260512_185101
    python scripts/marketing/export_winners.py --eval-slips path/to/eval_slips.csv --date 20260512
    python scripts/marketing/export_winners.py --date 20260512 --no-export
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parents[1]
RUNS_DIR = WORKSPACE / "data" / "output" / "runs"
WIDTH, HEIGHT = 1080, 1080

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\13142\AppData\Local\Google\Chrome\Application\chrome.exe",
]

STAT_LABELS = {
    "PTS": "Points",
    "REB": "Rebounds",
    "AST": "Assists",
    "PRA": "Pts + Reb + Ast",
    "PR": "Points + Rebounds",
    "PA": "Points + Assists",
    "RA": "Rebounds + Assists",
    "FTA": "Free Throw Attempts",
    "STL": "Steals",
    "BLK": "Blocks",
    "TOV": "Turnovers",
    "3PM": "3-Pointers Made",
    "FG3M": "3-Pointers Made",
    "BLST": "Blocks + Steals",
}

FAMILY_ORDER = {
    "Marketed": 0,
    "Windfall": 1,
    "System": 2,
    "DemonHunter": 3,
}


def find_chrome() -> str:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    raise FileNotFoundError("Chrome not found. Check CHROME_PATHS in this script.")


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE / path


def find_runs_for_date(date_str: str) -> list[Path]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted(
        [run for run in RUNS_DIR.iterdir() if run.is_dir() and run.name.startswith(date_str)],
        key=lambda run: run.name,
    )


def pretty_date(date_str: str) -> str:
    try:
        d = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        if sys.platform == "win32":
            return d.strftime("%B %#d, %Y")
        return d.strftime("%B %-d, %Y")
    except Exception:
        return date_str


def stat_label(code: Any) -> str:
    text = str(code or "").upper()
    return STAT_LABELS.get(text, text)


def fmt_line(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return str(value or "")
    return f"{num:g}"


def fmt_prob(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "--"


def fmt_mult(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return "--"
    if abs(num - round(num)) < 0.001:
        return f"{int(round(num))}x"
    return f"{num:.2f}x"


def tier_css(tier: Any) -> str:
    text = str(tier or "").upper()
    if text == "GOBLIN":
        return "tier-goblin"
    if text == "DEMON":
        return "tier-demon"
    return "tier-standard"


def direction_css(direction: Any) -> str:
    return "dir-under" if str(direction or "").upper() == "UNDER" else "dir-over"


def find_player_image(player_name: str) -> str | None:
    slug = re.sub(r"[^a-z0-9]+", "_", player_name.lower()).strip("_")
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = SCRIPT_DIR / f"{slug}{ext}"
        if path.is_file():
            return f"./{path.name}"
    return None


def load_winners_from_eval_slips(eval_slips_path: Path) -> list[dict[str, Any]]:
    df = pd.read_csv(eval_slips_path)
    if df.empty:
        return []
    required = {"status", "legs_json", "family", "slip_label"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{eval_slips_path} missing columns: {sorted(missing)}")

    winners: list[dict[str, Any]] = []
    for _, row in df[df["status"].astype(str).str.lower() == "win"].iterrows():
        legs = json.loads(str(row.get("legs_json", "[]") or "[]"))
        winners.append(
            {
                "family": str(row.get("family", "")),
                "slip_label": str(row.get("slip_label", "")),
                "n_legs": int(float(row.get("n_legs", len(legs)) or len(legs))),
                "hit_count": int(float(row.get("hit_count", len(legs)) or len(legs))),
                "truth_legs": int(float(row.get("truth_legs", len(legs)) or len(legs))),
                "hit_prob": row.get("hit_prob"),
                "payout_mult": row.get("payout_mult"),
                "ev_mult": row.get("ev_mult"),
                "source_file": str(row.get("source_file", "")),
                "legs": legs,
            }
        )

    winners.sort(key=lambda slip: (FAMILY_ORDER.get(slip["family"], 99), -int(slip["n_legs"])))
    return winners


def resolve_eval_slips(args: argparse.Namespace, game_date: str) -> Path:
    if args.eval_slips:
        path = resolve_path(args.eval_slips)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    if args.run:
        run_dir = resolve_path(args.run)
        path = run_dir / "eval_slips.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Missing eval_slips.csv in {run_dir}")
        return path

    for run_dir in reversed(find_runs_for_date(game_date)):
        path = run_dir / "eval_slips.csv"
        if path.is_file():
            return path
    raise FileNotFoundError(f"No eval_slips.csv found for {game_date}")


def featured_player(winners: list[dict[str, Any]]) -> str:
    for slip in winners:
        for leg in slip["legs"]:
            player = str(leg.get("player", "") or "").strip()
            if player:
                return player
    return "Atlas"


def render_leg(leg: dict[str, Any]) -> str:
    player = html.escape(str(leg.get("player", "") or ""))
    stat = html.escape(str(leg.get("stat", "") or "").upper())
    direction = html.escape(str(leg.get("direction", "") or "").upper())
    line = html.escape(fmt_line(leg.get("line")))
    tier = html.escape(str(leg.get("tier", "") or "").upper())
    actual = html.escape(fmt_line(leg.get("actual")))
    return f"""
      <div class="leg">
        <div class="check">HIT</div>
        <div class="leg-main">
          <div class="leg-player">{player}</div>
          <div class="leg-meta"><span>{stat}</span>{html.escape(stat_label(stat))}</div>
        </div>
        <div class="pick {direction_css(direction)}">
          <span>{direction}</span>
          <strong>{line}</strong>
        </div>
        <div class="actual">ACTUAL<br><strong>{actual}</strong></div>
        <div class="tier {tier_css(tier)}">{tier}</div>
      </div>
    """


def render_slip(slip: dict[str, Any]) -> str:
    family = html.escape(slip["family"])
    label = html.escape(slip["slip_label"])
    hit_prob = fmt_prob(slip.get("hit_prob"))
    payout = fmt_mult(slip.get("payout_mult"))
    ev = fmt_mult(slip.get("ev_mult"))
    legs_html = "\n".join(render_leg(leg) for leg in slip["legs"])
    return f"""
    <section class="slip-card">
      <div class="slip-head">
        <div>
          <div class="slip-family">{family}</div>
          <div class="slip-label">{label} Winner</div>
        </div>
        <div class="hit-pill">{slip["hit_count"]}/{slip["truth_legs"]} HIT</div>
      </div>
      <div class="legs">
        {legs_html}
      </div>
      <div class="slip-stats">
        <div><strong>{payout}</strong><span>Payout</span></div>
        <div><strong>{hit_prob}</strong><span>Model Hit Prob</span></div>
        <div><strong>{ev}</strong><span>EV Mult</span></div>
      </div>
    </section>
    """


def build_html(winners: list[dict[str, Any]], game_date: str, player_img: str | None) -> str:
    date_text = pretty_date(game_date)
    hero = featured_player(winners)
    hero_name = html.escape(hero.upper())
    image_html = ""
    if player_img:
        image_html = f'<img src="{html.escape(player_img)}" alt="{html.escape(hero)}" />'

    slip_cards = "\n".join(render_slip(slip) for slip in winners)
    total_slips = len(winners)
    total_legs = sum(int(slip["truth_legs"]) for slip in winners)
    hit_legs = sum(int(slip["hit_count"]) for slip in winners)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=1080" />
<title>Atlas Winners - {html.escape(date_text)}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;900&family=Space+Grotesk:wght@400;500;600;700&display=swap');
  * {{ box-sizing: border-box; }}
  body {{
    width: 1080px;
    height: 1080px;
    margin: 0;
    overflow: hidden;
    background: #020403;
    color: #fff;
    font-family: "Space Grotesk", Arial, sans-serif;
  }}
  .card {{
    width: 1080px;
    height: 1080px;
    position: relative;
    overflow: hidden;
    background:
      linear-gradient(rgba(0, 230, 118, 0.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0, 212, 255, 0.030) 1px, transparent 1px),
      radial-gradient(circle at 78% 10%, rgba(0, 230, 118, 0.18), transparent 32%),
      radial-gradient(circle at 8% 95%, rgba(0, 212, 255, 0.13), transparent 30%),
      #020403;
    background-size: 72px 72px, 72px 72px, auto, auto, auto;
  }}
  .hero {{
    position: absolute;
    inset: 0 0 auto 0;
    height: 370px;
    overflow: hidden;
    border-bottom: 1px solid rgba(0, 230, 118, 0.22);
  }}
  .hero img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 14%;
    filter: saturate(1.08) contrast(1.04);
  }}
  .hero::after {{
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(180deg, rgba(0,0,0,0.20), rgba(0,0,0,0.92)),
      linear-gradient(90deg, rgba(0,0,0,0.80), transparent 55%, rgba(0,0,0,0.35));
  }}
  .top {{
    position: relative;
    z-index: 4;
    height: 370px;
    padding: 42px 54px 32px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .brand-row, .summary-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .brand {{
    font-family: "Barlow Condensed", sans-serif;
    font-size: 27px;
    font-weight: 900;
    letter-spacing: 0.10em;
    text-transform: uppercase;
  }}
  .brand span {{ color: #f5a623; }}
  .date {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.56);
  }}
  .eyebrow {{
    color: #00e676;
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    margin-bottom: 9px;
  }}
  .headline {{
    font-family: "Barlow Condensed", sans-serif;
    font-size: 86px;
    line-height: 0.86;
    font-weight: 900;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    text-shadow: 0 8px 28px rgba(0,0,0,0.72);
  }}
  .hero-player {{
    margin-top: 10px;
    color: rgba(255,255,255,0.58);
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.16em;
  }}
  .summary-pill {{
    min-width: 146px;
    padding: 12px 16px;
    border: 1px solid rgba(0,230,118,0.35);
    background: rgba(0,230,118,0.09);
    text-align: center;
  }}
  .summary-pill strong {{
    display: block;
    color: #00e676;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 38px;
    line-height: 1;
  }}
  .summary-pill span {{
    display: block;
    margin-top: 4px;
    color: rgba(255,255,255,0.58);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }}
  .content {{
    position: relative;
    z-index: 5;
    height: 710px;
    padding: 26px 54px 34px;
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: 18px;
  }}
  .content-title {{
    display: flex;
    justify-content: space-between;
    align-items: end;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding-bottom: 15px;
  }}
  .content-title h2 {{
    margin: 0;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 45px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .content-title p {{
    margin: 0;
    color: rgba(255,255,255,0.45);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }}
  .slips {{
    display: grid;
    grid-template-columns: repeat({min(total_slips, 2)}, 1fr);
    gap: 18px;
    min-height: 0;
  }}
  .slip-card {{
    border: 1px solid rgba(0,230,118,0.20);
    background: rgba(2, 10, 8, 0.84);
    padding: 18px;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }}
  .slip-head {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 14px;
    margin-bottom: 14px;
  }}
  .slip-family {{
    color: #f5a623;
    font-size: 11px;
    font-weight: 900;
    letter-spacing: 0.18em;
    text-transform: uppercase;
  }}
  .slip-label {{
    margin-top: 3px;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 34px;
    line-height: 1;
    font-weight: 900;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }}
  .hit-pill {{
    color: #00e676;
    border: 1px solid rgba(0,230,118,0.35);
    background: rgba(0,230,118,0.08);
    padding: 8px 10px;
    font-size: 12px;
    font-weight: 900;
    white-space: nowrap;
  }}
  .legs {{
    display: flex;
    flex-direction: column;
    gap: 9px;
  }}
  .leg {{
    min-height: 76px;
    display: grid;
    grid-template-columns: 42px minmax(0, 1fr) 78px 62px 72px;
    gap: 10px;
    align-items: center;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.035);
    padding: 10px;
  }}
  .check {{
    width: 38px;
    height: 38px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: #00e676;
    color: #00170a;
    font-size: 10px;
    font-weight: 900;
  }}
  .leg-player {{
    font-size: 15px;
    font-weight: 800;
    line-height: 1.08;
  }}
  .leg-meta {{
    margin-top: 6px;
    color: rgba(255,255,255,0.42);
    font-size: 9px;
    font-weight: 700;
    line-height: 1.15;
  }}
  .leg-meta span {{
    display: inline-block;
    margin-right: 7px;
    color: #f5a623;
    font-size: 9px;
    font-weight: 900;
    letter-spacing: 0.12em;
  }}
  .pick span {{
    display: block;
    font-family: "Space Grotesk", Arial, sans-serif;
    font-size: 12px;
    line-height: 1.05;
    font-weight: 800;
    letter-spacing: 0.10em;
  }}
  .pick strong {{
    display: block;
    margin-top: 4px;
    font-family: "Space Grotesk", Arial, sans-serif;
    font-size: 24px;
    line-height: 0.95;
    font-weight: 800;
    letter-spacing: 0;
  }}
  .dir-over {{ color: #00e676; }}
  .dir-under {{ color: #ff5f6d; }}
  .actual {{
    color: rgba(255,255,255,0.46);
    text-align: center;
    font-size: 9px;
    font-weight: 900;
    letter-spacing: 0.10em;
  }}
  .actual strong {{
    color: #fff;
    font-family: "Space Grotesk", Arial, sans-serif;
    font-size: 23px;
    line-height: 1.05;
    font-weight: 800;
  }}
  .tier {{
    justify-self: end;
    padding: 6px 8px;
    font-size: 9px;
    font-weight: 900;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    border: 1px solid rgba(255,255,255,0.14);
  }}
  .tier-goblin {{ color: #4ade80; border-color: rgba(74,222,128,0.38); background: rgba(74,222,128,0.06); }}
  .tier-standard {{ color: #60a5fa; border-color: rgba(96,165,250,0.38); background: rgba(96,165,250,0.06); }}
  .tier-demon {{ color: #f87171; border-color: rgba(248,113,113,0.38); background: rgba(248,113,113,0.06); }}
  .slip-stats {{
    margin-top: auto;
    padding-top: 14px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }}
  .slip-stats div {{
    border: 1px solid rgba(255,255,255,0.07);
    background: rgba(255,255,255,0.03);
    padding: 9px 6px;
    text-align: center;
  }}
  .slip-stats strong {{
    display: block;
    color: #00e676;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 25px;
    line-height: 1;
  }}
  .slip-stats span {{
    display: block;
    margin-top: 4px;
    color: rgba(255,255,255,0.42);
    font-size: 8px;
    font-weight: 900;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }}
  .footer {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: rgba(255,255,255,0.38);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
  }}
  .footer strong {{ color: #00d4ff; }}
</style>
</head>
<body>
  <div class="card">
    <div class="hero">{image_html}</div>
    <div class="top">
      <div class="brand-row">
        <div class="brand">Atlas <span>Sports AI</span></div>
        <div class="date">{html.escape(date_text).upper()}</div>
      </div>
      <div>
        <div class="eyebrow">Confirmed Results</div>
        <div class="headline">Yesterday's<br>Winners</div>
        <div class="hero-player">FEATURED: {hero_name}</div>
      </div>
      <div class="summary-row">
        <div class="summary-pill"><strong>{total_slips}</strong><span>Winning Slips</span></div>
        <div class="summary-pill"><strong>{hit_legs}/{total_legs}</strong><span>Winner Legs</span></div>
      </div>
    </div>
    <main class="content">
      <div class="content-title">
        <h2>All Legs Cashed</h2>
        <p>Only full winners shown</p>
      </div>
      <div class="slips">
        {slip_cards}
      </div>
      <div class="footer">
        <div>Atlas Props</div>
        <strong>@AtlasSportsAI</strong>
        <div>Entertainment only</div>
      </div>
    </main>
  </div>
</body>
</html>
"""


def export_png(html_path: Path, out_path: Path) -> bool:
    chrome = find_chrome()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={WIDTH},{HEIGHT}",
        f"--screenshot={out_path.resolve()}",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        html_path.resolve().as_uri(),
    ]
    print(f"[winners] Rendering {html_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if out_path.exists() and out_path.stat().st_size > 10_000:
        print(f"[winners] PNG -> {out_path} ({out_path.stat().st_size // 1024}KB)")
        return True
    print("[winners] Chrome render failed")
    print((result.stderr or result.stdout or "")[-2000:])
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Atlas winner graphic from eval_slips.csv")
    parser.add_argument("--date", default=None, help="YYYYMMDD date for output naming and display")
    parser.add_argument("--run", default=None, help="Run directory containing eval_slips.csv")
    parser.add_argument("--eval-slips", default=None, help="Direct path to eval_slips.csv")
    parser.add_argument("--player-img", default=None, help="Optional hero image path")
    parser.add_argument("--no-export", action="store_true", help="Write HTML only")
    args = parser.parse_args()

    game_date = args.date or (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    eval_slips_path = resolve_eval_slips(args, game_date)
    winners = load_winners_from_eval_slips(eval_slips_path)
    if not winners:
        print(f"[winners] No full winning slips in {eval_slips_path}")
        return 1

    hero = featured_player(winners)
    if args.player_img:
        player_img = str(resolve_path(args.player_img).resolve().as_uri())
    else:
        player_img = find_player_image(hero)
        if player_img:
            print(f"[winners] Player image: {player_img}")
        else:
            print(f"[winners] No local hero image found for {hero}; rendering without photo.")

    html_text = build_html(winners, game_date, player_img)
    html_path = SCRIPT_DIR / f"winners_{game_date}.html"
    png_path = SCRIPT_DIR / f"winners_{game_date}.png"
    html_path.write_text(html_text, encoding="utf-8")
    print(f"[winners] Source -> {eval_slips_path}")
    print(f"[winners] HTML -> {html_path}")
    print(f"[winners] Winners -> {len(winners)} slips")
    for slip in winners:
        print(f"[winners] {slip['family']} {slip['slip_label']} {slip['hit_count']}/{slip['truth_legs']} hit")

    if not args.no_export and not export_png(html_path, png_path):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

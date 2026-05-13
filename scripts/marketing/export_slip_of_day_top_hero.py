"""
Build and export an Atlas slip-of-the-day card with a top hero photo.

Example:
  python scripts/marketing/export_slip_of_day_top_hero.py ^
    --slip data/output/runs/20260512_185101/recommended_4leg.csv ^
    --highlight-player "Stephon Castle" ^
    --player-image scripts/marketing/stephon_castle.jpg
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path
from typing import Any

from export_graphic import export


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parents[1]

LEG_RE = re.compile(
    r"^(?P<player>.*?)\s+"
    r"(?P<direction>OVER|UNDER)\s+"
    r"(?P<stat>[A-Z0-9+]+)\s+"
    r"(?P<line>-?\d+(?:\.\d+)?)\s+"
    r"\((?P<tier>[A-Z]+)\)",
    re.IGNORECASE,
)

TIER_CLASS = {
    "GOBLIN": "tier-goblin",
    "STANDARD": "tier-standard",
    "DEMON": "tier-demon",
}


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "--"


def _fmt_mult(value: Any) -> str:
    try:
        v = float(value)
    except Exception:
        return "--"
    if abs(v - round(v)) < 0.001:
        return f"{int(round(v))}x"
    return f"{v:.2f}x"


def _parse_leg(text: str) -> dict[str, str]:
    match = LEG_RE.match(str(text or "").strip())
    if not match:
        return {
            "player": str(text or "").strip(),
            "direction": "",
            "stat": "",
            "line": "",
            "tier": "",
        }
    return {key: value.strip() for key, value in match.groupdict().items()}


def _load_slip(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"No slip rows found in {path}")
    row = rows[0]

    legs: list[dict[str, str]] = []
    for i in range(1, 6):
        value = row.get(f"leg_{i}", "")
        if value:
            legs.append(_parse_leg(value))
    if not legs and row.get("legs"):
        legs = [_parse_leg(part) for part in str(row["legs"]).split(" | ") if part.strip()]
    if not legs:
        raise ValueError(f"No leg text found in {path}")

    return row, legs


def _render_leg_rows(legs: list[dict[str, str]], highlight_player: str) -> str:
    highlight_norm = highlight_player.strip().lower()
    rows: list[str] = []
    for idx, leg in enumerate(legs, start=1):
        tier = leg.get("tier", "").upper()
        tier_class = TIER_CLASS.get(tier, "tier-standard")
        player = html.escape(leg.get("player", ""))
        direction = html.escape(leg.get("direction", "").upper())
        stat = html.escape(leg.get("stat", "").upper())
        line = html.escape(leg.get("line", ""))
        is_highlight = leg.get("player", "").strip().lower() == highlight_norm
        rows.append(
            f"""
            <div class="leg-row {'highlight' if is_highlight else ''}">
              <div class="leg-index">{idx}</div>
              <div class="leg-main">
                <div class="leg-player">{player}</div>
                <div class="leg-pick"><span>{direction}</span> {stat} {line}</div>
              </div>
              <div class="tier {tier_class}">{html.escape(tier)}</div>
            </div>
            """
        )
    return "\n".join(rows)


def build_html(
    *,
    slip_path: Path,
    player_image: Path,
    highlight_player: str,
    output_html: Path,
) -> Path:
    row, legs = _load_slip(slip_path)
    n_legs = int(float(row.get("n_legs") or len(legs)))
    image_uri = player_image.resolve().as_uri()
    leg_rows = _render_leg_rows(legs, highlight_player)
    hit_prob = _fmt_pct(row.get("hit_prob"))
    payout = _fmt_mult(row.get("payout_mult"))
    ev = _fmt_mult(row.get("ev_mult"))
    avg_p = _fmt_pct(row.get("avg_p"))

    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080" />
<title>Atlas Slip of the Day</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 1080px;
    height: 1080px;
    overflow: hidden;
    background: #030507;
    font-family: "Arial", "Segoe UI", sans-serif;
    color: #fff;
  }}
  .card {{
    width: 1080px;
    height: 1080px;
    position: relative;
    overflow: hidden;
    background:
      linear-gradient(rgba(0, 212, 255, 0.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0, 212, 255, 0.035) 1px, transparent 1px),
      #030507;
    background-size: 72px 72px;
  }}
  .hero {{
    position: absolute;
    left: 0;
    top: 0;
    width: 1080px;
    height: 500px;
    overflow: hidden;
  }}
  .hero img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 34%;
    filter: saturate(1.08) contrast(1.08);
  }}
  .hero::after {{
    content: "";
    position: absolute;
    inset: 0;
    background:
      linear-gradient(180deg, rgba(0,0,0,0.08) 0%, rgba(0,0,0,0.12) 45%, #030507 100%),
      linear-gradient(90deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.08) 45%, rgba(0,0,0,0.62) 100%);
  }}
  .top-bar {{
    position: absolute;
    left: 42px;
    right: 42px;
    top: 28px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    z-index: 4;
  }}
  .brand {{
    font-size: 25px;
    font-weight: 900;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }}
  .brand span {{ color: #f5a623; }}
  .tag {{
    border: 1px solid rgba(0, 212, 255, 0.55);
    color: #00d4ff;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    background: rgba(0,0,0,0.42);
  }}
  .hero-copy {{
    position: absolute;
    left: 50px;
    bottom: 62px;
    z-index: 4;
    max-width: 790px;
  }}
  .eyebrow {{
    color: #00d4ff;
    font-size: 15px;
    font-weight: 900;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .name {{
    font-size: 88px;
    line-height: 0.86;
    font-weight: 950;
    text-transform: uppercase;
    letter-spacing: 0;
    text-shadow: 0 8px 34px rgba(0,0,0,0.75);
  }}
  .sub {{
    margin-top: 12px;
    color: rgba(255,255,255,0.78);
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }}
  .panel {{
    position: absolute;
    left: 44px;
    right: 44px;
    bottom: 42px;
    height: 580px;
    z-index: 5;
    background: rgba(4, 9, 13, 0.94);
    border: 1px solid rgba(0, 212, 255, 0.28);
    box-shadow: 0 0 42px rgba(0, 212, 255, 0.08);
    padding: 24px 32px 20px;
  }}
  .panel-head {{
    display: flex;
    justify-content: space-between;
    align-items: end;
    margin-bottom: 14px;
    padding-bottom: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.10);
  }}
  .title {{
    font-size: 40px;
    font-weight: 950;
    letter-spacing: 0;
    text-transform: uppercase;
  }}
  .meta {{
    color: rgba(255,255,255,0.52);
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-top: 5px;
  }}
  .payout {{
    text-align: right;
  }}
  .payout .value {{
    color: #00ff88;
    font-size: 54px;
    font-weight: 950;
    line-height: 0.9;
  }}
  .payout .label {{
    color: rgba(255,255,255,0.45);
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-top: 6px;
  }}
  .legs {{
    display: grid;
    gap: 9px;
  }}
  .leg-row {{
    height: 68px;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 10px 16px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(255,255,255,0.08);
  }}
  .leg-row.highlight {{
    border-color: rgba(0, 255, 136, 0.56);
    background: linear-gradient(90deg, rgba(0,255,136,0.14), rgba(255,255,255,0.045));
  }}
  .leg-index {{
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 212, 255, 0.16);
    color: #00d4ff;
    font-weight: 950;
    font-size: 17px;
  }}
  .leg-main {{
    flex: 1;
    min-width: 0;
  }}
  .leg-player {{
    font-size: 23px;
    font-weight: 950;
    line-height: 1.05;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .leg-pick {{
    margin-top: 4px;
    color: rgba(255,255,255,0.62);
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }}
  .leg-pick span {{ color: #00ff88; }}
  .tier {{
    width: 112px;
    padding: 9px 0;
    text-align: center;
    font-size: 13px;
    font-weight: 950;
    letter-spacing: 0.10em;
    border: 1px solid currentColor;
  }}
  .tier-goblin {{ color: #00ff88; background: rgba(0,255,136,0.09); }}
  .tier-standard {{ color: #00d4ff; background: rgba(0,212,255,0.09); }}
  .tier-demon {{ color: #ff4d5e; background: rgba(255,77,94,0.09); }}
  .stats {{
    position: absolute;
    left: 32px;
    right: 32px;
    bottom: 20px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
  }}
  .stat {{
    height: 66px;
    background: rgba(255,255,255,0.035);
    border: 1px solid rgba(255,255,255,0.07);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }}
  .stat .num {{
    color: #00d4ff;
    font-size: 24px;
    font-weight: 950;
  }}
  .stat .label {{
    margin-top: 3px;
    color: rgba(255,255,255,0.44);
    font-size: 11px;
    font-weight: 900;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="hero">
      <img src="{image_uri}" alt="{html.escape(highlight_player)}" />
      <div class="top-bar">
        <div class="brand">ATLAS <span>SPORTS AI</span></div>
        <div class="tag">Slip Of The Day</div>
      </div>
      <div class="hero-copy">
        <div class="eyebrow">{n_legs}-Leg Featured Slip</div>
        <div class="name">{html.escape(highlight_player)}</div>
        <div class="sub">Player Highlight · Spurs vs Wolves</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="title">Premium Card</div>
          <div class="meta">May 12, 2026 · Atlas live run 18:51</div>
        </div>
        <div class="payout">
          <div class="value">{payout}</div>
          <div class="label">Power Payout</div>
        </div>
      </div>
      <div class="legs">
        {leg_rows}
      </div>
      <div class="stats">
        <div class="stat"><div class="num">{hit_prob}</div><div class="label">Hit Prob</div></div>
        <div class="stat"><div class="num">{avg_p}</div><div class="label">Avg Leg P</div></div>
        <div class="stat"><div class="num">{ev}</div><div class="label">Atlas EV</div></div>
      </div>
    </div>
  </div>
</body>
</html>
"""

    output_html.write_text(html_text, encoding="utf-8")
    return output_html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slip", required=True, help="Path to recommended_Nleg.csv")
    parser.add_argument("--highlight-player", required=True, help="Player name to feature")
    parser.add_argument("--player-image", required=True, help="Path to player image")
    parser.add_argument(
        "--output-html",
        default=str(SCRIPT_DIR / "slip_of_day_20260512_4leg.html"),
        help="Output HTML path. PNG will use the same stem.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    slip_path = _repo_path(args.slip)
    player_image = _repo_path(args.player_image)
    output_html = _repo_path(args.output_html)

    if not slip_path.exists():
        raise FileNotFoundError(slip_path)
    if not player_image.exists():
        raise FileNotFoundError(player_image)

    build_html(
        slip_path=slip_path,
        player_image=player_image,
        highlight_player=args.highlight_player,
        output_html=output_html,
    )
    export(output_html, output_html.with_suffix(".png"))


if __name__ == "__main__":
    main()

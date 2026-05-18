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
from datetime import datetime
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

STAT_LABELS = {
    "PTS": "Points",
    "REB": "Rebounds",
    "AST": "Assists",
    "PRA": "Pts + Reb + Ast",
    "PR": "Points + Rebounds",
    "PA": "Points + Assists",
    "RA": "Rebounds + Assists",
    "FG3M": "3-Pointers",
    "3PM": "3-Pointers",
    "FTA": "Free Throws",
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


def _fmt_ev_pct(value: Any) -> str:
    try:
        v = float(value)
    except Exception:
        return "--"
    if v > 3:
        return f"{v:+.0f}%"
    return f"{(v - 1.0) * 100:+.0f}%"


def _pretty_run_meta(path: Path) -> str:
    run_id = next((part for part in path.parts if re.match(r"^20\d{6}_\d{6}", part)), "")
    if not run_id:
        return "Atlas live model"
    try:
        dt = datetime.strptime(run_id[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        return f"Atlas live run {run_id}"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year} - Atlas live run {dt.strftime('%H:%M')}"


def _stat_label(stat: str) -> str:
    stat = str(stat or "").upper()
    return STAT_LABELS.get(stat, stat)


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


def _mean(values: list[Any]) -> float | None:
    nums: list[float] = []
    for value in values:
        try:
            nums.append(float(value))
        except Exception:
            continue
    if not nums:
        return None
    return sum(nums) / len(nums)


def _load_marketed_slip(
    rows: list[dict[str, Any]],
    *,
    slip_label: str,
    path: Path,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    selected = [
        row
        for row in rows
        if str(row.get("slip", "")).strip().lower() == slip_label.strip().lower()
    ]
    if not selected:
        available = sorted({str(row.get("slip", "")).strip() for row in rows if row.get("slip")})
        raise ValueError(f"No marketed slip '{slip_label}' found in {path}. Available: {available}")

    first = selected[0]
    legs: list[dict[str, str]] = []
    for row in selected:
        legs.append(
            {
                "player": str(row.get("player", "")).strip(),
                "direction": str(row.get("direction", "")).strip(),
                "stat": str(row.get("stat", "")).strip(),
                "line": str(row.get("line", "")).strip(),
                "tier": str(row.get("tier", "")).strip(),
            }
        )

    summary = dict(first)
    summary["n_legs"] = len(legs)
    avg_p = _mean([row.get("p_cal") for row in selected])
    if avg_p is not None:
        summary["avg_p"] = avg_p
    if "ev_mult" not in summary and "ev" in summary:
        summary["ev_mult"] = summary["ev"]
    return summary, legs


def _load_slip(path: Path, *, slip_label: str = "3-leg") -> tuple[dict[str, Any], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"No slip rows found in {path}")

    if {"slip", "player", "stat", "direction", "line"}.issubset(rows[0].keys()):
        return _load_marketed_slip(rows, slip_label=slip_label, path=path)

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
        direction_raw = leg.get("direction", "").upper()
        direction = html.escape(direction_raw)
        direction_class = "dir-under" if direction_raw == "UNDER" else "dir-over"
        stat = html.escape(leg.get("stat", "").upper())
        line = html.escape(leg.get("line", ""))
        is_highlight = leg.get("player", "").strip().lower() == highlight_norm
        rows.append(
            f"""
            <div class="leg-row {'highlight' if is_highlight else ''}">
              <div class="leg-index">{idx}</div>
              <div class="leg-main">
                <div class="leg-player">{player}</div>
                <div class="leg-pick"><span class="{direction_class}">{direction}</span> {stat} {line} <em>{html.escape(_stat_label(stat))}</em></div>
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
    slip_label: str,
    hit_prob_display: str | None,
    ev_display: str | None,
    payout_display: str | None,
    actual_ev_display: str | None,
) -> Path:
    row, legs = _load_slip(slip_path, slip_label=slip_label)
    n_legs = int(float(row.get("n_legs") or len(legs)))
    image_uri = player_image.resolve().as_uri()
    leg_rows = _render_leg_rows(legs, highlight_player)
    hit_prob = hit_prob_display or _fmt_pct(row.get("hit_prob"))
    payout = payout_display or _fmt_mult(row.get("payout_mult"))
    ev = ev_display or _fmt_mult(row.get("ev_mult"))
    actual_ev = actual_ev_display or _fmt_ev_pct(row.get("ev_mult") or row.get("ev"))
    run_meta = _pretty_run_meta(slip_path)

    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080" />
<title>Atlas Slip of the Day</title>
<style>
  @import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Rajdhani:wght@500;600;700&display=swap");
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 1080px;
    height: 1080px;
    overflow: hidden;
    background: #020607;
    font-family: "Inter", system-ui, -apple-system, "Segoe UI", Arial, sans-serif;
    color: #fff;
  }}
  .card {{
    width: 1080px;
    height: 1080px;
    position: relative;
    overflow: hidden;
    background: #020607;
  }}
  .hero {{
    position: absolute;
    left: 0;
    top: 0;
    width: 1080px;
    height: 520px;
    overflow: hidden;
  }}
  .hero img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 30%;
    filter: saturate(1.1) contrast(1.12) brightness(0.92);
  }}
  .hero::after {{
    content: "";
    position: absolute;
    inset: 0;
    background:
      linear-gradient(180deg, rgba(0,0,0,0.08) 0%, rgba(0,0,0,0.18) 44%, #020607 100%),
      linear-gradient(90deg, rgba(0,0,0,0.70) 0%, rgba(0,0,0,0.12) 45%, rgba(0,0,0,0.58) 100%);
  }}
  .hero::before {{
    content: "";
    display: none;
  }}
  .top-bar {{
    position: absolute;
    left: 42px;
    right: 42px;
    top: 30px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    z-index: 4;
  }}
  .brand {{
    font-family: "Rajdhani", "Inter", sans-serif;
    font-size: 23px;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
  }}
  .brand span {{ color: #00d9ff; }}
  .tag {{
    border: 1px solid rgba(0, 217, 255, 0.58);
    border-radius: 999px;
    color: #00d9ff;
    padding: 11px 20px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    background: rgba(0, 17, 22, 0.58);
    box-shadow: 0 0 28px rgba(0, 217, 255, 0.14);
  }}
  .hero-copy {{
    position: absolute;
    left: 54px;
    bottom: 82px;
    z-index: 4;
    max-width: 790px;
  }}
  .eyebrow {{
    color: #00d9ff;
    font-size: 15px;
    font-weight: 900;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .name {{
    position: relative;
    display: inline-block;
    font-family: "Rajdhani", "Inter", sans-serif;
    font-size: 78px;
    line-height: 0.9;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    color: #d7e1e6;
    background: linear-gradient(180deg, #ffffff 0%, #d8e2e7 24%, #68777e 58%, #f5fbff 76%, #a7b5bc 100%);
    -webkit-background-clip: text;
    color: transparent;
    text-shadow: 0 0 24px rgba(0, 217, 255, 0.12);
  }}
  .name::after {{
    content: none;
  }}
  .sub {{
    position: relative;
    margin-top: 9px;
    padding-top: 11px;
    color: rgba(222,234,240,0.72);
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }}
  .sub::before {{
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    width: 920px;
    height: 2px;
    background:
      radial-gradient(circle at 34% 50%, rgba(255,247,214,.95) 0 2px, transparent 6px),
      linear-gradient(90deg, rgba(255,176,46,0.98), rgba(255,176,46,0.64) 28%, rgba(0,213,255,0.55) 62%, transparent 100%);
    box-shadow: 0 0 18px rgba(255,176,46,0.38), 0 0 36px rgba(255,176,46,0.10);
  }}
  .panel {{
    position: absolute;
    left: 44px;
    right: 44px;
    bottom: 38px;
    height: 590px;
    z-index: 5;
    background: linear-gradient(180deg, rgba(8, 31, 37, 0.985), rgba(5, 20, 25, 0.985));
    border: 1px solid rgba(0, 217, 255, 0.34);
    border-radius: 18px;
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.36), inset 0 1px 0 rgba(255,255,255,0.06);
    padding: 26px 32px 22px;
  }}
  .panel::before {{
    content: none;
  }}
  .panel-head {{
    display: flex;
    justify-content: space-between;
    align-items: end;
    margin-bottom: 16px;
    padding-bottom: 15px;
    border-bottom: 1px solid rgba(0,217,255,0.18);
  }}
  .title {{
    font-family: "Rajdhani", "Inter", sans-serif;
    font-size: 39px;
    font-weight: 700;
    letter-spacing: 0.01em;
    text-transform: uppercase;
    color: #d9e4e9;
    background: linear-gradient(180deg, #ffffff 0%, #c9d5dc 30%, #7a8991 60%, #f4fbff 78%, #a4b2ba 100%);
    -webkit-background-clip: text;
    color: transparent;
  }}
  .meta {{
    color: rgba(215,229,236,0.55);
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
    color: #27f45f;
    font-family: "Rajdhani", "Inter", sans-serif;
    font-size: 43px;
    font-weight: 700;
    line-height: 0.9;
    background-image:
      radial-gradient(ellipse at 18% 28%, rgba(244,255,246,.9) 0%, rgba(244,255,246,.22) 7%, transparent 18%),
      radial-gradient(ellipse at 72% 66%, rgba(123,255,159,.54) 0%, transparent 20%),
      linear-gradient(123deg, #bbffd0 0%, #f0fff4 13%, #2dff68 28%, #0aa33c 43%, #d7ffe2 56%, #17df52 70%, #056d25 84%, #8dffab 100%);
    background-size: 135% 135%, 135% 135%, 210% 100%;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    filter: drop-shadow(0 0 10px rgba(31,255,92,.18)) drop-shadow(0 0 22px rgba(31,255,92,.08));
  }}
  .payout .label {{
    color: rgba(215,229,236,0.45);
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-top: 6px;
  }}
  .legs {{
    display: grid;
    gap: 10px;
  }}
  .leg-row {{
    height: 72px;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 10px 16px;
    background: rgba(2, 17, 20, 0.78);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
  }}
  .leg-row.highlight {{
    border-color: rgba(0, 255, 136, 0.56);
    background: linear-gradient(90deg, rgba(0,255,136,0.13), rgba(0,217,255,0.05));
  }}
  .leg-index {{
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    background: rgba(0, 217, 255, 0.16);
    color: #00d9ff;
    font-weight: 950;
    font-size: 17px;
  }}
  .leg-main {{
    flex: 1;
    min-width: 0;
  }}
  .leg-player {{
    font-family: "Rajdhani", "Inter", sans-serif;
    font-size: 24px;
    font-weight: 700;
    line-height: 1.05;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .leg-pick {{
    margin-top: 4px;
    color: rgba(215,229,236,0.64);
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }}
  .leg-pick .dir-over {{ color: #00ff88; }}
  .leg-pick .dir-under {{ color: #ff4d5e; }}
  .leg-pick em {{
    margin-left: 10px;
    color: rgba(215,229,236,0.40);
    font-style: normal;
    letter-spacing: 0.08em;
  }}
  .tier {{
    width: 112px;
    padding: 9px 0;
    text-align: center;
    font-size: 13px;
    font-weight: 950;
    letter-spacing: 0.10em;
    border: 1px solid currentColor;
    border-radius: 999px;
  }}
  .tier-goblin {{ color: #00ff88; background: rgba(0,255,136,0.09); }}
  .tier-standard {{ color: #00d4ff; background: rgba(0,212,255,0.09); }}
  .tier-demon {{ color: #ff4d5e; background: rgba(255,77,94,0.09); }}
  .stats {{
    position: absolute;
    left: 32px;
    right: 32px;
    bottom: 22px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
  }}
  .stat {{
    height: 70px;
    background: rgba(255,255,255,0.035);
    border: 1px solid rgba(0,217,255,0.10);
    border-radius: 14px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }}
  .stat .num {{
    color: #00d9ff;
    font-family: "Rajdhani", "Inter", sans-serif;
    font-size: 24px;
    font-weight: 700;
  }}
  .stat .label {{
    margin-top: 3px;
    color: rgba(215,229,236,0.44);
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
        <div class="sub">Player Highlight - Atlas Daily Edge</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="title">Premium Card</div>
          <div class="meta">{html.escape(run_meta)}</div>
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
        <div class="stat"><div class="num">{ev}</div><div class="label">Atlas Value</div></div>
        <div class="stat"><div class="num">{actual_ev}</div><div class="label">EV</div></div>
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
    parser.add_argument("--slip", required=True, help="Path to recommended_Nleg.csv or marketed_slips.csv")
    parser.add_argument(
        "--slip-label",
        default="3-leg",
        help="Slip label to render when --slip points at marketed_slips.csv",
    )
    parser.add_argument("--highlight-player", required=True, help="Player name to feature")
    parser.add_argument("--player-image", required=True, help="Path to player image")
    parser.add_argument("--hit-prob-display", help="Optional exact hit probability text to render")
    parser.add_argument("--ev-display", help="Optional exact EV text to render")
    parser.add_argument("--payout-display", help="Optional exact payout text to render")
    parser.add_argument("--actual-ev-display", help="Optional exact public EV text to render")
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
        slip_label=args.slip_label,
        hit_prob_display=args.hit_prob_display,
        ev_display=args.ev_display,
        payout_display=args.payout_display,
        actual_ev_display=args.actual_ev_display,
    )
    export(output_html, output_html.with_suffix(".png"))


if __name__ == "__main__":
    main()

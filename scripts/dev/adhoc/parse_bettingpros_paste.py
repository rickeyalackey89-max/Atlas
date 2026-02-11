#!/usr/bin/env python
"""
Parse raw BettingPros cheat sheet paste text into a structured CSV
Usage:
  python tools/parse_bettingpros_paste.py

Input:
  data/input/bettingpros_paste.txt

Output:
  data/input/bettingpros_signals_today.csv
"""

from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import re
import pandas as pd
from datetime import datetime
PROJECT_ROOT = find_repo_root(Path(__file__))
IN_PATH = PROJECT_ROOT / "data" / "input" / "bettingpros_paste.txt"
OUT_PATH = PROJECT_ROOT / "data" / "input" / "bettingpros_signals_today.csv"

def parse_chunk(chunk):
    out = {}
    if len(chunk) >= 2:
        out["player"] = chunk[1]

    matchup = next((ln for ln in chunk if ln.startswith("- ")), None)
    if matchup:
        out["matchup"] = matchup[2:].strip()

    line_val = None
    line_idx = None
    for i, ln in enumerate(chunk):
        if re.fullmatch(r"\d+(\.\d+)?", ln):
            line_val = float(ln)
            line_idx = i
            break
    if line_val is None:
        return None

    out["line"] = line_val
    if line_idx + 1 < len(chunk):
        out["prop"] = chunk[line_idx + 1]

    for j in range(line_idx + 2, min(line_idx + 6, len(chunk))):
        if re.fullmatch(r"\d+(\.\d+)?", chunk[j]):
            out["proj"] = float(chunk[j])
            if j + 1 < len(chunk) and chunk[j + 1] in {"Over", "Under"}:
                out["bp_side_word"] = chunk[j + 1]
            if j + 2 < len(chunk) and re.fullmatch(r"[+\-]\d+(\.\d+)?", chunk[j + 2]):
                out["proj_diff"] = float(chunk[j + 2])
            break

    stars_ln = next((ln for ln in chunk if "out of 5 stars" in ln), None)
    if stars_ln:
        m = re.search(r"(\d)\s+out of 5 stars", stars_ln)
        out["stars"] = int(m.group(1)) if m else None

    ev_ln = next((ln for ln in chunk if re.fullmatch(r"[+\-]?\d+%+", ln)), None)
    if ev_ln:
        out["ev_pct"] = float(ev_ln.replace("%", ""))

    opp_ln = next((ln for ln in chunk if re.fullmatch(r"\d+(st|nd|rd|th)", ln)), None)
    if opp_ln:
        out["opp_rank_vs_prop"] = opp_ln

    hr_ln = next((ln for ln in chunk if "%" in ln and ("\t" in ln or re.search(r"\d+%\s+\d+%", ln))), None)
    if hr_ln:
        parts = re.split(r"[\t\s]+", hr_ln)
        pct = [p for p in parts if p.endswith("%")]
        if len(pct) >= 3:
            out["hit_L5"] = float(pct[0].replace("%", ""))
            out["hit_L15"] = float(pct[1].replace("%", ""))
            out["hit_season"] = float(pct[2].replace("%", ""))
            if len(pct) >= 4:
                out["hit_h2h"] = float(pct[3].replace("%", ""))

    pick_ln = next((ln for ln in chunk if re.fullmatch(r"[UO]\s+\d+(\.\d+)?", ln)), None)
    if not pick_ln:
        return None

    s, num = pick_ln.split()
    out["pick"] = "UNDER" if s == "U" else "OVER"
    out["pick_line"] = float(num)

    return out

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Missing input file: {IN_PATH}")

    text = IN_PATH.read_text(errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    start_idxs = [i for i, ln in enumerate(lines) if ln.startswith("Headshot of ")]
    rows = []

    for idx, start in enumerate(start_idxs):
        end = start_idxs[idx + 1] if idx + 1 < len(start_idxs) else len(lines)
        chunk = lines[start:end]
        d = parse_chunk(chunk)
        if d:
            rows.append(d)

    if not rows:
        raise RuntimeError("No rows parsed from BettingPros paste.")

    df = pd.DataFrame(rows)

    prop_map = {
        # singles
        "Pts": "PTS",
        "Reb": "REB",
        "Ast": "AST",
        "Stl": "STL",
        "Blk": "BLK",

        # common combo markets (map to PrizePicks stat codes used in today.csv)
        "Pts + Ast": "PA",
        "Pts + Reb": "PR",
        "Reb + Ast": "RA",
        "Pts + Reb + Ast": "PRA",
    }

    # Keep the raw BettingPros market key for debugging
    df["market_bp"] = df["prop"].map({
        "Pts + Ast": "PTS+AST",
        "Pts + Reb": "PTS+REB",
        "Reb + Ast": "REB+AST",
        "Pts + Reb + Ast": "PRA",
    }).fillna(df["prop"].str.replace(" ", ""))

    # Primary join key used by Atlas / PrizePicks board
    df["market_key"] = df["prop"].map(prop_map).fillna(df["prop"].str.replace(" ", ""))
    df["source"] = "BettingPros"
    df["source_date"] = datetime.now().strftime("%Y-%m-%d")

    df["signal_stars"] = df["stars"] / 5.0
    df["signal_ev"] = (df["ev_pct"].abs() / 50.0).clip(0, 1)
    df["signal_strength"] = (0.7 * df["signal_stars"] + 0.3 * df["signal_ev"]).clip(0, 1)

    out_cols = [
        "source","source_date","player","matchup","market_key","prop","pick","line",
        "proj","proj_diff","stars","ev_pct","hit_L5","hit_L15","hit_season","hit_h2h",
        "signal_strength"
    ]

    df[out_cols].to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH} (rows={len(df)})")

if __name__ == "__main__":
    main()

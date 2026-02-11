from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import Dict, List, Optional, Tuple

import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
RUNS_DIR = PROJECT_ROOT / "data" / "output" / "runs"

# -----------------------------
# Parsing helpers
# -----------------------------

_STAT_MAP = {
    # common long -> short
    "points": "PTS",
    "rebounds": "REB",
    "assists": "AST",
    "threes made": "FG3M",
    "3pt made": "FG3M",
    "3pm": "FG3M",
    "fg3m": "FG3M",
    # combos (accept multiple styles)
    "pts+rebs": "PR",
    "points+rebounds": "PR",
    "pts+asts": "PA",
    "points+assists": "PA",
    "rebs+asts": "RA",
    "rebounds+assists": "RA",
    "pts+rebs+asts": "PRA",
    "points+rebounds+assists": "PRA",
    "blks+stls": "BS",
    "blocks+steals": "BS",
    # abbreviations
    "pas": "PA",
    "pras": "PRA",
    "prs": "PR",
    "ras": "RA",
}

# Accept already-normalized short stats too
_SHORT_STATS = {"PTS","REB","AST","FG3M","PR","PA","RA","PRA","BS"}

LINE_RE = re.compile(
    r"""^\s*
        (?P<player>.+?)\s+
        (?P<dir>OVER|UNDER|MORE|LESS)\s+
        (?P<stat>[A-Za-z0-9\+\&\s]+?)\s+
        (?P<line>-?\d+(?:\.\d+)?)\s*
        $""",
    re.IGNORECASE | re.VERBOSE,
)

def _norm_dir(s: str) -> str:
    t = (s or "").strip().upper()
    if t in {"OVER", "MORE"}:
        return "OVER"
    if t in {"UNDER", "LESS"}:
        return "UNDER"
    return t

def _norm_stat(s: str) -> str:
    t = (s or "").strip().lower()
    t = t.replace("&", "+")
    t = re.sub(r"\s+", " ", t).strip()
    if t.upper() in _SHORT_STATS:
        return t.upper()
    # collapse spaces around +
    t2 = re.sub(r"\s*\+\s*", "+", t)
    if t2 in _STAT_MAP:
        return _STAT_MAP[t2]
    if t in _STAT_MAP:
        return _STAT_MAP[t]
    # last resort: try uppercase condensed
    u = t2.upper()
    return u

@dataclass
class PickRow:
    player: str
    direction: str
    stat: str
    line: Optional[float]  # optional; if omitted we'll best-match on player+stat+direction


def _read_picks(path: Path) -> List[PickRow]:
    """
    Supports:
      - CSV with headers including: player, stat, direction (or over_under), line (optional)
      - TXT (simple): one pick per line like: "Jamal Murray OVER PRA 29.5"
      - GameScript AI export TXT: blocks like:
            87
            Derrick Jones Jr.
            6+ Points
            LAC @ SAC • 9:00 PM
      - GameScript Capper export TXT: lines like:
            Payton Pritchard Over 26.5 PRAs
            Victor Wembanyama 10+ Rebounds
    """
    if not path.exists():
        raise FileNotFoundError(str(path))

    picks: List[PickRow] = []

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                player = (r.get("player") or r.get("Player") or "").strip()
                if not player:
                    continue
                direction = _norm_dir(r.get("direction") or r.get("over_under") or r.get("side") or "")
                stat = _norm_stat(r.get("stat") or r.get("Stat") or "")
                line_raw = r.get("line") or r.get("Line") or ""
                line = None
                try:
                    if str(line_raw).strip() != "":
                        line = float(line_raw)
                except Exception:
                    line = None
                picks.append(PickRow(player=player, direction=direction, stat=stat, line=line))
        return picks

    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()]

    # ------------------------------------------------------------
    # 1) Try GameScript AI block format (confidence line -> player -> prop)
    # ------------------------------------------------------------
    def _parse_alt_prop(prop: str) -> Optional[PickRow]:
        # Examples: "6+ Points", "13+ PAs", "10+ Rebounds"
        m = re.match(r"^(?P<line>\d+(?:\.\d+)?)\+\s+(?P<stat>.+?)\s*$", prop.strip(), flags=re.I)
        if not m:
            return None
        try:
            line = float(m.group("line"))
        except Exception:
            line = None
        stat = _norm_stat(m.group("stat"))
        return PickRow(player="", direction="OVER", stat=stat, line=line)

    ai_block_picks: List[PickRow] = []
    i = 0
    while i < len(lines):
        s = lines[i]
        if s.isdigit():
            v = int(s)
            # confidence scores are typically 0-100; ignore other numeric lines
            if 0 <= v <= 100 and i + 2 < len(lines):
                player = lines[i + 1].strip()
                prop = lines[i + 2].strip()
                pr = _parse_alt_prop(prop)
                if player and pr:
                    pr = PickRow(player=player, direction=pr.direction, stat=pr.stat, line=pr.line)
                    ai_block_picks.append(pr)
                    i += 3
                    continue
        i += 1

    # If we got a meaningful number of picks, accept this parse.
    if len(ai_block_picks) >= 3:
        return ai_block_picks

    # ------------------------------------------------------------
    # 2) Capper-style / mixed line scanning
    # ------------------------------------------------------------
    OVERUNDER_RE = re.compile(
        r"^(?P<player>.+?)\s+(?P<dir>Over|Under)\s+(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>[A-Za-z\+\s]+?)\s*$",
        flags=re.I,
    )
    ALT_RE = re.compile(r"^(?P<player>.+?)\s+(?P<line>\d+(?:\.\d+)?)\+\s+(?P<stat>.+?)\s*$", flags=re.I)

    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        # skip obvious non-pick lines
        if "@" in s or "•" in s:
            continue
        if s.lower().startswith(("nba", "game", "prop", "today", "updated", "exclusive", "early access", "potd", "content", "capper picks")):
            continue
        if re.match(r"^[\+\-]\d+", s):  # odds lines like -110
            continue
        if s.isdigit():
            continue

        m = OVERUNDER_RE.match(s)
        if m:
            player = m.group("player").strip()
            direction = _norm_dir(m.group("dir"))
            stat = _norm_stat(m.group("stat"))
            try:
                line = float(m.group("line"))
            except Exception:
                line = None
            if player and stat:
                picks.append(PickRow(player=player, direction=direction, stat=stat, line=line))
            continue

        # alt-lines like "Victor Wembanyama 10+ Rebounds" -> treat as OVER 10
        m2 = ALT_RE.match(s)
        if m2:
            player = m2.group("player").strip()
            stat = _norm_stat(m2.group("stat"))
            try:
                line = float(m2.group("line"))
            except Exception:
                line = None
            if player and stat:
                picks.append(PickRow(player=player, direction="OVER", stat=stat, line=line))
            continue

        # simple one-line format
        m3 = LINE_RE.match(s)
        if m3:
            player = m3.group("player").strip()
            direction = _norm_dir(m3.group("dir"))
            stat = _norm_stat(m3.group("stat"))
            try:
                line = float(m3.group("line"))
            except Exception:
                line = None
            picks.append(PickRow(player=player, direction=direction, stat=stat, line=line))

    return picks


    # treat as plain text
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = LINE_RE.match(s)
        if not m:
            continue
        player = m.group("player").strip()
        direction = _norm_dir(m.group("dir"))
        stat = _norm_stat(m.group("stat"))
        try:
            line = float(m.group("line"))
        except Exception:
            line = None
        picks.append(PickRow(player=player, direction=direction, stat=stat, line=line))
    return picks

# -----------------------------
# Matching + slip building
# -----------------------------

POWER_MULT = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}

def _latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not runs:
        raise FileNotFoundError(f"No run dirs under {RUNS_DIR}")
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]

def _load_scored(run_dir: Path) -> pd.DataFrame:
    # Prefer deduped; fall back to scored_legs
    p = run_dir / "scored_legs_deduped.csv"
    if not p.exists():
        p = run_dir / "scored_legs.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing scored legs in {run_dir}")
    df = pd.read_csv(p)
    return df

def _best_match(df: pd.DataFrame, pick: PickRow) -> Optional[pd.Series]:
    # strict match on player/stat/direction; optional line closest if multiple
    sub = df[
        (df["player"].astype(str) == pick.player) &
        (df["stat"].astype(str) == pick.stat) &
        (df["direction"].astype(str).str.upper() == pick.direction)
    ].copy()

    if sub.empty:
        return None

    # prefer main_line if present
    if "main_line" in sub.columns:
        sub = sub.sort_values(["main_line"], ascending=[False], na_position="last")

    if pick.line is not None and "line" in sub.columns:
        sub["line"] = pd.to_numeric(sub["line"], errors="coerce")
        sub = sub.dropna(subset=["line"])
        if not sub.empty:
            sub["_dist"] = (sub["line"] - float(pick.line)).abs()
            sub = sub.sort_values(["_dist"], ascending=[True])
            return sub.iloc[0]
    return sub.iloc[0]

def _format_leg(r: pd.Series) -> str:
    player = str(r.get("player","")).strip()
    direction = str(r.get("direction","")).strip().upper()
    stat = str(r.get("stat","")).strip()
    line = r.get("line")
    try:
        line_f = float(line)
        line_s = str(int(line_f)) if abs(line_f - int(line_f)) < 1e-9 else str(line_f)
    except Exception:
        line_s = str(line)
    tier = str(r.get("tier","")).strip().upper()
    pid = r.get("projection_id")
    pid_s = "" if pd.isna(pid) else str(int(pid)) if str(pid).isdigit() else str(pid)
    tier_part = f" ({tier})" if tier and tier.lower() != "nan" else ""
    id_part = f" [id:{pid_s}]" if pid_s else ""
    return f"{player} {direction} {stat} {line_s}{tier_part}{id_part}"

def _build_best_slips(df_pool: pd.DataFrame, n_legs: int, top_n: int, max_pool: int) -> pd.DataFrame:
    """
    Build best slips from pool:
      - enforce unique player per slip
      - rank by ev_mult then hit_prob
    """
    if df_pool.empty:
        return pd.DataFrame(columns=["n_legs","legs","hit_prob","ev_mult","avg_p","avg_fragility","slip_key"])

    df = df_pool.copy()
    # use p_adj if present else p
    if "p_adj" in df.columns:
        df["_p_use"] = pd.to_numeric(df["p_adj"], errors="coerce")
    else:
        df["_p_use"] = pd.to_numeric(df.get("p", pd.Series([pd.NA]*len(df))), errors="coerce")

    df["_p_use"] = df["_p_use"].fillna(0.0)

    df["_frag_use"] = pd.to_numeric(df.get("fragility_abs", df.get("fragility", 0.0)), errors="coerce").fillna(0.0)

    df = df.sort_values(["_p_use"], ascending=[False]).head(max_pool).reset_index(drop=True)

    import itertools
    rows = []
    mult = POWER_MULT.get(n_legs, 1.0)

    idxs = list(range(len(df)))
    for comb in itertools.combinations(idxs, n_legs):
        sub = df.loc[list(comb)]
        players = list(sub["player"].astype(str))
        if len(players) != len(set(players)):
            continue
        phit = float(sub["_p_use"].prod())
        ev_mult = mult * phit
        legs_list = [ _format_leg(sub.iloc[i]) for i in range(len(sub)) ]
        legs_str = " | ".join(legs_list)
        rows.append({
            "n_legs": n_legs,
            "legs": legs_str,
            "hit_prob": phit,
            "ev_mult": ev_mult,
            "avg_p": float(sub["_p_use"].mean()),
            "avg_fragility": float(sub["_frag_use"].mean()),
            "slip_key": legs_str,
        })

    if not rows:
        return pd.DataFrame(columns=["n_legs","legs","hit_prob","ev_mult","avg_p","avg_fragility","slip_key"])

    out = pd.DataFrame(rows)
    out = out.sort_values(["ev_mult","hit_prob"], ascending=[False, False]).head(top_n).reset_index(drop=True)

    # expand leg_i columns
    for i in range(1, n_legs+1):
        out[f"leg_{i}"] = out["legs"].apply(lambda s: s.split(" | ")[i-1] if isinstance(s,str) and " | " in s else (s if i==1 else pd.NA))
    # add compatibility cols
    for c in ["slip_agreement_score","slip_agreement_tier","slip_tag_set","slip_tag","slip_min_start_utc","slip_has_unknown_start"]:
        out[c] = pd.NA

    # final column order
    cols = ["n_legs","legs","hit_prob","ev_mult","avg_p","avg_fragility","slip_key",
            "slip_agreement_score","slip_agreement_tier","slip_tag_set","slip_tag",
            "slip_min_start_utc","slip_has_unknown_start"]
    cols += [f"leg_{i}" for i in range(1, n_legs+1)]
    return out[cols]

def main() -> int:
    ap = argparse.ArgumentParser(description="Build AI/Capper slips from a pick list using latest scored legs.")
    ap.add_argument("--product", required=True, choices=["AI","Capper"], help="Which product to write.")
    ap.add_argument("--input", required=True, help="Path to picks file (.txt or .csv).")
    ap.add_argument("--run-dir", default="", help="Optional explicit run dir; defaults to newest run.")
    ap.add_argument("--legs", default="4,5", help="Leg sizes to build, e.g. '4,5' or '3,4,5'")
    ap.add_argument("--top-n", type=int, default=25, help="Top slips to keep per leg size.")
    ap.add_argument("--max-pool", type=int, default=30, help="Max matched legs to consider (controls combinatorics).")
    args = ap.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    picks_path = Path(args.input)

    picks = _read_picks(picks_path)
    if not picks:
        print(f"[BUILD] No picks parsed from {picks_path}")
        return 0

    scored = _load_scored(run_dir)

    matched = []
    for pk in picks:
        m = _best_match(scored, pk)
        if m is None:
            continue
        matched.append(m)

    if not matched:
        print("[BUILD] 0 picks matched against scored legs. Check player/stat/direction names.")
        return 0

    pool = pd.DataFrame(matched).drop_duplicates(subset=["projection_id"], keep="first")

    out_dir = run_dir / args.product
    out_dir.mkdir(parents=True, exist_ok=True)

    leg_sizes = []
    for part in str(args.legs).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            leg_sizes.append(int(part))
        except Exception:
            pass
    if not leg_sizes:
        leg_sizes = [4,5]

    for n in leg_sizes:
        out = _build_best_slips(pool, n_legs=n, top_n=args.top_n, max_pool=args.max_pool)
        out_path = out_dir / f"recommended_{n}leg.csv"
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"[BUILD] wrote: {out_path} (rows={len(out)})")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())


from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
DEFAULT_IN_JSON = PROJECT_ROOT / "data" / "input" / "rotowire_lines.json"
OUT_CSV = PROJECT_ROOT / "data" / "input" / "external_priors_today.csv"


# Map RotoWire market names -> Atlas stat codes
MARKET_TO_STAT = {
    "Points": "PTS",
    "Rebounds": "REB",
    "Assists": "AST",
    "3PT Made": "FG3M",
    "PTS+REB": "PR",
    "PTS+AST": "PA",
    "REB+AST": "RA",
    "PTS+REB+AST": "PRA",
}


def _now_ts_local() -> str:
    # matches your existing manual schema style
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: Path) -> Dict[str, Any]:
    txt = path.read_text(encoding="utf-8", errors="ignore").strip()
    # Some "Copy Response" dumps may include leading junk; find first "{"
    i = txt.find("{")
    if i > 0:
        txt = txt[i:]
    return json.loads(txt)


def _index_markets(j: Dict[str, Any]) -> Dict[int, Tuple[str, str]]:
    """
    returns marketID -> (sport, marketName)
    """
    out: Dict[int, Tuple[str, str]] = {}
    for m in j.get("markets", []) or []:
        try:
            mid = int(m.get("marketID"))
        except Exception:
            continue
        sport = str(m.get("sport", "")).strip()
        name = str(m.get("marketName", "")).strip()
        out[mid] = (sport, name)
    return out


def _index_entities(j: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """
    entityID -> entity dict (includes name, sport, team, etc.)
    """
    out: Dict[int, Dict[str, Any]] = {}
    for e in j.get("entities", []) or []:
        try:
            eid = int(e.get("entityID"))
        except Exception:
            continue
        out[eid] = e
    return out


def _has_prizepicks_line(prop: Dict[str, Any]) -> bool:
    for ln in prop.get("lines", []) or []:
        if str(ln.get("book", "")).lower() == "prizepicks":
            return True
    return False


def extract_rotowire_priors(in_json: Path) -> pd.DataFrame:
    j = _read_json(in_json)

    markets = _index_markets(j)
    entities = _index_entities(j)

    rows: List[Dict[str, Any]] = []
    for prop in j.get("props", []) or []:
        try:
            mid = int(prop.get("marketID"))
        except Exception:
            continue

        sport, market_name = markets.get(mid, ("", ""))
        if sport != "NBA":
            continue

        stat = MARKET_TO_STAT.get(market_name)
        if not stat:
            continue

        # Only keep props that actually have a PrizePicks book line in RW
        # (helps ensure we're aligned to PP player naming + slate)
        if not _has_prizepicks_line(prop):
            continue

        mu = prop.get("projection", None)
        try:
            mu = float(mu)
        except Exception:
            continue

        ent_ids = prop.get("entities", []) or []
        if not ent_ids:
            continue

        # For NBA player props this should be a single entity
        eid = ent_ids[0]
        try:
            eid = int(eid)
        except Exception:
            continue

        ent = entities.get(eid, {})
        if str(ent.get("sport", "")).strip() != "NBA":
            continue

        player = str(ent.get("name", "")).strip()
        if not player:
            continue

        rows.append(
            {
                "source": "rotowire",
                "asof_ts": _now_ts_local(),
                "league": "NBA",
                "player": player,
                "stat": stat,
                "projection": mu,
                # keep optional columns for future (can be ignored by external_priors.py)
                "confidence": 1.0,
                "notes": "",
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # If multiple RW props map to same player+stat, keep the latest mean (shouldn't happen often)
    df = (
        df.groupby(["source", "league", "player", "stat"], as_index=False)
        .agg({"asof_ts": "max", "projection": "mean", "confidence": "max", "notes": "first"})
    )
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-json", default=str(DEFAULT_IN_JSON), help="Path to Rotowire lines.php JSON (Copy Response).")
    ap.add_argument("--out-csv", default=str(OUT_CSV), help="Output priors CSV path.")
    args = ap.parse_args()

    in_json = Path(args.in_json)
    out_csv = Path(args.out_csv)

    if not in_json.exists():
        raise SystemExit(f"[ERROR] input JSON not found: {in_json}")

    df = extract_rotowire_priors(in_json)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    print(f"[OK] wrote {out_csv} (rows={len(df)})")
    if len(df):
        print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()

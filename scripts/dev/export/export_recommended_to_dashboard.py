from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()

from zoneinfo import ZoneInfo

ROOT = find_repo_root(Path(__file__))
OUT_DIR = ROOT / "data" / "output" / "dashboard"

LATEST_ALL_DIR = ROOT / "data" / "output" / "latest" / "all"
WINDFALL_DIR = LATEST_ALL_DIR / "Windfall"

RECOMMENDED_CSV = WINDFALL_DIR / "recommended_5leg.csv"
OUT_JSON = OUT_DIR / "recommended_latest.json"

AUDIT_LAST5 = ROOT / "data" / "gamelogs" / "audit_last5_board.csv"

_ID_RE = re.compile(r"\[id:(\d+)\]")
_DIR_RE = re.compile(r"\b(OVER|UNDER|MORE|LESS|O|U)\b", re.I)
_LINE_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


# -----------------------
# helpers
# -----------------------

def _now_ct() -> str:
    return datetime.now(tz=ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M:%S %Z")


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _parse_series(s: str) -> list[float]:
    if not s or not isinstance(s, str):
        return []
    out = []
    for x in s.split("|"):
        try:
            out.append(float(x.strip()))
        except Exception:
            pass
    return out[:5]


def _load_audit_by_player() -> dict[str, dict]:
    """
    Keyed by normalized resolved_player (fallback board_player).
    """
    m: dict[str, dict] = {}
    if not AUDIT_LAST5.exists():
        return m

    with AUDIT_LAST5.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = r.get("resolved_player") or r.get("board_player")
            if not name:
                continue

            key = _norm_name(name)
            m[key] = {
                "player": name,
                "pts": _parse_series(r.get("last5_pts")),
                "reb": _parse_series(r.get("last5_reb")),
                "ast": _parse_series(r.get("last5_ast")),
                "fg3m": _parse_series(r.get("last5_fg3m")),
            }
    return m


def _extract_id(s: str) -> int | None:
    if not s:
        return None
    m = _ID_RE.search(s)
    return int(m.group(1)) if m else None


def _parse_leg_text(s: str) -> tuple[str, str, str, float] | None:
    """
    Returns (player, stat, dir, line)
    """
    if not s:
        return None

    dir_m = _DIR_RE.search(s)
    line_m = _LINE_RE.search(s)

    if not dir_m or not line_m:
        return None

    dir_raw = dir_m.group(1).upper()
    direction = "OVER" if dir_raw in ("OVER", "MORE", "O") else "UNDER"
    line = float(line_m.group(1))

    stat_tokens = [
        "PTS", "REB", "AST", "FG3M",
        "RA", "PA", "PR", "PRA"
    ]

    stat = None
    for t in stat_tokens:
        if re.search(rf"\b{t}\b", s, re.I):
            stat = t
            break
    if not stat:
        return None

    player = s[:dir_m.start()].strip()
    player = re.sub(r"[-–—]+$", "", player).strip()

    return player, stat, direction, line


def _count_hits(series: list[float], direction: str, line: float) -> int | None:
    if not series:
        return None
    hits = 0
    for v in series:
        if direction == "OVER" and v > line:
            hits += 1
        elif direction == "UNDER" and v < line:
            hits += 1
    return hits


def _build_series(stat: str, audit_row: dict) -> list[float]:
    if stat == "PTS":
        return audit_row["pts"]
    if stat == "REB":
        return audit_row["reb"]
    if stat == "AST":
        return audit_row["ast"]
    if stat == "FG3M":
        return audit_row["fg3m"]

    # combos
    if stat == "RA":
        return [r + a for r, a in zip(audit_row["reb"], audit_row["ast"])]
    if stat == "PA":
        return [p + a for p, a in zip(audit_row["pts"], audit_row["ast"])]
    if stat == "PR":
        return [p + r for p, r in zip(audit_row["pts"], audit_row["reb"])]
    if stat == "PRA":
        return [p + r + a for p, r, a in zip(
            audit_row["pts"], audit_row["reb"], audit_row["ast"]
        )]

    return []


def _build_legs_detail(row: dict, audit_by_player: dict[str, dict]) -> list[dict]:
    out = []

    legs = []
    for k in ("leg_1", "leg_2", "leg_3", "leg_4", "leg_5"):
        if row.get(k):
            legs.append(row[k])

    if not legs and row.get("legs"):
        legs = [p.strip() for p in row["legs"].split("|") if p.strip()]

    for leg in legs:
        parsed = _parse_leg_text(leg)
        if not parsed:
            continue

        player, stat, direction, line = parsed
        audit = audit_by_player.get(_norm_name(player))

        last5_hits = None
        if audit:
            series = _build_series(stat, audit)
            last5_hits = _count_hits(series, direction, line)

        out.append({
            "id": _extract_id(leg),
            "player": player,
            "stat": stat,
            "direction": direction,
            "line": line,
            "last5_hits": last5_hits,
            "leg_text": leg,
        })

    return out


def export_recommended_to_dashboard() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": _now_ct(),
        "source_csv": str(RECOMMENDED_CSV),
        "row_count": 0,
        "data": [],
        "notes": "Windfall-only export. last5 computed from audit_last5_board.csv (player-keyed).",
    }

    if not RECOMMENDED_CSV.exists():
        OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {OUT_JSON} (missing source)")
        return

    audit_by_player = _load_audit_by_player()

    with RECOMMENDED_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        r["legs_detail"] = _build_legs_detail(r, audit_by_player)
        payload["data"].append(r)

    payload["row_count"] = len(rows)

    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT_JSON} from {RECOMMENDED_CSV} ({len(rows)} rows)")


if __name__ == "__main__":
    export_recommended_to_dashboard()
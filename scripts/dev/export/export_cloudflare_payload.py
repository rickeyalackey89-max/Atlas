from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------
# Cloudflare payload exporter (Atlas)
#
# Reads latest CSV outputs for System + Windfall and audit_last5_board.csv
# (with *_avg columns) and writes a single canonical JSON payload:
#
#   data/output/dashboard/cloudflare_payload.json
#
# This file is intended to be the ONLY source consumed by AtlasDashboard/Cloudflare.
# GameScript will be added later; for now it's an empty array.
# ---------------------------------------------------------------------

PROJECT_ROOT = find_repo_root(Path(__file__))

LATEST_ALL = PROJECT_ROOT / "data" / "output" / "latest" / "all"
AUDIT_CSV  = PROJECT_ROOT / "data" / "gamelogs" / "audit_last5_board.csv"
OUT_DIR    = PROJECT_ROOT / "data" / "output" / "dashboard"
OUT_JSON   = OUT_DIR / "cloudflare_payload.json"

SYSTEM_DIR  = LATEST_ALL / "System"
WINDFALL_DIR = LATEST_ALL / "Windfall"

SYSTEM_FILES = {
    3: SYSTEM_DIR / "recommended_3leg.csv",
    4: SYSTEM_DIR / "recommended_4leg.csv",
    5: SYSTEM_DIR / "recommended_5leg.csv",
}

WINDFALL_FILES = {
    3: WINDFALL_DIR / "recommended_3leg.csv",
    4: WINDFALL_DIR / "recommended_4leg.csv",
    5: WINDFALL_DIR / "recommended_5leg.csv",
}


# -----------------------------
# Normalization
# -----------------------------
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def player_key(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = _strip_diacritics(name).lower()
    s = re.sub(r"[^a-z0-9\s\.\-']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = [p for p in s.split(" ") if p and p not in _SUFFIXES]
    return " ".join(parts).strip()

def normalize_dir(s: str) -> str:
    if not isinstance(s, str):
        return ""
    t = s.strip().upper()
    if t in {"OVER", "O", "MORE"}:
        return "OVER"
    if t in {"UNDER", "U", "LESS"}:
        return "UNDER"
    return t

def normalize_tier(s: str) -> str:
    if not isinstance(s, str):
        return ""
    t = s.strip().upper()
    # Some tiers appear as price labels; keep as-is if unknown
    if t in {"GOBLIN", "STANDARD", "DEMON"}:
        return t
    return t


# -----------------------------
# Parse leg raw string
# -----------------------------
LEG_RE = re.compile(
    r"^(?P<player>.+?)\s+"
    r"(?P<dir>OVER|UNDER|MORE|LESS|O|U)\s+"
    r"(?P<stat>[A-Z0-9\+]+)\s+"
    r"(?P<line>-?\d+(?:\.\d+)?)\s*"
    r"\((?P<tier>[^)]+)\)\s*"
    r"(?:\[(?:id|ID)\s*:\s*(?P<id>\d+)\s*\])?\s*$",
    re.IGNORECASE
)

ID_RE = re.compile(r"\[(?:id|ID)\s*:\s*(\d+)\s*\]")

def parse_leg_raw(raw: str) -> Dict[str, Any]:
    raw = str(raw or "").strip()
    out: Dict[str, Any] = {"raw": raw}

    if not raw:
        return out

    m = LEG_RE.match(raw)
    if m:
        out["player"] = m.group("player").strip()
        out["dir"] = normalize_dir(m.group("dir"))
        out["stat"] = m.group("stat").strip().upper()
        try:
            out["line"] = float(m.group("line"))
        except Exception:
            out["line"] = m.group("line")
        out["tier"] = normalize_tier(m.group("tier"))
        if m.group("id"):
            out["id"] = int(m.group("id"))
        return out

    # fallback parsing (best-effort)
    m_id = ID_RE.search(raw)
    if m_id:
        try:
            out["id"] = int(m_id.group(1))
        except Exception:
            pass

    # try to split at OVER/UNDER token
    m_dir = re.search(r"\b(OVER|UNDER|MORE|LESS|O|U)\b", raw, flags=re.IGNORECASE)
    if m_dir:
        out["player"] = raw[: m_dir.start()].strip()
        out["dir"] = normalize_dir(m_dir.group(1))

    m_stat = re.search(r"\b(OVER|UNDER|MORE|LESS|O|U)\s+([A-Z0-9\+]+)\b", raw, flags=re.IGNORECASE)
    if m_stat:
        out["stat"] = m_stat.group(2).upper()

    m_line = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\b", raw)
    if m_line:
        try:
            out["line"] = float(m_line.group(1))
        except Exception:
            out["line"] = m_line.group(1)

    m_tier = re.search(r"\(([^)]+)\)", raw)
    if m_tier:
        out["tier"] = normalize_tier(m_tier.group(1))

    return out


# -----------------------------
# Audit map
# -----------------------------
def load_audit(audit_csv: Path) -> Dict[str, Dict[str, Any]]:
    if not audit_csv.exists():
        raise FileNotFoundError(f"Missing audit file: {audit_csv}")
    df = pd.read_csv(audit_csv)

    # prefer resolved_player but fall back to board_player
    name_col = "resolved_player" if "resolved_player" in df.columns else "board_player"
    if "board_player" not in df.columns:
        raise ValueError("audit_last5_board.csv missing required column: board_player")

    out: Dict[str, Dict[str, Any]] = {}
    for _, r in df.iterrows():
        name = r.get(name_col, "") or r.get("board_player", "")
        k = player_key(str(name))
        if not k:
            continue
        out[k] = r.to_dict()
    return out

def audit_last5_val(audit_row: Dict[str, Any], stat: str) -> Optional[float]:
    if not audit_row:
        return None
    stat = (stat or "").upper()

    # Use *_avg columns if present; blank/NaN should return None
    def get_num(col: str) -> Optional[float]:
        v = audit_row.get(col, None)
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        try:
            return float(v)
        except Exception:
            return None

    # Direct
    if stat == "PTS":
        return get_num("last5_pts_avg")
    if stat == "REB":
        return get_num("last5_reb_avg")
    if stat == "AST":
        return get_num("last5_ast_avg")
    if stat == "FG3M":
        return get_num("last5_fg3m_avg")

    # Combos (prefer precomputed)
    if stat == "PR":
        v = get_num("last5_pr_avg")
        if v is not None:
            return v
        a, b = get_num("last5_pts_avg"), get_num("last5_reb_avg")
        return None if (a is None or b is None) else a + b

    if stat == "PA":
        v = get_num("last5_pa_avg")
        if v is not None:
            return v
        a, b = get_num("last5_pts_avg"), get_num("last5_ast_avg")
        return None if (a is None or b is None) else a + b

    if stat == "RA":
        v = get_num("last5_ra_avg")
        if v is not None:
            return v
        a, b = get_num("last5_reb_avg"), get_num("last5_ast_avg")
        return None if (a is None or b is None) else a + b

    if stat == "PRA":
        v = get_num("last5_pra_avg")
        if v is not None:
            return v
        a, b, c = get_num("last5_pts_avg"), get_num("last5_reb_avg"), get_num("last5_ast_avg")
        return None if (a is None or b is None or c is None) else a + b + c

    return None


# -----------------------------
# CSV -> Slip object
# -----------------------------
def read_top_row(csv_path: Path) -> Optional[Dict[str, Any]]:
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    return df.iloc[0].to_dict()

def guess_legs_from_row(row: Dict[str, Any]) -> Tuple[str, List[str]]:
    # Prefer legs_detail JSON if present
    for k in ("legs_detail", "legs_detail_json", "legsDetail", "legs_detail_str"):
        if k in row and isinstance(row[k], str) and row[k].strip():
            try:
                obj = json.loads(row[k])
                # allow either list of {"raw": "..."} or list of strings
                raws: List[str] = []
                for x in obj if isinstance(obj, list) else []:
                    if isinstance(x, dict) and "raw" in x:
                        raws.append(str(x["raw"]))
                    else:
                        raws.append(str(x))
                return (row.get("legs", row.get("legs_str", "")) or ""), raws
            except Exception:
                pass

    # Fallback to legs string
    legs_key = None
    for k in ("legs", "legs_str", "legsString"):
        if k in row:
            legs_key = k
            break
    legs_str = str(row.get(legs_key, "") or "") if legs_key else ""
    parts = [p.strip() for p in re.split(r"\s*\|\s*", legs_str) if p.strip()]
    return legs_str, parts

def build_slip(product: str, n_legs: int, csv_path: Path, audit_map: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    top = read_top_row(csv_path)
    if not top:
        return None

    legs_str, raw_legs = guess_legs_from_row(top)

    legs_detail: List[Dict[str, Any]] = []
    for raw in raw_legs[:n_legs]:
        leg = parse_leg_raw(raw)
        # attach last5_val based on audit avg fields
        pname = str(leg.get("player", "") or "")
        stat = str(leg.get("stat", "") or "")
        arow = audit_map.get(player_key(pname), {})
        v = audit_last5_val(arow, stat)
        if v is not None:
            # keep 3 decimals (matches audit rounding)
            leg["last5_val"] = round(float(v), 3)
        legs_detail.append(leg)

    slip: Dict[str, Any] = {
        "product": product,
        "n_legs": n_legs,
        "legs": legs_str,
        "legs_detail": legs_detail,
    }

    # carry through some useful fields if present (stringify to preserve exact source)
    passthrough = [
        "ev_mult", "ev", "atlas_ev",
        "hit_prob", "p_hit", "slip_p", "p_slip",
        "avg_fragility", "slip_tag_set", "slip_tag",
        "slip_agreement_tier", "slip_min_start_utc",
        "notes",
    ]
    for k in passthrough:
        if k in top and top[k] is not None and str(top[k]) != "nan":
            slip[k] = top[k]

    return slip


def main() -> None:
    audit_map = load_audit(AUDIT_CSV)

    system: List[Dict[str, Any]] = []
    for n, p in SYSTEM_FILES.items():
        s = build_slip("System", n, p, audit_map)
        if s:
            system.append(s)

    windfall: List[Dict[str, Any]] = []
    for n, p in WINDFALL_FILES.items():
        s = build_slip("Windfall", n, p, audit_map)
        if s:
            windfall.append(s)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "system": system,
        "windfall": windfall,
        "gamescript": [],  # to be added later from text inputs
        "status": None,
        "invalidations": None,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote: {OUT_JSON}")
    print(f"system_slips={len(system)} windfall_slips={len(windfall)} gamescript_slips=0")


if __name__ == "__main__":
    main()

import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# What src.features expects
SUPPORTED_STATS = {
    "3PM", "AST", "FG3M", "PA", "PR", "PRA", "PTS", "PTS_AST", "PTS_REB",
    "RA", "REB", "REB_AST"
}

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
OUT_CSV = os.path.join(PROJECT_ROOT, "data", "board", "today.csv")


def _safe_str(x: Any) -> str:
    return "" if x is None else str(x).strip()


def _iso_to_dt(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _clean_key(s: str) -> str:
    # normalize for matching
    return (
        s.strip()
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )


# Map common PrizePicks labels -> your expected codes
STAT_ALIASES = {
    # Singles
    "POINTS": "PTS",
    "PTS": "PTS",
    "REBOUNDS": "REB",
    "REB": "REB",
    "ASSISTS": "AST",
    "AST": "AST",

    # 3pt made
    "3PTMADE": "FG3M",
    "3PTSMade".upper().replace(" ", ""): "FG3M",
    "3POINTERSMADE": "FG3M",
    "FG3M": "FG3M",
    "3PM": "3PM",

    # Combos (no spaces)
    "POINTSREBOUNDS": "PR",
    "PTSREB": "PR",
    "PR": "PR",

    "POINTSASSISTS": "PA",
    "PTSAST": "PA",
    "PA": "PA",

    "REBOUNDSASSISTS": "RA",
    "REBAST": "RA",
    "RA": "RA",

    "POINTSREBOUNDSASSISTS": "PRA",
    "PTSREBAST": "PRA",
    "PRA": "PRA",

    # These two exist in your model list; sometimes PP labels them explicitly
    "POINTSREBOUNDS": "PR",
    "POINTSASSISTS": "PA",
}


def normalize_stat(raw: str) -> str:
    if not raw:
        return ""

    # If PP already gave you a model-code, keep it
    s0 = raw.strip()
    if s0 in SUPPORTED_STATS:
        return s0

    k = _clean_key(raw)

    # Handle plus-combos like "Points + Rebounds" etc.
    k = k.replace("+", "")

    # Direct alias lookup
    if k in STAT_ALIASES:
        return STAT_ALIASES[k]

    # Some PP variants:
    # "3-PT Made" -> 3PTMADE -> FG3M
    if "3PT" in k and "MADE" in k:
        return "FG3M"

    return ""


def _is_combo_text(raw: str) -> bool:
    return "+" in (raw or "")


def build_player_lookup(payload: Dict[str, Any]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    included = payload.get("included") or []
    for inc in included:
        try:
            inc_id = _safe_str(inc.get("id"))
            attrs = inc.get("attributes") or {}
            name = _safe_str(attrs.get("name"))
            if inc_id and name:
                lookup[inc_id] = name
        except Exception:
            continue
    return lookup


def pick_main_line(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sort_cols: List[str] = []
    ascending: List[bool] = []

    if "alt_line" in df.columns:
        sort_cols.append("alt_line")
        ascending.append(True)   # False first
    if "is_main" in df.columns:
        sort_cols.append("is_main")
        ascending.append(False)  # True first
    if "updated_at" in df.columns:
        sort_cols.append("updated_at")
        ascending.append(False)

    sort_cols.append("projection_id")
    ascending.append(True)

    df_sorted = df.sort_values(sort_cols, ascending=ascending, kind="mergesort")
    return df_sorted.drop_duplicates(subset=["player", "stat"], keep="first").copy()


def parse_projections(payload: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, int]]:
    data = payload.get("data") or []
    player_lookup = build_player_lookup(payload)

    dropped_unsupported = 0
    dropped_combo = 0
    dropped_started = 0
    dropped_missing_core = 0

    rows: List[Dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)

    for item in data:
        try:
            attrs = item.get("attributes") or {}
            rel = item.get("relationships") or {}

            projection_id = _safe_str(item.get("id"))

            # PrizePicks stat label may be "Points", etc.
            raw_stat = _safe_str(attrs.get("stat_type") or attrs.get("stat") or attrs.get("market"))
            stat = normalize_stat(raw_stat)

            line = attrs.get("line_score", None)

            start_time = _iso_to_dt(attrs.get("start_time"))
            updated_at = _iso_to_dt(attrs.get("updated_at") or attrs.get("updatedAt") or attrs.get("updated"))

            # player name via relationships
            player_name = ""
            for key in ("new_player", "player"):
                node = rel.get(key) or {}
                node_data = node.get("data") or {}
                pid = _safe_str(node_data.get("id"))
                if pid and pid in player_lookup:
                    player_name = player_lookup[pid]
                    break
            if not player_name:
                player_name = _safe_str(attrs.get("player_name") or attrs.get("player") or attrs.get("name"))

            if not player_name or not raw_stat:
                dropped_missing_core += 1
                continue

            # If PP label contains "+" and we *can't* normalize it, treat as combo/skip
            if _is_combo_text(raw_stat) and not stat:
                dropped_combo += 1
                continue

            # Drop games already started
            if start_time and start_time <= now_utc:
                dropped_started += 1
                continue

            # Drop anything we still don't support
            if stat not in SUPPORTED_STATS:
                dropped_unsupported += 1
                continue

            alt_line = attrs.get("is_alternate") or attrs.get("alt_line") or False
            is_main = attrs.get("is_main") or attrs.get("isMain") or False

            rows.append({
                "projection_id": projection_id,
                "player": player_name.strip(),
                "stat": stat,
                "line": line,
                "start_time": start_time.isoformat() if start_time else "",
                "updated_at": updated_at.isoformat() if updated_at else "",
                "alt_line": bool(alt_line),
                "is_main": bool(is_main),
            })

        except Exception:
            dropped_missing_core += 1
            continue

    df = pd.DataFrame(rows)

    if not df.empty:
        df["player"] = df["player"].astype(str).str.strip()
        df["stat"] = df["stat"].astype(str).str.strip()
        df = df.dropna(subset=["player", "stat"])
        df = df[(df["player"] != "") & (df["stat"] != "")]

    stats = {
        "dropped_unsupported": dropped_unsupported,
        "dropped_combo": dropped_combo,
        "dropped_started": dropped_started,
        "dropped_missing_core": dropped_missing_core,
    }
    return df, stats


def latest_raw_file() -> str:
    if not os.path.isdir(RAW_DIR):
        raise FileNotFoundError(f"Missing folder: {RAW_DIR}")
    files = [f for f in os.listdir(RAW_DIR) if f.startswith("prizepicks_") and f.endswith(".json")]
    if not files:
        raise FileNotFoundError(f"No raw json files found in: {RAW_DIR}")
    files.sort()
    return os.path.join(RAW_DIR, files[-1])


def main() -> None:
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    path = latest_raw_file()
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    df, stats = parse_projections(payload)
    before = len(df)
    df = pick_main_line(df)
    dropped_alt = before - len(df)

    if df.empty:
        raise RuntimeError(
            "Latest raw JSON produced 0 usable rows AFTER stat normalization. "
            "This means your raw file likely isn't NBA projections, or PrizePicks changed fields."
        )

    # Safe write
    tmp = OUT_CSV + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, OUT_CSV)

    print(f"Rebuilt from raw: {path}")
    print(f"Wrote: {OUT_CSV} (rows={len(df)})")
    print(f"Dropped unsupported/unknown stat: {stats['dropped_unsupported']}")
    print(f"Dropped combo props (A + B): {stats['dropped_combo']}")
    print(f"Dropped games already started: {stats['dropped_started']}")
    print(f"Dropped missing player/stat: {stats['dropped_missing_core']}")
    print(f"Dropped alt lines (kept 1 main line per player+stat): {dropped_alt}")


if __name__ == "__main__":
    main()
from __future__ import annotations
from Atlas.stages.rebuild.rebuild_today import run_rebuild

import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


# =========================
# Paths / Repo discovery
# =========================

def find_repo_root(start: Path) -> Path:
    """
    Walk upward until we find a repo layout with both /tools and /data folders.
    Falls back to the provided start path.
    """
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()


# File path: <repo>/src/Atlas/rebuild_today_from_any_raw.py
# parents[0] -> <repo>/src/Atlas
# parents[1] -> <repo>/src
# parents[2] -> <repo>
PROJECT_ROOT = find_repo_root(Path(__file__).parent)
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_PATH = PROJECT_ROOT / "data" / "board" / "today.csv"


# =========================
# Stat normalization
# =========================
# Canonical stats used across Atlas.
# NOTE: We do NOT drop unknown stats anymore (to satisfy: ALL stats, no silent fall-through).
CANONICAL_STATS = {
    # Singles
    "PTS",
    "REB",
    "AST",
    "BLK",
    "STL",
    "TOV",
    "FG3M",   # 3PT made
    "FGM",
    "FGA",
    "FTM",
    "FTA",
    # Combos
    "PR",     # Pts+Rebs
    "PA",     # Pts+Asts
    "RA",     # Rebs+Asts
    "PRA",    # Pts+Rebs+Asts
    "BS",     # Blks+Stls
}

# Map PrizePicks stat labels -> canonical codes
STAT_MAP: dict[str, str] = {
    # Points
    "POINTS": "PTS",
    "PTS": "PTS",

    # Rebounds
    "REBOUNDS": "REB",
    "REBS": "REB",
    "REB": "REB",

    # Assists
    "ASSISTS": "AST",
    "ASTS": "AST",
    "AST": "AST",

    # 3PT Made
    "3-PT MADE": "FG3M",
    "3-POINTERS MADE": "FG3M",
    "3PM": "FG3M",
    "3PTM": "FG3M",
    "FG3M": "FG3M",

    # Steals / Blocks / Turnovers (common variants)
    "STEALS": "STL",
    "STLS": "STL",
    "STL": "STL",
    "BLOCKS": "BLK",
    "BLKS": "BLK",
    "BLK": "BLK",
    "TURNOVERS": "TOV",
    "TOS": "TOV",
    "TOV": "TOV",

    # Combos
    "PTS+REBS": "PR",
    "POINTS+REBOUNDS": "PR",

    "PTS+ASTS": "PA",
    "POINTS+ASSISTS": "PA",

    "REBS+ASTS": "RA",
    "REBOUNDS+ASSISTS": "RA",

    "PTS+REBS+ASTS": "PRA",
    "POINTS+REBOUNDS+ASSISTS": "PRA",

    "BLKS+STLS": "BS",
    "BLOCKS+STEALS": "BS",

    # Free throw attempts
    "FREE THROWS ATTEMPTED": "FTA",
    "FREE THROW ATTEMPTS": "FTA",
    "FTA": "FTA",
}

# Map odds_type -> tier used elsewhere in the project
ODDS_TYPE_TO_TIER = {
    "standard": "STANDARD",
    "goblin": "GOBLIN",
    "demon": "DEMON",
}


# =========================
# Helpers
# =========================

def _clean_str(x: Any) -> str:
    return "" if x is None else str(x).strip()


def _parse_iso_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s2 = str(s).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _is_combo_player_name(name: str) -> bool:
    """
    Detect multi-player combo props like:
    - "A + B"
    - "A & B"
    - "A / B"
    These are NEVER allowed in Atlas.
    """
    n = _clean_str(name)
    if not n:
        return False

    for sep in [" + ", " & ", " / "]:
        if sep in n:
            return True

    if re.search(r"[A-Za-z]\s*[\+&/]\s*[A-Za-z]", n):
        return True

    return False


def _norm_stat(raw: Any) -> tuple[str, str, int]:
    """
    Returns (stat_canon, stat_raw_clean, is_canonical)
    - stat_canon: mapped canonical if known, else the cleaned raw (upper, normalized spaces)
    - stat_raw_clean: cleaned uppercase label
    - is_canonical: 1 if in known canonical set (either via map or already canonical), else 0
    """
    s = _clean_str(raw).upper()
    if not s:
        return "", "", 0

    s = re.sub(r"\s+", " ", s).strip()
    canon = STAT_MAP.get(s, s)

    is_canon = 1 if canon in CANONICAL_STATS else 0
    return canon, s, is_canon


def _load_latest_raw() -> Path:
    """
    Atlas 2.0 rule:
    1) Prefer prizepicks_*.json (live fetches)
    2) Choose newest by filesystem mtime
    3) Fall back to prizepicks_snapshot_*.json only if no prizepicks_*.json exist
    """
    live = sorted(RAW_DIR.glob("prizepicks_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if live:
        return live[0]

    snaps = sorted(RAW_DIR.glob("prizepicks_snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if snaps:
        return snaps[0]

    raise FileNotFoundError(f"No PrizePicks raw JSON files found in {RAW_DIR}")


def _build_player_map(payload: dict) -> dict[str, dict[str, str]]:
    """
    Build {player_id: {"name":..., "team":...}} from `included`.
    """
    mp: dict[str, dict[str, str]] = {}
    for inc in payload.get("included", []) or []:
        if inc.get("type") not in ("new_player", "player"):
            continue
        pid = _clean_str(inc.get("id"))
        attr = inc.get("attributes", {}) or {}
        name = _clean_str(attr.get("name"))
        team = _clean_str(attr.get("team"))
        if pid:
            mp[pid] = {"name": name, "team": team}
    return mp


def _get_player_id(item: dict) -> str:
    rel = item.get("relationships", {}) or {}
    return _clean_str(
        (((rel.get("new_player") or {}).get("data") or {}).get("id"))
        or (((rel.get("player") or {}).get("data") or {}).get("id"))
    )


def _dedupe_exact_props(base: pd.DataFrame) -> pd.DataFrame:
    """
    Keep ALL tiers and ALL alternate lines.

    Only remove true duplicates where the identity is the same:
      player + stat + tier + line + odds_type + start_time

    Prefer newest updated_at, then stable by source_projection_id.
    """
    if base.empty:
        return base

    df = base.copy()

    # Sort: newest first
    sort_cols: list[str] = []
    ascending: list[bool] = []
    for col, asc in [
        ("updated_at", False),
        ("source_projection_id", True),
    ]:
        if col in df.columns:
            sort_cols.append(col)
            ascending.append(asc)

    if sort_cols:
        df = df.sort_values(sort_cols, ascending=ascending, kind="mergesort")

    subset = [c for c in ["player", "stat", "tier", "line", "odds_type", "start_time"] if c in df.columns]
    if not subset:
        return df

    return df.drop_duplicates(subset=subset, keep="first").copy()


def _make_projection_id(source_projection_id: str, player: str, stat: str, tier: str, line: float, direction: str) -> str:
    """
    Enforce uniqueness per:
      player + stat + direction + line + tier

    We keep the provider id as part of the string when present, but do not rely on it.
    """
    # Use a stable, human-inspectable id
    src = _clean_str(source_projection_id) or "no_src"
    ply = _clean_str(player).replace("|", " ")
    st = _clean_str(stat)
    tr = _clean_str(tier)
    dr = _clean_str(direction)
    ln = f"{float(line):g}"
    return f"{src}|{ply}|{st}|{tr}|{ln}|{dr}"

def _build_replay_snapshot_name(raw_path: str, board_df: pd.DataFrame) -> str:
    raw_stem = Path(raw_path).stem  # prizepicks_20260227_105718

    slate_date = "unknown_date"
    if "game_date" in board_df.columns:
        s = (
            board_df["game_date"]
            .dropna()
            .astype(str)
            .str.strip()
        )
        s = s[s.ne("")]
        if not s.empty:
            dt = pd.to_datetime(s, errors="coerce")
            dt = dt.dropna()
            if not dt.empty:
                slate_date = dt.min().strftime("%Y%m%d")

    return f"replay_{slate_date}_{raw_stem}.csv"

# =========================
# Main
# =========================

def main() -> None:
    replay_raw = os.environ.get("ATLAS_REPLAY_RAW")
    is_replay = bool(replay_raw)
    # Resolve raw path (wrapper responsibility)
    if replay_raw:
        raw_path = Path(replay_raw).expanduser().resolve()
        if not raw_path.exists():
            raise FileNotFoundError(f"[REPLAY] ATLAS_REPLAY_RAW not found: {raw_path}")
        print(f"[REPLAY] Rebuild using raw: {raw_path}")

    else:
        raw_path = _load_latest_raw()

    # Load payload (wrapper responsibility)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))

    # Stage transform (pure deterministic logic)
    out = run_rebuild(payload=payload, is_replay=is_replay)

    # Preserve replay messaging (wrapper responsibility)
    if is_replay:
        print("[REPLAY] Rebuild bypassing started-game filtering (frozen now_utc).")

    # Write outputs (wrapper responsibility) — keep legacy path behavior
    out_path = Path("data") / "board" / "today.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote: {out_path}")

    # Snapshot (kept similar to fetch pattern)
    snap_dir = out_path.parent / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    if is_replay:
        snap_name = _build_replay_snapshot_name(str(raw_path), out)
        snap_path = snap_dir / snap_name
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snap_path = snap_dir / f"today_{ts}.csv"
    out.to_csv(snap_path, index=False)
    print(f"Snapshot: {snap_path}")
    
    if is_replay:
        print(f"[REPLAY] snapshot_written={snap_path}")

    # ---- Debug summary (safe; does not rely on legacy locals/counters)
    print(f"Rebuilt today.csv from: {raw_path}")
    print(f"Rows: {len(out)}")

    if "tier" in out.columns:
        print("\nTier counts:")
        print(out["tier"].value_counts(dropna=False))

    if "stat" in out.columns:
        print("\nStat counts (canonical):")
        print(out["stat"].value_counts(dropna=False).head(30))

    if "stat_is_canonical" in out.columns:
        noncanon = int((out["stat_is_canonical"] == 0).sum())
        if noncanon:
            print(f"\nWARNING: Non-canonical stat rows retained: {noncanon}")
            sample = (
                out.loc[out["stat_is_canonical"] == 0, ["stat_raw", "stat"]]
                .drop_duplicates()
                .head(15)
            )
            print("Sample unknown/mapped-through stats:")
            print(sample.to_string(index=False))


if __name__ == "__main__":
    main()
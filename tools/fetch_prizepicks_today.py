from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()

from typing import Any, Optional

import pandas as pd
import requests

# ---------------------------------------------------------------
# Paths (absolute, based on repo root)
# ---------------------------------------------------------------

from Atlas.runtime.paths import find_repo_root

PROJECT_ROOT = find_repo_root(Path(__file__))

OUT_PATH = PROJECT_ROOT / "data" / "board" / "fetch_board.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SNAP_DIR = PROJECT_ROOT / "data" / "board" / "snapshots"

# -------------------------------------------------------------------
# PrizePicks endpoint
# -------------------------------------------------------------------

LEAGUE_ID_NBA = 7
URL = (
    "https://api.prizepicks.com/projections"
    f"?league_id={LEAGUE_ID_NBA}"
    "&per_page=250"
    "&single_stat=false"
    "&in_game=false"
    "&state_code=MO"
    "&game_mode=prizepools"
)

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://app.prizepicks.com/",
    "User-Agent": "Mozilla/5.0",
}

# -------------------------------------------------------------------
# Supported stat codes in this project
# -------------------------------------------------------------------

SUPPORTED_STATS = {
    "PTS",
    "REB",
    "AST",
    "FG3M",
    "PR",   # Pts+Rebs
    "PA",   # Pts+Asts
    "RA",   # Rebs+Asts
    "PRA",  # Pts+Rebs+Asts
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _clean_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        s = str(x)
    except Exception:
        return ""
    return s.strip()


def _is_combo_player_name(name: str) -> bool:
    """
    Detect multi-player combo props like:
      - "A + B"
      - "A & B"
      - "A / B"
    These are NEVER allowed in Atlas (we only want single-player combo STATS like PRA/PR/PA/RA).
    """
    n = _clean_str(name)
    if not n:
        return False

    # Explicit multi-player separators
    for sep in [" + ", " & ", " / "]:
        if sep in n:
            return True

    # Catch cases without spaces but with letters on both sides
    if re.search(r"[A-Za-z]\s*[\+&/]\s*[A-Za-z]", n):
        return True

    return False

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def _fetch_json(
    url: str,
    timeout: int = 30,
    max_attempts: int = 8,
    cache_path: str | None = None,
    cache_ttl_seconds: int = 180,
) -> dict[str, Any]:
    """
    Fetch JSON with:
      - TTL cache (default 3 minutes) to avoid re-hitting rate-limited endpoints
      - HTTP 429 handling (Retry-After + exponential backoff + jitter)
    """
    import os
    import json
    import time
    import random
    from pathlib import Path

    # ---- Cache read (if enabled)
    if cache_path:
        try:
            p = Path(cache_path)
            if p.exists():
                age = time.time() - p.stat().st_mtime
                if age <= cache_ttl_seconds:
                    with p.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    print(f"[CACHE HIT] {p} (age={age:.1f}s <= {cache_ttl_seconds}s)")
                    return data
        except Exception as e:
            print(f"[CACHE WARN] Could not read cache ({cache_path}): {e}")

    s = _make_session()
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = s.get(url, timeout=timeout)

            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_s = int(retry_after)
                    except ValueError:
                        sleep_s = 15
                else:
                    sleep_s = min(120, (2 ** (attempt - 1))) + random.uniform(0, 1.5)

                print(f"[RATE LIMIT] 429 Too Many Requests. Sleeping {sleep_s:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(sleep_s)
                continue

            r.raise_for_status()
            data = r.json()

            # ---- Cache write (if enabled)
            if cache_path:
                try:
                    p = Path(cache_path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with p.open("w", encoding="utf-8") as f:
                        json.dump(data, f)
                    print(f"[CACHE WRITE] {p}")
                except Exception as e:
                    print(f"[CACHE WARN] Could not write cache ({cache_path}): {e}")

            return data

        except Exception as e:
            last_exc = e
            sleep_s = min(60, (2 ** (attempt - 1))) + random.uniform(0, 1.5)
            print(f"[FETCH ERROR] {e}. Sleeping {sleep_s:.1f}s (attempt {attempt}/{max_attempts})")
            time.sleep(sleep_s)

    raise RuntimeError(f"Failed to fetch JSON after {max_attempts} attempts: {last_exc}")

def _parse_iso_datetime(s: str) -> Optional[datetime]:
    s = _clean_str(s)
    if not s:
        return None
    # Handle Zulu
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        # ensure tz-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _infer_tag(odds_type: Any) -> str:
    t = _clean_str(odds_type).upper()
    # PrizePicks commonly uses these; keep tolerant
    if "GOBLIN" in t:
        return "GOBLIN"
    if "DEMON" in t:
        return "DEMON"
    return ""


def _norm_stat(stat_raw: Any) -> str:
    s = _clean_str(stat_raw)

    # Normalize separators/spaces
    s2 = s.replace(" ", "").replace("–", "-").replace("—", "-")

    # Common singles
    single_map = {
        "Points": "PTS",
        "Pts": "PTS",
        "Rebounds": "REB",
        "Rebs": "REB",
        "Assists": "AST",
        "Asts": "AST",
        "3-PTMade": "FG3M",
        "3PTMade": "FG3M",
        "3PointersMade": "FG3M",
        "3-PointersMade": "FG3M",
        "3PTM": "FG3M",
        "FG3M": "FG3M",
    }

    # If exact match exists
    if s in single_map:
        return single_map[s]

    # Try stripping punctuation variants
    if s2 in single_map:
        return single_map[s2]

    # Combos often appear like these
    combo_map = {
        "Pts+Rebs": "PR",
        "Points+Rebounds": "PR",
        "Pts+Ast": "PA",
        "Pts+Asts": "PA",
        "Points+Assists": "PA",
        "Rebs+Asts": "RA",
        "Rebounds+Assists": "RA",
        "Pts+Rebs+Asts": "PRA",
        "Points+Rebounds+Assists": "PRA",
        "PRA": "PRA",
        "PR": "PR",
        "PA": "PA",
        "RA": "RA",
    }

    if s in combo_map:
        return combo_map[s]
    if s2 in combo_map:
        return combo_map[s2]

    # Some feeds use stat_display_name vs stat_type slightly differently
    # so try a few friendly reductions
    s3 = s.replace(" ", "")
    if s3 in combo_map:
        return combo_map[s3]
    if s3 in single_map:
        return single_map[s3]

    return ""


def _pick_main_line(group: pd.DataFrame) -> pd.DataFrame:
    """
    Pick ONE line for a given (player, stat).
    Main line = most common line (mode).
    Tie-break:
      - prefer tag == "" (standard)
      - then prefer closest to median line
    """
    g = group.copy()

    # Ensure numeric line within each group for stable value_counts/median math
    g["line"] = pd.to_numeric(g["line"], errors="coerce")

    vc = g["line"].value_counts(dropna=True)
    if vc.empty:
        # NEVER drop the whole group; keep one row so the board can't collapse to 0
        return g.head(1)

    top = vc.max()
    modes = vc[vc == top].index.tolist()
    cand = g[g["line"].isin(modes)].copy()

    # prefer standard props (no tag)
    def tag_rank(t: Any) -> int:
        t = _clean_str(t).upper()
        if t == "":
            return 0
        if t == "GOBLIN":
            return 1
        if t == "DEMON":
            return 2
        return 3

    cand["tag_rank"] = cand["tag"].apply(tag_rank)
    cand = cand.sort_values(["tag_rank"]).copy()

    if len(cand) == 1:
        return cand.drop(columns=["tag_rank"])

    med = cand["line"].median()
    cand["dist"] = (cand["line"] - med).abs()
    cand = cand.sort_values(["tag_rank", "dist"])
    return cand.head(1).drop(columns=["tag_rank", "dist"])


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    payload = _fetch_json(URL)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"prizepicks_{ts}.json"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    data = payload.get("data", []) or []
    included = payload.get("included", []) or []

    # Build players map
    players: dict[str, dict[str, Any]] = {}
    for inc in included:
        if inc.get("type") in ("new_player", "player"):
            pid = _clean_str(inc.get("id"))
            attr = inc.get("attributes", {}) or {}
            players[pid] = {"name": attr.get("name"), "team": attr.get("team")}

    dropped_unknown_stat = 0
    dropped_combo_players = 0
    dropped_started_games = 0
    dropped_missing_player = 0
    dropped_bad_rows = 0
    dropped_alt_lines = 0

    now_utc = datetime.now(timezone.utc)

    rows: list[dict[str, Any]] = []

    for item in data:
        if item.get("type") != "projection":
            continue

        attr = item.get("attributes", {}) or {}
        rel = item.get("relationships", {}) or {}

        proj_id = _clean_str(item.get("id"))

        player_id = _clean_str(
            ((rel.get("new_player") or {}).get("data") or {}).get("id")
            or ((rel.get("player") or {}).get("data") or {}).get("id")
        )

        p = players.get(player_id, {})
        player_name = _clean_str(p.get("name"))
        team = _clean_str(p.get("team"))

        # Fallbacks: projection itself can include display name/team in some variants
        if not player_name:
            player_name = _clean_str(attr.get("description") or attr.get("player_name") or attr.get("name"))
        if not team:
            team = _clean_str(attr.get("team") or attr.get("team_abbr"))

        if not player_name:
            dropped_missing_player += 1
            continue

        # Skip combo players like "A + B"
        if _is_combo_player_name(player_name):
            dropped_combo_players += 1
            continue

        stat = _norm_stat(attr.get("stat_type") or attr.get("stat_type_display") or attr.get("stat_display_name"))
        if not stat or stat not in SUPPORTED_STATS:
            dropped_unknown_stat += 1
            continue

        start_time = _clean_str(attr.get("start_time"))
        dt = _parse_iso_datetime(start_time)
        if dt is not None and dt < now_utc:
            dropped_started_games += 1
            continue

        game_date = _clean_str(attr.get("game_date"))

        line = attr.get("line_score")
        if line is None:
            line = attr.get("flash_sale_line_score")
        if line is None:
            line = attr.get("line") or attr.get("score") or attr.get("projection")

        try:
            line = float(line) if line is not None else None
        except Exception:
            line = None

        odds_type = attr.get("odds_type")
        tag = _infer_tag(odds_type)

        opp = _clean_str(attr.get("opponent"))
        home = 1 if _clean_str(attr.get("home")) in ("1", "True", "true") else 0

        rows.append(
            {
                "projection_id": proj_id,
                "player": player_name,
                "stat": stat,
                "line": line,
                "tag": tag,
                "team": team,
                "opp": opp,
                "home": home,
                "game_date": game_date,
            }
        )

    base = pd.DataFrame(rows)

    # Guard: strip blanks
    if not base.empty:
        before_guard = len(base)
        base["player"] = base["player"].fillna("").astype(str)
        base["stat"] = base["stat"].fillna("").astype(str)
        base = base[(base["player"].str.strip() != "") & (base["stat"].str.strip() != "")].copy()
        dropped_bad_rows = before_guard - len(base)

    # Ensure numeric line and drop rows with missing line BEFORE mainline selection
    if not base.empty:
        base["line"] = pd.to_numeric(base["line"], errors="coerce")
        base = base[base["line"].notna()].copy()

    if base.empty:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        base.to_csv(OUT_PATH, index=False)

        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        snap_path = SNAP_DIR / f"today_{ts}.csv"
        base.to_csv(snap_path, index=False)

        print(f"Fetched from: {URL}")
        print(f"Wrote: {OUT_PATH} (rows=0)")
        print(f"Saved raw: {raw_path}")
        print(f"Dropped unsupported/unknown stat: {dropped_unknown_stat}")
        print(f"Dropped combo players (multi-player props): {dropped_combo_players}")
        print(f"Dropped missing player: {dropped_missing_player}")
        print(f"Dropped games already started: {dropped_started_games}")
        print(f"Dropped blank player/stat rows (guard): {dropped_bad_rows}")
        print("Dropped alt lines (kept 1 main line per player+stat): 0")
        return

    before = len(base)

    # IMPORTANT: reset index to avoid weird namedtuple/_asdict issues
    base = base.reset_index(drop=True)

    # Main-line selection
    filtered = (
        base.groupby(["player", "stat"], group_keys=False)
        .apply(_pick_main_line)
        .reset_index()
    )

    # pandas groupby/apply can drop group keys ("player","stat") from returned frame.
    # Recover deterministically.
    if "player" not in filtered.columns or "stat" not in filtered.columns:
        rename_map = {}
        if "level_0" in filtered.columns:
            rename_map["level_0"] = "player"
        if "level_1" in filtered.columns:
            rename_map["level_1"] = "stat"
        if rename_map:
            filtered = filtered.rename(columns=rename_map)

    # Final fallback: merge keys back using projection_id
    if "player" not in filtered.columns or "stat" not in filtered.columns:
        keys = base[["projection_id", "player", "stat"]].drop_duplicates("projection_id")
        filtered = filtered.merge(keys, on="projection_id", how="left")

    filtered = filtered.reset_index(drop=True)

    after = len(filtered)
    dropped_alt_lines = before - after

    # Expand to OVER/UNDER
    expanded_rows: list[dict[str, Any]] = []
    for d in filtered.to_dict("records"):
        for direction in ("OVER", "UNDER"):
            expanded_rows.append(
                {
                    "projection_id": d.get("projection_id", ""),
                    "player": d.get("player", ""),
                    "stat": d.get("stat", ""),
                    "direction": direction,
                    "line": d.get("line", ""),
                    "tag": d.get("tag", ""),
                    "team": d.get("team", ""),
                    "opp": d.get("opp", ""),
                    "home": d.get("home", 0),
                    "game_date": d.get("game_date", ""),
                }
            )

    df = pd.DataFrame(expanded_rows)
    if not df.empty:
        df["line"] = pd.to_numeric(df["line"], errors="coerce")
        df = df[df["line"].notna()].copy()

        # final guard for blanks
        df["player"] = df["player"].fillna("").astype(str)
        df["stat"] = df["stat"].fillna("").astype(str)
        bad = (df["player"].str.strip() == "") | (df["stat"].str.strip() == "")
        if bad.any():
            df = df.loc[~bad].copy()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAP_DIR / f"today_{ts}.csv"
    df.to_csv(snap_path, index=False)

    print(f"Fetched from: {URL}")
    print(f"Wrote: {OUT_PATH} (rows={len(df)})")
    print(f"Saved raw: {raw_path}")
    print(f"Dropped unsupported/unknown stat: {dropped_unknown_stat}")
    print(f"Dropped combo players (multi-player props): {dropped_combo_players}")
    print(f"Dropped missing player: {dropped_missing_player}")
    print(f"Dropped games already started: {dropped_started_games}")
    print(f"Dropped blank player/stat rows (guard): {dropped_bad_rows}")
    print(f"Dropped alt lines (kept 1 main line per player+stat): {dropped_alt_lines}")


if __name__ == "__main__":
    main()
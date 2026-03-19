from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

from Atlas.stages.common.paths import find_repo_root
from Atlas.stages.fetch.fetch_prizepicks_today import run_fetch

# ---------------------------------------------------------------
# Paths
# ---------------------------------------------------------------

PROJECT_ROOT = find_repo_root(Path(__file__))

OUT_PATH = PROJECT_ROOT / "data" / "board" / "fetch_board.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SNAP_DIR = PROJECT_ROOT / "data" / "board" / "snapshots"

# ---------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------

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

# Kept here for backward compatibility/readability (stage has its own copy).
SUPPORTED_STATS = {
    "PTS", "REB", "AST", "FG3M",
    "PR", "PA", "RA", "PRA",
}

# ---------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s

# ---------------------------------------------------------------
# REPLAY-AWARE FETCH
# ---------------------------------------------------------------

def _load_json_from_disk(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _fetch_json_live(
    url: str,
    timeout: int = 30,
    max_attempts: int = 8,
) -> dict[str, Any]:

    session = _make_session()
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = session.get(url, timeout=timeout)

            if r.status_code == 429:
                sleep_s = min(120, (2 ** (attempt - 1))) + random.uniform(0, 1.5)
                print(f"[RATE LIMIT] Sleeping {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_exc = e
            sleep_s = min(60, (2 ** (attempt - 1))) + random.uniform(0, 1.5)
            print(f"[FETCH ERROR] {e}. Sleeping {sleep_s:.1f}s")
            time.sleep(sleep_s)

    raise RuntimeError(f"Failed to fetch JSON: {last_exc}")

def _get_payload(url: str, raw_path: Optional[str]) -> tuple[dict[str, Any], bool]:
    """
    Replay precedence:
      1) --raw-path argument
      2) ATLAS_REPLAY_RAW env var
      3) live HTTP
    Returns: (payload, is_replay)
    """
    if raw_path:
        p = Path(raw_path).resolve()
        print(f"[REPLAY] Loading raw JSON from: {p}")
        return _load_json_from_disk(p), True

    env_raw = os.environ.get("ATLAS_REPLAY_RAW")
    if env_raw:
        p = Path(env_raw).resolve()
        print(f"[REPLAY] Loading raw JSON from env: {p}")
        return _load_json_from_disk(p), True

    return _fetch_json_live(url), False


# ---------------------------------------------------------------
# Sticky-Union Roster Map
# ---------------------------------------------------------------

def _is_valid_team_abbr(team: str) -> bool:
    """Check if team is a valid 3-letter uppercase NBA abbreviation."""
    return isinstance(team, str) and len(team) == 3 and team.isupper() and team.isalpha()


def _update_roster_map(final_df: pd.DataFrame, run_ts: str) -> None:
    """
    Build sticky-union roster map from today's fetch and existing roster_map.csv.
    Writes updates to roster_map.csv and audit files.
    """
    ROSTER_MAP_PATH = PROJECT_ROOT / "data" / "input" / "roster_map.csv"
    AUDIT_DIR = PROJECT_ROOT / ".atlas_audit" / "diagnostics"
    
    # Build today_map: player -> team (only valid entries)
    today_map = {}
    for _, row in final_df.iterrows():
        player = str(row.get("player", "")).strip()
        team = str(row.get("team", "")).strip()
        
        if player and _is_valid_team_abbr(team):
            today_map[player] = team
    
    # Load existing roster_map if it exists
    old_map = {}
    if ROSTER_MAP_PATH.exists():
        old_df = pd.read_csv(ROSTER_MAP_PATH)
        old_map = dict(zip(old_df["player"], old_df["team"]))
    
    # Build new_map with sticky-union logic
    new_map = old_map.copy()
    new_map.update(today_map)
    
    # Detect conflicts (multiple teams per player in final_df)
    conflicts = []
    for player in today_map:
        player_rows = final_df[final_df["player"].astype(str).str.strip() == player]
        teams = player_rows["team"].astype(str).str.strip().unique()
        
        if len(teams) > 1 and all(_is_valid_team_abbr(t) for t in teams):
            # Use mode (most frequent); if tie, use first alphabetically
            mode_team = player_rows["team"].astype(str).str.strip().mode()
            chosen_team = mode_team[0] if len(mode_team) > 0 else teams[0]
            conflicts.append({
                "player": player,
                "conflicting_teams": ",".join(sorted(teams)),
                "chosen_team": chosen_team,
            })
            new_map[player] = chosen_team
    
    # Build audit: changes only
    updates = []
    for player, new_team in new_map.items():
        old_team = old_map.get(player, "")
        if old_team != new_team:  # Only changed rows
            updates.append({
                "player": player,
                "old_team": old_team,
                "new_team": new_team,
                "source": "fetch_board",
            })
    
    # Write roster_map.csv
    ROSTER_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    roster_df = pd.DataFrame([
        {"player": p, "team": t} for p, t in sorted(new_map.items())
    ])
    roster_df.to_csv(ROSTER_MAP_PATH, index=False)
    print(f"[ROSTER_MAP] Wrote {len(new_map)} entries to {ROSTER_MAP_PATH}")
    
    # Write audit updates
    if updates:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        updates_df = pd.DataFrame(updates)
        updates_path = AUDIT_DIR / f"roster_map_updates_{run_ts}.csv"
        updates_df.to_csv(updates_path, index=False)
        print(f"[ROSTER_MAP] Wrote {len(updates)} updates to {updates_path}")
    
    # Write audit conflicts
    if conflicts:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        conflicts_df = pd.DataFrame(conflicts)
        conflicts_path = AUDIT_DIR / f"roster_map_conflicts_{run_ts}.csv"
        conflicts_df.to_csv(conflicts_path, index=False)
        print(f"[ROSTER_MAP] Wrote {len(conflicts)} conflicts to {conflicts_path}")


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------

def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-path", help="Replay: load raw PrizePicks JSON from disk")
    ap.add_argument(
        "--raw-only",
        action="store_true",
        help="Legacy flag (kept for orchestrator compatibility).",
    )
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    payload, is_replay = _get_payload(URL, args.raw_path)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"prizepicks_{ts}.json"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    # --- Phase 6: core logic moved into stage module (no behavior change) ---
    final_df = run_fetch(payload=payload, is_replay=is_replay)

    # --- FETCH CONTRACT GATE (fail-fast) ---
    REQUIRED = ["player", "stat", "line", "team", "opp", "home", "game_date", "direction"]
    missing = [c for c in REQUIRED if c not in final_df.columns]
    if missing:
        raise ValueError(f"FETCH CONTRACT FAIL: missing columns: {missing}")

    import pandas as pd

    for c in ["player", "stat", "team", "opp", "game_date", "direction"]:
        final_df[c] = final_df[c].astype(str).fillna("").str.strip()

    if "home" not in final_df.columns:
        final_df["home"] = 0
    final_df["home"] = pd.to_numeric(final_df["home"], errors="coerce").fillna(0).astype(int)

    final_df["line"] = pd.to_numeric(final_df["line"], errors="coerce")

    rows = len(final_df)
    if rows <= 0:
        raise ValueError("FETCH CONTRACT FAIL: 0 rows")

    opp_blank = (final_df["opp"].str.len() == 0).mean()
    date_blank = (final_df["game_date"].str.len() == 0).mean()
    line_nan = final_df["line"].isna().mean()

    if opp_blank != 0.0:
        raise ValueError(f"FETCH CONTRACT FAIL: opp_blank={opp_blank}")
    if date_blank != 0.0:
        raise ValueError(f"FETCH CONTRACT FAIL: date_blank={date_blank}")
    if line_nan > 0.0:
        raise ValueError(f"FETCH CONTRACT FAIL: line_nan={line_nan}")

    multi_team_rows = final_df["team"].str.contains("/", regex=False, na=False).sum()
    if multi_team_rows:
        raise ValueError(f"FETCH CONTRACT FAIL: multi_team_team_rows={multi_team_rows}")

    report = {
        "rows": int(rows),
        "opp_blank": float(opp_blank),
        "date_blank": float(date_blank),
        "line_nan_rate": float(line_nan),
        "multi_team_team_rows": int(multi_team_rows),
        "dtypes": {k: str(v) for k, v in final_df.dtypes.items()},
    }
    Path("data/board").mkdir(parents=True, exist_ok=True)
    Path("data/board/fetch_contract_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    # --- END FETCH CONTRACT GATE ---

    # --- STICKY-UNION ROSTER MAP (after contract validation) ---
    _update_roster_map(final_df, ts)
    # --- END ROSTER MAP ---

    if final_df.empty:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        final_df.to_csv(OUT_PATH, index=False)
        print(f"Wrote: {OUT_PATH} (rows=0)")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(OUT_PATH, index=False)

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"today_{ts}.csv").write_text(final_df.to_csv(index=False), encoding="utf-8")

    print(f"Wrote: {OUT_PATH} (rows={len(final_df)})")


if __name__ == "__main__":
    main()
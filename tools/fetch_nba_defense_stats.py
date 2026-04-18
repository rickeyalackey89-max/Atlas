#!/usr/bin/env python3
"""
Fetch NBA.com team-level opponent stats (defense vs. category).

Calls the ``leaguedashteamstats`` endpoint with ``MeasureType=Opponent``
to get per-team opponent averages for PTS, REB, AST, FG3M, BLK, STL, TOV.
Computes a league-relative factor for each stat: >0 means opponent is *soft*
(allows more than league avg), <0 means tough defence.

Outputs:
  data/input/nba_team_defense_today.csv   (overwritten each run)
  data/archives/nba_defense/nba_team_defense_<date>.csv  (immutable per-date)

ENV:
  NBA_DEFENSE_SEASON        (optional) e.g. "2025-26"
  NBA_DEFENSE_GAME_DATE     (optional) YYYY-MM-DD for labelling/archiving
  NBA_DEFENSE_TIMEOUT_S     (optional) request timeout, default 15
  NBA_DEFENSE_OUT_PATH      (optional) override output csv path
"""
from __future__ import annotations

import csv
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_out_path() -> Path:
    return _repo_root() / "data" / "input" / "nba_team_defense_today.csv"


def _default_archive_dir() -> Path:
    return _repo_root() / "data" / "archives" / "nba_defense"


# ---------------------------------------------------------------------------
# NBA.com stat columns → Atlas stat names
# ---------------------------------------------------------------------------

# The leaguedashteamstats Opponent endpoint returns columns prefixed "OPP_"
# These are per-game averages of what the opponent *allows*.
STAT_COL_MAP: Dict[str, str] = {
    "OPP_PTS": "PTS",
    "OPP_REB": "REB",
    "OPP_AST": "AST",
    "OPP_FG3M": "FG3M",
    "OPP_BLK": "BLK",
    "OPP_STL": "STL",
    "OPP_TOV": "TOV",
}

# Combo stats are computed from component averages.
COMBO_COMPONENTS: Dict[str, List[str]] = {
    "PRA": ["PTS", "REB", "AST"],
    "PR": ["PTS", "REB"],
    "PA": ["PTS", "AST"],
    "RA": ["REB", "AST"],
}

# ---------------------------------------------------------------------------
# NBA.com API (via nba_api)
# ---------------------------------------------------------------------------


def _current_season() -> str:
    """Return the NBA season string like '2025-26'."""
    now = datetime.now()
    # NBA season starts in October; season year = calendar year of October start.
    year = now.year if now.month >= 10 else now.year - 1
    return f"{year}-{(year + 1) % 100:02d}"


def fetch_team_opponent_stats(
    season: str | None = None,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """Fetch per-team opponent PerGame stats from NBA.com via nba_api."""
    from nba_api.stats.endpoints import LeagueDashTeamStats

    season = season or os.getenv("NBA_DEFENSE_SEASON", _current_season())
    timeout = int(os.getenv("NBA_DEFENSE_TIMEOUT_S", str(timeout)))

    print(f"[NBA DEFENSE] Fetching {season} team opponent stats via nba_api …")
    last_err = None
    for attempt in range(1, 4):
        try:
            endpoint = LeagueDashTeamStats(
                season=season,
                measure_type_detailed_defense="Opponent",
                per_mode_detailed="PerGame",
                season_type_all_star="Regular Season",
                timeout=timeout,
            )
            df = endpoint.get_data_frames()[0]
            break
        except Exception as exc:
            last_err = exc
            wait = attempt * 10
            print(f"[NBA DEFENSE] Attempt {attempt} failed ({type(exc).__name__}: {exc}), retrying in {wait}s …")
            import time
            time.sleep(wait)
    else:
        raise last_err  # type: ignore[misc]

    print(f"[NBA DEFENSE] Got {len(df)} teams, {len(df.columns)} columns")
    records: List[Dict[str, Any]] = df.to_dict("records")
    return records


# ---------------------------------------------------------------------------
# NBA team abbreviation mapping
# ---------------------------------------------------------------------------

# nba_api's LeagueDashTeamStats does NOT return TEAM_ABBREVIATION;
# it only has TEAM_ID and TEAM_NAME.  We use nba_api.stats.static.teams
# to build a lookup, then apply Atlas-specific overrides.

ABBR_OVERRIDE: Dict[str, str] = {
    "PHX": "PHO",   # Some gamelog sources use PHO for Phoenix
}


def _build_team_id_to_abbr() -> Dict[int, str]:
    """Build a TEAM_ID → abbreviation mapping from nba_api static data."""
    from nba_api.stats.static import teams as _teams_mod
    mapping: Dict[int, str] = {}
    for t in _teams_mod.get_teams():
        abbr = str(t.get("abbreviation", "")).upper()
        abbr = ABBR_OVERRIDE.get(abbr, abbr)
        mapping[int(t["id"])] = abbr
    return mapping


def _normalise_team_by_id(team_id: int, lookup: Dict[int, str]) -> str:
    """Return the Atlas-standard team abbreviation for a given TEAM_ID."""
    return lookup.get(team_id, "")


# ---------------------------------------------------------------------------
# Compute defence-vs-category factors
# ---------------------------------------------------------------------------

def build_defense_factors(
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert raw opponent per-game stats into league-relative factors.

    For each team and stat, compute:
        factor = team_opp_avg / league_avg  (>1.0 = soft, <1.0 = tough)
        rel    = factor - 1.0               (centred at 0; what the calibrator expects)
    """
    if not records:
        return []

    # Compute league averages for each stat column
    league_avgs: Dict[str, float] = {}
    for col in STAT_COL_MAP:
        vals = [float(r.get(col, 0)) for r in records if r.get(col) is not None]
        league_avgs[col] = sum(vals) / len(vals) if vals else 0.0

    # Also compute league averages for combo stats
    combo_league: Dict[str, float] = {}
    for combo, components in COMBO_COMPONENTS.items():
        src_cols = [k for k, v in STAT_COL_MAP.items() if v in components]
        total = sum(league_avgs.get(c, 0) for c in src_cols)
        combo_league[combo] = total

    # Build TEAM_ID → abbreviation lookup once
    _id_to_abbr = _build_team_id_to_abbr()

    rows_out: List[Dict[str, Any]] = []
    for rec in records:
        team_abbr = _normalise_team_by_id(int(rec.get("TEAM_ID", 0)), _id_to_abbr)
        team_name = rec.get("TEAM_NAME", "")
        gp = int(rec.get("GP", 0))

        # Singles
        for col, stat in STAT_COL_MAP.items():
            val = float(rec.get(col, 0))
            lavg = league_avgs.get(col, 0)
            factor = val / lavg if lavg > 0 else 1.0
            rel = round(factor - 1.0, 5)
            rows_out.append({
                "team": team_abbr,
                "team_name": team_name,
                "stat": stat,
                "opp_avg_pg": round(val, 2),
                "league_avg_pg": round(lavg, 2),
                "defense_factor": round(factor, 5),
                "defense_rel": rel,
                "gp": gp,
            })

        # Combos
        for combo, components in COMBO_COMPONENTS.items():
            src_cols = [k for k, v in STAT_COL_MAP.items() if v in components]
            val = sum(float(rec.get(c, 0)) for c in src_cols)
            lavg = combo_league.get(combo, 0)
            factor = val / lavg if lavg > 0 else 1.0
            rel = round(factor - 1.0, 5)
            rows_out.append({
                "team": team_abbr,
                "team_name": team_name,
                "stat": combo,
                "opp_avg_pg": round(val, 2),
                "league_avg_pg": round(lavg, 2),
                "defense_factor": round(factor, 5),
                "defense_rel": rel,
                "gp": gp,
            })

    return rows_out


# ---------------------------------------------------------------------------
# Write CSV
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "team", "team_name", "stat", "opp_avg_pg", "league_avg_pg",
    "defense_factor", "defense_rel", "gp",
]


def write_csv(
    rows: List[Dict[str, Any]],
    out_path: Path | None = None,
    archive_dir: Path | None = None,
    game_date: str | None = None,
) -> Path:
    out_path = Path(os.getenv("NBA_DEFENSE_OUT_PATH", str(out_path or _default_out_path())))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[NBA DEFENSE] Wrote {len(rows)} rows -> {out_path}")

    # Archive
    archive_dir = Path(archive_dir or _default_archive_dir())
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_tag = game_date or os.getenv(
        "NBA_DEFENSE_GAME_DATE",
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
    )
    archive_name = f"nba_team_defense_{date_tag.replace('-', '')}.csv"
    archive_path = archive_dir / archive_name
    if not archive_path.exists():
        shutil.copy2(out_path, archive_path)
        print(f"[NBA DEFENSE] Archived -> {archive_path}")

    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    records = fetch_team_opponent_stats()
    if not records:
        print("[NBA DEFENSE] No data returned — exiting")
        sys.exit(1)

    rows = build_defense_factors(records)
    write_csv(rows)

    # Quick summary
    print(f"\n[NBA DEFENSE] Summary ({len(records)} teams):")
    for stat in ["PTS", "REB", "AST", "FG3M", "PRA"]:
        stat_rows = [r for r in rows if r["stat"] == stat]
        if not stat_rows:
            continue
        softest = max(stat_rows, key=lambda r: r["defense_rel"])
        toughest = min(stat_rows, key=lambda r: r["defense_rel"])
        print(
            f"  {stat:5s}: softest={softest['team']} ({softest['defense_rel']:+.3f}), "
            f"toughest={toughest['team']} ({toughest['defense_rel']:+.3f})"
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
tools/refresh_iael_today.py

LIVE IAEL refresh tool.
Purpose (in Atlas model terms):
- Ensure injury availability gate can be satisfied for today's live runs.
- Prefer to run the existing injury pull/parse pipeline if present.
- Ensure dashboard status_latest.json includes report_date when not in dead_period.
- Ensure invalidations_latest.json exists (may be empty list).

This tool is invoked by src/Atlas/cli.py LIVE preflight when cached IAEL proof is missing.
It MUST be safe to run many times per day (idempotent).
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

def _local_now() -> datetime:
    # Windows local time; consistent with your printed timestamps
    return datetime.now()

def _is_enforced_window(now: datetime) -> bool:
    # 10:00 AM to 10:00 PM inclusive start, exclusive end
    return time(10, 0) <= now.time() < time(22, 0)

def _assert_no_team_mismatches(root: Path, latest_norm: Path) -> None:
    """
    HARD STOP if IAEL assigns a known roster_map player to the wrong team.
    Unknown players (not in roster_map) are ignored.
    Writes an audit CSV under .atlas_audit/diagnostics/ before raising.
    """
    # Ensure we can import Atlas modules from src-layout
    src_dir = root / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))

    from Atlas.core.iael_filter import normalize_person_name
    from Atlas.engine.new_probability import _team_to_abbr

    # Load IAEL normalized rows
    data = json.loads(latest_norm.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    # Load roster_map (canonical)
    roster_path = root / "data" / "input" / "roster_map.csv"
    if not roster_path.exists():
        raise RuntimeError(f"Missing roster_map.csv required for IAEL validation: {roster_path}")

    # Build lookup: player_norm -> team_abbr
    roster_lookup: dict[str, str] = {}
    with roster_path.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        cols = [c.lower() for c in (rdr.fieldnames or [])]

        # best-effort column pick (no guessing later)
        player_col = None
        for cand in ("player", "player_name", "name"):
            if cand in cols and rdr.fieldnames is not None:
                player_col = rdr.fieldnames[cols.index(cand)]
                break

        team_col = None
        for cand in ("team", "team_abbr", "team_u"):
            if cand in cols and rdr.fieldnames is not None:
                team_col = rdr.fieldnames[cols.index(cand)]
                break

        if not player_col or not team_col:
            raise RuntimeError(f"roster_map.csv missing required columns. Found={rdr.fieldnames}")

        for r in rdr:
            p = (r.get(player_col) or "").strip()
            t = (r.get(team_col) or "").strip().upper()
            if not p or not t:
                continue
            k = normalize_person_name(p).lower()
            # prefer first seen; deterministic
            roster_lookup.setdefault(k, t)
        
        # Optional scope-down: only enforce mismatches for teams on the current actionable slate.
        # fetch_board.csv is already strict-gated upstream to today CT + not started yet.
        active_teams: set[str] = set()
        fetch_board_path = root / "data" / "board" / "fetch_board.csv"
        if fetch_board_path.exists():
            try:
                with fetch_board_path.open("r", encoding="utf-8", newline="") as f:
                    rdr = csv.DictReader(f)
                    cols = [c.lower() for c in (rdr.fieldnames or [])]

                    team_col = None
                    for cand in ("team", "team_abbr", "team_u"):
                        if cand in cols and rdr.fieldnames is not None:
                            team_col = rdr.fieldnames[cols.index(cand)]
                            break

                    opp_col = None
                    for cand in ("opp", "opponent"):
                        if cand in cols and rdr.fieldnames is not None:
                            opp_col = rdr.fieldnames[cols.index(cand)]
                            break

                    home_col = None
                    for cand in ("home",):
                        if cand in cols and rdr.fieldnames is not None:
                            home_col = rdr.fieldnames[cols.index(cand)]
                            break

                    for r in rdr:
                        for col in (team_col, opp_col, home_col):
                            if not col:
                                continue
                            v = (r.get(col) or "").strip().upper()
                            if len(v) == 3 and v.isalpha():
                                active_teams.add(v)

                if active_teams:
                    print(f"[IAEL] Team mismatch scope limited to active fetch_board teams: {sorted(active_teams)}")
                else:
                    print("[IAEL] fetch_board.csv found but no active teams parsed; mismatch audit will use full IAEL universe.")
            except Exception as e:
                print(f"[IAEL][WARN] Could not parse fetch_board.csv for mismatch scoping: {e}", file=sys.stderr)
    
    # Check mismatches (known players only)
    mismatches = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        p_raw = (r.get("player") or "").strip()
        team_raw = (r.get("team") or "").strip()
        if not p_raw or not team_raw:
            continue

        p_k = normalize_person_name(p_raw).lower()
        roster_team = roster_lookup.get(p_k)
        if not roster_team:
            # Unknown player -> IGNORE (two-way / 10-day / stale roster map)
            continue

        iael_team = _team_to_abbr(team_raw).strip().upper()

        # If fetch_board exists, only enforce mismatches for teams still on the actionable slate.
        if active_teams and iael_team not in active_teams:
            continue

        if iael_team and roster_team and iael_team != roster_team:
            mismatches.append(
                {
                    "player": p_raw,
                    "player_norm": p_k,
                    "status": (r.get("status") or "").strip(),
                    "iael_team_raw": team_raw,
                    "iael_team": iael_team,
                    "roster_team": roster_team,
                    "reason": (r.get("reason") or "").strip(),
                }
            )

    if not mismatches:
        return

    # Write audit report
    diag_dir = root / ".atlas_audit" / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    ts = _local_now().strftime("%Y%m%d_%H%M%S")
    out = diag_dir / f"iael_team_mismatches_{ts}.csv"

    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["player", "player_norm", "status", "iael_team_raw", "iael_team", "roster_team", "reason"],
        )
        w.writeheader()
        for m in mismatches:
            w.writerow(m)

    # Print short summary then HARD STOP
    print(f"[IAEL][FAIL] TEAM MISMATCHES found: {len(mismatches)}. Audit: {out}", file=sys.stderr)
    for m in mismatches[:10]:
        print(
            f"  - {m['player']} status={m['status']} iael={m['iael_team']} roster={m['roster_team']} (raw_team={m['iael_team_raw']})",
            file=sys.stderr,
        )

    raise RuntimeError(f"IAEL TEAM MISMATCHES: {len(mismatches)} (see {out})")


def _sync_roster_map_from_latest_norm(root: Path, latest_norm: Path) -> int:
    """
    Update data/input/roster_map.csv from the current IAEL normalized rows.

    This preserves the existing player strings in roster_map.csv and only updates
    teams for normalized player-name matches. It is intentionally narrow so it can
    correct stale active-player team labels without introducing naming drift.
    """
    roster_path = root / "data" / "input" / "roster_map.csv"
    if not roster_path.exists() or not latest_norm.exists():
        return 0

    # Ensure Atlas imports resolve when the tool is run directly.
    src_dir = root / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))

    from Atlas.core.iael_filter import normalize_person_name
    from Atlas.engine.new_probability import _team_to_abbr

    try:
        data = json.loads(latest_norm.read_text(encoding="utf-8"))
    except Exception:
        return 0

    rows = data if isinstance(data, list) else data.get("rows", [])
    if not isinstance(rows, list) or not rows:
        return 0

    try:
        roster_df = pd.read_csv(roster_path)
    except Exception:
        return 0

    if "player" not in roster_df.columns or "team" not in roster_df.columns:
        return 0

    roster_df = roster_df.copy()
    roster_df["player"] = roster_df["player"].astype(str).str.strip()
    roster_df["team"] = roster_df["team"].astype(str).str.strip()
    roster_df["player_norm"] = roster_df["player"].apply(normalize_person_name)

    updates: list[dict[str, str]] = []
    updated_rows = 0

    for r in rows:
        if not isinstance(r, dict):
            continue

        p_raw = (r.get("player") or "").strip()
        team_raw = (r.get("team") or "").strip()
        if not p_raw or not team_raw:
            continue

        p_norm = normalize_person_name(p_raw)
        iael_team = _team_to_abbr(team_raw).strip().upper()
        if not p_norm or not iael_team:
            continue

        mask = roster_df["player_norm"].astype(str).eq(p_norm)
        if not bool(mask.any()):
            continue

        current_teams = roster_df.loc[mask, "team"].astype(str).str.strip()
        if bool((current_teams == iael_team).all()):
            continue

        before_players = roster_df.loc[mask, "player"].astype(str).tolist()
        before_teams = roster_df.loc[mask, "team"].astype(str).tolist()

        roster_df.loc[mask, "team"] = iael_team
        updated_rows += int(mask.sum())

        for player_str, old_team in zip(before_players, before_teams):
            updates.append(
                {
                    "player": player_str,
                    "player_norm": p_norm,
                    "old_team": old_team,
                    "new_team": iael_team,
                    "iael_team_raw": team_raw,
                    "reason": (r.get("reason") or "").strip(),
                }
            )

    if updated_rows <= 0:
        return 0

    roster_df.drop(columns=["player_norm"], inplace=True)
    roster_df.to_csv(roster_path, index=False)

    diag_dir = root / ".atlas_audit" / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    ts = _local_now().strftime("%Y%m%d_%H%M%S")
    audit_path = diag_dir / f"roster_map_iael_sync_{ts}.csv"
    try:
        pd.DataFrame(updates).to_csv(audit_path, index=False)
        print(f"[IAEL] Synced roster_map.csv from latest IAEL: {updated_rows} row updates. Audit: {audit_path}")
    except Exception:
        print(f"[IAEL] Synced roster_map.csv from latest IAEL: {updated_rows} row updates.")

    return updated_rows

def _pulled_at_local_from_normalized(latest_norm: Path) -> datetime:
    """
    Determine pulled_at (local naive datetime) from the normalized JSON.
    Priority of JSON keys: pulled_at_ct, pulled_at_local, pulled_at.
    If the key is missing or parsing fails, fall back to the file mtime.
    """
    # mtime fallback (naive local)
    def mtime_dt() -> datetime:
        try:
            return datetime.fromtimestamp(latest_norm.stat().st_mtime)
        except Exception:
            return _local_now()

    try:
        data = json.loads(latest_norm.read_text(encoding="utf-8"))
    except Exception:
        return mtime_dt()

    if not isinstance(data, dict):
        return mtime_dt()

    for key in ("pulled_at_ct", "pulled_at_local", "pulled_at"):
        val = data.get(key)
        if not val:
            continue
        try:
            dt = datetime.fromisoformat(val)
            # convert tz-aware to local naive, leave naive as-is
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            # parsing failed — try next key, but ultimately fallback to mtime
            continue

    return mtime_dt()

def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def today_yyyy_mm_dd() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def find_injury_pipeline(root: Path) -> Path | None:
    candidates = [
        root / "scripts" / "dev" / "adhoc" / "injury" / "injury_pull_and_parse.py",
        root / "tools" / "injury_pull_and_parse.py",
        root / "scripts" / "injury_pull_and_parse.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def ensure_invalidations(root: Path) -> Path:
    out = root / "data" / "output" / "dashboard" / "invalidations_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_text("[]", encoding="utf-8")
    return out


def load_status(root: Path) -> tuple[Path, dict]:
    p = root / "data" / "output" / "dashboard" / "status_latest.json"
    if not p.exists():
        raise RuntimeError(f"IAEL status file not found: {p}")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Could not parse IAEL status_latest.json: {e}") from e
    if not isinstance(obj, dict):
        raise RuntimeError("status_latest.json must be a JSON object")
    return p, obj


def write_status(path: Path, obj: dict) -> None:
    # Preserve stable formatting
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _publish_latest_from_newest(root: Path) -> Path | None:
    """
    Publish newest snapshot *.json (excluding latest.json) to norm_dir/latest.json.
    Returns the published latest.json Path or None if no snapshots found.
    Prints chosen filename or a message when none found.
    """
    norm_dir = root / "data" / "output" / "injury" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    latest_path = norm_dir / "latest.json"
    cands = [p for p in norm_dir.glob("*.json") if p.name != "latest.json"]
    if not cands:
        print("[IAEL] No normalized snapshots found to publish as latest.json")
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    src = cands[0]
    latest_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[IAEL] Published latest.json <- {src.name}")
    return latest_path


def main() -> int:
    root = repo_root()

    # 1) Run injury pipeline if available
    pipe = find_injury_pipeline(root)
    if pipe is not None:
        print(f"[IAEL] Running injury pipeline: {pipe}")
        rc = subprocess.run([sys.executable, str(pipe)], cwd=str(root)).returncode
        if rc != 0:
            print(f"[IAEL][WARN] injury pipeline returned ExitCode={rc}. Continuing to validate status files.", file=sys.stderr)
    else:
        print("[IAEL][WARN] No injury pipeline script found. Will only validate/repair status fields.", file=sys.stderr)

    _publish_latest_from_newest(root)
    latest_norm = root / "data" / "output" / "injury" / "normalized" / "latest.json"
    if latest_norm.exists():
        _sync_roster_map_from_latest_norm(root, latest_norm)
        try:
            _assert_no_team_mismatches(root, latest_norm)

        except Exception as e:
            print(f"[IAEL][WARN] Team mismatch audit failed pre-fetch: {e}", file=sys.stderr)
    
    # STRICT freshness gate: 10am–10pm must have IAEL refreshed within last 30 minutes
    now = _local_now()
    if _is_enforced_window(now):
        latest_norm = root / "data" / "output" / "injury" / "normalized" / "latest.json"
        if not latest_norm.exists():
            print(f"[IAEL][FAIL] Missing normalized latest.json: {latest_norm}", file=sys.stderr)
            return 2

        # Use the normalized JSON (or mtime fallback) to determine when it was pulled.
        pulled_at = _pulled_at_local_from_normalized(latest_norm)
        age = now - pulled_at

        if age > timedelta(minutes=30):
            mins = age.total_seconds() / 60.0
            print(f"[IAEL][FAIL] IAEL stale: age={mins:.1f} min (>30 min) during enforced window. latest={latest_norm}", file=sys.stderr)
            return 2
        else:
            mins = age.total_seconds() / 60.0
            print(f"[IAEL] Freshness OK: age={mins:.1f} min (<=30) during enforced window.")
    else:
        print("[IAEL] Freshness gate not enforced (outside 10am–10pm).")
    # 2) Ensure invalidations exists (even if empty)
    inv = ensure_invalidations(root)
    print(f"[IAEL] invalidations_latest.json: {inv}")

    # 3) Ensure status has report_date when not in dead_period
    status_path, st = load_status(root)

    dead_period = bool(st.get("dead_period", False))
    if dead_period:
        # In dead period, report_date may be intentionally absent.
        print("[IAEL] dead_period=true; leaving report_date as-is.")
        write_status(status_path, st)
        return 0

    rep = str(st.get("report_date") or "").strip()
    if not rep:
        st["report_date"] = today_yyyy_mm_dd()
        st["generated_at"] = datetime.now().isoformat(timespec="seconds")
        write_status(status_path, st)
        print(f"[IAEL] Filled missing report_date with today={st['report_date']}")
    else:
        print(f"[IAEL] report_date already present: {rep}")

    # Ensure normalized/latest.json always reflects the newest snapshot (idempotent)
    _publish_latest_from_newest(root)

    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[IAEL][FATAL] {e}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:
    ZoneInfo = None  # type: ignore


CHI_TZ = "America/Chicago"

# Keep EXACT legacy schema
STORE_COLUMNS = [
    "game_date", "player", "team", "opp",
    "minutes", "pts", "reb", "ast",
    "fg3m", "fga", "fta", "tov",
    "usg_proxy",
]

TELEM_COLUMNS = ["date", "games_logged", "status", "error", "written_at"]

Row = Dict[str, object]


def chi_today() -> date:
    if ZoneInfo is None:
        return datetime.now().date()
    return datetime.now(ZoneInfo(CHI_TZ)).date()


def parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_m_d_yyyy(d: date) -> str:
    # matches legacy style like 2/7/2026 (no leading zeros)
    return f"{d.month}/{d.day}/{d.year}"


def default_repo_root() -> Path:
    # tools/refresh_nba_gamelogs.py -> repo root is parent of tools
    return Path(__file__).resolve().parents[1]


def atomic_write_csv(path: Path, fieldnames: List[str], rows: List[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    tmp.replace(path)


def read_csv_rows(path: Path) -> Tuple[List[str], List[Row]]:
    if not path.exists():
        return ([], [])
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows: List[Row] = []
        for row in r:
            rows.append(dict(row))  # type: ignore[arg-type]
        return (list(r.fieldnames or []), rows)


def http_get_json(url: str, timeout_sec: int) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def retry_get_json(url: str, timeout_sec: int, retries: int, backoff_sec: float) -> dict:
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return http_get_json(url, timeout_sec=timeout_sec)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff_sec * (2 ** attempt))
    assert last_err is not None
    raise last_err


@dataclass
class Telemetry:
    games_logged: Optional[int]
    status: str
    error: str


def write_telemetry(telemetry_dir: Path, target: date, telemetry: Telemetry) -> Path:
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    out = telemetry_dir / f"{target.strftime('%Y-%m-%d')}_games_logged.csv"

    row: Row = {
        "date": target.strftime("%Y-%m-%d"),
        "games_logged": "" if telemetry.games_logged is None else int(telemetry.games_logged),
        "status": telemetry.status,
        "error": telemetry.error,
        "written_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    atomic_write_csv(out, TELEM_COLUMNS, [row])
    return out


def espn_scoreboard_event_ids(target: date, timeout_sec: int, retries: int, backoff_sec: float) -> List[str]:
    # ✅ working endpoint you validated
    yyyymmdd = target.strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={yyyymmdd}"
    data = retry_get_json(url, timeout_sec=timeout_sec, retries=retries, backoff_sec=backoff_sec)

    events = data.get("events", []) or []
    out: List[str] = []
    for ev in events:
        eid = ev.get("id")
        if eid:
            out.append(str(eid))
    return out


def _parse_made_attempt(s: str) -> Tuple[int, int]:
    # "7-14" -> (7, 14)
    try:
        made_s, att_s = s.split("-")
        return int(made_s), int(att_s)
    except Exception:
        return (0, 0)


def _parse_minutes(s: str) -> int:
    # ESPN may give "22" or "22:13"
    if not s:
        return 0
    try:
        if ":" in s:
            return int(s.split(":")[0])
        return int(s)
    except Exception:
        return 0


def espn_game_player_rows(event_id: str, target: date, timeout_sec: int, retries: int, backoff_sec: float) -> List[Row]:
    """
    Uses ESPN summary endpoint. Converts to legacy per-player gamelog schema.
    Keeps DNP rows if present (minutes may be 0).
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}"
    data = retry_get_json(url, timeout_sec=timeout_sec, retries=retries, backoff_sec=backoff_sec)

    # Regular season only (your requirement)
    # ESPN metadata varies; safest is to check "header.competitions[].type.abbreviation" or similar
    # We'll do a soft filter: if seasonType exists and isn't "2" (regular), skip.
    # If we can't detect it, we keep it (best-effort).
    try:
        competitions = (((data.get("header") or {}).get("competitions") or [])[:1])
        if competitions:
            comp = competitions[0]
            season_type = (((comp.get("type") or {}).get("id")) or "")
            # ESPN commonly: 1=preseason, 2=regular, 3=postseason
            if str(season_type) not in ("", "2"):
                return []
    except Exception:
        pass

    boxscore = data.get("boxscore", {}) or {}
    players = boxscore.get("players", []) or []
    if len(players) < 2:
        return []

    # Each entry corresponds to a team
    team_entries: List[Tuple[str, dict]] = []
    for p in players:
        team = (p.get("team") or {})
        abbr = team.get("abbreviation") or team.get("shortDisplayName") or ""
        stats_blocks = p.get("statistics", []) or []
        if not abbr or not stats_blocks:
            continue

        chosen = None
        for blk in stats_blocks:
            if blk.get("athletes") and blk.get("labels"):
                chosen = blk
                break
        if chosen is None:
            continue
        team_entries.append((str(abbr), chosen))

    if len(team_entries) < 2:
        return []

    date_str = fmt_m_d_yyyy(target)
    rows: List[Row] = []

    for idx, (team_abbr, blk) in enumerate(team_entries[:2]):
        opp_abbr = team_entries[1 - idx][0]

        labels: List[str] = [str(x) for x in (blk.get("labels") or [])]
        athletes = blk.get("athletes") or []

        def label_index(name: str) -> int:
            try:
                return labels.index(name)
            except ValueError:
                return -1

        i_min = label_index("MIN")
        i_fg = label_index("FG")
        i_3pt = label_index("3PT")
        i_ft = label_index("FT")
        i_reb = label_index("REB")
        i_ast = label_index("AST")
        i_to = label_index("TO")
        i_pts = label_index("PTS")

        for a in athletes:
            athlete = a.get("athlete") or {}
            player_name = athlete.get("displayName") or athlete.get("shortName") or athlete.get("fullName") or ""
            stat_list = a.get("stats") or []
            if not player_name or not stat_list:
                continue

            def get_stat(i: int) -> str:
                if i < 0 or i >= len(stat_list):
                    return ""
                v = stat_list[i]
                return "" if v is None else str(v)

            min_s = get_stat(i_min)
            fg_s = get_stat(i_fg)
            pt3_s = get_stat(i_3pt)
            ft_s = get_stat(i_ft)
            reb_s = get_stat(i_reb)
            ast_s = get_stat(i_ast)
            to_s = get_stat(i_to)
            pts_s = get_stat(i_pts)

            minutes = _parse_minutes(min_s)
            _, fg_a = _parse_made_attempt(fg_s)
            pt3_m, _ = _parse_made_attempt(pt3_s)
            _, ft_a = _parse_made_attempt(ft_s)

            def to_int(s: str) -> int:
                try:
                    return int(s) if s != "" else 0
                except Exception:
                    return 0

            pts = to_int(pts_s)
            reb = to_int(reb_s)
            ast = to_int(ast_s)
            tov = to_int(to_s)

            fga = fg_a
            fta = ft_a
            fg3m = pt3_m

            usg_proxy = 0.0
            if minutes > 0:
                usg_proxy = (float(fga) + 0.44 * float(fta) + float(tov)) / float(minutes)

            rows.append({
                "game_date": date_str,
                "player": player_name,
                "team": team_abbr,
                "opp": opp_abbr,
                "minutes": minutes,
                "pts": pts,
                "reb": reb,
                "ast": ast,
                "fg3m": fg3m,
                "fga": fga,
                "fta": fta,
                "tov": tov,
                "usg_proxy": round(usg_proxy, 6),
            })

    return rows


def upsert_day_rows(existing_rows: List[Row], target: date, new_rows: List[Row]) -> List[Row]:
    """
    Remove all rows for target date (legacy format), then append new rows.
    """
    target_str = fmt_m_d_yyyy(target)
    kept: List[Row] = []
    for r in existing_rows:
        if str(r.get("game_date", "")).strip() != target_str:
            kept.append(r)
    kept.extend(new_rows)
    return kept


def normalize_to_store_schema(rows: List[Row]) -> List[Row]:
    normalized: List[Row] = []
    for r in rows:
        normalized.append({k: r.get(k, "") for k in STORE_COLUMNS})
    return normalized


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=str, default="")
    ap.add_argument("--gamelog-path", type=str, default="data/gamelogs/nba_gamelogs.csv")
    ap.add_argument("--telemetry-dir", type=str, default="data/telemetry/games_logged")

    # Yesterday only by default (go-live mode)
    ap.add_argument("--days-back", type=int, default=1)
    ap.add_argument("--target-date", type=str, default="")

    ap.add_argument("--timeout-sec", type=int, default=15)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--backoff-sec", type=float, default=1.0)

    # orchestrator compatibility
    ap.add_argument("--chunk-days", type=int, default=1)
    ap.add_argument("--run-id", type=str, default="", help="optional run identifier (ignored by logic)")

    # ✅ go-live switch: wipe old history and begin at yesterday
    ap.add_argument("--start-fresh", action="store_true", help="overwrite store with only the target day's rows")

    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else default_repo_root()
    gamelog_path = (repo_root / args.gamelog_path).resolve()
    telemetry_dir = (repo_root / args.telemetry_dir).resolve()

    target = parse_yyyy_mm_dd(args.target_date) if args.target_date else (chi_today() - timedelta(days=int(args.days_back)))

    if args.run_id:
        print(f"[refresh_nba_gamelogs] INFO: run_id={args.run_id}", file=sys.stderr)
    print(f"[refresh_nba_gamelogs] INFO: target_date={target} store={gamelog_path} start_fresh={args.start_fresh}", file=sys.stderr)

    # 1) scoreboard (fast)
    try:
        event_ids = espn_scoreboard_event_ids(
            target,
            timeout_sec=int(args.timeout_sec),
            retries=int(args.retries),
            backoff_sec=float(args.backoff_sec),
        )
    except Exception as e:
        telem = Telemetry(games_logged=None, status="error", error=f"espn_scoreboard_failed: {type(e).__name__}: {e}")
        try:
            out = write_telemetry(telemetry_dir, target, telem)
            print(f"[refresh_nba_gamelogs] WARN: wrote telemetry {out} status=error", file=sys.stderr)
        except Exception as te:
            print(f"[refresh_nba_gamelogs] WARN: telemetry write failed: {type(te).__name__}: {te}", file=sys.stderr)
        return 0  # best-effort

    games_count = len(event_ids)

    # 2) parse player rows per game
    all_rows: List[Row] = []
    per_game_errors: List[str] = []

    for eid in event_ids:
        try:
            rows = espn_game_player_rows(
                eid,
                target,
                timeout_sec=int(args.timeout_sec),
                retries=int(args.retries),
                backoff_sec=float(args.backoff_sec),
            )
            all_rows.extend(rows)
        except Exception as e:
            per_game_errors.append(f"event={eid} {type(e).__name__}: {e}")

    # 3) telemetry ALWAYS
    status = "ok"
    err = ""
    if per_game_errors:
        status = "ok_partial"
        err = "; ".join(per_game_errors[:3])
        if len(per_game_errors) > 3:
            err += f"; (+{len(per_game_errors)-3} more)"
    try:
        out = write_telemetry(telemetry_dir, target, Telemetry(games_logged=games_count, status=status, error=err))
        print(f"[refresh_nba_gamelogs] INFO: wrote telemetry {out} games_logged={games_count} status={status}", file=sys.stderr)
    except Exception as e:
        print(f"[refresh_nba_gamelogs] WARN: telemetry write failed: {type(e).__name__}: {e}", file=sys.stderr)

    # If no games, we’re done (telemetry already says 0)
    if games_count == 0:
        print(f"[refresh_nba_gamelogs] INFO: no games on {target}; store unchanged.", file=sys.stderr)
        return 0

    # If games exist but we parsed no rows, do not touch store
    if not all_rows:
        print(f"[refresh_nba_gamelogs] WARN: games exist but no player rows parsed for {target}; store unchanged.", file=sys.stderr)
        return 0

    # 4) store write (legacy schema)
    try:
        if args.start_fresh:
            final_rows = normalize_to_store_schema(all_rows)
        else:
            _, existing_rows = read_csv_rows(gamelog_path)
            updated = upsert_day_rows(existing_rows, target, all_rows)
            final_rows = normalize_to_store_schema(updated)

        atomic_write_csv(gamelog_path, STORE_COLUMNS, final_rows)
        print(f"[refresh_nba_gamelogs] INFO: wrote store rows_for_day={len(all_rows)} total_rows={len(final_rows)}", file=sys.stderr)
    except Exception as e:
        print(f"[refresh_nba_gamelogs] WARN: failed to write store: {type(e).__name__}: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
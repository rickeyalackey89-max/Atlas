"""
Build cloudflare_payload.json from slip CSVs.

Called after run_publish_stage to create the dashboard payload.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
import csv as _csv_module
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from Atlas.core.prizepicks_quote import quote_prizepicks_payout


def _norm_name(name: str) -> str:
    """Strip diacritics for fuzzy name matching (e.g. Schröder -> Schroder)."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").strip()


def _repo_root() -> Path:
    """Return the Atlas workspace root (two levels above src/Atlas/stages/publish/)."""
    return Path(__file__).resolve().parents[4]


def _sanitize(obj):
    """Recursively replace NaN/Inf floats with None so json.dumps produces valid JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj

def _compute_performance_stats(repo_root: Path) -> dict:
    """Aggregate hit rates from recent eval_legs across live_runs telemetry."""
    from datetime import timedelta, timezone
    live_runs_dir = repo_root / "data" / "telemetry" / "live_runs"
    if not live_runs_dir.exists():
        return {}

    seen: set = set()
    rows: list = []
    eval_files = sorted(live_runs_dir.rglob("eval_legs.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for fpath in eval_files:
        try:
            with open(fpath, newline="", encoding="utf-8", errors="replace") as f:
                reader = _csv_module.DictReader(f)
                for row in reader:
                    hit_val = row.get("hit", "")
                    if hit_val not in ("0", "1", "0.0", "1.0"):
                        continue
                    game_date = (row.get("game_date") or "")[:10]
                    key = (
                        game_date,
                        (row.get("player") or "").strip(),
                        (row.get("stat") or "").strip(),
                        str(row.get("line") or "").strip(),
                        (row.get("direction") or "").strip().upper(),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        gd = datetime.strptime(game_date, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    try:
                        p_cal = float(row.get("p_cal") or "")
                        if not math.isfinite(p_cal):
                            p_cal = 0.5
                    except (ValueError, TypeError):
                        p_cal = 0.5
                    rows.append({
                        "game_date": gd,
                        "tier": (row.get("tier") or "").upper(),
                        "p_cal": p_cal,
                        "hit": int(float(hit_val)),
                    })
        except Exception:
            continue

    if not rows:
        return {}

    latest_game_date = max(r["game_date"] for r in rows)
    cutoff_7d = latest_game_date - timedelta(days=6)
    cutoff_30d = latest_game_date - timedelta(days=29)

    def _stats(subset: list) -> dict:
        if not subset:
            return {"n": 0, "hits": 0, "hit_rate": None, "brier": None}
        n = len(subset)
        hits = sum(r["hit"] for r in subset)
        brier = round(sum((r["p_cal"] - r["hit"]) ** 2 for r in subset) / n, 4)
        return {"n": n, "hits": hits, "hit_rate": round(hits / n, 4), "brier": brier}

    rows_7d = [r for r in rows if r["game_date"] >= cutoff_7d]
    rows_30d = [r for r in rows if r["game_date"] >= cutoff_30d]

    result: dict = {
        "overall": {"last_7d": _stats(rows_7d), "last_30d": _stats(rows_30d)},
        "by_tier": {},
        "meta": {
            "source": "data/telemetry/live_runs/**/eval_legs.csv",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "latest_game_date": latest_game_date.isoformat(),
            "window_7d": {"start": cutoff_7d.isoformat(), "end": latest_game_date.isoformat()},
            "window_30d": {"start": cutoff_30d.isoformat(), "end": latest_game_date.isoformat()},
            "eval_files": len(eval_files),
            "unique_scored_legs": len(rows),
        },
    }
    for tier in ("GOBLIN", "STANDARD", "DEMON"):
        result["by_tier"][tier] = {
            "last_7d": _stats([r for r in rows_7d if r["tier"] == tier]),
            "last_30d": _stats([r for r in rows_30d if r["tier"] == tier]),
        }
    return result


def _compute_yesterday_slip_record(repo_root: Path) -> dict:
    """Score yesterday's slips by family (Market, System, Windfall).

    Rules:
    - Weekend game dates use the run closest to 2:30 PM.
    - Weekday game dates use the run closest to 5:30 PM.
    - ATLAS_YESTERDAY_REPORT_RUN can override the selected run.
    - A leg with no truth in eval_legs (DNP / not scored) voids the entire slip —
      the slip is excluded from wins AND total (not counted as a loss).
    - Returns per-family win/total plus an aggregate.
    """
    import os as _os
    import re as _re
    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    yesterday_str = yesterday.isoformat()
    prefix = yesterday_str.replace("-", "")
    runs_dir = repo_root / "data" / "output" / "runs"
    if not runs_dir.exists():
        return {}
    run_name_re = _re.compile(r"^(\d{8})_(\d{6})")
    run_dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith(prefix) and run_name_re.match(d.name)],
        key=lambda d: d.name,
    )
    if not run_dirs:
        return {}

    def _run_seconds(run_dir: Path) -> int | None:
        try:
            m = run_name_re.match(run_dir.name)
            if not m:
                return None
            hhmmss = m.group(2)
            return int(hhmmss[:2]) * 3600 + int(hhmmss[2:4]) * 60 + int(hhmmss[4:6])
        except Exception:
            return None

    def _target_seconds(game_date: date) -> int:
        # Saturday/Sunday: 2:30 PM report. Monday-Friday: 5:30 PM report.
        return (14 * 3600 + 30 * 60) if game_date.weekday() >= 5 else (17 * 3600 + 30 * 60)

    def _resolve_run_ref(ref: str) -> Path | None:
        """Resolve a published/env run id to a concrete run directory.

        Dashboard payloads often store the base timestamp (YYYYMMDD_HHMMSS)
        while the actual folder may carry an operational suffix such as
        *_single_slate. Prefer exact folders, then unique timestamp-prefix
        matches with eval output.
        """
        ref = str(ref or "").strip()
        if not ref:
            return None
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = runs_dir / ref
        if candidate.is_dir() and candidate.name.startswith(prefix) and _run_seconds(candidate) is not None:
            return candidate

        ref_name = Path(ref).name
        matches = [
            d for d in run_dirs
            if d.name == ref_name or d.name.startswith(ref_name) or ref_name.startswith(d.name[:15])
        ]
        if not matches:
            return None
        matches.sort(key=lambda d: ((d / "eval_slips.csv").exists(), (d / "eval_legs.csv").exists(), d.stat().st_mtime), reverse=True)
        return matches[0]

    def _published_report_run() -> Path | None:
        payload_path = repo_root / "data" / "output" / "dashboard" / "cloudflare_payload.json"
        if not payload_path.exists():
            return None
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        published_id = str(payload.get("run_id") or "").strip()
        if not published_id.startswith(prefix):
            return None
        return _resolve_run_ref(published_id)

    report_run: Path | None = _published_report_run()
    configured_report_run = _os.environ.get("ATLAS_YESTERDAY_REPORT_RUN", "").strip()
    if report_run is None and configured_report_run:
        report_run = _resolve_run_ref(configured_report_run)

    if report_run is None:
        target = _target_seconds(yesterday)
        report_run = min(
            run_dirs,
            key=lambda d: (
                abs((_run_seconds(d) or 0) - target),
                (_run_seconds(d) or 0) > target,
                _run_seconds(d) or 0,
            ),
        )

    def _score_eval_slips() -> dict | None:
        """Use the explicit slip eval artifact when present.

        This is the authoritative source because it matches the run's actual
        generated slip files, family labels, void handling, and evaluated leg
        truth. Manual rescoring remains below as a fallback for older runs.
        """
        ep = report_run / "eval_slips.csv"
        if not ep.exists():
            return None
        family_map = {
            "market": "market",
            "marketed": "market",
            "system": "system",
            "windfall": "windfall",
        }
        buckets = {
            "market": {"wins": 0, "total": 0},
            "system": {"wins": 0, "total": 0},
            "windfall": {"wins": 0, "total": 0},
        }
        try:
            with open(ep, newline="", encoding="utf-8", errors="replace") as f:
                for row in _csv_module.DictReader(f):
                    family_key = family_map.get(str(row.get("family") or "").strip().lower())
                    if family_key is None:
                        continue
                    status = str(row.get("status") or "").strip().lower()
                    if status in {"void", "dnp", "no_truth", "pending", ""}:
                        continue
                    if status not in {"win", "loss"}:
                        all_hit = str(row.get("all_hit") or "").strip().lower()
                        status = "win" if all_hit in {"1", "1.0", "true", "yes"} else "loss"
                    buckets[family_key]["total"] += 1
                    if status == "win":
                        buckets[family_key]["wins"] += 1
        except Exception:
            return None

        agg_wins = sum(v["wins"] for v in buckets.values())
        agg_total = sum(v["total"] for v in buckets.values())
        if agg_total == 0:
            return None
        return {
            "date": yesterday_str,
            "run_id": report_run.name,
            "wins": agg_wins,
            "total": agg_total,
            "pct": round(agg_wins / agg_total, 4),
            "market": {**buckets["market"], "pct": round(buckets["market"]["wins"] / buckets["market"]["total"], 4) if buckets["market"]["total"] else 0},
            "system": {**buckets["system"], "pct": round(buckets["system"]["wins"] / buckets["system"]["total"], 4) if buckets["system"]["total"] else 0},
            "windfall": {**buckets["windfall"], "pct": round(buckets["windfall"]["wins"] / buckets["windfall"]["total"], 4) if buckets["windfall"]["total"] else 0},
        }

    eval_slips_record = _score_eval_slips()
    if eval_slips_record is not None:
        return eval_slips_record

    # Build hit lookup from eval_legs of that run only
    # key: (player, stat, line, direction) -> 0 or 1
    # Missing key = DNP / no truth
    hit_lookup: dict = {}
    el = report_run / "eval_legs.csv"
    if el.exists():
        try:
            with open(el, newline="", encoding="utf-8", errors="replace") as f:
                for row in _csv_module.DictReader(f):
                    hit_val = row.get("hit", "")
                    if hit_val not in ("0", "1", "0.0", "1.0"):
                        continue
                    key = (
                        row.get("player", "").strip(),
                        row.get("stat", "").strip(),
                        row.get("line", "").strip(),
                        (row.get("direction") or "").upper(),
                    )
                    if key not in hit_lookup:
                        hit_lookup[key] = int(float(hit_val))
        except Exception:
            pass

    def _score_legs(leg_keys: list) -> str:
        """Return 'win', 'loss', or 'void' for a list of (player,stat,line,dir) tuples."""
        for k in leg_keys:
            if k not in hit_lookup:
                return "void"  # any DNP voids the slip
        if all(hit_lookup[k] == 1 for k in leg_keys):
            return "win"
        return "loss"

    def _score_marketed() -> dict:
        """Score marketed_slips.csv — each slip_name (3-leg/4-leg/5-leg) is one slip."""
        mp = report_run / "marketed_slips.csv"
        wins, total = 0, 0
        if not mp.exists():
            return {"wins": wins, "total": total}
        try:
            slips: dict = {}
            with open(mp, newline="", encoding="utf-8", errors="replace") as f:
                for row in _csv_module.DictReader(f):
                    sn = (row.get("slip") or "").strip()
                    slips.setdefault(sn, []).append(row)
            for legs in slips.values():
                leg_keys = [
                    (leg.get("player", "").strip(), leg.get("stat", "").strip(),
                     leg.get("line", "").strip(), (leg.get("direction") or "").upper())
                    for leg in legs
                ]
                result = _score_legs(leg_keys)
                if result == "void":
                    continue
                total += 1
                if result == "win":
                    wins += 1
        except Exception:
            pass
        return {"wins": wins, "total": total}

    def _parse_leg_str(s: str):
        """Parse 'Player OVER STAT 7.5 (TIER) [id:...]' -> (player, stat, line, direction) or None."""
        m = _re.match(r'^(.+?)\s+(OVER|UNDER)\s+(\w+)\s+([\d.]+)', str(s).strip())
        if not m:
            return None
        return (m.group(1).strip(), m.group(3).strip(), m.group(4).strip(), m.group(2).upper())

    def _score_family_dir(family_dir: Path) -> dict:
        """Score recommended slip files for one family directory."""
        wins, total = 0, 0
        for n in [2, 3, 4, 5]:
            csv_path = family_dir / f"recommended_{n}leg.csv"
            if not csv_path.exists():
                continue
            try:
                with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
                    reader = _csv_module.DictReader(f)
                    rows_list = list(reader)
                if not rows_list:
                    continue
                row = rows_list[0]  # top-1 slip only
                leg_cols = sorted([c for c in row.keys() if _re.match(r'leg_\d+$', c)])
                leg_keys = []
                for lc in leg_cols:
                    parsed = _parse_leg_str(row.get(lc, ""))
                    if parsed:
                        leg_keys.append(parsed)
                if not leg_keys:
                    continue
                result = _score_legs(leg_keys)
                if result == "void":
                    continue
                total += 1
                if result == "win":
                    wins += 1
            except Exception:
                continue
        return {"wins": wins, "total": total}

    market = _score_marketed()
    system = _score_family_dir(report_run / "System")
    windfall = _score_family_dir(report_run / "Windfall")

    agg_wins = market["wins"] + system["wins"] + windfall["wins"]
    agg_total = market["total"] + system["total"] + windfall["total"]

    if agg_total == 0:
        return {}

    return {
        "date": yesterday_str,
        "run_id": report_run.name,
        "wins": agg_wins,
        "total": agg_total,
        "pct": round(agg_wins / agg_total, 4) if agg_total else 0,
        "market": {**market, "pct": round(market["wins"] / market["total"], 4) if market["total"] else 0},
        "system": {**system, "pct": round(system["wins"] / system["total"], 4) if system["total"] else 0},
        "windfall": {**windfall, "pct": round(windfall["wins"] / windfall["total"], 4) if windfall["total"] else 0},
    }



def _load_today_slate_teams(repo_root: Path) -> set:
    """Return the set of team abbreviations (upper) playing on today's slate."""
    try:
        board_path = repo_root / "data" / "board" / "today.csv"
        if not board_path.exists():
            return set()
        df = pd.read_csv(board_path, usecols=lambda c: c in {"team", "opp"})
        teams: set = set()
        for col in ("team", "opp"):
            if col in df.columns:
                teams.update(df[col].dropna().astype(str).str.upper().str.strip().tolist())
        return teams
    except Exception:
        return set()


def _load_injury_context(repo_root: Path) -> dict:
    """Load latest IAEL injury report for dashboard display, filtered to today's slate teams."""
    out: dict = {"invalidated_players": [], "questionable_players": [], "report_date": None, "report_label": None}

    # Only show injuries for teams actually playing today
    slate_teams = _load_today_slate_teams(repo_root)

    iael_path = repo_root / "data" / "output" / "dashboard" / "injury_invalidations_latest.json"
    if not iael_path.exists():
        return out
    try:
        with open(iael_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out["report_date"] = data.get("report_date")
        out["report_label"] = data.get("report_label")
        all_invalidated = data.get("invalidated_players", [])
        if slate_teams:
            out["invalidated_players"] = [
                p for p in all_invalidated
                if str(p.get("team", "")).upper().strip() in slate_teams
            ]
        else:
            out["invalidated_players"] = all_invalidated
    except Exception:
        pass

    # Pull QUESTIONABLE players from the normalized snapshot
    normalized_path = repo_root / "data" / "output" / "injury" / "normalized" / "latest.json"
    if normalized_path.exists():
        try:
            with open(normalized_path, "r", encoding="utf-8") as f:
                norm = json.load(f)
            for row in norm.get("rows", []):
                team_u = str(row.get("team", "")).upper().strip()
                if slate_teams and team_u not in slate_teams:
                    continue
                if (row.get("status", "").upper() == "QUESTIONABLE"
                        and not row.get("hard_invalid", False)):
                    out["questionable_players"].append({
                        "team": row.get("team", ""),
                        "player": row.get("player", ""),
                        "status": "QUESTIONABLE",
                        "reason": row.get("reason", ""),
                    })
        except Exception:
            pass
    return out


def _load_prizepicks_visual_assets(repo_root: Path, slate_date: str | None) -> dict:
    """Load player headshots and team logos from the matching PrizePicks raw board."""
    assets = {"players": {}, "teams": {}}
    raw_dir = repo_root / "data" / "raw"
    if not raw_dir.exists():
        return assets

    date_key = str(slate_date or "").replace("-", "")
    candidates = sorted(raw_dir.glob(f"prizepicks_{date_key}_*.json")) if date_key else []
    if not candidates:
        candidates = sorted(raw_dir.glob("prizepicks_*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return assets

    try:
        data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except Exception:
        return assets

    for item in data.get("included", []):
        item_type = item.get("type")
        attrs = item.get("attributes") or {}
        if item_type == "team":
            abbr = str(attrs.get("abbreviation") or "").upper().strip()
            if not abbr or "/" in abbr:
                continue
            assets["teams"][abbr] = {
                "logo_url": attrs.get("logo"),
                "team_name": attrs.get("name"),
                "market": attrs.get("market"),
                "primary_color": attrs.get("primary_color"),
                "secondary_color": attrs.get("secondary_color"),
            }
        elif item_type == "new_player":
            if attrs.get("combo"):
                continue
            name = str(attrs.get("display_name") or attrs.get("name") or "").strip()
            team = str(attrs.get("team") or "").upper().strip()
            if not name:
                continue
            payload = {
                "image_url": attrs.get("image_url"),
                "jersey_number": attrs.get("jersey_number"),
                "position": attrs.get("position"),
                "pp_player_id": item.get("id"),
            }
            norm = _norm_name(name).lower()
            assets["players"][(team, norm)] = payload
            assets["players"].setdefault(("", norm), payload)
    return assets


def _quote_prizepicks_payout(legs: list[dict], amount_bet_cents: int = 2500) -> dict | None:
    """Quote real PrizePicks adjusted payouts for a final slip via game_types."""
    return quote_prizepicks_payout(legs, amount_bet_cents=amount_bet_cents)


def _apply_prizepicks_quote_to_slip(slip: dict, legs: list[dict]) -> dict:
    quote = _quote_prizepicks_payout(legs)
    if not quote:
        slip["pp_quote_ok"] = False
        slip["pp_quote_status"] = "unquoted"
        slip["pp_payout_is_exact"] = False
        return slip

    power_mult = ((quote.get("power") or {}).get("all_correct"))
    flex_mult = ((quote.get("flex") or {}).get("all_correct"))
    chosen = quote.get("chosen") or {}
    chosen_mult = chosen.get("all_correct")
    if chosen_mult is None:
        chosen_mult = power_mult if power_mult is not None else flex_mult
    payout_is_exact = bool(chosen.get("payout_is_exact"))
    slip["pp_quote_ok"] = payout_is_exact
    slip["pp_quote_status"] = quote.get("quote_status") or ""
    slip["pp_payout_is_exact"] = payout_is_exact
    slip["pp_payout_quote_key"] = quote.get("quote_key") or ""
    slip["pp_payout_quote"] = quote
    slip["pp_power_payout_mult"] = power_mult
    slip["pp_flex_payout_mult"] = flex_mult
    if chosen_mult is not None:
        slip["payout_mult_fallback"] = slip.get("payout_mult")
        slip["payout_mult"] = float(chosen_mult)
        hit_prob = slip.get("hit_prob")
        try:
            hit_prob_f = float(hit_prob)
            ev = hit_prob_f * float(chosen_mult)
            slip["ev"] = ev
            slip["ev_mult"] = ev
        except Exception:
            pass
    return slip


def _build_stat_hub_payload(all_legs: list[dict], gamelogs_df: Optional["pd.DataFrame"], repo_root: Path) -> dict:
    """Build dashboard-ready team/player average blocks for today's slate."""
    out = {
        "teams": [],
        "playoff_active": False,
        "playoff_start": "2026-04-30",
        "slate_date": None,
        "source": "data/gamelogs/nba_gamelogs.csv",
    }
    if gamelogs_df is None or gamelogs_df.empty or not all_legs:
        return out

    slate_rows: dict[tuple[str, str], dict] = {}
    slate_dates: list[pd.Timestamp] = []
    for leg in all_legs:
        player = str(leg.get("player") or "").strip()
        team = str(leg.get("team") or "").strip().upper()
        if not player or not team:
            continue
        opp = str(leg.get("opp") or "").strip().upper()
        slate_rows.setdefault((team, _norm_name(player).lower()), {
            "player": player,
            "team": team,
            "opp": opp,
        })
        gd = pd.to_datetime(leg.get("game_date"), errors="coerce")
        if pd.notna(gd):
            slate_dates.append(gd)

    if not slate_rows:
        return out

    slate_date = max(slate_dates).normalize() if slate_dates else None
    if slate_date is not None:
        out["slate_date"] = slate_date.date().isoformat()

    playoff_start = pd.Timestamp(out["playoff_start"])
    playoff_active = bool(slate_date is not None and slate_date >= playoff_start)
    out["playoff_active"] = playoff_active
    visual_assets = _load_prizepicks_visual_assets(repo_root, out["slate_date"])

    logs = gamelogs_df.copy()
    if "game_date" not in logs.columns or "player" not in logs.columns:
        return out
    logs["game_date_dt"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs[logs["game_date_dt"].notna()].copy()
    if logs.empty:
        return out
    if slate_date is not None:
        logs = logs[logs["game_date_dt"] < slate_date].copy()
    if logs.empty:
        return out

    logs["player_norm"] = logs["player"].astype(str).map(lambda x: _norm_name(x).lower())
    if "team" in logs.columns:
        logs["team_norm"] = logs["team"].astype(str).str.upper().str.strip()
    else:
        logs["team_norm"] = ""
    if "opp" in logs.columns:
        logs["opp_norm"] = logs["opp"].astype(str).str.upper().str.strip()
    else:
        logs["opp_norm"] = ""

    avg_cols = ["minutes", "pts", "reb", "ast", "fg3m"]

    def _avg_block(frame: "pd.DataFrame") -> dict | None:
        if frame.empty:
            return None
        block: dict = {"gp": int(len(frame))}
        for col in avg_cols:
            if col not in frame.columns:
                block["min" if col == "minutes" else col] = None
                continue
            val = pd.to_numeric(frame[col], errors="coerce").mean()
            block["min" if col == "minutes" else col] = round(float(val), 1) if pd.notna(val) else None
        return block

    team_map: dict[str, dict] = {}
    for (team, player_norm), meta in slate_rows.items():
        player_logs = logs[(logs["player_norm"] == player_norm) & (logs["team_norm"] == team)]
        if player_logs.empty:
            player_logs = logs[logs["player_norm"] == player_norm]

        playoff_logs = player_logs[player_logs["game_date_dt"] >= playoff_start] if playoff_active else player_logs.iloc[0:0]
        opp = str(meta.get("opp") or "").upper().strip()
        series_logs = playoff_logs[playoff_logs["opp_norm"] == opp] if playoff_active and opp else playoff_logs.iloc[0:0]

        team_entry = team_map.setdefault(team, {"team": team, "opponents": set(), "players": []})
        if opp:
            team_entry["opponents"].add(opp)
        player_visual = (
            visual_assets["players"].get((team, player_norm))
            or visual_assets["players"].get(("", player_norm))
            or {}
        )
        team_entry["players"].append({
            "player": meta["player"],
            "image_url": player_visual.get("image_url"),
            "jersey_number": player_visual.get("jersey_number"),
            "position": player_visual.get("position"),
            "season": _avg_block(player_logs),
            "playoffs": _avg_block(playoff_logs) if playoff_active else None,
            "series": _avg_block(series_logs) if playoff_active else None,
        })

    teams = []
    for team, entry in sorted(team_map.items()):
        players = sorted(entry["players"], key=lambda p: str(p.get("player", "")))
        team_visual = visual_assets["teams"].get(team, {})
        teams.append({
            "team": team,
            "team_name": team_visual.get("team_name"),
            "market": team_visual.get("market"),
            "logo_url": team_visual.get("logo_url"),
            "opponents": sorted(entry["opponents"]),
            "players": players,
        })
    out["teams"] = teams
    return out


def _parse_leg(raw: str) -> dict:
    """Parse a leg string like 'LeBron James OVER PTS 23.5 (DEMON) [id:10991881]'"""
    m = re.match(
        r"^(.+?)\s+(OVER|UNDER)\s+(\w+)\s+([\d.]+)\s+\((\w+)\)\s+\[id:(\d+)\]$",
        raw.strip(),
    )
    if not m:
        return {"raw": raw, "player": "?", "dir": "?", "stat": "?", "line": 0, "tier": "?", "id": 0}
    return {
        "raw": raw.strip(),
        "player": m.group(1).strip(),
        "dir": m.group(2),
        "stat": m.group(3),
        "line": float(m.group(4)),
        "tier": m.group(5),
        "id": int(m.group(6)),
    }


def _load_top_slip(csv_path: Path, product: str) -> Optional[dict]:
    """Load top slip (by ev_mult) from a CSV file."""
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return None
        # Sort by ev_mult descending, take top 1
        df = df.sort_values("ev_mult", ascending=False).head(1)
        row = df.iloc[0]
        legs_raw = str(row.get("legs", ""))
        legs_list = [_parse_leg(leg_text) for leg_text in legs_raw.split(" | ")]
        return {
            "product": product,
            "n_legs": int(row.get("n_legs", len(legs_list))),
            "legs": legs_raw,
            "legs_detail": legs_list,
            "hit_prob": float(row.get("hit_prob", 0)),
            "ev_mult": float(row.get("ev_mult", 0)),
            "payout_mult": float(row.get("payout_mult", 0)),
            "avg_fragility": float(row.get("avg_fragility", 0)),
        }
    except Exception:
        return None


# Stat code -> callable that accepts a gamelog row and returns the numeric value
_STAT_EXPR: dict[str, list[str]] = {
    "PTS": ["pts"],
    "REB": ["reb"],
    "AST": ["ast"],
    "FG3M": ["fg3m"],
    "PA":  ["pts", "ast"],
    "PR":  ["pts", "reb"],
    "RA":  ["reb", "ast"],
    "PRA": ["pts", "reb", "ast"],
    "BLK": ["blk"],
    "STL": ["stl"],
    "TOV": ["tov"],
    "FTA": ["fta"],
    "FGA": ["fga"],
}


def _compute_l10(
    gamelogs: "pd.DataFrame",
    player: str,
    stat: str,
    line: float,
    direction: str,
    n: int = 10,
) -> tuple[float | None, int]:
    """Return (hit_rate, games_used) for last n games."""
    cols = _STAT_EXPR.get(stat.upper())
    if cols is None:
        return None, 0
    player_gl = gamelogs[gamelogs["player"] == player].sort_values("game_date", ascending=False).head(n)
    if player_gl.empty:
        # Fallback: strip diacritics and retry (e.g. "Schröder" -> "Schroder")
        norm = _norm_name(player)
        player_gl = gamelogs[gamelogs["player"].apply(_norm_name) == norm].sort_values("game_date", ascending=False).head(n)
    if player_gl.empty:
        return None, 0
    available = [c for c in cols if c in player_gl.columns]
    if not available:
        return None, 0
    vals = player_gl[available].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    games = int(vals.notna().sum())
    if games == 0:
        return None, 0
    if direction.upper() == "OVER":
        hits = int((vals > line).sum())
    else:
        hits = int((vals < line).sum())
    return round(hits / games, 4), games


def _preserve_yesterday_slips(out_dir: Path) -> dict:
    """Read yesterday_slips from the existing payload so live runs don't erase it."""
    try:
        existing = out_dir / "cloudflare_payload.json"
        if not existing.exists():
            return {}
        data = json.loads(existing.read_text(encoding="utf-8"))
        ys = data.get("performance", {}).get("yesterday_slips")
        if ys:
            return {"yesterday_slips": ys}
    except Exception:
        pass
    return {}


def _performance_from_payload(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        perf = data.get("performance", data) if isinstance(data, dict) else {}
        if not isinstance(perf, dict) or not perf.get("overall"):
            return {}
        return {k: v for k, v in perf.items() if k != "yesterday_slips"}
    except Exception:
        return {}


def _preserve_performance_stats(out_dir: Path) -> dict:
    """Read existing leg-performance stats so live runs leave 6AM eval windows intact."""
    candidates = [
        out_dir / "performance_latest.json",
        out_dir / "cloudflare_payload.json",
    ]

    # Local dashboard publish copies may be the only surviving performance source
    # after trimming Atlas runtime telemetry. Use them as a seed, then cache back
    # into Atlas/data/output/dashboard for future runs.
    dashboard_public = _repo_root().parent / "atlas-dashboard" / "public"
    candidates.extend([
        dashboard_public / "data" / "cloudflare_payload.json",
        dashboard_public / "data_stage" / "cloudflare_payload.json",
    ])

    for candidate in candidates:
        perf = _performance_from_payload(candidate)
        if perf:
            return perf
    return {}


def _write_performance_cache(out_dir: Path, performance: dict) -> None:
    if not isinstance(performance, dict) or not performance.get("overall"):
        return
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        cache_path = out_dir / "performance_latest.json"
        cache_path.write_text(json.dumps(_sanitize(performance), indent=2), encoding="utf-8")
    except Exception:
        pass


def build_cloudflare_payload(
    run_dir: Path,
    out_dir: Path,
    marketed_slips: Optional[list] = None,
    gamelogs_path: Optional[Path] = None,
    include_yesterday_slips: bool = False,
) -> Path:
    """
    Build cloudflare_payload.json from the slip CSVs in run_dir.

    Args:
        run_dir: The run directory containing System/, Windfall/, demonhunter.csv
        out_dir: Where to write cloudflare_payload.json (usually data/output/dashboard/)
        marketed_slips: Optional list of marketed slip dicts to include in payload
        include_yesterday_slips: Only the 6am eval run should pass True.
            Defaults to False — live runs preserve 6am performance/results fields.

    Returns:
        Path to the written payload file.
    """
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")

    # Load gamelogs once for l10 hit-rate computation and stat hub averages.
    gamelogs_df: Optional["pd.DataFrame"] = None
    if gamelogs_path is None:
        default_logs = _repo_root() / "data" / "gamelogs" / "nba_gamelogs.csv"
        gamelogs_path = default_logs if default_logs.exists() else None
    if gamelogs_path is not None and Path(gamelogs_path).exists():
        try:
            gamelogs_df = pd.read_csv(gamelogs_path, usecols=lambda c: c in {
                "game_date", "player", "team", "opp", "minutes", "pts", "reb", "ast", "fg3m",
                "fga", "fta", "tov", "blk", "stl",
            })
        except Exception:
            gamelogs_df = None

    performance_stats = _compute_performance_stats(_repo_root()) if include_yesterday_slips else _preserve_performance_stats(out_dir)
    if not performance_stats:
        performance_stats = _preserve_performance_stats(out_dir)
    if not performance_stats:
        performance_stats = _compute_performance_stats(_repo_root())

    payload = {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "run_id": run_dir.name,
        "system": [],
        "system_winprob": [],
        "windfall": [],
        "windfall_winprob": [],
        "demonhunter": [],
        "gamescript": [],
        "marketed_slips": [],
        "top_hit_list": [],
        "performance": {
            **performance_stats,
            **({"yesterday_slips": _compute_yesterday_slip_record(_repo_root())} if include_yesterday_slips else _preserve_yesterday_slips(out_dir)),
        },
        "injury_context": _load_injury_context(_repo_root()),
    }
    
    # System: top available leg counts.
    for n in [2, 3, 4, 5]:
        slip = _load_top_slip(run_dir / "System" / f"recommended_{n}leg.csv", "System")
        if slip:
            slip = _apply_prizepicks_quote_to_slip(slip, slip.get("legs_detail", []))
            payload["system"].append(slip)
    
    # System winprob: top available leg counts.
    for n in [2, 3, 4, 5]:
        slip = _load_top_slip(run_dir / "System" / f"recommended_{n}leg_winprob.csv", "System WinProb")
        if slip:
            slip = _apply_prizepicks_quote_to_slip(slip, slip.get("legs_detail", []))
            payload["system_winprob"].append(slip)
    
    # Windfall: top available leg counts.
    for n in [2, 3, 4, 5]:
        slip = _load_top_slip(run_dir / "Windfall" / f"recommended_{n}leg.csv", "Windfall")
        if slip:
            slip = _apply_prizepicks_quote_to_slip(slip, slip.get("legs_detail", []))
            payload["windfall"].append(slip)
    
    # Windfall winprob: top available leg counts.
    for n in [2, 3, 4, 5]:
        slip = _load_top_slip(run_dir / "Windfall" / f"recommended_{n}leg_winprob.csv", "Windfall WinProb")
        if slip:
            slip = _apply_prizepicks_quote_to_slip(slip, slip.get("legs_detail", []))
            payload["windfall_winprob"].append(slip)
    
    # Demonhunter: top available leg counts from single CSV.
    demon_csv = run_dir / "demonhunter.csv"
    if demon_csv.exists():
        try:
            df = pd.read_csv(demon_csv)
            for n in [2, 3, 4, 5]:
                subset = df[df["n_legs"] == n]
                if not subset.empty:
                    subset = subset.sort_values("ev_mult", ascending=False).head(1)
                    row = subset.iloc[0]
                    legs_raw = str(row.get("legs", ""))
                    legs_list = [_parse_leg(leg_text) for leg_text in legs_raw.split(" | ")]
                    demon_slip = {
                        "product": "Demonhunter",
                        "n_legs": n,
                        "legs": legs_raw,
                        "legs_detail": legs_list,
                        "hit_prob": float(row.get("hit_prob", 0)),
                        "ev_mult": float(row.get("ev_mult", 0)),
                        "payout_mult": float(row.get("payout_mult", 0)),
                        "avg_fragility": float(row.get("avg_fragility", 0)),
                    }
                    demon_slip = _apply_prizepicks_quote_to_slip(demon_slip, legs_list)
                    payload["demonhunter"].append(demon_slip)
        except Exception:
            pass
    
    # Marketed slips — prefer caller-supplied list, fall back to marketed_slips.json in run_dir
    if not marketed_slips:
        ms_json = run_dir / "marketed_slips.json"
        if ms_json.exists():
            try:
                raw_ms = json.loads(ms_json.read_text(encoding="utf-8"))
                if isinstance(raw_ms, dict):
                    marketed_slips = raw_ms.get("slips", [])
                elif isinstance(raw_ms, list):
                    marketed_slips = raw_ms
            except Exception:
                marketed_slips = []

    if marketed_slips:
        _seen_l10: dict[tuple, tuple] = {}  # (player,stat,dir,line) -> (l10_hr, l10_n)
        for slip in marketed_slips:
            legs = slip.get("legs", [])
            n_legs = slip.get("n_legs") or (len(legs) if isinstance(legs, list) else 0)
            hit_prob = slip.get("hit_prob") or slip.get("hit_probability")
            payout = slip.get("payout_mult") or slip.get("payout")
            ev = slip.get("ev") or slip.get("ev_mult")
            high_conf = slip.get("high_confidence", False)

            # Normalise legs to a clean list of dicts with just the fields the dashboard needs
            clean_legs = []
            if isinstance(legs, list):
                for leg in legs:
                    if isinstance(leg, dict):
                        player = leg.get("player", "?")
                        stat   = leg.get("stat", "?")
                        direction = str(leg.get("direction") or leg.get("dir", "?")).upper()
                        line   = leg.get("line", 0)
                        # compute l10 once per unique (player, stat, dir, line)
                        key = (player, stat.upper(), direction, float(line))
                        if key not in _seen_l10:
                            if gamelogs_df is not None:
                                l10_hr, l10_n = _compute_l10(gamelogs_df, player, stat, float(line), direction)
                            else:
                                l10_hr, l10_n = None, 0
                            _seen_l10[key] = (l10_hr, l10_n)
                        l10_hr, l10_n = _seen_l10[key]
                        clean_legs.append({
                            "projection_id": leg.get("projection_id"),
                            "source_projection_id": leg.get("source_projection_id"),
                            "player": player,
                            "dir": direction,
                            "stat": stat,
                            "line": line,
                            "tier": str(leg.get("tier", "STANDARD")).upper(),
                            "team": leg.get("team", ""),
                            "opp": leg.get("opp", ""),
                            "p_cal": leg.get("p_cal") or leg.get("p_cal_marketed"),
                            "is_questionable": int(float(leg.get("is_questionable", 0) or 0)),
                            "q_out_frac": float(leg.get("q_out_frac", 0.0) or 0.0),
                            "l10_hr": l10_hr,
                            "l10_n": l10_n,
                        })

            marketed_payload = {
                "label": slip.get("label", f"{n_legs}-leg"),
                "n_legs": n_legs,
                "hit_prob": hit_prob,
                "payout_mult": payout,
                "ev": ev,
                "high_confidence": high_conf,
                "legs": clean_legs,
            }
            marketed_payload = _apply_prizepicks_quote_to_slip(marketed_payload, clean_legs)
            payload["marketed_slips"].append(marketed_payload)

        # Build top_hit_list from unique legs with enough sample
        top_hit_list = [
            {"player": k[0], "stat": k[1], "dir": k[2], "line": k[3],
             "l10_hr": v[0], "l10_n": v[1]}
            for k, v in _seen_l10.items()
            if v[0] is not None and v[1] >= 5
        ]
        top_hit_list.sort(key=lambda x: x["l10_hr"], reverse=True)
        payload["top_hit_list"] = top_hit_list[:10]
    # ---- Load market odds (DraftKings + FanDuel) if available ----
    _odds_lookup: dict = {}
    odds_path = _repo_root() / "data" / "input" / "odds_market_today.json"
    if odds_path.exists():
        try:
            odds_rows = json.loads(odds_path.read_text(encoding="utf-8"))
            for o in odds_rows:
                key = (o.get("player_norm", ""), o.get("stat", ""), float(o.get("line", 0)))
                _odds_lookup[key] = o
        except Exception:
            pass

    # ---- all_legs: every scored leg with display metrics + market odds ----
    scored_csv = run_dir / "scored_legs_deduped.csv"
    if scored_csv.exists():
        try:
            _KEEP = [
                "game_date", "player", "team", "opp", "stat", "line", "direction", "tier",
                "p_cal", "fragility", "q_blowout", "l20_edge", "role_ctx_mult",
                "role_ctx_reason", "p_for_cal", "p_adj", "payout_modifier", "ev_mult",
                "usage_dep", "usage_burden_ratio", "minutes_cv", "volatility_minutes_cv",
                "min_mean", "min_std", "modeled_minutes", "minute_risk_score",
            ]
            al_df = pd.read_csv(scored_csv, usecols=lambda c: c in set(_KEEP))
            al_df = al_df.drop_duplicates(subset=["player", "stat", "direction", "line"])
            al_df = al_df.sort_values("p_cal", ascending=False)
            all_legs_out = []
            def _f(value):
                try:
                    return float(value) if pd.notna(value) else None
                except Exception:
                    return None

            for _, row in al_df.iterrows():
                p_cal = row.get("p_cal")
                frag  = row.get("fragility")
                qbow  = row.get("q_blowout")
                edge  = row.get("l20_edge")
                role  = row.get("role_ctx_mult")
                # Odds lookup: try exact norm name match then fallback
                player_norm = _norm_name(str(row.get("player", ""))).lower()
                stat        = str(row.get("stat", ""))
                try:
                    line_f = float(row.get("line", 0)) if pd.notna(row.get("line")) else 0.0
                except Exception:
                    line_f = 0.0
                odds = _odds_lookup.get((player_norm, stat, line_f)) or {}
                tier = str(row.get("tier", "")).upper()
                tier_mod_default = {"STANDARD": 1.0, "GOBLIN": 0.9, "DEMON": 1.1}.get(tier, 1.0)
                try:
                    payout_modifier = float(row.get("payout_modifier")) if pd.notna(row.get("payout_modifier")) else tier_mod_default
                except Exception:
                    payout_modifier = tier_mod_default
                try:
                    atlas_ev = float(row.get("ev_mult")) if pd.notna(row.get("ev_mult")) else None
                except Exception:
                    atlas_ev = None
                if atlas_ev is None:
                    atlas_ev = float(p_cal) * payout_modifier if pd.notna(p_cal) else None
                all_legs_out.append({
                    "game_date":   str(row.get("game_date", "")) or None,
                    "player":      str(row.get("player", "")),
                    "team":        str(row.get("team", "")),
                    "opp":         str(row.get("opp", "")),
                    "stat":        stat,
                    "line":        line_f if line_f else None,
                    "dir":         str(row.get("direction", "")),
                    "tier":        tier,
                    "p_cal":       float(p_cal) if pd.notna(p_cal) else None,
                    "p_for_cal":   float(row.get("p_for_cal")) if pd.notna(row.get("p_for_cal")) else None,
                    "p_adj":       float(row.get("p_adj")) if pd.notna(row.get("p_adj")) else None,
                    "payout_modifier": payout_modifier,
                    "atlas_ev":    atlas_ev,
                    "ev_mult":     atlas_ev,
                    "atlas_edge":  (atlas_ev - 0.5) if atlas_ev is not None else None,
                    "fragility":   float(frag)  if pd.notna(frag)  else None,
                    "q_blowout":   float(qbow)  if pd.notna(qbow)  else None,
                    "l20_edge":    float(edge)  if pd.notna(edge)  else None,
                    "role_mult":   float(role)  if pd.notna(role)  else None,
                    "role_reason": str(row.get("role_ctx_reason", "")) or None,
                    "usage_score": _f(row.get("usage_dep")),
                    "usage_dep": _f(row.get("usage_dep")),
                    "usage_burden_ratio": _f(row.get("usage_burden_ratio")),
                    "minutes_cv": _f(row.get("minutes_cv")),
                    "minute_volatility": _f(row.get("volatility_minutes_cv", row.get("minutes_cv"))),
                    "modeled_minutes": _f(row.get("modeled_minutes", row.get("min_mean"))),
                    "min_mean": _f(row.get("min_mean")),
                    "min_std": _f(row.get("min_std")),
                    "minute_risk_score": _f(row.get("minute_risk_score")),
                    # Market odds (None when not available)
                    "dk_over":     odds.get("dk_over"),
                    "dk_under":    odds.get("dk_under"),
                    "fd_over":     odds.get("fd_over"),
                    "fd_under":    odds.get("fd_under"),
                    "dk_imp_over": odds.get("dk_imp_over"),
                    "fd_imp_over": odds.get("fd_imp_over"),
                })
            payload["all_legs"] = all_legs_out
            # Extract role-boosted legs for the injury tab
            no_effect_reasons = {"no_outs", "none", "combo_no_effect", "no_share_matrix", "stat_unmapped", ""}
            role_boosted = []
            for leg in all_legs_out:
                reason = str(leg.get("role_reason") or "").strip()
                if reason.lower() in no_effect_reasons:
                    continue
                role_mult = leg.get("role_mult")
                if role_mult is None:
                    continue
                try:
                    role_delta = abs(float(role_mult) - 1.0)
                except (TypeError, ValueError):
                    continue
                if role_delta < 0.005:
                    continue
                role_boosted.append({
                    "player": leg.get("player"),
                    "team": leg.get("team"),
                    "stat": leg.get("stat"),
                    "line": leg.get("line"),
                    "dir": leg.get("dir"),
                    "tier": leg.get("tier"),
                    "p_cal": leg.get("p_cal"),
                    "role_mult": role_mult,
                    "role_reason": reason,
                })
            payload["injury_context"]["role_boosted"] = role_boosted
        except Exception:
            payload["all_legs"] = []
    else:
        payload["all_legs"] = []

    payload["stat_hub"] = _build_stat_hub_payload(payload.get("all_legs", []), gamelogs_df, _repo_root())

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cloudflare_payload.json"
    # Inject total_slips into main payload so landing page can read it
    payload["total_slips"] = len(payload.get("system") or []) + len(payload.get("windfall") or []) + len(payload.get("demonhunter") or []) + len(payload.get("marketed_slips") or [])
    out_path.write_text(json.dumps(_sanitize(payload), indent=2), encoding="utf-8")
    _write_performance_cache(out_dir, payload.get("performance") or {})

    # Write lightweight picks file for homepage
    # Guarantee 1 top pick per tier (GOBLIN, STANDARD, DEMON) then fill to 50
    picks_fields = ["player", "team", "opp", "stat", "line", "dir", "tier", "p_cal"]
    all_legs_list = payload.get("all_legs") or []
    _TIERS = ["GOBLIN", "STANDARD", "DEMON"]
    tier_picks = {}
    remaining = []
    for leg in all_legs_list:
        t = (leg.get("tier") or "").upper()
        if t in _TIERS and t not in tier_picks:
            tier_picks[t] = leg
        else:
            remaining.append(leg)
    # Ordered: guaranteed tier picks first, then fill from remaining up to 50
    guaranteed = [tier_picks[t] for t in _TIERS if t in tier_picks]
    filler = [leg for leg in remaining if leg not in guaranteed]
    picks_list = guaranteed + filler[:max(0, 50 - len(guaranteed))]
    picks_payload = {
        "generated_at": payload.get("generated_at", ""),
        "picks": [{k: leg.get(k) for k in picks_fields} for leg in picks_list],
        "total_legs": len(all_legs_list),
        "total_slips": len(payload.get("system") or []) + len(payload.get("windfall") or []) + len(payload.get("demonhunter") or []) + len(payload.get("marketed_slips") or []),
    }
    picks_path = out_dir / "picks_today.json"
    picks_path.write_text(json.dumps(_sanitize(picks_payload)), encoding="utf-8")

    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python build_cloudflare_payload.py <run_dir>")
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    out_dir = run_dir.parents[1] / "dashboard"
    # Called by 6am eval run — this is the ONLY path that should update yesterday_slips
    result = build_cloudflare_payload(run_dir, out_dir, include_yesterday_slips=True)
    print(f"Wrote: {result}")

"""
Build cloudflare_payload.json from slip CSVs.

Called after run_publish_stage to create the dashboard payload.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional


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

import csv as _csv_module
import pandas as pd


def _compute_performance_stats(repo_root: Path) -> dict:
    """Aggregate hit rates from recent eval_legs across live_runs telemetry."""
    from datetime import timedelta, timezone
    live_runs_dir = repo_root / "data" / "telemetry" / "live_runs"
    if not live_runs_dir.exists():
        return {}
    today = datetime.now(timezone.utc).date()
    cutoff_7d = today - timedelta(days=7)
    cutoff_30d = today - timedelta(days=30)

    seen: set = set()
    rows: list = []
    for fpath in sorted(live_runs_dir.rglob("eval_legs.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(fpath, newline="", encoding="utf-8", errors="replace") as f:
                reader = _csv_module.DictReader(f)
                for row in reader:
                    hit_val = row.get("hit", "")
                    if hit_val not in ("0", "1", "0.0", "1.0"):
                        continue
                    game_date = (row.get("game_date") or "")[:10]
                    key = (game_date, row.get("player",""), row.get("stat",""), row.get("line",""), row.get("direction",""))
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        gd = datetime.strptime(game_date, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    try:
                        p_cal = float(row.get("p_cal") or 0)
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

    def _stats(subset: list) -> dict:
        if not subset:
            return {"n": 0, "hit_rate": None, "brier": None}
        n = len(subset)
        hits = sum(r["hit"] for r in subset)
        brier = round(sum((r["p_cal"] - r["hit"]) ** 2 for r in subset) / n, 4)
        return {"n": n, "hit_rate": round(hits / n, 4), "brier": brier}

    rows_7d = [r for r in rows if r["game_date"] >= cutoff_7d]
    rows_30d = [r for r in rows if r["game_date"] >= cutoff_30d]

    result: dict = {
        "overall": {"last_7d": _stats(rows_7d), "last_30d": _stats(rows_30d)},
        "by_tier": {},
    }
    for tier in ("GOBLIN", "STANDARD", "DEMON"):
        result["by_tier"][tier] = {
            "last_7d": _stats([r for r in rows_7d if r["tier"] == tier]),
            "last_30d": _stats([r for r in rows_30d if r["tier"] == tier]),
        }
    return result


def _compute_yesterday_slip_record(repo_root: Path) -> dict:
    """Count yesterday's marketed slip wins from data/output/runs/."""
    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    yesterday_str = yesterday.isoformat()
    prefix = yesterday_str.replace("-", "")
    runs_dir = repo_root / "data" / "output" / "runs"
    if not runs_dir.exists():
        return {}
    run_dirs = sorted(
        [d for d in runs_dir.iterdir()
         if d.is_dir() and d.name.startswith(prefix) and len(d.name) == 15 and d.name[8] == "_"],
        key=lambda d: d.name,
    )
    if not run_dirs:
        return {}
    # Build hit lookup from eval_legs
    hit_lookup: dict = {}
    for rd in run_dirs:
        el = rd / "eval_legs.csv"
        if not el.exists():
            continue
        try:
            with open(el, newline="", encoding="utf-8", errors="replace") as f:
                for row in _csv_module.DictReader(f):
                    hit_val = row.get("hit", "")
                    if hit_val not in ("0", "1", "0.0", "1.0"):
                        continue
                    gd = (row.get("game_date") or "")[:10]
                    if gd != yesterday_str:
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
            continue
    if not hit_lookup:
        return {}
    # Score marketed slips; deduplicate wins by leg-set frozenset
    wins = 0
    total = 0
    seen_wins: set = set()
    for rd in run_dirs:
        mp = rd / "marketed_slips.csv"
        if not mp.exists():
            continue
        try:
            slips: dict = {}
            with open(mp, newline="", encoding="utf-8", errors="replace") as f:
                for row in _csv_module.DictReader(f):
                    sn = (row.get("slip") or "").strip()
                    slips.setdefault(sn, []).append(row)
            for slip_name, legs in slips.items():
                leg_keys = tuple(
                    (l.get("player", "").strip(), l.get("stat", "").strip(),
                     l.get("line", "").strip(), (l.get("direction") or "").upper())
                    for l in legs
                )
                slip_won = all(hit_lookup.get(k, 0) == 1 for k in leg_keys)
                if slip_won:
                    frozen = frozenset(leg_keys)
                    if frozen not in seen_wins:
                        seen_wins.add(frozen)
                        wins += 1
                total += 1
        except Exception:
            continue
    if total == 0:
        return {}
    return {
        "date": yesterday_str,
        "wins": wins,
        "total": total,
        "pct": round(wins / total, 4),
    }


def _load_injury_context(repo_root: Path) -> dict:
    """Load latest IAEL injury report for dashboard display."""
    out: dict = {"invalidated_players": [], "report_date": None, "report_label": None}
    iael_path = repo_root / "data" / "output" / "dashboard" / "injury_invalidations_latest.json"
    if not iael_path.exists():
        return out
    try:
        with open(iael_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out["report_date"] = data.get("report_date")
        out["report_label"] = data.get("report_label")
        out["invalidated_players"] = data.get("invalidated_players", [])
    except Exception:
        pass
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
        legs_list = [_parse_leg(l) for l in legs_raw.split(" | ")]
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


def build_cloudflare_payload(
    run_dir: Path,
    out_dir: Path,
    marketed_slips: Optional[list] = None,
    gamelogs_path: Optional[Path] = None,
) -> Path:
    """
    Build cloudflare_payload.json from the slip CSVs in run_dir.
    
    Args:
        run_dir: The run directory containing System/, Windfall/, demonhunter.csv
        out_dir: Where to write cloudflare_payload.json (usually data/output/dashboard/)
        marketed_slips: Optional list of marketed slip dicts to include in payload
    
    Returns:
        Path to the written payload file.
    """
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")

    # Load gamelogs once for l10 hit-rate computation
    gamelogs_df: Optional["pd.DataFrame"] = None
    if gamelogs_path is not None and Path(gamelogs_path).exists():
        try:
            gamelogs_df = pd.read_csv(gamelogs_path, usecols=lambda c: c in {
                "game_date", "player", "pts", "reb", "ast", "fg3m",
                "fga", "fta", "tov", "blk", "stl",
            })
        except Exception:
            gamelogs_df = None

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
        "performance": {**_compute_performance_stats(_repo_root()), "yesterday_slips": _compute_yesterday_slip_record(_repo_root())},
        "injury_context": _load_injury_context(_repo_root()),
    }
    
    # System: top 3-leg, 4-leg, 5-leg (EV-based)
    for n in [3, 4, 5]:
        slip = _load_top_slip(run_dir / "System" / f"recommended_{n}leg.csv", "System")
        if slip:
            payload["system"].append(slip)
    
    # System winprob: top 3-leg, 4-leg, 5-leg (win probability based)
    for n in [3, 4, 5]:
        slip = _load_top_slip(run_dir / "System" / f"recommended_{n}leg_winprob.csv", "System WinProb")
        if slip:
            payload["system_winprob"].append(slip)
    
    # Windfall: top 3-leg, 4-leg, 5-leg (EV-based)
    for n in [3, 4, 5]:
        slip = _load_top_slip(run_dir / "Windfall" / f"recommended_{n}leg.csv", "Windfall")
        if slip:
            payload["windfall"].append(slip)
    
    # Windfall winprob: top 3-leg, 4-leg, 5-leg (win probability based)
    for n in [3, 4, 5]:
        slip = _load_top_slip(run_dir / "Windfall" / f"recommended_{n}leg_winprob.csv", "Windfall WinProb")
        if slip:
            payload["windfall_winprob"].append(slip)
    
    # Demonhunter: top 3-leg, 4-leg, 5-leg from single CSV
    demon_csv = run_dir / "demonhunter.csv"
    if demon_csv.exists():
        try:
            df = pd.read_csv(demon_csv)
            for n in [3, 4, 5]:
                subset = df[df["n_legs"] == n]
                if not subset.empty:
                    subset = subset.sort_values("ev_mult", ascending=False).head(1)
                    row = subset.iloc[0]
                    legs_raw = str(row.get("legs", ""))
                    legs_list = [_parse_leg(l) for l in legs_raw.split(" | ")]
                    payload["demonhunter"].append({
                        "product": "Demonhunter",
                        "n_legs": n,
                        "legs": legs_raw,
                        "legs_detail": legs_list,
                        "hit_prob": float(row.get("hit_prob", 0)),
                        "ev_mult": float(row.get("ev_mult", 0)),
                        "payout_mult": float(row.get("payout_mult", 0)),
                        "avg_fragility": float(row.get("avg_fragility", 0)),
                    })
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
                            "player": player,
                            "dir": direction,
                            "stat": stat,
                            "line": line,
                            "tier": str(leg.get("tier", "STANDARD")).upper(),
                            "team": leg.get("team", ""),
                            "opp": leg.get("opp", ""),
                            "p_cal": leg.get("p_cal") or leg.get("p_cal_marketed"),
                            "l10_hr": l10_hr,
                            "l10_n": l10_n,
                        })

            payload["marketed_slips"].append({
                "label": slip.get("label", f"{n_legs}-leg"),
                "n_legs": n_legs,
                "hit_prob": hit_prob,
                "payout_mult": payout,
                "ev": ev,
                "high_confidence": high_conf,
                "legs": clean_legs,
            })

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
                "player", "team", "opp", "stat", "line", "direction", "tier",
                "p_cal", "fragility", "q_blowout", "l20_edge", "role_ctx_mult",
                "role_ctx_reason", "p_for_cal",
            ]
            al_df = pd.read_csv(scored_csv, usecols=lambda c: c in set(_KEEP))
            al_df = al_df.drop_duplicates(subset=["player", "stat", "direction", "line"])
            al_df = al_df.sort_values("p_cal", ascending=False)
            all_legs_out = []
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
                all_legs_out.append({
                    "player":      str(row.get("player", "")),
                    "team":        str(row.get("team", "")),
                    "opp":         str(row.get("opp", "")),
                    "stat":        stat,
                    "line":        line_f if line_f else None,
                    "dir":         str(row.get("direction", "")),
                    "tier":        str(row.get("tier", "")),
                    "p_cal":       float(p_cal) if pd.notna(p_cal) else None,
                    "fragility":   float(frag)  if pd.notna(frag)  else None,
                    "q_blowout":   float(qbow)  if pd.notna(qbow)  else None,
                    "l20_edge":    float(edge)  if pd.notna(edge)  else None,
                    "role_mult":   float(role)  if pd.notna(role)  else None,
                    "role_reason": str(row.get("role_ctx_reason", "")) or None,
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
            payload["injury_context"]["role_boosted"] = [
                {
                    "player": leg.get("player"),
                    "team": leg.get("team"),
                    "stat": leg.get("stat"),
                    "line": leg.get("line"),
                    "dir": leg.get("dir"),
                    "tier": leg.get("tier"),
                    "p_cal": leg.get("p_cal"),
                    "role_mult": leg.get("role_mult"),
                    "role_reason": leg.get("role_reason"),
                }
                for leg in all_legs_out
                if leg.get("role_reason") and leg.get("role_reason") not in ("no_outs", "None", "", None)
            ]
        except Exception:
            payload["all_legs"] = []
    else:
        payload["all_legs"] = []

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cloudflare_payload.json"
    out_path.write_text(json.dumps(_sanitize(payload), indent=2), encoding="utf-8")

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
    filler = [l for l in remaining if l not in guaranteed]
    picks_list = guaranteed + filler[:max(0, 50 - len(guaranteed))]
    picks_payload = {
        "generated_at": payload.get("generated_at", ""),
        "picks": [{k: leg.get(k) for k in picks_fields} for leg in picks_list],
        "total_legs": len(all_legs_list),
        "total_slips": len(payload.get("system") or []) + len(payload.get("windfall") or []) + len(payload.get("demonhunter") or []),
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
    result = build_cloudflare_payload(run_dir, out_dir)
    print(f"Wrote: {result}")

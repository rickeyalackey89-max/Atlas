#!/usr/bin/env python3
"""
Fetch Rotowire NBA lines/spreads and write Atlas-friendly JSON.

HARD REQUIREMENT (your semantics):
- Rotowire is called every LIVE run.

SMOOTH BEHAVIOR:
- If Rotowire returns no rows / no events, do NOT silently proceed with empty spreads.
- Instead:
  1) Try to fall back to last-known-good file: data/input/rotowire_lines_last_good.json
  2) If fallback exists and has events, write that into rotowire_lines.json (with a note)
  3) If fallback missing/empty too, write the empty stub and exit non-zero.

ENV:
  ROTOWIRE_GAME_DATE        (optional) YYYY-MM-DD
  ROTOWIRE_BOOK             (optional) default "mgm"  (currently only mgm supported in this script)
  ROTOWIRE_TIMEOUT_S        (optional) default 20
  ROTOWIRE_PHPSESSID        (optional) If provided, use this session id cookie.
  ROTOWIRE_OUT_PATH         (optional) output path override
  ROTOWIRE_LAST_GOOD_PATH   (optional) last-good path override
  ROTOWIRE_ALLOW_EMPTY      (optional) "1" => allow empty without failing (not recommended for LIVE)
  ROTOWIRE_DEBUG_DIR        (optional) where to write debug payloads
  ROTOWIRE_LINES_URL        (optional) full override URL
  ROTOWIRE_HEADERS_JSON     (optional) JSON dict of extra headers
  ROTOWIRE_BOOTSTRAP_URL    (optional) page to visit first to obtain cookies (default: NBA odds page)
  ROTOWIRE_EVENT_TZ         (optional) timezone name for Rotowire eventTime parsing (default America/New_York)

  ODDS_API_KEY              (optional) The Odds API key. If set, used as a fallback source when Rotowire
                            is empty/blocked or yields 0 events.
  ODDS_API_REGIONS          (optional) default "us"
  ODDS_API_MARKETS          (optional) default "spreads" (can be "spreads" or "h2h,spreads,totals" etc.)
  ODDS_API_BOOK_PREF        (optional) comma-separated bookmaker keys preference order (default "draftkings,fanduel")
  ODDS_API_TIMEOUT_S        (optional) default 20
  ODDS_API_TZ               (optional) timezone used to map commence_time to game_date (default America/Chicago)

Notes:
- This tool writes JSON shaped as:
  {"sport":"NBA","source":..., "date":"YYYY-MM-DD","events":[...], "fetched_at":"...Z", "note":"..."}
- Events are:
  {"gameID":..., "eventTime": epoch, "game_date":"YYYY-MM-DD", "homeTeam":"ATL", "awayTeam":"NYK",
   "spread":{"home": -4.5, "away": 4.5}, "ml": {"home": -180, "away": 150}, "ou": 229.5, "source":"mgm"}
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class Event:
    gameID: str
    eventTime: int
    game_date: str
    homeTeam: str
    awayTeam: str
    home_spread: Optional[float]
    away_spread: Optional[float]
    home_ml: Optional[int]
    away_ml: Optional[int]
    ou: Optional[float]
    source: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "gameID": self.gameID,
            "eventTime": self.eventTime,
            "game_date": self.game_date,
            "homeTeam": self.homeTeam,
            "awayTeam": self.awayTeam,
            "spread": {"home": self.home_spread, "away": self.away_spread},
            "ml": {"home": self.home_ml, "away": self.away_ml},
            "ou": self.ou,
            "source": self.source,
        }


# -----------------------------
# Small helpers
# -----------------------------
def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_out_path() -> Path:
    return _repo_root() / "data" / "input" / "rotowire_lines.json"


def _default_last_good_path() -> Path:
    return _repo_root() / "data" / "input" / "rotowire_lines_last_good.json"


def _debug_dir() -> Path:
    p = Path(os.getenv("ROTOWIRE_DEBUG_DIR", str(_repo_root() / "data" / "output" / "debug")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_debug(name: str, content: str) -> None:
    p = _debug_dir() / name
    p.write_text(content, encoding="utf-8")


def _maybe_env(name: str) -> Optional[str]:
    v = os.getenv(name, "").strip()
    return v or None


def _headers_from_env() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.rotowire.com/betting/nba/odds",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    extra_json = _maybe_env("ROTOWIRE_HEADERS_JSON")
    if extra_json:
        try:
            extra = json.loads(extra_json)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    headers[str(k)] = str(v)
        except Exception:
            # ignore bad header json; debugging via debug_dir if desired
            pass
    return headers


def to_float(x: Any) -> Optional[float]:
    """
    Defensive float parser.
    - None -> None
    - "PK"/"PICK" -> 0.0
    - numeric strings -> float
    - int/float -> float
    """
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return None
        if s.upper() in {"PK", "PICK", "PICK'EM", "PICKEM"}:
            return 0.0
        try:
            return float(s)
        except ValueError:
            # try to keep only numeric-ish chars
            cleaned = "".join(ch for ch in s if ch.isdigit() or ch in "+-.")
            if cleaned in {"", "+", "-", ".", "+.", "-."}:
                return None
            try:
                return float(cleaned)
            except Exception:
                return None
    # other types
    try:
        return float(str(x).strip())
    except Exception:
        return None


def _to_nullable_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return int(x)
    if isinstance(x, float):
        # Rotowire sometimes returns floats; treat as int if safe
        try:
            return int(x)
        except Exception:
            return None
    s = str(x).strip()
    if not s or s == "-":
        return None
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in "+-")
    if cleaned in {"", "+", "-"}:
        return None
    try:
        return int(cleaned)
    except Exception:
        return None


def _event_tz():
    # Rotowire table times are effectively US/Eastern for NBA odds pages.
    tz_name = (os.getenv("ROTOWIRE_EVENT_TZ") or "America/New_York").strip()
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/New_York")


def _parse_game_date_epoch(game_date_str: Optional[str], fallback_yyyy_mm_dd: str) -> int:
    """
    Parse Rotowire 'gameDate' into epoch seconds.
    Interpret naive timestamps as ROTOWIRE_EVENT_TZ (default America/New_York).
    """
    tz = _event_tz()

    if game_date_str:
        s = str(game_date_str).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                if tz is not None:
                    dt = dt.replace(tzinfo=tz)
                    return int(dt.timestamp())
                return int(dt.replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                pass

    # fallback: noon local to avoid UTC-midnight boundary surprises
    dt = datetime.strptime(fallback_yyyy_mm_dd, "%Y-%m-%d").replace(hour=12)
    if tz is not None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _normalize_rows_shape(payload: Any) -> List[Dict[str, Any]]:
    """
    Rotowire table responses vary.
    Accept:
      - list[dict]
      - dict with key 'data'/'rows'/'result' containing list[dict]
      - list containing a single list of dicts
    """
    if isinstance(payload, list):
        if len(payload) == 1 and isinstance(payload[0], list):
            payload = payload[0]
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for k in ("data", "rows", "result"):
            v = payload.get(k)
            if isinstance(v, list):
                if len(v) == 1 and isinstance(v[0], list):
                    v = v[0]
                return [x for x in v if isinstance(x, dict)]

    return []


def _pick_book_fields(book: str) -> Tuple[str, str, str]:
    b = (book or "mgm").strip().lower()
    if b == "mgm":
        return ("mgm_spread", "mgm_moneyline", "mgm_ou")
    raise SystemExit(f"[rotowire] Unsupported ROTOWIRE_BOOK={book!r}. Supported: mgm")


def _build_url(game_date: str) -> str:
    return f"https://www.rotowire.com/betting/nba/tables/nba-games-by-market.php?date={game_date}"


def _bootstrap_rotowire_session(sess: requests.Session, timeout_s: float) -> None:
    """Best-effort: visit a normal Rotowire page to obtain a PHPSESSID (and related) cookies."""
    bootstrap_url = (os.getenv("ROTOWIRE_BOOTSTRAP_URL") or "https://www.rotowire.com/betting/nba/odds").strip()
    try:
        sess.get(bootstrap_url, timeout=timeout_s)
    except Exception:
        # best-effort only
        return


# -----------------------------
# Odds API fallback
# -----------------------------
_NBA_TEAM_ABBR: Dict[str, str] = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}


def _abbr_from_team_name(name: str) -> Optional[str]:
    if not name:
        return None
    n = str(name).strip()
    if n in _NBA_TEAM_ABBR:
        return _NBA_TEAM_ABBR[n]
    n2 = n.replace("Los Angeles", "LA")
    if n2 in _NBA_TEAM_ABBR:
        return _NBA_TEAM_ABBR[n2]
    return None


def _parse_iso_z(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _oddsapi_tz():
    tz_name = (os.getenv("ODDS_API_TZ") or "America/Chicago").strip()
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Chicago")


def _fetch_oddsapi_events(game_date: str) -> List[Event]:
    api_key = (os.getenv("ODDS_API_KEY") or "").strip()
    if not api_key:
        return []

    regions = (os.getenv("ODDS_API_REGIONS") or "us").strip()
    markets = (os.getenv("ODDS_API_MARKETS") or "spreads").strip()
    timeout_s = float(os.getenv("ODDS_API_TIMEOUT_S", os.getenv("ROTOWIRE_TIMEOUT_S", "20")))
    book_pref = (os.getenv("ODDS_API_BOOK_PREF") or "draftkings,fanduel").strip()
    pref = [x.strip().lower() for x in book_pref.split(",") if x.strip()]

    url = (
        "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        f"?regions={regions}&markets={markets}&oddsFormat=american&apiKey={api_key}"
    )

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    print(f"[oddsapi] GET {url.split('apiKey=')[0]}apiKey=***")
    r = requests.get(url, headers=headers, timeout=timeout_s)
    body = r.content or b""
    print(f"[oddsapi] status={r.status_code} bytes={len(body)}")
    if r.status_code != 200:
        _write_debug(f"oddsapi_http_{r.status_code}_{game_date}.txt", (r.text or "")[:20000])
        return []

    try:
        data = r.json()
    except Exception:
        _write_debug(f"oddsapi_not_json_{game_date}.txt", (r.text or "")[:20000])
        return []

    if not isinstance(data, list):
        _write_debug(f"oddsapi_bad_shape_{game_date}.json", json.dumps(data, ensure_ascii=False)[:200000])
        return []

    tz = _oddsapi_tz()
    out: List[Event] = []

    for ev in data:
        if not isinstance(ev, dict):
            continue

        commence = _parse_iso_z(str(ev.get("commence_time") or ""))
        if commence is None:
            continue

        local_dt = commence.astimezone(tz) if tz is not None else commence
        gd = local_dt.date().isoformat()
        if gd != game_date:
            continue

        home_name = str(ev.get("home_team") or "").strip()
        away_name = str(ev.get("away_team") or "").strip()
        home_abbr = _abbr_from_team_name(home_name)
        away_abbr = _abbr_from_team_name(away_name)
        if not home_abbr or not away_abbr:
            continue

        game_id = str(ev.get("id") or "").strip() or f"oddsapi_{home_abbr}_{away_abbr}_{gd}"

        bms = ev.get("bookmakers")
        if not isinstance(bms, list):
            continue

        chosen: Optional[Dict[str, Any]] = None
        for want in pref:
            for bm in bms:
                if isinstance(bm, dict) and str(bm.get("key") or "").lower() == want:
                    chosen = bm
                    break
            if chosen is not None:
                break

        if chosen is None:
            chosen = bms[0] if (bms and isinstance(bms[0], dict)) else None
        if chosen is None:
            continue

        bm_key = str(chosen.get("key") or "").lower() or "oddsapi"
        mkts = chosen.get("markets")
        if not isinstance(mkts, list):
            continue

        spread_mkt = next((m for m in mkts if isinstance(m, dict) and str(m.get("key") or "") == "spreads"), None)
        if spread_mkt is None:
            continue

        outs = spread_mkt.get("outcomes")
        if not isinstance(outs, list):
            continue

        home_spread: Optional[float] = None
        away_spread: Optional[float] = None

        for o in outs:
            if not isinstance(o, dict):
                continue
            name = str(o.get("name") or "").strip()
            pt_f = to_float(o.get("point"))
            if pt_f is None:
                continue
            if name == home_name:
                home_spread = pt_f
            elif name == away_name:
                away_spread = pt_f

        if home_spread is None or away_spread is None:
            continue

        out.append(
            Event(
                gameID=game_id,
                eventTime=int(commence.timestamp()),
                game_date=gd,
                homeTeam=home_abbr,
                awayTeam=away_abbr,
                home_spread=home_spread,
                away_spread=away_spread,
                home_ml=None,
                away_ml=None,
                ou=None,
                source=f"oddsapi:{bm_key}",
            )
        )

    return out


# -----------------------------
# Last-good fallback
# -----------------------------
def _load_last_good(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict) and isinstance(obj.get("events"), list) and len(obj["events"]) > 0:
            return obj
    except Exception:
        return None
    return None


def _write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def _today_dashed_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _resolve_archive_ids() -> Tuple[Optional[str], str, str]:
    run_id = os.environ.get("ATLAS_RUN_ID") or None
    snapshot_id = os.environ.get("ATLAS_SNAPSHOT_ID") or _utc_compact()
    date_dashed = os.environ.get("ATLAS_ASOF_DATE_DASHED") or _today_dashed_utc()
    return run_id, snapshot_id, date_dashed


def _maybe_archive_live_rotowire(out_path: Path) -> None:
    """
    Additive live-only archive copy for backtest fidelity.

    Rules:
    - archive only when writing the canonical live latest file
    - do nothing for replay/backtest/overridden paths
    - never interfere with the normal live write path
    """
    try:
        if out_path.resolve() != _default_out_path().resolve():
            return

        run_id, snapshot_id, date_dashed = _resolve_archive_ids()
        year = date_dashed[0:4]
        snap_dir = _repo_root() / "data" / "archives" / "iael" / year / date_dashed / snapshot_id
        snap_dir.mkdir(parents=True, exist_ok=True)

        dst = snap_dir / "rotowire_lines.json"
        shutil.copy2(out_path, dst)

        manifest = {
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "date": date_dashed,
            "rotowire_snapshot_dir": str(snap_dir),
            "rotowire_src": str(out_path),
            "rotowire_dst": str(dst),
            "fetched_at": _now_utc_iso(),
        }
        (snap_dir / "rotowire_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[rotowire] archive skipped: {e!r}")


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    timeout_s = float(os.getenv("ROTOWIRE_TIMEOUT_S", "20"))
    book = os.getenv("ROTOWIRE_BOOK", "mgm")
    allow_empty = os.getenv("ROTOWIRE_ALLOW_EMPTY", "0").strip() == "1"

    spread_field, ml_field, ou_field = _pick_book_fields(book)

    game_date = _maybe_env("ROTOWIRE_GAME_DATE")
    url = _maybe_env("ROTOWIRE_LINES_URL")

    if not game_date:
        game_date = datetime.now().strftime("%Y-%m-%d")

    if not url:
        url = _build_url(game_date)

    headers = _headers_from_env()

    # Use a session so cookies persist (Rotowire often gates this endpoint behind PHPSESSID).
    sess = requests.Session()
    sess.headers.update(headers)

    php_sessid = (os.getenv("ROTOWIRE_PHPSESSID") or "").strip()
    if php_sessid:
        sess.cookies.set("PHPSESSID", php_sessid, domain="www.rotowire.com")
    else:
        _bootstrap_rotowire_session(sess, timeout_s)

    out_path = Path(os.getenv("ROTOWIRE_OUT_PATH", str(_default_out_path())))
    last_good_path = Path(os.getenv("ROTOWIRE_LAST_GOOD_PATH", str(_default_last_good_path())))

    print(f"[rotowire] GET {url}")
    r = sess.get(url, timeout=timeout_s)
    body = r.content or b""
    print(f"[rotowire] status={r.status_code} bytes={len(body)}")

    # -----------------------------
    # HTTP non-200
    # -----------------------------
    if r.status_code != 200:
        _write_debug(f"rotowire_http_{r.status_code}_{game_date}.txt", (r.text or "")[:10000])

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": f"FALLBACK_USED: oddsapi (rotowire http_{r.status_code})",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        lg = _load_last_good(last_good_path)
        if lg is not None:
            lg2 = dict(lg)
            lg2["note"] = f"STALE_FALLBACK_USED: http_{r.status_code}"
            lg2["fetched_at"] = _now_utc_iso()
            _write_json_atomic(out_path, lg2)
            _maybe_archive_live_rotowire(out_path)
            print(f"[rotowire] wrote {out_path} (events={len(lg2['events'])}) using LAST_GOOD fallback")
            return 0

        return 2

    # -----------------------------
    # Rotowire returned HTML (cookie-gated)
    # -----------------------------
    ct = (r.headers.get("Content-Type") or "").lower()
    if "text/html" in ct:
        _write_debug(f"rotowire_html_{game_date}.html", (r.text or "")[:200000])

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": "FALLBACK_USED: oddsapi (rotowire got_html)",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        lg = _load_last_good(last_good_path)
        if lg is not None:
            lg2 = dict(lg)
            lg2["note"] = "STALE_FALLBACK_USED: got_html"
            lg2["fetched_at"] = _now_utc_iso()
            _write_json_atomic(out_path, lg2)
            _maybe_archive_live_rotowire(out_path)
            print(f"[rotowire] wrote {out_path} (events={len(lg2['events'])}) using LAST_GOOD fallback")
            return 0

        if allow_empty:
            return 0
        return 3

    # -----------------------------
    # Parse JSON body
    # -----------------------------
    try:
        payload = r.json()
    except Exception as e:
        _write_debug(f"rotowire_not_json_{game_date}.txt", (r.text or "")[:10000])

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [x.to_json() for x in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": f"FALLBACK_USED: oddsapi (rotowire not_json:{type(e).__name__})",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        lg = _load_last_good(last_good_path)
        if lg is not None:
            lg2 = dict(lg)
            lg2["note"] = f"STALE_FALLBACK_USED: not_json:{type(e).__name__}"
            lg2["fetched_at"] = _now_utc_iso()
            _write_json_atomic(out_path, lg2)
            _maybe_archive_live_rotowire(out_path)
            print(f"[rotowire] wrote {out_path} (events={len(lg2['events'])}) using LAST_GOOD fallback")
            return 0

        if allow_empty:
            return 0
        return 4

    rows = _normalize_rows_shape(payload)

    # One-time bootstrap+retry if empty and we didn't explicitly provide PHPSESSID.
    if not rows and not php_sessid:
        _bootstrap_rotowire_session(sess, timeout_s)
        try:
            r2 = sess.get(url, timeout=timeout_s)
            if r2.status_code == 200:
                payload2 = r2.json()
                rows2 = _normalize_rows_shape(payload2)
                if rows2:
                    payload = payload2
                    rows = rows2
        except Exception:
            pass

    # If rotowire literally returned [] (bytes=2), rows will be empty.
    if not rows:
        _write_debug(
            f"rotowire_empty_rows_{game_date}.json",
            json.dumps(payload, ensure_ascii=False)[:200000],
        )

        oa_events = _fetch_oddsapi_events(game_date)
        if oa_events:
            out_obj = {
                "sport": "NBA",
                "source": "the-odds-api.com/v4 (fallback)",
                "date": game_date,
                "events": [e.to_json() for e in oa_events],
                "fetched_at": _now_utc_iso(),
                "note": "FALLBACK_USED: oddsapi (rotowire empty_rows)",
            }
            _write_json_atomic(out_path, out_obj)
            _maybe_archive_live_rotowire(out_path)
            _write_json_atomic(last_good_path, out_obj)
            print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
            return 0

        lg = _load_last_good(last_good_path)
        if lg is not None:
            lg2 = dict(lg)
            lg2["note"] = "STALE_FALLBACK_USED: empty_rows"
            lg2["fetched_at"] = _now_utc_iso()
            _write_json_atomic(out_path, lg2)
            _maybe_archive_live_rotowire(out_path)
            print(f"[rotowire] wrote {out_path} (events={len(lg2['events'])}) using LAST_GOOD fallback")
            return 0

        out_obj = {
            "sport": "NBA",
            "source": "rotowire.com/betting/nba/tables/nba-games-by-market.php",
            "date": game_date,
            "events": [],
            "fetched_at": _now_utc_iso(),
            "note": "No rows returned from endpoint (schema change, blocked, or empty slate).",
        }
        _write_json_atomic(out_path, out_obj)
        print(f"[rotowire] wrote {out_path} (events=0) at {_now_utc_iso()}")

        if allow_empty:
            return 0
        return 5

    # -----------------------------
    # Build events from Rotowire rows
    # -----------------------------
    games: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        gid = str(row.get("gameID", "")).strip()
        if gid:
            games.setdefault(gid, []).append(row)

    events: List[Event] = []
    for gid, grp in games.items():
        if len(grp) < 2:
            continue

        def ha_tag(x: Dict[str, Any]) -> str:
            return str(x.get("homeAway", "")).strip().lower()

        home = next((x for x in grp if ha_tag(x) == "home"), None)
        away = next((x for x in grp if ha_tag(x) == "away"), None)
        if home is None or away is None:
            home, away = grp[0], grp[1]

        home_team = str(home.get("abbr", "")).strip() or str(home.get("team", "")).strip()
        away_team = str(away.get("abbr", "")).strip() or str(away.get("team", "")).strip()
        if not home_team or not away_team:
            continue

        event_time = _parse_game_date_epoch(str(home.get("gameDate", "") or ""), game_date)

        home_spread = to_float(home.get(spread_field))
        away_spread = to_float(away.get(spread_field))
        home_ml = _to_nullable_int(home.get(ml_field))
        away_ml = _to_nullable_int(away.get(ml_field))

        ou_val = home.get(ou_field) if home.get(ou_field) is not None else away.get(ou_field)
        ou = to_float(ou_val)

        events.append(
            Event(
                gameID=gid,
                eventTime=event_time,
                game_date=game_date,
                homeTeam=home_team,
                awayTeam=away_team,
                home_spread=home_spread,
                away_spread=away_spread,
                home_ml=home_ml,
                away_ml=away_ml,
                ou=ou,
                source=book.lower(),
            )
        )

    out_obj: Dict[str, Any] = {
        "sport": "NBA",
        "source": "rotowire.com/betting/nba/tables/nba-games-by-market.php",
        "date": game_date,
        "events": [e.to_json() for e in events],
        "fetched_at": _now_utc_iso(),
    }

    _write_json_atomic(out_path, out_obj)
    _maybe_archive_live_rotowire(out_path)
    print(f"[rotowire] wrote {out_path} (events={len(events)}) at {_now_utc_iso()}")

    # Update last-good if we actually have events
    if events:
        _write_json_atomic(last_good_path, out_obj)
        print(f"[rotowire] updated last-good: {last_good_path}")
        return 0

    # -----------------------------
    # Parsed rows but produced zero events -> fallback chain
    # -----------------------------
    _write_debug(
        f"rotowire_zero_events_{game_date}.json",
        json.dumps(rows, ensure_ascii=False)[:200000],
    )

    oa_events = _fetch_oddsapi_events(game_date)
    if oa_events:
        out_obj = {
            "sport": "NBA",
            "source": "the-odds-api.com/v4 (fallback)",
            "date": game_date,
            "events": [e.to_json() for e in oa_events],
            "fetched_at": _now_utc_iso(),
            "note": "FALLBACK_USED: oddsapi (rotowire parsed_zero_events)",
        }
        _write_json_atomic(out_path, out_obj)
        _write_json_atomic(last_good_path, out_obj)
        print(f"[oddsapi] wrote {out_path} (events={len(oa_events)}) using FALLBACK")
        return 0

    lg = _load_last_good(last_good_path)
    if lg is not None:
        lg2 = dict(lg)
        lg2["note"] = "STALE_FALLBACK_USED: parsed_zero_events"
        lg2["fetched_at"] = _now_utc_iso()
        _write_json_atomic(out_path, lg2)
        print(f"[rotowire] wrote {out_path} (events={len(lg2['events'])}) using LAST_GOOD fallback")
        return 0

    if allow_empty:
        return 0
    return 6


if __name__ == "__main__":
    sys.exit(main())